"""巡检 Agent 调模型的唯一入口：全 app/agent、app/tools 只有本文件导入 app.ask.llm。

每次调用前后在 logs/agent_llm.jsonl 追加 phase=start / end 一行（不记提示词、回答正文与密钥）。
temperature=0、单次 30s 超时、不设 max_tokens。
"""
from __future__ import annotations

import json
import threading
import time
from datetime import datetime

from app.ask import llm as _llm
from app.config import ROOT

LLM_LOG = ROOT / "logs" / "agent_llm.jsonl"
TIMEOUT_S = 30.0
_LOCK = threading.Lock()

LLMUnavailable = _llm.LLMUnavailable
json_object = _llm.json_object


def _log(row: dict) -> None:
    LLM_LOG.parent.mkdir(parents=True, exist_ok=True)
    with _LOCK, LLM_LOG.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def call_model(run_id: str, call_seq: int, purpose: str, messages: list[dict]) -> str:
    """一次模型调用。失败抛 LLMUnavailable（或解析前的其他异常原样抛出）。"""
    _log({"ts": datetime.now().astimezone().isoformat(timespec="milliseconds"), "run_id": run_id,
          "call_seq": call_seq, "purpose": purpose, "phase": "start"})
    t0 = time.perf_counter()
    ok, error = False, None
    try:
        text = _llm.chat(messages, temperature=0, timeout=TIMEOUT_S)
        if not text.strip():
            raise LLMUnavailable("模型返回内容为空")
        ok = True
        return text
    except LLMUnavailable as exc:
        error = "E_LLM_TIMEOUT" if getattr(exc, "timed_out", False) else "E_LLM_UNAVAILABLE"
        raise
    except Exception as exc:  # noqa: BLE001 - 记录后原样抛出
        error = f"E_LLM_{exc.__class__.__name__}"
        raise
    finally:
        row = {"ts": datetime.now().astimezone().isoformat(timespec="milliseconds"), "run_id": run_id,
               "call_seq": call_seq, "purpose": purpose, "phase": "end", "ok": ok,
               "elapsed_ms": int((time.perf_counter() - t0) * 1000)}
        if error:
            row["error"] = error
        _log(row)
