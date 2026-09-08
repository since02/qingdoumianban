"""青豆面板 - 应用入口（绿色可移动，单进程，内存友好）。"""
import os
import subprocess
import sys
import time

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

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
    import routes.yybgo
    import routes.users
    import routes.files
    import routes.jdcookie
    from routes import bp
    app.register_blueprint(bp)
    app.register_blueprint(routes.yybgo.yyb_bp)


def bootstrap():
    db.init_db()
    sched_mod.reload_all()


def _serve_with_retry(app, port, max_retries=30, retry_interval=1.0):
    """启动 HTTP 服务；若端口暂被占用（如重启交接期、或他进程占用）则重试。
    监听地址取自设置 host（默认 0.0.0.0，可改 127.0.0.1 仅本机）。
    端口持续不可用会打印明确错误并退出，便于排查。"""
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
    # 重试耗尽，明确失败原因
    print(f"[青豆面板] 端口 {port} 持续不可用，面板启动失败。请检查："
          f"1) 是否有其他程序占用该端口（如另一个面板实例）；"
          f"2) 系统设置里的端口/host 是否正确。错误详情: {last_err}")
    raise last_err


if __name__ == "__main__":
    _register_routes()
    bootstrap()
    port = int(config.get_setting("port", "5700") or 5700)
    print(f"青豆面板已启动: http://127.0.0.1:{port}  (默认账号 admin / adminadmin)")
    _serve_with_retry(app, port)
