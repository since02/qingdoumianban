"""青豆面板 - yyb-go 微信扫码登录对接（应用宝接口服务）。

对接方式：本面板将 yyb-go 作为「微信/应用宝扫码登录」的凭证后端。
登录流程：
  1) 前端调用 POST /api/yybgo/qr  -> 面板用 Bearer Token 请求 yyb-go 生成二维码
  2) 前端轮询 GET /api/yybgo/qr/<id>/poll
  3) 用户手机确认后，前端调用 POST /api/yybgo/qr/<id>/confirm
     -> 面板向 yyb-go 确认并取得微信账号，验证通过后下发本面板自己的 API Token

本模块同时提供「连接状态 + 已登录微信账号」查询，供独立「微信对接」页面展示。
注意：登录相关接口为公开接口（login 阶段使用）；配置/连接/账号查询接口需鉴权。
"""
import os
import re
import time
import subprocess

import requests
from flask import request, Blueprint
from core import db, config
from routes import json_ok, json_err, auth_required, get_json_body

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HIDDEN_VBS = os.path.join(BASE_DIR, "run_hidden.vbs")
yyb_bp = Blueprint("yybgo", __name__, url_prefix="/api")

YYB_TERMINAL = {"expired", "cancelled", "unknown", "timeout"}
YYB_READY = {"scanned", "confirmed", "authorized", "approved", "ok", "success",
             "done", "ready", "loggedin"}


def _yyb_cfg():
    enabled = (config.get_setting("yybgo_enabled", "0") or "0") == "1"
    host = config.get_setting("yybgo_host", "127.0.0.1") or "127.0.0.1"
    port = config.get_setting("yybgo_port", "8000") or "8000"
    token = config.get_setting("yybgo_token", "") or ""
    return {
        "enabled": enabled,
        "host": host,
        "port": port,
        "url": f"http://{host}:{port}",
        "token": token,
    }


# ============ yyb-go 服务管理（本机程序启动/停止/状态） ============

def _yyb_bin():
    return (config.get_setting("yybgo_bin", "") or "").strip()


def _yyb_args():
    return (config.get_setting("yybgo_args", "") or "").strip()


def _port_listening(port, timeout=1.0):
    import socket
    s = socket.socket()
    s.settimeout(timeout)
    try:
        return s.connect_ex(("127.0.0.1", int(port))) == 0
    except Exception:
        return False
    finally:
        try:
            s.close()
        except Exception:
            pass


def _yyb_procs(bin_path=None):
    """按可执行文件路径或进程名找出 yyb-go 进程。"""
    try:
        import psutil
    except Exception:
        return []
    name_hint = os.path.splitext(os.path.basename(bin_path))[0].lower() if bin_path else "yyb-go"
    out = []
    for p in psutil.process_iter(["pid", "name", "exe", "cmdline"]):
        try:
            exe = (p.info.get("exe") or "")
            name = (p.info.get("name") or "").lower()
            if bin_path and os.path.normcase(exe) == os.path.normcase(bin_path):
                out.append(p)
            elif not bin_path and name.startswith(name_hint):
                out.append(p)
        except Exception:
            continue
    return out


def _hidden_start(cmdline, workdir):
    """通过 run_hidden.vbs 以隐藏窗口、不等待方式启动命令（进程独立于本面板）。"""
    subprocess.run(
        ["wscript.exe", "//nologo", HIDDEN_VBS, cmdline, workdir],
        cwd=BASE_DIR, timeout=30,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )


@yyb_bp.route("/yybgo/service", methods=["GET"])
@auth_required
def yyb_service_status():
    cfg = _yyb_cfg()
    bin_path = _yyb_bin()
    exists = bool(bin_path) and os.path.isfile(bin_path)
    procs = _yyb_procs(bin_path if exists else None)
    listening = _port_listening(cfg["port"])
    health_ok = False
    if listening:
        r, err = _yyb_call("GET", "/health", timeout=4)
        health_ok = (r is not None and r.status_code == 200)
    running = bool(procs) or listening
    return json_ok({
        "bin": bin_path,
        "exists": exists,
        "running": running,
        "pid": procs[0].pid if procs else None,
        "port": cfg["port"],
        "listening": listening,
        "health_ok": health_ok,
        "console_url": cfg["url"],
        "args": _yyb_args(),
    })


