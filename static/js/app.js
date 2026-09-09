/* 青豆面板 - 前端 SPA（原生 JS，无构建依赖） */
const API_BASE = "";
let TOKEN = localStorage.getItem("qd_token") || "";
let ROLE = localStorage.getItem("qd_role") || "";
let CURRENT = "dashboard";
let wxTimer = null;
let yybTimer = null;
let metricsTimer = null;
let filesTimer = null;

/* 权限：viewer(0) < op(1) < admin(2) */
function roleLevel(r) { return { viewer: 0, op: 1, admin: 2 }[r] || -1; }
function canOp() { return roleLevel(ROLE) >= 1; }
function canAdmin() { return roleLevel(ROLE) >= 2; }
function roleText(r) { return { admin: "管理员", op: "操作员", viewer: "只读" }[r] || r; }

/* 主题（黑/白皮肤）初始化：尽早应用，避免闪烁，且不依赖 $ 助手（避免 TDZ 错误） */
(function () {
  try {
    var t = localStorage.getItem("qd_theme") || "dark";
    document.documentElement.setAttribute("data-theme", t);
  } catch (e) {}
})();

const NAV = [
  { id: "dashboard", icon: "🏠", label: "仪表盘" },
  { id: "tasks", icon: "⏰", label: "定时任务" },
  { id: "scripts", icon: "📜", label: "脚本管理" },
  { id: "subs", icon: "🔗", label: "订阅管理" },
  { id: "deps", icon: "📦", label: "依赖安装" },
  { id: "envs", icon: "🔐", label: "环境变量" },
  { id: "notifs", icon: "🔔", label: "通知设置" },
  { id: "ai", icon: "🤖", label: "AI 对接" },
  { id: "files", icon: "🗂️", label: "文件管理" },
  { id: "monitor", icon: "📈", label: "系统监控" },
  { id: "yybgo", icon: "💬", label: "微信对接" },
  { id: "jdcookie", icon: "🛒", label: "京东Cookie" },
  { id: "users", icon: "👥", label: "用户管理", adminOnly: true },
  { id: "system", icon: "⚙️", label: "系统设置" },
];

/* ---------- 工具 ---------- */
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => Array.from(r.querySelectorAll(s));
function esc(s) { return String(s == null ? "" : s).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])); }
function badge(text, cls) { return `<span class="badge ${cls}">${esc(text)}</span>`; }
function statusBadge(s) {
  if (s === "success") return badge("成功", "b-green");
  if (s === "failed") return badge("失败", "b-red");
  if (s === "timeout") return badge("超时", "b-yellow");
  if (s === "running") return badge("运行中", "b-blue");
  if (s === "skipped") return badge("跳过", "b-gray");
  return badge(s || "-", "b-gray");
}
function toast(msg, ok = true) {
  const t = $("#toast");
  t.textContent = msg;
  t.style.borderColor = ok ? "var(--accent)" : "var(--red)";
  t.classList.add("show");
  clearTimeout(t._t);
  t._t = setTimeout(() => t.classList.remove("show"), 2600);
}
async function api(method, path, body) {
  const headers = { "Authorization": "Bearer " + TOKEN };
  const opt = { method, headers };
  if (body !== undefined) { headers["Content-Type"] = "application/json"; opt.body = JSON.stringify(body); }
  const r = await fetch(API_BASE + "/api" + path, opt);
  if (r.status === 401) { showLogin(); throw new Error("未授权"); }
  const text = await r.text();
  if (!text.trim()) {
    return { code: 1, msg: `服务器返回空响应（HTTP ${r.status}）`, data: null };
  }
  let j;
  try { j = JSON.parse(text); }
  catch (e) {
    let tip = text.slice(0, 80).replace(/\s+/g, " ");
    if (r.status === 404) {
      tip = `接口未找到（HTTP 404），请重启面板以加载最新代码`;
    } else if (r.status >= 500) {
      tip = `服务器内部错误（HTTP ${r.status}）：${tip}`;
    } else {
      tip = `响应解析失败（HTTP ${r.status}）：${tip}`;
    }
    return { code: 1, msg: tip, data: null };
  }
  return j;
}
async function apiGet(path) { return api("GET", path); }
async function apiPost(path, body) { return api("POST", path, body); }
async function apiPut(path, body) { return api("PUT", path, body); }
async function apiDel(path) { return api("DELETE", path); }

/* ---------- 模态 ---------- */
function openModal(title, bodyHtml, footHtml = "", wide = false) {
  $("#modal-title").textContent = title;
  $("#modal-body").innerHTML = bodyHtml;
  $("#modal-foot").innerHTML = footHtml;
  $("#modal").classList.toggle("wide", wide);
  $("#overlay").classList.add("show");
}
function closeModal() { $("#overlay").classList.remove("show"); }
$("#overlay").addEventListener("click", e => { if (e.target.id === "overlay") closeModal(); });

/* ---------- 鉴权 ---------- */
function showLogin() {
  $("#app").classList.add("hidden");
  $("#login").style.display = "flex";
  const tbtn = $("#theme-toggle-login");
  if (tbtn) tbtn.style.display = "inline-block";
  refreshLoginOptions();
}
function hideLogin() {
  $("#login").style.display = "none";
  $("#app").classList.remove("hidden");
  const tbtn = $("#theme-toggle-login");
  if (tbtn) tbtn.style.display = "none";
}
async function doLogin() {
  const username = $("#login-user").value.trim();
  const password = $("#login-pass").value;
  try {
    const r = await fetch(API_BASE + "/api/login", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, password }),
    });
    const j = await r.json();
    if (j.code === 0) {
      TOKEN = j.data.token;
      ROLE = j.data.role || "admin";
      localStorage.setItem("qd_token", TOKEN);
      localStorage.setItem("qd_role", ROLE);
      bootApp();
    } else toast(j.msg || "登录失败", false);
  } catch (e) { toast("登录请求失败", false); }
}
function logout() {
  apiPost("/logout", {}).catch(() => {});
  TOKEN = ""; ROLE = ""; localStorage.removeItem("qd_token"); localStorage.removeItem("qd_role");
  showLogin();
}
async function showChangePw() {
  openModal("修改密码", `
    <label>原密码</label><input id="pw_old" type="password">
    <label>新密码（≥6位）</label><input id="pw_new" type="password">`,
    `<button class="ghost" onclick="closeModal()">取消</button><button class="primary" onclick="submitChangePw()">保存</button>`);
}
async function submitChangePw() {
  const j = await apiPost("/change_password", { old_password: $("#pw_old").value, new_password: $("#pw_new").value }).catch(() => ({ code: 1, msg: "失败" }));
  if (j.code === 0) { toast("密码已修改"); closeModal(); } else toast(j.msg, false);
}

/* ---------- 主题皮肤（黑/白切换） ---------- */
function applyTheme(t) {
  if (!t) t = localStorage.getItem("qd_theme") || "dark";
  document.documentElement.setAttribute("data-theme", t);
  localStorage.setItem("qd_theme", t);
  const btn = $("#theme-toggle-login");
  if (btn) btn.textContent = t === "dark" ? "☀️ 白色" : "🌙 黑色";
}
function toggleTheme() {
  const cur = document.documentElement.getAttribute("data-theme") || "dark";
  applyTheme(cur === "dark" ? "light" : "dark");
}

/* ---------- 微信扫码登录（yyb-go 对接） ---------- */
async function refreshLoginOptions() {
  const j = await apiGet("/yybgo/status").catch(() => ({ code: 1 }));
  if (j.code === 0 && j.data && j.data.enabled) {
    const b = $("#btn-wx");
    if (b) b.style.display = "block";
  }
}
function showWxLogin() {
  openModal("微信扫码登录",
    `<div style="text-align:center;">
       <div id="wxqr" style="display:inline-block;padding:10px;background:#fff;border-radius:8px;min-width:220px;min-height:220px;line-height:220px;color:#888;">正在生成…</div>
       <p class="muted" id="wxstatus">请使用微信/应用宝扫码并在手机上确认</p>
       <div class="toolbar" style="justify-content:center;"><button class="ghost sm" onclick="startWx()">刷新二维码</button><button class="ghost sm" onclick="closeModal()">取消</button></div>
     </div>`);
  startWx();
}
async function startWx() {
  if (wxTimer) { clearTimeout(wxTimer); wxTimer = null; }
  const j = await apiPost("/yybgo/qr", {}).catch(() => ({ code: 1, msg: "请求失败" }));
  if (j.code !== 0) { const e = $("#wxqr"); if (e) e.innerHTML = '<span style="color:#c33;line-height:normal;">生成失败：' + esc(j.msg) + '</span>'; return; }
  $("#wxqr").innerHTML = '<img src="' + j.data.image + '" style="width:200px;height:200px;display:block;">';
  pollWx(j.data.session_id);
}
async function pollWx(sid) {
  const j = await apiGet("/yybgo/qr/" + sid + "/poll").catch(() => ({ code: 1 }));
  if (j.code !== 0) { $("#wxstatus").textContent = "轮询失败，请刷新"; return; }
  const d = j.data || {};
  if (d.expired) { $("#wxstatus").textContent = "二维码已过期，请点击刷新"; return; }
  $("#wxstatus").textContent = "状态：" + (d.status || "等待扫码") + "（请在手机上确认）";
  if (d.ready) { confirmWx(sid); return; }
  wxTimer = setTimeout(() => pollWx(sid), 1500);
}
async function confirmWx(sid) {
  const j = await apiPost("/yybgo/qr/" + sid + "/confirm", {}).catch(() => ({ code: 1, msg: "确认失败" }));
  if (j.code !== 0) { $("#wxstatus").textContent = "确认失败：" + (j.msg || ""); return; }
  if (j.data && j.data.ready && j.data.token) {
    TOKEN = j.data.token;
    localStorage.setItem("qd_token", TOKEN);
    closeModal();
    bootApp();
  } else {
    $("#wxstatus").textContent = "登录缓冲未就绪，继续等待…";
    wxTimer = setTimeout(() => pollWx(sid), 1500);
  }
}

/* ---------- 导航 ---------- */
function renderNav() {
  const items = NAV.filter(n => !n.adminOnly || canAdmin());
  $("#nav").innerHTML = items.map(n =>
    `<a data-view="${n.id}" class="${n.id === CURRENT ? "active" : ""}"><span class="ico">${n.icon}</span>${n.label}</a>`).join("");
  $$("#nav a").forEach(a => a.onclick = () => navigate(a.dataset.view));
}
function navigate(view) {
  CURRENT = view;
  if (yybTimer) { clearInterval(yybTimer); yybTimer = null; }
  if (yybQrTimer) { clearInterval(yybQrTimer); yybQrTimer = null; }
  if (metricsTimer) { clearInterval(metricsTimer); metricsTimer = null; }
  if (filesTimer) { clearInterval(filesTimer); filesTimer = null; }
  $$("#nav a").forEach(a => a.classList.toggle("active", a.dataset.view === view));
  const map = {
    dashboard: renderDashboard, tasks: renderTasks, scripts: renderScripts,
    subs: renderSubs, deps: renderDeps, envs: renderEnvs, notifs: renderNotifs,
    ai: renderAI, files: renderFiles, monitor: renderMonitor, users: renderUsers,
    yybgo: renderYybgo, jdcookie: renderJdCookie, system: renderSystem,
  };
  (map[view] || renderDashboard)();
}

/* ---------- 仪表盘 ---------- */
async function renderDashboard() {
  $("#main").innerHTML = `<div class="page-head"><div><h2>仪表盘</h2><div class="sub">面板运行状态总览</div></div>
    <div class="toolbar"><button class="ghost" onclick="renderDashboard()">刷新</button></div></div>
    <div id="dash">加载中…</div>`;
  const j = await apiGet("/dashboard");
  if (j.code !== 0) return;
  const s = j.data.stats, sys = j.data.sys;
  $("#dash").innerHTML = `
    <div class="grid stats" style="margin-bottom:16px;">
      ${stat(s.tasks, "任务总数")}
      ${stat(s.enabled_tasks, "启用任务")}
      ${stat(s.success, "成功(最近)")}
      ${stat(s.failed, "失败(最近)")}
      ${stat(s.subscriptions, "订阅数")}
      ${stat(s.scripts, "脚本数")}
      ${stat(s.environments, "环境变量")}
      ${stat(s.notifications, "通知渠道")}
    </div>
    <div class="grid" style="grid-template-columns:1fr 1fr; gap:16px;">
      <div class="card"><div class="page-head"><h2 style="font-size:15px;">系统信息</h2></div>
        <table><tbody>
          <tr><td class="muted">面板版本</td><td>${esc(sys.version)}</td></tr>
          <tr><td class="muted">操作系统</td><td class="mono">${esc(sys.platform)}</td></tr>
          <tr><td class="muted">Python</td><td class="mono">${esc(sys.python)}</td></tr>
          <tr><td class="muted">Node.js</td><td class="mono">${esc(sys.node)}</td></tr>
          <tr><td class="muted">内存占用</td><td>${sys.mem_mb != null ? sys.mem_mb + " MB" : "—"}</td></tr>
          <tr><td class="muted">CPU</td><td>${sys.cpu_percent != null ? sys.cpu_percent + "%" : "—"}</td></tr>
          <tr><td class="muted">监听端口</td><td class="mono">${esc(sys.port)}</td></tr>
        </tbody></table>
      </div>
      <div class="card"><div class="page-head"><h2 style="font-size:15px;">最近执行</h2></div>
        ${j.data.recent_logs.length ? `<table><thead><tr><th>任务</th><th>状态</th><th>时间</th></tr></thead><tbody>
          ${j.data.recent_logs.map(l => `<tr><td>${esc(l.task_name || l.kind)}</td><td>${statusBadge(l.status)}</td><td class="muted nowrap">${esc(l.started_at)}</td></tr>`).join("")}
        </tbody></table>` : `<div class="empty">暂无执行记录</div>`}
      </div>
    </div>`;
}
function stat(n, l) { return `<div class="stat"><div class="num">${n}</div><div class="lbl">${l}</div></div>`; }

