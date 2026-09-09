"""青豆面板 - 京东 Cookie 获取模块。

提供两种登录源：
  builtin（默认）：纯 Python 京东官方扫码登录（core/jdqr.py），无需任何外部程序；
  yybgo：外部 yyb-go 微信登录态驱动京东小程序登录（需本机 yyb-go.exe）。

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
from routes.yybgo import _yyb_cfg, _yyb_call

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
    """builtin（默认，纯 Python 扫码）或 yybgo（外部 yyb-go）。"""
    return (config_get("jd_login_source") or "builtin").strip() or "builtin"


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


# ============ yyb-go -> 京东登录 ============
def get_yyb_code(ref, app_id):
    r, err = _yyb_call("POST", "/wxapp/getCode", json={"ref": ref, "app_id": app_id})
    if err or not r or r.status_code != 200:
        raise RuntimeError("yyb-go getCode 失败：" + (err or ("HTTP %s" % (r.status_code if r else "?"))))
    try:
        payload = _unwrap(r.json())
    except Exception:
        raise RuntimeError("yyb-go getCode 返回非 JSON")
    openid = _nested_str(payload, ("openid", "openId", "open_id"))
    code = _nested_str(payload, ("wxCode", "wx_code", "jsCode", "jscode", "code"))
    if len(code) < 8 or code in {"0", "200", "201"}:
        raise RuntimeError("yyb-go getCode 未返回有效一次性 code")
    return code, openid


def _get_user_info(ref):
    """full 模式需要用户信息，调 yyb-go operateWxData；失败降级为 code-only。"""
    try:
        r, err = _yyb_call("POST", "/wxapp/operateWxData",
                           json={"ref": ref, "app_id": JD_APPID,
                                 "payload": {"api_name": "getUserInfo", "data": {"withCredentials": True}, "env": 1}})
        if err or not r or r.status_code != 200:
            return None
        res = _unwrap(r.json())
        raw = _nested(res, ("rawData", "raw_data")) or _nested(res, ("userInfo", "user_info"))
        if isinstance(raw, dict):
            raw = json.dumps(raw, ensure_ascii=False, separators=(",", ":"))
        return {
            "rawData": str(raw or ""),
            "signature": _nested_str(res, ("signature",)),
            "encrytData": _nested_str(res, ("encryptedData", "encrytData", "encrypted_data")),
            "iv": _nested_str(res, ("iv",)),
            "openid": _nested_str(res, ("openid", "openId", "open_id")),
        }
    except Exception:
        return None


def _login_headers():
    return {
        "User-Agent": UA_WX,
        "Referer": f"https://servicewechat.com/{JD_APPID}/873/page-frame.html",
        "Accept": "application/json,text/plain,*/*",
    }


def call_login_lt(session, code, user_info=None):
    params = {
        "appid": JD_APPID, "code": code, "type": "silent",
        "isPopup": "false", "isIgnoreCookie": "false", "isOfficialPin": "false",
        "loginColor": "{}", "returnUrl": "pages/my/index/index",
        "deviceName": "iPhone", "deviceOS": "iOS", "deviceOSVersion": "17.0",
        "deviceVersion": "8.0.49", "g_tk": "0", "g_ty": "ls",
    }
    if user_info:
        params.update({
            "rawData": user_info.get("rawData", ""),
            "signature": user_info.get("signature", ""),
            "encrytData": user_info.get("encrytData", ""),
            "encryptedData": user_info.get("encrytData", ""),
            "iv": user_info.get("iv", ""),
            "ou": user_info.get("openid", ""),
        })
    url = "https://wq.jd.com/mlogin/wxapp/login_lt?" + urllib.parse.urlencode(params)
    resp = session.get(url, headers=_login_headers(), timeout=30, allow_redirects=True)
    try:
        pj = resp.json()
    except Exception:
        pj = {}
    cookie = normalize_pt_cookie(session.cookies)
    if not cookie:
        cookie = _cookie_from_payload(pj)
    if not cookie:
        cookie = normalize_pt_cookie(dict(resp.headers).get("Set-Cookie", ""))
    return cookie or "", pj


def _pt_headers():
    return {
        "User-Agent": (
            "Mozilla/5.0 (Linux; Android 10; Pixel 4 XL) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/126.0.0.0 Mobile Safari/537.36 "
            "MicroMessenger/7.0.20.1781 NetType/WIFI MiniProgramEnv/Windows WindowsWechat/WMPF"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9",
    }


def _jd_allowed(url):
    p = urllib.parse.urlparse(url)
    host = (p.hostname or "").lower()
    return p.scheme == "https" and any(host == h or host.endswith(h) for h in JD_ALLOWED)


def jd_pt_cookie_login(code):
    """PT OAuth 兜底链：用 PT appid 的 code 走 plogin 跳转拿 pt_key/pt_pin。"""
    session = requests.Session()
    login_url = "https://plogin.m.jd.com/user/login.action?" + urllib.parse.urlencode(
        {"appid": JD_PT_APP, "returnurl": JD_PT_RETURN_URL})
    resp = session.get(login_url, headers=_pt_headers(), timeout=30, allow_redirects=False)
    location = resp.headers.get("Location")
    if not location or resp.status_code < 300 or resp.status_code >= 400:
        raise RuntimeError("JD PT login.action 未跳转：HTTP %s" % resp.status_code)
    oauth = urllib.parse.urlparse(urllib.parse.urljoin(login_url, location))
    q = urllib.parse.parse_qs(oauth.query, keep_blank_values=True)
    if q.get("appid", [""])[0] != JD_PT_APPID:
        raise RuntimeError("JD PT OAuth appid 不匹配")
    redirect_uri = q.get("redirect_uri", [""])[0]
    state = q.get("state", [""])[0]
    if not redirect_uri or not state:
        raise RuntimeError("JD PT OAuth 缺少 redirect_uri/state")
    cb = urllib.parse.urlparse(redirect_uri)
    cbq = urllib.parse.parse_qsl(cb.query, keep_blank_values=True)
    cbq.extend([("code", code), ("state", state)])
    current = urllib.parse.urlunparse(cb._replace(query=urllib.parse.urlencode(cbq)))
    for _ in range(8):
        if not _jd_allowed(current):
            raise RuntimeError("JD PT 刷新地址超出允许域名")
        r = session.get(current, headers=_pt_headers(), timeout=30, allow_redirects=False)
        cookie = normalize_pt_cookie(session.cookies)
        if not cookie:
            cookie = _cookie_from_payload(dict(r.headers).get("Set-Cookie", ""))
        if cookie:
            return cookie
        loc = r.headers.get("Location")
        if (not loc) or (r.status_code not in {200, 301, 302, 303, 307, 308}):
            break
        current = urllib.parse.urljoin(current, loc)
    raise RuntimeError("JD PT 刷新链未返回 pt_key/pt_pin")


def attempt_code_login(ref, full=False):
    cfg = _jd_cfg()
    code, _openid = get_yyb_code(ref, cfg.get("jd_appid") or JD_APPID)
    session = requests.Session()
    user_info = _get_user_info(ref) if full else None
    cookie, _pj = call_login_lt(session, code, user_info)
    if not cookie and cfg.get("cookie_mode") in ("pt", "all"):
        try:
            cookie = jd_pt_cookie_login(get_yyb_code(ref, cfg.get("jd_pt_appid") or JD_PT_APPID)[0])
        except Exception:
            pass
    return cookie


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
    yyb = _yyb_cfg()
    return json_ok({**cfg, "login_source": _login_source(),
                    "yyb_enabled": yyb.get("enabled"), "yyb_url": yyb.get("url")})


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
    if "login_source" in b:
        src = "yybgo" if str(b.get("login_source")).strip() == "yybgo" else "builtin"
        config.set_setting("jd_login_source", src)
    return json_ok(msg="已保存京东 Cookie 配置")


@bp.route("/jdcookie/connection", methods=["GET"])
@auth_required
def jd_connection():
    """连接状态与账号列表。builtin 模式直接返回本地账号，无需外部服务。"""
    src = _login_source()
    if src == "builtin":
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
    from routes.yybgo import yyb_connection as _yc
    resp = _yc()
    return resp


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
    b = get_json_body()
    ref = (b.get("ref") or "").strip()
    name = (b.get("name") or "").strip()
    if not ref:
        return json_err("缺少微信账号 ref")
    if _login_source() == "builtin":
        return json_err("内置模式不支持静默刷新：京东 Cookie 约 30 天有效，失效后请点「扫码登录」重新获取")
    cfg = _jd_cfg()
    full = cfg.get("login_mode") == "full"
    try:
        cookie = attempt_code_login(ref, full=full)
    except Exception as e:
        _store_account(ref, name, "", False, str(e))
        return json_err("获取失败：" + str(e))
    if not normalize_pt_cookie(cookie):
        _store_account(ref, name, "", False, "登录成功但未解析到 pt_key/pt_pin")
        return json_err("登录成功但未能解析出 pt_key/pt_pin")
    pin = _pin_from(cookie)
    action = _write_env(cookie, pin, name or pin)
    _store_account(ref, name, cookie, True)
    return json_ok({"action": action, "pin": pin, "preview": normalize_pt_cookie(cookie)[:48] + "…"},
                   msg="京东 Cookie 已获取并写入「%s」" % (_jd_cfg().get("cookie_env_name") or "JD_COOKIE"))


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
    from routes.yybgo import _extract_list
    r, err = _yyb_call("GET", "/accounts", timeout=10)
    if err or not r or r.status_code != 200:
        return json_err("无法获取微信账号：" + (err or "HTTP %s" % (r.status_code if r else "?")))
    accounts = _extract_list(r.json())
    results = []
    for a in accounts:
        if not isinstance(a, dict):
            continue
        ref = str(a.get("ref") or a.get("openid") or a.get("openId") or a.get("id") or a.get("uin") or "").strip()
        if not ref:
            continue
        label = a.get("nickname") or a.get("alias") or a.get("openid") or "账号"
        try:
            cookie = attempt_code_login(ref, full=(_jd_cfg().get("login_mode") == "full"))
            if not normalize_pt_cookie(cookie):
                _store_account(ref, label, "", False, "未解析到 pt_key/pt_pin")
                results.append({"ref": ref, "ok": False, "msg": "未解析到 cookie"})
                continue
            pin = _pin_from(cookie)
            _write_env(cookie, pin, label or pin)
            _store_account(ref, label, cookie, True)
            results.append({"ref": ref, "ok": True, "pin": pin})
        except Exception as e:
            _store_account(ref, label, "", False, str(e))
            results.append({"ref": ref, "ok": False, "msg": str(e)})
        time.sleep(1)
    ok = sum(1 for x in results if x["ok"])
    return json_ok({"results": results}, msg="完成：成功 %d / 共 %d" % (ok, len(results)))


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
    builtin 模式：逐个校验已存 Cookie 有效性，失效即标记（京东 cookie 无法静默续期，需重新扫码）；
    yybgo 模式：对每个微信账号重新走 code 登录刷新 cookie。"""
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
        r, err = _yyb_call("GET", "/accounts", timeout=10)
        if err or not r or r.status_code != 200:
            return
        from routes.yybgo import _extract_list
        for a in _extract_list(r.json()):
            if not isinstance(a, dict):
                continue
            ref = str(a.get("ref") or a.get("openid") or a.get("openId") or a.get("id") or a.get("uin") or "").strip()
            if not ref:
                continue
            label = a.get("nickname") or a.get("alias") or a.get("openid") or "账号"
            try:
                cookie = attempt_code_login(ref, full=(cfg.get("login_mode") == "full"))
                if normalize_pt_cookie(cookie):
                    pin = _pin_from(cookie)
                    _write_env(cookie, pin, label or pin)
                    _store_account(ref, label, cookie, True)
            except Exception:
                pass
    except Exception:
        pass
