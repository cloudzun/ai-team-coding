"""城市经营看板 · FastAPI 入口。"""
from __future__ import annotations

import re
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request as UrlRequest
from urllib.request import urlopen

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.concurrency import run_in_threadpool

from . import queries
from .config import settings

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

# 问数面板由另一个施工者实现（app/ask）。未就绪时不允许拖垮整个看板。
try:  # pragma: no cover - 集成点
    from .ask import router as ask_router

    app.include_router(ask_router)
except ImportError as exc:  # 只在缺模块时降级；其他导入错误照常抛出
    print(f"[看板] 问数接口未启用：{exc.__class__.__name__}: {exc}")

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
RANGE_MSG = "须满足 2024-10-01 ≤ start ≤ end ≤ 2026-09-30"


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


def date_range(start: str, end: str) -> tuple[str, str]:
    """/api/compare 与 /api/districts 共用的区间参数规则。"""
    start = parse_day(start, "start")
    end = parse_day(end, "end")
    if not (queries.COMPARE_MIN <= start <= end <= queries.COMPARE_MAX):
        raise HTTPException(status_code=422, detail=RANGE_MSG)
    return start, end


# ---------------------------------------------------------------- 页面
@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    d = dash()
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "districts": d.districts,
            "notice": d.meta.get("notice", ""),
            "meta": d.meta,
            # Web 端 Key 可以下发到浏览器；安全密钥不下发，只走同源代理
            "amap_js_key": settings.amap_js_key,
        },
    )


# ---------------------------------------------------------------- 数据接口
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
    start, end = date_range(start, end)
    return dash().compare(start, end)


@app.get("/api/districts")
def api_districts(start: str = "2026-07-01", end: str = "2026-09-30"):
    start, end = date_range(start, end)
    return dash().district_view(start, end)


@app.get("/api/structure")
def api_structure(district: str | None = None):
    return dash().structure[scope(district)]


@app.get("/api/distribution")
def api_distribution(district: str | None = None):
    return dash().distribution[scope(district)]


@app.get("/api/geo")
def api_geo(district: str | None = None):
    return dash().geo[scope(district)]


# ---------------------------------------------------------------- 高德安全密钥代理
# 规格 1.1：页面设 window._AMapSecurityConfig.serviceHost = "/_AMapService"，
# 由本服务按高德官方“安全密钥代理”规则转发，并在服务端追加 jscode。
AMAP_ROUTES = (
    ("/v4/map/styles", "https://webapi.amap.com"),
    ("/v3/vectormap", "https://fmap01.amap.com"),
)
AMAP_DEFAULT_HOST = "https://restapi.amap.com"
PROXY_TIMEOUT_S = 10.0


def amap_upstream(sub_path: str) -> str:
    """三条转发规则（规格 1.1）；其余一律回落到 restapi。"""
    path = "/" + sub_path.lstrip("/")
    for prefix, host in AMAP_ROUTES:
        if path == prefix or path.startswith(prefix + "/"):
            return host
    return AMAP_DEFAULT_HOST


def _forward(url: str, body: bytes | None, content_type: str | None) -> tuple[int, bytes, str]:
    req = UrlRequest(url, data=body, method="POST" if body is not None else "GET")
    if content_type:
        req.add_header("Content-Type", content_type)
    req.add_header("User-Agent", "homestay-dashboard/2")
    try:
        with urlopen(req, timeout=PROXY_TIMEOUT_S) as resp:  # noqa: S310 - 仅转发到高德域名
            return resp.status, resp.read(), resp.headers.get("Content-Type", "application/json")
    except HTTPError as err:  # 上游 4xx/5xx 原样回传，便于地图侧自行处理
        return err.code, err.read(), err.headers.get("Content-Type", "application/json")


@app.api_route("/_AMapService/{sub_path:path}", methods=["GET", "POST"])
async def amap_service(sub_path: str, request: Request):
    query = request.url.query
    code = settings.amap_js_security_code
    if code:
        # 安全密钥只在服务端拼接，绝不出现在任何前端响应或日志里
        query = (query + "&" if query else "") + urlencode({"jscode": code})
    url = amap_upstream(sub_path) + "/" + sub_path.lstrip("/")
    if query:
        url += "?" + query
    body = await request.body() if request.method == "POST" else None
    try:
        status, payload, content_type = await run_in_threadpool(
            _forward, url, body, request.headers.get("content-type")
        )
    except (URLError, TimeoutError, OSError):
        raise HTTPException(status_code=502, detail="高德服务不可达") from None
    headers = {"Cache-Control": "no-store"}
    return Response(content=payload, status_code=status, media_type=content_type, headers=headers)
