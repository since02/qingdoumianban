"""青豆面板 - 系统设置 / 仪表盘 / 重启 / 备份 / 更新 路由。"""
import os
import sys
import re
import json as _json
import time
import socket
import platform
import subprocess
import threading
from datetime import datetime
from flask import request, Response, send_file
from core import db, config
from core import scheduler
from core import executor
from routes import bp, json_ok, json_err, auth_required, get_json_body

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP_PATH = os.path.join(BASE_DIR, "app.py")
SCRIPTS_DIR = os.path.join(BASE_DIR, "data", "scripts")


def _sys_info():
    info = {
        "panel": config.PANEL_NAME,
        "version": config.PANEL_VERSION,
        "platform": platform.platform(),
        "python": sys.version.split()[0],
        "node": "",
        "cwd": BASE_DIR,
        "port": config.get_setting("port", "5700"),
        "pid": os.getpid(),
    }
    try:
        info["node"] = subprocess.run([executor.get_node_path(), "-v"],
                                      capture_output=True, text=True, timeout=10).stdout.strip()
    except Exception:
        info["node"] = "未检测到"
    try:
        import psutil
        p = psutil.Process(os.getpid())
        info["mem_mb"] = round(p.memory_info().rss / 1024 / 1024, 1)
        info["cpu_percent"] = p.cpu_percent(interval=0.3)
    except Exception:
        info["mem_mb"] = None
        info["cpu_percent"] = None
    return info


@bp.route("/dashboard", methods=["GET"])
@auth_required
def dashboard():
    tasks = db.query("SELECT status,last_status FROM tasks")
    enabled = sum(1 for t in tasks if t["status"] == 1)
    success = sum(1 for t in tasks if t["last_status"] == "success")
    failed = sum(1 for t in tasks if t["last_status"] in ("failed", "timeout"))
    subs = db.query("SELECT COUNT(*) AS c FROM subscriptions")
    envs = db.query("SELECT COUNT(*) AS c FROM environments")
    notifs = db.query("SELECT COUNT(*) AS c FROM notifications WHERE status=1")
    scripts_dir = os.path.join(BASE_DIR, "data", "scripts")
    script_count = 0
    if os.path.exists(scripts_dir):
        for _root, _d, files in os.walk(scripts_dir):
            script_count += len([f for f in files if f.endswith((".py", ".js", ".sh"))])
    recent = db.query("SELECT * FROM logs ORDER BY id DESC LIMIT 8")
    return json_ok({
        "sys": _sys_info(),
        "stats": {
            "tasks": len(tasks), "enabled_tasks": enabled,
            "success": success, "failed": failed,
            "subscriptions": subs[0]["c"], "environments": envs[0]["c"],
            "notifications": notifs[0]["c"], "scripts": script_count,
        },
        "recent_logs": [dict(r) for r in recent],
    })


@bp.route("/system/info", methods=["GET"])
@auth_required
def system_info():
    return json_ok(_sys_info())


# 系统监控：网络 IO 增量需要保留上一次采样
_net_prev = None
_net_prev_ts = 0


@bp.route("/system/metrics", methods=["GET"])
@auth_required
def system_metrics():
    import time as _t
    data = {"cpu": None, "cpu_per_core": [], "mem": None, "disk": None, "net": None, "boot": None}
    try:
        import psutil
        data["cpu"] = psutil.cpu_percent(interval=0.3)
        data["cpu_per_core"] = psutil.cpu_percent(interval=0.1, percpu=True)
        vm = psutil.virtual_memory()
        data["mem"] = {"percent": vm.percent, "used_mb": round(vm.used / 1024 / 1024),
                       "total_mb": round(vm.total / 1024 / 1024)}
        # 取 data 目录所在磁盘分区
        disk_path = BASE_DIR
        try:
            du = psutil.disk_usage(disk_path)
            data["disk"] = {"percent": du.percent, "used_gb": round(du.used / 1024**3, 2),
                            "total_gb": round(du.total / 1024**3, 2), "path": disk_path}
        except Exception:
            pass
        now = _t.time()
        cur = psutil.net_io_counters()
        global _net_prev, _net_prev_ts
        if _net_prev and (now - _net_prev_ts) > 0:
            dt = now - _net_prev_ts
            data["net"] = {
                "sent_kb_s": round((cur.bytes_sent - _net_prev.bytes_sent) / 1024 / dt, 2),
                "recv_kb_s": round((cur.bytes_recv - _net_prev.bytes_recv) / 1024 / dt, 2),
            }
        else:
            data["net"] = {"sent_kb_s": 0, "recv_kb_s": 0}
        _net_prev = cur
        _net_prev_ts = now
        try:
            data["boot"] = int(_t.time() - psutil.boot_time())
        except Exception:
            pass
    except Exception as e:
        data["error"] = str(e)
    return json_ok(data)


