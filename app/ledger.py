"""Append-only, hash-chained evidence ledger.

Every entry commits to the one before it. Editing or deleting any historical
row breaks the chain from that point forward, and verify() reports exactly
where. That property is the product: a heat-illness claim filed eight months
from now is argued over what the record says, and a record that can be quietly
back-edited is worth nothing.

Deliberately not called "tamper-proof". A local SQLite file can be replaced
wholesale. It is tamper-evident: you cannot change one entry and keep the
chain intact. Anchoring the head hash to an external timestamping service is
the next step and is out of scope for a two-week build.
"""
import hashlib
import json
import sqlite3
import threading
from datetime import datetime, timezone
from typing import Optional

from app.config import DB_PATH

GENESIS = "0" * 64
_lock = threading.Lock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS entries (
    seq         INTEGER PRIMARY KEY AUTOINCREMENT,
    ts_utc      TEXT NOT NULL,
    site_id     TEXT NOT NULL,
    kind        TEXT NOT NULL,
    severity    TEXT,
    payload     TEXT NOT NULL,
    prev_hash   TEXT NOT NULL,
    entry_hash  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_entries_site ON entries(site_id, seq);

CREATE TABLE IF NOT EXISTS site_state (
    site_id     TEXT NOT NULL,
    key         TEXT NOT NULL,
    value       TEXT,
    updated_utc TEXT,
    PRIMARY KEY (site_id, key)
);
"""


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init() -> None:
    with _conn() as conn:
        conn.executescript(SCHEMA)


def canonical(payload: dict) -> str:
    """Byte-stable JSON. The hash is only meaningful if serialisation is."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def digest(seq: int, ts_utc: str, site_id: str, kind: str, payload_json: str, prev_hash: str) -> str:
    material = "|".join([str(seq), ts_utc, site_id, kind, payload_json, prev_hash])
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def head() -> dict:
    with _conn() as conn:
        row = conn.execute(
            "SELECT seq, entry_hash FROM entries ORDER BY seq DESC LIMIT 1"
        ).fetchone()
    if row is None:
        return {"seq": 0, "hash": GENESIS}
    return {"seq": row["seq"], "hash": row["entry_hash"]}


def append(site_id: str, kind: str, payload: dict, severity: Optional[str] = None) -> dict:
    """Write one entry and return it. Serialised to keep the chain linear."""
    ts = datetime.now(timezone.utc).isoformat()
    with _lock:
        with _conn() as conn:
            prev = conn.execute(
                "SELECT seq, entry_hash FROM entries ORDER BY seq DESC LIMIT 1"
            ).fetchone()
            prev_hash = prev["entry_hash"] if prev else GENESIS
            seq = (prev["seq"] if prev else 0) + 1
            payload_json = canonical(payload)
            entry_hash = digest(seq, ts, site_id, kind, payload_json, prev_hash)
            conn.execute(
                "INSERT INTO entries (seq, ts_utc, site_id, kind, severity, payload, prev_hash, entry_hash)"
                " VALUES (?,?,?,?,?,?,?,?)",
                (seq, ts, site_id, kind, severity, payload_json, prev_hash, entry_hash),
            )
    return {
        "seq": seq,
        "ts_utc": ts,
        "site_id": site_id,
        "kind": kind,
        "severity": severity,
        "payload": payload,
        "prev_hash": prev_hash,
        "entry_hash": entry_hash,
    }


def _row_to_entry(row: sqlite3.Row) -> dict:
    return {
        "seq": row["seq"],
        "ts_utc": row["ts_utc"],
        "site_id": row["site_id"],
        "kind": row["kind"],
        "severity": row["severity"],
        "payload": json.loads(row["payload"]),
        "prev_hash": row["prev_hash"],
        "entry_hash": row["entry_hash"],
    }


def entries(site_id: Optional[str] = None, limit: int = 200, kinds: Optional[list] = None) -> list:
    sql = "SELECT * FROM entries"
    where, args = [], []
    if site_id:
        where.append("site_id = ?")
        args.append(site_id)
    if kinds:
        where.append(f"kind IN ({','.join('?' * len(kinds))})")
        args.extend(kinds)
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY seq DESC LIMIT ?"
    args.append(limit)
    with _conn() as conn:
        rows = conn.execute(sql, args).fetchall()
    return [_row_to_entry(r) for r in rows]


def entries_between(site_id: str, start_iso: str, end_iso: str) -> list:
    with _conn() as conn:
        rows = conn.execute(
            "SELECT * FROM entries WHERE site_id = ? AND ts_utc >= ? AND ts_utc <= ? ORDER BY seq ASC",
            (site_id, start_iso, end_iso),
        ).fetchall()
    return [_row_to_entry(r) for r in rows]


def verify() -> dict:
    """Walk the whole chain and recompute every hash."""
    with _conn() as conn:
        rows = conn.execute("SELECT * FROM entries ORDER BY seq ASC").fetchall()

    prev_hash = GENESIS
    expected_seq = 1
    for row in rows:
        if row["seq"] != expected_seq:
            return {
                "ok": False,
                "entries": len(rows),
                "broken_at_seq": row["seq"],
                "reason": f"sequence gap: expected {expected_seq}, found {row['seq']} (an entry was deleted)",
                "head": head(),
            }
        if row["prev_hash"] != prev_hash:
            return {
                "ok": False,
                "entries": len(rows),
                "broken_at_seq": row["seq"],
                "reason": "prev_hash does not match the preceding entry (chain was re-linked)",
                "head": head(),
            }
        recomputed = digest(
            row["seq"], row["ts_utc"], row["site_id"], row["kind"], row["payload"], row["prev_hash"]
        )
        if recomputed != row["entry_hash"]:
            return {
                "ok": False,
                "entries": len(rows),
                "broken_at_seq": row["seq"],
                "reason": "entry content does not match its hash (this entry was edited after the fact)",
                "head": head(),
            }
        prev_hash = row["entry_hash"]
        expected_seq += 1

    return {
        "ok": True,
        "entries": len(rows),
        "broken_at_seq": None,
        "reason": "every entry hashes to its recorded value and links to its predecessor",
        "head": head(),
    }


# --- lightweight per-site agent state (not part of the evidence chain) -----

def get_state(site_id: str, key: str) -> Optional[str]:
    with _conn() as conn:
        row = conn.execute(
            "SELECT value FROM site_state WHERE site_id = ? AND key = ?", (site_id, key)
        ).fetchone()
    return row["value"] if row else None


def set_state(site_id: str, key: str, value: Optional[str]) -> None:
    with _conn() as conn:
        conn.execute(
            "INSERT INTO site_state (site_id, key, value, updated_utc) VALUES (?,?,?,?)"
            " ON CONFLICT(site_id, key) DO UPDATE SET value=excluded.value, updated_utc=excluded.updated_utc",
            (site_id, key, value, datetime.now(timezone.utc).isoformat()),
        )
