"""配置读取：仓库根 `.env` → `settings`。

- `.env` 已在 `.gitignore`，任何密钥值都不许出现在代码、模板、日志里；
  本模块只做“从文件/环境变量取值”，不打印、不落盘。
- 键名见规格 1.1：LLM_BASE_URL / LLM_MODEL / LLM_API_KEY / AMAP_JS_KEY /
  AMAP_JS_SECURITY_CODE / AMAP_WEB_SERVICE_KEY（LLM_API_KEY 可选，本地无鉴权接口可留空）。
- 环境变量优先于 `.env`（方便临时覆盖，例如把 LLM 指向不存在的端口做降级验收）。
"""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = ROOT / ".env"

# 允许写成 export KEY=value，也允许引号；不支持多行值（本仓库用不到）。
_TRUE = {"1", "true", "yes", "on"}
_PAIRS = {"'": "'", '"': '"'}


def parse_env_file(path: Path) -> dict[str, str]:
    """把 .env 解析成字典；文件不存在或某行不合法就跳过，不抛异常。"""
    data: dict[str, str] = {}
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return data
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].strip()
        key, sep, value = line.partition("=")
        if not sep:
            continue
        key = key.strip()
        if not key:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] in _PAIRS and value[-1] == _PAIRS[value[0]]:
            value = value[1:-1]
        data[key] = value
    return data


class Settings:
    """只暴露配置项，不提供任何“打印全部配置”的方法。"""

    __slots__ = (
        "llm_base_url",
        "llm_model",
        "llm_api_key",
        "amap_js_key",
        "amap_js_security_code",
        "amap_web_service_key",
    )

    def __init__(self, env_path: Path = ENV_PATH) -> None:
        values = parse_env_file(env_path)

        def get(key: str) -> str:
            from_os = os.environ.get(key)
            if from_os is not None and from_os.strip():
                return from_os.strip()
            return values.get(key, "").strip()

        self.llm_base_url = get("LLM_BASE_URL")
        self.llm_model = get("LLM_MODEL")
        self.llm_api_key = get("LLM_API_KEY")
        self.amap_js_key = get("AMAP_JS_KEY")
        self.amap_js_security_code = get("AMAP_JS_SECURITY_CODE")
        self.amap_web_service_key = get("AMAP_WEB_SERVICE_KEY")

    # 只报“有没有”，不报值，可安全写进日志
    @property
    def has_amap_js(self) -> bool:
        return bool(self.amap_js_key)

    @property
    def has_amap_security_code(self) -> bool:
        return bool(self.amap_js_security_code)

    def __repr__(self) -> str:  # 防止默认 repr 被误用到日志里
        return (
            "Settings(llm_base_url=%r, llm_model=%r, llm_api_key=%s, amap_js_key=%s, "
            "amap_js_security_code=%s, amap_web_service_key=%s)"
            % (
                self.llm_base_url,
                self.llm_model,
                "<set>" if self.llm_api_key else "<empty>",
                "<set>" if self.amap_js_key else "<empty>",
                "<set>" if self.amap_js_security_code else "<empty>",
                "<set>" if self.amap_web_service_key else "<empty>",
            )
        )


settings = Settings()
