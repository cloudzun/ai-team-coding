"""问数面板后端：`POST /api/ask`（规格 2.4 / 3 / 4.1）。

集成契约：`router = APIRouter()`，由 `app/main.py` 里 `include_router` 挂上。
配置只读 `app.config.settings`（llm_base_url / llm_model），该模块缺失时退回 `.env`。
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from . import llm, pipeline

router = APIRouter()

QUESTION_MIN = 1
QUESTION_MAX = 200


class AskRequest(BaseModel):
    question: str


@router.post("/api/ask")
def api_ask(body: AskRequest):
    question = (body.question or "").strip()
    if not (QUESTION_MIN <= len(question) <= QUESTION_MAX):
        raise HTTPException(
            status_code=422,
            detail=f"question 去掉首尾空白后须为 {QUESTION_MIN}–{QUESTION_MAX} 字",
        )
    try:
        return pipeline.ask(question)
    except llm.LLMUnavailable as exc:
        return JSONResponse(status_code=503, content={"error": "E_LLM", "message": str(exc)})
