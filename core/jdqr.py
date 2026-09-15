"""京东扫码登录引擎（纯 Python，零外部依赖）。

替代 yyb-go 的最终产出（pt_key/pt_pin）：
  1) GET  qr.m.jd.com/show            -> 二维码图片 + wlfstk_smdl token
  2) 轮询 GET qr.m.jd.com/check       -> 201 未扫 / 202 已扫待确认 / 203 过期 / 200 成功(ticket)
  3) GET  passport.jd.com/uc/qrCodeTicketValidation?t=<ticket>
                                    -> returnCode=0 时经 Set-Cookie 下发 pt_key/pt_pin

接口形态与 yyb-go 对齐（create/poll/confirm 三段式），面板与独立脚本均可复用。
"""
import base64
import json
import re
import threading
import time
import urllib.parse
import uuid

import requests

UA_PC = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)
UA_M = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
)

QR_APPID = "133"

# check 状态码 -> 统一状态
CODE_MAP = {
    200: "confirmed",   # 已确认，携带 ticket
    201: "waiting",     # 未扫描
    202: "scanned",     # 已扫描，手机待确认
    203: "expired",     # 二维码过期
    257: "error",       # 参数异常
}

SESSION_TTL = 300  # 扫码会话保留 5 分钟


class JdQrSession:
    """一次京东扫码登录会话。"""

    def __init__(self):
        self.sid = uuid.uuid4().hex[:16]
        self.s = requests.Session()
        self.s.headers.update({
            "User-Agent": UA_PC,
            "Referer": "https://passport.jd.com/new/login.aspx",
        })
        self.token = ""        # wlfstk_smdl
        self.status = "created"
        self.msg = ""
        self.ticket = ""
        self.cookie = ""
        self.pt_pin = ""
        self.nickname = ""
        self.created = time.time()

    # ---- 1. 生成二维码 ----
    def create_qr(self):
        # 预热 passport，拿 guid/_t 等基础 cookie
        try:
            self.s.get("https://passport.jd.com/new/login.aspx", timeout=15)
        except Exception:
            pass
        r = self.s.get(
            "https://qr.m.jd.com/show",
            params={"appid": QR_APPID, "size": 200, "t": int(time.time() * 1000)},
            timeout=15,
        )
        r.raise_for_status()
        if "image" not in (r.headers.get("Content-Type") or ""):
            raise RuntimeError("京东二维码接口返回异常: %s" % r.headers.get("Content-Type"))
        self.token = self.s.cookies.get("wlfstk_smdl") or ""
        if not self.token:
            raise RuntimeError("未获取到二维码 token（wlfstk_smdl）")
        self.status = "waiting"
        return base64.b64encode(r.content).decode("ascii")

    # ---- 2. 轮询扫码状态 ----
    def poll(self):
        if self.status in ("confirmed", "success"):
            return self._state()
        if self.status == "expired":
            return self._state()
        if not self.token:
            raise RuntimeError("会话尚未生成二维码")
        r = self.s.get(
            "https://qr.m.jd.com/check",
            params={
                "callback": "jsonpCallback",
                "appid": QR_APPID,
                "token": self.token,
                "_": int(time.time() * 1000),
            },
            timeout=15,
        )
        txt = (r.text or "").strip()
        try:
            j = json.loads(txt[txt.index("{"): txt.rindex("}") + 1])
        except Exception:
            raise RuntimeError("check 返回非 JSON: %s" % txt[:120])
        code = j.get("code")
        self.msg = str(j.get("msg") or "")
        self.status = CODE_MAP.get(code, "unknown")
        if code == 200:
            self.ticket = str(j.get("ticket") or "")
            if not self.ticket:
                self.status = "error"
                self.msg = "扫码成功但未返回 ticket"
        return self._state()

    def _state(self):
        return {"status": self.status, "msg": self.msg,
                "expired": self.status in ("expired", "error"),
                "ready": self.status == "success"}

    # ---- 3. ticket 换 Cookie ----
    def confirm(self):
        if self.status == "success" and self.cookie:
            return self._result()
        if self.status != "confirmed" or not self.ticket:
            raise RuntimeError("用户尚未在手机上确认（当前状态: %s）" % self.status)
        ticket = self.ticket
        # 京东扫码登录唯一正确的 ticket 兑换端点：
        #   GET passport.jd.com/uc/qrCodeTicketValidation?t=<ticket>
        # 成功（returnCode=0）后京东通过 Set-Cookie 下发 pt_key/pt_pin（社区脚本通用做法）。
        # 旧实现里用的 passport.jd.com/uc/login、pt.m.jd.com/user/login、
        # plogin.m.jd.com/user/login 都不是扫码 ticket 的兑换地址（后者实测 302 跳 error2.aspx），
        # 导致永远拿不到 pt_key/pt_pin → 前端报「获取失败」。
        url = "https://passport.jd.com/uc/qrCodeTicketValidation"
        headers = {
            "User-Agent": UA_PC,
            "Referer": "https://passport.jd.com/uc/login?ltype=logout",
            "Accept": "*/*",
        }
        r = self.s.get(url, params={"t": ticket}, headers=headers,
                       timeout=30, allow_redirects=False)
        txt = (r.text or "").strip()
        try:
            j = json.loads(txt)
        except Exception:
            j = {}
        rc = j.get("returnCode") if isinstance(j, dict) else None
        if rc != 0:
            msg = (j.get("msg") or "") if isinstance(j, dict) else ""
            raise RuntimeError(
                "京东二维码校验未通过（returnCode=%s%s），请重新生成二维码并在手机京东 App 上确认"
                % (rc, "，%s" % msg if msg else ""))
        # returnCode=0 表示校验通过。京东会在校验响应的 Set-Cookie 里下发 pt_key/pt_pin。
        # 直接用正则从 Set-Cookie 头解析，绕开 cookie jar 的 domain/属性判断（最可靠）。
        cookie = _parse_pt_from_headers(r.headers.get("Set-Cookie") or "")
        # 兜底：部分情况下主域 pt_key 需再访问一次主页才落地
        if not cookie:
            try:
                r2 = self.s.get("https://www.jd.com/", timeout=15, allow_redirects=True)
                cookie = _parse_pt_from_headers(r2.headers.get("Set-Cookie") or "")
            except Exception:
                pass
        if not cookie:
            cookie = self._extract_pt()
        if not cookie:
            names = sorted({c.name for c in self.s.cookies if "pt" in c.name.lower()})
            sc = (r.headers.get("Set-Cookie") or "").replace("\r", "").replace("\n", "")[:400]
            raise RuntimeError(
                "登录校验已通过（returnCode=0），但未能从响应中解析到 pt_key/pt_pin。"
                "（会话 pt 类 cookie: %s；校验响应 Set-Cookie 摘要: %s）"
                % (",".join(names) or "无", sc or "空"))
        # 写回 session，便于后续 verify_cookie / 续期使用
        for name, value in _split_pt(cookie).items():
            try:
                self.s.cookies.set(name, value, domain=".jd.com", path="/")
            except Exception:
                pass
        self.cookie = cookie
        self.pt_pin = _pin_of(cookie)
        self.status = "success"
        ok, nick = verify_cookie(cookie)
        self.nickname = nick or ""
        return self._result()

    def _extract_pt(self):
        try:
            vals = {}
            for c in self.s.cookies:
                if getattr(c, "name", "") in ("pt_key", "pt_pin") and getattr(c, "value", None):
                    vals[c.name] = c.value
            if vals.get("pt_key") and vals.get("pt_pin"):
                return "pt_key=%s;pt_pin=%s;" % (vals["pt_key"], vals["pt_pin"])
        except Exception:
            pass
        return ""

    def _result(self):
        return {"cookie": self.cookie, "pt_pin": self.pt_pin,
                "nickname": self.nickname, "status": self.status}


