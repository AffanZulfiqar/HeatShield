"""The monitoring agent.

In live mode, FortyGuard only serves data ≥3 days old — no current temperature,
no forecast. The agent therefore works differently per mode:

  REPLAY: synthetic diurnal curve lets the full sense→predict→prove loop run,
          including future threshold crossings and pre-breach advisories.

  LIVE:   fetches historical hourly readings from 3 days ago, evaluates each
          against the rulepack, finds the peak/worst hour, and records the
          evidence chain. There are no "forecasted" crossings because the
          readings are already in the past — they are confirmed events.

The heartbeat comment from the original still applies: a gap in the ledger is
indistinguishable from a system outage. Heartbeats make "nothing happened" an
affirmative signed statement.
"""
import asyncio
import logging
from datetime import datetime, timedelta, timezone

from app import config, ledger, notify
from app.models import jsonable
from app.providers import get_provider
from app.rules import engine
from app.sites import all_sites, require_site

log = logging.getLogger("scorched.agent")

SEVERITY_LABEL = {
    "no_duty": "No temperature-triggered duty",
    "baseline": "Baseline duties only",
    "advisory": "Advisory risk level",
    "action": "Action level",
    "high_heat": "High-heat procedures",
    "extreme": "Extreme heat procedures",
}


def _provenance(readings) -> str:
    return readings[0].provenance if readings else "unknown"


