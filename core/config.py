"""青豆面板 - 配置 / 设置 / 鉴权 工具。"""
import os
import hmac
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
    # 默认监听地址（0.0.0.0 便于服务器/局域网部署，可改 127.0.0.1 仅本机）
    host = db.query_one("SELECT value FROM settings WHERE key='host'")
    if host is None:
        db.execute("INSERT INTO settings(key,value) VALUES(?,?)", ("host", "0.0.0.0"))
    # 默认并发
    conc = db.query_one("SELECT value FROM settings WHERE key='max_concurrent'")
    if conc is None:
        db.execute("INSERT INTO settings(key,value) VALUES(?,?)", ("max_concurrent", "5"))
    # 默认时区显示
    tz = db.query_one("SELECT value FROM settings WHERE key='timezone'")
    if tz is None:
        db.execute("INSERT INTO settings(key,value) VALUES(?,?)", ("timezone", "Asia/Shanghai"))
    # GitHub 自动更新（默认关闭，需自行填写仓库地址）
    for k, v in (("github_repo", ""), ("github_branch", "main"), ("github_auto_update", "0")):
        if db.query_one("SELECT key FROM settings WHERE key=?", (k,)) is None:
            db.execute("INSERT INTO settings(key,value) VALUES(?,?)", (k, v))


def hash_password(pw: str) -> str:
    """加盐 SHA-256 哈希，存储格式： sha256$<salt_hex>$<hash_hex>。"""
    salt = secrets.token_hex(16)
    dig = hashlib.sha256((salt + pw).encode("utf-8")).hexdigest()
    return f"sha256${salt}${dig}"


def _legacy_hash(pw: str) -> str:
    """兼容旧版无盐哈希（qingdou:: 前缀）。"""
    return hashlib.sha256(("qingdou::" + pw).encode("utf-8")).hexdigest()


def verify_password(pw: str) -> bool:
    row = db.query_one("SELECT value FROM settings WHERE key='admin_password'")
    if row is None:
        return False
    stored = row["value"]
    if stored.startswith("sha256$"):
        try:
            _, salt, dig = stored.split("$", 2)
        except ValueError:
            return False
        calc = hashlib.sha256((salt + pw).encode("utf-8")).hexdigest()
        return hmac.compare_digest(calc, dig)
    # 兼容旧版无盐哈希：验证通过则自动迁移为加盐格式（不影响已登录态）
    if stored == _legacy_hash(pw):
        set_setting("admin_password", hash_password(pw))
        return True
    return False


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