@yyb_bp.route("/yybgo/service/start", methods=["POST"])
@auth_required
def yyb_service_start():
    bin_path = _yyb_bin()
    if not bin_path:
        return json_err("请先在下方填写 yyb-go 程序路径（yyb-go.exe 的完整路径）")
    if not os.path.isfile(bin_path):
        return json_err(f"程序不存在: {bin_path}")
    cfg = _yyb_cfg()
    if _port_listening(cfg["port"]):
        return json_err(f"端口 {cfg['port']} 已有服务在监听（可能已启动）")
    workdir = os.path.dirname(bin_path) or "."
    # 日志写到 data/yybgo.log：借助外部隐藏启动器无法直接重定向，改由脚本自身输出兜底；
    # 这里用隐藏启动器的参数形式拼命令行，输出重定向交给 yyb-go 自身（若无输出则静默）。
    extra = _yyb_args()
    cmdline = f'"{bin_path}"' + (f" {extra}" if extra else "")
    try:
        _hidden_start(cmdline, workdir)
    except Exception as e:
        return json_err(f"启动失败: {e}")
    # 等待端口就绪（最多 12s）
    ok = False
    for _ in range(12):
        time.sleep(1)
        if _port_listening(cfg["port"]):
            ok = True
            break
    if ok:
        return json_ok(msg=f"yyb-go 已启动: {cfg['url']}")
    return json_err("已发出启动命令，但端口未就绪。请确认程序路径/参数是否正确（可到 yyb-go 目录查看其日志）")


@yyb_bp.route("/yybgo/service/stop", methods=["POST"])
@auth_required
def yyb_service_stop():
    cfg = _yyb_cfg()
    procs = _yyb_procs(_yyb_bin() or None)
    stopped = []
    for p in procs:
        try:
            p.terminate()
            stopped.append(p.pid)
        except Exception:
            continue
    time.sleep(1.2)
    for p in _yyb_procs(_yyb_bin() or None):
        try:
            p.kill()
        except Exception:
            pass
    # 端口兜底：若仍监听，按占用者结束
    if _port_listening(cfg["port"]):
        try:
            out = subprocess.run(["netstat", "-ano"], capture_output=True, text=True, timeout=20).stdout
            for line in out.splitlines():
                if f":{cfg['port']}" in line and "LISTENING" in line.upper():
                    parts = line.split()
                    if len(parts) >= 5 and parts[-1].isdigit():
                        subprocess.run(["taskkill", "/F", "/PID", parts[-1]],
                                       capture_output=True, timeout=20)
        except Exception:
            pass
    time.sleep(0.5)
    if _port_listening(cfg["port"]):
        return json_err("端口仍被占用，请手动结束对应进程")
    return json_ok(msg=f"yyb-go 已停止（结束进程 {len(stopped) or 0} 个）")


def _yyb_call(method, path, **kw):
    cfg = _yyb_cfg()
    headers = {}
    if cfg["token"]:
        headers["Authorization"] = "Bearer " + cfg["token"]
    timeout = kw.pop("timeout", 60)
    try:
        r = requests.request(method, cfg["url"] + path, headers=headers, timeout=timeout, **kw)
        return r, None
    except Exception as e:
        return None, str(e)


def _extract_list(j):
    """从 yyb-go 响应里尽量取出账号数组（兼容 {data:[...]} / 直接数组 / {accounts:[...]} 等）。"""
    if isinstance(j, list):
        return j
    if isinstance(j, dict):
        for k in ("data", "accounts", "list", "items"):
            v = j.get(k)
            if isinstance(v, list):
                return v
    return []


def _account_label(a):
    if not isinstance(a, dict):
        return "未知账号"
    return (a.get("nickname") or a.get("alias") or a.get("openid")
            or a.get("uin") or "未知账号")


@yyb_bp.route("/yybgo/status", methods=["GET"])
def yyb_status():
    """公开：登录页用来决定是否显示「微信扫码登录」按钮。"""
    return json_ok({"enabled": _yyb_cfg()["enabled"]})


@yyb_bp.route("/yybgo/config", methods=["GET"])
@auth_required
def get_yyb_config():
    cfg = _yyb_cfg()
    return json_ok({
        "enabled": cfg["enabled"],
        "host": cfg["host"],
        "port": cfg["port"],
        "has_token": bool(cfg["token"]),
        "bin": _yyb_bin(),
        "args": _yyb_args(),
    })


@yyb_bp.route("/yybgo/config", methods=["POST"])
@auth_required
def save_yyb_config():
    b = get_json_body()
    enabled = "1" if b.get("enabled") else "0"
    host = (b.get("host") or "127.0.0.1").strip()
    port = str(b.get("port") or "8000").strip()
    token = (b.get("token") or "").strip()
    config.set_setting("yybgo_enabled", enabled)
    config.set_setting("yybgo_host", host)
    config.set_setting("yybgo_port", port)
    if token:
        config.set_setting("yybgo_token", token)
    if "bin" in b:
        config.set_setting("yybgo_bin", (b.get("bin") or "").strip())
    if "args" in b:
        config.set_setting("yybgo_args", (b.get("args") or "").strip())
    return json_ok(msg="已保存 yyb-go 配置")


