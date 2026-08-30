# 🔥 HeatShield — Worksite Heat Safety Intelligence

> **Predict. Act. Prove.** — Real-time heat compliance for outdoor construction worksites, powered by FortyGuard temperature intelligence.

[![Live Demo](https://img.shields.io/badge/Live%20Demo-Visit%20App-orange?style=for-the-badge)](https://heat-shield.up.railway.app)
[![FortyGuard](https://img.shields.io/badge/Powered%20by-FortyGuard-red?style=for-the-badge)](https://fortyguard.com)
[![License](https://img.shields.io/badge/License-MIT-blue?style=for-the-badge)](LICENSE)

---

## 🚀 Live Demo

**[→ https://heat-shield.up.railway.app](https://heat-shield.up.railway.app)**

Running in **live mode** on Railway — real FortyGuard temperature data for each worksite. `LOOKAHEAD_HOURS=0` is intentional to stay within the free-tier quota of 30 heatmaps/day (current reading only, no hourly forecast tasks).

---

## 🌡️ What It Does

Heat illness is the #1 weather-related killer of outdoor workers. HeatShield gives site supervisors a single dashboard to:

| Feature | Description |
|---|---|
| **Real-time heat map** | Pulls FortyGuard's hyperlocal temperature signal for any 200m worksite AOI |
| **Jurisdiction compliance** | Checks OSHA, Cal/OSHA, OR-OSHA, WA L&I thresholds automatically |
| **Forecast breach alerts** | Wired and functional — disabled on the live Railway deployment (`LOOKAHEAD_HOURS=0`) to stay within the 30 heatmaps/day free-tier quota |
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

- **Evidence ledger persistence:** Deployed on Railway which has a **persistent filesystem** — the hash-chained SQLite ledger survives restarts and retains all historical readings. (Note: serverless platforms like Vercel would reset the ledger on cold starts.)
- **Slack notifications:** `SLACK_WEBHOOK_URL` is wired but untested end-to-end in the competition build.
- **Historical FortyGuard data:** The `station_delta` comparison fetches NWS station readings (free, no key) but the FortyGuard historical filter (`FG_FILTER_HISTORICAL=3`) depends on your plan's historical data window — not verified beyond the current reading.
- **Mobile layout:** The UI is optimised for desktop (1024px+). Narrow screens clip the left panel.
- **`LOOKAHEAD_HOURS=0` on live deployment:** The Railway deployment is intentionally set to `LOOKAHEAD_HOURS=0` (current temperature only, no hourly forecast tasks). The FortyGuard free tier allows 30 heatmaps/day — with 6 worksites and 6-hour polling that leaves zero headroom for forecast lookahead. Forecast breach alerts are fully wired in the code and work in replay mode; increase `LOOKAHEAD_HOURS` if you have a higher-quota plan.

---

## 🔬 Real FortyGuard API Request & Response

*Site:* Maryland Parkway BRT work zone, Las Vegas, NV (36.14406, -115.13731) — federal jurisdiction (no state heat standard; General Duty Clause applies)

**Request — POST `https://api.fortyguard.com/v1/heatmap`**  
*Header:* `api-key: <redacted>`
```json
{
  "polygon_aoi": {
    "type": "FeatureCollection",
    "features": [{
      "type": "Feature",
      "properties": {},
      "geometry": { "type": "Polygon", "coordinates": [[...]] }
    }]
  },
  "date_time": { "start_date": "<3+ days back>", "start_time": "14:00", "filter_type": 1 },
  "granularity": 100
}
```

**Submit response**
```json
{
  "error": false,
  "status_code": 200,
  "message": "Heatmap Submitted Successfully",
  "data": { "activity_id": "a045e976-adbe-4769-bc24-7fdf0dd45fc9" }
}
```

**Poll response** — GET `/v1/status/a045e976-adbe-4769-bc24-7fdf0dd45fc9` (completed after 7 polls)
```json
{
  "error": false,
  "status_code": 200,
  "message": "Completed",
  "data": {
    "activity_id": "a045e976-adbe-4769-bc24-7fdf0dd45fc9",
    "status": "Completed",
    "result": { "map_data": { "features": [...] } }
  }
}
```

**What our app does with it** — real output from `/api/status`
```json
{
  "site_id": "maryland-parkway-brt-01",
  "status": "advisory",
  "current_f": 101.8,
  "provenance": "measured",
  "source": "fortyguard",
  "is_live": true,
  "worst": {
    "name": "Advisory: elevated risk, document controls",
    "citation": "OSHA-NIOSH heat guidance (non-binding)",
    "trigger_f": 95,
    "requirements": [
      "Increase rest frequency and observation",
      "Record the controls actually applied, since the General Duty Clause is proved by conduct rather than by threshold"
    ]
  }
}
```

*A live, real FortyGuard temperature reading (101.8 °F) is pulled for the exact worksite polygon, then evaluated against jurisdiction-specific thresholds — here, federal OSHA/NIOSH advisory guidance, since Nevada has no state-level heat standard.*

---


## 📄 License

MIT — built for the FortyGuard Real Worksites Competition.
