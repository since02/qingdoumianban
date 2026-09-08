"""青豆面板 - 配置 / 设置 / 鉴权 工具。"""
import os
import re
import hashlib
import secrets
from core import db

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
SCRIPTS_DIR = os.path.join(DATA_DIR, "scripts")
LOGS_DIR = os.path.join(DATA_DIR, "logs")
SUBS_DIR = os.path.join(DATA_DIR, "subs")

DEFAULT_USERNAME = "admin"
DEFAULT_PASSWORD = "adminadmin"
PANEL_NAME = "青豆面板"
PANEL_VERSION = "1.0.0"


def ensure_defaults():
    """初始化默认设置、账户、通知与 AI 占位。"""
    admin_pw = db.query_one("SELECT value FROM settings WHERE key='admin_password'")
    if admin_pw is None:
        db.execute(
            "INSERT INTO settings(key,value) VALUES(?,?)",
            ("admin_password", hash_password(DEFAULT_PASSWORD)),
        )
    tok = db.query_one("SELECT value FROM settings WHERE key='api_token'")
    if tok is None:
        db.execute(
            "INSERT INTO settings(key,value) VALUES(?,?)",
            ("api_token", secrets.token_hex(24)),
        )
    # 默认开放端口
    port = db.query_one("SELECT value FROM settings WHERE key='port'")
    if port is None:
        db.execute("INSERT INTO settings(key,value) VALUES(?,?)", ("port", "5700"))
    # 默认并发
    conc = db.query_one("SELECT value FROM settings WHERE key='max_concurrent'")
    if conc is None:
        db.execute("INSERT INTO settings(key,value) VALUES(?,?)", ("max_concurrent", "5"))
    # 默认时区显示
    tz = db.query_one("SELECT value FROM settings WHERE key='timezone'")
    if tz is None:
        db.execute("INSERT INTO settings(key,value) VALUES(?,?)", ("timezone", "Asia/Shanghai"))
    # yyb-go 微信扫码登录对接（默认关闭，本机 127.0.0.1:8000）
    for k, v in (("yybgo_enabled", "0"), ("yybgo_host", "127.0.0.1"),
                 ("yybgo_port", "8000"), ("yybgo_token", "")):
        if db.query_one("SELECT key FROM settings WHERE key=?", (k,)) is None:
            db.execute("INSERT INTO settings(key,value) VALUES(?,?)", (k, v))
    # 兼容旧版：若曾配置过 yybgo_url，拆分到 host/port
    old = db.query_one("SELECT value FROM settings WHERE key='yybgo_url'")
    if old and old["value"]:
        m = re.match(r"https?://([^:/]+)(?::(\d+))?", old["value"].rstrip("/"))
        if m:
            db.execute("UPDATE settings SET value=? WHERE key='yybgo_host'", (m.group(1),))
            if m.group(2):
                db.execute("UPDATE settings SET value=? WHERE key='yybgo_port'", (m.group(2),))
    # GitHub 自动更新（默认关闭，需自行填写仓库地址）
    for k, v in (("github_repo", ""), ("github_branch", "main"), ("github_auto_update", "0")):
        if db.query_one("SELECT key FROM settings WHERE key=?", (k,)) is None:
            db.execute("INSERT INTO settings(key,value) VALUES(?,?)", (k, v))


def hash_password(pw: str) -> str:
    return hashlib.sha256(("qingdou::" + pw).encode("utf-8")).hexdigest()


def verify_password(pw: str) -> bool:
    row = db.query_one("SELECT value FROM settings WHERE key='admin_password'")
    if row is None:
        return False
    return row["value"] == hash_password(pw)


def get_setting(key, default=None):
    row = db.query_one("SELECT value FROM settings WHERE key=?", (key,))
    return row["value"] if row else default


def set_setting(key, value):
    existing = db.query_one("SELECT key FROM settings WHERE key=?", (key,))
    if existing:
        db.execute("UPDATE settings SET value=? WHERE key=?", (str(value), key))
    else:
        db.execute("INSERT INTO settings(key,value) VALUES(?,?)", (key, str(value)))


def get_api_token():
    return get_setting("api_token", "")


def ensure_dirs():
    for d in (DATA_DIR, SCRIPTS_DIR, LOGS_DIR, SUBS_DIR):
        os.makedirs(d, exist_ok=True)
