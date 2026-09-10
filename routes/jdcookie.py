"""青豆面板 - 京东 Cookie 获取模块。

登录源：
  builtin（默认，唯一）：纯 Python 京东官方扫码登录（core/jdqr.py），无需任何外部程序。

获取到的 pt_key/pt_pin 写入面板环境变量（默认 JD_COOKIE），供青龙类脚本消费。
"""
import re
import json
import time
import urllib.parse
import requests
from flask import request
from core import db
from core.jdqr import (create_session, poll_session, confirm_session,
                       drop_session, verify_cookie)
from routes import bp, json_ok, json_err, auth_required, role_required, get_json_body

# 京东小程序 appid（微信内京东购物/京东小程序）
JD_APPID = "wx91d27dbf599dff74"
# 京东 PT（passport）OAuth appid（兜底链使用）
JD_PT_APPID = "wx2f5d8f9715c59d10"
JD_PT_APP = "300"
JD_PT_RETURN_URL = "https://my.m.jd.com/account/index.html"
JD_ALLOWED = ("jd.com", ".jd.com", "jd.hk", ".jd.hk", "3.cn", ".3.cn")

UA_WX = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 "
    f"MicroMessenger/8.0.49 NetType/WIFI Language/zh_CN miniProgram/{JD_APPID}"
)


# ============ 配置 ============
def _jd_cfg():
    row = db.query_one("SELECT * FROM jdcookie_config WHERE id=1")
    if not row:
        return {
            "jd_appid": JD_APPID, "jd_pt_appid": JD_PT_APPID,
            "cookie_env_name": "JD_COOKIE", "cookie_mode": "pt",
            "login_mode": "auto", "auto_refresh_cron": "0 */2 * * *", "auto_refresh": 0,
        }
    return dict(row)


def _ensure_cfg():
    if not db.query_one("SELECT 1 FROM jdcookie_config WHERE id=1"):
        db.execute(
            "INSERT INTO jdcookie_config(id,jd_appid,jd_pt_appid,cookie_env_name,cookie_mode,login_mode,auto_refresh_cron,auto_refresh) "
            "VALUES(1,?,?,?,?,?,?,0)",
            (JD_APPID, JD_PT_APPID, "JD_COOKIE", "pt", "auto", "0 */2 * * *"),
        )


# ============ 登录源 ============
def _login_source():
    """目前仅支持 builtin（纯 Python 京东官方扫码），无需外部程序。"""
    return "builtin"


def config_get(key, default=""):
    from core import config
    return config.get_setting(key, default)


# ============ 工具 ============
def _unwrap(payload):
    """兼容 {code,data,msg} 业务响应。"""
    if isinstance(payload, dict) and "code" in payload and "data" in payload:
        code = str(payload.get("code"))
        if code not in {"0", "200", "201"}:
            raise RuntimeError(payload.get("msg") or ("业务状态异常：" + code))
        data = payload["data"]
        if isinstance(data, dict):
            return data
        if isinstance(data, str) and data.strip().startswith(("{", "[")):
            try:
                return json.loads(data)
            except Exception:
                pass
        return {"value": data}
    return payload


def _nested(payload, keys):
    wanted = {str(k).lower() for k in keys}
    if isinstance(payload, dict):
        for k, v in payload.items():
            if (k in keys or str(k).lower() in wanted) and v not in (None, ""):
                return v
        for v in payload.values():
            found = _nested(v, keys)
            if found not in (None, ""):
                return found
    elif isinstance(payload, list):
        for v in payload:
            found = _nested(v, keys)
            if found not in (None, ""):
                return found
    return None


def _nested_str(payload, keys):
    v = _nested(payload, keys)
    return v.strip() if isinstance(v, str) else ""


def normalize_pt_cookie(cookie):
    """从 requests CookieJar 或文本中提取 pt_key;pt_pin;。"""
    if hasattr(cookie, "__iter__") and not isinstance(cookie, (str, bytes)):
        try:
            vals = {}
            for c in cookie:
                if getattr(c, "name", "") in ("pt_key", "pt_pin") and getattr(c, "value", None):
                    vals[c.name] = c.value
            if vals.get("pt_key") and vals.get("pt_pin"):
                return f"pt_key={vals['pt_key']};pt_pin={vals['pt_pin']};"
            return ""
        except Exception:
            pass
    text = str(cookie or "")
    k = re.search(r"(?:^|[;?,\s])pt_key=([^;?,\s]+)", text)
    p = re.search(r"(?:^|[;?,\s])pt_pin=([^;?,\s]+)", text)
    if k and p:
        return f"pt_key={k.group(1)};pt_pin={p.group(1)};"
    return ""


def _cookie_from_payload(payload):
    """京东有时把 pt_key/pt_pin 放在 JSON 响应体字段，而非 Set-Cookie 头（可能嵌套）。"""
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except Exception:
            return normalize_pt_cookie(payload)
    if not isinstance(payload, dict):
        return normalize_pt_cookie(payload)
    pt_key = _nested(payload, ("pt_key", "ptKey"))
    pt_pin = _nested(payload, ("pt_pin", "ptPin"))
    if pt_key and pt_pin:
        return f"pt_key={str(pt_key)};pt_pin={str(pt_pin)};"
    return ""


