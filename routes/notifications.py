"""青豆面板 - 通知设置路由。"""
import json
from flask import request
from core import db, notifier
from routes import bp, json_ok, json_err, auth_required, get_json_body

TYPE_FIELDS = {
    "pushplus": ["token"],
    "serverchan": ["sendkey"],
    "bark": ["key", "base"],
    "telegram": ["bot_token", "chat_id"],
    "wecom": ["webhook"],
    "dingtalk": ["webhook"],
    "webhook": ["url", "method"],
}


@bp.route("/notifications", methods=["GET"])
@auth_required
def list_notif():
    rows = db.query("SELECT * FROM notifications ORDER BY is_default DESC, id ASC")
    return json_ok([dict(r) for r in rows])


@bp.route("/notifications", methods=["POST"])
@auth_required
def create_notif():
    b = get_json_body()
    name = (b.get("name") or "").strip()
    ntype = (b.get("ntype") or "").strip()
    if not name or not ntype:
        return json_err("名称与类型不能为空")
    cfg = {k: b.get(k, "") for k in TYPE_FIELDS.get(ntype, [])}
    is_default = int(b.get("is_default", 0))
    if is_default:
        db.execute("UPDATE notifications SET is_default=0")
    db.execute(
        "INSERT INTO notifications(name,ntype,config,status,is_default) VALUES(?,?,?,?,?)",
        (name, ntype, json.dumps(cfg, ensure_ascii=False), int(b.get("status", 1)), is_default),
    )
    return json_ok(msg="添加成功")


@bp.route("/notifications/<int:nid>", methods=["PUT"])
@auth_required
def update_notif(nid):
    b = get_json_body()
    n = db.query_one("SELECT * FROM notifications WHERE id=?", (nid,))
    if not n:
        return json_err("通知不存在")
    cfg = {k: b.get(k, "") for k in TYPE_FIELDS.get(b.get("ntype", n["ntype"]), [])} or \
        json.loads(n["config"] or "{}")
    is_default = int(b.get("is_default", n["is_default"]))
    if is_default:
        db.execute("UPDATE notifications SET is_default=0")
    db.execute(
        "UPDATE notifications SET name=?,ntype=?,config=?,status=?,is_default=? WHERE id=?",
        (b.get("name", n["name"]), b.get("ntype", n["ntype"]),
         json.dumps(cfg, ensure_ascii=False), int(b.get("status", n["status"])), is_default, nid),
    )
    return json_ok(msg="更新成功")


@bp.route("/notifications/<int:nid>", methods=["DELETE"])
@auth_required
def delete_notif(nid):
    db.execute("DELETE FROM notifications WHERE id=?", (nid,))
    return json_ok(msg="删除成功")


@bp.route("/notifications/<int:nid>/test", methods=["POST"])
@auth_required
def test_notif(nid):
    n = db.query_one("SELECT * FROM notifications WHERE id=?", (nid,))
    if not n:
        return json_err("通知不存在")
    try:
        code, resp = notifier.send_one(n["ntype"], json.loads(n["config"] or "{}"),
                                       "青豆面板测试", "这是一条来自青豆面板的测试通知 ✅")
        return json_ok({"code": code, "resp": resp}, msg="已发送")
    except Exception as e:
        return json_err(f"发送失败: {e}")
