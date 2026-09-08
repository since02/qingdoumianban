"""青豆面板 - AI 对接（OpenAI 兼容接口：ChatGPT / DeepSeek / 通义 / 本地 Ollama 等）。"""
import json
import requests
from core import db


def list_ai():
    return db.query("SELECT * FROM ai_configs ORDER BY is_default DESC, id ASC")


def get_default_ai():
    return db.query_one("SELECT * FROM ai_configs WHERE status=1 ORDER BY is_default DESC, id ASC")


def chat(messages, ai=None, temperature=0.7, max_tokens=2000, timeout=120):
    """调用 Chat Completions 接口，返回 (content, error)。"""
    ai = ai or get_default_ai()
    if not ai or not ai["api_key"]:
        return None, "未配置可用的 AI（请在「AI 设置」中添加并启用）。"
    base = (ai["base_url"] or "https://api.openai.com/v1").rstrip("/")
    if not base.endswith("/v1"):
        base = base + "/v1"
    url = base + "/chat/completions"
    headers = {"Authorization": f"Bearer {ai['api_key']}", "Content-Type": "application/json"}
    payload = {
        "model": ai["model"] or "gpt-3.5-turbo",
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    try:
        r = requests.post(url, json=payload, headers=headers, timeout=timeout)
        if r.status_code != 200:
            return None, f"AI 接口返回 {r.status_code}: {r.text[:300]}"
        data = r.json()
        return data["choices"][0]["message"]["content"], None
    except Exception as e:
        return None, f"AI 调用失败: {e}"


def generate_script(prompt, lang="python"):
    """让 AI 生成一段可运行的脚本（python/js）。"""
    sys_msg = {
        "role": "system",
        "content": (
            "你是一个脚本生成助手。请只输出一段可直接运行的"
            f"{'Python' if lang=='python' else 'JavaScript'}代码，"
            "不要输出解释、不要使用 markdown 代码块包裹，只输出纯代码本身。"
            "代码应当健壮、带必要注释，并可通过 print 输出结果。"
        ),
    }
    user_msg = {"role": "user", "content": prompt}
    content, err = chat([sys_msg, user_msg], max_tokens=2500)
    if err:
        return None, err
    # 去掉可能的代码块包裹
    text = content.strip()
    if text.startswith("```"):
        text = text.split("```", 2)[1]
        if text.startswith("python") or text.startswith("js") or text.startswith("javascript"):
            text = text.split("\n", 1)[1] if "\n" in text else text
    return text.strip(), None


def analyze_log(log_text):
    """让 AI 分析任务日志，返回问题结论与建议。"""
    snippet = log_text[-4000:] if log_text else ""
    sys_msg = {"role": "system", "content": "你是一个运维分析助手，请基于日志用中文简洁指出问题原因与修复建议。"}
    user_msg = {"role": "user", "content": f"以下是一段任务运行日志：\n\n{snippet}"}
    return chat([sys_msg, user_msg], max_tokens=1200)


def summarize(text):
    sys_msg = {"role": "system", "content": "请用一句话中文总结以下内容要点。"}
    user_msg = {"role": "user", "content": text[:3000]}
    return chat([sys_msg, user_msg], max_tokens=400)
