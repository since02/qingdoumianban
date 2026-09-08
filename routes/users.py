"""青豆面板 - 用户管理（仅管理员）。"""
from flask import request
from core import db, config
from routes import bp, json_ok, json_err, auth_required, get_json_body


def _safe_role(role):
    return role if role in ("admin", "op", "viewer") else "viewer"


@bp.route("/users", methods=["GET"])
@auth_required
def list_users():
    rows = db.query("SELECT id,username,role,status,created_at FROM users ORDER BY id")
    return json_ok([dict(r) for r in rows])


@bp.route("/users", methods=["POST"])
@auth_required
def create_user():
    b = get_json_body()
    username = (b.get("username") or "").strip()
    password = b.get("password") or ""
    if not username or len(password) < 6:
        return json_err("用户名必填且密码至少 6 位")
    if db.query_one("SELECT id FROM users WHERE username=?", (username,)):
        return json_err("用户名已存在")
    role = _safe_role(b.get("role", "viewer"))
    db.execute("INSERT INTO users(username,pw_hash,role,status) VALUES(?,?,?,?)",
               (username, config.hash_password(password), role, int(b.get("status", 1))))
    return json_ok(msg="用户已创建")


@bp.route("/users/<int:uid>", methods=["PUT"])
@auth_required
def update_user(uid):
    b = get_json_body()
    row = db.query_one("SELECT * FROM users WHERE id=?", (uid,))
    if not row:
        return json_err("用户不存在")
    role = _safe_role(b.get("role", row["role"]))
    status = int(b.get("status", row["status"]))
    pw = b.get("password") or ""
    if pw:
        if len(pw) < 6:
            return json_err("新密码至少 6 位")
        db.execute("UPDATE users SET role=?,status=?,pw_hash=? WHERE id=?",
                   (role, status, config.hash_password(pw), uid))
    else:
        db.execute("UPDATE users SET role=?,status=? WHERE id=?", (role, status, uid))
    return json_ok(msg="已更新")


@bp.route("/users/<int:uid>", methods=["DELETE"])
@auth_required
def delete_user(uid):
    row = db.query_one("SELECT * FROM users WHERE id=?", (uid,))
    if not row:
        return json_err("用户不存在")
    me = request._qd_user
    if row["username"] == me["username"]:
        return json_err("不能删除当前登录账户")
    if (db.query_one("SELECT COUNT(*) AS c FROM users WHERE status=1") or {}).get("c", 0) <= 1:
        return json_err("至少保留一个启用账户")
    db.execute("DELETE FROM users WHERE id=?", (uid,))
    return json_ok(msg="已删除")
