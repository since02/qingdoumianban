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


def _init_console():
    """让中文在 cmd 窗口正常显示。

    Python 的 stdout 默认编码可能与控制台实际代码页不一致（例如 GBK 控制台下按 UTF-8
    输出），导致双击 start.bat 时窗口里中文变成乱码。这里按控制台真实代码页重设编码。
    """
    if os.name != "nt":
        return
    try:
        import ctypes
        cp = ctypes.windll.kernel32.GetConsoleOutputCP() or 936
        for s in (sys.stdout, sys.stderr):
            if s is None:
                continue
            try:
                s.reconfigure(encoding=f"cp{cp}", errors="replace")
            except Exception:
                pass
    except Exception:
        pass


_init_console()


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
        # 注意：Windows netstat 输出可能含非 UTF-8 字节（中文 locale），必须 errors="replace"，
        # 否则 text=True 用默认 utf-8 解码会抛 UnicodeDecodeError，stdout 变成 None 导致后续崩溃。
        out = subprocess.run(
            ["netstat", "-ano"], capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=20,
        ).stdout or ""
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
    # 多次重试，确保彻底停止所有面板进程并释放端口。
    # 旧进程常以 DETACHED 方式运行，psutil 有时读不到其命令行而漏杀，
    # 因此每次循环都按端口强制兜底结束，直到端口不再被监听为止。
    # 同时优先读取 panel.pid 精准结束（避免误杀其它 python 进程）。
    pidfile = os.path.join(LOG_DIR, "panel.pid")
    for _ in range(15):
        # 优先结束 pidfile 记录的进程
        try:
            if os.path.exists(pidfile):
                with open(pidfile, encoding="utf-8", errors="replace") as f:
                    pid = int((f.read() or "").strip() or 0)
                if pid > 0:
                    try:
                        import psutil
                        psutil.Process(pid).kill()
                        print(f"  已按 pidfile 结束 PID {pid}")
                    except Exception:
                        pass
        except Exception:
            pass
        procs = _panel_procs()
        listening = _port_listening(port)
        if not procs and not listening:
            break
        for p in procs:
            try:
                p.kill()
                print(f"  已结束 PID {p.pid} ({p.info.get('name')})")
            except Exception as e:
                print(f"  结束 PID {p.pid} 失败: {e}")
        # 兜底：无论 psutil 是否识别到，只要端口还被占用就强制按端口结束
        if _port_listening(port):
            _stop_by_port(port)
        time.sleep(0.5)
    if _port_listening(port):
        print("仍有残留进程占用端口，请手动结束")
        return 1
    print("面板已停止")
    return 0


def start():
    os.makedirs(LOG_DIR, exist_ok=True)
    # 幂等：若面板已经在运行且健康检查通过，直接返回，避免重复拉起导致进程堆积
    port_now = _port()
    if _port_listening(port_now):
        try:
            import urllib.request
            with urllib.request.urlopen(f"http://127.0.0.1:{port_now}/healthz", timeout=2) as r:
                if r.status == 200:
                    msg = f"面板已在运行: http://127.0.0.1:{port_now}"
                    print(msg)
                    with open(LOG_FILE, "a", encoding="utf-8", errors="replace") as f:
                        f.write(f"[启动检测] {msg}\n")
                    return 0
        except Exception:
            pass
    # 先停旧的，避免端口冲突
    stop()
    # 等待端口彻底释放，避免旧进程的 TIME_WAIT 导致新进程绑定失败
    port_pre = _port()
    for _ in range(20):
        if not _port_listening(port_pre):
            break
        time.sleep(0.5)

    log = open(LOG_FILE, "a", encoding="utf-8", errors="replace")
    log.write(f"\n===== {time.strftime('%Y-%m-%d %H:%M:%S')} 启动面板 =====\n")
    log.flush()
    log.close()

    try:
        # 统一用 Python subprocess 直接拉起，不再经过 panel_hidden.vbs。
        # VBS 的 WshShell.Run 在接收含中文路径的命令行字符串时，易出现编码/拆分错误，
        # 导致命令被拆成多个字符执行、app.py 参数丢失，最终面板无法启动。
        py_candidates = [
            os.path.join(BASE_DIR, ".venv", "Scripts", "python.exe"),
            sys.executable,
            "python",
        ]
        py = None
        for cand in py_candidates:
            if isinstance(cand, str) and os.path.isfile(cand):
                py = cand
                break
        if py is None:
            py = py_candidates[-1]

        flog = open(LOG_FILE, "a", encoding="utf-8", errors="replace")
        flog.write(f"===== 通过 subprocess.Popen 启动面板（{py} app.py）=====\n")
        flog.flush()

        kwargs = {
            "cwd": BASE_DIR,
            "stdout": flog,
            "stderr": subprocess.STDOUT,
            "stdin": subprocess.DEVNULL,
            "close_fds": True,
        }
        if os.name == "nt":
            creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)
            creationflags |= getattr(subprocess, "DETACHED_PROCESS", 0x00000008)
            creationflags |= 0x08000000  # CREATE_NO_WINDOW
            kwargs["creationflags"] = creationflags
        else:
            kwargs["start_new_session"] = True
        subprocess.Popen([py, "app.py"], **kwargs)
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
