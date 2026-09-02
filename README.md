# Company financials extractor

Type a **Norwegian company name**, and structured financials are saved as JSON.

Two ways to run it:

- **On this PC:** Streamlit app (quality check, folders on disk)
- **For Base44:** a small HTTP API around the same `extract_company()` function. Host it on Railway, then Value Beyond Wealth calls it.

Read [VISION.md](VISION.md) for why this exists.

Extracted company folders stay on disk and are not uploaded to GitHub (`.local-output/` is ignored).

## Run the desktop app (this PC)

1. Open this folder in Cursor.
2. In a terminal:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\streamlit.exe run streamlit_app.py
```

3. A browser tab opens (usually http://localhost:8501).
4. Enter a company name (optional: 9-digit organisation number).
5. If several companies match, pick the **legal entity** (not a department / `avd`).
6. Click **Extract**. Open the new `{company}_{orgnr}` folder.

What you should see: `snapshot.json`, `financials.csv`, `snapshot.md`, `quality.md`, `sources/`, `manifest.json`.

### Optional: command line

```powershell
.\.venv\Scripts\python.exe -m company_financials --company "Equinor ASA" --orgnr 923609016 --output .local-output
```

## Run the API locally (try before Railway)

Same extractor, JSON over HTTP. After the pip install above:

```powershell
.\.venv\Scripts\uvicorn.exe company_financials.api:app --reload --app-dir src
```

Open http://localhost:8000/docs

- `GET /health` and `GET /openapi.json` are public
- `POST /extract` body: `{ "company": "Equinor ASA", "orgnr": "923609016", "refresh": false }`
- `GET /companies/{orgnr}` returns a cached snapshot if one exists
- If env `COMPANY_FINANCIALS_API_KEY` is set, send it as header `X-API-Key`

If several Brreg matches, `POST /extract` returns `needs_disambiguation: true` and a short `candidates` list. Retry with the legal entity's `orgnr`.

## Put the API on Railway (so Base44 can reach it)

Railway waits long enough for a scrape (often 15–60 seconds). You need a GitHub push of this branch first.

1. Open [railway.app](https://railway.app) and log in with GitHub
2. **New project** → **Deploy from GitHub repo** → `company_financials_extractor`
3. If it asks for a branch, pick `main` or `master` (whichever has this API code) — or this `Base44-accessible` branch until it is merged
4. After the first deploy, open the service → **Settings** → **Networking** → **Generate domain**
5. Open **Variables** and add:
   - `COMPANY_FINANCIALS_API_KEY` = a long random string (do not put this in Git)
6. Redeploy if the variable was added after the first boot
7. In a browser, open `https://YOUR-RAILWAY-URL/health` — you should see `{"status":"ok"}`

**Later extractor improvements:** edit this repo → commit → push to GitHub. Railway redeploys. Base44 keeps calling the same two URLs. You only change Base44 if the JSON *shape* changes.

## Connect Base44

Needs a Base44 **Builder** plan (custom workspace integrations).

1. In Base44, click your workspace name (bottom left) → **Settings** → **Integrations** → **New Integration**
2. Choose **From URL** and paste `https://YOUR-RAILWAY-URL/openapi.json` (or **Paste JSON** from that same URL)
3. Enable **POST /extract** and **GET /companies/{orgnr}**
4. **Slug:** `company-financials`
5. **Base URL:** `https://YOUR-RAILWAY-URL` (no trailing slash)
6. **Custom header:** name `X-API-Key`, value = the same secret as on Railway
7. Create the integration

Then in **Value Beyond Wealth**, tell the Base44 builder:

```
When an admin generates stock research, first get structured financials from the workspace integration slug "company-financials".

1. Call post:/extract with { company, orgnr?, refresh? }.
2. If the response has needs_disambiguation=true, show the candidates and ask the admin to pick the legal entity (not an avd). Retry post:/extract with that orgnr.
3. Save the returned snapshot on a CompanySnapshot entity keyed by organisation number.
4. The AI researcher must read that stored snapshot for accounts, leadership, shareholders, NACE, and ratios. Do not scrape the web for those numbers.

If a snapshot already exists, you may call get:/companies/{orgnr} instead of extracting again.
```

If custom integrations are not on your plan, add one Base44 backend function that `fetch`es `https://YOUR-RAILWAY-URL/extract` with the `X-API-Key` header. Do not copy this Python extractor into Base44.

## What it collects (Norway only)

- Brønnøysund Enhetsregisteret: identity, NACE, leadership, group structure
- Regnskapsregisteret: last filed year (official cross-check)
- Proff.no public pages: up to 5 years of accounts, shareholders when shown
- Computed margins (EBIT, net, equity ratio, ROE, current ratio)

Proff amounts are often in **thousands**. The snapshot stores currency, unit, and a full (normalized) amount.

## Limits

- Personal-use website: the Proff scrape is still in this code. A cloud IP can be blocked; if that happens, use Streamlit on this PC, and later swap Proff for a licensed API behind the same `extract_company()`.
- Last-year Brreg figures are a preview API and missing for some company types (banks, insurance, some small filings).
- Market multiples (P/E, EV/EBITDA) need a share price and are **not** included yet.

## Tests

```powershell
.\.venv\Scripts\python.exe -m pytest
```

## Git (backup of code only)

- **Commit** = save a snapshot of the code on this PC
- **Push** = copy that snapshot to GitHub (Railway can then redeploy)

Never commit extracted company folders or `COMPANY_FINANCIALS_API_KEY`.

Changes in this chat live **on this PC** until you ask to commit or push. After a GitHub push + Railway deploy, the API is on the internet (locked with the API key). Base44 wiring is **on Base44**.