/* ---------- 定时任务 ---------- */
async function renderTasks() {
  $("#main").innerHTML = `<div class="page-head"><div><h2>定时任务</h2><div class="sub">支持 cron 定时执行 py / js / sh / 命令</div></div>
    <div class="toolbar"><button class="ghost" onclick="renderTasks()">刷新</button>
    ${canOp() ? `<button class="primary" onclick="taskForm()">+ 新建任务</button>
    <button class="ghost" onclick="runOnceForm()">▶ 立即运行</button>` : ""}</div></div>
    <div id="task-list">加载中…</div>`;
  const j = await apiGet("/tasks");
  if (j.code !== 0) return;
  const rows = j.data;
  // 运行中/排队状态
  let activeMap = {};
  try {
    const a = await apiGet("/tasks/active");
    if (a.code === 0) {
      (a.data.running || []).forEach(r => { if (r.task_id) activeMap[r.task_id] = "running"; });
      (a.data.queued_task_ids || []).forEach(tid => { if (!activeMap[tid]) activeMap[tid] = "queued"; });
    }
  } catch (e) {}
  if (!rows.length) { $("#task-list").innerHTML = `<div class="card empty">还没有任务，点击「新建任务」开始</div>`; return; }
  const op = canOp();
  $("#task-list").innerHTML = `<div class="card" style="padding:0;"><table><thead><tr>
    <th>名称</th><th>命令</th><th>计划(cron)</th><th>状态</th><th>上次结果</th><th>下次运行</th><th>操作</th></tr></thead><tbody>
    ${rows.map(t => `<tr>
      <td><b>${esc(t.name)}</b>${activeMap[t.id] === "running" ? ' <span class="badge b-blue">运行中</span>' : activeMap[t.id] === "queued" ? ' <span class="badge b-yellow">排队中</span>' : ''}</td>
      <td class="mono" style="max-width:280px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;" title="${esc(t.command)}">${esc(t.command)}</td>
      <td class="mono">${esc(t.schedule)}</td>
      <td>${t.status == 1 ? badge("启用", "b-green") : badge("停用", "b-gray")}</td>
      <td>${statusBadge(t.last_status)}</td>
      <td class="muted nowrap">${esc(t.next_run || "")}</td>
      <td class="nowrap">
        <button class="sm" onclick="viewTaskLogs(${t.id}, '${esc(t.name)}')">日志</button>
        ${op ? `<button class="sm" onclick="runTask(${t.id})">运行</button>
        <button class="sm" onclick="toggleTask(${t.id}, ${t.status == 1 ? 0 : 1})">${t.status == 1 ? "停用" : "启用"}</button>
        <button class="sm" onclick="taskForm(${t.id})">编辑</button>
        <button class="sm danger" onclick="delTask(${t.id})">删</button>` : ""}
      </td></tr>`).join("")}
  </tbody></table></div>`;
}
function taskForm(id) {
  const isEdit = !!id;
  const html = `<label>任务名称</label><input id="t_name">
    <label>执行命令（python / node / bash / task xxx.py / 任意命令）</label><textarea id="t_cmd" placeholder='例如：python "scripts/demo.py" 或 node "scripts/x.js"'></textarea>
    <div class="row2">
      <div><label>cron 计划（5 段）</label><input id="t_sched" value="0 0 * * *" class="mono" placeholder="分 时 日 月 周"></div>
      <div><label>状态</label><select id="t_status"><option value="1">启用</option><option value="0">停用</option></select></div>
    </div>
    <div class="row2">
      <div><label>失败/完成通知</label><select id="t_notify"><option value="0">不通知</option><option value="1">通知</option></select></div>
      <div><label>通知渠道ID（逗号分隔，留空=全部启用）</label><input id="t_ntype" placeholder="例如：1,2"></div>
    </div>
    <p class="muted" style="font-size:12px;">cron 示例：<code class="k">0 9 * * *</code> 每天9点 · <code class="k">*/10 * * * *</code> 每10分钟 · <code class="k">0 0 1 * *</code> 每月1号</p>`;
  openModal(isEdit ? "编辑任务" : "新建任务", html,
    `<button class="ghost" onclick="closeModal()">取消</button><button class="primary" onclick="saveTask(${id || 0})">保存</button>`);
  if (isEdit) apiGet("/tasks").then(j => {
    const t = j.data.find(x => x.id == id); if (!t) return;
    $("#t_name").value = t.name; $("#t_cmd").value = t.command; $("#t_sched").value = t.schedule;
    $("#t_status").value = t.status; $("#t_notify").value = t.notify; $("#t_ntype").value = t.notify_type || "";
  });
}
async function saveTask(id) {
  const body = {
    name: $("#t_name").value.trim(), command: $("#t_cmd").value.trim(),
    schedule: $("#t_sched").value.trim(), status: parseInt($("#t_status").value),
    notify: parseInt($("#t_notify").value), notify_type: $("#t_ntype").value.trim(),
  };
  const j = id ? await apiPut("/tasks/" + id, body) : await apiPost("/tasks", body);
  if (j.code === 0) { toast("已保存"); closeModal(); renderTasks(); } else toast(j.msg, false);
}
async function runTask(id) { const j = await apiPost("/tasks/" + id + "/run", {}); toast(j.code === 0 ? "已提交执行" : j.msg, j.code === 0); }
async function toggleTask(id, st) { const j = await apiPost("/tasks/" + id + "/enable", { status: st }); if (j.code === 0) renderTasks(); }
async function delTask(id) { if (!confirm("确认删除该任务？")) return; const j = await apiDel("/tasks/" + id); if (j.code === 0) { toast("已删除"); renderTasks(); } }
function runOnceForm() {
  openModal("立即运行命令", `<label>命令</label><textarea id="ro_cmd" placeholder='python "scripts/demo.py"'></textarea>
    <label>任务名（仅用于日志标识）</label><input id="ro_name" value="一次性任务">`,
    `<button class="ghost" onclick="closeModal()">取消</button><button class="primary" onclick="submitRunOnce()">运行</button>`);
}
async function submitRunOnce() {
  const j = await apiPost("/tasks/run_once", { command: $("#ro_cmd").value.trim(), name: $("#ro_name").value });
  if (j.code === 0) { toast("已提交执行"); closeModal(); } else toast(j.msg, false);
}

/* ---------- 任务日志 ---------- */
async function viewTaskLogs(tid, name) {
  const j = await apiGet("/tasks/" + tid + "/logs"); if (j.code !== 0) return;
  const logs = j.data;
  const body = logs.length ? `<table><thead><tr><th>ID</th><th>状态</th><th>耗时</th><th>开始时间</th><th></th></tr></thead><tbody>
    ${logs.map(l => `<tr><td>#${l.id}</td><td>${statusBadge(l.status)}</td><td>${l.duration != null ? l.duration + "s" : "-"}</td>
      <td class="muted nowrap">${esc(l.started_at || "")}</td>
      <td><button class="sm" onclick="viewLog(${l.id})">查看</button></td></tr>`).join("")}
  </tbody></table>` : `<div class="empty">该任务暂无执行日志</div>`;
  openModal("日志 · " + (name || ("#" + tid)), body, `<button class="primary" onclick="closeModal()">关闭</button>`, true);
}
async function viewLog(lid) {
  const j = await apiGet("/logs/" + lid); if (j.code !== 0) return;
  openModal("日志 #" + lid + " · " + (j.data.log.status || ""), `<div class="logview">${esc(j.data.content || "")}</div>`,
    `<button class="primary" onclick="closeModal()">关闭</button>`, true);
}

/* ---------- 脚本管理 ---------- */
async function renderScripts() {
  $("#main").innerHTML = `<div class="page-head"><div><h2>脚本管理</h2><div class="sub">位于 data/scripts 目录，可直接创建 / 编辑 / 运行</div></div>
    <div class="toolbar"><button class="ghost" onclick="renderScripts()">刷新</button>
    ${canOp() ? `<button class="primary" onclick="scriptForm()">+ 新建脚本</button>` : ""}</div></div>
    <div id="script-list">加载中…</div>`;
  const j = await apiGet("/scripts");
  if (j.code !== 0) return;
  const rows = j.data;
  if (!rows.length) { $("#script-list").innerHTML = `<div class="card empty">暂无脚本</div>`; return; }
  $("#script-list").innerHTML = `<div class="card" style="padding:0;"><table><thead><tr>
    <th>文件名</th><th>大小</th><th>修改时间</th><th>操作</th></tr></thead><tbody>
    ${rows.map(f => `<tr><td class="mono">${esc(f.name)}</td><td class="muted">${fmtSize(f.size)}</td>
      <td class="muted nowrap">${new Date(f.mtime * 1000).toLocaleString()}</td>
      <td class="nowrap">${canOp() ? `<button class="sm" onclick="scriptForm('${encodeURIComponent(f.name)}')">编辑</button>
      <button class="sm" onclick="runScript('${encodeURIComponent(f.name)}')">运行</button>
      <button class="sm danger" onclick="delScript('${encodeURIComponent(f.name)}')">删</button>` : ""}</td></tr>`).join("")}
  </tbody></table></div>`;
}
function fmtSize(b) { if (b < 1024) return b + " B"; if (b < 1048576) return (b / 1024).toFixed(1) + " KB"; return (b / 1048576).toFixed(1) + " MB"; }
async function scriptForm(name) {
  const nm = name ? decodeURIComponent(name) : "";
  const body = nm ? (await apiGet("/scripts/" + encodeURIComponent(nm))).data : { content: "" };
  const html = `<label>文件名（可含子目录，如 sub/a.py）</label><input id="s_name" value="${esc(nm)}">
    <label>内容</label><textarea id="s_content" style="min-height:360px;">${esc(body.content || "")}</textarea>`;
  openModal(nm ? "编辑脚本" : "新建脚本", html,
    `<button class="ghost" onclick="closeModal()">取消</button><button class="primary" onclick="saveScript('${encodeURIComponent(nm)}')">保存</button>`, true);
}
async function saveScript(orig) {
  const name = $("#s_name").value.trim();
  const j = orig ? await apiPut("/scripts/" + orig, { content: $("#s_content").value })
                 : await apiPost("/scripts", { name, content: $("#s_content").value });
  if (j.code === 0) { toast("已保存"); closeModal(); renderScripts(); } else toast(j.msg, false);
}
async function delScript(name) { if (!confirm("确认删除该脚本？")) return; const j = await apiDel("/scripts/" + name); if (j.code === 0) { toast("已删除"); renderScripts(); } }
async function runScript(name) { const j = await apiPost("/scripts/" + decodeURIComponent(name) + "/run", {}); toast(j.code === 0 ? "已提交执行" : j.msg, j.code === 0); }

