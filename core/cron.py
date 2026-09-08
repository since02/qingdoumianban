"""青豆面板 - Cron 表达式解析与下次运行时间计算。"""
from datetime import datetime
from apscheduler.triggers.cron import CronTrigger
from apscheduler.util import astimezone


def parse_cron(expr: str) -> CronTrigger:
    """解析标准 5 字段 crontab 表达式，返回 CronTrigger。"""
    expr = (expr or "").strip()
    if not expr:
        raise ValueError("cron 表达式为空")
    return CronTrigger.from_crontab(expr)


def next_run_time(expr: str, now: datetime = None) -> datetime:
    """返回下一次运行时间（本地时区）。"""
    trigger = parse_cron(expr)
    base = now or datetime.now(astimezone(None))
    nxt = trigger.get_next_fire_time(None, base)
    return nxt


def is_valid_cron(expr: str) -> bool:
    try:
        parse_cron(expr)
        return True
    except Exception:
        return False


def human_cron(expr: str) -> str:
    """粗略的中文描述（可选展示用）。"""
    return expr
