"""青豆面板 - 路由公共组件（Blueprint / 鉴权 / 响应封装 / 权限拦截）。"""
import functools
from flask import request, jsonify, Blueprint
from core import config
from core import session as _session

bp = Blueprint("api", __name__, url_prefix="/api")


def json_ok(data=None, msg="ok"):
    return jsonify({"code": 0, "msg": msg, "data": data})


def json_err(msg="error", code=1, status=200):
    return jsonify({"code": code, "msg": msg, "data": None}), status


def _extract_token():
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return auth[7:].strip()
    return request.args.get("token") or request.cookies.get("qd_token")


def _current_user():
    return _session.get_session(_extract_token())


def auth_required(f):
    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        user = _current_user()
        if not user:
            return json_err("未授权，请先登录", code=401, status=401)
        request._qd_user = user
        return f(*args, **kwargs)
    return wrapper


def role_required(*roles):
    def deco(f):
        @functools.wraps(f)
        def wrapper(*args, **kwargs):
            user = _current_user()
            if not user:
                return json_err("未授权，请先登录", code=401, status=401)
            if roles and user["role"] not in roles:
                return json_err("权限不足", code=403, status=403)
            request._qd_user = user
            return f(*args, **kwargs)
        return wrapper
    return deco


# ============ 权限拦截（集中式）：非只读请求按角色放行 ============
# admin-only 与 op-or-admin 路径前缀。静态 api_token 一律视为 admin，外部脚本不受影响。
_ADMIN_PREFIX = ("/users", "/system/settings", "/system/restart", "/system/stop",
                 "/system/start-daemon", "/system/restore", "/system/update")
_OP_PREFIX = ("/tasks", "/scripts", "/subscriptions", "/environments",
              "/notifications", "/dependencies", "/ai")


@bp.before_request
def _enforce_permission():
    # 登录接口放行（否则无人能登录）
    if request.path.endswith("/login"):
        return
    if request.method == "GET":
        return
    user = _current_user()
    if not user:
        return  # auth_required 会返回 401
    path = request.path
    if any(path.startswith(p) for p in _ADMIN_PREFIX):
        if user["role"] != "admin":
            return json_err("权限不足（需要管理员）", code=403, status=403)
        return
    if any(path.startswith(p) for p in _OP_PREFIX):
        if user["role"] not in ("op", "admin"):
            return json_err("权限不足（需要操作员及以上）", code=403, status=403)


def get_json_body():
    return request.get_json(force=True, silent=True) or {}