/* ---------- 订阅管理 ---------- */
async function renderSubs() {
  $("#main").innerHTML = `<div class="page-head"><div><h2>订阅管理</h2><div class="sub">支持 Git 仓库 / 青龙格式 JSON 清单，自动导入脚本与定时任务</div></div>
    <div class="toolbar"><button class="ghost" onclick="renderSubs()">刷新</button>
    ${canOp() ? `<button class="primary" onclick="subForm()">+ 新建订阅</button>` : ""}</div></div>
    <div id="sub-list">加载中…</div>`;
  const j = await apiGet("/subscriptions"); if (j.code !== 0) return;
  const rows = j.data;
  if (!rows.length) { $("#sub-list").innerHTML = `<div class="card empty">暂无订阅</div>`; return; }
  $("#sub-list").innerHTML = `<div class="card" style="padding:0;"><table><thead><tr>
    <th>名称</th><th>类型</th><th>地址</th><th>分支</th><th>计划</th><th>状态</th><th>上次同步</th><th>操作</th></tr></thead><tbody>
    ${rows.map(s => `<tr><td><b>${esc(s.name)}</b></td><td>${badge(s.stype, "b-blue")}</td>
      <td class="mono" style="max-width:240px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;" title="${esc(s.url)}">${esc(s.url)}</td>
      <td>${esc(s.branch)}</td><td class="mono">${esc(s.schedule)}</td>
      <td>${s.status == 1 ? badge("启用", "b-green") : badge("停用", "b-gray")}</td>
      <td class="muted nowrap">${esc(s.last_sync || "-")} ${s.last_status ? statusBadge(s.last_status) : ""}${s.last_status === "failed" && s.last_error ? ` <span class="badge b-red" style="cursor:help;" title="${esc(s.last_error)}">?</span>` : ""}</td>
      <td class="nowrap"><button class="sm" onclick="subLogs(${s.id})">日志</button>
      ${canOp() ? `<button class="sm" onclick="syncSub(${s.id})">同步</button>
      <button class="sm" onclick="subForm(${s.id})">编辑</button>
      <button class="sm danger" onclick="delSub(${s.id})">删</button>` : ""}</td></tr>`).join("")}
  </tbody></table></div>`;
}
let subLogList = [];
async function subLogs(sid) {
  openModal("订阅同步日志", `<div>
    <div id="sublog-list" class="muted">加载中…</div>
    <div id="sublog-view" style="display:none;margin-top:12px;">
      <div class="toolbar" style="justify-content:space-between;"><b style="font-size:13px;" id="sublog-title">日志内容</b>
      <button class="sm ghost" onclick="subLogsBack()">← 返回列表</button></div>
      <pre id="sublog-content" class="mono" style="max-height:380px;overflow:auto;background:var(--bg2,rgba(127,127,127,.08));padding:10px;border-radius:8px;white-space:pre-wrap;word-break:break-all;font-size:12px;"></pre>
    </div></div>`,
    `<button class="ghost" onclick="closeModal()">关闭</button>`);
  const j = await apiGet(`/subscriptions/${sid}/logs`).catch(() => ({ code: 1 }));
  const box = $("#sublog-list");
  if (j.code !== 0) { box.textContent = j.msg || "加载失败"; return; }
  subLogList = j.data || [];
  if (!subLogList.length) { box.innerHTML = "暂无同步日志，点「同步」后会记录每次拉取结果。"; return; }
  box.innerHTML = `<table><thead><tr><th>开始时间</th><th>结束时间</th><th>状态</th><th>操作</th></tr></thead><tbody>
    ${subLogList.map(l => `<tr><td class="nowrap">${esc(l.started_at || "-")}</td>
      <td class="nowrap muted">${esc(l.finished_at || "-")}</td>
      <td>${l.status === "success" ? badge("成功", "b-green") : l.status ? badge("失败", "b-red") : badge("进行中", "b-yellow")}</td>
      <td><button class="sm" onclick="subLogView(${l.id})">查看</button></td></tr>`).join("")}
  </tbody></table>`;
  $("#sublog-view").style.display = "none";
  window._subLogsSid = sid;
}
function subLogsBack() {
  $("#sublog-view").style.display = "none";
  $("#sublog-list").style.display = "";
}
async function subLogView(logId) {
  const j = await apiGet(`/subscriptions/logs/${logId}`).catch(() => ({ code: 1 }));
  if (j.code !== 0) return toast(j.msg || "读取失败", false);
  $("#sublog-title").textContent = "日志内容（" + (j.data.started_at || "") + "）";
  $("#sublog-content").textContent = j.data.content || "（空）";
  $("#sublog-list").style.display = "none";
  $("#sublog-view").style.display = "";
}
function subForm(id) {
  const html = `<label>粘贴青龙 <b>ql repo</b> 命令（自动识别并填充下方字段）</label>
    <textarea id="sub_ql" rows="2" placeholder='ql repo https://github.com/user/repo.git "jd_|jx_|jddj_" "backUp" "^jd[^_]|USER|JD|function|sendNotify|utils" main'></textarea>
    <div style="margin:4px 0 10px;"><button type="button" class="sm" onclick="parseQlCmd()">解析并填充</button>
      <span class="muted" style="font-size:12px;">支持 ql repo / ql raw，代理前缀地址也会自动识别</span></div>
    <hr class="mt">
    <label>订阅名称</label><input id="sub_name">
    <label>类型</label><select id="sub_type"><option value="git">Git 仓库</option><option value="json">青龙格式 JSON 清单</option></select>
    <label>地址（git 仓库 URL 或 JSON 清单 URL）</label><input id="sub_url" placeholder="https://github.com/user/repo.git">
    <div class="row2"><div><label>分支（git 用）</label><input id="sub_branch" value="main"></div>
    <div><label>别名（目录名/脚本前缀）</label><input id="sub_alias" placeholder="myrepo"></div></div>
    <div class="row2"><div><label>同步计划 cron</label><input id="sub_sched" value="0 0 * * *" class="mono"></div>
    <div><label>状态</label><select id="sub_status"><option value="1">启用</option><option value="0">停用</option></select></div></div>
    <label>白名单（含这些关键词才导入，竖线分隔，留空=全部）</label><input id="sub_white" placeholder="jd_|jx_|jddj_">
    <label>黑名单（匹配则跳过，竖线分隔）</label><input id="sub_black" placeholder="backUp">
    <label>依赖过滤（命中的文件视为依赖、不导入为任务，竖线分隔）</label><input id="sub_dep" placeholder="^jd[^_]|USER|JD|function|sendNotify|utils">`;
  openModal(id ? "编辑订阅" : "新建订阅", html,
    `<button class="ghost" onclick="closeModal()">取消</button><button class="primary" onclick="saveSub(${id || 0})">保存</button>`);
  if (id) apiGet("/subscriptions").then(j => { const s = j.data.find(x => x.id == id); if (!s) return;
    $("#sub_name").value = s.name; $("#sub_type").value = s.stype; $("#sub_url").value = s.url;
    $("#sub_branch").value = s.branch; $("#sub_alias").value = s.alias; $("#sub_sched").value = s.schedule; $("#sub_status").value = s.status;
    $("#sub_white").value = s.whitelist || ""; $("#sub_black").value = s.blacklist || ""; $("#sub_dep").value = s.dependence || ""; });
}
async function parseQlCmd() {
  const cmd = ($("#sub_ql").value || "").trim();
  if (!cmd) return toast("请先粘贴 ql repo 命令", false);
  const btn = $("button[onclick='parseQlCmd()']");
  const old = btn ? btn.textContent : "";
  if (btn) { btn.disabled = true; btn.textContent = "解析中…"; }
  try {
    const j = await apiPost("/subscriptions/parse-ql", { command: cmd });
    if (j.code !== 0) {
      return toast(j.msg || "解析失败", false);
    }
    const d = j.data || {};
    if (!d.url) {
      return toast("未能从命令中识别出仓库地址，请检查是否为 ql repo <url> ... 格式", false);
    }
    if (d.name) $("#sub_name").value = d.name;
    if (d.alias) $("#sub_alias").value = d.alias;
    $("#sub_url").value = d.url;
    $("#sub_branch").value = d.branch || "main";
    $("#sub_type").value = d.stype || "git";
    $("#sub_white").value = d.whitelist || "";
    $("#sub_black").value = d.blacklist || "";
    $("#sub_dep").value = d.dependence || "";
    toast("已自动识别并填充 ✅");
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = old || "解析并填充"; }
  }
}
async function saveSub(id) {
  const body = { name: $("#sub_name").value.trim(), stype: $("#sub_type").value, url: $("#sub_url").value.trim(),
    branch: $("#sub_branch").value.trim(), alias: $("#sub_alias").value.trim(), schedule: $("#sub_sched").value.trim(), status: parseInt($("#sub_status").value),
    whitelist: $("#sub_white").value.trim(), blacklist: $("#sub_black").value.trim(), dependence: $("#sub_dep").value.trim() };
  const j = id ? await apiPut("/subscriptions/" + id, body) : await apiPost("/subscriptions", body);
  if (j.code === 0) { toast("已保存"); closeModal(); renderSubs(); } else toast(j.msg, false);
}
async function syncSub(id) {
  const j = await apiPost("/subscriptions/" + id + "/sync", {});
  toast(j.code === 0 ? "已提交同步，正在后台拉取…" : j.msg, j.code === 0);
  if (j.code === 0) setTimeout(renderSubs, 4000);
}
async function delSub(id) { if (!confirm("确认删除该订阅？")) return; const j = await apiDel("/subscriptions/" + id); if (j.code === 0) { toast("已删除"); renderSubs(); } }

/* ---------- 依赖安装 ---------- */
async function renderDeps() {
  $("#main").innerHTML = `<div class="page-head"><div><h2>依赖安装</h2><div class="sub">支持 pip / npm / apt，后台执行不阻塞面板</div></div>
    <div class="toolbar"><button class="ghost" onclick="renderDeps()">刷新</button></div></div>
    <div class="card" style="margin-bottom:16px;">
      <div class="row2">
        <div><label>类型</label><select id="d_type"><option value="pip">pip (Python)</option><option value="npm">npm (Node)</option><option value="apt">apt (系统)</option></select></div>
        <div><label>包名（空格分隔多个）</label><input id="d_pkgs" placeholder="例如：requests beautifulsoup4"></div>
      </div>
      <div class="row2">
        <div><label>pip 可执行（可选）</label><input id="d_pip" placeholder="默认 pip"></div>
        <div><label>npm 可执行（可选）</label><input id="d_npm" placeholder="默认 npm"></div>
      </div>
      <div style="margin-top:12px;">${canOp() ? `<button class="primary" onclick="installDep()">安装</button>` : `<span class="muted">只读角色无安装权限</span>`}</div>
    </div>
    <div id="dep-list">加载中…</div>`;
  const j = await apiGet("/dependencies"); if (j.code !== 0) return;
  const rows = j.data;
  $("#dep-list").innerHTML = rows.length ? `<div class="card" style="padding:0;"><table><thead><tr>
    <th>类型</th><th>依赖</th><th>状态</th><th>时间</th><th>操作</th></tr></thead><tbody>
    ${rows.map(d => `<tr><td>${badge(d.dtype, "b-blue")}</td><td class="mono">${esc(d.name)}</td>
      <td>${statusBadge(d.status)}</td><td class="muted nowrap">${esc(d.created_at || "")}</td>
      <td><button class="sm" onclick="viewDepLog(${d.id})">日志</button></td></tr>`).join("")}
  </tbody></table></div>` : `<div class="card empty">暂无安装记录</div>`;
}
async function installDep() {
  const j = await apiPost("/dependencies/install", {
    dtype: $("#d_type").value, packages: $("#d_pkgs").value.trim(), pip: $("#d_pip").value.trim(), npm: $("#d_npm").value.trim(),
  });
  if (j.code === 0) { toast("已在后台安装"); renderDeps(); } else toast(j.msg, false);
}
async function viewDepLog(id) {
  const j = await apiGet("/dependencies/" + id + "/log"); if (j.code !== 0) return;
  openModal("依赖安装日志", `<div class="logview">${esc(j.data.content)}</div>`, `<button class="primary" onclick="closeModal()">关闭</button>`, true);
}

/* ---------- 环境变量 ---------- */
async function renderEnvs() {
  $("#main").innerHTML = `<div class="page-head"><div><h2>环境变量</h2><div class="sub">所有启用变量会在任务执行时注入环境</div></div>
    <div class="toolbar"><button class="ghost" onclick="renderEnvs()">刷新</button>
    ${canOp() ? `<button class="primary" onclick="envForm()">+ 新建变量</button>` : ""}</div></div>
    <div id="env-list">加载中…</div>`;
  const j = await apiGet("/environments"); if (j.code !== 0) return;
  const rows = j.data;
  $("#env-list").innerHTML = rows.length ? `<div class="card" style="padding:0;"><table><thead><tr>
    <th>名称</th><th>值</th><th>备注</th><th>状态</th><th>操作</th></tr></thead><tbody>
    ${rows.map(e => `<tr><td class="mono"><b>${esc(e.name)}</b></td><td class="mono" style="max-width:300px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;" title="${esc(e.value)}">${esc(e.value)}</td>
      <td class="muted">${esc(e.remarks || "")}</td>      <td>${e.status == 1 ? badge("启用", "b-green") : badge("停用", "b-gray")}</td>
      <td class="nowrap">${canOp() ? `<button class="sm" onclick="envForm(${e.id})">编辑</button><button class="sm danger" onclick="delEnv(${e.id})">删</button>` : ""}</td></tr>`).join("")}
  </tbody></table></div>` : `<div class="card empty">暂无变量</div>`;
}
function envForm(id) {
  openModal(id ? "编辑变量" : "新建变量",
    `<label>变量名</label><input id="e_name"><label>变量值</label><input id="e_value">
     <label>备注</label><input id="e_remarks"><label>状态</label><select id="e_status"><option value="1">启用</option><option value="0">停用</option></select>`,
    `<button class="ghost" onclick="closeModal()">取消</button><button class="primary" onclick="saveEnv(${id || 0})">保存</button>`);
  if (id) apiGet("/environments").then(j => { const e = j.data.find(x => x.id == id); if (!e) return;
    $("#e_name").value = e.name; $("#e_value").value = e.value; $("#e_remarks").value = e.remarks; $("#e_status").value = e.status; });
}
async function saveEnv(id) {
  const body = { name: $("#e_name").value.trim(), value: $("#e_value").value, remarks: $("#e_remarks").value, status: parseInt($("#e_status").value) };
  const j = id ? await apiPut("/environments/" + id, body) : await apiPost("/environments", body);
  if (j.code === 0) { toast("已保存"); closeModal(); renderEnvs(); } else toast(j.msg, false);
}
async function delEnv(id) { if (!confirm("确认删除？")) return; const j = await apiDel("/environments/" + id); if (j.code === 0) { toast("已删除"); renderEnvs(); } }

