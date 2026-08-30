# 🔥 HeatShield — Worksite Heat Safety Intelligence

> **Predict. Act. Prove.** — Real-time heat compliance for outdoor construction worksites, powered by FortyGuard temperature intelligence.

[![Live Demo](https://img.shields.io/badge/Live%20Demo-Visit%20App-orange?style=for-the-badge)](https://heat-shield-red.vercel.app)
[![FortyGuard](https://img.shields.io/badge/Powered%20by-FortyGuard-red?style=for-the-badge)](https://fortyguard.com)
[![License](https://img.shields.io/badge/License-MIT-blue?style=for-the-badge)](LICENSE)

---

## 🚀 Live Demo

**[→ https://heat-shield-red.vercel.app](https://heat-shield-red.vercel.app)**

No login required. The demo runs in **replay mode** (synthetic heat data) to protect FortyGuard API quota — all features are fully functional.

---

## 🌡️ What It Does

Heat illness is the #1 weather-related killer of outdoor workers. HeatShield gives site supervisors a single dashboard to:

| Feature | Description |
|---|---|
| **Real-time heat map** | Pulls FortyGuard's hyperlocal temperature signal for any 200m worksite AOI |
| **Jurisdiction compliance** | Checks OSHA, Cal/OSHA, OR-OSHA, WA L&I thresholds automatically |
| **Forecast breach alerts** | Projects threshold crossings up to 12 hours ahead so crews can prepare |
| **Operational heat plan** | Generates step-by-step supervisor actions (STOP / STAGE / PREPARE / MONITOR) |
| **Evidence ledger** | Signed, hash-chained record of every reading — litigation-ready proof |
| **MCP endpoint** | AI agent integration via Model Context Protocol (`/mcp`) |
| **PDF reports** | Downloadable heat safety record per site per day |

---

## 🗺️ Verified Real Worksites

All pins are real, publicly documented U.S. active construction projects:

| Worksite | Location | Source |
|---|---|---|
| Maryland Parkway BRT work zone | Las Vegas, NV | City of Las Vegas construction phasing docs |
| I-10 Gila River bridge work zone | Arizona | ADOT active bridge replacement (2026) |
| TSMC Arizona Fab 21 expansion | Phoenix, AZ | TSMC SEC filing — ongoing construction |
| I-30 Canyon reconstruction | Dallas, TX | TxDOT 2026–2031 active project |
| UCLA Gayley Towers | Los Angeles, CA | UCLA Capital Programs (through Feb 2027) |
| N. Houston Highway drainage work | Houston, TX | TxDOT segment 3B-1, St. Emanuel St. |

> Pins are work-zone representatives, not claims that a specific crew is at the exact coordinate at this instant.

---

## 🛠️ Tech Stack

- **Backend:** FastAPI (Python) + uvicorn
- **Temperature data:** [FortyGuard API](https://fortyguard.com) — hyperlocal heatmap at 100m granularity
- **Compliance rules:** Multi-jurisdiction JSON rulepacks (Federal OSHA, CA, OR, WA)
- **Evidence chain:** SQLite with SHA-256 hash chain (tamper-evident ledger)
- **Frontend:** Vanilla JS + Leaflet.js (no framework — fast, zero-dependency UI)
- **AI integration:** MCP (Model Context Protocol) endpoint for agent tooling
- **Station baseline:** NOAA/NWS API — free, keyless, no quota

---

## ⚡ Run Locally

```powershell
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
Copy-Item .env.example .env
# Add your FortyGuard API key to .env (leave blank for replay/demo mode)
python -m uvicorn app.main:app --reload
```

Open **http://127.0.0.1:8000**

---

## 🔑 API Quota Protection

The app is designed to **never burn FortyGuard credits accidentally**:

- No API call at startup
- No API call when selecting a site
- No background polling by default (`POLL_ENABLED=false`)
- One explicit "Analyze" click = one heatmap request (cached for 6 hours)
- `LOOKAHEAD_HOURS=0` — current temp only, no extra forecast tasks
- `DATA_MODE=replay` for demos — zero quota, full UI

---

## 🤖 MCP Endpoint (AI Agent Integration)

HeatShield exposes a Model Context Protocol server at `/mcp`:

```
POST /mcp  →  JSON-RPC 2.0
GET  /mcp/tools  →  tool list
POST /mcp/call   →  direct tool call
```

**Available tools:** `list_sites`, `check_compliance`, `forecast_breach`, `generate_heat_plan`, `get_evidence`, `verify_ledger`, `station_delta`, `explain_rulepack`

---

## ⚠️ Known Limitations / What Doesn't Work Yet

- **Serverless SQLite:** On Vercel the evidence ledger resets between cold starts (SQLite writes to `/tmp` which is ephemeral). A persistent deployment (Railway, Render, or a VM) retains the ledger across sessions.
- **Slack notifications:** `SLACK_WEBHOOK_URL` is wired but untested end-to-end in the competition build.
- **Historical FortyGuard data:** The `station_delta` comparison fetches NWS station readings (free, no key) but the FortyGuard historical filter (`FG_FILTER_HISTORICAL=3`) depends on your plan's historical data window — not verified beyond the current reading.
- **Mobile layout:** The UI is optimised for desktop (1024px+). Narrow screens clip the left panel.
- **LOOKAHEAD_HOURS > 0:** Forecast breach alerts are fully wired but the FortyGuard free-tier quota makes multi-hour lookahead expensive; `LOOKAHEAD_HOURS=0` is the safe default.

---

## 🔬 Real FortyGuard API Request & Response

The following is a real request+response from the FortyGuard heatmap API (TSMC Arizona Fab 21, Phoenix AZ, captured during development):

**Request — POST `https://api.fortyguard.com/v1/heatmap`**
```json
{
  "polygon_aoi": [
    [33.5105, -112.0346],
    [33.5105, -112.0328],
    [33.5087, -112.0328],
    [33.5087, -112.0346],
    [33.5105, -112.0346]
  ],
  "date_time": "2026-08-28T14:00:00Z",
  "granularity": 100,
  "filter": 1
}
```
*Header:* `api-key: <redacted>`

**Response**
```json
{
  "data": {
    "activity_id": "fg-a8c21d94-3b7e-4a12-9f01-d5e8c3b22a47",
    "status": "processing"
  }
}
```

**Poll — GET `https://api.fortyguard.com/v1/status/fg-a8c21d94-3b7e-4a12-9f01-d5e8c3b22a47`**
```json
{
  "data": {
    "activity_id": "fg-a8c21d94-3b7e-4a12-9f01-d5e8c3b22a47",
    "status": "completed",
    "result": {
      "tiles": [
        { "lat": 33.5096, "lon": -112.0337, "temperature": 41.2, "units": "c" },
        { "lat": 33.5096, "lon": -112.0328, "temperature": 42.0, "units": "c" }
      ]
    }
  }
}
```

*Temperature of 41.2 °C = 106.2 °F — above the Cal/OSHA High Heat threshold (100 °F). HeatShield would trigger a **HIGH HEAT** alert and generate the STOP/PROTECT heat plan for this site.*

---

## 📄 License

MIT — built for the FortyGuard Real Worksites Competition.
