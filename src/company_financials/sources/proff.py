"""Proff.no public-page scraper (local testing only).

The live website later must use a licensed feed, not this HTML/JSON scrape.
Proff's Next.js pages embed a company object in ``__NEXT_DATA__``.
"""

from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import quote, urljoin

import httpx

from company_financials.config import MAX_FINANCIAL_YEARS, PROFF_BASE, PROFF_SEARCH_URL
from company_financials.http import fetch
from company_financials.models import (
    FinancialYear,
    GroupLink,
    LogCallback,
    MoneyLine,
    Shareholder,
)

# Published money lines on Proff Norway pages are almost always in thousands.
MONEY_CODES = {
    "revenue": "SDI",
    "sales_revenue": "SI",
    "operating_profit": "DR",
    "profit_before_tax": "ORS",
    "net_profit": "AARS",
    "ebitda": "EBITDA",
    "total_assets": "SED",
    "equity": "SEK",
    "total_debt": "SG",
    "current_assets": "SOM",
    "current_liabilities": "SKG",
    "noncurrent_assets": "SAM",
    "noncurrent_liabilities": "SLG",
}

AVD_RE = re.compile(r"(?:^|-)avd(?:-|$)|avdeling", re.I)


def parse_next_data(html: str) -> dict[str, Any] | None:
    match = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.DOTALL)
    if not match:
        return None
    try:
        data = json.loads(match.group(1))
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def iter_dicts(obj: Any):
    if isinstance(obj, dict):
        yield obj
        for value in obj.values():
            yield from iter_dicts(value)
    elif isinstance(obj, list):
        for item in obj:
            yield from iter_dicts(item)


def extract_company_blob(next_data: dict[str, Any], orgnr: str | None = None) -> dict[str, Any] | None:
    page_company = (
        (next_data.get("props") or {}).get("pageProps") or {}
    ).get("company")
    if isinstance(page_company, dict) and page_company.get("companyAccounts"):
        if not orgnr or str(page_company.get("orgnr") or "") == orgnr:
            return page_company

    best: dict[str, Any] | None = None
    best_score = -1
    for item in iter_dicts(next_data):
        if not isinstance(item.get("orgnr"), (str, int)):
            continue
        if orgnr and str(item.get("orgnr")) != orgnr:
            continue
        accounts = item.get("companyAccounts")
        score = 0
        if isinstance(accounts, list):
            score += 10 + min(len(accounts), 10)
        if item.get("shareholders"):
            score += 3
        if item.get("companyId"):
            score += 1
        if score > best_score:
            best = item
            best_score = score
    return best


def _is_department_href(href: str) -> bool:
    path = href.split("?")[0].lower()
    return bool(AVD_RE.search(path))


def pick_profile_href(html: str, orgnr: str) -> str | None:
    hrefs = re.findall(r'href="(/selskap/[^"]+)"', html)
    unique: list[str] = []
    for href in hrefs:
        if href not in unique:
            unique.append(href)
    if not unique:
        return None

    non_avd = [h for h in unique if not _is_department_href(h)]
    with_orgnr = [h for h in non_avd if h.rstrip("/").endswith(orgnr)]
    if with_orgnr:
        return with_orgnr[0]
    if non_avd:
        return non_avd[0]
    return unique[0]


def _as_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        text = value.strip().replace(" ", "").replace("\xa0", "").replace(",", ".")
        if not text:
            return None
        try:
            return float(text)
        except ValueError:
            return None
    return None


def _codes(accounts: list[dict[str, Any]]) -> dict[str, float]:
    out: dict[str, float] = {}
    for item in accounts:
        code = item.get("code")
        amount = _as_float(item.get("amount"))
        if code and amount is not None:
            out[str(code)] = amount
    return out


def _year_int(value: Any) -> int | None:
    text = str(value or "")
    return int(text[:4]) if text[:4].isdigit() else None


def accounts_to_years(
    periods: list[dict[str, Any]] | None,
    *,
    statement: str,
    unit: int,
    fallback_currency: str,
    limit: int = MAX_FINANCIAL_YEARS,
) -> list[FinancialYear]:
    if not periods:
        return []
    years: list[FinancialYear] = []
    seen: set[int] = set()
    for period in periods:
        year = _year_int(period.get("year") or (period.get("periodEnd") or ""))
        if year is None or year in seen:
            continue
        seen.add(year)
        codes = _codes(period.get("accounts") or [])
        currency = str(period.get("currency") or fallback_currency or "NOK")
        employees = codes.get("ANT")
        kwargs: dict[str, Any] = {
            "year": year,
            "period_start": period.get("periodStart"),
            "period_end": period.get("periodEnd"),
            "currency": currency,
            "unit": unit,
            "statement": statement,
            "employees": int(employees) if employees is not None else None,
        }
        for field, code in MONEY_CODES.items():
            raw = codes.get(code)
            if raw is None and field == "revenue":
                raw = codes.get("SI")
            kwargs[field] = MoneyLine.from_raw(raw, unit, currency)
        years.append(FinancialYear(**kwargs))
        if len(years) >= limit:
            break
    return years


