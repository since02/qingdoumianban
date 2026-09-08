"""青豆面板 - 鉴权路由。"""
from flask import request
from core import config
from routes import bp, json_ok, json_err, auth_required


@bp.route("/login", methods=["POST"])
def login():
    body = request.get_json(force=True, silent=True) or {}
    username = (body.get("username") or "").strip()
    password = body.get("password") or ""
    if username != config.DEFAULT_USERNAME:
        return json_err("用户名或密码错误")
    if not config.verify_password(password):
        return json_err("用户名或密码错误")
    return json_ok({"token": config.get_api_token(), "username": username})


@bp.route("/me", methods=["GET"])
@auth_required
def me():
    return json_ok({"username": config.DEFAULT_USERNAME, "panel": config.PANEL_NAME,
                    "version": config.PANEL_VERSION})


@bp.route("/change_password", methods=["POST"])
@auth_required
def change_password():
    body = request.get_json(force=True, silent=True) or {}
    old = body.get("old_password") or ""
    new = body.get("new_password") or ""
    if not config.verify_password(old):
        return json_err("原密码错误")
    if len(new) < 6:
        return json_err("新密码至少 6 位")
    config.set_setting("admin_password", config.hash_password(new))
    return json_ok(msg="密码已修改")
