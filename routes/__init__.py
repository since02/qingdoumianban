"""青豆面板 - 路由公共组件（Blueprint / 鉴权 / 响应封装）。"""
import functools
from flask import request, jsonify, Blueprint
from core import config

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


def auth_required(f):
    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        token = _extract_token()
        if not token or token != config.get_api_token():
            return json_err("未授权，请先登录", code=401, status=401)
        return f(*args, **kwargs)
    return wrapper


def get_json_body():
    return request.get_json(force=True, silent=True) or {}
