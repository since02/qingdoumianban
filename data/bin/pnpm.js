#!/usr/bin/env node
/**
 * 青豆面板 · pnpm 绿色垫片（portable shim）
 * ---------------------------------------------------------------
 * 背景：很多青龙脚本（如 jd_scripts 系列的 jd_indeps.js）用 pnpm 命令装全局依赖，
 *       但本面板是「绿色可移动」定位——目标机器可能只装了 node/npm，没有 pnpm。
 *       结果就是 `pnpm add -g xxx` 全部报「command not found」→ 依赖安装全失败。
 *
 * 方案：本垫片把 pnpm 常用子命令翻译成 npm 等价命令，并把全局包装进
 *       项目内 data/npm-global 目录（随文件夹一起搬走，不污染系统环境）。
 *
 * 命令映射：
 *   pnpm config set registry X     -> 记录到 data/npm-global/.npmrc（安装时强制生效）
 *   pnpm install -g                -> no-op 成功（npm 无参 -g 会报错，脚本会因此中断）
 *   pnpm add -g pkg[@ver]          -> npm install -g pkg[@ver]
 *   pnpm remove -g pkg             -> npm uninstall -g pkg
 *   pnpm ls -g [pkg] --depth 0     -> npm ls -g [pkg] --depth 0 --json
 *   其它                            -> 尽量透传给同名 npm 子命令，未知命令按成功返回（不阻断脚本）
 */
'use strict';
const path = require('path');
const fs = require('fs');
const cp = require('child_process');

const BASE_DIR = path.resolve(__dirname, '..', '..');               // data/bin -> 项目根
const GLOBAL_DIR = path.join(BASE_DIR, 'data', 'npm-global');        // 绿色全局目录
const REGISTRY = process.env.QD_NPM_REGISTRY || 'https://registry.npmmirror.com';

try { fs.mkdirSync(GLOBAL_DIR, { recursive: true }); } catch (e) { }

function findNpm() {
  const dir = path.dirname(process.execPath);
  const cands = process.platform === 'win32'
    ? [path.join(dir, 'npm.cmd'), path.join(dir, 'npm.exe')]
    : [path.join(dir, 'npm'),
       path.join(dir, '..', 'lib', 'node_modules', 'npm', 'bin', 'npm-cli.js')];
  for (const c of cands) { try { if (fs.existsSync(c)) return c; } catch (e) { } }
  return process.platform === 'win32' ? 'npm.cmd' : 'npm';
}

