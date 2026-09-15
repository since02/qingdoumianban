"""京东扫码登录引擎（纯 Python）。

京东官方扫码登录，走移动端 plogin（appid=300）流程，三段式：
  1) GET  plogin.m.jd.com/cgi-bin/mm/new_login_entrance  -> s_token（伴随 guid/lsid/lstoken cookie）
  2) POST plogin.m.jd.com/cgi-bin/m/tmauthreflogurl      -> token + okl_token(Set-Cookie)
     二维码 URL: https://plogin.m.jd.com/cgi-bin/m/tmauth?appid=300&client_type=m&token=<token>
  3) POST plogin.m.jd.com/cgi-bin/m/tmauthchecktoken     -> errcode 判定：
        0   = 登录成功（Set-Cookie 下发 pt_key/pt_pin）
        21  = 二维码失效
        176 = 尚未扫码 / 授权未确认

说明：京东 PC 端 qr.m.jd.com（appid=133）那套旧流程即使 returnCode=0 也不再下发
登录态 Cookie（实测 Set-Cookie 为空），因此改为移动端 tmauth 流程——pt_key/pt_pin 在
tmauthchecktoken 返回 errcode=0 时经 Set-Cookie 下发。

接口形态保持 create/poll/confirm 三段式，面板与独立脚本均可复用。
"""
import base64
import io
import json
import re
import threading
import time
import urllib.parse
import uuid

import requests

# 移动端 UA（京东 plogin 扫码流程要求，末尾 TM/{0} 填毫秒时间戳防缓存）
UA = (
    "Mozilla/5.0 (iPhone; U; CPU iPhone OS 4_3_2 like Mac OS X; en-us) "
    "AppleWebKit/533.17.9 (KHTML, like Gecko) Version/5.0.2 Mobile/8H7 "
    "Safari/6533.18.5 UCBrowser/13.4.2.1122 TM/{0}"
)

LOGIN_APPID = "300"
QR_URL_TMPL = "https://plogin.m.jd.com/cgi-bin/m/tmauth?appid=300&client_type=m&token={token}"
RETURN_URL_TMPL = (
    "https://wqlogin2.jd.com/passport/LoginRedirect?state={t}"
    "&returnurl=//home.m.jd.com/myJd/newhome.action?sceneval=2&ufc=&/myJd/home.action"
)

SESSION_TTL = 300  # 扫码会话保留 5 分钟


