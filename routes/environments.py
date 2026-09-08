"""青豆面板 - 环境变量路由（供脚本读取）。"""
from flask import request
from core import db
from routes import bp, json_ok, json_err, auth_required, get_json_body


@bp.route("/environments", methods=["GET"])
@auth_required
def list_env():
    rows = db.query("SELECT * FROM environments ORDER BY id DESC")
    return json_ok([dict(r) for r in rows])


@bp.route("/environments", methods=["POST"])
@auth_required
def create_env():
    b = get_json_body()
    name = (b.get("name") or "").strip()
    if not name:
        return json_err("变量名不能为空")
    db.execute(
        "INSERT INTO environments(name,value,remarks,status) VALUES(?,?,?,?)",
        (name, b.get("value", ""), b.get("remarks", ""), int(b.get("status", 1))),
    )
    return json_ok(msg="添加成功")


@bp.route("/environments/<int:eid>", methods=["PUT"])
@auth_required
def update_env(eid):
    b = get_json_body()
    env = db.query_one("SELECT * FROM environments WHERE id=?", (eid,))
    if not env:
        return json_err("变量不存在")
    db.execute(
        "UPDATE environments SET name=?,value=?,remarks=?,status=? WHERE id=?",
        (b.get("name", env["name"]), b.get("value", env["value"]),
         b.get("remarks", env["remarks"]), int(b.get("status", env["status"])), eid),
    )
    return json_ok(msg="更新成功")


@bp.route("/environments/<int:eid>", methods=["DELETE"])
@auth_required
def delete_env(eid):
    db.execute("DELETE FROM environments WHERE id=?", (eid,))
    return json_ok(msg="删除成功")
