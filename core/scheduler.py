"""青豆面板 - 定时调度器（基于 APScheduler，单线程触发 + 线程池执行，省内存）。"""
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.util import astimezone
from core import db, config, executor

_scheduler = None


def get_scheduler():
    global _scheduler
    if _scheduler is None:
        tz = config.get_setting("timezone", "Asia/Shanghai") or "Asia/Shanghai"
        _scheduler = BackgroundScheduler(timezone=tz)
        _scheduler.start()
    return _scheduler


def _run_task_job(task_id):
    task = db.query_one("SELECT * FROM tasks WHERE id=?", (task_id,))
    if not task or task["status"] != 1:
        return
    executor.submit(
        task["command"],
        task_id=task_id,
        task_name=task["name"],
        notify=task["notify"],
        notify_type=task["notify_type"],
        kind="task",
    )


def _run_sub_job(sub_id):
    try:
        from core.subscription import sync_subscription
        sync_subscription(sub_id)
    except Exception as e:
        print(f"[青豆面板] 订阅 {sub_id} 执行异常: {e}")


def _tz():
    return config.get_setting("timezone", "Asia/Shanghai") or "Asia/Shanghai"


def add_task_job(task):
    sched = get_scheduler()
    job_id = f"task_{task['id']}"
    try:
        sched.remove_job(job_id)
    except Exception:
        pass
    if task["status"] != 1:
        return
    try:
        trigger = CronTrigger.from_crontab(task["schedule"], timezone=_tz())
        sched.add_job(_run_task_job, trigger, id=job_id, args=[task["id"]],
                      replace_existing=True, max_instances=1)
    except Exception as e:
        print(f"[青豆面板] 任务 {task['id']} 调度失败: {e}")


def remove_task_job(task_id):
    sched = get_scheduler()
    try:
        sched.remove_job(f"task_{task_id}")
    except Exception:
        pass


def add_sub_job(sub):
    sched = get_scheduler()
    job_id = f"sub_{sub['id']}"
    try:
        sched.remove_job(job_id)
    except Exception:
        pass
    if sub["status"] != 1:
        return
    try:
        trigger = CronTrigger.from_crontab(sub["schedule"], timezone=_tz())
        sched.add_job(_run_sub_job, trigger, id=job_id, args=[sub["id"]],
                      replace_existing=True, max_instances=1)
    except Exception as e:
        print(f"[青豆面板] 订阅 {sub['id']} 调度失败: {e}")


def remove_sub_job(sub_id):
    sched = get_scheduler()
    try:
        sched.remove_job(f"sub_{sub_id}")
    except Exception:
        pass


def _auto_update_job():
    """每日检查并自动拉取 GitHub 更新（仅当启用时）。"""
    try:
        if (config.get_setting("github_auto_update", "0") or "0") != "1":
            return
        import routes.system as sysmod
        sysmod.auto_update_pull()
    except Exception as e:
        print(f"[青豆面板] 自动更新异常: {e}")


def _ensure_auto_update_job():
    sched = get_scheduler()
    try:
        sched.remove_job("qd-auto-update")
    except Exception:
        pass
    try:
        sched.add_job(_auto_update_job, CronTrigger.from_crontab("0 4 * * *", timezone=_tz()),
                      id="qd-auto-update", replace_existing=True, max_instances=1)
    except Exception as e:
        print(f"[青豆面板] 自动更新任务注册失败: {e}")


def reload_all():
    """加载所有启用的任务与订阅到调度器。"""
    for t in db.query("SELECT * FROM tasks WHERE status=1"):
        add_task_job(t)
    for s in db.query("SELECT * FROM subscriptions WHERE status=1"):
        add_sub_job(s)
    # 可选：GitHub 自动更新（每日 4:00 检查并拉取），需用户启用且为 git 仓库
    try:
        if (config.get_setting("github_auto_update", "0") or "0") == "1":
            _ensure_auto_update_job()
        else:
            try:
                get_scheduler().remove_job("qd-auto-update")
            except Exception:
                pass
    except Exception:
        pass


def shutdown():
    if _scheduler:
        _scheduler.shutdown(wait=False)
