"""青豆面板 - 脚本文件管理（基于 data/scripts 目录）。"""
import os
import json
from flask import request
from core import config
from core import db
from routes import bp, json_ok, json_err, auth_required, get_json_body

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS_DIR = os.path.join(BASE_DIR, "data", "scripts")


def _safe_path(name):
    """确保路径落在 SCRIPTS_DIR 内，避免越权。"""
    name = (name or "").strip().replace("\\", "/")
    full = os.path.normpath(os.path.join(SCRIPTS_DIR, name))
    if not full.startswith(os.path.normpath(SCRIPTS_DIR)):
        return None
    return full


def _list_scripts():
    out = []
    for root, _dirs, files in os.walk(SCRIPTS_DIR):
        for fn in files:
            if fn.endswith((".py", ".js", ".sh", ".txt", ".md", ".json")):
                fp = os.path.join(root, fn)
                rel = os.path.relpath(fp, SCRIPTS_DIR)
                out.append({
                    "name": rel.replace("\\", "/"),
                    "size": os.path.getsize(fp),
                    "mtime": os.path.getmtime(fp),
                })
    out.sort(key=lambda x: x["name"])
    return out


@bp.route("/scripts", methods=["GET"])
@auth_required
def list_scripts():
    return json_ok(_list_scripts())


@bp.route("/scripts/<path:name>", methods=["GET"])
@auth_required
def read_script(name):
    fp = _safe_path(name)
    if not fp or not os.path.exists(fp):
        return json_err("文件不存在")
    with open(fp, "r", encoding="utf-8", errors="replace") as f:
        content = f.read()
    return json_ok({"name": name, "content": content})


@bp.route("/scripts", methods=["POST"])
@auth_required
def create_script():
    b = get_json_body()
    name = (b.get("name") or "").strip()
    content = b.get("content", "")
    if not name:
        return json_err("文件名不能为空")
    fp = _safe_path(name)
    if not fp:
        return json_err("非法文件名")
    os.makedirs(os.path.dirname(fp), exist_ok=True)
    if os.path.exists(fp):
        return json_err("文件已存在")
    with open(fp, "w", encoding="utf-8") as f:
        f.write(content)
    return json_ok(msg="创建成功")


@bp.route("/scripts/<path:name>", methods=["PUT"])
@auth_required
def update_script(name):
    b = get_json_body()
    content = b.get("content", "")
    fp = _safe_path(name)
    if not fp:
        return json_err("非法文件名")
    os.makedirs(os.path.dirname(fp), exist_ok=True)
    with open(fp, "w", encoding="utf-8") as f:
        f.write(content)
    return json_ok(msg="保存成功")


@bp.route("/scripts/<path:name>", methods=["DELETE"])
@auth_required
def delete_script(name):
    fp = _safe_path(name)
    if not fp or not os.path.exists(fp):
        return json_err("文件不存在")
    os.remove(fp)
    return json_ok(msg="删除成功")


@bp.route("/scripts/<path:name>/run", methods=["POST"])
@auth_required
def run_script(name):
    fp = _safe_path(name)
    if not fp or not os.path.exists(fp):
        return json_err("文件不存在")
    rel = os.path.relpath(fp, BASE_DIR).replace("\\", "/")
    ext = os.path.splitext(fp)[1]
    if ext == ".js":
        cmd = f'node "{rel}"'
    elif ext == ".sh":
        cmd = f'bash "{rel}"'
    else:
        cmd = f'python "{rel}"'
    res = __import__("core.executor", fromlist=["executor"]).submit(
        cmd, task_name=f"脚本:{name}", kind="task", lock_key=f"script:{name}")
    return json_ok({"status": res}, msg="已提交执行")
