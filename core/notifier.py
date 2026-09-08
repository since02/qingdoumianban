"""青豆面板 - 通知推送（pushplus / Server酱 / Bark / Telegram / 企业微信 / 钉钉 / 自定义 Webhook）。"""
import os
import json
import time
import requests
from core import db, config

TIMEOUT = 10


def list_notifiers():
    return db.query("SELECT * FROM notifications ORDER BY is_default DESC, id ASC")


def get_active(notify_type=None):
    """返回本次要使用的通知配置列表。notify_type 形如 '1,2' 指定 id。"""
    if notify_type:
        ids = [int(x) for x in str(notify_type).split(",") if x.strip().isdigit()]
        rows = db.query("SELECT * FROM notifications WHERE id IN (%s)" % ",".join("?" * len(ids)), ids)
        return rows
    # 默认：所有启用 + 标记为默认
    rows = db.query("SELECT * FROM notifications WHERE status=1")
    return rows


def _post(url, payload, headers=None):
    try:
        r = requests.post(url, json=payload, headers=headers or {}, timeout=TIMEOUT)
        return r.status_code, r.text[:200]
    except Exception as e:
        return -1, str(e)[:200]


def send_one(ntype, cfg, title, content):
    cfg = cfg or {}
    if ntype == "pushplus":
        token = cfg.get("token", "")
        return _post("https://www.pushplus.plus/send",
                     {"token": token, "title": title, "content": content, "template": "html"})
    if ntype == "serverchan":
        sendkey = cfg.get("sendkey", "")
        return _post(f"https://sctapi.ftqq.com/{sendkey}.send",
                     {"title": title, "desp": content})
    if ntype == "bark":
        key = cfg.get("key", "")
        base = cfg.get("base", "https://api.day.app")
        url = f"{base}/{key}/{requests.utils.quote(title)}/{requests.utils.quote(content)}"
        try:
            r = requests.get(url, timeout=TIMEOUT)
            return r.status_code, r.text[:200]
        except Exception as e:
            return -1, str(e)[:200]
    if ntype == "telegram":
        bot = cfg.get("bot_token", "")
        chat = cfg.get("chat_id", "")
        url = f"https://api.telegram.org/bot{bot}/sendMessage"
        return _post(url, {"chat_id": chat, "text": f"{title}\n\n{content}", "parse_mode": "Markdown"})
    if ntype == "wecom":
        webhook = cfg.get("webhook", "")
        return _post(webhook, {"msgtype": "text", "text": {"content": f"{title}\n{content}"}})
    if ntype == "dingtalk":
        webhook = cfg.get("webhook", "")
        return _post(webhook, {"msgtype": "text", "text": {"content": f"{title}\n{content}"}})
    if ntype == "webhook":
        url = cfg.get("url", "")
        method = (cfg.get("method", "POST") or "POST").upper()
        try:
            if method == "GET":
                r = requests.get(url, params={"title": title, "content": content}, timeout=TIMEOUT)
            else:
                r = requests.post(url, json={"title": title, "content": content},
                                  headers={"Content-Type": "application/json"}, timeout=TIMEOUT)
            return r.status_code, r.text[:200]
        except Exception as e:
            return -1, str(e)[:200]
    return -1, f"未知通知类型: {ntype}"


def notify_task_result(task_name, status, log_path=None, notify_type=None):
    title_map = {"success": "✅ 执行成功", "failed": "❌ 执行失败", "timeout": "⏱ 执行超时", "skipped": "⏭ 已跳过"}
    title = f"青豆面板 {title_map.get(status, status)} - {task_name}"
    content = f"任务：{task_name}\n状态：{status}\n时间：{__import__('time').strftime('%Y-%m-%d %H:%M:%S')}"
    if log_path and os.path.exists(log_path):
        try:
            with open(log_path, "r", encoding="utf-8", errors="replace") as f:
                tail = "".join(f.readlines()[-30:])
            content += f"\n\n--- 最近日志 ---\n{tail[-1500:]}"
        except Exception:
            pass
    for n in get_active(notify_type):
        try:
            send_one(n["ntype"], json.loads(n["config"] or "{}"), title, content)
        except Exception as e:
            print(f"[青豆面板] 通知 {n['id']} 发送失败: {e}")


def notify_text(title, content, notify_type=None):
    for n in get_active(notify_type):
        try:
            send_one(n["ntype"], json.loads(n["config"] or "{}"), title, content)
        except Exception as e:
            print(f"[青豆面板] 通知 {n['id']} 发送失败: {e}")