def _pin_from(cookie):
    m = re.search(r"(?:^|[;,\s])pt_pin=([^;,\s]+)", normalize_pt_cookie(cookie))
    return m.group(1) if m else ""


# ============ 写入环境变量 ============
def _write_env(cookie, pin, remark):
    cfg = _jd_cfg()
    name = cfg.get("cookie_env_name") or "JD_COOKIE"
    cookie_pure = normalize_pt_cookie(cookie)
    value = cookie if cfg.get("cookie_mode") == "all" else cookie_pure
    existing = db.query("SELECT * FROM environments WHERE name=?", (name,))
    for e in existing:
        if normalize_pt_cookie(e["value"]) == cookie_pure:
            db.execute("UPDATE environments SET value=?,remarks=?,status=1 WHERE id=?",
                       (value, remark or pin, e["id"]))
            return "update"
    if existing:
        db.execute("INSERT INTO environments(name,value,remarks,status) VALUES(?,?,?,?)",
                   (name, value, remark or pin, 1))
        return "create"
    db.execute("INSERT INTO environments(name,value,remarks,status) VALUES(?,?,?,?)",
               (name, value, remark or pin, 1))
    return "create"


def _expire_after(days=30):
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(time.time() + days * 86400))


def _store_account(ref, name, cookie, ok, errmsg="", openid=""):
    pin = _pin_from(cookie) if ok else ""
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    status = "ok" if ok else "error"
    db.execute(
        "INSERT INTO jdcookie_accounts(ref,name,openid,pt_pin,cookie,status,last_update,expire_at,errmsg) "
        "VALUES(?,?,?,?,?,?,?,?,?) "
        "ON CONFLICT(ref) DO UPDATE SET name=?,openid=?,pt_pin=?,cookie=?,status=?,last_update=?,expire_at=?,errmsg=?",
        (ref, name, openid, pin, cookie if ok else "", status, now, _expire_after(30) if ok else "", errmsg,
         name, openid, pin, cookie if ok else "", status, now, _expire_after(30) if ok else "", errmsg),
    )


# ============ 路由 ============
@bp.route("/jdcookie/config", methods=["GET"])
@auth_required
def jd_config_get():
    _ensure_cfg()
    cfg = _jd_cfg()
    return json_ok({**cfg, "login_source": _login_source()})


@bp.route("/jdcookie/config", methods=["POST"])
@role_required("admin")
def jd_config_set():
    b = get_json_body()
    _ensure_cfg()
    from core import config
    db.execute(
        "UPDATE jdcookie_config SET jd_appid=?,jd_pt_appid=?,cookie_env_name=?,cookie_mode=?,login_mode=?,auto_refresh_cron=?,auto_refresh=? WHERE id=1",
        (b.get("jd_appid", JD_APPID), b.get("jd_pt_appid", JD_PT_APPID),
         (b.get("cookie_env_name") or "JD_COOKIE").strip() or "JD_COOKIE",
         b.get("cookie_mode", "pt"), b.get("login_mode", "auto"),
         (b.get("auto_refresh_cron") or "0 */2 * * *").strip() or "0 */2 * * *",
         1 if b.get("auto_refresh") else 0))
    return json_ok(msg="已保存京东 Cookie 配置")


@bp.route("/jdcookie/connection", methods=["GET"])
@auth_required
def jd_connection():
    """连接状态与账号列表。builtin 模式直接返回本地账号，无需外部服务。"""
    rows = db.query("SELECT * FROM jdcookie_accounts ORDER BY id DESC")
    accs = []
    for r in rows:
        d = dict(r)
        accs.append({
            "ref": d.get("ref"), "label": d.get("name") or d.get("pt_pin") or d.get("ref"),
            "nickname": d.get("name") or "", "openid": d.get("openid") or "",
            "status": "alive" if d.get("status") == "ok" else "dead",
        })
    return json_ok({"enabled": True, "connected": True, "mode": "builtin",
                    "url": "内置京东扫码（无需外部服务）",
                    "accounts": accs, "account_count": len(accs)})


# ============ 内置扫码登录（builtin，纯 Python） ============
@bp.route("/jdcookie/qr", methods=["POST"])
@auth_required
def jd_qr_create():
    try:
        sid, img = create_session()
    except Exception as e:
        return json_err("生成京东二维码失败：" + str(e))
    return json_ok({"session_id": sid, "image": "data:image/png;base64," + img,
                    "status": "waiting"})


@bp.route("/jdcookie/qr/<sid>/poll", methods=["GET"])
@auth_required
def jd_qr_poll(sid):
    try:
        st = poll_session(sid)
    except Exception as e:
        return json_err(str(e))
    return json_ok(st)