@bp.route("/system/settings", methods=["GET"])
@auth_required
def get_settings():
    keys = ["host", "port", "max_concurrent", "task_timeout", "timezone", "python_path", "node_path",
            "github_repo", "github_branch", "github_auto_update"]
    data = {k: config.get_setting(k) for k in keys}
    return json_ok(data)


@bp.route("/system/settings", methods=["POST"])
@auth_required
def save_settings():
    b = get_json_body()
    for k in ["host", "port", "max_concurrent", "task_timeout", "timezone", "python_path", "node_path",
              "github_repo", "github_branch", "github_auto_update"]:
        if k in b:
            config.set_setting(k, b[k])
    return json_ok(msg="已保存（host/端口/并发等需重启面板后生效）")


def _port_listening(port):
    try:
        port = int(port)
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(1)
            return s.connect_ex(("127.0.0.1", port)) == 0
    except Exception:
        return False


def _spawn_detached():
    """以完全脱离终端的守护方式启动一个新的面板进程（继承当前 cwd 与解释器）。"""
    log_path = os.path.join(BASE_DIR, "data", "daemon.log")
    logf = open(log_path, "a", buffering=1)
    # 注意：Windows 下一旦重定向了 stdout/stderr，就不能再设置 close_fds=True，
    # 否则 subprocess 会抛 ValueError: close_fds is not supported on Windows platforms
    # if you redirect stdin/stdout/stderr。这里统一用 False（Linux 同样允许）。
    kwargs = dict(args=[sys.executable, APP_PATH], cwd=BASE_DIR,
                  stdout=logf, stderr=logf, close_fds=False)
    if sys.platform.startswith("win"):
        kwargs["creationflags"] = 0x00000008  # DETACHED_PROCESS
    else:
        kwargs["start_new_session"] = True
    try:
        proc = subprocess.Popen(**kwargs)
    finally:
        # 父进程关闭自己的日志副本即可，子进程已继承其句柄
        try:
            logf.close()
        except Exception:
            pass
    return proc


@bp.route("/system/restart", methods=["POST"])
@auth_required
def restart():
    """重启面板：先派发一个完全独立的后台进程，再退出当前进程（更稳健，跨进程监督可用）。"""
    def _do():
        try:
            _spawn_detached()
        except Exception as e:
            print("[青豆面板] 重启派发失败:", e)
        time.sleep(1.2)
        os._exit(0)
    threading.Thread(target=_do, daemon=True).start()
    return json_ok(msg="正在重启服务")


@bp.route("/system/stop", methods=["POST"])
@auth_required
def stop():
    """关闭面板服务：先返回响应，再退出进程。"""
    def _do():
        time.sleep(0.6)
        os._exit(0)
    threading.Thread(target=_do, daemon=True).start()
    return json_ok(msg="正在关闭服务")


@bp.route("/system/start-daemon", methods=["POST"])
@auth_required
def start_daemon():
    """以守护进程方式启动面板（脱离终端，后台常驻）。若端口已占用则视为已在运行。"""
    port = config.get_setting("port", "5700")
    if _port_listening(port):
        return json_err("服务已在运行（端口 %s 已被占用）" % port)
    try:
        _spawn_detached()
        return json_ok({"msg": "已尝试以守护进程方式启动，日志见 data/daemon.log"})
    except Exception as e:
        return json_err(f"启动守护进程失败: {e}")