/* ---------- 通知设置 ---------- */
const NOTIF_FIELDS = {
  pushplus: [{ k: "token", l: "Token" }],
  serverchan: [{ k: "sendkey", l: "SendKey" }],
  bark: [{ k: "key", l: "Key" }, { k: "base", l: "BaseURL(可选)" }],
  telegram: [{ k: "bot_token", l: "Bot Token" }, { k: "chat_id", l: "Chat ID" }],
  wecom: [{ k: "webhook", l: "Webhook" }],
  dingtalk: [{ k: "webhook", l: "Webhook" }],
  webhook: [{ k: "url", l: "URL" }, { k: "method", l: "方法(GET/POST)" }],
};
async function renderNotifs() {
  $("#main").innerHTML = `<div class="page-head"><div><h2>通知设置</h2><div class="sub">支持 pushplus / Server酱 / Bark / Telegram / 企业微信 / 钉钉 / 自定义 Webhook</div></div>
    <div class="toolbar"><button class="ghost" onclick="renderNotifs()">刷新</button>
    ${canOp() ? `<button class="primary" onclick="notifForm()">+ 新建渠道</button>` : ""}</div></div>
    <div id="notif-list">加载中…</div>`;
  const j = await apiGet("/notifications"); if (j.code !== 0) return;
  const rows = j.data;
  $("#notif-list").innerHTML = rows.length ? `<div class="card" style="padding:0;"><table><thead><tr>
    <th>名称</th><th>类型</th><th>默认</th><th>状态</th><th>操作</th></tr></thead><tbody>
    ${rows.map(n => `<tr><td><b>${esc(n.name)}</b> ${n.is_default ? badge("默认", "b-green") : ""}</td>
      <td>${badge(n.ntype, "b-blue")}</td><td>${n.is_default ? "是" : "否"}</td>
      <td>${n.status == 1 ? badge("启用", "b-green") : badge("停用", "b-gray")}</td>
      <td class="nowrap">${canOp() ? `<button class="sm" onclick="testNotif(${n.id})">测试</button>
      <button class="sm" onclick="notifForm(${n.id})">编辑</button><button class="sm danger" onclick="delNotif(${n.id})">删</button>` : ""}</td></tr>`).join("")}
  </tbody></table></div>` : `<div class="card empty">暂无通知渠道</div>`;
}
function notifForm(id) {
  const opts = Object.keys(NOTIF_FIELDS).map(k => `<option value="${k}">${k}</option>`).join("");
  openModal(id ? "编辑渠道" : "新建渠道",
    `<label>名称</label><input id="n_name">
     <label>类型</label><select id="n_type" onchange="notifFields()">${opts}</select>
     <div id="n_fields"></div>
     <div class="row2"><div><label>状态</label><select id="n_status"><option value="1">启用</option><option value="0">停用</option></select></div>
     <div><label>设为默认</label><select id="n_default"><option value="0">否</option><option value="1">是</option></select></div></div>`,
    `<button class="ghost" onclick="closeModal()">取消</button><button class="primary" onclick="saveNotif(${id || 0})">保存</button>`);
  if (id) apiGet("/notifications").then(j => { const n = j.data.find(x => x.id == id); if (!n) return;
    $("#n_name").value = n.name; $("#n_type").value = n.ntype; $("#n_status").value = n.status; $("#n_default").value = n.is_default;
    notifFields(); const cfg = JSON.parse(n.config || "{}");
    NOTIF_FIELDS[n.ntype].forEach(f => { const el = $("#nf_" + f.k); if (el) el.value = cfg[f.k] || ""; }); });
  else notifFields();
}
function notifFields() {
  const t = $("#n_type").value;
  $("#n_fields").innerHTML = NOTIF_FIELDS[t].map(f => `<label>${f.l}</label><input id="nf_${f.k}">`).join("");
}
async function saveNotif(id) {
  const t = $("#n_type").value;
  const cfg = {}; NOTIF_FIELDS[t].forEach(f => cfg[f.k] = $("#nf_" + f.k).value);
  const body = { name: $("#n_name").value.trim(), ntype: t, config: cfg, status: parseInt($("#n_status").value), is_default: parseInt($("#n_default").value) };
  const j = id ? await apiPut("/notifications/" + id, body) : await apiPost("/notifications", body);
  if (j.code === 0) { toast("已保存"); closeModal(); renderNotifs(); } else toast(j.msg, false);
}
async function testNotif(id) { const j = await apiPost("/notifications/" + id + "/test", {}); toast(j.code === 0 ? "已发送测试（" + (j.data.resp || "") + "）" : j.msg, j.code === 0); }
async function delNotif(id) { if (!confirm("确认删除？")) return; const j = await apiDel("/notifications/" + id); if (j.code === 0) { toast("已删除"); renderNotifs(); } }

/* ---------- AI 对接 ---------- */
async function renderAI() {
  $("#main").innerHTML = `<div class="page-head"><div><h2>AI 对接</h2><div class="sub">兼容 OpenAI / DeepSeek / 通义 / 本地 Ollama，用于脚本生成与日志分析</div></div>
    <div class="toolbar"><button class="ghost" onclick="renderAI()">刷新</button>
    ${canOp() ? `<button class="primary" onclick="aiForm()">+ 添加配置</button>` : ""}</div></div>
    <div class="grid" style="grid-template-columns:1fr 1fr; gap:16px;">
      <div class="card"><div class="page-head"><h2 style="font-size:15px;">配置列表</h2></div><div id="ai-list">加载中…</div></div>
      <div class="card"><div class="page-head"><h2 style="font-size:15px;">智能助手</h2></div>
        <div class="tabs"><button class="active" data-tab="chat" onclick="aiTab(this,'chat')">对话</button>
          <button data-tab="gen" onclick="aiTab(this,'gen')">生成脚本</button>
          <button data-tab="analyze" onclick="aiTab(this,'analyze')">分析日志</button></div>
        <div id="ai-tab-chat">${aiChatHtml()}</div>
        <div id="ai-tab-gen" class="hidden">${aiGenHtml()}</div>
        <div id="ai-tab-analyze" class="hidden">${aiAnalyzeHtml()}</div>
      </div></div>`;
  const j = await apiGet("/ai"); if (j.code !== 0) return;
  const rows = j.data;
  $("#ai-list").innerHTML = rows.length ? `<table><thead><tr><th>名称</th><th>模型</th><th>默认</th><th>操作</th></tr></thead><tbody>
    ${rows.map(a => `<tr><td><b>${esc(a.name)}</b> ${a.is_default ? badge("默认", "b-green") : ""}</td>
      <td class="mono">${esc(a.model || "-")}</td><td>${a.is_default ? "是" : "否"}</td>
      <td class="nowrap"><button class="sm" onclick="aiForm(${a.id})">编辑</button><button class="sm danger" onclick="delAi(${a.id})">删</button></td></tr>`).join("")}
  </tbody></table>` : `<div class="empty">暂无 AI 配置</div>`;
}
function aiTab(btn, tab) {
  $$(".tabs button").forEach(b => b.classList.toggle("active", b === btn));
  ["chat", "gen", "analyze"].forEach(t => $("#ai-tab-" + t).classList.toggle("hidden", t !== tab));
}
function aiChatHtml() {
  return `<div id="chat-box" class="logview" style="height:240px;margin-bottom:8px;"></div>
    <textarea id="chat-in" placeholder="输入消息，Enter 发送（Shift+Enter 换行）"></textarea>
    <div style="margin-top:8px;text-align:right;"><button class="primary" onclick="sendChat()">发送</button></div>`;
}
function aiGenHtml() {
  return `<label>需求描述（希望脚本做什么）</label><textarea id="gen-prompt" placeholder="例如：写一个 Python 脚本，抓取某网站标题并保存到 result.txt"></textarea>
    <div class="row2"><div><label>语言</label><select id="gen-lang"><option value="python">Python</option><option value="javascript">JavaScript</option></select></div></div>
    <div style="margin-top:8px;text-align:right;"><button class="primary" onclick="genScript()">生成</button></div>
    <label style="margin-top:12px;">生成结果</label><textarea id="gen-out" style="min-height:160px;"></textarea>
    <div style="margin-top:8px;text-align:right;"><button class="ghost" onclick="saveGenAsScript()">保存为脚本</button></div>`;
}
function aiAnalyzeHtml() {
  return `<label>选择最近日志进行分析</label><select id="an-log"><option value="">— 加载中 —</option></select>
    <div style="margin-top:8px;text-align:right;"><button class="primary" onclick="analyzeLog()">分析</button></div>
    <label style="margin-top:12px;">分析结论</label><div id="an-out" class="logview" style="min-height:140px;white-space:pre-wrap;">—</div>`;
}
let CHAT_MSGS = [];
async function sendChat() {
  const inp = $("#chat-in"); const text = inp.value.trim(); if (!text) return;
  CHAT_MSGS.push({ role: "user", content: text });
  $("#chat-box").innerHTML += `<div><b>你：</b>${esc(text)}</div>`; inp.value = "";
  const j = await apiPost("/ai/chat", { messages: CHAT_MSGS });
  if (j.code === 0) { CHAT_MSGS.push({ role: "assistant", content: j.data.content });
    $("#chat-box").innerHTML += `<div style="color:var(--accent-2)"><b>AI：</b>${esc(j.data.content)}</div>`; }
  else $("#chat-box").innerHTML += `<div style="color:var(--red)">错误：${esc(j.msg)}</div>`;
  $("#chat-box").scrollTop = $("#chat-box").scrollHeight;
}
async function genScript() {
  const j = await apiPost("/ai/generate_script", { prompt: $("#gen-prompt").value, lang: $("#gen-lang").value });
  if (j.code === 0) $("#gen-out").value = j.data.code; else toast(j.msg, false);
}
async function saveGenAsScript() {
  const code = $("#gen-out").value; if (!code) return;
  const name = "ai_" + Date.now() + ($("#gen-lang").value === "python" ? ".py" : ".js");
  const j = await apiPost("/scripts", { name, content: code });
  if (j.code === 0) { toast("已保存为脚本：" + name); } else toast(j.msg, false);
}
async function analyzeLog() {
  const lid = $("#an-log").value; if (!lid) { toast("请选择日志", false); return; }
  const j = await apiPost("/ai/analyze_log", { log_id: parseInt(lid) });
  if (j.code === 0) $("#an-out").textContent = j.data.analysis; else toast(j.msg, false);
}
function aiForm(id) {
  openModal(id ? "编辑 AI 配置" : "添加 AI 配置",
    `<label>名称</label><input id="a_name" placeholder="例如：DeepSeek">
     <label>提供商</label><select id="a_provider"><option value="openai">OpenAI 兼容</option><option value="deepseek">DeepSeek</option><option value="dashscope">通义千问</option><option value="ollama">本地 Ollama</option></select>
     <label>Base URL</label><input id="a_base" placeholder="https://api.openai.com/v1 或 http://127.0.0.1:11434/v1">
     <label>API Key</label><input id="a_key" type="password">
     <label>模型名</label><input id="a_model" placeholder="gpt-3.5-turbo / deepseek-chat">
     <div class="row2"><div><label>状态</label><select id="a_status"><option value="1">启用</option><option value="0">停用</option></select></div>
     <div><label>默认</label><select id="a_default"><option value="0">否</option><option value="1">是</option></select></div></div>`,
    `<button class="ghost" onclick="closeModal()">取消</button><button class="primary" onclick="saveAi(${id || 0})">保存</button>`);
  if (id) apiGet("/ai").then(j => { const a = j.data.find(x => x.id == id); if (!a) return;
    $("#a_name").value = a.name; $("#a_provider").value = a.provider; $("#a_base").value = a.base_url;
    $("#a_key").value = a.api_key; $("#a_model").value = a.model; $("#a_status").value = a.status; $("#a_default").value = a.is_default; });
}
async function saveAi(id) {
  const body = { name: $("#a_name").value.trim(), provider: $("#a_provider").value, base_url: $("#a_base").value.trim(),
    api_key: $("#a_key").value, model: $("#a_model").value.trim(), status: parseInt($("#a_status").value), is_default: parseInt($("#a_default").value) };
  const j = id ? await apiPut("/ai/" + id, body) : await apiPost("/ai", body);
  if (j.code === 0) { toast("已保存"); closeModal(); renderAI(); } else toast(j.msg, false);
}
async function delAi(id) { if (!confirm("确认删除？")) return; const j = await apiDel("/ai/" + id); if (j.code === 0) { toast("已删除"); renderAI(); } }

