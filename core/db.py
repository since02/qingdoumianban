"""青豆面板 - 数据库访问层（SQLite，WAL 模式，线程安全，内存友好）。"""
import os
import sqlite3
import threading

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
DB_PATH = os.path.join(DATA_DIR, "qingdou.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    command TEXT NOT NULL,
    schedule TEXT NOT NULL DEFAULT '0 0 * * *',
    status INTEGER NOT NULL DEFAULT 1,
    last_run TEXT,
    last_status TEXT,
    last_duration REAL,
    notify INTEGER NOT NULL DEFAULT 0,
    notify_type TEXT,
    extra TEXT,
    created_at TEXT DEFAULT (datetime('now','localtime')),
    updated_at TEXT DEFAULT (datetime('now','localtime'))
);
CREATE TABLE IF NOT EXISTS scripts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    path TEXT NOT NULL,
    content TEXT,
    created_at TEXT DEFAULT (datetime('now','localtime')),
    updated_at TEXT DEFAULT (datetime('now','localtime'))
);
CREATE TABLE IF NOT EXISTS subscriptions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    url TEXT NOT NULL,
    branch TEXT DEFAULT 'main',
    stype TEXT NOT NULL DEFAULT 'git',
    schedule TEXT NOT NULL DEFAULT '0 0 * * *',
    status INTEGER NOT NULL DEFAULT 1,
    last_sync TEXT,
    last_status TEXT,
    alias TEXT,
    created_at TEXT DEFAULT (datetime('now','localtime'))
);
CREATE TABLE IF NOT EXISTS environments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    value TEXT,
    remarks TEXT,
    status INTEGER NOT NULL DEFAULT 1,
    created_at TEXT DEFAULT (datetime('now','localtime'))
);
CREATE TABLE IF NOT EXISTS notifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    ntype TEXT NOT NULL,
    config TEXT,
    status INTEGER NOT NULL DEFAULT 1,
    is_default INTEGER NOT NULL DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now','localtime'))
);
CREATE TABLE IF NOT EXISTS logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id INTEGER,
    task_name TEXT,
    sub_id INTEGER,
    kind TEXT DEFAULT 'task',
    started_at TEXT DEFAULT (datetime('now','localtime')),
    finished_at TEXT,
    status TEXT,
    duration REAL,
    log_file TEXT,
    pid INTEGER
);
CREATE TABLE IF NOT EXISTS ai_configs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    provider TEXT NOT NULL DEFAULT 'openai',
    base_url TEXT,
    api_key TEXT,
    model TEXT,
    status INTEGER NOT NULL DEFAULT 1,
    is_default INTEGER NOT NULL DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now','localtime'))
);
CREATE TABLE IF NOT EXISTS dependencies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    dtype TEXT NOT NULL,
    name TEXT NOT NULL,
    version TEXT,
    status TEXT,
    log_file TEXT,
    created_at TEXT DEFAULT (datetime('now','localtime'))
);
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT
);
"""

_local = threading.local()


def get_conn():
    if not hasattr(_local, "conn"):
        os.makedirs(DATA_DIR, exist_ok=True)
        conn = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA busy_timeout=30000")
        conn.execute("PRAGMA foreign_keys=ON")
        _local.conn = conn
    return _local.conn


def init_db():
    os.makedirs(DATA_DIR, exist_ok=True)
    conn = get_conn()
    conn.executescript(SCHEMA)
    conn.commit()
    # 兼容旧库：补齐可能缺失的列
    _migrate(conn)
    conn.commit()
    # 初始化默认设置
    from core.config import ensure_defaults
    ensure_defaults()


def _migrate(conn):
    cur = conn.execute("PRAGMA table_info(dependencies)")
    cols = {r[1] for r in cur.fetchall()}
    if "log_file" not in cols:
        try:
            conn.execute("ALTER TABLE dependencies ADD COLUMN log_file TEXT")
        except Exception:
            pass


def query(sql, args=()):
    conn = get_conn()
    cur = conn.execute(sql, args)
    return cur.fetchall()


def query_one(sql, args=()):
    conn = get_conn()
    cur = conn.execute(sql, args)
    return cur.fetchone()


def execute(sql, args=()):
    conn = get_conn()
    cur = conn.execute(sql, args)
    conn.commit()
    return cur.lastrowid


def executescript(sql):
    conn = get_conn()
    conn.executescript(sql)
    conn.commit()


def row_to_dict(row):
    if row is None:
        return None
    return dict(row)


def rows_to_list(rows):
    return [dict(r) for r in rows]
