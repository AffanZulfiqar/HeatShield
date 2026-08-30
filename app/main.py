"""Scorched — HTTP surface: REST API + MCP endpoint."""
import asyncio
import contextlib
import json
import logging
import re
from datetime import datetime, timedelta, timezone

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from app import agent, comparison, config, geo, ledger
from app.models import jsonable
from app.report import build_report
from app.rules import engine
from app.sites import all_sites, add_site, remove_site, get_site, require_site

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("scorched")

app = FastAPI(title=config.PRODUCT_NAME, description=config.PRODUCT_TAGLINE, version="0.1.0")
_task = None


@app.on_event("startup")
async def startup():
    global _task
    ledger.init()
    mode = config.resolved_mode()
    env_file = config.ROOT / ".env"
    # Hard diagnostic — printed before anything else so there's no ambiguity
    import sys
    print(f"[SCORCHED STARTUP] ROOT={config.ROOT}", flush=True)
    print(f"[SCORCHED STARTUP] .env exists={( config.ROOT / '.env').exists()}", flush=True)
    print(f"[SCORCHED STARTUP] FORTYGUARD_API_KEY={'SET ('+str(len(config._fg_key()))+ ' chars)' if config._fg_key() else 'NOT SET'}", flush=True)
    print(f"[SCORCHED STARTUP] DATA_MODE={config.DATA_MODE}  resolved={config.resolved_mode()}", flush=True)
    log.info("mode=%s  env=%s  key_set=%s  packs=%s",
             mode, env_file, bool(config._fg_key()), ", ".join(engine.available_packs()))
    if mode == "replay":
        if not env_file.exists():
            log.warning("DEMO MODE: .env not found at %s. Run: cp .env.example .env  then add your FORTYGUARD_API_KEY.", env_file)
        elif not config.FG_API_KEY and config.DATA_MODE == "live":
            log.warning(
                "DEMO MODE: DATA_MODE=live is set but FORTYGUARD_API_KEY is empty in %s. "
                "Add your key and restart to switch to live mode.", env_file
            )
        elif not config.FG_API_KEY:
            log.warning("DEMO MODE: FORTYGUARD_API_KEY is empty in %s — running synthetic data.", env_file)
        else:
            log.warning("DEMO MODE: DATA_MODE=replay is set explicitly in .env.")
    # Competition safety: never spend FortyGuard credits on startup.
    # A site is queried only after an explicit user action.
    if config.POLL_ENABLED:
        _task = asyncio.create_task(agent.loop())


@app.on_event("shutdown")
async def shutdown():
    if _task:
        _task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await _task


# ── meta ────────────────────────────────────────────────────────────────────

@app.get("/api/meta")
async def meta():
    return {
        "product": config.PRODUCT_NAME,
        "tagline": config.PRODUCT_TAGLINE,
        "mode": config.resolved_mode(),
        "replay": config.is_replay(),
        "lookahead_hours": config.LOOKAHEAD_HOURS,
        "poll_interval_s": config.POLL_INTERVAL_S,
        "rulepacks": [
            {
                "jurisdiction": p["jurisdiction"],
                "name": p["name"],
                "citation": p.get("citation"),
                "metric": p.get("metric"),
                "status": p.get("status"),
                "coverage": engine.coverage(p).to_dict(),
                "thresholds": [
                    {"id": t["id"], "name": t["name"], "value_f": t["value_f"], "severity": t["severity"]}
                    for t in p["thresholds"] if t["severity"] != "baseline"
                ],
            }
            for p in engine.all_packs()
        ],
        "ledger": ledger.verify(),
    }


@app.get("/api/debug-mode")
async def debug_mode():
    env_file = config.ROOT / ".env"
    if config.resolved_mode() == "live":
        return {"mode": "live", "reason": "live"}
    if not env_file.exists():
        return {"mode": "replay", "reason": "no_env_file", "expected": str(env_file)}
    if not config.FG_API_KEY:
        return {"mode": "replay", "reason": "no_key", "env_file": str(env_file)}
    if config.DATA_MODE == "replay":
        return {"mode": "replay", "reason": "forced"}
    return {"mode": "replay", "reason": "unknown"}