def _pin_of(cookie):
    import re
    m = re.search(r"pt_pin=([^;,\s]+)", cookie or "")
    if not m:
        return ""
    return urllib.parse.unquote(m.group(1))


def _parse_pt_from_headers(set_cookie_str):
    """从 Set-Cookie 响应头字符串里直接提取 pt_key/pt_pin（绕开 cookie jar 的域判断）。

    京东在 qrCodeTicketValidation returnCode=0 时通过 Set-Cookie 下发这两个 cookie，
    但 requests 的 cookie jar 受 domain / SameSite / Partitioned 等属性影响，可能漏存，
    因此这里直接对原始头做正则解析，最稳妥。
    """
    if not set_cookie_str:
        return ""
    text = set_cookie_str.replace("\r", "").replace("\n", "")
    k = re.search(r"pt_key=([^;,\s]+)", text)
    p = re.search(r"pt_pin=([^;,\s]+)", text)
    if k and p:
        return "pt_key=%s;pt_pin=%s;" % (k.group(1), p.group(1))
    return ""


def _split_pt(cookie):
    """'pt_key=...;pt_pin=...;' -> {name: value}"""
    out = {}
    for part in cookie.split(";"):
        part = part.strip()
        if "=" in part:
            n, v = part.split("=", 1)
            if n.strip() in ("pt_key", "pt_pin"):
                out[n.strip()] = v
    return out


# ============ 会话注册表（线程安全 + 自动清理） ============
_sessions = {}
_lock = threading.Lock()


def _cleanup():
    now = time.time()
    dead = [k for k, v in _sessions.items() if now - v.created > SESSION_TTL]
    for k in dead:
        _sessions.pop(k, None)


def create_session():
    sess = JdQrSession()
    img = sess.create_qr()
    with _lock:
        _cleanup()
        _sessions[sess.sid] = sess
    return sess.sid, img


def get_session(sid):
    with _lock:
        return _sessions.get(str(sid))


def poll_session(sid):
    sess = get_session(sid)
    if not sess:
        return {"status": "expired", "msg": "会话不存在或已过期",
                "expired": True, "ready": False}
    return sess.poll()


def confirm_session(sid):
    sess = get_session(sid)
    if not sess:
        raise RuntimeError("会话不存在或已过期，请重新扫码")
    return sess.confirm()


def drop_session(sid):
    with _lock:
        _sessions.pop(str(sid), None)


# ============ Cookie 校验（供自动刷新/状态展示） ============
def verify_cookie(cookie):
    """校验 pt_key/pt_pin 是否仍有效。返回 (True/False/None, 昵称)；
    None 表示网络原因无法判定。"""
    if not cookie or "pt_key=" not in cookie:
        return False, ""
    endpoints = [
        ("https://me-api.jd.com/user_new/info/GetJDUserInfoUnion",
         {"Referer": "https://home.m.jd.com/myJd/newhome.action"}),
        ("https://wq.jd.com/user/info/QueryJDUserInfo",
         {"Referer": "https://wqs.jd.com/my/okuserinfo.shtml"}),
    ]
    for url, extra in endpoints:
        try:
            h = {"User-Agent": UA_M, "Cookie": cookie}
            h.update(extra)
            r = requests.get(url, headers=h, timeout=12)
            j = r.json()
            if str(j.get("ret")) == "0" or (j.get("data") or {}).get("userInfo"):
                nick = ""
                try:
                    ui = (j.get("data") or {}).get("userInfo") or {}
                    nick = ui.get("nickname") or ui.get("baseInfo", {}).get("nickname") or ""
                except Exception:
                    nick = ""
                return True, nick
            return False, ""
        except Exception:
            continue
    return None, ""
