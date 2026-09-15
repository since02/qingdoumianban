"""青豆面板 - 应用入口（绿色可移动，单进程，内存友好）。"""
import os
import subprocess
import sys
import time

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

# 启动期就把 stdout/stderr 双写到 data/panel.log：
# 1) pythonw 无控制台时 sys.stdout 为 None，任何 print 都会抛异常导致进程静默退出（必须兜底）
# 2) 后台启动场景下，没有日志就无法排查"打不开"这类问题
class _Tee:
    """同时写原流与日志文件；任一失败都不影响另一个。"""

    def __init__(self, stream, f):
        self._s = stream
        self._f = f

    def write(self, data):
        for t in (self._s, self._f):
            if t is None:
                continue
            try:
                t.write(data)
                t.flush()
            except Exception:
                pass
        return len(data or "")

    def flush(self):
        for t in (self._s, self._f):
            if t is None:
                continue
            try:
                t.flush()
            except Exception:
                pass

    def isatty(self):
        return False

    def fileno(self):
        try:
            return self._s.fileno()
        except Exception:
            raise OSError("no fileno")


def _setup_log():
    try:
        _log_dir = os.path.join(BASE_DIR, "data")
        os.makedirs(_log_dir, exist_ok=True)
        f = open(os.path.join(_log_dir, "panel.log"), "a", encoding="utf-8", errors="replace")
        f.write(f"\n===== {time.strftime('%Y-%m-%d %H:%M:%S')} 进程启动 =====\n")
        f.flush()
        if sys.stdout is None or sys.stderr is None:
            sys.stdout = f if sys.stdout is None else sys.stdout
            sys.stderr = f if sys.stderr is None else sys.stderr
        else:
            sys.stdout = _Tee(sys.stdout, f)
            sys.stderr = _Tee(sys.stderr, f)
    except Exception:
        pass


_setup_log()

# 单实例守卫：若端口已被同机其他面板实例监听，则当前进程立即退出，
# 避免重复进程/僵尸堆积（排查中发现面板启动期可能被间接拉起一个"影子"子进程，
# 但只要保证"只有一个实例真正监听端口、其余自行退出"即可稳定可起可停）。
def _single_instance_guard():
    import socket
    try:
        port = int(config.get_setting("port", "5700") or 5700)
    except Exception:
        port = 5700
    s = socket.socket()
    s.settimeout(1)
    try:
        taken = s.connect_ex(("127.0.0.1", port)) == 0
    except Exception:
        taken = False
    finally:
        try:
            s.close()
        except Exception:
            pass
    if taken:
        try:
            with open(os.path.join(BASE_DIR, "data", "panel.log"), "a", encoding="utf-8", errors="replace") as lf:
                lf.write(f"[单实例] 端口 {port} 已被占用，pid={os.getpid()} 退出，避免重复实例\n")
        except Exception:
            pass
        os._exit(0)


from flask import Flask, send_from_directory
from core import db, config
from core import scheduler as sched_mod

config.ensure_dirs()

app = Flask(__name__, static_folder=os.path.join(BASE_DIR, "static"), static_url_path="/static")


def _cache_version():
    """取 git commit hash 前 8 位作为静态资源版本号；非 git 目录则用时间戳。"""
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=BASE_DIR, stderr=subprocess.DEVNULL, text=True,
        ).strip()
        if out:
            return out
    except Exception:
        pass
    return str(int(time.time()))


@app.route("/")
def index():
    path = os.path.join(BASE_DIR, "static", "index.html")
    try:
        with open(path, "r", encoding="utf-8") as f:
            html = f.read()
    except Exception:
        return send_from_directory(os.path.join(BASE_DIR, "static"), "index.html")
    html = html.replace("{{CACHE_VERSION}}", _cache_version())
    return html


@app.route("/healthz")
def healthz():
    return {"status": "ok", "panel": config.PANEL_NAME, "version": config.PANEL_VERSION}


def _register_routes():
    import routes.auth
    import routes.tasks
    import routes.scripts
    import routes.subscriptions
    import routes.dependencies
    import routes.environments
    import routes.notifications
    import routes.system
    import routes.ai
    import routes.compat
    import routes.users
    import routes.files
    import routes.jdcookie
    from routes import bp
    app.register_blueprint(bp)


def bootstrap():
    db.init_db()
    sched_mod.reload_all()


def _serve_with_retry(app, port, max_retries=10, retry_interval=1.0):
    """启动 HTTP 服务；若端口暂被占用（如重启交接期、或已有实例在运行）则短暂重试，
    仍不可用即视为"已有实例在跑"，当前进程优雅退出，避免重复进程/僵尸堆积。
    监听地址取自设置 host（默认 0.0.0.0，可改 127.0.0.1 仅本机）。"""
    host = config.get_setting("host", "0.0.0.0") or "0.0.0.0"
    last_err = None
    for attempt in range(max_retries):
        try:
            from waitress import serve
            print(f"青豆面板正在监听: http://{host}:{port}")
            serve(app, host=host, port=port, threads=8, ident="Qingdou")
            return
        except OSError as e:
            last_err = e
            print(f"[青豆面板] 端口 {port} 暂不可用: {e}（{attempt+1}/{max_retries}），{retry_interval}s 后重试…")
            time.sleep(retry_interval)
    # 端口持续被占用：说明已有面板实例在运行，当前进程退出（不再抛异常/堆积僵尸）
    print(f"[青豆面板] 端口 {port} 持续被占用，已有面板实例在运行，当前进程退出。")
    os._exit(0)


if __name__ == "__main__":
    _single_instance_guard()
    _register_routes()
    bootstrap()
    port = int(config.get_setting("port", "5700") or 5700)
    # 登记本进程 PID，供 panel_ctl stop 精准结束（避免误杀其它 python）
    try:
        with open(os.path.join(BASE_DIR, "data", "panel.pid"), "w", encoding="utf-8") as _pf:
            _pf.write(str(os.getpid()))
    except Exception:
        pass
    print(f"青豆面板已启动: http://127.0.0.1:{port}  (默认账号 admin / adminadmin)")
    _serve_with_retry(app, port)
