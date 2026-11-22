"""OpenAI 兼容的最小客户端（只用标准库 urllib，不引新依赖）。

配置优先读 `app.config.settings`（llm_base_url / llm_model / llm_api_key）；
该模块不可用时退回读仓库根 `.env` 或环境变量 LLM_BASE_URL / LLM_MODEL / LLM_API_KEY。
前两个键都没有配置时不发请求、直接抛 LLMUnavailable（代码里不留任何默认地址或模型名）。
LLM_API_KEY 可选：有值就加请求头 `Authorization: Bearer <值>`，无值则不加（本地无鉴权
接口可留空）；密钥值不写进日志、报错与返回值。
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ENV_FILE = ROOT / ".env"
TIMEOUT_S = 30.0


class LLMUnavailable(Exception):
    """模型服务不可达 / 超时 / 返回不可解析。→ /api/ask 回 503 E_LLM。

    timed_out=True 表示"连上了但 30s 没回"，diagnose 可以据此退回确定性回答而不是 503。
    """

    def __init__(self, message: str, timed_out: bool = False) -> None:
        self.timed_out = timed_out
        super().__init__(message)


def _env_file() -> dict[str, str]:
    out: dict[str, str] = {}
    try:
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            out[key.strip()] = value.strip().strip('"').strip("'")
    except OSError:
        pass
    return out


def llm_settings() -> tuple[str, str]:
    """(base_url, model)。没有配置就报错并给提示；不留任何默认地址或模型名。"""
    base = model = None
    try:
        from app.config import settings  # type: ignore

        base = getattr(settings, "llm_base_url", None)
        model = getattr(settings, "llm_model", None)
    except Exception:
        pass
    if not base or not model:
        env = _env_file()
        base = base or os.environ.get("LLM_BASE_URL") or env.get("LLM_BASE_URL")
        model = model or os.environ.get("LLM_MODEL") or env.get("LLM_MODEL")
    if not base or not model:
        raise LLMUnavailable(
            "未配置模型接口：在本仓库根目录的 .env 或环境变量里设置 LLM_BASE_URL 与 LLM_MODEL"
            "（键名与说明见 .env.example）。不配置时问数接口返回 503，看板其余部分照常工作。"
        )
    return str(base).rstrip("/"), str(model)


def llm_api_key() -> str:
    """可选的 API 密钥；没配置时返回空字符串。

    读法与 LLM_BASE_URL / LLM_MODEL 一致：`app.config.settings` → 环境变量 → `.env`。
    调用方不得把返回值写进日志、报错或接口返回。
    """
    key = None
    try:
        from app.config import settings  # type: ignore

        key = getattr(settings, "llm_api_key", None)
    except Exception:
        pass
    if not key:
        env = _env_file()
        key = os.environ.get("LLM_API_KEY") or env.get("LLM_API_KEY")
    return str(key).strip() if key else ""


def _endpoint(base: str) -> str:
    if base.endswith("/chat/completions"):
        return base
    return base + "/chat/completions"


def chat(messages: list[dict], *, temperature: float = 0.0, timeout: float = TIMEOUT_S,
         max_tokens: int | None = None) -> str:
    """一次对话补全，返回首个 choice 的 content 文本。失败抛 LLMUnavailable。"""
    base, model = llm_settings()
    payload = {
        "model": model,
        "temperature": temperature,
        "messages": messages,
    }
    if max_tokens:
        payload["max_tokens"] = int(max_tokens)
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    api_key = llm_api_key()
    if api_key:
        # 只有配了 LLM_API_KEY 才带这个头；值只在请求头里出现一次，不进日志与报错。
        headers["Authorization"] = f"Bearer {api_key}"
    req = urllib.request.Request(
        _endpoint(base),
        data=data,
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        raise LLMUnavailable(f"模型服务返回 HTTP {exc.code}") from None
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        timed_out = isinstance(exc, TimeoutError) or "timed out" in str(exc).lower()
        raise LLMUnavailable(f"模型服务不可达：{exc}", timed_out=timed_out) from None
    try:
        body = json.loads(raw)
        content = body["choices"][0]["message"]["content"]
    except (ValueError, KeyError, IndexError, TypeError):
        raise LLMUnavailable("模型返回格式不可解析") from None
    if not isinstance(content, str):
        raise LLMUnavailable("模型返回内容为空")
    return content


def json_object(text: str) -> dict:
    """从模型输出里抠出第一个 JSON 对象（剥代码围栏、容忍前后废话）。"""
    if not text or not text.strip():
        raise ValueError("空输出")
    body = text.strip()
    if body.startswith("```"):
        body = body.split("\n", 1)[1] if "\n" in body else body
        if body.rstrip().endswith("```"):
            body = body.rstrip()[:-3]
    start = body.find("{")
    end = body.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("输出里没有 JSON 对象")
    candidate = body[start : end + 1]
    try:
        parsed = json.loads(candidate)
    except ValueError:
        # 常见毛病：中文引号、行尾逗号、尾随注释
        cleaned = candidate.replace("，", ",").replace("“", '"').replace("”", '"')
        cleaned = _drop_trailing_commas(cleaned)
        parsed = json.loads(cleaned)
    if not isinstance(parsed, dict):
        raise ValueError("输出不是 JSON 对象")
    return parsed


def _drop_trailing_commas(text: str) -> str:
    out = []
    in_string = False
    escape = False
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if in_string:
            out.append(ch)
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            i += 1
            continue
        if ch == '"':
            in_string = True
            out.append(ch)
            i += 1
            continue
        if ch == ",":
            j = i + 1
            while j < n and text[j] in " \t\r\n":
                j += 1
            if j < n and text[j] in "}]":
                i += 1
                continue
        out.append(ch)
        i += 1
    return "".join(out)


def strip_code_fences(sql: str) -> str:
    """模型常把 SQL 包在 ```sql 围栏里。"""
    text = (sql or "").strip()
    if not text.startswith("```"):
        return text
    lines = text.splitlines()
    lines = lines[1:]
    if lines and lines[-1].strip().startswith("```"):
        lines = lines[:-1]
    return "\n".join(lines).strip()