@bp.route("/system/reload_scheduler", methods=["POST"])
@auth_required
def reload_scheduler():
    scheduler.reload_all()
    return json_ok(msg="调度器已重载")


# ============ 备份 / 恢复（导出全部设置项目） ============
# 注：脚本以文件形式存于 data/scripts，由备份的 files 段负责；DB 中的 scripts 表已废弃不再写入，故不在此列出。
BACKUP_TABLES = ["settings", "tasks", "subscriptions", "environments",
                 "notifications", "ai_configs", "dependencies"]


@bp.route("/system/backup", methods=["GET"])
@auth_required
def backup_export():
    """导出全部设置项目为 JSON（运行参数、任务、订阅、变量、通知、AI 配置、依赖记录、脚本内容）。"""
    payload = {
        "panel": config.PANEL_NAME,
        "version": config.PANEL_VERSION,
        "exported_at": datetime.now().isoformat(timespec="seconds"),
        "schema_version": 1,
        "data": {},
    }
    for t in BACKUP_TABLES:
        try:
            rows = db.query(f"SELECT * FROM {t}")
            payload["data"][t] = [dict(r) for r in rows]
        except Exception:
            payload["data"][t] = []
    # 同时备份 data/scripts 下的真实脚本文件内容（此前仅备份了未使用的 scripts 表，存在磁盘上的脚本本身并未导出）
    try:
        files = []
        for root, _d, files_in in os.walk(SCRIPTS_DIR):
            for fn in files_in:
                if fn.endswith((".py", ".js", ".sh", ".txt", ".md", ".json")):
                    fp = os.path.join(root, fn)
                    try:
                        with open(fp, "r", encoding="utf-8", errors="replace") as sf:
                            content = sf.read()
                        rel = os.path.relpath(fp, SCRIPTS_DIR).replace("\\", "/")
                        files.append({"path": rel, "content": content})
                    except Exception:
                        pass
        payload["files"] = files
    except Exception:
        payload["files"] = []
    body = _json.dumps(payload, ensure_ascii=False, indent=2)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    return Response(body, mimetype="application/json",
                    headers={"Content-Disposition": f"attachment; filename=qingdou-backup-{ts}.json"})


@bp.route("/system/backup/db", methods=["GET"])
@auth_required
def backup_db_file():
    """直接下载数据库文件（含日志等完整数据）。"""
    from core import db as _db
    if not os.path.exists(_db.DB_PATH):
        return json_err("数据库文件不存在")
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    return send_file(_db.DB_PATH, as_attachment=True,
                    download_name=f"qingdou-{ts}.db", mimetype="application/octet-stream")


