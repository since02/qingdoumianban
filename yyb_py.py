#!/usr/bin/env python3
"""yyb_py.py - yyb-go 的纯 Python 替代（京东扫码登录兼容服务）。

与面板同仓库，直接运行即可（无需 Go、无需编译）：
    python yyb_py.py                    # 默认 127.0.0.1:8899
    python yyb_py.py --host 0.0.0.0 --port 8899

提供的 HTTP API（与 yyb-go 对齐 + 京东扩展）：
    GET  /health                        健康检查
    GET  /accounts                      已保存的京东账号列表
    POST /qr?as_base64=true             生成京东扫码二维码 {session_id, image_base64}
    GET  /qr/<sid>/poll                 轮询 {status}  waiting/scanned/confirmed/expired/success
    POST /qr/<sid>/confirm              确认换 Cookie {pt_pin, cookie, ...}
    POST /jd/qr                         同 /qr
    GET  /jd/qr/<sid>/poll              同 /qr/<sid>/poll
    POST /jd/qr/<sid>/confirm           同 /qr/<sid>/confirm
    POST /jd/cookie/check               校验 cookie {cookie} -> {valid, nickname}
    DELETE /jd/account/<pt_pin>         删除账号记录

账号持久化到 data/yybpy_accounts.json。
依赖：requests（面板 venv 自带）。
"""
import argparse
import base64
import json
import os
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from flask import Flask, jsonify, request

from core import jdqr

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ACC_FILE = os.path.join(BASE_DIR, "data", "yybpy_accounts.json")

app = Flask("yyb_py")


# ============ 账号持久化 ============
_acc_lock = threading.Lock()


def _load_accounts():
    try:
        with open(ACC_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def _save_accounts(accs):
    os.makedirs(os.path.dirname(ACC_FILE), exist_ok=True)
    with open(ACC_FILE, "w", encoding="utf-8") as f:
        json.dump(accs, f, ensure_ascii=False, indent=2)


def _upsert_account(pin, nickname, cookie):
    with _acc_lock:
        accs = _load_accounts()
        now = time.strftime("%Y-%m-%d %H:%M:%S")
        for a in accs:
            if a.get("pt_pin") == pin:
                a.update({"cookie": cookie, "nickname": nickname or a.get("nickname", ""),
                          "status": "ok", "last_update": now, "errmsg": ""})
                break
        else:
            accs.insert(0, {"ref": "jd_" + (pin or str(int(time.time()))), "pt_pin": pin,
                            "nickname": nickname or pin, "cookie": cookie, "status": "ok",
                            "last_update": now, "expire_at": time.strftime(
                                "%Y-%m-%d %H:%M:%S", time.localtime(time.time() + 30 * 86400)),
                            "errmsg": ""})
        _save_accounts(accs)


# ============ 响应包装（与 yyb-go 一致的 {code, data, msg}） ============
def ok(data=None, msg=""):
    return jsonify({"code": 0, "data": data or {}, "msg": msg})


def err(msg, code=1):
    return jsonify({"code": code, "data": {}, "msg": msg})


# ============ 路由 ============
@app.get("/health")
def health():
    return ok({"status": "ok", "mode": "builtin", "service": "yyb_py",
               "time": time.strftime("%Y-%m-%d %H:%M:%S")})


@app.get("/accounts")
def accounts():
    accs = _load_accounts()
    out = [{"ref": a.get("ref"), "nickname": a.get("nickname"), "pt_pin": a.get("pt_pin"),
            "status": a.get("status"), "last_update": a.get("last_update")} for a in accs]
    return ok({"accounts": out, "list": out, "total": len(out)})


def _create_qr():
    try:
        sid, img = jdqr.create_session()
    except Exception as e:
        return err("生成二维码失败: %s" % e)
    data = {"session_id": sid, "image_base64": img, "status": "waiting"}
    if request.args.get("as_base64") in ("1", "true"):
        data["image_base64"] = "data:image/png;base64," + img
    return ok(data)


def _poll(sid):
    try:
        return ok(jdqr.poll_session(sid))
    except Exception as e:
        return err(str(e))


def _confirm(sid):
    try:
        res = jdqr.confirm_session(sid)
    except Exception as e:
        jdqr.drop_session(sid)
        return err(str(e))
    jdqr.drop_session(sid)
    cookie = res.get("cookie") or ""
    pin = res.get("pt_pin") or ""
    if cookie and pin:
        _upsert_account(pin, res.get("nickname") or "", cookie)
    return ok({"pt_pin": pin, "nickname": res.get("nickname") or "",
               "cookie": cookie, "status": "success"})


@app.post("/qr")
def qr_create():
    return _create_qr()


@app.get("/qr/<sid>/poll")
def qr_poll(sid):
    return _poll(sid)


@app.post("/qr/<sid>/confirm")
def qr_confirm(sid):
    return _confirm(sid)


@app.post("/jd/qr")
def jd_qr_create():
    return _create_qr()


@app.get("/jd/qr/<sid>/poll")
def jd_qr_poll(sid):
    return _poll(sid)


@app.post("/jd/qr/<sid>/confirm")
def jd_qr_confirm(sid):
    return _confirm(sid)


@app.post("/jd/cookie/check")
def jd_cookie_check():
    b = request.get_json(silent=True) or {}
    cookie = b.get("cookie") or ""
    if not cookie:
        return err("缺少 cookie")
    valid, nick = jdqr.verify_cookie(cookie)
    if valid is None:
        return err("网络原因无法校验")
    return ok({"valid": bool(valid), "nickname": nick})


@app.delete("/jd/account/<pin>")
def jd_account_del(pin):
    with _acc_lock:
        accs = [a for a in _load_accounts() if a.get("pt_pin") != pin]
        _save_accounts(accs)
    return ok(msg="已删除")


def main():
    ap = argparse.ArgumentParser(description="yyb-go 的纯 Python 替代（京东扫码登录）")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8899)
    args = ap.parse_args()
    print("[yyb_py] listening on http://%s:%d  (mode=builtin, 京东扫码)" % (args.host, args.port))
    app.run(host=args.host, port=args.port, threaded=True, debug=False, use_reloader=False)


if __name__ == "__main__":
    main()
