"""Core data types shared across the app."""
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Any, Optional


@dataclass
class Site:
    id: str
    name: str
    operator: str
    industry: str
    jurisdiction: str
    lat: float
    lng: float
    timezone: str
    shift_start: str  # local "HH:MM"
    shift_end: str
    supervisor: str
    clothing: str = "standard"  # standard | double_layer | non_breathing
    notes: str = ""
    source_url: str = ""
    source_name: str = ""
    state: str = ""             # two-letter code, for UI filtering
    verified: bool = False      # True only for sites with source_url provenance

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Reading:
    """One temperature value for one place at one time."""

    site_id: str
    ts_utc: datetime
    temp_f: float
    source: str  # fortyguard | station:KXYZ | replay
    provenance: str  # measured | forecast | replay-synthetic
    detail: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "site_id": self.site_id,
            "ts_utc": self.ts_utc.isoformat(),
            "temp_f": round(self.temp_f, 2),
            "source": self.source,
            "provenance": self.provenance,
            "detail": self.detail,
        }


@dataclass
class RuleHit:
    """A threshold in a rulepack that the reading satisfies."""

    threshold_id: str
    name: str
    severity: str  # action | high_heat | extreme
    citation: str
    value_f: float
    trigger_f: float
    requirements: list
    evidence_note: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Coverage:
    """Whether a rulepack can actually be evaluated with the data we hold.

    Rules written against heat index (Oregon) need humidity, which a pure
    temperature feed cannot supply. Saying so out loud is the honest move.
    """

    satisfiable: bool
    metric: str
    missing: Optional[str] = None
    note: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def jsonable(obj: Any) -> Any:
    if isinstance(obj, datetime):
        return obj.isoformat()
    if hasattr(obj, "to_dict"):
        return obj.to_dict()
    if isinstance(obj, list):
        return [jsonable(o) for o in obj]
    if isinstance(obj, dict):
        return {k: jsonable(v) for k, v in obj.items()}
    return obj
