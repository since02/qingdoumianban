"""青豆面板 - 定时任务路由。"""
import os
import time
from flask import request
from core import db, config, scheduler, executor
from core.cron import is_valid_cron, next_run_time
from routes import bp, json_ok, json_err, auth_required, get_json_body


def _sync_task_scheduler(task):
    if task["status"] == 1:
        scheduler.add_task_job(task)
    else:
        scheduler.remove_task_job(task["id"])


@bp.route("/tasks", methods=["GET"])
@auth_required
def list_tasks():
    search = (request.args.get("search") or "").strip().lower()
    status = (request.args.get("status") or "").strip()  # "" / "0" / "1"
    rows = [dict(r) for r in db.query("SELECT * FROM tasks ORDER BY id DESC")]
    if search:
        rows = [r for r in rows
                if search in (r.get("name") or "").lower()
                or search in (r.get("command") or "").lower()]
    if status in ("0", "1"):
        rows = [r for r in rows if str(r.get("status")) == status]
    out = []
    for r in rows:
        try:
            r["next_run"] = next_run_time(r["schedule"]).strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            r["next_run"] = ""
        out.append(r)
    return json_ok(out)


@bp.route("/tasks/batch", methods=["POST"])
@auth_required
def batch_tasks():
    """批量操作：enable / disable / run / delete。"""
    b = get_json_body()
    ids = b.get("ids") or []
    action = b.get("action")
    if not isinstance(ids, list) or not ids:
        return json_err("请先选择任务")
    if action not in ("enable", "disable", "run", "delete"):
        return json_err("未知操作")
    ok = 0
    for raw in ids:
        try:
            tid = int(raw)
        except (TypeError, ValueError):
            continue
        task = db.query_one("SELECT * FROM tasks WHERE id=?", (tid,))
        if not task:
            continue
        if action == "delete":
            db.execute("DELETE FROM tasks WHERE id=?", (tid,))
            scheduler.remove_task_job(tid)
            ok += 1
        elif action in ("enable", "disable"):
            st = 1 if action == "enable" else 0
            db.execute("UPDATE tasks SET status=? WHERE id=?", (st, tid))
            _sync_task_scheduler(task)
            ok += 1
        elif action == "run":
            executor.submit(
                task["command"], task_id=tid, task_name=task["name"],
                notify=task["notify"], notify_type=task["notify_type"], kind="task",
                lock_key=f"task:{tid}",
            )
            ok += 1
    return json_ok(msg=f"已处理 {ok} 个任务")


@bp.route("/tasks/active", methods=["GET"])
@auth_required
def tasks_active():
    return json_ok(executor.get_active())


@bp.route("/tasks/<int:tid>", methods=["GET"])
@auth_required
def get_task(tid):
    task = db.query_one("SELECT * FROM tasks WHERE id=?", (tid,))
    if not task:
        return json_err("任务不存在")
    d = dict(task)
    try:
        d["next_run"] = next_run_time(task["schedule"]).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        d["next_run"] = ""
    return json_ok(d)


@bp.route("/tasks", methods=["POST"])
@auth_required
def create_task():
    b = get_json_body()
    name = (b.get("name") or "").strip()
    command = (b.get("command") or "").strip()
    schedule = (b.get("schedule") or "0 0 * * *").strip()
    if not name or not command:
        return json_err("名称与命令不能为空")
    if not is_valid_cron(schedule):
        return json_err("cron 表达式无效")
    tid = db.execute(
        "INSERT INTO tasks(name,command,schedule,status,notify,notify_type) "
        "VALUES(?,?,?,?,?,?)",
        (name, command, schedule, int(b.get("status", 1)), int(b.get("notify", 0)),
         b.get("notify_type")),
    )
    task = db.query_one("SELECT * FROM tasks WHERE id=?", (tid,))
    _sync_task_scheduler(task)
    return json_ok({"id": tid}, msg="创建成功")


