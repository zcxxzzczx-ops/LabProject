"""
Frontend server — FastAPI + Jinja2.
Tutte le route chiamano il backend via HTTP e rendono template HTML.
"""
import os
from pathlib import Path
import httpx
from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

BACKEND_URL = os.getenv("BACKEND_URL", "http://backend:8003")
app = FastAPI(title="Frontend")
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


async def _get(path: str, params: dict | None = None) -> dict:
    async with httpx.AsyncClient(timeout=120.0) as c:
        r = await c.get(f"{BACKEND_URL}{path}", params=params)
        if r.status_code == 200:
            return r.json()
        try:
            detail = r.json().get("detail", r.text)
        except Exception:
            detail = r.text
        return {"error": detail}


async def _post(path: str, body: dict) -> dict:
    async with httpx.AsyncClient(timeout=120.0) as c:
        r = await c.post(f"{BACKEND_URL}{path}", json=body)
        if r.status_code == 200:
            return r.json()
        try:
            detail = r.json().get("detail", r.text)
        except Exception:
            detail = r.text
        return {"error": detail}


async def _delete(path: str, body: dict) -> dict:
    async with httpx.AsyncClient(timeout=120.0) as c:
        r = await c.delete(f"{BACKEND_URL}{path}", json=body)
        if r.status_code == 200:
            return r.json()
        try:
            detail = r.json().get("detail", r.text)
        except Exception:
            detail = r.text
        return {"error": detail}


# ---------------------------------------------------------------------------
# HOME
# ---------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
async def home(request: Request) -> HTMLResponse:
    status = await _get("/status")
    domains_data = await _get("/domains")
    domains = domains_data.get("domains", []) if "error" not in domains_data else []
    return templates.TemplateResponse("index.html", {
        "request": request,
        "active_page": "home",
        "status": status,
        "domains": domains,
    })


# ---------------------------------------------------------------------------
# PARSER & EVALUATION
# ---------------------------------------------------------------------------

@app.get("/parser", response_class=HTMLResponse)
async def parser_page(request: Request) -> HTMLResponse:
    domains_data = await _get("/domains")
    domains = domains_data.get("domains", []) if "error" not in domains_data else []
    gs_urls: dict[str, list[str]] = {}
    for d in domains:
        r = await _get("/gold_standard_urls", {"domain": d})
        gs_urls[d] = r.get("gold_standard_urls", []) if "error" not in r else []
    return templates.TemplateResponse("parser.html", {
        "request": request,
        "active_page": "parser",
        "domains": domains,
        "gs_urls": gs_urls,
    })


@app.post("/parser", response_class=HTMLResponse)
async def parser_run(
    request: Request,
    url: str = Form(...),
    mode: str = Form("live"),
) -> HTMLResponse:
    domains_data = await _get("/domains")
    domains = domains_data.get("domains", []) if "error" not in domains_data else []
    gs_urls: dict[str, list[str]] = {}
    for d in domains:
        r = await _get("/gold_standard_urls", {"domain": d})
        gs_urls[d] = r.get("gold_standard_urls", []) if "error" not in r else []

    local = (mode == "local")
    parse_result = await _post("/parse", {"url": url, "local": local})

    gs_result = None
    eval_result = None
    judge_result = None
    if "error" not in parse_result:
        gs_resp = await _get("/gold_standard", {"url": url})
        if "error" not in gs_resp:
            gs_result = gs_resp
            eval_result = await _post("/evaluate", {
                "parsed_text": parse_result.get("parsed_text", ""),
                "gold_text": gs_result.get("gold_text", ""),
            })
            judge_result = await _post("/evaluate_judge", {
                "parsed_text": parse_result.get("parsed_text", ""),
                "gold_text": gs_result.get("gold_text", ""),
            })

    return templates.TemplateResponse("parser.html", {
        "request": request,
        "active_page": "parser",
        "domains": domains,
        "gs_urls": gs_urls,
        "submitted_url": url,
        "mode": mode,
        "parse_result": parse_result,
        "gs_result": gs_result,
        "eval_result": eval_result,
        "judge_result": judge_result,
    })


