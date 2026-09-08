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
import requests
from flask import request, Blueprint
from core import db, config
from routes import json_ok, json_err, auth_required, get_json_body

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
