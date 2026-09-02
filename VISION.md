# Vision: structured company data for Value Beyond Wealth

This file is the north star for this repo. V1 is intentionally small. Do not lose the later destination.

## The problem

Value Beyond Wealth (Base44 website) lets admins generate stock research with AI. The AI is weak at finding **correct company financials and related facts** if it has to hunt the web at query time. Those numbers should already exist in a structured store, then be handed to the researcher.

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

### How Base44 should call this (later, not V1)

Base44 can import an OpenAPI spec as a custom workspace integration, or a Base44 backend function can `fetch` our HTTP API. The website should receive JSON that matches `CompanySnapshot` in this repo. Same extract function, different wrapper.

Production must **not** scrape Proff.no. Swap the Proff HTML adapter for a licensed Proff API (or equivalent) behind the same interface.

## V1 (this repo, now)

Local-only quality check:

- Norwegian companies only (listed and unlisted)
- Streamlit on this PC, data in a local folder
- Brreg for identity, roles, group tree, last-year accounts (cross-check)
- Public Proff.no pages for up to **five years** of financials (and shareholders when shown)
- Computed margins/ratios that do not need a share price
- No HTTP API, no Streamlit Cloud, no OAuth, no Base44 wiring

See [README.md](README.md) for how to run it.

## Later (after V1 quality looks good)

1. Keep `extract_company()` and `CompanySnapshot` unchanged.
2. Add a thin FastAPI wrapper: cache-first `GET /companies/{orgnr}`, `POST /extract`.
3. Publish OpenAPI for Base44.
4. Replace the Proff scraper with a licensed feed.
5. Add share prices, then multiples (P/E, EV/EBITDA, …).
6. Other countries, one source adapter at a time.

## Sibling project

`company-collector` (local Automasjon / Datahenting) downloads **documents**. This project stores **structured numbers**. Later pieces should **read the folders**, not import either package.