/* ---------- 系统设置 ---------- */
async function renderSystem() {
  const info = await apiGet("/system/info"); const sett = await apiGet("/system/settings");
  const s = sett.data || {};
  $("#main").innerHTML = `<div class="page-head"><div><h2>系统设置</h2><div class="sub">面板运行参数、备份恢复与版本更新</div></div>
    <div class="toolbar"><button class="ghost" onclick="renderSystem()">刷新</button></div></div>
    <div class="grid" style="grid-template-columns:1fr 1fr; gap:16px; margin-bottom:16px;">
      <div class="card"><div class="page-head"><h2 style="font-size:15px;">运行参数</h2></div>
        <label>监听端口</label><input id="s_port" value="${esc(s.port || '5700')}">
        <label>最大并发任务数</label><input id="s_max" value="${esc(s.max_concurrent || '5')}">
        <label>单任务超时（秒）</label><input id="s_timeout" value="${esc(s.task_timeout || '3600')}">
        <label>时区</label><input id="s_tz" value="${esc(s.timezone || 'Asia/Shanghai')}">
        <label>Python 路径（留空=自动）</label><input id="s_py" value="${esc(s.python_path || '')}">
        <label>Node 路径（留空=自动）</label><input id="s_node" value="${esc(s.node_path || '')}">
        <p class="muted" style="font-size:12px;">端口 / 并发等修改后需重启面板生效</p>
        ${canAdmin() ? `<button class="primary" onclick="saveSettings()">保存设置</button>` : `<span class="muted">需管理员权限</span>`}
      </div>
      <div class="card"><div class="page-head"><h2 style="font-size:15px;">运维操作</h2></div>
        <p>当前面板版本：<b>${esc(info.data.version)}</b></p>
        <p>Python：${esc(info.data.python)} · Node：${esc(info.data.node)}</p>
        <p>内存：${info.data.mem_mb != null ? info.data.mem_mb + " MB" : "—"} · CPU：${info.data.cpu_percent != null ? info.data.cpu_percent + "%" : "—"}</p>
        <hr>
        ${canAdmin() ? `<div class="toolbar">
          <button onclick="reloadScheduler()">重载调度器</button>
          <button onclick="doRestart()">🔄 重启服务</button>
          <button class="danger" onclick="doStop()">🛑 关闭服务</button>
          <button onclick="startDaemon()">🚀 启动守护进程</button>
        </div>` : `<p class="muted">运维操作需管理员权限</p>`}
        <p class="muted" style="font-size:12px;margin-top:10px;">服务状态：运行中（PID <b id="svc_pid"></b>）· 关闭后可在本机双击 start.bat 重新启动，或使用上方「启动守护进程」</p>
        <p class="muted" style="font-size:12px;margin-top:12px;">开放 API Token（用于脚本/外部调用，Bearer 鉴权）：</p>
        <div class="mono" style="word-break:break-all;background:var(--bg);padding:8px;border-radius:8px;border:1px solid var(--border);" id="api-token">加载中…</div>
      </div>
    </div>
    <div class="grid" style="grid-template-columns:1fr 1fr; gap:16px;">
      <div class="card"><div class="page-head"><h2 style="font-size:15px;">备份与恢复</h2></div>
        <p class="muted" style="font-size:12px;margin-top:0;">导出当前全部设置项目（运行参数、任务、订阅、环境变量、通知、AI 配置、依赖记录、脚本内容），可用于迁移或回滚。</p>
        <div class="toolbar">
          <button class="primary" onclick="exportBackup()">📥 导出全部设置(JSON)</button>
          <button onclick="exportDb()">📦 导出数据库文件</button>
          ${canAdmin() ? `<button onclick="importBackup()">📤 导入恢复</button>` : ""}
        </div>
        <p class="muted" style="font-size:12px;margin-top:10px;">导入将覆盖现有同名配置，请谨慎操作；数据库文件含日志等完整数据。</p>
      </div>
      <div class="card"><div class="page-head"><h2 style="font-size:15px;">版本与更新（GitHub）</h2>
        <div class="toolbar"><button class="ghost" onclick="checkUpdate()">检查更新</button></div></div>
        <label>GitHub 仓库地址（如 https://github.com/你的用户名/你的仓库）</label><input id="gh_repo" value="${esc(s.github_repo || '')}" placeholder="https://github.com/user/repo">
        <div class="row2"><div><label>分支</label><input id="gh_branch" value="${esc(s.github_branch || 'main')}"></div>
        <div><label>自动更新</label><select id="gh_auto"><option value="0">关闭</option><option value="1">每日自动</option></select></div></div>
        <p class="muted" style="font-size:12px;">填写仓库并「保存」后，点击「检查更新」可比对远程提交；「立即更新」执行 git pull 并重启以应用新版本（需为 git 仓库且已联网）。</p>
        ${canAdmin() ? `<div class="toolbar"><button class="primary" onclick="saveGithub()">保存仓库设置</button>
        <button onclick="doUpdate()">⤴ 立即更新</button></div>` : `<p class="muted">需管理员权限</p>`}
        <div id="update-status" class="muted" style="font-size:12px;margin-top:10px;">尚未检查更新</div>
      </div>
    </div>`;
  const me = await apiGet("/me");
  $("#api-token").textContent = TOKEN || "(未登录)";
  if ($("#svc_pid")) $("#svc_pid").textContent = info.data.pid || "—";
  $("#gh_auto").value = s.github_auto_update || "0";
}
async function saveSettings() {
  const j = await apiPost("/system/settings", {
    port: $("#s_port").value, max_concurrent: $("#s_max").value, task_timeout: $("#s_timeout").value,
    timezone: $("#s_tz").value, python_path: $("#s_py").value, node_path: $("#s_node").value,
  });
  if (j.code === 0) toast("已保存（端口/并发需重启后生效）"); else toast(j.msg, false);
}
async function saveGithub() {
  const j = await apiPost("/system/settings", {
    github_repo: $("#gh_repo").value.trim(),
    github_branch: $("#gh_branch").value.trim() || "main",
    github_auto_update: $("#gh_auto").value,
  }).catch(() => ({ code: 1, msg: "保存失败" }));
  toast(j.code === 0 ? "仓库设置已保存" : (j.msg || "保存失败"), j.code === 0);
}
async function exportBackup() {
  try {
    const r = await fetch("/api/system/backup", { headers: { "Authorization": "Bearer " + TOKEN } });
    const blob = await r.blob();
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "qingdou-backup-" + new Date().toISOString().slice(0, 19).replace(/[:T]/g, "-") + ".json";
    a.click();
    URL.revokeObjectURL(a.href);
    toast("已导出全部设置");
  } catch (e) { toast("导出失败", false); }
}
async function exportDb() {
  try {
    const r = await fetch("/api/system/backup/db", { headers: { "Authorization": "Bearer " + TOKEN } });
    if (!r.ok) { toast("导出失败（权限不足？）", false); return; }
    const blob = await r.blob();
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "qingdou-" + new Date().toISOString().slice(0, 19).replace(/[:T]/g, "-") + ".db";
    a.click();
    URL.revokeObjectURL(a.href);
    toast("已开始下载数据库文件");
  } catch (e) { toast("导出失败", false); }
}
async function importBackup() {
  const inp = document.createElement("input");
  inp.type = "file"; inp.accept = ".json,application/json";
  inp.onchange = async () => {
    const f = inp.files[0]; if (!f) return;
    if (!confirm("导入将覆盖当前所有设置/任务/订阅/变量/通知/AI 配置，确认继续？")) return;
    let obj;
    try { obj = JSON.parse(await f.text()); } catch (e) { toast("JSON 解析失败", false); return; }
    const j = await apiPost("/system/restore", obj).catch(() => ({ code: 1, msg: "导入失败" }));
    toast(j.code === 0 ? "已从备份恢复" : (j.msg || "导入失败"), j.code === 0);
    if (j.code === 0) renderSystem();
  };
  inp.click();
}
async function checkUpdate() {
  const j = await apiGet("/system/update/check").catch(() => ({ code: 1 }));
  if (j.code !== 0) { toast("检查失败", false); return; }
  const d = j.data;
  let html = `当前版本：<b>${esc(d.panel_version)}</b><br>`;
  if (!d.has_git) html += `<span class="badge b-red">未安装 git</span> `;
  if (!d.is_repo) html += `<span class="badge b-yellow">非 git 仓库</span> 需在仓库目录运行才能自动更新<br>`;
  html += `本地提交：<span class="mono">${esc(d.current_commit || '-')}</span><br>`;
  html += `远程提交：<span class="mono">${esc(d.remote_commit || '-')}</span><br>`;
  html += d.behind ? `<span class="badge b-yellow">有更新可用</span>` : `<span class="badge b-green">已是最新</span>`;
  $("#update-status").innerHTML = html;
}
async function doUpdate() {
  if (!confirm("将执行 git pull 并重启面板以应用更新，确认？")) return;
  toast("正在更新…");
  const j = await apiPost("/system/update/do", {}).catch(() => ({ code: 1, msg: "更新失败" }));
  if (j.code !== 0) { toast(j.msg || "更新失败", false); return; }
  pollUntilAlive(() => toast("更新完成，已重启"));
}
async function reloadScheduler() { const j = await apiPost("/system/reload_scheduler", {}); if (j.code === 0) toast("调度器已重载"); }
async function doRestart() {
  if (!confirm("确认重启面板服务？重启后会自动恢复并刷新页面。")) return;
  toast("正在重启服务…");
  const j = await apiPost("/system/restart", {}).catch(() => ({ code: 1, msg: "请求失败" }));
  if (j.code !== 0) { toast(j.msg || "重启失败", false); return; }
  pollUntilAlive(() => { toast("已重启，正在刷新…"); location.reload(); });
}
async function doStop() {
  if (!confirm("确认关闭面板服务？关闭后需手动重新启动。")) return;
  toast("正在关闭服务…");
  const j = await apiPost("/system/stop", {}).catch(() => ({ code: 1, msg: "请求失败" }));
  if (j.code !== 0) { toast(j.msg || "关闭失败", false); return; }
  waitUntilDead(() => toast("服务已关闭，可双击 start.bat 或用「启动守护进程」重新拉起", false));
}
async function startDaemon() {
  const j = await apiPost("/system/start-daemon", {}).catch(() => ({ code: 1, msg: "操作失败" }));
  if (j.code === 0) { toast((j.data && j.data.msg) || "已启动守护进程"); pollUntilAlive(() => toast("守护进程已就绪")); }
  else toast(j.msg || "启动失败", false);
}
function pollUntilAlive(cb) {
  let n = 0;
  const t = setInterval(async () => {
    n++;
    try { const r = await fetch("/healthz"); if (r.ok) { clearInterval(t); cb(); return; } } catch (e) {}
    if (n > 40) clearInterval(t);
  }, 1000);
}
function waitUntilDead(cb) {
  let n = 0;
  const t = setInterval(async () => {
    n++;
    try { await fetch("/healthz"); } catch (e) { clearInterval(t); cb(); return; }
    if (n > 20) { clearInterval(t); cb(); }
  }, 1000);
}

