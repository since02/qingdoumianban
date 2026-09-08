"""青豆面板 - 启动/停止控制器（跨平台，不依赖外部脚本）。

用法：
    python panel_ctl.py start    # 先停旧进程，再以无窗口方式后台启动，日志写入 data/panel.log
    python panel_ctl.py stop     # 停止面板进程

设计要点：
1) 不使用 pythonw：pythonw 无控制台，sys.stdout 为 None，代码里的 print 会抛异常导致进程静默退出。
   这里用 sys.executable（普通 python.exe）配合平台专属的进程分离参数，实现"无窗口 + 输出可查"。
2) 进程识别按命令行含 "app.py" 匹配（排除控制器自身），避免误杀。
3) 日志由本控制器以文件句柄方式交给子进程，可靠落盘。
"""
import os
import sys
import time
import sqlite3
import subprocess

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_DIR = os.path.join(BASE_DIR, "data")
LOG_FILE = os.path.join(LOG_DIR, "panel.log")
MARK = "app.py"
SELF = "panel_ctl.py"


def _port():
    """从数据库读取面板端口，失败则回落 5700。"""
    try:
        db = os.path.join(BASE_DIR, "data", "qingdou.db")
        if os.path.exists(db):
            conn = sqlite3.connect(db)
            row = conn.execute("SELECT value FROM settings WHERE key='port'").fetchone()
            conn.close()
            if row and row[0]:
                return int(row[0])
    except Exception:
        pass
    return 5700


def _is_panel_cmd(cmd):
    """命令行中是否把 app.py 作为一个独立参数（避免误匹配包含该字样的其他命令）。"""
    for x in cmd or []:
        s = str(x)
        if s == MARK or s.endswith(os.sep + MARK) or s.endswith("/" + MARK):
            return True
    return False


def _panel_procs():
    """找出所有面板进程（参数为 app.py，且不是本控制器）。"""
    try:
        import psutil
    except Exception:
        return []
    out = []
    for p in psutil.process_iter(["pid", "name", "cmdline"]):
        try:
            cmd = p.info.get("cmdline") or []
            if _is_panel_cmd(cmd) and not any(SELF in str(x) for x in cmd):
                out.append(p)
        except Exception:
            continue
    return out


def _port_listening(port):
    """判断端口是否仍在监听（用于确认面板是否真的停了）。"""
    import socket
    s = socket.socket()
    s.settimeout(1)
    try:
        return s.connect_ex(("127.0.0.1", port)) == 0
    except Exception:
        return False
    finally:
        try:
            s.close()
        except Exception:
            pass


def _stop_by_port(port):
    """兜底：面板进程若脱离了进程枚举视图（如 DETACHED 启动），按端口占用者 PID 结束。"""
    killed = False
    try:
        out = subprocess.run(["netstat", "-ano"], capture_output=True, text=True, timeout=20).stdout
        pids = []
        for line in out.splitlines():
            upper = line.upper()
            if f":{port}" in line and "LISTENING" in upper:
                parts = line.split()
                if len(parts) >= 5 and parts[-1].isdigit():
                    pid = int(parts[-1])
                    if pid > 0 and pid not in pids:
                        pids.append(pid)
        for pid in pids:
            subprocess.run(["taskkill", "/F", "/PID", str(pid)],
                           capture_output=True, timeout=20)
            print(f"  已按端口占用结束 PID {pid}")
            killed = True
    except Exception as e:
        print(f"  按端口结束失败: {e}")
    return killed


def stop():
    port = _port()
    procs = _panel_procs()
    if not procs and not _port_listening(port):
        print("没有正在运行的面板进程")
        return 0

    if procs:
        print(f"发现面板进程 {len(procs)} 个，正在停止…")
        for p in procs:
            try:
                p.terminate()
                print(f"  已请求停止 PID {p.pid} ({p.info.get('name')})")
            except Exception as e:
                print(f"  停止 PID {p.pid} 失败: {e}")
        time.sleep(1.5)
        for p in _panel_procs():
            try:
                p.kill()
                print(f"  已强制结束 PID {p.pid}")
            except Exception:
                pass
        time.sleep(0.5)

    # 兜底：psutil 可能枚举不到已脱离的进程，改按端口处理
    if _port_listening(port):
        print(f"端口 {port} 仍在监听，按端口占用者结束…")
        _stop_by_port(port)
        time.sleep(1)

    if _port_listening(port):
        print("仍有残留进程占用端口，请手动结束")
        return 1
    print("面板已停止")
    return 0


def start():
    os.makedirs(LOG_DIR, exist_ok=True)
    # 先停旧的，避免端口冲突
    stop()
    time.sleep(1)

    log = open(LOG_FILE, "a", encoding="utf-8", errors="replace")
    log.write(f"\n===== {time.strftime('%Y-%m-%d %H:%M:%S')} 启动面板 =====\n")
    log.flush()
    log.close()

    try:
        if os.name == "nt":
            # Windows：交由 panel_hidden.vbs 以「隐藏窗口 + 不等待」方式拉起，
            # 这样进程不属于本控制台，关闭 bat 窗口也不会把面板一起杀掉
            # （此前 DETACHED_PROCESS 方式在部分环境下仍会随调用方退出而终止）。
            vbs = os.path.join(BASE_DIR, "panel_hidden.vbs")
            if os.path.exists(vbs):
                subprocess.run(["wscript.exe", "//nologo", vbs],
                               cwd=BASE_DIR, timeout=30,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                print("已通过隐藏方式启动面板（日志: data\\panel.log）")
            else:  # vbs 缺失时退回直接启动
                raise FileNotFoundError(vbs)
        else:
            py = sys.executable
            flog = open(LOG_FILE, "a", encoding="utf-8", errors="replace")
            subprocess.Popen([py, "app.py"], cwd=BASE_DIR,
                             stdout=flog, stderr=subprocess.STDOUT,
                             stdin=subprocess.DEVNULL, start_new_session=True)
            print(f"已后台启动面板（日志: data{os.sep}panel.log）")
    except Exception as e:
        print(f"启动失败: {e}")
        with open(LOG_FILE, "a", encoding="utf-8", errors="replace") as f:
            f.write(f"[启动失败] {e}\n")
        return 1

    # 健康检查
    port = _port()
    ok = False
    for _ in range(15):
        time.sleep(1)
        try:
            import urllib.request
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/healthz", timeout=2) as r:
                if r.status == 200:
                    ok = True
                    break
        except Exception:
            continue

    if ok:
        msg = f"面板已就绪: http://127.0.0.1:{port}"
        print(msg)
    else:
        msg = "启动后未检测到服务，请查看 data/panel.log 中的报错"
        print(msg)
        # 把日志尾部直接打出来，便于一眼看到崩溃原因
        try:
            with open(LOG_FILE, "r", encoding="utf-8", errors="replace") as f:
                tail = f.readlines()[-25:]
            if tail:
                print("---- data/panel.log 尾部 ----")
                for ln in tail:
                    print("  " + ln.rstrip())
                print("-----------------------------")
        except Exception:
            pass

    with open(LOG_FILE, "a", encoding="utf-8", errors="replace") as f:
        f.write(f"[启动检测] {msg}\n")
    return 0 if ok else 1


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "start"
    if cmd == "start":
        sys.exit(start())
    elif cmd == "stop":
        sys.exit(stop())
    else:
        print("用法: python panel_ctl.py start|stop")
        sys.exit(2)
