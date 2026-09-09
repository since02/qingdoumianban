"""青豆面板 - 订阅管理路由。"""
from flask import request
from core import db, scheduler
from core.cron import is_valid_cron
from core.qlparse import parse_ql_repo
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
        "INSERT INTO subscriptions(name,url,branch,stype,schedule,status,alias,whitelist,blacklist,dependence) "
        "VALUES(?,?,?,?,?,?,?,?,?,?)",
        (name, url, b.get("branch", "main"), b.get("stype", "git"),
         b.get("schedule", "0 0 * * *"), int(b.get("status", 1)), b.get("alias"),
         b.get("whitelist", ""), b.get("blacklist", ""), b.get("dependence", "")),
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
        "UPDATE subscriptions SET name=?,url=?,branch=?,stype=?,schedule=?,status=?,alias=?,whitelist=?,blacklist=?,dependence=? WHERE id=?",
        (b.get("name", sub["name"]), b.get("url", sub["url"]),
         b.get("branch", sub["branch"]), b.get("stype", sub["stype"]),
         b.get("schedule", sub["schedule"]), int(b.get("status", sub["status"])),
         b.get("alias", sub["alias"]),
         b.get("whitelist", sub.get("whitelist", "")),
         b.get("blacklist", sub.get("blacklist", "")),
         b.get("dependence", sub.get("dependence", "")), sid),
    )
    sub = db.query_one("SELECT * FROM subscriptions WHERE id=?", (sid,))
    scheduler.add_sub_job(sub)
    return json_ok(msg="更新成功")


@bp.route("/subscriptions/parse-ql", methods=["POST"])
@auth_required
def parse_ql():
    """解析青龙 ql repo / ql raw 命令，返回可直接填充订阅表单的字段。"""
    b = get_json_body()
    info = parse_ql_repo(b.get("command") or "")
    if not info:
        return json_err("无法识别该命令，请确认是 ql repo/raw 格式，例如："
                        "ql repo <url> <白名单> <黑名单> <依赖过滤> <分支>")
    return json_ok(info)


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


@bp.route("/subscriptions/<int:sid>/logs", methods=["GET"])
@auth_required
def sub_logs(sid):
    """某订阅的同步日志列表（最近 50 条）。"""
    rows = db.query(
        "SELECT id,started_at,finished_at,status FROM logs "
        "WHERE sub_id=? AND kind='sub' ORDER BY id DESC LIMIT 50", (sid,))
    return json_ok([dict(r) for r in rows])


@bp.route("/subscriptions/logs/<int:log_id>", methods=["GET"])
@auth_required
def sub_log_content(log_id):
    """读取一条订阅同步日志的内容。"""
    row = db.query_one("SELECT * FROM logs WHERE id=? AND kind='sub'", (log_id,))
    if not row:
        return json_err("日志不存在")
    import os
    content = ""
    if row["log_file"] and os.path.isfile(row["log_file"]):
        try:
            with open(row["log_file"], "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
        except Exception as e:
            content = f"日志文件读取失败: {e}"
    else:
        content = "日志文件已不存在（可能被清理）"
    return json_ok({"id": row["id"], "started_at": row["started_at"],
                    "finished_at": row["finished_at"], "status": row["status"],
                    "content": content[-20000:]})
