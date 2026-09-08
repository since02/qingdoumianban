"""青豆面板 - 鉴权路由（多用户 / 会话令牌）。"""
from flask import request
from core import db, config
from core import session as _session
from routes import bp, json_ok, json_err, auth_required


def _verify_user_password(username, password):
    """校验 users 表的加盐密码；同时兼容旧 admin_password 设置（首次登录迁移）。"""
    row = db.query_one("SELECT id,pw_hash,role,status FROM users WHERE username=?", (username,))
    if not row:
        # 兼容旧版：仅存在 admin_password 设置、且用户名恰为默认用户名时
        if username == config.DEFAULT_USERNAME and config.verify_password(password):
            # 把旧管理员迁移进 users 表
            try:
                db.execute(
                    "INSERT INTO users(username,pw_hash,role,status) VALUES(?,?,?,?)",
                    (username, config.hash_password(password), "admin", 1),
                )
            except Exception:
                pass
            return {"username": username, "role": "admin"}
        return None
    if row["status"] != 1:
        return None
    stored = row["pw_hash"]
    ok = False
    if stored.startswith("sha256$"):
        try:
            _, salt, dig = stored.split("$", 2)
            calc = __import__("hashlib").sha256((salt + password).encode("utf-8")).hexdigest()
            ok = calc == dig
        except Exception:
            ok = False
    if not ok and stored == config._legacy_hash(password):
        ok = True
        # 迁移为加盐格式
        db.execute("UPDATE users SET pw_hash=? WHERE id=?", (config.hash_password(password), row["id"]))
    return {"username": username, "role": row["role"]} if ok else None


@bp.route("/login", methods=["POST"])
def login():
    body = request.get_json(force=True, silent=True) or {}
    username = (body.get("username") or "").strip()
    password = body.get("password") or ""
    user = _verify_user_password(username, password)
    if not user:
        return json_err("用户名或密码错误")
    token = _session.create_session(user["username"], user["role"])
    return json_ok({"token": token, "username": user["username"], "role": user["role"]})


@bp.route("/me", methods=["GET"])
@auth_required
def me():
    user = request._qd_user
    return json_ok({"username": user["username"], "role": user["role"],
                    "panel": config.PANEL_NAME, "version": config.PANEL_VERSION})


@bp.route("/logout", methods=["POST"])
@auth_required
def logout():
    token = _cur_token()
    _session.destroy_session(token)
    return json_ok(msg="已退出")


def _cur_token():
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return auth[7:].strip()
    return request.args.get("token") or request.cookies.get("qd_token")


@bp.route("/change_password", methods=["POST"])
@auth_required
def change_password():
    body = request.get_json(force=True, silent=True) or {}
    old = body.get("old_password") or ""
    new = body.get("new_password") or ""
    user = request._qd_user
    if len(new) < 6:
        return json_err("新密码至少 6 位")
    row = db.query_one("SELECT id,pw_hash FROM users WHERE username=?", (user["username"],))
    if not row:
        return json_err("用户不存在")
    stored = row["pw_hash"]
    ok = False
    if stored.startswith("sha256$"):
        try:
            _, salt, dig = stored.split("$", 2)
            calc = __import__("hashlib").sha256((salt + old).encode("utf-8")).hexdigest()
            ok = calc == dig
        except Exception:
            ok = False
    if not ok and stored == config._legacy_hash(old):
        ok = True
    if not ok:
        return json_err("原密码错误")
    db.execute("UPDATE users SET pw_hash=? WHERE id=?", (config.hash_password(new), row["id"]))
    return json_ok(msg="密码已修改")
