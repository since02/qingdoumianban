"""青豆面板 - 应用入口（绿色可移动，单进程，内存友好）。"""
import os
import sys
import time

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

from flask import Flask, send_from_directory
from core import db, config
from core import scheduler as sched_mod

config.ensure_dirs()

app = Flask(__name__, static_folder=os.path.join(BASE_DIR, "static"), static_url_path="/static")


@app.route("/")
def index():
    return send_from_directory(os.path.join(BASE_DIR, "static"), "index.html")


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
    from routes import bp
    app.register_blueprint(bp)
    app.register_blueprint(routes.yybgo.yyb_bp)


def bootstrap():
    db.init_db()
    sched_mod.reload_all()


def _serve_with_retry(app, port, max_retries=20, retry_interval=0.5):
    """启动 HTTP 服务；若端口暂被占用（如重启交接期）则重试，直到成功或耗尽次数。
    监听地址取自设置 host（默认 0.0.0.0，可改 127.0.0.1 仅本机）。"""
    host = config.get_setting("host", "0.0.0.0") or "0.0.0.0"
    for attempt in range(max_retries):
        try:
            try:
                from waitress import serve
                serve(app, host=host, port=port, threads=8, ident="Qingdou")
                return
            except Exception:
                app.run(host=host, port=port, threaded=True, use_reloader=False)
                return
        except OSError as e:
            if attempt < max_retries - 1:
                print(f"[青豆面板] 端口 {port} 暂不可用（{e}），{retry_interval}s 后重试（{attempt+1}/{max_retries}）…")
                time.sleep(retry_interval)
            else:
                raise


if __name__ == "__main__":
    _register_routes()
    bootstrap()
    port = int(config.get_setting("port", "5700") or 5700)
    print(f"青豆面板已启动: http://127.0.0.1:{port}  (默认账号 admin / adminadmin)")
    _serve_with_retry(app, port)