@yyb_bp.route("/yybgo/connection", methods=["GET"])
@auth_required
def yyb_connection():
    """连接状态 + 已登录微信账号列表（供「微信对接」页面展示）。"""
    cfg = _yyb_cfg()
    if not cfg["enabled"]:
        return json_ok({"enabled": False, "connected": False, "accounts": [],
                        "msg": "未启用 yyb-go 对接"})
    if not cfg["token"]:
        return json_ok({"enabled": True, "connected": False, "accounts": [],
                        "msg": "已启用但未配置 API Token（YYB_API_TOKEN）"})
    r, err = _yyb_call("GET", "/health", timeout=5)
    connected = (r is not None and r.status_code == 200)
    if not connected and r is not None:
        err = err or ("HTTP %s" % r.status_code)
    accounts = []
    account_count = 0
    if connected:
        ar, aerr = _yyb_call("GET", "/accounts", timeout=10)
        if ar and ar.status_code == 200:
            try:
                accounts = _extract_list(ar.json())
                account_count = len(accounts)
            except Exception:
                accounts = []
                account_count = 0
    return json_ok({
        "enabled": True,
        "host": cfg["host"],
        "port": cfg["port"],
        "url": cfg["url"],
        "connected": connected,
        "error": err,
        "accounts": [{
            "label": _account_label(a),
            "nickname": a.get("nickname") if isinstance(a, dict) else "",
            "openid": a.get("openid") if isinstance(a, dict) else "",
            "status": (a.get("status") if isinstance(a, dict) else "") or "",
        } for a in accounts],
        "account_count": account_count,
    })


@yyb_bp.route("/yybgo/health", methods=["GET"])
@auth_required
def yyb_health():
    cfg = _yyb_cfg()
    if not cfg["url"]:
        return json_ok({"ok": False, "msg": "未配置服务地址"})
    r, err = _yyb_call("GET", "/health")
    if err:
        return json_ok({"ok": False, "msg": err})
    return json_ok({"ok": r.status_code == 200, "status": r.status_code})


@yyb_bp.route("/yybgo/qr", methods=["POST"])
def create_qr():
    cfg = _yyb_cfg()
    if not cfg["enabled"] or not cfg["url"]:
        return json_err("微信扫码登录未启用或未配置 yyb-go")
    r, err = _yyb_call("POST", "/qr?as_base64=true")
    if err:
        return json_err("无法连接 yyb-go: " + err)
    if r.status_code != 200:
        return json_err("yyb-go 返回 HTTP %s" % r.status_code)
    data = (r.json() or {}).get("data", {})
    img = data.get("image_base64")
    if not img:
        return json_err("yyb-go 未返回二维码")
    # 补前缀：部分 yyb-go 返回裸 base64，前端 <img src> 需 data:image/png;base64, 前缀才能渲染
    if not img.startswith("data:"):
        img = "data:image/png;base64," + img
    return json_ok({"session_id": data.get("session_id"), "image": img,
                    "status": data.get("status", "")})


@yyb_bp.route("/yybgo/qr/<sid>/poll", methods=["GET"])
def poll_qr(sid):
    cfg = _yyb_cfg()
    if not cfg["enabled"] or not cfg["url"]:
        return json_err("微信扫码登录未启用")
    r, err = _yyb_call("GET", "/qr/%s/poll" % sid)
    if err:
        return json_err("无法连接 yyb-go: " + err)
    data = (r.json() or {}).get("data", {}) if r.status_code == 200 else {}
    status = (data.get("status") or "").lower()
    expired = status in YYB_TERMINAL
    ready = status in YYB_READY
    return json_ok({"status": data.get("status", ""), "expired": expired, "ready": ready})


@yyb_bp.route("/yybgo/qr/<sid>/confirm", methods=["POST"])
def confirm_qr(sid):
    cfg = _yyb_cfg()
    if not cfg["enabled"] or not cfg["url"]:
        return json_err("微信扫码登录未启用")
    r, err = _yyb_call("POST", "/qr/%s/confirm" % sid)
    if err:
        return json_err("无法连接 yyb-go: " + err)
    if r.status_code == 200:
        data = (r.json() or {}).get("data", {})
        # 微信账号已捕获 -> 视为本面板登录成功，下发面板自身 token
        return json_ok({"ready": True, "token": config.get_api_token(), "account": data})
    if r.status_code == 409:
        # 登录缓冲尚未就绪（用户尚未在手机端确认），前端继续轮询
        return json_ok({"ready": False, "status": "not_ready"})
    return json_err("确认失败: yyb-go HTTP %s" % r.status_code)
