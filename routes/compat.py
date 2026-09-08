"""青豆面板 - 青龙兼容开放 API（envs / crons），便于外部工具对接。"""
from flask import request
from core import db
from routes import bp, auth_required, get_json_body
from core.cron import is_valid_cron
from core import scheduler, executor


def _ok(data):
    return {"code": 200, "message": "ok", "data": data}


def _err(msg):
    return {"code": 500, "message": msg, "data": None}


@bp.route("/envs", methods=["GET"])
@auth_required
def ql_envs():
    rows = db.query("SELECT * FROM environments ORDER BY id DESC")
    data = [{"id": r["id"], "name": r["name"], "value": r["value"],
             "remarks": r["remarks"], "status": r["status"]} for r in rows]
    return _ok(data)


@bp.route("/envs", methods=["POST"])
@auth_required
def ql_envs_add():
    b = get_json_body()
    name = (b.get("name") or "").strip()
    if not name:
        return _err("name 不能为空")
    db.execute("INSERT INTO environments(name,value,remarks,status) VALUES(?,?,?,?)",
               (name, b.get("value", ""), b.get("remarks", ""), int(b.get("status", 1))))
    return _ok({"id": db.query_one("SELECT last_insert_rowid() AS i")["i"]})


@bp.route("/crons", methods=["GET"])
@auth_required
def ql_crons():
    rows = db.query("SELECT * FROM tasks ORDER BY id DESC")
    data = [{"id": r["id"], "name": r["name"], "command": r["command"],
             "schedule": r["schedule"], "status": r["status"]} for r in rows]
    return _ok(data)


@bp.route("/crons", methods=["POST"])
@auth_required
def ql_crons_add():
    b = get_json_body()
    name = (b.get("name") or "").strip()
    command = (b.get("command") or "").strip()
    schedule = (b.get("schedule") or "0 0 * * *").strip()
    if not is_valid_cron(schedule):
        return _err("schedule 无效")
    tid = db.execute("INSERT INTO tasks(name,command,schedule,status) VALUES(?,?,?,1)",
                     (name, command, schedule))
    scheduler.add_task_job(db.query_one("SELECT * FROM tasks WHERE id=?", (tid,)))
    return _ok({"id": tid})


@bp.route("/crons/<int:tid>", methods=["PUT"])
@auth_required
def ql_crons_upd(tid):
    b = get_json_body()
    task = db.query_one("SELECT * FROM tasks WHERE id=?", (tid,))
    if not task:
        return _err("任务不存在")
    db.execute("UPDATE tasks SET name=?,command=?,schedule=? WHERE id=?",
               (b.get("name", task["name"]), b.get("command", task["command"]),
                b.get("schedule", task["schedule"]), tid))
    scheduler.add_task_job(db.query_one("SELECT * FROM tasks WHERE id=?", (tid,)))
    return _ok({"id": tid})


@bp.route("/crons/<int:tid>", methods=["DELETE"])
@auth_required
def ql_crons_del(tid):
    db.execute("DELETE FROM tasks WHERE id=?", (tid,))
    scheduler.remove_task_job(tid)
    return _ok({"id": tid})


@bp.route("/crons/run", methods=["POST"])
@auth_required
def ql_crons_run():
    b = get_json_body()
    tid = b.get("id") or b.get("task_id")
    task = db.query_one("SELECT * FROM tasks WHERE id=?", (int(tid),))
    if not task:
        return _err("任务不存在")
    executor.submit(task["command"], task_id=task["id"], task_name=task["name"], kind="task")
    return _ok({"id": task["id"]})