/* ---------- 微信对接（yyb-go，独立页面） ---------- */
async function renderYybgo() {
  if (yybTimer) { clearInterval(yybTimer); yybTimer = null; }
  if (yybQrTimer) { clearInterval(yybQrTimer); yybQrTimer = null; }
  $("#main").innerHTML = `<div class="page-head"><div><h2>微信对接</h2><div class="sub">内置京东扫码（纯 Python，推荐）或外部 yyb-go 微信扫码，双模式可切换</div></div>
    <div class="toolbar"><button class="ghost" onclick="loadYybgo()">刷新</button>
    <button class="primary" onclick="yybAddAccount()">＋ 扫码添加账号</button></div></div>
    <div class="grid" style="grid-template-columns:1fr 1fr; gap:16px; margin-bottom:16px;">
      <div class="card"><div class="page-head"><h2 style="font-size:15px;">对接模式</h2></div>
        <label>登录源</label><select id="yyb_mode" onchange="yybModeChanged()"><option value="builtin">内置京东扫码（推荐，纯 Python 无需外部程序）</option><option value="external">外部 yyb-go（微信扫码，需本机 yyb-go.exe）</option></select>
        <div id="yyb-svc-ext">
          <div class="page-head" style="margin-top:14px;"><h2 style="font-size:15px;">服务管理</h2>
            <div class="toolbar" id="yyb-svc-btns"></div></div>
          <div id="yyb-svc" class="muted">检测中…</div>
          <div class="row2" style="margin-top:10px;"><div><label>yyb-go 程序路径（exe 完整路径，用于本机一键启动）</label><input id="yyb_bin" placeholder="例如 D:\\tools\\yyb-go\\yyb-go.exe"></div>
          <div><label>启动参数（可选，如监听地址/端口）</label><input id="yyb_args" placeholder="例如 -addr 127.0.0.1:8899"></div></div>
        </div>
        <p class="muted" id="yyb-svc-builtin" style="font-size:12px;display:none;">内置模式在面板进程内直接运行，无需启动任何外部服务。扫码入口在「京东Cookie」页（手机京东 App 扫码自动获取 Cookie）。</p>
      </div>
      <div class="card"><div class="page-head"><h2 style="font-size:15px;">服务配置</h2></div>
        <label class="flex" style="gap:8px;font-size:13px;align-items:center;"><input type="checkbox" id="yyb_enabled" style="width:auto;"> 启用微信扫码登录面板（仅外部 yyb-go 模式有效）</label>
        <div class="row2"><div><label>服务地址（本机 IP，默认 127.0.0.1）</label><input id="yyb_host" value="127.0.0.1"></div>
        <div><label>端口（默认 8000，可自定义）</label><input id="yyb_port" value="8000"></div></div>
        <label>yyb-go API Token（YYB_API_TOKEN，留空则不修改）</label><input id="yyb_token" placeholder="留空表示不修改">
        <div class="toolbar"><button class="primary" onclick="saveYybConfig()">保存配置</button>
        <button onclick="testYyb()">测试连接</button>
        <a id="yyb_console" class="ghost" style="text-decoration:none;display:none;padding:7px 14px;border:1px solid var(--border);border-radius:8px;font-size:13px;" target="_blank" href="#">打开 yyb-go 控制台 ↗</a></div>
        <p class="muted" id="yyb_msg" style="font-size:12px;">外部模式启用后，登录页将出现「微信扫码登录」按钮。</p>
      </div>
    </div>
    <div class="card"><div class="page-head"><h2 style="font-size:15px;">已登录账号</h2>
      <div class="toolbar"><button class="ghost" onclick="loadYybConn()">刷新列表</button></div></div>
      <div id="yyb-accounts" class="muted">加载中…</div>
    </div>`;
  loadYybgo();
  loadYybService();
  yybTimer = setInterval(() => { if (CURRENT === "yybgo") { loadYybConn(); loadYybService(); } }, 8000);
}
function yybModeChanged() {
  const ext = $("#yyb_mode").value === "external";
  $("#yyb-svc-ext").style.display = ext ? "" : "none";
  $("#yyb-svc-builtin").style.display = ext ? "none" : "";
}
async function loadYybService() {
  const j = await apiGet("/yybgo/service").catch(() => null);
  const box = $("#yyb-svc"), btns = $("#yyb-svc-btns"), cons = $("#yyb_console");
  if (!box) return;
  if (!j || j.code !== 0) { box.innerHTML = `<span class="badge b-red">状态获取失败</span>`; return; }
  const d = j.data;
  if (d.builtin) {
    box.innerHTML = `<span class="dot green"></span><b>内置模式运行中</b> · 纯 Python，无需外部程序`;
    if (btns) btns.innerHTML = "";
    if (cons) cons.style.display = "none";
    return;
  }
  $("#yyb_bin").value = d.bin || "";
  $("#yyb_args").value = d.args || "";
  if (cons) { cons.href = d.console_url || "#"; cons.style.display = d.running ? "inline-block" : "none"; }
  let st;
  if (!d.bin) st = `<span class="badge b-gray">未配置程序路径</span> <span class="muted">在下方填写 yyb-go.exe 路径后可一键启动</span>`;
  else if (!d.exists) st = `<span class="badge b-red">程序不存在</span> <span class="mono">${esc(d.bin)}</span>`;
  else if (d.health_ok) st = `<span class="dot green"></span><b>运行中</b> · 端口 ${esc(d.port)} · <a href="${esc(d.console_url)}" target="_blank">${esc(d.console_url)}</a>${d.pid ? " · PID " + d.pid : ""}`;
  else if (d.listening) st = `<span class="dot green"></span><b>端口已监听</b>（health 未响应）· 端口 ${esc(d.port)}`;
  else if (d.running) st = `<span class="dot yellow"></span><b>进程在运行</b>但端口 ${esc(d.port)} 未监听（可能启动参数与端口配置不一致）`;
  else st = `<span class="dot gray"></span><b>已停止</b>`;
  box.innerHTML = st;
  if (btns) {
    const canStart = d.bin && d.exists;
    btns.innerHTML = `
      <button class="primary sm" ${canStart && !d.running ? "" : "disabled"} onclick="yybSvcStart()">▶ 启动服务</button>
      <button class="sm" ${d.running ? "" : "disabled"} onclick="yybSvcStop()">⏹ 停止服务</button>`;
  }
}
async function yybSvcStart() {
  if ($("#yyb_mode") && $("#yyb_mode").value !== "external") { toast("内置模式无需启动服务", true); return; }
  if (!$("#yyb_bin") || !confirmSaveYybBin()) return;
  toast("正在启动 yyb-go…");
  const j = await apiPost("/yybgo/service/start", {}).catch(() => ({ code: 1, msg: "请求失败" }));
  toast(j.msg || (j.code === 0 ? "已启动" : "启动失败"), j.code === 0);
  loadYybService(); loadYybConn();
}
async function yybSvcStop() {
  const j = await apiPost("/yybgo/service/stop", {}).catch(() => ({ code: 1, msg: "请求失败" }));
  toast(j.msg || (j.code === 0 ? "已停止" : "停止失败"), j.code === 0);
  loadYybService(); loadYybConn();
}
function confirmSaveYybBin() {
  const bin = $("#yyb_bin").value.trim();
  if (!bin) { toast("请先填写 yyb-go 程序路径", false); return false; }
  return true;
}
let yybQrTimer = null;
async function yybAddAccount() {
  const isBuiltin = $("#yyb_mode") && $("#yyb_mode").value === "builtin";
  if (isBuiltin) {
    toast("内置模式请到「京东Cookie」页扫码添加京东账号", false);
    return;
  }
  openModal("扫码添加微信账号", `<div style="text-align:center;">
      <div id="yyb-qr-status" class="muted" style="margin-bottom:10px;">正在生成二维码…</div>
      <div id="yyb-qr-img" style="min-height:220px;display:flex;align-items:center;justify-content:center;"></div>
      <p class="muted" style="font-size:12px;margin-top:10px;">请使用微信扫码并在手机上确认授权；成功后账号会出现在下方列表。</p>
    </div>`,
    `<button class="ghost" onclick="closeModal()">关闭</button>`);
  if (yybQrTimer) { clearInterval(yybQrTimer); yybQrTimer = null; }
  const j = await apiPost("/yybgo/qr", {}).catch(() => ({ code: 1, msg: "请求失败" }));
  if (j.code !== 0) { $("#yyb-qr-status").textContent = "❌ " + (j.msg || "生成失败（请确认 yyb-go 已启动且已配置 Token）"); return; }
  $("#yyb-qr-img").innerHTML = `<img src="${j.data.image}" style="width:220px;height:220px;border-radius:8px;" alt="二维码">`;
  $("#yyb-qr-status").textContent = "等待扫码…";
  const sid = j.data.session_id;
  let done = false;
  yybQrTimer = setInterval(async () => {
    if (done || CURRENT !== "yybgo") { clearInterval(yybQrTimer); yybQrTimer = null; return; }
    const p = await apiGet(`/yybgo/qr/${sid}/poll`).catch(() => null);
    if (!p || p.code !== 0) return;
    if (p.data.ready) {
      done = true; clearInterval(yybQrTimer); yybQrTimer = null;
      $("#yyb-qr-status").innerHTML = `<span class="badge b-green">扫码成功</span> 正在确认…`;
      const c = await apiPost(`/yybgo/qr/${sid}/confirm`, {}).catch(() => ({ code: 1 }));
      $("#yyb-qr-status").innerHTML = c.code === 0
        ? `<span class="badge b-green">添加成功 ✅</span> <span class="muted">可关闭本窗口</span>`
        : `<span class="badge b-yellow">已扫码</span> ${esc(c.msg || "确认接口未就绪，稍后刷新列表查看")}`;
      loadYybConn();
    } else if (p.data.expired) {
      done = true; clearInterval(yybQrTimer); yybQrTimer = null;
      $("#yyb-qr-status").innerHTML = `<span class="badge b-red">二维码已过期</span> <button class="sm" onclick="yybAddAccount()">重新生成</button>`;
    } else if (p.data.status) {
      $("#yyb-qr-status").textContent = "状态: " + p.data.status;
    }
  }, 2500);
}
async function loadYybgo() {
  const c = await apiGet("/yybgo/config").catch(() => ({ code: 1 }));
  if (c.code === 0 && c.data) {
    if ($("#yyb_mode")) $("#yyb_mode").value = c.data.mode || "builtin";
    yybModeChanged();
    $("#yyb_enabled").checked = !!c.data.enabled;
    $("#yyb_host").value = c.data.host || "127.0.0.1";
    $("#yyb_port").value = c.data.port || "8000";
    if ($("#yyb_bin")) $("#yyb_bin").value = c.data.bin || "";
    if ($("#yyb_args")) $("#yyb_args").value = c.data.args || "";
  }
  loadYybConn();
}
async function loadYybConn() {
  const j = await apiGet("/yybgo/connection").catch(() => ({ code: 1, msg: "请求失败" }));
  const conn = $("#yyb-conn");
  let builtin = false;
  if (j.code !== 0) { if (conn) conn.innerHTML = `<span class="badge b-red">检测失败</span> ${esc(j.msg || "")}`; }
  else {
    const d = j.data || {};
    builtin = d.mode === "builtin";
    if (!conn) { /* noop */ }
    else if (builtin) conn.innerHTML = `<span class="dot green"></span><b>内置扫码模式</b> · 京东账号直接在「京东Cookie」页扫码添加`;
    else if (!d.enabled) conn.innerHTML = `<span class="dot gray"></span><b>未启用</b> · 请在右侧开启并保存`;
    else if (d.connected) conn.innerHTML = `<span class="dot green"></span><b>已连接</b> · ${esc(d.url)}`;
    else conn.innerHTML = `<span class="dot red"></span><b>未连接</b> · ${esc(d.url)} ${d.error ? "（" + esc(d.error) + "）" : ""}`;
  }
  const box = $("#yyb-accounts");
  if (!box) return;
  const accs = (j.data && j.data.accounts) || [];
  if (builtin) {
    if (!accs.length) { box.innerHTML = `<span class="muted">暂无京东账号。请到「京东Cookie」页点「＋ 扫码登录京东」添加。</span>`; return; }
    box.innerHTML = `<table><thead><tr><th>京东账号</th><th>状态</th><th>pt_pin</th></tr></thead><tbody>
      ${accs.map(a => `<tr><td><b>${esc(a.label || a.nickname || "未知")}</b></td>
        <td>${badge(a.status === "alive" ? "正常" : "失效", a.status === "alive" ? "b-green" : "b-red")}</td>
        <td class="mono nowrap">${esc(a.openid || "")}</td></tr>`).join("")}
    </tbody></table>`;
    return;
  }
  if (!j.data || !j.data.connected) { box.innerHTML = `<span class="muted">未连接到 yyb-go，无法获取账号列表。</span>`; return; }
  if (!accs.length) { box.innerHTML = `<span class="muted">暂无已登录的微信账号。请在 yyb-go 中扫码登录后刷新。</span>`; return; }
  box.innerHTML = `<table><thead><tr><th>账号</th><th>状态</th><th>OpenID</th></tr></thead><tbody>
    ${accs.map(a => `<tr><td><b>${esc(a.label || a.nickname || "未知")}</b></td>
      <td>${a.status ? badge(a.status, a.status === "alive" ? "b-green" : "b-gray") : badge("未知", "b-gray")}</td>
      <td class="mono nowrap">${esc((a.openid || "").slice(0, 14) + ((a.openid || "").length > 14 ? "…" : ""))}</td></tr>`).join("")}
  </tbody></table>`;
}
async function saveYybConfig() {
  const j = await apiPost("/yybgo/config", {
    mode: $("#yyb_mode") ? $("#yyb_mode").value : "builtin",
    enabled: $("#yyb_enabled").checked,
    host: $("#yyb_host").value.trim() || "127.0.0.1",
    port: $("#yyb_port").value.trim() || "8000",
    token: $("#yyb_token").value,
    bin: $("#yyb_bin") ? $("#yyb_bin").value.trim() : "",
    args: $("#yyb_args") ? $("#yyb_args").value.trim() : "",
  }).catch(() => ({ code: 1, msg: "保存失败" }));
  toast(j.code === 0 ? "yyb-go 配置已保存" : (j.msg || "保存失败"), j.code === 0);
  if (j.code === 0) { $("#yyb_token").value = ""; loadYybgo(); loadYybService(); }
}
async function testYyb() {
  const j = await apiGet("/yybgo/health").catch(() => ({ code: 1, msg: "测试失败" }));
  const m = $("#yyb_msg");
  if (j.code === 0 && j.data) {
    if (m) m.textContent = j.data.ok ? "✅ 连接正常（HTTP " + j.data.status + "）" : ("❌ " + (j.data.msg || ("HTTP " + j.data.status)));
  } else if (m) m.textContent = (j.msg || "测试失败");
  loadYybConn();
}

