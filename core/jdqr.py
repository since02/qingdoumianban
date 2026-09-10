"""京东扫码登录引擎（纯 Python，零外部依赖）。

替代 yyb-go 的最终产出（pt_key/pt_pin）：
  1) GET  qr.m.jd.com/show            -> 二维码图片 + wlfstk_smdl token
  2) 轮询 GET qr.m.jd.com/check       -> 201 未扫 / 202 已扫待确认 / 203 过期 / 200 成功(ticket)
  3) GET  pt.m.jd.com/user/login      -> 用 ticket 换 pt_key/pt_pin 会话 Cookie

接口形态与 yyb-go 对齐（create/poll/confirm 三段式），面板与独立脚本均可复用。
"""
import base64
import json
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
        ret_pc = urllib.parse.quote("https://www.jd.com/", safe="")
        # 多端点依次尝试：PC passport 优先（appid=133 的 ticket 由 PC 扫码页签发）
        attempts = [
            ("https://passport.jd.com/uc/login?ticket=%s&ReturnUrl=%s" % (ticket, ret_pc),
             UA_PC, "https://passport.jd.com/new/login.aspx"),
            ("https://pt.m.jd.com/user/login?%s" % urllib.parse.urlencode(
                {"ticket": ticket, "appid": QR_APPID, "returnurl": "https://www.jd.com/"}),
             UA_M, "https://plogin.m.jd.com/login/login?appid=%s" % QR_APPID),
            ("https://plogin.m.jd.com/user/login?%s" % urllib.parse.urlencode(
                {"ticket": ticket, "appid": QR_APPID, "returnurl": "https://www.jd.com/"}),
             UA_M, "https://plogin.m.jd.com/login/login?appid=%s" % QR_APPID),
        ]
        diag = []
        for url, ua, ref in attempts:
            try:
                self.s.headers.update({
                    "User-Agent": ua, "Referer": ref,
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                })
                r = self.s.get(url, timeout=30, allow_redirects=True)
                cookie = self._extract_pt()
                diag.append("%s -> %s" % (urllib.parse.urlsplit(url).netloc,
                                          "OK" if cookie else "no-pt"))
                if cookie:
                    self.cookie = cookie
                    self.pt_pin = _pin_of(cookie)
                    self.status = "success"
                    ok, nick = verify_cookie(cookie)
                    self.nickname = nick or ""
                    return self._result()
            except Exception as e:
                diag.append("%s -> %s" % (urllib.parse.urlsplit(url).netloc,
                                          type(e).__name__))
        raise RuntimeError("登录成功但未从会话中解析到 pt_key/pt_pin [%s]" % "; ".join(diag))

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