class JdQrSession:
    """一次京东扫码登录会话。"""

    def __init__(self):
        self.sid = uuid.uuid4().hex[:16]
        self.s = requests.Session()
        self.s.headers.update({"Accept": "application/json, text/plain, */*"})
        self.s_token = ""      # 第一步拿到
        self.token = ""        # 二维码订单 token（m_token...）
        self.okl_token = ""    # 校验用
        self.qr_url = ""       # 二维码内容（URL）
        self.status = "created"
        self.msg = ""
        self.cookie = ""
        self.pt_pin = ""
        self.nickname = ""
        self.created = time.time()

    # ---- 内部工具 ----
    def _ua(self):
        return UA.format(int(time.time() * 1000))

    def _referer(self, t_ms=None):
        t = t_ms or int(time.time() * 1000)
        return (
            "https://plogin.m.jd.com/login/login?appid=300&returnurl="
            "https://wqlogin2.jd.com/passport/LoginRedirect?state=%d"
            "&returnurl=//home.m.jd.com/myJd/newhome.action?sceneval=2&ufc=&/myJd/home.action"
            "&source=wq_passport" % t
        )

    # ---- 1. 生成二维码 ----
    def create_qr(self):
        # 1-1) 取 s_token
        t = int(time.time())
        ru = (
            "https://wq.jd.com/passport/LoginRedirect?state=%d&returnurl="
            "https://home.m.jd.com/myJd/newhome.action?sceneval=2&ufc=&/myJd/home.action"
            "&source=wq_passport" % t
        )
        url1 = ("https://plogin.m.jd.com/cgi-bin/mm/new_login_entrance?lang=chs&appid=300&returnurl="
                + urllib.parse.quote(ru, safe=""))
        r1 = self.s.get(url1, headers={"User-Agent": self._ua(), "Referer": url1}, timeout=20)
        r1.raise_for_status()
        try:
            self.s_token = (r1.json() or {}).get("s_token", "")
        except Exception:
            self.s_token = ""
        if not self.s_token:
            raise RuntimeError("京东未返回 s_token（body: %s）" % (r1.text or "")[:120])

        # 1-2) 取二维码 token + okl_token
        t2 = int(time.time() * 1000)
        url2 = ("https://plogin.m.jd.com/cgi-bin/m/tmauthreflogurl?s_token=%s&v=%d&remember=true"
                % (self.s_token, t2))
        data2 = {"lang": "chs", "appid": LOGIN_APPID,
                 "returnurl": RETURN_URL_TMPL.format(t=t2)}
        h2 = {"User-Agent": self._ua(), "Referer": self._referer(t2),
              "Content-Type": "application/x-www-form-urlencoded; Charset=UTF-8"}
        r2 = self.s.post(url2, headers=h2, data=data2, timeout=20)
        r2.raise_for_status()
        try:
            self.token = (r2.json() or {}).get("token", "")
        except Exception:
            self.token = ""
        if not self.token:
            raise RuntimeError("京东未返回登录 token（body: %s）" % (r2.text or "")[:120])
        self.okl_token = (self.s.cookies.get_dict() or {}).get("okl_token", "")

        # 1-3) 二维码内容（自行编码成图片）
        self.qr_url = QR_URL_TMPL.format(token=self.token)
        self.status = "waiting"
        return _qr_png_base64(self.qr_url)

    # ---- 2. 轮询扫码状态 ----
    def poll(self):
        if self.status in ("success", "expired"):
            return self._state()
        if not self.token:
            raise RuntimeError("会话尚未生成二维码")
        t = int(time.time() * 1000)
        url = ("https://plogin.m.jd.com/cgi-bin/m/tmauthchecktoken?&token=%s&ou_state=0&okl_token=%s"
               % (self.token, self.okl_token))
        data = {"lang": "chs", "appid": LOGIN_APPID,
                "returnurl": RETURN_URL_TMPL.format(t=t), "source": "wq_passport"}
        h = {"User-Agent": self._ua(), "Referer": self._referer(t),
             "Content-Type": "application/x-www-form-urlencoded; Charset=UTF-8"}
        r = self.s.post(url, headers=h, data=data, timeout=20)
        try:
            j = r.json()
        except Exception:
            raise RuntimeError("tmauthchecktoken 返回非 JSON：%s" % (r.text or "")[:120])
        code = j.get("errcode")
        self.msg = str(j.get("message") or "")
        if code == 0:
            # 登录成功：pt_key/pt_pin 经 Set-Cookie 下发（直接从响应头解析，绕开 cookie jar 域判断）
            cookie = _parse_pt_from_headers(r.headers.get("Set-Cookie") or "")
            if not cookie:
                cookie = self._extract_pt()
            if not cookie:
                try:
                    r2 = self.s.get("https://home.m.jd.com/myJd/newhome.action?sceneval=2&ufc=",
                                    headers={"User-Agent": self._ua()}, timeout=15)
                    cookie = _parse_pt_from_headers(r2.headers.get("Set-Cookie") or "")
                except Exception:
                    pass
            if cookie:
                for n, v in _split_pt(cookie).items():
                    try:
                        self.s.cookies.set(n, v, domain=".jd.com", path="/")
                    except Exception:
                        pass
                self.cookie = cookie
                self.pt_pin = _pin_of(cookie)
                self.status = "success"
                self.msg = "扫码登录成功"
            else:
                self.status = "error"
                self.msg = ("扫码已确认，但未从响应中解析到 pt_key/pt_pin"
                            "（Set-Cookie 摘要: %s）"
                            % (((r.headers.get("Set-Cookie") or "").replace("\r", "")
                                .replace("\n", "")[:200]) or "空"))
        elif code == 21:
            self.status = "expired"
        elif code == 176:
            self.status = "waiting"   # 尚未扫码 / 授权未确认
        else:
            self.status = "waiting"
        return self._state()

    def _state(self):
        return {"status": self.status, "msg": self.msg,
                "expired": self.status in ("expired", "error"),
                "ready": self.status == "success"}

    # ---- 3. 确认并取回 Cookie ----
    def confirm(self):
        if self.status == "success" and self.cookie:
            return self._finish()
        # 用户点了确认但前端可能尚未轮询到：再查一次
        self.poll()
        if self.status == "success" and self.cookie:
            return self._finish()
        if self.status == "error":
            raise RuntimeError(self.msg or "扫码已确认，但未取到 Cookie")
        raise RuntimeError("用户尚未在手机上确认登录（当前状态: %s）" % self.status)

    def _finish(self):
        self.pt_pin = self.pt_pin or _pin_of(self.cookie)
        ok, nick = verify_cookie(self.cookie)
        self.nickname = nick or self.pt_pin
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
                "nickname": self.nickname, "status": self.status, "qr_url": self.qr_url}


def _pin_of(cookie):
    m = re.search(r"pt_pin=([^;,\s]+)", cookie or "")
    if not m:
        return ""
    return urllib.parse.unquote(m.group(1))


def _parse_pt_from_headers(set_cookie_str):
    """从 Set-Cookie 响应头字符串里直接提取 pt_key/pt_pin（绕开 cookie jar 的域判断）。"""
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
    for part in (cookie or "").split(";"):
        part = part.strip()
        if "=" in part:
            n, v = part.split("=", 1)
            if n.strip() in ("pt_key", "pt_pin"):
                out[n.strip()] = v
    return out


def _qr_png_base64(text):
    """把文本编码成 PNG 二维码（base64）。优先 segno（纯 Python，零依赖）。"""
    try:
        import segno
    except ImportError:
        raise RuntimeError("缺少二维码生成库，请执行：pip install segno")
    buf = io.BytesIO()
    segno.make(text, error="m").save(buf, kind="png", scale=6, border=2)
    return base64.b64encode(buf.getvalue()).decode("ascii")


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
    ua_m = ("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 "
            "(KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1")
    for url, extra in endpoints:
        try:
            h = {"User-Agent": ua_m, "Cookie": cookie}
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