async def scan_site(site_id: str) -> dict:
    site = require_site(site_id)
    provider = get_provider()
    pack = engine.load_pack(site.jurisdiction)
    cov = engine.coverage(pack)

    # In live mode: fetch historical readings from the available window (3 days ago).
    # In replay mode: forecast() returns a synthetic diurnal curve starting now.
    readings = await provider.forecast(site, config.LOOKAHEAD_HOURS)
    current = readings[0]

    is_live = config.resolved_mode() == "live"

    base_payload = {
        "site": {"id": site.id, "name": site.name, "lat": site.lat, "lng": site.lng},
        "jurisdiction": site.jurisdiction,
        "rulepack": {"citation": pack.get("citation"), "status": pack.get("status")},
        "data_source": current.source,
        "provenance": current.provenance,
        "mode": config.resolved_mode(),
        "data_note": (
            "Historical FortyGuard data (≥3 days old). FortyGuard does not serve current/forecast data."
            if is_live else "Synthetic replay data."
        ),
    }

    # Coverage gap: say so rather than pretending.
    if not cov.satisfiable:
        marker = f"coverage_gap:{datetime.now(timezone.utc):%Y-%m-%d}"
        if ledger.get_state(site.id, "last_coverage_gap") != marker:
            ledger.append(
                site.id,
                "COVERAGE_GAP",
                {
                    **base_payload,
                    "metric_required": cov.metric,
                    "missing_input": cov.missing,
                    "note": cov.note,
                    "observed_temp_f": round(current.temp_f, 1),
                },
                severity="advisory",
            )
            ledger.set_state(site.id, "last_coverage_gap", marker)
        gap = {
            "site_id": site.id,
            "status": "unevaluable",
            "status_label": "Not evaluable from temperature alone",
            "coverage": cov.to_dict(),
            "current_f": round(current.temp_f, 1),
            "observed_utc": current.ts_utc.isoformat(),
            "provenance": current.provenance,
            "source": current.source,
            "hits": [],
            "crossings": [],
            "forecast": [],
            "is_live": is_live,
            "fetched_utc": datetime.now(timezone.utc).isoformat(),
        }
        _cache[site.id] = gap
        _cache_at[site.id] = datetime.now(timezone.utc)
        return gap

    # Evaluate every reading; find the worst hour.
    all_hits = [(r, engine.evaluate(r, site, pack)) for r in readings]
    # Peak: reading with the highest severity / temperature.
    worst_reading, worst_hits = max(
        all_hits, key=lambda pair: (
            engine.SEVERITY_ORDER.index(engine.status_of(pair[1]))
            if engine.status_of(pair[1]) in engine.SEVERITY_ORDER else -1,
            pair[0].temp_f,
        )
    )

    # "Current" status = worst status across the window (honest for historical data).
    hits = worst_hits
    status = engine.status_of(hits)
    worst = engine.worst(hits)

    # In live mode, crossings are confirmed past events, not predictions.
    # In replay mode, project future crossings as usual.
    if is_live:
        crossings = _confirmed_crossings(all_hits, readings[0], site, pack)
    else:
        crossings = engine.project_crossings(readings, site, pack)

    events = []

    # Status transition.
    prev_status = ledger.get_state(site.id, "status")
    if prev_status != status:
        entry = ledger.append(
            site.id,
            "STATUS_CHANGE",
            {
                **base_payload,
                "from": prev_status or "unknown",
                "to": status,
                "temp_f": round(worst_reading.temp_f, 1),
                "observed_utc": worst_reading.ts_utc.isoformat(),
                "triggered": jsonable(hits),
                "requirements_now_in_force": worst.requirements if worst else [],
            },
            severity=status,
        )
        ledger.set_state(site.id, "status", status)
        events.append(entry)

        if worst and status in ("action", "high_heat", "extreme"):
            receipt = await notify.send(
                site,
                subject=f"{site.name}: {SEVERITY_LABEL.get(status, status)} recorded",
                body=(
                    f"{worst_reading.temp_f:.1f}F at the worksite "
                    f"(observed {worst_reading.ts_utc.strftime('%Y-%m-%d %H:%M UTC')}), "
                    f"threshold {worst.trigger_f:.0f}F ({worst.citation}). "
                    f"Required: " + "; ".join(worst.requirements[:3])
                ),
                severity=status,
            )
            events.append(
                ledger.append(
                    site.id,
                    "NOTICE_SENT",
                    {**base_payload, "about_seq": entry["seq"], "receipt": receipt},
                    severity=status,
                )
            )

    # Pre-breach / confirmed-crossing advisories (one per threshold per day).
    today = f"{datetime.now(timezone.utc):%Y-%m-%d}"
    for crossing in crossings:
        key = f"advised:{crossing['threshold_id']}"
        if ledger.get_state(site.id, key) == today:
            continue
        ledger.set_state(site.id, key, today)
        event_kind = "CONFIRMED_CROSSING" if is_live else "PRE_BREACH"
        entry = ledger.append(
            site.id,
            event_kind,
            {**base_payload, "current_f": round(current.temp_f, 1), "forecast": crossing},
            severity=crossing["severity"],
        )
        events.append(entry)

    # Heartbeat.
    last_hb = ledger.get_state(site.id, "last_heartbeat")
    due = True
    if last_hb:
        try:
            due = datetime.fromisoformat(last_hb) < datetime.now(timezone.utc) - timedelta(
                minutes=config.HEARTBEAT_MINUTES
            )
        except ValueError:
            due = True
    if due:
        ledger.append(
            site.id,
            "READING",
            {
                **base_payload,
                "temp_f": round(worst_reading.temp_f, 1),
                "observed_utc": worst_reading.ts_utc.isoformat(),
                "status": status,
                "triggered_ids": [h.threshold_id for h in hits],
            },
            severity=status,
        )
        ledger.set_state(site.id, "last_heartbeat", datetime.now(timezone.utc).isoformat())

    result = {
        "site_id": site.id,
        "status": status,
        "status_label": SEVERITY_LABEL.get(status, status),
        "coverage": cov.to_dict(),
        "current_f": round(worst_reading.temp_f, 1),
        "observed_utc": worst_reading.ts_utc.isoformat(),
        "provenance": worst_reading.provenance,
        "source": worst_reading.source,
        "hits": jsonable(hits),
        "worst": jsonable(worst) if worst else None,
        "crossings": crossings,
        "forecast": [
            {"ts_utc": r.ts_utc.isoformat(), "temp_f": round(r.temp_f, 1)} for r in readings
        ],
        "new_events": [{"seq": e["seq"], "kind": e["kind"]} for e in events],
        "is_live": is_live,
        "data_note": base_payload["data_note"],
        # When this app actually called the provider. Distinct from observed_utc,
        # which is when the temperature itself was measured. In live mode those
        # are ~3 days apart, so conflating them misleads.
        "fetched_utc": datetime.now(timezone.utc).isoformat(),
    }
    _cache[site.id] = result
    _cache_at[site.id] = datetime.now(timezone.utc)
    return result


