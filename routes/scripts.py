"""青豆面板 - 脚本文件管理（data/scripts + data/subs 订阅脚本双目录）。"""
import os
import json
from flask import request
from core import config
from core import db
from routes import bp, json_ok, json_err, auth_required, get_json_body

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS_DIR = os.path.join(BASE_DIR, "data", "scripts")
SUBS_DIR = os.path.join(BASE_DIR, "data", "subs")
# 虚拟前缀：subs/xxx 映射到 data/subs/xxx（订阅拉取的脚本）
SUBS_PREFIX = "subs/"


def _safe_path(name):
    """确保路径落在 SCRIPTS_DIR 或 SUBS_DIR 内，返回 (full_path, base_dir, rel)；越权返回 None。"""
    name = (name or "").strip().replace("\\", "/").lstrip("/")
    if name.startswith(SUBS_PREFIX):
        base, rel = SUBS_DIR, name[len(SUBS_PREFIX):]
    else:
        base, rel = SCRIPTS_DIR, name
    full = os.path.normpath(os.path.join(base, rel))
    if not (full == os.path.normpath(base) or full.startswith(os.path.normpath(base) + os.sep)):
        return None
    return (full, base, rel)


def _list_scripts():
    out = []
    for base, prefix in ((SCRIPTS_DIR, ""), (SUBS_DIR, SUBS_PREFIX)):
        if not os.path.isdir(base):
            continue
        for root, dirs, files in os.walk(base):
            # 跳过 .git 等仓库内部目录
            dirs[:] = [d for d in dirs if d not in (".git", "__pycache__", "node_modules")]
            for fn in files:
                if fn.endswith((".py", ".js", ".sh", ".txt", ".md", ".json")):
                    fp = os.path.join(root, fn)
                    rel = os.path.relpath(fp, base).replace("\\", "/")
                    try:
                        size = os.path.getsize(fp)
                        mtime = os.path.getmtime(fp)
                    except OSError:
                        continue
                    out.append({"name": prefix + rel, "size": size, "mtime": mtime})
    out.sort(key=lambda x: x["name"])
    return out


@bp.route("/scripts", methods=["GET"])
@auth_required
def list_scripts():
    dir_filter = (request.args.get("dir") or "").strip()      # "" / "scripts" / "subs"
    q = (request.args.get("q") or "").strip().lower()          # 文件名过滤
    out = _list_scripts()
    if dir_filter == "scripts":
        out = [s for s in out if not s["name"].startswith(SUBS_PREFIX)]
    elif dir_filter == "subs":
        out = [s for s in out if s["name"].startswith(SUBS_PREFIX)]
    if q:
        out = [s for s in out if q in s["name"].lower()]
    return json_ok(out)


@bp.route("/scripts/search", methods=["GET"])
@auth_required
def search_scripts():
    """全文搜索：同时匹配文件名与文件内容（含行号与片段），对标青龙脚本搜索。"""
    q = (request.args.get("q") or "").strip()
    if not q:
        return json_ok({"name_matches": [], "content_matches": []})
    ql = q.lower()
    all_scripts = _list_scripts()
    name_matches = [s for s in all_scripts if ql in s["name"].lower()]
    content_matches = []
    for s in all_scripts:
        sp = _safe_path(s["name"])
        if not sp or not os.path.isfile(sp[0]):
            continue
        try:
            with open(sp[0], "r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()
        except OSError:
            continue
        hits = []
        total = 0
        for i, line in enumerate(lines, 1):
            if ql in line.lower():
                total += 1
                if len(hits) < 5:
                    snippet = line.strip()
                    if len(snippet) > 200:
                        snippet = snippet[:200] + "…"
                    hits.append({"line": i, "text": snippet})
        if total:
            content_matches.append({"name": s["name"], "hits": hits, "total": total})
    return json_ok({"name_matches": name_matches, "content_matches": content_matches})


@bp.route("/scripts/<path:name>", methods=["GET"])
@auth_required
def read_script(name):
    sp = _safe_path(name)
    if not sp or not os.path.exists(sp[0]):
        return json_err("文件不存在")
    with open(sp[0], "r", encoding="utf-8", errors="replace") as f:
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
    sp = _safe_path(name)
    if not sp:
        return json_err("非法文件名")
    fp = sp[0]
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
    sp = _safe_path(name)
    if not sp:
        return json_err("非法文件名")
    fp = sp[0]
    os.makedirs(os.path.dirname(fp), exist_ok=True)
    with open(fp, "w", encoding="utf-8") as f:
        f.write(content)
    return json_ok(msg="保存成功")


@bp.route("/scripts/<path:name>", methods=["DELETE"])
@auth_required
def delete_script(name):
    sp = _safe_path(name)
    if not sp or not os.path.exists(sp[0]):
        return json_err("文件不存在")
    os.remove(sp[0])
    return json_ok(msg="删除成功")


@bp.route("/scripts/<path:name>/run", methods=["POST"])
@auth_required
def run_script(name):
    sp = _safe_path(name)
    if not sp or not os.path.exists(sp[0]):
        return json_err("文件不存在")
    fp, _base, rel = sp
    run_rel = os.path.relpath(fp, BASE_DIR).replace("\\", "/")
    ext = os.path.splitext(fp)[1]
    if ext == ".js":
        cmd = f'node "{run_rel}"'
    elif ext == ".sh":
        cmd = f'bash "{run_rel}"'
    else:
        cmd = f'python "{run_rel}"'
    res = __import__("core.executor", fromlist=["executor"]).submit(
        cmd, task_name=f"脚本:{name}", kind="task", lock_key=f"script:{name}")
    return json_ok({"status": res}, msg="已提交执行")
