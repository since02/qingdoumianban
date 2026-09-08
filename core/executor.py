"""青豆面板 - 脚本执行引擎（支持 py/js/命令，限并发队列，流式写盘，内存友好）。"""
import os
import sys
import time
import uuid
import queue
import threading
import subprocess
from core import db, config

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
SCRIPTS_DIR = os.path.join(DATA_DIR, "scripts")
LOGS_DIR = os.path.join(DATA_DIR, "logs")

# 并发队列：工作线程池从队列取任务；超额任务进入队列等待，不再被丢弃。
_queue = queue.Queue()
_active = {}            # run_id -> {task_id, task_name, sub_id, kind, started_at, started_iso}
_queue_lock = {}        # lock_key -> True（运行中或排队中的去重标记）
_lock = threading.Lock()
_workers = []
_workers_n = 0


def get_python_path():
    p = config.get_setting("python_path", "")
    if p and os.path.exists(p):
        return p
    return sys.executable


def get_node_path():
    p = config.get_setting("node_path", "")
    if p and os.path.exists(p):
        return p
    return "node"


def _resolve_script_ref(token):
    """将脚本引用解析为绝对路径；支持裸名、相对面板根目录、相对脚本目录、绝对路径。"""
    token = (token or "").strip().strip('"').strip("'")
    if not token:
        return token
    if os.path.isabs(token) and os.path.exists(token):
        return token
    rel_base = os.path.normpath(os.path.join(BASE_DIR, token))
    if os.path.exists(rel_base):
        return rel_base
    rel_scr = os.path.normpath(os.path.join(SCRIPTS_DIR, token))
    if os.path.exists(rel_scr):
        return rel_scr
    return token


def _quote_if_needed(p):
    p = (p or "").strip()
    if len(p) >= 2 and ((p[0] == '"' and p[-1] == '"') or (p[0] == "'" and p[-1] == "'")):
        return p
    if " " in p or (os.name == "nt" and ("(" in p or ")" in p)):
        return f'"{p}"'
    return p


def resolve_command(command):
    """把用户输入的命令解析成可直接 shell 执行的字符串。"""
    cmd = (command or "").strip()
    if not cmd:
        return cmd
    low = cmd.lower()

    def _interp_branch(kw, interp):
        rest = cmd.split(None, 1)[1].strip()
        parts = rest.split(None, 1)
        script = _resolve_script_ref(parts[0])
        rest2 = ((" " + parts[1]) if len(parts) > 1 else "")
        return f'{_quote_if_needed(interp)} {_quote_if_needed(script)}{rest2}'

    if low.startswith("task "):
        rest = cmd.split(None, 1)[1].strip()
        if rest.endswith(".js"):
            return _interp_branch("node ", get_node_path())
        if rest.endswith(".sh"):
            return f'bash {_quote_if_needed(_resolve_script_ref(rest))}'
        return _interp_branch("python ", get_python_path())
    if low.startswith("python ") or low.startswith("python3 ") or low.startswith("py "):
        return _interp_branch("python ", get_python_path())
    if low.startswith("node ") or low.startswith("nodejs "):
        return _interp_branch("node ", get_node_path())
    if low.startswith("bash ") or low.startswith("sh "):
        return _interp_branch("bash ", "bash")
    return cmd


def build_env():
    """合并系统环境与已启用的环境变量。"""
    env = os.environ.copy()
    rows = db.query("SELECT name,value FROM environments WHERE status=1")
    for r in rows:
        env[str(r["name"])] = str(r["value"] or "")
    return env


def make_log_path(prefix):
    os.makedirs(LOGS_DIR, exist_ok=True)
    ts = time.strftime("%Y%m%d_%H%M%S")
    return os.path.join(LOGS_DIR, f"{prefix}_{ts}_{os.getpid()}.log")


def _kill_tree(proc):
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            import signal
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


