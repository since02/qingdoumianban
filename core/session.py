"""青豆面板 - 会话与权限（多用户）。

登录后签发一个会话 Token（存 sessions 表）；auth_required 同时接受
静态 api_token（外部脚本/服务调用，一律视为 admin）。
"""
from core import db, config


def create_session(username, role):
    import secrets
    token = secrets.token_hex(24)
    db.execute(
        "INSERT INTO sessions(token,username,role,created_at) VALUES(?,?,?,datetime('now','localtime'))",
        (token, username, role),
    )
    return token


def destroy_session(token):
    if not token:
        return
    try:
        db.execute("DELETE FROM sessions WHERE token=?", (token,))
    except Exception:
        pass


def get_session(token):
    """返回 {'username','role'} 或 None。静态 api_token 视为 admin。"""
    if not token:
        return None
    if token == config.get_api_token():
        return {"username": config.DEFAULT_USERNAME, "role": "admin"}
    row = db.query_one("SELECT username,role FROM sessions WHERE token=?", (token,))
    if not row:
        return None
    return {"username": row["username"], "role": row["role"]}


ROLE_LEVEL = {"viewer": 0, "op": 1, "admin": 2}


def role_level(role):
    return ROLE_LEVEL.get(role, -1)


def role_at_least(role, need):
    """role 是否达到 need 等级（viewer<op<admin）。"""
    return role_level(role) >= ROLE_LEVEL.get(need, 99)
