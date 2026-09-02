# Vision: structured company data for Value Beyond Wealth

This file is the north star for this repo. Do not lose the later destination.

## The problem

Value Beyond Wealth (Base44 website) lets admins generate stock research with AI. The AI is weak at finding **correct company financials and other company data** if it has to hunt the web at query time. Those numbers should already exist in a structured store, then be handed to the researcher.

## Grand vision

A reusable **extract function** that the website can call:

1. Admin (or the researcher) asks for a company.
2. If we already have a fresh snapshot, return it from storage.
3. If not, gather data from official registers and licensed feeds, structure it, store it, and return it.
4. The AI researcher uses that snapshot instead of scraping the web itself.

Target contents (over time):

- Financial statements (multi-year)
- Leadership / board
- Shareholders / ownership
- Company / group structure
- Business category (NACE)
- **Derived** margins and (for listed names) market multiples

Storage must stay **indexable by organisation number** (and later ticker), so lookup is cheap.

### How Base44 calls this

Do **not** copy this Python extractor into Base44 (Base44 functions are TypeScript/Deno). Keep one codebase here.

1. This repo exposes `POST /extract` and `GET /companies/{orgnr}` (FastAPI wrapper around `extract_company()`).
2. Host the API (Railway). JSON matches `CompanySnapshot`.
3. Base44 imports `/openapi.json` as a custom workspace integration (`company-financials`), or a backend function `fetch`es the same URLs.
4. Value Beyond Wealth saves the snapshot on a `CompanySnapshot` entity keyed by organisation number. The researcher reads that entity.

See [README.md](README.md) for local API, Railway, and Base44 click steps.

Production-quality path still should **not** scrape Proff.no. Swap the Proff HTML adapter for a licensed Proff API (or equivalent) behind the same `extract_company()` interface. Personal-use can keep the scrape until then.

## Now (this repo)

- Norwegian companies only (listed and unlisted)
- Streamlit on this PC for quality checking; data in a local folder
- HTTP API for Base44 (`src/company_financials/api.py`)
- Brreg for identity, roles, group tree, last-year accounts (cross-check)
- Public Proff.no pages for up to **five years** of financials (and shareholders when shown)
- Computed margins/ratios that do not need a share price
- No Streamlit Cloud, no OAuth

## Later

1. Keep `extract_company()` and `CompanySnapshot` unchanged unless the JSON contract must grow.
2. Replace the Proff scraper with a licensed feed.
3. Add share prices, then multiples (P/E, EV/EBITDA, …).
4. Other countries, one source adapter at a time.

Improving the extractor later: change this repo, push to GitHub, Railway redeploys. Base44 keeps the same endpoints.

## Sibling project

`company-collector` (local Automasjon / Datahenting) downloads **documents**. This project stores **structured numbers**. Later pieces should **read the folders**, not import either package.
