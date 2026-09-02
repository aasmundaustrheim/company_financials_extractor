# Company financials extractor (V1)

Local desktop app: type a **Norwegian company name**, and structured financials are saved in a folder on this computer.

This is a **local** tool. There is no website and no login. Extracted data stays on your disk and is not uploaded to GitHub.

Read [VISION.md](VISION.md) for why this exists and what comes after V1.

## Run it

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

`.local-output/` is ignored by Git.

### Optional: command line

```powershell
.\.venv\Scripts\python.exe -m company_financials --company "Equinor ASA" --orgnr 923609016 --output .local-output
```

## What it collects (Norway only)

- Brønnøysund Enhetsregisteret: identity, NACE, leadership, group structure
- Regnskapsregisteret: last filed year (official cross-check)
- Proff.no public pages: up to 5 years of accounts, shareholders when shown
- Computed margins (EBIT, net, equity ratio, ROE, current ratio)

Proff amounts are often in **thousands**. The snapshot stores currency, unit, and a full (normalized) amount.

## Limits

- Local testing only. Do not use this Proff scrape from the live website later.
- Last-year Brreg figures are a preview API and missing for some company types (banks, insurance, some small filings).
- Market multiples (P/E, EV/EBITDA) need a share price and are **not** in V1.

## Tests

```powershell
.\.venv\Scripts\python.exe -m pytest
```

## Git (backup of code only)

- **Commit** = save a snapshot of the code on this PC
- **Push** = copy that snapshot to GitHub

Never commit extracted company folders.

Changes in this chat live **on this PC** until you ask to commit or push.
