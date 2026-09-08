# 青豆面板 (Qingdou Panel)

一个**本地运行、绿色可移动**的任务调度面板，对标青龙面板 / 呆呆面板，主打**轻量、省内存、依赖齐全、可对接 AI**。

## 特性

| 功能 | 说明 |
|------|------|
| ⏰ 定时任务 | 标准 5 段 crontab 表达式，支持 `python` / `node` / `bash` / `task xxx.py` / 任意 shell 命令 |
| 📜 脚本管理 | 内置文件管理器，在线创建 / 编辑 / 删除 / 运行 `.py` `.js` `.sh` 脚本 |
| 🔗 订阅管理 | 支持 **Git 仓库** 与 **青龙格式 JSON 清单** 自动同步，按脚本内 `# cron:` 注释自动建任务 |
| 📦 依赖安装 | 后台执行 `pip` / `npm` / `apt`，不阻塞面板，带安装日志 |
| 🔐 环境变量 | 所有启用变量在执行时注入子进程环境 |
| 🔔 通知推送 | pushplus / Server酱 / Bark / Telegram / 企业微信 / 钉钉 / 自定义 Webhook，任务结果自动推送 |
| 🤖 AI 对接 | 兼容 OpenAI / DeepSeek / 通义 / 本地 Ollama，支持对话、脚本生成、日志分析 |
| 💬 微信对接 | 独立「微信对接」页对接 yyb-go（应用宝扫码登录），可配置本机 IP/端口、查看连接状态与已登录微信账号 |
| 💾 备份与恢复 | 一键导出全部设置项（JSON）/ 导出数据库文件 / 导入恢复，便于迁移与回滚 |
| 🔄 GitHub 更新 | 填仓库地址后可「检查更新」「立即更新」（`git pull` + 自动重启），可开启每日自动更新 |
| 🔌 开放 API | 自带 Token（Bearer）REST API，含青龙兼容的 `/api/envs` `/api/crons`，可对接外部脚本 |
| 🖥 管理面板 | 暗色主题单页后台，仪表盘、任务、脚本、订阅、依赖、变量、通知、AI、微信对接、系统设置 |
| 💾 省内存 | 单进程 + SQLite(WAL) + 线程池限并发 + 日志流式写盘，默认仅占用几十 MB |
| 🐧 跨平台 | 同一套代码可在 **Windows / Linux / macOS** 服务器运行，启动脚本与执行引擎均做平台适配 |

## 快速开始

### Windows

```bat
双击 start.bat
```

首次运行会自动创建 `.venv` 并安装依赖，随后访问 http://127.0.0.1:5700

### Linux / macOS

```bash
chmod +x start.sh
./start.sh
```

### 手动运行

```bash
python -m venv .venv
.venv/bin/pip install -r requirements.txt
python app.py
```

默认账号：**admin / adminadmin**（登录后请尽快修改密码）。

## 新增功能说明

### 💬 微信对接（yyb-go）
左侧导航「微信对接」为独立设置页：
- **服务配置**：默认本机 IP `127.0.0.1`、端口 `8000`（yyb-go 默认），可自定义；填写 `YYB_API_TOKEN` 作为鉴权。
- **连接状态**：页面实时显示「已连接 / 未连接 / 未启用」圆点，并支持「测试连接」。
- **已登录微信账号**：连接正常时自动列出 yyb-go 中已登录的微信账号（昵称、状态、OpenID 片段），每 8 秒自动刷新。
- 启用后，登录页将出现「🟢 微信扫码登录」按钮，扫码确认即下发面板 Token。

> yyb-go 默认监听 `127.0.0.1:8000`，鉴权为 `Authorization: Bearer <YYB_API_TOKEN>`。详见 https://github.com/Aoluis1005/yyb-go

### 💾 备份与恢复（系统设置 → 备份与恢复）
- **导出全部设置(JSON)**：导出运行参数、任务、订阅、环境变量、通知、AI 配置、依赖记录、脚本内容，用于迁移或回滚。
- **导出数据库文件**：直接下载 `qingdou.db`（含日志等完整数据）。
- **导入恢复**：上传备份 JSON，整表替换覆盖当前配置（脚本文件需另行拷贝 `data/scripts` 目录）。

### 🔄 GitHub 自动更新（系统设置 → 版本与更新）
1. 将面板以 `git clone` 方式部署到服务器（需联网、已安装 git）。
2. 在「GitHub 仓库地址」填入你的仓库（如 `https://github.com/用户名/仓库`），选择分支。
3. 点「检查更新」比对本地与远程提交；点「立即更新」执行 `git pull` 并自动重启以应用新版本。
4. 可选「每日自动」：开启后由面板内置调度器每日 04:00 自动拉取并重启。

> 提示：更新会先 `git stash` 本地改动再 `pull`；若自定义文件需保留，请走分支或 fork 方式。

## 跨平台与服务器部署

- 面板以 `0.0.0.0` 监听，天然支持服务器部署；生产环境建议配合 Nginx 反向代理并限制来源 IP。
- Linux 需预装 `python3` 与 `python3-venv`（部分发行版需 `apt install python3-venv`）。
- 依赖安装（`pip`/`npm`/`apt`）与脚本执行（`python`/`node`/`bash`）均已做平台适配；任务命令里的解释器路径留空即自动取当前运行环境。
- 守护进程 / 重启 / 关闭按钮在 Windows 与 Linux 下均可用（Linux 以 `setsid` 脱离终端）。

## 目录结构

```
qingdou-panel/
├── app.py                 # 入口（单进程）
├── requirements.txt
├── start.bat / start.sh   # 一键启动
├── core/                  # 核心引擎
│   ├── db.py              # SQLite 封装（WAL）
│   ├── config.py          # 配置/鉴权
│   ├── cron.py            # crontab 解析
│   ├── executor.py        # 脚本执行引擎
│   ├── scheduler.py       # APScheduler 调度
│   ├── subscription.py    # 订阅同步
│   ├── notifier.py        # 通知推送
│   └── ai.py              # AI 对接
├── routes/                # REST API 与青龙兼容接口
├── static/                # 前端单页（原生 HTML/CSS/JS，无构建）
└── data/                  # 数据库 / 脚本 / 日志（绿色数据目录）
```

## 开放 API 示例

```bash
# token 在「系统设置」查看
TOKEN=你的token

# 列出环境变量（青龙兼容）
curl -H "Authorization: Bearer $TOKEN" http://127.0.0.1:5700/api/envs

# 新增定时任务
curl -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"name":"测试","command":"python scripts/demo.py","schedule":"0 9 * * *"}' \
  http://127.0.0.1:5700/api/crons

# 调用 AI
curl -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"prompt":"写一个打印 hello 的 python 脚本"}' \
  http://127.0.0.1:5700/api/ai/generate_script
```

## 性能与内存优化要点

- 单进程 + 后台调度线程，任务执行走 **有界线程池**（默认 5 并发，可在系统设置调整）。
- 日志直接 **流式写入磁盘文件**，不在内存中堆积。
- SQLite 使用 **WAL** 模式，读写互不阻塞。
- 前端为**零依赖原生 JS**，无需 Node/Webpack 构建。
- 依赖最小化：`Flask` + `APScheduler` + `requests`（可选 `waitress` 提升并发）。
