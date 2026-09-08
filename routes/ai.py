"""青豆面板 - AI 设置 / 对话 / 脚本生成 / 日志分析 路由。"""
import os
import json
from flask import request
from core import db, ai
from routes import bp, json_ok, json_err, auth_required, get_json_body


@bp.route("/ai", methods=["GET"])
@auth_required
def list_ai():
    rows = db.query("SELECT * FROM ai_configs ORDER BY is_default DESC, id ASC")
    return json_ok([dict(r) for r in rows])


@bp.route("/ai", methods=["POST"])
@auth_required
def create_ai():
    b = get_json_body()
    name = (b.get("name") or "").strip()
    if not name:
        return json_err("名称不能为空")
    is_default = int(b.get("is_default", 0))
    if is_default:
        db.execute("UPDATE ai_configs SET is_default=0")
    db.execute(
        "INSERT INTO ai_configs(name,provider,base_url,api_key,model,status,is_default) "
        "VALUES(?,?,?,?,?,?,?)",
        (name, b.get("provider", "openai"), b.get("base_url", ""),
         b.get("api_key", ""), b.get("model", ""), int(b.get("status", 1)), is_default),
    )
    return json_ok(msg="添加成功")


@bp.route("/ai/<int:aid>", methods=["PUT"])
@auth_required
def update_ai(aid):
    b = get_json_body()
    a = db.query_one("SELECT * FROM ai_configs WHERE id=?", (aid,))
    if not a:
        return json_err("配置不存在")
    is_default = int(b.get("is_default", a["is_default"]))
    if is_default:
        db.execute("UPDATE ai_configs SET is_default=0")
    db.execute(
        "UPDATE ai_configs SET name=?,provider=?,base_url=?,api_key=?,model=?,status=?,is_default=? WHERE id=?",
        (b.get("name", a["name"]), b.get("provider", a["provider"]),
         b.get("base_url", a["base_url"]), b.get("api_key", a["api_key"]),
         b.get("model", a["model"]), int(b.get("status", a["status"])), is_default, aid),
    )
    return json_ok(msg="更新成功")


@bp.route("/ai/<int:aid>", methods=["DELETE"])
@auth_required
def delete_ai(aid):
    db.execute("DELETE FROM ai_configs WHERE id=?", (aid,))
    return json_ok(msg="删除成功")


@bp.route("/ai/test", methods=["POST"])
@auth_required
def test_ai():
    b = get_json_body()
    msg, err = ai.chat([{"role": "user", "content": "ping"}], ai={
        "provider": b.get("provider", "openai"),
        "base_url": b.get("base_url", ""),
        "api_key": b.get("api_key", ""),
        "model": b.get("model", ""),
    })
    if err:
        return json_err(err)
    return json_ok({"reply": msg}, msg="连接成功")


@bp.route("/ai/chat", methods=["POST"])
@auth_required
def ai_chat():
    b = get_json_body()
    messages = b.get("messages") or [{"role": "user", "content": b.get("prompt", "")}]
    msg, err = ai.chat(messages, max_tokens=int(b.get("max_tokens", 2000)))
    if err:
        return json_err(err)
    return json_ok({"content": msg})


@bp.route("/ai/generate_script", methods=["POST"])
@auth_required
def ai_gen():
    b = get_json_body()
    prompt = b.get("prompt", "")
    lang = b.get("lang", "python")
    code, err = ai.generate_script(prompt, lang)
    if err:
        return json_err(err)
    return json_ok({"code": code, "lang": lang})


@bp.route("/ai/analyze_log", methods=["POST"])
@auth_required
def ai_analyze():
    b = get_json_body()
    text = b.get("text", "")
    if not text:
        lid = b.get("log_id")
        if lid:
            row = db.query_one("SELECT * FROM logs WHERE id=?", (int(lid),))
            if row and row["log_file"] and os.path.exists(row["log_file"]):
                with open(row["log_file"], "r", encoding="utf-8", errors="replace") as f:
                    text = f.read()
    result, err = ai.analyze_log(text)
    if err:
        return json_err(err)
    return json_ok({"analysis": result})
