"""青豆面板 - 文件管理器（限定在 data/ 目录内，防越权）。"""
import os
import time
from flask import request
from core import db, config
from routes import bp, json_ok, json_err, auth_required, get_json_body

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
EDITABLE_EXT = (".py", ".js", ".sh", ".txt", ".md", ".json", ".yaml", ".yml", ".ini",
                ".conf", ".cfg", ".log", ".csv", ".html", ".css", ".xml", ".toml")

MAX_READ = 2 * 1024 * 1024  # 单次读取上限 2MB


def _safe(path):
    """将相对 data/ 的路径解析为绝对路径，并确保不越出 DATA_DIR。"""
    if not path:
        return None
    path = path.strip().replace("\\", "/")
    if ".." in path.split("/"):
        return None
    full = os.path.normpath(os.path.join(DATA_DIR, path))
    if not full.startswith(os.path.normpath(DATA_DIR)):
        return None
    return full


@bp.route("/files/tree", methods=["GET"])
@auth_required
def files_tree():
    rel = (request.args.get("path", "") or "").strip().replace("\\", "/")
    base = _safe(rel)
    if base is None:
        return json_err("非法路径")
    if not os.path.exists(base):
        os.makedirs(base, exist_ok=True)
    entries = []
    try:
        for name in sorted(os.listdir(base)):
            full = os.path.join(base, name)
            is_dir = os.path.isdir(full)
            entries.append({
                "name": name,
                "path": (rel + "/" + name).lstrip("/"),
                "is_dir": is_dir,
                "size": 0 if is_dir else os.path.getsize(full),
                "mtime": os.path.getmtime(full),
            })
    except Exception as e:
        return json_err("读取目录失败: " + str(e))
    entries.sort(key=lambda x: (not x["is_dir"], x["name"].lower()))
    return json_ok({"path": rel, "entries": entries})


@bp.route("/files/content", methods=["GET"])
@auth_required
def files_content():
    rel = request.args.get("path", "") or ""
    full = _safe(rel)
    if not full or not os.path.isfile(full):
        return json_err("文件不存在")
    if not full.lower().endswith(EDITABLE_EXT):
        return json_err("该类型文件不支持在线编辑")
    try:
        with open(full, "r", encoding="utf-8", errors="replace") as f:
            content = f.read(MAX_READ)
    except Exception as e:
        return json_err("读取失败: " + str(e))
    return json_ok({"path": rel, "content": content, "size": os.path.getsize(full)})


@bp.route("/files/write", methods=["POST"])
@auth_required
def files_write():
    b = get_json_body()
    rel = (b.get("path") or "").strip()
    content = b.get("content", "")
    full = _safe(rel)
    if not full:
        return json_err("非法路径")
    if not full.lower().endswith(EDITABLE_EXT):
        return json_err("该类型文件不支持在线编辑")
    try:
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w", encoding="utf-8") as f:
            f.write(content)
    except Exception as e:
        return json_err("写入失败: " + str(e))
    return json_ok(msg="已保存")


@bp.route("/files/mkdir", methods=["POST"])
@auth_required
def files_mkdir():
    b = get_json_body()
    rel = (b.get("path") or "").strip()
    full = _safe(rel)
    if not full:
        return json_err("非法路径")
    try:
        os.makedirs(full, exist_ok=True)
    except Exception as e:
        return json_err("创建失败: " + str(e))
    return json_ok(msg="已创建目录")


@bp.route("/files/delete", methods=["POST"])
@auth_required
def files_delete():
    b = get_json_body()
    rel = (b.get("path") or "").strip()
    full = _safe(rel)
    if not full or not os.path.exists(full):
        return json_err("文件/目录不存在")
    try:
        if os.path.isdir(full):
            os.rmdir(full) if not os.listdir(full) else _rmtree(full)
        else:
            os.remove(full)
    except Exception as e:
        return json_err("删除失败: " + str(e))
    return json_ok(msg="已删除")


def _rmtree(path):
    import shutil
    shutil.rmtree(path, ignore_errors=True)
