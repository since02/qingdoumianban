"""青豆面板 - 解析青龙 `ql repo` / `ql raw` 命令为订阅字段。

纯函数、无第三方重依赖，便于单测与复用。
"""
import re
import shlex


def parse_ql_repo(cmd: str):
    """解析 `ql repo <url> <white> <black> <dependence> <branch>` 形式的命令。

    返回 dict 或 None。支持代理前缀 URL（如 https://proxy/https://github.com/...）、
    带引号参数、以及裸仓库 URL（不含 ql 前缀）兜底。
    """
    cmd = (cmd or "").strip()
    if not cmd:
        return None
    # 合并多行并去掉注释
    lines = [ln.strip() for ln in cmd.splitlines() if ln.strip() and not ln.strip().startswith("#")]
    text = " ".join(lines)
    try:
        toks = shlex.split(text, posix=True)
    except ValueError:
        toks = text.split()
    if not toks:
        return None
    # 定位 `ql repo` / `ql raw`
    idx = None
    for i, t in enumerate(toks):
        if t.lower() in ("repo", "raw") and i >= 1 and "ql" in toks[i - 1].lower():
            idx = i
            break
    if idx is None:
        # 兜底：整段就是一个 git 地址
        if toks[0].lower().startswith("http"):
            name = _repo_name(toks[0])
            return {"stype": "git", "name": name, "alias": name, "url": toks[0],
                    "branch": "main", "whitelist": "", "blacklist": "", "dependence": ""}
        return None
    rest = toks[idx + 1:]
    if not rest:
        return None
    url = rest[0].strip().strip("'\"")
    if not url:
        return None
    white = rest[1].strip().strip("'\"") if len(rest) > 1 else ""
    black = rest[2].strip().strip("'\"") if len(rest) > 2 else ""
    dependence = rest[3].strip().strip("'\"") if len(rest) > 3 else ""
    branch = rest[4].strip().strip("'\"") if len(rest) > 4 else "main"
    name = _repo_name(url)
    return {"stype": "git", "name": name, "alias": name, "url": url,
            "branch": branch or "main", "whitelist": white,
            "blacklist": black, "dependence": dependence}


def _repo_name(url: str) -> str:
    """从仓库 URL 推导默认名称，兼容代理前缀（proxy/https://real）。"""
    m = re.search(r'https?://[^/\s]+/(https?://.+)$', url)
    if m:
        url = m.group(1)
    path = re.sub(r'\.git$', '', url.strip())
    seg = path.rstrip('/').split('/')[-1]
    if not seg:
        parts = path.rstrip('/').split('/')
        seg = parts[-2] if len(parts) > 1 else 'repo'
    seg = re.sub(r'[^\w\-]+', '_', seg) or 'repo'
    return seg