/** 执行 npm；prefix/registry 一律用环境变量下发，避免命令行出现中文路径 */
function runNpm(args, capture) {
  const npm = findNpm();
  const env = Object.assign({}, process.env, {
    npm_config_prefix: GLOBAL_DIR,
    npm_config_registry: REGISTRY,
    npm_config_global: 'true',
    npm_config_yes: 'true',
    npm_config_fund: 'false',
    npm_config_audit: 'false',
    npm_config_update_notifier: 'false',
    // 让被安装包的 postinstall 也能找到 node
    PATH: path.dirname(process.execPath) + path.delimiter + (process.env.PATH || ''),
  });
  const useNodeCli = npm.endsWith('npm-cli.js');
  const file = useNodeCli ? process.execPath : npm;
  const argv = useNodeCli ? [npm].concat(args) : args;
  const stdio = capture ? ['ignore', 'pipe', 'pipe'] : 'inherit';
  let r = cp.spawnSync(file, argv, { stdio: stdio, env: env, shell: false, encoding: 'utf8' });
  if (r.error) {
    // 兜底：交给 shell 执行（Windows 上的 .cmd）
    const q = (s) => (/[\s"]/.test(s) ? '"' + String(s).replace(/"/g, '\\"') + '"' : s);
    r = cp.spawnSync([q(npm)].concat(args.map(q)).join(' '),
      { stdio: stdio, env: env, shell: true, encoding: 'utf8' });
  }
  const status = typeof r.status === 'number' ? r.status : 1;
  if (!capture) return status;
  return { status: status, stdout: r.stdout || '', stderr: r.stderr || '' };
}

/** 把 npm ls --json 输出转成 pnpm ls --json 的数组格式，避免脚本误判「未安装」而反复重装 */
function toPnpmStyle(npmJsonText, want) {
  let obj = null;
  try { obj = JSON.parse(npmJsonText); } catch (e) { return '[]'; }
  const deps = (obj && obj.dependencies) || {};
  const out = [];
  Object.keys(deps).forEach(function (k) {
    const v = deps[k] || {};
    if (!v.version) return;
    if (want && want.length && want.indexOf(k) < 0) return;
    out.push({ name: k, version: v.version, path: v.resolved || '' });
  });
  return JSON.stringify(out);
}

function writeNpmrcRegistry(reg) {
  try {
    const f = path.join(GLOBAL_DIR, '.npmrc');
    let txt = '';
    try { txt = fs.readFileSync(f, 'utf8'); } catch (e) { }
    txt = txt.replace(/^\s*registry\s*=.*$/mg, '').trim();
    txt = (txt ? txt + '\n' : '') + 'registry=' + reg + '\n';
    fs.writeFileSync(f, txt, 'utf8');
  } catch (e) { }
}

const raw = process.argv.slice(2);
const sub = (raw[0] || '').toLowerCase();
const rest = raw.slice(1);
const isGlobal = raw.some((a) => a === '-g' || a === '--global');
const pkgs = rest.filter((a) => !a.startsWith('-'));

if (!sub) { console.log('pnpm shim (qingdou panel) - use: add -g <pkg> / ls -g [pkg]'); process.exit(0); }

// config set registry <url>
if (sub === 'config' && (rest[0] || '').toLowerCase() === 'set' && (rest[1] || '').toLowerCase() === 'registry') {
  writeNpmrcRegistry(rest[2] || REGISTRY);
  process.exit(0);
}
if (sub === 'config') { process.exit(0); }            // 其它 config 子命令：静默成功

// install / add
if (sub === 'add' || sub === 'i' || sub === 'install') {
  if (!pkgs.length) {
    // `pnpm install -g`（无包名）：npm 会报错并中断调用方脚本 → 直接成功返回
    process.exit(0);
  }
  process.exit(runNpm(['install', '-g'].concat(pkgs)));
}

// remove
if (sub === 'remove' || sub === 'rm' || sub === 'uninstall' || sub === 'un') {
  if (!pkgs.length) process.exit(0);
  process.exit(runNpm(['uninstall', '-g'].concat(pkgs)));
}

// update
if (sub === 'update' || sub === 'up' || sub === 'upgrade') {
  process.exit(runNpm(['update', '-g'].concat(pkgs)));
}

// list / ls
if (sub === 'ls' || sub === 'list') {
  const depthIdx = rest.findIndex((a) => a === '--depth');
  const depth = depthIdx >= 0 ? rest[depthIdx + 1] : '0';
  const json = rest.indexOf('--json') >= 0;
  const cand = pkgs.filter((p) => p !== '0');
  const argv = ['ls', '-g'].concat(cand).concat(['--depth', depth]).concat(json ? ['--json'] : []);
  if (!json) { runNpm(argv); process.exit(0); }
  const res = runNpm(argv, true);
  // 输出 pnpm 风格数组：[{"name":"got","version":"11.8.6"}]；查不到则为 []
  console.log(toPnpmStyle(res.stdout, cand));
  process.exit(0);
}

// env / store / root / bin 等查询类
if (sub === 'root') { console.log(process.platform === 'win32'
  ? path.join(GLOBAL_DIR, 'node_modules') : path.join(GLOBAL_DIR, 'lib', 'node_modules')); process.exit(0); }
if (sub === 'store' || sub === 'store-path') { console.log(path.join(GLOBAL_DIR, '.pnpm-store')); process.exit(0); }
if (sub === 'bin' || sub === 'bin-dir') { console.log(GLOBAL_DIR); process.exit(0); }

// 其它：尝试同名 npm 子命令，失败也不阻断
if (isGlobal) {
  const rc = runNpm([sub].concat(rest.filter((a) => a !== '-g' && a !== '--global')));
  process.exit(rc);
}
process.exit(0);
