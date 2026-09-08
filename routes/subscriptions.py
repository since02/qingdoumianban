"""青豆面板 - 订阅管理路由。"""
from flask import request
from core import db, scheduler
from core.cron import is_valid_cron
from core.subscription import sync_subscription, run_sub_now
from routes import bp, json_ok, json_err, auth_required, get_json_body


@bp.route("/subscriptions", methods=["GET"])
@auth_required
def list_subs():
    rows = db.query("SELECT * FROM subscriptions ORDER BY id DESC")
    return json_ok([dict(r) for r in rows])


@bp.route("/subscriptions", methods=["POST"])
@auth_required
def create_sub():
    b = get_json_body()
    name = (b.get("name") or "").strip()
    url = (b.get("url") or "").strip()
    if not name or not url:
        return json_err("名称与地址不能为空")
    schedule = (b.get("schedule") or "0 0 * * *").strip()
    if not is_valid_cron(schedule):
        return json_err("cron 表达式无效")
    sid = db.execute(
        "INSERT INTO subscriptions(name,url,branch,stype,schedule,status,alias) "
        "VALUES(?,?,?,?,?,?,?)",
        (name, url, b.get("branch", "main"), b.get("stype", "git"),
         b.get("schedule", "0 0 * * *"), int(b.get("status", 1)), b.get("alias")),
    )
    sub = db.query_one("SELECT * FROM subscriptions WHERE id=?", (sid,))
    scheduler.add_sub_job(sub)
    return json_ok({"id": sid}, msg="创建成功")


@bp.route("/subscriptions/<int:sid>", methods=["PUT"])
@auth_required
def update_sub(sid):
    b = get_json_body()
    sub = db.query_one("SELECT * FROM subscriptions WHERE id=?", (sid,))
    if not sub:
        return json_err("订阅不存在")
    db.execute(
        "UPDATE subscriptions SET name=?,url=?,branch=?,stype=?,schedule=?,status=?,alias=? WHERE id=?",
        (b.get("name", sub["name"]), b.get("url", sub["url"]),
         b.get("branch", sub["branch"]), b.get("stype", sub["stype"]),
         b.get("schedule", sub["schedule"]), int(b.get("status", sub["status"])),
         b.get("alias", sub["alias"]), sid),
    )
    sub = db.query_one("SELECT * FROM subscriptions WHERE id=?", (sid,))
    scheduler.add_sub_job(sub)
    return json_ok(msg="更新成功")


@bp.route("/subscriptions/<int:sid>", methods=["DELETE"])
@auth_required
def delete_sub(sid):
    db.execute("DELETE FROM subscriptions WHERE id=?", (sid,))
    scheduler.remove_sub_job(sid)
    return json_ok(msg="删除成功")


@bp.route("/subscriptions/<int:sid>/sync", methods=["POST"])
@auth_required
def sync_sub(sid):
    sub = db.query_one("SELECT * FROM subscriptions WHERE id=?", (sid,))
    if not sub:
        return json_err("订阅不存在")
    res = run_sub_now(sid)
    return json_ok({"status": res}, msg="已提交同步")
