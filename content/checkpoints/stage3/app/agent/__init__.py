"""巡检 Agent（两规则版）。

集成契约：导出 `router`（/api/agent/*、/api/ops/*）、`dispatch_tool`、`TOOL_NAMES`；
由 app/main.py 以 try/except ImportError 挂上。
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from app import ops_store

from . import runner
from .tools import TOOL_NAMES, dispatch_tool

__all__ = ["router", "dispatch_tool", "TOOL_NAMES"]

router = APIRouter()


class RunRequest(BaseModel):
    use_llm: bool = True


class CommitRequest(BaseModel):
    preview_ids: list[str] = []


class DecisionRequest(BaseModel):
    kind: str
    id: int | str
    decision: str


# ---------------------------------------------------------------- 巡检
@router.post("/api/agent/run")
def api_agent_run(body: RunRequest | None = None):
    run_id = runner.start(True if body is None else body.use_llm)
    return {"run_id": run_id}


@router.get("/api/agent/run/{run_id}")
def api_agent_run_get(run_id: str):
    snap = runner.snapshot(run_id)
    if snap is None:
        raise HTTPException(status_code=404, detail="run_id 不存在")
    return snap


# ---------------------------------------------------------------- 待审批
@router.post("/api/ops/preview")
async def api_ops_preview(request: Request):
    try:
        payload = await request.json()
    except ValueError:
        payload = None
    if not isinstance(payload, dict):
        res = {"ok": False, "reject_reason": "E_PARAM 请求体须为 JSON 对象", "rules": []}
        await run_in_threadpool(ops_store.audit, "api_preview", {"body": None}, res)
        return res
    res = await run_in_threadpool(ops_store.preview, payload)
    audit_res = {"ok": res["ok"]}
    if res["ok"]:
        audit_res["preview_id"] = res["preview_id"]
    else:
        audit_res["reason"] = res.get("reject_reason")
    await run_in_threadpool(ops_store.audit, "api_preview", {k: v for k, v in payload.items() if k != "evidence"}
                            | {"run_id": payload.get("run_id")}, audit_res)
    out = {"ok": res["ok"]}
    for k in ("preview_id", "reject_reason", "rules", "row"):
        if k in res:
            out[k] = res[k]
    return out


@router.post("/api/ops/commit")
def api_ops_commit(body: CommitRequest):
    res = ops_store.commit([str(x) for x in body.preview_ids])
    ops_store.audit("api_commit", {"preview_ids": body.preview_ids},
                    {"ok": True, "committed": res["committed"], "rejected": res["rejected"]})
    return res


@router.get("/api/ops/items")
def api_ops_items():
    return ops_store.items()


@router.post("/api/ops/decision")
def api_ops_decision(body: DecisionRequest):
    params = {"kind": body.kind, "id": body.id, "decision": body.decision}
    try:
        res = ops_store.decision(body.kind, body.id, body.decision)
    except ops_store.DecisionError as exc:
        ops_store.audit("api_decision", params, {"ok": False, "reason": str(exc)})
        return JSONResponse(status_code=exc.status, content={"ok": False, "detail": str(exc)})
    ops_store.audit("api_decision", params, res)
    return res


@router.get("/api/ops/audit")
def api_ops_audit(run_id: str | None = None):
    return {"rows": ops_store.audit_rows(run_id)}