def _run_streaming(cmd, log_path, env, cwd, timeout):
    start = time.time()
    flags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
    with open(log_path, "w", encoding="utf-8", errors="replace") as lf:
        lf.write(f"[青豆面板] 执行命令: {cmd}\n")
        lf.write(f"[青豆面板] 开始时间: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
        lf.flush()
        try:
            proc = subprocess.Popen(cmd, shell=True, stdout=lf, stderr=subprocess.STDOUT,
                                    env=env, cwd=cwd, creationflags=flags)
        except Exception as e:
            lf.write(f"[青豆面板][错误] 启动失败: {e}\n")
            return -1, time.time() - start, False
        timed_out = False
        try:
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            _kill_tree(proc)
            try:
                proc.wait(timeout=10)
            except Exception:
                pass
        rc = proc.returncode
        lf.write(f"[青豆面板] 结束时间: {time.strftime('%Y-%m-%d %H:%M:%S')}  退出码: {rc}\n")
        if timed_out:
            lf.write("[青豆面板][超时] 任务超过时间限制已被终止\n")
    return rc, time.time() - start, timed_out


def _run_and_log(command, task_id=None, task_name=None, sub_id=None,
                 notify=0, notify_type=None, timeout=None, kind="task"):
    log_path = make_log_path("task" if kind == "task" else "sub")
    log_id = db.execute(
        "INSERT INTO logs(task_id,task_name,sub_id,kind,log_file,started_at) "
        "VALUES(?,?,?,?,?,datetime('now','localtime'))",
        (task_id, task_name, sub_id, kind, log_path),
    )
    default_timeout = int(config.get_setting("task_timeout", "3600") or 3600)
    timeout = timeout or default_timeout
    resolved = resolve_command(command)
    try:
        rc, duration, timed_out = _run_streaming(resolved, log_path, build_env(), BASE_DIR, timeout)
    except Exception as e:
        rc, duration, timed_out = -1, 0, False
        with open(log_path, "a", encoding="utf-8", errors="replace") as lf:
            lf.write(f"[青豆面板][异常] {e}\n")
    status = "timeout" if timed_out else ("success" if rc == 0 else "failed")
    db.execute(
        "UPDATE logs SET finished_at=datetime('now','localtime'),status=?,duration=? WHERE id=?",
        (status, round(duration, 2), log_id),
    )
    if task_id:
        db.execute(
            "UPDATE tasks SET last_run=datetime('now','localtime'),last_status=?,last_duration=? WHERE id=?",
            (status, round(duration, 2), task_id),
        )
    if sub_id:
        db.execute(
            "UPDATE subscriptions SET last_sync=datetime('now','localtime'),last_status=? WHERE id=?",
            (status, sub_id),
        )
    if notify:
        try:
            from core.notifier import notify_task_result
            notify_task_result(task_name or "青豆任务", status, log_path, notify_type)
        except Exception as e:
            with open(log_path, "a", encoding="utf-8", errors="replace") as lf:
                lf.write(f"[青豆面板][通知失败] {e}\n")
    return status


def _worker():
    """工作线程：循环从队列取任务执行，直到收到哨兵 None。"""
    while True:
        item = _queue.get()
        if item is None:
            _queue.task_done()
            break
        run_id, fn, lock_key = item
        try:
            _active[run_id] = {
                "run_id": run_id,
                "task_id": fn._qd_task_id,
                "task_name": fn._qd_task_name,
                "sub_id": fn._qd_sub_id,
                "kind": fn._qd_kind,
                "started_at": time.time(),
                "started_iso": time.strftime("%Y-%m-%d %H:%M:%S"),
            }
            fn()
        except Exception:
            pass
        finally:
            _active.pop(run_id, None)
            if lock_key:
                _queue_lock.pop(lock_key, None)
            try:
                _queue.task_done()
            except Exception:
                pass


def _ensure_workers(n):
    global _workers_n
    with _lock:
        while _workers_n < n:
            t = threading.Thread(target=_worker, daemon=True, name=f"qd-worker-{_workers_n}")
            t.start()
            _workers.append(t)
            _workers_n += 1


def submit(command, task_id=None, task_name=None, sub_id=None,
           notify=0, notify_type=None, timeout=None, kind="task", lock_key=None):
    """提交一次执行（异步，立即返回 queued / skipped）。

    - 若显式传入 lock_key 且当前已有同 key 任务在运行或排队，则跳过（skipped），避免重叠。
    - 否则进入并发队列；超过 max_concurrent 的任务排队等待，不再被丢弃。
    """
    if lock_key is None:
        if task_id:
            lock_key = f"t{task_id}"
        elif sub_id:
            lock_key = f"s{sub_id}"
        else:
            lock_key = None

    if lock_key:
        with _lock:
            if _queue_lock.get(lock_key):
                return "skipped"
            _queue_lock[lock_key] = True

    maxc = int(config.get_setting("max_concurrent", "5") or 5)
    _ensure_workers(max(1, maxc))

    def _job():
        return _run_and_log(command, task_id, task_name, sub_id, notify, notify_type, timeout, kind)
    _job._qd_task_id = task_id
    _job._qd_task_name = task_name
    _job._qd_sub_id = sub_id
    _job._qd_kind = kind

    run_id = uuid.uuid4().hex
    _queue.put((run_id, _job, lock_key))
    return "queued"


def get_active():
    """返回运行中/排队中的任务状态，供前端展示。"""
    maxc = int(config.get_setting("max_concurrent", "5") or 5)
    running = [v for v in _active.values()]
    # 排队中的任务 id（尚未被工作线程取出执行的）
    queued_ids = []
    for item in list(_queue.queue):
        if item and item[1] is not None:
            tid = item[1]._qd_task_id
            if tid is not None:
                queued_ids.append(tid)
    return {
        "running": running,
        "queued": _queue.qsize(),
        "queued_task_ids": queued_ids,
        "max_concurrent": maxc,
    }


def run_now(command, timeout=None):
    """同步立即执行（用于测试/一次性运行），返回 (status, log_path)。"""
    log_path = make_log_path("run")
    default_timeout = int(config.get_setting("task_timeout", "3600") or 3600)
    timeout = timeout or default_timeout
    resolved = resolve_command(command)
    rc, duration, timed_out = _run_streaming(resolved, log_path, build_env(), BASE_DIR, timeout)
    status = "timeout" if timed_out else ("success" if rc == 0 else "failed")
    return status, log_path