@app.post("/api/mode")
async def set_mode(body: dict):
    """Switch DATA_MODE at runtime by rewriting .env. Restarts the provider."""
    mode = body.get("mode", "").lower()
    if mode not in ("live", "replay", "auto"):
        raise HTTPException(400, "mode must be live | replay | auto")
    env_file = config.ROOT / ".env"
    if not env_file.exists():
        example = config.ROOT / ".env.example"
        if example.exists():
            import shutil
            shutil.copy(example, env_file)
    text = env_file.read_text(encoding="utf-8") if env_file.exists() else ""
    if re.search(r"^DATA_MODE\s*=", text, re.MULTILINE):
        text = re.sub(r"^DATA_MODE\s*=.*$", f"DATA_MODE={mode}", text, flags=re.MULTILINE)
    else:
        text = text.rstrip() + f"\nDATA_MODE={mode}\n"
    env_file.write_text(text, encoding="utf-8")
    # Reload env and reset provider
    try:
        from dotenv import load_dotenv
        load_dotenv(dotenv_path=env_file, override=True)
    except ImportError:
        pass
    import os
    os.environ["DATA_MODE"] = mode
    config.DATA_MODE = mode
    from app.providers import reset_provider
    reset_provider()
    return {"mode": mode, "effective": config.resolved_mode()}


# ── sites ────────────────────────────────────────────────────────────────────

@app.get("/api/resolve")
async def resolve_location(lat: float = Query(...), lng: float = Query(...)):
    """State, rulepack and timezone for a map pin. Offline; no quota cost."""
    return geo.resolve(lat, lng)


@app.get("/api/sites")
async def sites():
    return [s.to_dict() for s in all_sites()]


@app.post("/api/sites")
async def create_site(body: dict):
    required = ["name", "lat", "lng"]
    missing = [k for k in required if not body.get(k)]
    if missing:
        raise HTTPException(400, f"missing fields: {', '.join(missing)}")
    try:
        site = add_site(body)
    except Exception as exc:
        raise HTTPException(400, str(exc))
    # Do NOT query FortyGuard automatically. User must explicitly analyze the site.
    return site.to_dict()


@app.delete("/api/sites/{site_id}")
async def delete_site(site_id: str):
    if not remove_site(site_id):
        raise HTTPException(404, f"site '{site_id}' not found")
    return {"deleted": site_id}


# ── status ───────────────────────────────────────────────────────────────────

@app.get("/api/status")
async def status_all(force: bool = Query(False), cached_only: bool = Query(False)):
    """Statuses for every site.

    cached_only=true returns just what is already in memory and never calls
    FortyGuard. That is the safe default for a UI refresh once the registry is
    larger than the daily heatmap quota.
    """
    if cached_only:
        return agent.cached_statuses()
    return await agent.scan_all(force=force)


@app.post("/api/sites/{site_id}/analyze")
async def analyze_site(site_id: str):
    """Explicit, quota-consuming FortyGuard analysis for one worksite."""
    if get_site(site_id) is None:
        raise HTTPException(404, f"unknown site '{site_id}'")
    return await agent.status_of_site(site_id, max_age_s=config.POLL_INTERVAL_S, force=False)


@app.get("/api/sites/{site_id}/status")
async def site_status(site_id: str, force: bool = Query(False)):
    if get_site(site_id) is None:
        raise HTTPException(404, f"unknown site '{site_id}'")
    return await agent.status_of_site(site_id, force=force)


@app.post("/api/scan")
async def scan_now():
    return {"scanned": await agent.scan_all(force=True)}


# ── rules ────────────────────────────────────────────────────────────────────

@app.get("/api/rules")
async def list_rules():
    return [engine.load_pack(j) for j in engine.available_packs()]


@app.get("/api/rules/{jurisdiction}")
async def get_rules(jurisdiction: str):
    try:
        return engine.load_pack(jurisdiction)
    except FileNotFoundError:
        raise HTTPException(404, f"no rulepack for '{jurisdiction}'")


# ── ledger ───────────────────────────────────────────────────────────────────

@app.get("/api/ledger")
async def get_ledger(site_id: str = Query(None), limit: int = Query(100, le=1000)):
    return {"entries": ledger.entries(site_id=site_id, limit=limit), "head": ledger.head()}