def _confirmed_crossings(all_hits, first_reading, site, pack) -> list:
    """In live mode: return thresholds that were actually crossed in the historical window."""
    first_hit_ids = {h.threshold_id for h in engine.evaluate(first_reading, site, pack)}
    seen = set()
    crossings = []
    for reading, hits in all_hits[1:]:
        for hit in hits:
            if hit.threshold_id in first_hit_ids or hit.threshold_id in seen:
                continue
            if hit.severity == "baseline":
                continue
            seen.add(hit.threshold_id)
            crossings.append({
                "threshold_id": hit.threshold_id,
                "name": hit.name,
                "severity": hit.severity,
                "citation": hit.citation,
                "trigger_f": hit.trigger_f,
                "forecast_f": round(reading.temp_f, 1),
                "expected_at_utc": reading.ts_utc.isoformat(),
                "lead_minutes": 0,  # already happened
                "requirements": hit.requirements,
                "confirmed": True,
            })
    crossings.sort(key=lambda c: c["forecast_f"], reverse=True)
    return crossings


_cache: dict = {}
_cache_at: dict = {}


def cached(site_id: str):
    return _cache.get(site_id)


def cache_age_s(site_id: str) -> float:
    at = _cache_at.get(site_id)
    if at is None:
        return float("inf")
    return (datetime.now(timezone.utc) - at).total_seconds()


async def status_of_site(site_id: str, max_age_s: float = None, force: bool = False) -> dict:
    # Default cache window matches the poll interval so UI refreshes never hit the API
    max_age = config.POLL_INTERVAL_S if max_age_s is None else max_age_s
    if not force and cache_age_s(site_id) <= max_age and site_id in _cache:
        return {**_cache[site_id], "cached": True, "cache_age_s": round(cache_age_s(site_id))}
    result = await scan_site(site_id)
    return {**result, "cached": False, "cache_age_s": 0}


def cached_statuses() -> list:
    """Every status already in memory. Makes no API call and costs no quota.

    With a large site registry this is what a UI refresh should use: scanning
    39 sites would blow a 30/day heatmap budget in a single click.
    """
    out = []
    for site in all_sites():
        entry = _cache.get(site.id)
        if entry is None:
            continue
        out.append({**entry, "cached": True, "cache_age_s": round(cache_age_s(site.id))})
    return out


async def scan_all(force: bool = True, max_age_s: float = None) -> list:
    """Scan every site concurrently.

    Serially this took (number of sites) x (poll timeout) in the worst case —
    six sites x 90s is nine minutes of a browser sitting on a spinner with no
    output. Concurrently the whole request is bounded by the slowest single
    site, and each failure is returned as an error row instead of aborting.
    """
    sites = all_sites()
    sem = asyncio.Semaphore(3)  # burst control: 6 simultaneous submits can trip rate limits

    async def one(site):
        async with sem:
            try:
                if force:
                    return await scan_site(site.id)
                return await status_of_site(site.id, max_age_s=max_age_s)
            except Exception as exc:
                log.exception("scan failed for %s", site.id)
                return {
                    "site_id": site.id,
                    "status": "error",
                    "status_label": "Data unavailable",
                    "error": f"{type(exc).__name__}: {exc}",
                }

    return list(await asyncio.gather(*(one(s) for s in sites)))


async def loop() -> None:
    log.info(
        "agent loop starting: every %ss, %sh window, mode=%s",
        config.POLL_INTERVAL_S,
        config.LOOKAHEAD_HOURS,
        config.resolved_mode(),
    )
    while True:
        try:
            await scan_all()
        except Exception:
            log.exception("scan cycle failed")
        await asyncio.sleep(config.POLL_INTERVAL_S)