# ---------------------------------------------------------------------------
# GOLD STANDARD BUILDER
# ---------------------------------------------------------------------------

@app.get("/gold-standard", response_class=HTMLResponse)
async def gs_page(request: Request) -> HTMLResponse:
    domains_data = await _get("/domains")
    domains = domains_data.get("domains", []) if "error" not in domains_data else []
    return templates.TemplateResponse("gold_standard.html", {
        "request": request,
        "active_page": "gs",
        "domains": domains,
    })


@app.post("/gold-standard/fetch-html", response_class=HTMLResponse)
async def gs_fetch_html(
    request: Request,
    domain: str = Form(...),
    url: str = Form(...),
) -> HTMLResponse:
    domains_data = await _get("/domains")
    domains = domains_data.get("domains", []) if "error" not in domains_data else []

    parse_result = await _post("/parse", {"url": url, "local": False})
    gs_urls_resp = await _get("/gold_standard_urls", {"domain": domain})
    existing_urls = gs_urls_resp.get("gold_standard_urls", []) if "error" not in gs_urls_resp else []

    return templates.TemplateResponse("gold_standard.html", {
        "request": request,
        "active_page": "gs",
        "domains": domains,
        "selected_domain": domain,
        "submitted_url": url,
        "parse_result": parse_result,
        "existing_urls": existing_urls,
    })


@app.post("/gold-standard/save", response_class=HTMLResponse)
async def gs_save(
    request: Request,
    domain: str = Form(...),
    url: str = Form(...),
    html_text: str = Form(...),
    gold_text: str = Form(...),
) -> HTMLResponse:
    domains_data = await _get("/domains")
    domains = domains_data.get("domains", []) if "error" not in domains_data else []

    save_wr = await _post("/add_web_resource", {"url": url, "html_text": html_text})
    save_gs = None
    if "error" not in save_wr:
        save_gs = await _post("/add_gold_standard", {"url": url, "gold_text": gold_text})

    gs_urls_resp = await _get("/gold_standard_urls", {"domain": domain})
    existing_urls = gs_urls_resp.get("gold_standard_urls", []) if "error" not in gs_urls_resp else []

    msg_ok = save_gs and "error" not in save_gs
    return templates.TemplateResponse("gold_standard.html", {
        "request": request,
        "active_page": "gs",
        "domains": domains,
        "selected_domain": domain,
        "existing_urls": existing_urls,
        "save_ok": msg_ok,
        "save_error": save_gs.get("error") if save_gs and "error" in save_gs else (
            save_wr.get("error") if "error" in save_wr else None
        ),
    })


@app.post("/gold-standard/delete", response_class=HTMLResponse)
async def gs_delete(
    request: Request,
    domain: str = Form(...),
    url: str = Form(...),
) -> HTMLResponse:
    domains_data = await _get("/domains")
    domains = domains_data.get("domains", []) if "error" not in domains_data else []

    await _delete("/gold_standard", {"url": url})

    gs_urls_resp = await _get("/gold_standard_urls", {"domain": domain})
    existing_urls = gs_urls_resp.get("gold_standard_urls", []) if "error" not in gs_urls_resp else []

    return templates.TemplateResponse("gold_standard.html", {
        "request": request,
        "active_page": "gs",
        "domains": domains,
        "selected_domain": domain,
        "existing_urls": existing_urls,
        "save_ok": False,
    })


# ---------------------------------------------------------------------------
# STATS
# ---------------------------------------------------------------------------

@app.get("/stats", response_class=HTMLResponse)
async def stats_page(request: Request) -> HTMLResponse:
    db_stats = await _get("/db_stats")
    domains_data = await _get("/domains")
    domains = domains_data.get("domains", []) if "error" not in domains_data else []
    return templates.TemplateResponse("stats.html", {
        "request": request,
        "active_page": "stats",
        "domains": domains,
        "db_stats": db_stats,
    })
