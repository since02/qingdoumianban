"""青豆面板 - 依赖安装（pip / npm / 系统包），后台执行并记录日志。"""
import os
import re
import time
import threading
from flask import request
from core import db, config
from core import executor as _exec
from routes import bp, json_ok, json_err, auth_required, get_json_body

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOGS_DIR = os.path.join(BASE_DIR, "data", "logs")

# 包名/参数白名单：仅允许常见包名与版本限定符，拦截 shell 元字符（; | & $ ` ( ) 等）
_SAFE_PKG = re.compile(r"^[A-Za-z0-9._@+!=<>:~/\-]+$")


def _validate_packages(packages):
    toks = (packages or "").split()
    bad = [t for t in toks if not _SAFE_PKG.match(t)]
    if bad:
        return None, "非法的包名或参数: " + " ".join(bad)
    return toks, None


def _install_worker(dep_id, dtype, command, log_path):
    with open(log_path, "w", encoding="utf-8", errors="replace") as lf:
        lf.write(f"[青豆面板] 安装依赖（{dtype}）: {' '.join(command)}\n")
        lf.flush()
        import subprocess
        try:
            # 以参数列表方式执行，shell=False，从根本上消除命令注入
            proc = subprocess.Popen(command, shell=False, stdout=lf, stderr=subprocess.STDOUT,
                                    cwd=BASE_DIR)
            proc.wait(timeout=600)
            rc = proc.returncode
        except subprocess.TimeoutExpired:
            rc = -2
            lf.write("[青豆面板][超时] 依赖安装超过 10 分钟被终止\n")
        except Exception as e:
            rc = -1
            lf.write(f"[青豆面板][错误] {e}\n")
    status = "success" if rc == 0 else "failed"
    db.execute("UPDATE dependencies SET status=?,log_file=? WHERE id=?", (status, log_path, dep_id))


@bp.route("/dependencies/install", methods=["POST"])
@auth_required
def install_dep():
    b = get_json_body()
    dtype = (b.get("dtype") or "pip").strip().lower()
    packages = (b.get("packages") or "").strip()
    if not packages:
        return json_err("请填写要安装的依赖")
    toks, err = _validate_packages(packages)
    if err:
        return json_err(err)
    if dtype == "pip":
        pip = (b.get("pip") or "").strip()
        base = [pip] if (pip and pip not in ("pip",)) else [_exec.get_python_path()]
        command = base + ["-m", "pip", "install"] + toks
    elif dtype == "npm":
        npm = (b.get("npm") or "npm").strip() or "npm"
        command = [npm, "install", "-g"] + toks
    elif dtype == "apt":
        command = ["apt-get", "install", "-y"] + toks
    else:
        return json_err("不支持的依赖类型")
    os.makedirs(LOGS_DIR, exist_ok=True)
    log_path = os.path.join(LOGS_DIR, f"dep_{time.strftime('%Y%m%d_%H%M%S')}.log")
    dep_id = db.execute(
        "INSERT INTO dependencies(dtype,name,version,status) VALUES(?,?,?,?)",
        (dtype, packages, "", "running"),
    )
    t = threading.Thread(target=_install_worker, args=(dep_id, dtype, command, log_path), daemon=True)
    t.start()
    return json_ok({"id": dep_id}, msg="已在后台开始安装")


@bp.route("/dependencies", methods=["GET"])
@auth_required
def list_deps():
    rows = db.query("SELECT * FROM dependencies ORDER BY id DESC LIMIT 100")
    out = []
    for r in rows:
        d = dict(r)
        d["size"] = os.path.getsize(r["log_file"]) if r["log_file"] and os.path.exists(r["log_file"]) else 0
        out.append(d)
    return json_ok(out)


@bp.route("/dependencies/<int:did>/log", methods=["GET"])
@auth_required
def dep_log(did):
    row = db.query_one("SELECT * FROM dependencies WHERE id=?", (did,))
    if not row or not row["log_file"] or not os.path.exists(row["log_file"]):
        return json_err("日志不存在")
    with open(row["log_file"], "r", encoding="utf-8", errors="replace") as f:
        content = f.read()
    return json_ok({"content": content, "dep": dict(row)})
