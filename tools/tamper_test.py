"""Prove the ledger is tamper-evident.

Run this live in the demo. It edits one historical temperature directly in the
database, exactly the way someone would if they wanted a bad afternoon to
disappear, and then shows verification naming the entry that changed.

    python -m tools.tamper_test

Restores the original value at the end, so it is safe to run before presenting.
"""
import json
import sqlite3
import sys

from app import ledger
from app.config import DB_PATH


def show(label: str) -> dict:
    result = ledger.verify()
    mark = "PASS" if result["ok"] else "FAIL"
    print(f"\n[{mark}] {label}")
    print(f"       entries: {result['entries']}")
    print(f"       {result['reason']}")
    if result["broken_at_seq"]:
        print(f"       first bad entry: #{result['broken_at_seq']}")
    return result


def main() -> int:
    ledger.init()
    if not ledger.entries(limit=1):
        print("Ledger is empty. Start the server once so the agent writes some entries.")
        return 1

    show("chain as written")

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT seq, payload FROM entries WHERE kind IN ('READING','STATUS_CHANGE')"
        " ORDER BY seq ASC LIMIT 1"
    ).fetchone()
    if row is None:
        print("No temperature entries to tamper with yet.")
        return 1

    seq = row["seq"]
    original = row["payload"]
    payload = json.loads(original)
    before = payload.get("temp_f")
    payload["temp_f"] = 79.0  # just under the California shade threshold
    forged = ledger.canonical(payload)

    print(f"\n--- editing entry #{seq}: temp_f {before} -> 79.0, leaving its hash untouched")
    conn.execute("UPDATE entries SET payload = ? WHERE seq = ?", (forged, seq))
    conn.commit()

    result = show("chain after the edit")

    conn.execute("UPDATE entries SET payload = ? WHERE seq = ?", (original, seq))
    conn.commit()
    conn.close()

    show("chain after restoring the original value")

    print(
        "\nThe edit changed one number in one row and nothing else. Verification located it "
        "by sequence number without needing to know what the original value was."
    )
    return 0 if not result["ok"] else 2


if __name__ == "__main__":
    sys.exit(main())