@bp.route("/jdcookie/qr/<sid>/confirm", methods=["POST"])
@auth_required
def jd_qr_confirm(sid):
    try:
        res = confirm_session(sid)
    except Exception as e:
        # 会话已结束的清理
        drop_session(sid)
        return json_err(str(e))
    cookie = res.get("cookie") or ""
    pin = res.get("pt_pin") or ""
    drop_session(sid)
    if not cookie:
        return json_err("未获取到 Cookie")
    nickname = res.get("nickname") or pin
    ref = "jd_" + (pin or time.strftime("%Y%m%d%H%M%S"))
    action = _write_env(cookie, pin, nickname or pin)
    _store_account(ref, nickname or pin or "京东账号", cookie, True,
                   errmsg="", openid=ref)
    return json_ok({"pt_pin": pin, "nickname": nickname, "action": action},
                   msg="京东 Cookie 已获取并写入「%s」" % (_jd_cfg().get("cookie_env_name") or "JD_COOKIE"))


@bp.route("/jdcookie/check", methods=["POST"])
@auth_required
def jd_check_one():
    """校验某账号 Cookie 有效性（builtin 模式下也可用）。"""
    b = get_json_body()
    ref = (b.get("ref") or "").strip()
    if not ref:
        return json_err("缺少 ref")
    row = db.query_one("SELECT * FROM jdcookie_accounts WHERE ref=?", (ref,))
    if not row:
        return json_err("账户不存在")
    ok, nick = verify_cookie(row["cookie"] or "")
    if ok is None:
        return json_err("网络原因无法校验（京东接口不可达）")
    if ok:
        db.execute("UPDATE jdcookie_accounts SET status='ok',errmsg='' WHERE ref=?", (ref,))
        if nick:
            db.execute("UPDATE jdcookie_accounts SET name=? WHERE ref=? AND (name IS NULL OR name='')", (nick, ref))
        return json_ok({"valid": True, "nickname": nick}, msg="Cookie 有效 ✅")
    db.execute("UPDATE jdcookie_accounts SET status='error',errmsg='Cookie 已失效，请重新扫码' WHERE ref=?", (ref,))
    return json_ok({"valid": False}, msg="Cookie 已失效 ❌ 请重新扫码登录")


@bp.route("/jdcookie/accounts", methods=["GET"])
@auth_required
def jd_accounts():
    rows = db.query("SELECT * FROM jdcookie_accounts ORDER BY id DESC")
    return json_ok([dict(r) for r in rows])


@bp.route("/jdcookie/refresh", methods=["POST"])
@auth_required
def jd_refresh():
    return json_err("内置模式不支持静默刷新：京东 Cookie 约 30 天有效，失效后请点「＋ 扫码登录京东」重新获取")


@bp.route("/jdcookie/refresh_all", methods=["POST"])
@auth_required
def jd_refresh_all():
    """对微信账号列表中的每个账号尝试刷新（供自动定时任务/一键全刷）。
    builtin 模式下等价于「全量校验」。"""
    if _login_source() == "builtin":
        rows = db.query("SELECT * FROM jdcookie_accounts WHERE cookie!=''")
        if not rows:
            return json_err("暂无京东账号，请先扫码登录")
        results = []
        for row in rows:
            ok, _nick = verify_cookie(row["cookie"] or "")
            if ok is True:
                db.execute("UPDATE jdcookie_accounts SET status='ok',errmsg='' WHERE ref=?", (row["ref"],))
                results.append({"ref": row["ref"], "ok": True, "pin": row["pt_pin"]})
            elif ok is False:
                db.execute("UPDATE jdcookie_accounts SET status='error',errmsg='Cookie 已失效，请重新扫码' WHERE ref=?", (row["ref"],))
                results.append({"ref": row["ref"], "ok": False, "msg": "已失效"})
            else:
                results.append({"ref": row["ref"], "ok": False, "msg": "网络原因无法校验"})
        good = sum(1 for x in results if x["ok"])
        return json_ok({"results": results}, msg="校验完成：有效 %d / 共 %d" % (good, len(results)))


@bp.route("/jdcookie/account/delete", methods=["POST"])
@auth_required
def jd_account_del():
    b = get_json_body()
    ref = (b.get("ref") or "").strip()
    if not ref:
        return json_err("缺少 ref")
    db.execute("DELETE FROM jdcookie_accounts WHERE ref=?", (ref,))
    return json_ok(msg="已删除账户记录")


# ============ 供 scheduler 调用的自动刷新入口 ============
def auto_refresh_job():
    """被 scheduler 定时调用。
    builtin 模式：逐个校验已存 Cookie 有效性，失效即标记（京东 cookie 无法静默续期，需重新扫码）。"""
    try:
        cfg = _jd_cfg()
        if not cfg.get("auto_refresh"):
            return
        if _login_source() == "builtin":
            rows = db.query("SELECT * FROM jdcookie_accounts WHERE cookie!='' AND status='ok'")
            for row in rows:
                ok, _nick = verify_cookie(row["cookie"] or "")
                if ok is True:
                    db.execute("UPDATE jdcookie_accounts SET status='ok',errmsg='' WHERE ref=?",
                               (row["ref"],))
                elif ok is False:
                    db.execute("UPDATE jdcookie_accounts SET status='error',"
                               "errmsg='自动检查发现 Cookie 已失效，请重新扫码' WHERE ref=?",
                               (row["ref"],))
            return
    except Exception:
        pass