@bp.route("/system/restore", methods=["POST"])
@auth_required
def backup_restore():
    """从备份 JSON 恢复全部设置项目（整表替换，覆盖当前配置）。"""
    b = get_json_body()
    data = b.get("data")
    if not isinstance(data, dict):
        return json_err("备份文件格式不正确（缺少 data 字段）")
    for t in BACKUP_TABLES:
        rows = data.get(t)
        if not rows:
            continue
        if t == "settings":
            for row in rows:
                if not isinstance(row, dict):
                    continue
                k = row.get("key")
                if k is not None:
                    config.set_setting(k, row.get("value"))
            continue
        # 仅允许本表真实存在的列（白名单），列名须符合标识符规范，杜绝不受信 JSON 的列名注入
        try:
            allowed = {r["name"] for r in db.query(f"PRAGMA table_info({t})")}
        except Exception:
            continue
        try:
            db.execute(f"DELETE FROM {t}")
        except Exception:
            pass
        for row in rows:
            if not isinstance(row, dict):
                continue
            cols = [c for c in row.keys()
                    if c in allowed and re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", str(c))]
            if not cols:
                continue
            ph = ",".join("?" for _ in cols)
            colsql = ",".join(cols)
            db.execute(f"INSERT INTO {t}({colsql}) VALUES({ph})", [row[c] for c in cols])
    try:
        scheduler.reload_all()
    except Exception:
        pass
    # 恢复磁盘上的脚本文件（按相对路径写回 data/scripts，防止越权写其它目录）
    files = data.get("files")
    if isinstance(files, list):
        for fobj in files:
            if not isinstance(fobj, dict):
                continue
            rel = (fobj.get("path") or "").strip().replace("\\", "/")
            if not rel or ".." in rel.split("/"):
                continue
            dest = os.path.normpath(os.path.join(SCRIPTS_DIR, rel))
            if not dest.startswith(os.path.normpath(SCRIPTS_DIR)):
                continue
            try:
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                with open(dest, "w", encoding="utf-8") as wf:
                    wf.write(fobj.get("content", ""))
            except Exception:
                pass
    return json_ok(msg="已从备份恢复（已替换设置/任务/订阅/变量/通知/AI/依赖/脚本配置及脚本文件）")


# ============ GitHub 自动更新 ============
def _git(*args, timeout=60):
    try:
        r = subprocess.run(["git"] + list(args), cwd=BASE_DIR,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                           timeout=timeout, text=True)
        return r.returncode, r.stdout.strip(), r.stderr.strip()
    except FileNotFoundError:
        return 127, "", "git 未安装"
    except Exception as e:
        return 1, "", str(e)


def _git_update_core():
    """执行 git pull 并重启以应用更新。返回 (ok, msg)。"""
    rc, _, _ = _git("rev-parse", "--is-inside-work-tree")
    if rc != 0:
        return False, "当前不是 git 仓库，无法自动更新。请先 git clone 你的仓库到本目录。"
    repo = config.get_setting("github_repo", "") or ""
    branch = config.get_setting("github_branch", "main") or "main"
    # 使用 --autostash：有本地改动时自动暂存、拉取后自动还原；拉取失败也不会丢失改动。
    if repo:
        rc, out, err = _git("pull", "--autostash", repo, branch, timeout=180)
    else:
        rc, out, err = _git("pull", "--autostash", timeout=180)
    if rc != 0:
        return False, "更新失败: " + (err or out)[:300]
    return True, "已更新"


@bp.route("/system/update/check", methods=["GET"])
@auth_required
def update_check():
    repo = config.get_setting("github_repo", "") or ""
    branch = config.get_setting("github_branch", "main") or "main"
    has_git = _git("--version")[0] == 0
    rc, out, _ = _git("rev-parse", "--is-inside-work-tree")
    is_repo = (rc == 0 and out == "true")
    cur = ""
    if is_repo:
        _, cur, _ = _git("rev-parse", "HEAD")
        cur = (cur or "")[:12]
    remote_commit = ""
    behind = False
    if is_repo and repo and branch:
        rc2, out2, _ = _git("ls-remote", repo, branch, timeout=30)
        if rc2 == 0 and out2:
            parts = out2.split()
            remote_commit = parts[0][:12] if parts else ""
            behind = bool(remote_commit) and remote_commit != cur
    return json_ok({
        "has_git": has_git,
        "is_repo": is_repo,
        "current_commit": cur,
        "remote_commit": remote_commit,
        "behind": behind,
        "repo": repo,
        "branch": branch,
        "panel_version": config.PANEL_VERSION,
    })


@bp.route("/system/update/do", methods=["POST"])
@auth_required
def update_do():
    ok, msg = _git_update_core()
    if not ok:
        return json_err(msg)

    def _do():
        try:
            _spawn_detached()
        except Exception:
            pass
        time.sleep(1.2)
        os._exit(0)

    threading.Thread(target=_do, daemon=True).start()
    return json_ok(msg="已拉取更新，正在重启以应用新版本")


def auto_update_pull():
    """供调度器自动更新调用：成功则拉取并重启。"""
    ok, _msg = _git_update_core()
    if not ok:
        return
    threading.Thread(target=lambda: (_spawn_detached(), time.sleep(1.2), os._exit(0)),
                     daemon=True).start()
