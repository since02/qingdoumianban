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

CRON_RE = re.compile(r"cron\s*[:=]?\s*[\"']?\s*([0-9][0-9*/,\- ]{8,})[\"']?", re.IGNORECASE)


def _detect_cron(head):
    """从文件头部注释中识别 cron 表达式。
    兼容主流写法：`#cron: x x x`、`// cron=x`、JS 块注释 `* cron: x`、`cron "x x x"`、
    Python `cron="0 8 * * *"` 等；逐行扫描取第一处。"""
    for line in head.splitlines():
        s = line.strip()
        if "cron" not in s.lower():
            continue
        # 排除代码调用（如 new Cron(...)），只认注释或赋值场景
        if "new Cron" in s or "schedule(" in s:
            continue
        m = CRON_RE.search(s)
        if m:
            cand = m.group(1).strip()
            # 5 段式校验（分 时 日 月 周）
            parts = cand.split()
            if len(parts) == 5 and all(re.fullmatch(r"[0-9*/,\-]+", p) for p in parts):
                return cand
    return ""

# 直连失败时依次尝试的加速镜像（可在系统设置 sub_git_mirrors 覆盖，空格分隔）
DEFAULT_MIRRORS = "https://js.googo.win/ https://ghproxy.net/ https://gh-proxy.com/ https://ghfast.top/"


def _mirrors():
    return (config.get_setting("sub_git_mirrors", DEFAULT_MIRRORS) or DEFAULT_MIRRORS).split()


def _split_patterns(s):
    """把整个字段当作一条正则（与青龙 ql repo 参数语义一致）。
    例：`jd_|jx_|jddj_`、`^wx-script/.*\\.(js|py)$` 均整体生效；无效正则按字面兜底。"""
    if not s:
        return []
    s = s.strip()
    try:
        return [re.compile(s)]
    except re.error:
        return [re.compile(re.escape(s))]


def _match_any(rel, regexes):
    return any(rx.search(rel) for rx in regexes)


def sync_subscription(sub_id):
    """同步订阅。返回统计 dict（供日志记录）；失败抛异常并写入 last_error。"""
    row = db.query_one("SELECT * FROM subscriptions WHERE id=?", (sub_id,))
    if not row:
        raise RuntimeError(f"订阅 #{sub_id} 不存在")
    sub = dict(row)  # sqlite3.Row 没有 .get，统一转 dict
    stats = {"files": 0, "tasks": 0, "url": sub["url"], "mirror": ""}
    try:
        if sub["stype"] == "git":
            stats.update(_sync_git(sub) or {})
        elif sub["stype"] == "json":
            stats.update(_sync_json(sub) or {})
        db.execute(
            "UPDATE subscriptions SET last_status='success', last_sync=datetime('now','localtime'), "
            "last_error='' WHERE id=?",
            (sub_id,),
        )
        stats["ok"] = True
        return stats
    except Exception as e:
        db.execute(
            "UPDATE subscriptions SET last_status='failed', last_sync=datetime('now','localtime'), "
            "last_error=? WHERE id=?",
            (str(e)[:800], sub_id),
        )
        raise


def _run_git(args, cwd=None):
    res = subprocess.run(["git"] + args, cwd=cwd or SUBS_DIR,
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=300)
    if res.returncode != 0:
        raise RuntimeError(res.stderr.decode("utf-8", "replace")[:500])
    return res


def _git_mirror_url(url, mirror):
    """给原始 git URL 加加速镜像前缀（避免重复拼接）。"""
    if not mirror:
        return url
    for m in _mirrors():
        if url.startswith(m):
            return url
    return mirror.rstrip("/") + "/" + url