/* ---------- 京东 Cookie（内置扫码 / yyb-go 双模式） ---------- */
async function renderJdCookie() {
  if (yybTimer) { clearInterval(yybTimer); yybTimer = null; }
  if (yybQrTimer) { clearInterval(yybQrTimer); yybQrTimer = null; }
  if (window.jdTimer) { clearInterval(window.jdTimer); window.jdTimer = null; }
  $("#main").innerHTML = `<div class="page-head"><div><h2>京东 Cookie</h2><div class="sub">内置京东扫码登录（纯 Python，无需外部程序），自动获取 pt_key/pt_pin 写入环境变量供青龙脚本使用</div></div>
    <div class="toolbar"><button class="primary" onclick="jdQrAdd()">＋ 扫码登录京东</button>
    <button class="ghost" onclick="renderJdCookie()">刷新</button></div></div>
    <div class="grid" style="grid-template-columns:1fr 1fr; gap:16px; margin-bottom:16px;">
      <div class="card"><div class="page-head"><h2 style="font-size:15px;">登录源状态</h2></div>
        <div id="jd-conn" class="muted">检测中…</div>
      </div>
      <div class="card"><div class="page-head"><h2 style="font-size:15px;">京东 Cookie 设置</h2></div>
        <label>登录源</label><select id="jd_login_source"><option value="builtin">内置扫码（推荐，纯 Python 无需外部程序）</option><option value="yybgo">外部 yyb-go（微信登录态驱动）</option></select>
        <label>环境变量名（脚本读取的键，默认 JD_COOKIE）</label><input id="jd_env_name" value="JD_COOKIE">
        <div class="row2"><div><label>Cookie 模式</label><select id="jd_cookie_mode"><option value="pt">pt（仅 pt_key/pt_pin）</option><option value="all">all（全部 Cookie）</option></select></div>
        <div><label>登录模式（仅 yyb-go 模式）</label><select id="jd_login_mode"><option value="auto">auto</option><option value="code">code</option><option value="full">full</option></select></div></div>
        <div class="row2"><div><label>自动检查 cron</label><input id="jd_cron" value="0 */2 * * *" class="mono"></div>
        <div><label class="flex" style="gap:8px;align-items:center;font-size:13px;margin-top:18px;"><input type="checkbox" id="jd_auto" style="width:auto;"> 启用自动检查</label></div></div>
        <div class="toolbar"><button class="primary" onclick="saveJdConfig()">保存设置</button>
        <button onclick="jdRefreshAll()">🔄 校验/刷新全部</button></div>
        <p class="muted" style="font-size:12px;">内置模式：手机京东 App 扫码 → 自动写入 Cookie；失效后需重新扫码（京东 Cookie 约 30 天有效）。yyb-go 模式：微信小程序 code 静默续期。</p>
      </div>
    </div>
    <div class="card" id="jd-acc-card"><div class="page-head"><h2 style="font-size:15px;" id="jd-acc-title">京东账号</h2>
      <div class="toolbar"><button class="ghost" onclick="loadJdAccounts()">刷新列表</button></div></div>
      <div id="jd-accounts" class="muted">加载中…</div>
    </div>
    <div class="card"><div class="page-head"><h2 style="font-size:15px;">已获取的京东 Cookie</h2></div>
      <div id="jd-cookies" class="muted">加载中…</div>
    </div>`;
  loadJdConfig();
  loadJdAccounts();
  window.jdTimer = setInterval(() => { if (CURRENT === "jdcookie") loadJdAccounts(); }, 15000);
}
async function loadJdConfig() {
  const c = await apiGet("/jdcookie/config").catch(() => ({ code: 1 }));
  if (c.code === 0 && c.data) {
    $("#jd_login_source").value = c.data.login_source || "builtin";
    $("#jd_env_name").value = c.data.cookie_env_name || "JD_COOKIE";
    $("#jd_cookie_mode").value = c.data.cookie_mode || "pt";
    $("#jd_login_mode").value = c.data.login_mode || "auto";
    $("#jd_cron").value = c.data.auto_refresh_cron || "0 */2 * * *";
    $("#jd_auto").checked = !!c.data.auto_refresh;
  }
}
async function saveJdConfig() {
  const j = await apiPost("/jdcookie/config", {
    login_source: $("#jd_login_source").value,
    cookie_env_name: $("#jd_env_name").value.trim() || "JD_COOKIE",
    cookie_mode: $("#jd_cookie_mode").value,
    login_mode: $("#jd_login_mode").value,
    auto_refresh_cron: $("#jd_cron").value.trim() || "0 */2 * * *",
    auto_refresh: $("#jd_auto").checked,
  }).catch(() => ({ code: 1, msg: "保存失败" }));
  toast(j.code === 0 ? "京东 Cookie 设置已保存" : (j.msg || "保存失败"), j.code === 0);
  if (j.code === 0) loadJdAccounts();
}
async function loadJdAccounts() {
  const cj = await apiGet("/jdcookie/connection").catch(() => ({ code: 1, msg: "请求失败" }));
  const conn = $("#jd-conn");
  let builtin = true;
  if (conn) {
    if (cj.code !== 0) conn.innerHTML = `<span class="badge b-red">检测失败</span> ${esc(cj.msg || "")}`;
    else {
      const d = cj.data || {};
      builtin = d.mode !== "external";
      if (builtin) conn.innerHTML = `<span class="dot green"></span><b>内置扫码模式</b> · 纯 Python 京东扫码，无需外部服务`;
      else if (!d.enabled) conn.innerHTML = `<span class="dot gray"></span><b>未启用</b> · 请先在「微信对接」开启 yyb-go`;
      else if (d.connected) conn.innerHTML = `<span class="dot green"></span><b>已连接</b> · ${esc(d.url)}`;
      else conn.innerHTML = `<span class="dot red"></span><b>未连接</b> · ${esc(d.url)} ${d.error ? "（" + esc(d.error) + "）" : ""}`;
    }
  }
  const accBox = $("#jd-accounts"), accTitle = $("#jd-acc-title");
  const accs = (cj.data && cj.data.accounts) || [];
  if (accBox && !builtin) {
    if (accTitle) accTitle.textContent = "微信账号（点击获取京东 Cookie）";
    if (!cj.data || !cj.data.connected) accBox.innerHTML = `<span class="muted">未连接到 yyb-go，无法获取微信账号。</span>`;
    else if (!accs.length) accBox.innerHTML = `<span class="muted">暂无已登录微信账号，请在 yyb-go 中扫码登录后刷新。</span>`;
    else accBox.innerHTML = `<table><thead><tr><th>微信账号</th><th>状态</th><th>操作</th></tr></thead><tbody>
      ${accs.map(a => { const ref = a.openid || a.uin || a.id || ""; const label = a.label || a.nickname || "未知";
        return `<tr><td><b>${esc(label)}</b></td><td>${a.status ? badge(a.status, a.status === "alive" ? "b-green" : "b-gray") : badge("未知", "b-gray")}</td>
        <td><button class="sm" data-ref="${esc(ref)}" data-name="${esc(label)}" onclick="jdRefresh(this.dataset.ref, this.dataset.name)">获取 Cookie</button></td></tr>`; }).join("")}
    </tbody></table>`;
  }
  const ck = await apiGet("/jdcookie/accounts").catch(() => ({ code: 1, data: [] }));
  const ckBox = $("#jd-cookies");
  if (!ckBox) return;
  const list = ck.data || [];
  if (!list.length) {
    if (ckBox) ckBox.innerHTML = `<span class="muted">尚未获取任何京东 Cookie。点右上角「＋ 扫码登录京东」开始（手机京东 App 扫码即可）。</span>`;
    return;
  }
  ckBox.innerHTML = `<table><thead><tr><th>账号</th><th>京东账号(pt_pin)</th><th>状态</th><th>最后更新</th><th>过期</th><th>操作</th></tr></thead><tbody>
    ${list.map(r => `<tr>
      <td><b>${esc(r.name || r.ref)}</b></td>
      <td class="mono nowrap">${esc(r.pt_pin || "—")}</td>
      <td>${r.status === "ok" ? badge("正常", "b-green") : badge("失效", "b-red")}</td>
      <td class="muted nowrap">${esc(r.last_update || "—")}</td>
      <td class="muted nowrap">${esc(r.expire_at || "—")}</td>
      <td>${builtin
        ? `<button class="sm" data-ref="${esc(r.ref)}" onclick="jdCheck(this.dataset.ref)">校验</button>`
        : `<button class="sm" data-ref="${esc(r.ref)}" data-name="${esc(r.name || "")}" onclick="jdRefresh(this.dataset.ref, this.dataset.name)">刷新</button>`}
      <button class="sm danger" data-ref="${esc(r.ref)}" onclick="jdDeleteAccount(this.dataset.ref)">删</button></td></tr>`).join("")}
  </tbody></table>`;
}
let jdQrTimer = null;
async function jdQrAdd() {
  if (jdQrTimer) { clearInterval(jdQrTimer); jdQrTimer = null; }
  openModal("扫码登录京东", `<div style="text-align:center;">
      <div id="jd-qr-status" class="muted" style="margin-bottom:10px;">正在生成二维码…</div>
      <div id="jd-qr-img" style="min-height:220px;display:flex;align-items:center;justify-content:center;"></div>
      <p class="muted" style="font-size:12px;margin-top:10px;">请打开<b>手机京东 App</b> → 扫一扫，并在手机上点击「确认登录」。</p>
    </div>`,
    `<button class="ghost" onclick="closeModal()">关闭</button>`);
  const j = await apiPost("/jdcookie/qr", {}).catch(() => ({ code: 1, msg: "请求失败" }));
  if (j.code !== 0) { $("#jd-qr-status").textContent = "❌ " + (j.msg || "生成失败"); return; }
  $("#jd-qr-img").innerHTML = `<img src="${j.data.image}" style="width:220px;height:220px;border-radius:8px;background:#fff;padding:6px;" alt="京东二维码">`;
  $("#jd-qr-status").textContent = "等待扫码…（二维码约 5 分钟有效）";
  const sid = j.data.session_id;
  let done = false;
  jdQrTimer = setInterval(async () => {
    if (done) { clearInterval(jdQrTimer); jdQrTimer = null; return; }
    const p = await apiGet(`/jdcookie/qr/${sid}/poll`).catch(() => null);
    if (!p || p.code !== 0) return;
    if (p.data.status === "scanned") $("#jd-qr-status").textContent = "📱 已扫码，请在手机上确认登录…";
    if (p.data.expired) {
      done = true; clearInterval(jdQrTimer); jdQrTimer = null;
      $("#jd-qr-status").innerHTML = `<span class="badge b-red">二维码已过期</span> <button class="sm" onclick="jdQrAdd()">重新生成</button>`;
    } else if (p.data.status === "confirmed") {
      done = true; clearInterval(jdQrTimer); jdQrTimer = null;
      $("#jd-qr-status").innerHTML = `<span class="badge b-green">已确认</span> 正在获取 Cookie…`;
      const c = await apiPost(`/jdcookie/qr/${sid}/confirm`, {}).catch(() => ({ code: 1, msg: "请求失败" }));
      if (c.code === 0) {
        $("#jd-qr-status").innerHTML = `<span class="badge b-green">登录成功 ✅</span> <span class="muted">京东账号 ${esc(c.data.pt_pin || "")} 已写入环境变量，可关闭本窗口</span>`;
        loadJdAccounts();
      } else {
        $("#jd-qr-status").innerHTML = `<span class="badge b-red">获取失败</span> ${esc(c.msg || "")}`;
      }
    }
  }, 2500);
}
async function jdCheck(ref) {
  if (!ref) return toast("缺少 ref", false);
  toast("正在校验 Cookie…", true);
  const j = await apiPost("/jdcookie/check", { ref }).catch(() => ({ code: 1, msg: "请求失败" }));
  toast(j.code === 0 ? (j.msg || "校验完成") : (j.msg || "校验失败"), j.code === 0 && j.data && j.data.valid !== false);
  loadJdAccounts();
}
async function jdRefresh(ref, name) {
  if (!ref) return toast("缺少账号 ref", false);
  toast("正在获取京东 Cookie…", true);
  const j = await apiPost("/jdcookie/refresh", { ref, name }).catch(() => ({ code: 1, msg: "请求失败" }));
  toast(j.code === 0 ? (j.msg || "获取成功") : (j.msg || "获取失败"), j.code === 0);
  if (j.code === 0) loadJdAccounts();
}
async function jdRefreshAll() {
  toast("正在刷新全部账号…", true);
  const j = await apiPost("/jdcookie/refresh_all", {}).catch(() => ({ code: 1, msg: "请求失败" }));
  toast(j.code === 0 ? (j.msg || "完成") : (j.msg || "失败"), j.code === 0);
  if (j.code === 0) loadJdAccounts();
}
async function jdDeleteAccount(ref) {
  if (!confirm("确认删除该账户记录？（不会删除已写入的环境变量）")) return;
  const j = await apiPost("/jdcookie/account/delete", { ref }).catch(() => ({ code: 1, msg: "删除失败" }));
  toast(j.code === 0 ? "已删除" : (j.msg || "删除失败"), j.code === 0);
  if (j.code === 0) loadJdAccounts();
}

