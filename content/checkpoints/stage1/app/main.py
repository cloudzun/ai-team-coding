"""城市经营看板 · FastAPI 入口。"""
from __future__ import annotations

import re
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from . import queries

APP_DIR = Path(__file__).resolve().parent
STATE: dict[str, queries.Dashboard] = {}


@asynccontextmanager
async def lifespan(_app: FastAPI):
    STATE["dash"] = queries.Dashboard()
    yield
    STATE.clear()


app = FastAPI(title="城市经营看板", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=APP_DIR / "static"), name="static")
templates = Jinja2Templates(directory=APP_DIR / "templates")

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def dash() -> queries.Dashboard:
    return STATE["dash"]


def scope(district: str | None) -> str:
    if district is None or district == "":
        return ""
    if district not in dash().district_ids:
        raise HTTPException(status_code=422, detail="district 必须为空或 D01–D08")
    return district


def parse_day(value: str, field: str) -> str:
    if not DATE_RE.match(value or ""):
        raise HTTPException(status_code=422, detail=f"{field} 必须是 YYYY-MM-DD")
    try:
        date.fromisoformat(value)
    except ValueError:
        raise HTTPException(status_code=422, detail=f"{field} 不是合法日期") from None
    return value


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    d = dash()
    return templates.TemplateResponse(
        request,
        "index.html",
        {"districts": d.districts, "notice": d.meta.get("notice", ""), "meta": d.meta},
    )


@app.get("/api/meta")
def api_meta():
    m = dash().meta
    return {"notice": m.get("notice"), "generator_version": m.get("generator_version"), "seed": m.get("seed")}


@app.get("/api/kpi")
def api_kpi(district: str | None = None):
    return dash().kpi[scope(district)]


@app.get("/api/trend")
def api_trend(district: str | None = None):
    return dash().trend[scope(district)]


@app.get("/api/compare")
def api_compare(start: str = "2026-07-01", end: str = "2026-09-30"):
    start = parse_day(start, "start")
    end = parse_day(end, "end")
    if not (queries.COMPARE_MIN <= start <= end <= queries.COMPARE_MAX):
        raise HTTPException(status_code=422, detail="须满足 2024-10-01 ≤ start ≤ end ≤ 2026-09-30")
    return dash().compare(start, end)


@app.get("/api/structure")
def api_structure(district: str | None = None):
    return dash().structure[scope(district)]


@app.get("/api/distribution")
def api_distribution(district: str | None = None):
    return dash().distribution[scope(district)]


@app.get("/api/geo")
def api_geo(district: str | None = None):
    return dash().geo[scope(district)]