def _sync_git(sub):
    """clone/pull 仓库；直连失败时自动尝试加速镜像。返回统计。"""
    alias = (sub["alias"] or f"sub_{sub['id']}").strip() or f"sub_{sub['id']}"
    target = os.path.join(SUBS_DIR, alias)
    url = sub["url"]
    branch = sub["branch"] or "main"
    os.makedirs(SUBS_DIR, exist_ok=True)
    stats = {"files": 0, "tasks": 0, "url": url, "mirror": ""}

    def _try_clone(u):
        if os.path.exists(os.path.join(target, ".git")):
            _run_git(["-C", target, "pull", "origin", branch])
        else:
            if os.path.exists(target):
                import shutil
                shutil.rmtree(target)
            _run_git(["clone", "--depth", "1", "-b", branch, u, target])

    last_err = None
    candidates = [("", url)] + [(m, _git_mirror_url(url, m)) for m in _mirrors()]
    for mirror, u in candidates:
        try:
            _try_clone(u)
            stats["mirror"] = mirror
            break
        except Exception as e:
            last_err = e
            continue
    else:
        raise RuntimeError(f"git 拉取失败（已尝试直连与 {_mirrors()} 镜像）：{last_err}")
    imported = _import_crons(target, sub)
    stats["tasks"] = imported
    return stats


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
    stats = {"files": 0, "tasks": 0, "url": url, "mirror": ""}
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
        stats["files"] += 1
        _find_or_create_task(sub["id"], fname, name,
                             _cmd_for_ext(fpath, ext), schedule)
        stats["tasks"] += 1
    return stats


def _cmd_for_ext(fpath, ext):
    """返回相对面板根目录的可移植命令（解释器由执行时根据当前位置解析）。"""
    rel = os.path.relpath(fpath, BASE_DIR).replace("\\", "/")
    if ext == ".js":
        return f'node "{rel}"'
    if ext == ".sh":
        return f'bash "{rel}"'
    return f'python "{rel}"'


def _import_crons(target, sub):
    """扫描仓库文件并按 cron 注释导入任务，返回导入（命中）文件数。"""
    white = _split_patterns(sub.get("whitelist"))
    black = _split_patterns(sub.get("blacklist"))
    dep = _split_patterns(sub.get("dependence"))
    imported = 0
    for root, _dirs, files in os.walk(target):
        for fn in files:
            if not fn.endswith((".py", ".js", ".sh")):
                continue
            fpath = os.path.join(root, fn)
            rel = os.path.relpath(fpath, target).replace("\\", "/")
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
                    head = "".join(f.readlines()[:30])
            except Exception:
                continue
            schedule = _detect_cron(head)
            if not schedule:
                continue
            name = os.path.splitext(fn)[0]
            ext = os.path.splitext(fn)[1]
            _find_or_create_task(sub["id"], f"{sub['alias'] or sub['id']}/{rel}",
                                 name, _cmd_for_ext(fpath, ext), schedule)
            imported += 1
    return imported


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
    """立即同步一个订阅，并记录日志（含拉取方式与导入统计）。"""
    import threading

    def _work():
        log_path = os.path.join(LOGS_DIR, f"sub_{time.strftime('%Y%m%d_%H%M%S')}_{os.getpid()}.log")
        os.makedirs(LOGS_DIR, exist_ok=True)
        log_id = db.execute(
            "INSERT INTO logs(sub_id,kind,log_file,started_at) VALUES(?,?,?,datetime('now','localtime'))",
            (sub_id, "sub", log_path),
        )
        sub = db.query_one("SELECT name FROM subscriptions WHERE id=?", (sub_id,))
        try:
            with open(log_path, "w", encoding="utf-8", errors="replace") as lf:
                lf.write(f"[青豆面板] 开始同步订阅 #{sub_id} {sub['name'] if sub else ''}\n")
            stats = sync_subscription(sub_id)
            status = "success"
            with open(log_path, "a", encoding="utf-8", errors="replace") as lf:
                if stats.get("mirror"):
                    lf.write(f"[青豆面板] 直连失败/使用镜像: {stats['mirror']}\n")
                lf.write(f"[青豆面板] 同步完成 ✅ 拉取地址: {stats.get('url','')}"
                         f" 导入任务: {stats.get('tasks', 0)} 个\n")
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