/* ---------- 系统监控 ---------- */
let cpuHist = [];
async function renderMonitor() {
  if (metricsTimer) { clearInterval(metricsTimer); metricsTimer = null; }
  $("#main").innerHTML = `<div class="page-head"><div><h2>系统监控</h2><div class="sub">实时 CPU / 内存 / 磁盘 / 网络（每 2 秒刷新）</div></div>
    <div class="toolbar"><button class="ghost" onclick="renderMonitor()">刷新</button></div></div>
    <div class="grid" style="grid-template-columns:1fr 1fr; gap:16px;">
      <div class="card"><div class="page-head"><h2 style="font-size:15px;">资源占用</h2></div>
        <div id="m-cpu" class="metric">CPU：<b>—</b></div>
        <div class="bar"><span id="m-cpu-bar"></span></div>
        <div id="m-mem" class="metric">内存：<b>—</b></div>
        <div class="bar"><span id="m-mem-bar"></span></div>
        <div id="m-disk" class="metric">磁盘：<b>—</b></div>
        <div class="bar"><span id="m-disk-bar"></span></div>
        <div id="m-net" class="metric">网络：<b>—</b></div>
      </div>
      <div class="card"><div class="page-head"><h2 style="font-size:15px;">CPU 使用率曲线</h2></div>
        <canvas id="m-canvas" width="420" height="200" style="width:100%;height:200px;"></canvas>
      </div>
    </div>`;
  cpuHist = [];
  await loadMetrics();
  metricsTimer = setInterval(loadMetrics, 2000);
}
async function loadMetrics() {
  const j = await apiGet("/system/metrics").catch(() => ({ code: 1 }));
  if (j.code !== 0) return;
  const d = j.data;
  if (d.cpu != null) {
    $("#m-cpu").innerHTML = "CPU：<b>" + d.cpu + "%</b>";
    $("#m-cpu-bar").style.width = d.cpu + "%";
    cpuHist.push(d.cpu); if (cpuHist.length > 60) cpuHist.shift();
    drawCpu();
  }
  if (d.mem) {
    $("#m-mem").innerHTML = "内存：<b>" + d.mem.used_mb + " / " + d.mem.total_mb + " MB（" + d.mem.percent + "%）</b>";
    $("#m-mem-bar").style.width = d.mem.percent + "%";
  }
  if (d.disk) {
    $("#m-disk").innerHTML = "磁盘：<b>" + d.disk.used_gb + " / " + d.disk.total_gb + " GB（" + d.disk.percent + "%）</b>";
    $("#m-disk-bar").style.width = d.disk.percent + "%";
  }
  if (d.net) {
    $("#m-net").innerHTML = "网络：↑ <b>" + d.net.sent_kb_s + " KB/s</b> · ↓ <b>" + d.net.recv_kb_s + " KB/s</b>";
  }
}
function drawCpu() {
  const c = document.getElementById("m-canvas"); if (!c) return;
  const ctx = c.getContext("2d");
  const W = c.width, H = c.height;
  ctx.clearRect(0, 0, W, H);
  ctx.strokeStyle = "rgba(128,128,128,0.2)";
  for (let i = 0; i <= 4; i++) { const y = H * i / 4; ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(W, y); ctx.stroke(); }
  const n = cpuHist.length; if (!n) return;
  ctx.strokeStyle = getComputedStyle(document.documentElement).getPropertyValue("--accent") || "#4f9cf9";
  ctx.lineWidth = 2; ctx.beginPath();
  cpuHist.forEach((v, i) => { const x = n > 1 ? W * i / (n - 1) : 0; const y = H - (v / 100) * H; if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y); });
  ctx.stroke();
}

/* ---------- 文件管理 ---------- */
let fileCurPath = "";
async function renderFiles() {
  if (filesTimer) { clearInterval(filesTimer); filesTimer = null; }
  $("#main").innerHTML = `<div class="page-head"><div><h2>文件管理</h2><div class="sub">浏览与编辑 data/ 目录下的文件（已限制在该目录内，防越权）</div></div>
    <div class="toolbar"><button class="ghost" onclick="renderFiles()">刷新</button>
    <button class="primary" onclick="newFile()">+ 新建文件</button>
    <button class="ghost" onclick="newFolder()">+ 新建文件夹</button></div></div>
    <div class="card"><div id="file-path" class="muted" style="margin-bottom:10px;word-break:break-all;"></div>
    <div id="file-list">加载中…</div></div>`;
  await loadFiles("");
}
async function loadFiles(path) {
  fileCurPath = path || "";
  const j = await apiGet("/files/tree?path=" + encodeURIComponent(fileCurPath)); if (j.code !== 0) return;
  $("#file-path").textContent = "data/" + (j.data.path || "");
  const es = j.data.entries || [];
  if (!es.length) { $("#file-list").innerHTML = `<div class="empty">空目录</div>`; return; }
  $("#file-list").innerHTML = `<table><thead><tr><th>名称</th><th>类型</th><th>大小</th><th>修改时间</th><th>操作</th></tr></thead><tbody>
    ${es.map(e => `<tr><td>${e.is_dir ? "📁" : "📄"} <b>${esc(e.name)}</b></td>
      <td>${e.is_dir ? "目录" : "文件"}</td>
      <td class="muted">${e.is_dir ? "-" : fmtSize(e.size)}</td>
      <td class="muted nowrap">${new Date(e.mtime * 1000).toLocaleString()}</td>
      <td class="nowrap">${e.is_dir ? `<button class="sm" onclick="openFolder('${encodeURIComponent(e.path)}')">打开</button>` : `<button class="sm" onclick="editFile('${encodeURIComponent(e.path)}')">编辑</button>`}
        ${canAdmin() ? `<button class="sm danger" onclick="delFile('${encodeURIComponent(e.path)}')">删</button>` : ""}</td></tr>`).join("")}
  </tbody></table>`;
}
function openFolder(p) { loadFiles(decodeURIComponent(p)); }
async function editFile(p) {
  const path = decodeURIComponent(p);
  const j = await apiGet("/files/content?path=" + encodeURIComponent(path));
  if (j.code !== 0) return toast(j.msg, false);
  const html = `<label>${esc(path)}</label><textarea id="fe_content" style="min-height:360px;font-family:monospace;">${esc(j.data.content || "")}</textarea>`;
  openModal("编辑 · " + path, html, `<button class="ghost" onclick="closeModal()">取消</button><button class="primary" onclick="saveFile('${encodeURIComponent(path)}')">保存</button>`, true);
}
async function saveFile(p) {
  const path = decodeURIComponent(p);
  const j = await apiPost("/files/write", { path, content: $("#fe_content").value }).catch(() => ({ code: 1, msg: "保存失败" }));
  if (j.code === 0) { toast("已保存"); closeModal(); loadFiles(fileCurPath); } else toast(j.msg, false);
}
function newFile() {
  const name = prompt("文件名（可含子目录，如 sub/a.py）："); if (!name) return;
  const path = (fileCurPath ? fileCurPath + "/" : "") + name.trim();
  openModal("新建文件 · " + path, `<label>${esc(path)}</label><textarea id="fe_content" style="min-height:320px;font-family:monospace;"></textarea>`,
    `<button class="ghost" onclick="closeModal()">取消</button><button class="primary" onclick="saveFile('${encodeURIComponent(path)}')">保存</button>`, true);
}
function newFolder() {
  const name = prompt("文件夹名："); if (!name) return;
  const path = (fileCurPath ? fileCurPath + "/" : "") + name.trim();
  apiPost("/files/mkdir", { path }).then(j => { if (j.code === 0) { toast("已创建"); loadFiles(fileCurPath); } else toast(j.msg, false); });
}
async function delFile(p) {
  const path = decodeURIComponent(p); if (!confirm("确认删除 " + path + "？")) return;
  const j = await apiPost("/files/delete", { path }).catch(() => ({ code: 1, msg: "删除失败" }));
  if (j.code === 0) { toast("已删除"); loadFiles(fileCurPath); } else toast(j.msg, false);
}

/* ---------- 用户管理（管理员） ---------- */
async function renderUsers() {
  if (!canAdmin()) { toast("需要管理员权限", false); navigate("dashboard"); return; }
  $("#main").innerHTML = `<div class="page-head"><div><h2>用户管理</h2><div class="sub">多用户与角色权限（管理员 / 操作员 / 只读）</div></div>
    <div class="toolbar"><button class="ghost" onclick="renderUsers()">刷新</button>
    <button class="primary" onclick="userForm()">+ 新建用户</button></div></div>
    <div id="user-list">加载中…</div>`;
  const j = await apiGet("/users"); if (j.code !== 0) return;
  const rows = j.data;
  $("#user-list").innerHTML = rows.length ? `<div class="card" style="padding:0;"><table><thead><tr>
    <th>用户名</th><th>角色</th><th>状态</th><th>创建时间</th><th>操作</th></tr></thead><tbody>
    ${rows.map(u => `<tr><td><b>${esc(u.username)}</b></td>
      <td>${badge(roleText(u.role), u.role === "admin" ? "b-red" : u.role === "op" ? "b-blue" : "b-gray")}</td>
      <td>${u.status == 1 ? badge("启用", "b-green") : badge("停用", "b-gray")}</td>
      <td class="muted nowrap">${esc(u.created_at || "")}</td>
      <td class="nowrap"><button class="sm" onclick="userForm(${u.id})">编辑</button>
      <button class="sm danger" onclick="delUser(${u.id})">删</button></td></tr>`).join("")}
  </tbody></table></div>` : `<div class="card empty">暂无用户</div>`;
}
function userForm(id) {
  const isEdit = !!id;
  const html = `<label>用户名</label><input id="u_name" ${isEdit ? "disabled" : ""}>
    <label>密码（${isEdit ? "留空则不修改" : "至少 6 位"}）</label><input id="u_pw" type="password">
    <div class="row2"><div><label>角色</label><select id="u_role"><option value="viewer">只读</option><option value="op">操作员</option><option value="admin">管理员</option></select></div>
    <div><label>状态</label><select id="u_status"><option value="1">启用</option><option value="0">停用</option></select></div></div>`;
  openModal(isEdit ? "编辑用户" : "新建用户", html,
    `<button class="ghost" onclick="closeModal()">取消</button><button class="primary" onclick="saveUser(${id || 0})">保存</button>`);
  if (isEdit) apiGet("/users").then(j => { const u = j.data.find(x => x.id == id); if (!u) return;
    $("#u_name").value = u.username; $("#u_role").value = u.role; $("#u_status").value = u.status; });
}
async function saveUser(id) {
  const body = { username: $("#u_name").value.trim(), password: $("#u_pw").value, role: $("#u_role").value, status: parseInt($("#u_status").value) };
  const j = id ? await apiPut("/users/" + id, body) : await apiPost("/users", body);
  if (j.code === 0) { toast("已保存"); closeModal(); renderUsers(); } else toast(j.msg, false);
}
async function delUser(id) {
  if (!confirm("确认删除该用户？")) return;
  const j = await apiDel("/users/" + id);
  if (j.code === 0) { toast("已删除"); renderUsers(); } else toast(j.msg, false);
}

/* ---------- 启动 ---------- */
async function bootApp() {
  try {
    const me = await apiGet("/me");
    if (me.code !== 0) throw new Error("auth");
    ROLE = me.data.role || "admin";
    localStorage.setItem("qd_role", ROLE);
    $("#uname").textContent = me.data.username + "（" + roleText(me.data.role) + "）";
    hideLogin(); renderNav(); navigate("dashboard");
    // 预加载最近日志用于 AI 分析下拉
    apiGet("/logs?limit=30").then(j => {
      if (j.code === 0 && $("#an-log")) {
        $("#an-log").innerHTML = j.data.map(l => `<option value="${l.id}">#${l.id} ${esc(l.task_name || l.kind)} ${esc(l.status || "")}</option>`).join("");
      }
    });
  } catch (e) { showLogin(); }
}
applyTheme();
if (TOKEN) bootApp(); else showLogin();
