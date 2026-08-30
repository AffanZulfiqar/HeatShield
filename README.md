# HeatShield — Real Worksite Heat Operations

**Predict. Act. Prove.**

HeatShield turns FortyGuard temperature intelligence into a worksite safety decision system. The demo uses real, publicly documented U.S. construction/infrastructure/industrial projects as worksite pins.

## Competition demo
1. Start the app.
2. The map loads **without making any FortyGuard requests**.
3. Select a real worksite.
4. Click **Analyze worksite** / refresh for that site.
5. HeatShield submits **one** FortyGuard heatmap task for the site's 200 m AOI at 100 m granularity.
6. The result is cached for the configured poll interval.
7. Generate the heat plan and evidence record.

### Credit protection
- No FortyGuard call at startup.
- No automatic background polling by default.
- No API call when merely selecting a site.
- One explicit analysis = one heatmap task when the cache is empty.
- Repeated views use the in-memory cache until it expires.
- `LOOKAHEAD_HOURS=0` is the default, so the live provider does not create extra hourly tasks.
- Use replay mode for rehearsals.

## Verified real worksites
- Maryland Parkway BRT work zone — Las Vegas, NV. City of Las Vegas documents the active project; the construction phasing document lists work hours.
- I-10 Gila River bridge work zone — Arizona. ADOT documents active bridge replacement and 2026 construction activity.
- TSMC Arizona Fab 21 expansion — Phoenix, AZ. TSMC's SEC filing states construction of additional facilities is ongoing.
- I-30 Canyon reconstruction — Dallas, TX. TxDOT documents the 2026–2031 active project and construction work zone.
- UCLA Gayley Towers — Los Angeles, CA. UCLA Capital Programs lists the project in Construction phase through Feb 2027.
- North Houston Highway Improvement drainage work — Houston, TX. TxDOT lists active segment 3B-1 construction along St. Emanuel Street.

The pins are **project/work-zone representatives**, not claims that a specific crew is standing at the exact coordinate at this instant.

## Run
```powershell
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
Copy-Item .env.example .env
# put your FortyGuard key in .env
python -m uvicorn app.main:app --reload
```
Open `http://127.0.0.1:8000`.

## Live vs replay
`DATA_MODE=auto` uses FortyGuard only when a key is present. `DATA_MODE=replay` never calls the API and is ideal for the competition rehearsal.