def parse_shareholders(company: dict[str, Any]) -> list[Shareholder]:
    rows: list[Shareholder] = []
    for item in company.get("shareholders") or []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        share = item.get("share")
        percent = _as_float(str(share).replace("%", "") if share is not None else None)
        org = item.get("companyId") or item.get("orgnr")
        orgnr = str(org) if org and str(org).isdigit() and len(str(org)) == 9 else None
        rows.append(
            Shareholder(
                name=name,
                share_percent=percent,
                number_of_shares=_as_float(item.get("numberOfShares")),
                organisation_number=orgnr,
            )
        )
    return rows


def parse_proff_group(company: dict[str, Any]) -> list[GroupLink]:
    structure = company.get("corporateStructure") or {}
    if not isinstance(structure, dict):
        return []
    parent_no = structure.get("parentCompanyOrganisationNumber")
    parent_name = structure.get("parentCompanyName")
    if not parent_no and not parent_name:
        return []
    return [
        GroupLink(
            name=str(parent_name) if parent_name else None,
            organisation_number=str(parent_no) if parent_no else None,
            country=structure.get("parentCompanyCountryCode"),
            relation="parent",
        )
    ]


def detect_unit(
    company_years: list[FinancialYear],
    brreg_summaries: list[dict[str, Any]],
) -> tuple[int, str | None]:
    """Guess whether Proff amounts are thousands by comparing to Brreg."""
    brreg_by_year = {
        int(row["year"]): row
        for row in brreg_summaries
        if row.get("year") and row.get("revenue") is not None
    }
    for year in company_years:
        brreg = brreg_by_year.get(year.year)
        if not brreg or year.revenue is None:
            continue
        raw = year.revenue.raw
        official = float(brreg["revenue"])
        if official == 0:
            continue
        if abs(raw * 1000 - official) / abs(official) < 0.08:
            return 1000, None
        if abs(raw - official) / abs(official) < 0.08:
            return 1, "Proff amounts already match Brreg at unit 1 (not thousands)."
        return 1000, (
            f"Could not auto-detect Proff unit for {year.year} "
            f"(Proff raw {raw} vs Brreg {official}); defaulting to thousands."
        )
    return 1000, None


def rescale_years(years: list[FinancialYear], unit: int) -> list[FinancialYear]:
    updated: list[FinancialYear] = []
    for year in years:
        data = year.model_dump()
        data["unit"] = unit
        for field in MONEY_CODES:
            line = getattr(year, field)
            if line is not None:
                data[field] = MoneyLine.from_raw(line.raw, unit, year.currency)
        updated.append(FinancialYear.model_validate(data))
    return updated


def scrape_proff(
    client: httpx.Client,
    orgnr: str,
    log: LogCallback | None = None,
) -> tuple[dict[str, Any] | None, str | None, dict[str, Any]]:
    """Return (company blob, profile URL, raw bits to save)."""

    def _log(msg: str) -> None:
        if log:
            log(msg)

    search_url = f"{PROFF_SEARCH_URL}?q={quote(orgnr)}"
    _log("Searching Proff by organisation number...")
    try:
        search_html = fetch(client, search_url).text
    except httpx.HTTPError as exc:
        _log(f"Proff search failed: {exc}")
        return None, None, {"error": str(exc), "search_url": search_url}
    href = pick_profile_href(search_html, orgnr)
    raw: dict[str, Any] = {"search_href": href}

    company = None
    search_next = parse_next_data(search_html)
    if search_next:
        company = extract_company_blob(search_next, orgnr)

    profile_url: str | None = None
    if href:
        profile_url = urljoin(PROFF_BASE, href.replace("/selskap/", "/regnskap/", 1))
        if "/regnskap/" not in profile_url:
            profile_url = urljoin(PROFF_BASE, href)
        _log(f"Fetching Proff accounts page: {profile_url}")
        try:
            profile_html = fetch(client, profile_url).text
        except httpx.HTTPError:
            profile_url = urljoin(PROFF_BASE, href)
            _log(f"Retrying Proff profile page: {profile_url}")
            try:
                profile_html = fetch(client, profile_url).text
            except httpx.HTTPError as exc:
                _log(f"Proff profile page failed: {exc}")
                return company, None, raw
        profile_next = parse_next_data(profile_html)
        if profile_next:
            richer = extract_company_blob(profile_next, orgnr)
            if richer:
                company = richer
            raw["proff_orgnr"] = (company or {}).get("orgnr")
            raw["proff_company_id"] = (company or {}).get("companyId")
            raw["proff_name"] = (company or {}).get("name") or (company or {}).get("legalName")
            raw["years"] = [
                p.get("year") for p in (company or {}).get("companyAccounts") or []
            ][:12]

    if company is None:
        _log("Proff did not return a company object in the page data.")
    else:
        n_years = len(company.get("companyAccounts") or [])
        _log(f"Proff company accounts years available: {n_years}.")
    return company, profile_url, raw
