"""青豆面板 - 订阅同步（git 仓库 / qinglong 格式 JSON 清单，自动导入脚本与定时任务）。"""
import os
import re
import json
import time
import subprocess
import requests
from core import db, config, executor

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
SCRIPTS_DIR = os.path.join(DATA_DIR, "scripts")
SUBS_DIR = os.path.join(DATA_DIR, "subs")
LOGS_DIR = os.path.join(DATA_DIR, "logs")

CRON_RE = re.compile(r"(?:#|//)\s*cron\s*[:=]\s*([0-9*/,\-\s]{9,})", re.IGNORECASE)


def _split_patterns(s):
    """把 `a|b|c` 形式的竖线分隔模式编译为正则列表（无效模式按字面兜底）。"""
    if not s:
        return []
    out = []
    for p in s.split("|"):
        p = p.strip()
        if not p:
            continue
        try:
            out.append(re.compile(p))
        except re.error:
            out.append(re.compile(re.escape(p)))
    return out


def _match_any(rel, regexes):
    return any(rx.search(rel) for rx in regexes)


def sync_subscription(sub_id):
    sub = db.query_one("SELECT * FROM subscriptions WHERE id=?", (sub_id,))
    if not sub:
        return
    try:
        if sub["stype"] == "git":
            _sync_git(sub)
        elif sub["stype"] == "json":
            _sync_json(sub)
        db.execute(
            "UPDATE subscriptions SET last_status='success', last_sync=datetime('now','localtime') WHERE id=?",
            (sub_id,),
        )
    except Exception as e:
        db.execute(
            "UPDATE subscriptions SET last_status='failed', last_sync=datetime('now','localtime') WHERE id=?",
            (sub_id,),
        )
        raise


def _run_git(args, cwd=None):
    res = subprocess.run(["git"] + args, cwd=cwd or SUBS_DIR,
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=300)
    if res.returncode != 0:
        raise RuntimeError(res.stderr.decode("utf-8", "replace")[:500])
    return res


def _sync_git(sub):
    alias = (sub["alias"] or f"sub_{sub['id']}").strip() or f"sub_{sub['id']}"
    target = os.path.join(SUBS_DIR, alias)
    url = sub["url"]
    branch = sub["branch"] or "main"
    os.makedirs(SUBS_DIR, exist_ok=True)
    if os.path.exists(os.path.join(target, ".git")):
        _run_git(["-C", target, "pull", "origin", branch])
    else:
        if os.path.exists(target):
            import shutil
            shutil.rmtree(target)
        _run_git(["clone", "--depth", "1", "-b", branch, url, target])
    _import_crons(target, sub)


def _sync_json(sub):
    url = sub["url"]
    r = requests.get(url, timeout=60)
    r.raise_for_status()
    data = r.json()
    if isinstance(data, dict):
        data = data.get("subs", data.get("list", []))
    if not isinstance(data, list):
        raise RuntimeError("订阅 JSON 格式错误：应为数组")
    alias = (sub["alias"] or f"sub_{sub['id']}").strip() or f"sub_{sub['id']}"
    for item in data:
        name = item.get("name") or item.get("title") or "未命名"
        file_url = item.get("url") or item.get("link")
        schedule = item.get("schedule") or item.get("cron") or "0 0 * * *"
        if not file_url:
            continue
        ext = ".py" if file_url.endswith(".py") else ".js" if file_url.endswith(".js") else ".sh"
        safe = re.sub(r"\W+", "_", name)
        fname = f"{alias}_{safe}{ext}"
        fpath = os.path.join(SCRIPTS_DIR, fname)
        try:
            content = requests.get(file_url, timeout=60).text
        except Exception:
            continue
        with open(fpath, "w", encoding="utf-8") as f:
            f.write(content)
        _find_or_create_task(sub["id"], fname, name,
                             _cmd_for_ext(fpath, ext), schedule)


def _cmd_for_ext(fpath, ext):
    """返回相对面板根目录的可移植命令（解释器由执行时根据当前位置解析）。"""
    rel = os.path.relpath(fpath, BASE_DIR).replace("\\", "/")
    if ext == ".js":
        return f'node "{rel}"'
    if ext == ".sh":
        return f'bash "{rel}"'
    return f'python "{rel}"'


def _import_crons(target, sub):
    white = _split_patterns(sub.get("whitelist"))
    black = _split_patterns(sub.get("blacklist"))
    dep = _split_patterns(sub.get("dependence"))
    for root, _dirs, files in os.walk(target):
        for fn in files:
            if not fn.endswith((".py", ".js", ".sh")):
                continue
            fpath = os.path.join(root, fn)
            rel = os.path.relpath(fpath, target)
            # 依赖文件（如 sendNotify.js / package.json 等）不导入为任务
            if _match_any(rel, dep):
                continue
            # 黑名单优先跳过
            if _match_any(rel, black):
                continue
            # 白名单存在时，仅导入命中者
            if white and not _match_any(rel, white):
                continue
            try:
                with open(fpath, "r", encoding="utf-8", errors="replace") as f:
                    head = "".join(f.readlines()[:25])
            except Exception:
                continue
            m = CRON_RE.search(head)
            if not m:
                continue
            schedule = m.group(1).strip()
            name = os.path.splitext(fn)[0]
            ext = os.path.splitext(fn)[1]
            _find_or_create_task(sub["id"], f"{sub['alias'] or sub['id']}/{rel}",
                                 name, _cmd_for_ext(fpath, ext), schedule)


def _find_or_create_task(sub_id, file_key, name, command, schedule):
    """按 (sub_id, file_key) 幂等创建/更新任务。"""
    existing = db.query_one(
        "SELECT id FROM tasks WHERE extra LIKE ?",
        (f'%"sub_id": {sub_id}, "file": "{file_key}"%',),
    )
    if existing:
        db.execute(
            "UPDATE tasks SET name=?, command=?, schedule=? WHERE id=?",
            (name, command, schedule, existing["id"]),
        )
    else:
        db.execute(
            "INSERT INTO tasks(name,command,schedule,status,extra) VALUES(?,?,?,1,?)",
            (name, command, schedule, json.dumps({"sub_id": sub_id, "file": file_key})),
        )


def run_sub_now(sub_id):
    """立即同步一个订阅，并记录日志。"""
    import threading

    def _work():
        log_path = os.path.join(LOGS_DIR, f"sub_{time.strftime('%Y%m%d_%H%M%S')}_{os.getpid()}.log")
        os.makedirs(LOGS_DIR, exist_ok=True)
        log_id = db.execute(
            "INSERT INTO logs(sub_id,kind,log_file,started_at) VALUES(?,?,?,datetime('now','localtime'))",
            (sub_id, "sub", log_path),
        )
        try:
            with open(log_path, "w", encoding="utf-8", errors="replace") as lf:
                lf.write(f"[青豆面板] 开始同步订阅 #{sub_id}\n")
            sync_subscription(sub_id)
            status = "success"
        except Exception as e:
            status = "failed"
            with open(log_path, "a", encoding="utf-8", errors="replace") as lf:
                lf.write(f"[青豆面板][错误] {e}\n")
        db.execute(
            "UPDATE logs SET finished_at=datetime('now','localtime'),status=? WHERE id=?",
            (status, log_id),
        )

    t = threading.Thread(target=_work, daemon=True)
    t.start()
    return "queued"