@app.get("/api/ledger/verify")
async def verify_ledger():
    return ledger.verify()


# ── comparison / report ──────────────────────────────────────────────────────

@app.get("/api/comparison/{site_id}")
async def get_comparison(site_id: str, days: int = Query(7, ge=1, le=30)):
    site = require_site(site_id)
    return await comparison.compare(site, days=days)


@app.get("/api/report/{site_id}")
async def get_report(site_id: str, days: int = Query(7, ge=1, le=90)):
    require_site(site_id)
    buf = build_report(site_id, days=days)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d")
    return Response(
        content=buf.read(),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="heat-record-{site_id}-{stamp}.pdf"'},
    )


# ── heat plan ────────────────────────────────────────────────────────────────

def _heat_plan(st: dict, site) -> dict:
    current = float(st.get("current_f") or 0)
    forecast = st.get("forecast") or []
    crossings = st.get("crossings") or []
    sev = st.get("status", "no_duty")
    severity_score = {"no_duty": 0, "baseline": 15, "advisory": 30,
                      "action": 55, "high_heat": 80, "extreme": 100}.get(sev, 20)
    next_cross = crossings[0] if crossings else None
    peak = max([float(x.get("temp_f", current)) for x in forecast] or [current])
    hours_elevated = sum(1 for x in forecast if float(x.get("temp_f", 0)) >= 80)
    score = min(100, round(max(severity_score, min(100, severity_score + max(0, peak - current) * 1.5))))

    if sev in ("high_heat", "extreme"):
        priority, window = "STOP / PROTECT", "Now"
        actions = [
            "Move exposed crews to shade or a cooled recovery area immediately.",
            "Activate the highest applicable work/rest controls and supervisor check-ins.",
            "Defer non-essential high-exertion work to the coolest available window.",
            "Record the intervention and worker acknowledgement in the evidence trail.",
        ]
    elif sev == "action":
        priority, window = "STAGE CONTROLS", "Now"
        actions = [
            "Stage water, shade and recovery space before the next threshold crossing.",
            "Prepare work/rest rotation and supervisor observation for the active level.",
            "Reschedule the heaviest task to an earlier/cooler period where practical.",
        ]
    elif next_cross:
        priority, window = "PREPARE", f"{max(0, round(next_cross.get('lead_minutes', 0) / 60))}h lead"
        actions = [
            f"Stage controls before {next_cross.get('expected_at_utc', 'the forecast crossing')}.",
            "Notify the shift supervisor and confirm the recovery area is usable.",
            "Move high-exertion tasks away from the predicted peak where practical.",
        ]
    else:
        priority, window = "MONITOR", "No threshold crossing projected"
        actions = [
            "Maintain baseline heat controls and normal supervisor monitoring.",
            "Keep the recovery/shade setup available if conditions change.",
        ]

    return {
        "site_id": site.id,
        "priority": priority,
        "window": window,
        "risk_score": score,
        "current_f": round(current, 1),
        "forecast_peak_f": round(peak, 1),
        "elevated_hours_in_lookahead": hours_elevated,
        "next_crossing": next_cross,
        "actions": actions,
        "why": "Plan generated from FortyGuard temperature signal and the site rulepack.",
        "provenance": st.get("provenance"),
    }


@app.get("/api/heatplan/{site_id}")
async def heat_plan(site_id: str):
    site = require_site(site_id)
    st = await agent.status_of_site(site_id)
    return _heat_plan(st, site)


# ── MCP ──────────────────────────────────────────────────────────────────────

