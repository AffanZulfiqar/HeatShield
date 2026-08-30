"""Rulepack engine.

A rulepack is data, not code. Adding a jurisdiction means dropping a JSON file
into packs/ - no branching logic anywhere in the app. That is what makes the
"this scales to 50 states" claim credible rather than aspirational.
"""
import json
from functools import lru_cache
from typing import Iterable, Optional

from app.config import PACKS_DIR
from app.models import Coverage, Reading, RuleHit, Site

OPS = {
    ">=": lambda a, b: a >= b,
    ">": lambda a, b: a > b,
    "<=": lambda a, b: a <= b,
    "<": lambda a, b: a < b,
}

SEVERITY_ORDER = ["baseline", "advisory", "action", "high_heat", "extreme"]


@lru_cache(maxsize=None)
def load_pack(jurisdiction: str) -> dict:
    path = PACKS_DIR / f"{jurisdiction}.json"
    if not path.exists():
        raise FileNotFoundError(
            f"No rulepack for jurisdiction '{jurisdiction}'. "
            f"Available: {', '.join(available_packs())}"
        )
    return json.loads(path.read_text())


def available_packs() -> list:
    return sorted(p.stem for p in PACKS_DIR.glob("*.json"))


def all_packs() -> list:
    return [load_pack(j) for j in available_packs()]


def coverage(pack: dict, have: Optional[Iterable[str]] = None) -> Coverage:
    """Can we evaluate this pack with the signals we actually hold?

    We hold 2 m air temperature. Packs written against heat index need relative
    humidity too. Reporting that honestly is better than quietly treating
    ambient temperature as heat index, which under-reports every humid day and
    would be the single most damaging bug this system could ship.
    """
    have = set(have or {"temp_f"})
    metric = pack.get("metric", "temp_f")
    if metric in have:
        return Coverage(satisfiable=True, metric=metric, note=pack.get("metric_note", ""))
    missing = ", ".join(pack.get("requires_inputs", ["unknown input"]))
    return Coverage(
        satisfiable=False,
        metric=metric,
        missing=missing,
        note=pack.get("metric_note", ""),
    )


def _industry_match(threshold: dict, site: Site) -> bool:
    industries = threshold.get("industries", "all")
    if industries == "all":
        return True
    return site.industry in industries


def _clothing_match(threshold: dict, site: Site) -> bool:
    clothing = threshold.get("clothing", "any")
    if clothing == "any":
        return True
    return site.clothing == clothing


def evaluate(reading: Reading, site: Site, pack: Optional[dict] = None) -> list:
    """Return every threshold the reading currently satisfies, worst last."""
    pack = pack or load_pack(site.jurisdiction)
    cov = coverage(pack)
    if not cov.satisfiable:
        return []

    hits = []
    for t in pack["thresholds"]:
        if not _industry_match(t, site) or not _clothing_match(t, site):
            continue
        op = OPS.get(t.get("op", ">="))
        if op is None or not op(reading.temp_f, t["value_f"]):
            continue
        hits.append(
            RuleHit(
                threshold_id=t["id"],
                name=t["name"],
                severity=t["severity"],
                citation=t.get("citation", pack.get("citation", "")),
                value_f=round(reading.temp_f, 1),
                trigger_f=t["value_f"],
                requirements=t.get("requirements", []),
                evidence_note=t.get("evidence_note", ""),
            )
        )
    hits.sort(key=lambda h: SEVERITY_ORDER.index(h.severity) if h.severity in SEVERITY_ORDER else 0)
    return hits


def worst(hits: list) -> Optional[RuleHit]:
    return hits[-1] if hits else None


def status_of(hits: list) -> str:
    w = worst(hits)
    if w is None:
        return "no_duty"
    return w.severity


def project_crossings(forecast: list, site: Site, pack: Optional[dict] = None) -> list:
    """Find the first forecast hour that crosses each threshold not yet active.

    This is the difference between a thermometer and an agent: the supervisor is
    told at 09:00 that shade and rotations must be staged before 13:00, rather
    than being told at 13:05 that the site is already out of compliance.
    """
    pack = pack or load_pack(site.jurisdiction)
    if not coverage(pack).satisfiable or not forecast:
        return []

    now_hits = {h.threshold_id for h in evaluate(forecast[0], site, pack)}
    crossings = []
    seen = set()
    for reading in forecast[1:]:
        for hit in evaluate(reading, site, pack):
            if hit.threshold_id in now_hits or hit.threshold_id in seen:
                continue
            if hit.severity == "baseline":
                continue
            seen.add(hit.threshold_id)
            lead_minutes = int(
                (reading.ts_utc - forecast[0].ts_utc).total_seconds() // 60
            )
            crossings.append(
                {
                    "threshold_id": hit.threshold_id,
                    "name": hit.name,
                    "severity": hit.severity,
                    "citation": hit.citation,
                    "trigger_f": hit.trigger_f,
                    "forecast_f": round(reading.temp_f, 1),
                    "expected_at_utc": reading.ts_utc.isoformat(),
                    "lead_minutes": lead_minutes,
                    "requirements": hit.requirements,
                }
            )
    crossings.sort(key=lambda c: c["lead_minutes"])
    return crossings