@bp.route("/tasks/<int:tid>", methods=["PUT"])
@auth_required
def update_task(tid):
    b = get_json_body()
    task = db.query_one("SELECT * FROM tasks WHERE id=?", (tid,))
    if not task:
        return json_err("任务不存在")
    name = b.get("name", task["name"])
    command = b.get("command", task["command"])
    schedule = b.get("schedule", task["schedule"])
    if not is_valid_cron(schedule):
        return json_err("cron 表达式无效")
    db.execute(
        "UPDATE tasks SET name=?,command=?,schedule=?,status=?,notify=?,"
        "notify_type=?,updated_at=datetime('now','localtime') WHERE id=?",
        (name, command, schedule, int(b.get("status", task["status"])),
         int(b.get("notify", task["notify"])), b.get("notify_type", task["notify_type"]), tid),
    )
    task = db.query_one("SELECT * FROM tasks WHERE id=?", (tid,))
    _sync_task_scheduler(task)
    return json_ok(msg="更新成功")


@bp.route("/tasks/<int:tid>", methods=["DELETE"])
@auth_required
def delete_task(tid):
    db.execute("DELETE FROM tasks WHERE id=?", (tid,))
    scheduler.remove_task_job(tid)
    return json_ok(msg="删除成功")


@bp.route("/tasks/<int:tid>/enable", methods=["POST"])
@auth_required
def enable_task(tid):
    status = int((get_json_body().get("status", 1)))
    db.execute("UPDATE tasks SET status=? WHERE id=?", (status, tid))
    task = db.query_one("SELECT * FROM tasks WHERE id=?", (tid,))
    _sync_task_scheduler(task)
    return json_ok(msg="操作成功")


@bp.route("/tasks/<int:tid>/run", methods=["POST"])
@auth_required
def run_task(tid):
    task = db.query_one("SELECT * FROM tasks WHERE id=?", (tid,))
    if not task:
        return json_err("任务不存在")
    res = executor.submit(
        task["command"], task_id=tid, task_name=task["name"],
        notify=task["notify"], notify_type=task["notify_type"], kind="task",
        lock_key=f"task:{tid}",
    )
    return json_ok({"status": res}, msg="已提交执行")


@bp.route("/tasks/run_once", methods=["POST"])
@auth_required
def run_once():
    b = get_json_body()
    command = (b.get("command") or "").strip()
    if not command:
        return json_err("命令不能为空")
    res = executor.submit(command, task_name=b.get("name", "一次性任务"), kind="task")
    return json_ok({"status": res}, msg="已提交执行")


@bp.route("/logs", methods=["GET"])
@auth_required
def list_logs():
    limit = int(request.args.get("limit", 50))
    rows = db.query("SELECT * FROM logs ORDER BY id DESC LIMIT ?", (limit,))
    out = []
    for r in rows:
        d = dict(r)
        d["size"] = os.path.getsize(r["log_file"]) if r["log_file"] and os.path.exists(r["log_file"]) else 0
        out.append(d)
    return json_ok(out)


@bp.route("/tasks/<int:tid>/logs", methods=["GET"])
@auth_required
def task_logs(tid):
    limit = int(request.args.get("limit", 30))
    rows = db.query("SELECT * FROM logs WHERE task_id=? ORDER BY id DESC LIMIT ?", (tid, limit))
    out = []
    for r in rows:
        d = dict(r)
        d["size"] = os.path.getsize(r["log_file"]) if r["log_file"] and os.path.exists(r["log_file"]) else 0
        out.append(d)
    return json_ok(out)


@bp.route("/logs/<int:lid>", methods=["GET"])
@auth_required
def get_log(lid):
    row = db.query_one("SELECT * FROM logs WHERE id=?", (lid,))
    if not row or not row["log_file"] or not os.path.exists(row["log_file"]):
        return json_err("日志不存在")
    with open(row["log_file"], "r", encoding="utf-8", errors="replace") as f:
        content = f.read()
    return json_ok({"content": content, "log": dict(row)})