TOOLS = [
    {"name": "list_sites", "description": "List every monitored worksite.", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "check_compliance", "description": "Current worksite temperature vs jurisdiction heat standard.", "inputSchema": {"type": "object", "properties": {"site_id": {"type": "string"}}, "required": ["site_id"]}},
    {"name": "forecast_breach", "description": "Threshold crossings projected within the lookahead window.", "inputSchema": {"type": "object", "properties": {"site_id": {"type": "string"}, "hours": {"type": "integer"}}, "required": ["site_id"]}},
    {"name": "generate_heat_plan", "description": "Explainable operational heat plan from the FortyGuard signal.", "inputSchema": {"type": "object", "properties": {"site_id": {"type": "string"}}, "required": ["site_id"]}},
    {"name": "get_evidence", "description": "Signed ledger entries for a worksite.", "inputSchema": {"type": "object", "properties": {"site_id": {"type": "string"}, "days": {"type": "integer"}}, "required": ["site_id"]}},
    {"name": "verify_ledger", "description": "Recompute the hash chain and report integrity.", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "station_delta", "description": "Worksite temp vs nearest official station; blind hours.", "inputSchema": {"type": "object", "properties": {"site_id": {"type": "string"}, "days": {"type": "integer"}}, "required": ["site_id"]}},
    {"name": "explain_rulepack", "description": "Full rulepack text for a jurisdiction.", "inputSchema": {"type": "object", "properties": {"jurisdiction": {"type": "string"}}, "required": ["jurisdiction"]}},
]


async def call_tool(name: str, args: dict):
    if name == "list_sites":
        return [{**s.to_dict(), "standard": engine.load_pack(s.jurisdiction).get("citation")} for s in all_sites()]
    if name == "check_compliance":
        return await agent.status_of_site(args["site_id"])
    if name == "forecast_breach":
        site = require_site(args["site_id"])
        from app.providers import get_provider
        hours = int(args.get("hours", config.LOOKAHEAD_HOURS))
        forecast = await get_provider().forecast(site, hours)
        return {"site_id": site.id, "lookahead_hours": hours, "crossings": engine.project_crossings(forecast, site), "provenance": forecast[0].provenance}
    if name == "generate_heat_plan":
        site = require_site(args["site_id"])
        st = await agent.status_of_site(site.id)
        return _heat_plan(st, site)
    if name == "get_evidence":
        site = require_site(args["site_id"])
        days = int(args.get("days", 7))
        end = datetime.now(timezone.utc)
        start = end - timedelta(days=days)
        return {"site_id": site.id, "window_days": days, "entries": ledger.entries_between(site.id, start.isoformat(), end.isoformat()), "chain": ledger.verify()}
    if name == "verify_ledger":
        return ledger.verify()
    if name == "station_delta":
        site = require_site(args["site_id"])
        result = await comparison.compare(site, days=int(args.get("days", 7)))
        result.pop("rows", None)
        return result
    if name == "explain_rulepack":
        return engine.load_pack(args["jurisdiction"])
    raise KeyError(f"unknown tool '{name}'")


@app.get("/mcp/tools")
async def mcp_tools():
    return {"tools": TOOLS}


@app.post("/mcp/call")
async def mcp_call(payload: dict):
    try:
        result = await call_tool(payload.get("name", ""), payload.get("arguments", {}))
        return {"ok": True, "result": jsonable(result)}
    except Exception as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)


@app.post("/mcp")
async def mcp_jsonrpc(request: Request):
    body = await request.json()
    rpc_id = body.get("id")
    method = body.get("method")
    params = body.get("params") or {}

    def ok(result):
        return {"jsonrpc": "2.0", "id": rpc_id, "result": result}

    def err(code, message):
        return {"jsonrpc": "2.0", "id": rpc_id, "error": {"code": code, "message": message}}

    if method == "initialize":
        return ok({"protocolVersion": "2024-11-05", "capabilities": {"tools": {}}, "serverInfo": {"name": "scorched", "version": "0.1.0"}})
    if method == "ping":
        return ok({})
    if method == "tools/list":
        return ok({"tools": TOOLS})
    if method == "tools/call":
        try:
            result = await call_tool(params.get("name", ""), params.get("arguments") or {})
            return ok({"content": [{"type": "text", "text": json.dumps(jsonable(result), indent=2, default=str)}], "isError": False})
        except Exception as exc:
            return ok({"content": [{"type": "text", "text": f"error: {exc}"}], "isError": True})
    return err(-32601, f"method not found: {method}")


# ── static ───────────────────────────────────────────────────────────────────

@app.get("/")
async def index():
    return FileResponse(config.STATIC_DIR / "index.html")


app.mount("/static", StaticFiles(directory=str(config.STATIC_DIR)), name="static")
