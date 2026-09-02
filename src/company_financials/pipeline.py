"""Orchestrate Brreg + Proff into a CompanySnapshot and a local folder."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import httpx

from company_financials.config import DEFAULT_OUTPUT_DIR, LISTED_ORG_FORMS, MAX_FINANCIAL_YEARS
from company_financials.http import create_client
from company_financials.models import (
    Address,
    BrregEntity,
    CompanySnapshot,
    Coverage,
    FinancialYear,
    GroupLink,
    Identity,
    LogCallback,
    Mismatch,
    NaceCode,
    RunResult,
    SourceRef,
    utc_now,
)
from company_financials.ratios import compute_ratios
from company_financials.resolver import resolve_company
from company_financials.sources.brreg import fetch_accounts, fetch_group, fetch_roles
from company_financials.sources.proff import (
    accounts_to_years,
    detect_unit,
    parse_proff_group,
    parse_shareholders,
    rescale_years,
    scrape_proff,
)
from company_financials.storage.local import find_cached, load_snapshot, write_snapshot


def _nace(entity: BrregEntity) -> list[NaceCode]:
    codes: list[NaceCode] = []
    for raw in (entity.naeringskode1, entity.naeringskode2, entity.naeringskode3):
        if isinstance(raw, dict) and (raw.get("kode") or raw.get("beskrivelse")):
            codes.append(
                NaceCode(code=raw.get("kode"), description=raw.get("beskrivelse"))
            )
    return codes


def _address(raw: dict[str, Any] | None) -> Address | None:
    if not raw:
        return None
    streets = raw.get("adresse") or []
    if isinstance(streets, str):
        streets = [streets]
    return Address(
        street=[str(s) for s in streets],
        postal_code=raw.get("postnummer"),
        city=raw.get("poststed"),
        municipality=raw.get("kommune"),
        country=raw.get("land"),
    )


def _purpose(entity: BrregEntity) -> str | None:
    parts = entity.vedtektsfestetFormaal or []
    text = " ".join(str(p) for p in parts).strip()
    return text or None


def identity_from_entity(entity: BrregEntity) -> Identity:
    form = entity.organisasjonsform or {}
    code = form.get("kode")
    return Identity(
        orgnr=entity.organisasjonsnummer,
        name=entity.navn,
        org_form_code=code,
        org_form=form.get("beskrivelse") or code,
        listed=code in LISTED_ORG_FORMS,
        employees=entity.antallAnsatte,
        website=entity.hjemmeside,
        purpose=_purpose(entity),
        nace=_nace(entity),
        address=_address(entity.forretningsadresse),
        founded=entity.stiftelsesdato,
        last_accounts_year=entity.sisteInnsendteAarsregnskap,
        bankrupt=entity.konkurs,
        under_liquidation=entity.underAvvikling,
        in_group=entity.erIKonsern,
    )


def _merge_group(brreg: list[GroupLink], proff: list[GroupLink]) -> list[GroupLink]:
    merged: list[GroupLink] = []
    seen: set[tuple[str | None, str | None, str | None]] = set()
    for item in [*brreg, *proff]:
        key = (item.organisation_number, item.name, item.relation)
        if key in seen:
            continue
        seen.add(key)
        merged.append(item)
    return merged


def _cross_check(
    years: list[FinancialYear],
    brreg_summaries: list[dict[str, Any]],
) -> list[Mismatch]:
    mismatches: list[Mismatch] = []
    by_year = {int(row["year"]): row for row in brreg_summaries if row.get("year")}
    fields = (
        "revenue",
        "operating_profit",
        "net_profit",
        "equity",
        "total_assets",
        "total_debt",
    )
    for year in years:
        if year.statement != "company":
            continue
        official = by_year.get(year.year)
        if not official:
            continue
        for field in fields:
            brreg_val = official.get(field)
            line = getattr(year, field)
            proff_val = None if line is None else line.normalized
            if brreg_val is None or proff_val is None:
                continue
            denom = max(abs(brreg_val), 1.0)
            rel = abs(proff_val - brreg_val) / denom
            if rel > 0.05 and abs(proff_val - brreg_val) > 1000:
                mismatches.append(
                    Mismatch(
                        year=year.year,
                        field=field,
                        brreg=brreg_val,
                        proff=proff_val,
                        note=f"relative difference {rel:.1%}",
                    )
                )
    return mismatches


def _expected_years(have: list[int]) -> list[int]:
    this_year = date.today().year
    # Norwegian filings lag; the newest expected year is last calendar year
    # unless Proff already has the current year.
    newest = max(have) if have else this_year - 1
    newest = min(newest, this_year)
    want = list(range(newest, newest - MAX_FINANCIAL_YEARS, -1))
    return [y for y in want if y not in have]


def extract_company(
    company_name: str,
    output_dir: str | Path | None = None,
    orgnr: str | None = None,
    entity: BrregEntity | None = None,
    refresh: bool = False,
    log: LogCallback | None = None,
) -> RunResult:
    messages: list[str] = []

    def _log(msg: str) -> None:
        messages.append(msg)
        if log:
            log(msg)

    output_root = Path(output_dir or DEFAULT_OUTPUT_DIR)

    with create_client() as client:
        if entity is None:
            resolved, candidates = resolve_company(client, company_name, orgnr, _log)
            if resolved is None and candidates:
                return RunResult(
                    success=False,
                    needs_disambiguation=True,
                    candidates=candidates,
                    messages=messages,
                )
            if resolved is None:
                return RunResult(success=False, messages=messages)
            entity = resolved

        if not refresh:
            cached = find_cached(output_root, entity.organisasjonsnummer)
            if cached is not None:
                snapshot = load_snapshot(cached)
                _log(f"Loaded cached snapshot from {cached}")
                return RunResult(
                    success=True,
                    snapshot=snapshot,
                    company_dir=cached,
                    messages=messages,
                    loaded_from_cache=True,
                )

        ident = identity_from_entity(entity)
        sources: list[SourceRef] = [
            SourceRef(
                name="brreg_enhet",
                url=f"https://data.brreg.no/enhetsregisteret/api/enheter/{entity.organisasjonsnummer}",
                fetched_at=utc_now(),
            )
        ]
        raw_sources: dict[str, object] = {"brreg_enhet": entity.raw}

        leadership, roles_raw = fetch_roles(client, entity.organisasjonsnummer, _log)
        if roles_raw is not None:
            raw_sources["brreg_roles"] = roles_raw
            sources.append(
                SourceRef(name="brreg_roles", fetched_at=utc_now())
            )

        group_brreg, group_raw = fetch_group(client, entity.organisasjonsnummer, _log)
        if group_raw is not None:
            raw_sources["brreg_group"] = group_raw
            sources.append(SourceRef(name="brreg_group", fetched_at=utc_now()))

        brreg_summaries, accounts_raw = fetch_accounts(
            client, entity.organisasjonsnummer, _log
        )
        if accounts_raw is not None:
            raw_sources["brreg_regnskap"] = accounts_raw
            sources.append(SourceRef(name="brreg_regnskap", fetched_at=utc_now()))

        try:
            company, proff_url, proff_meta = scrape_proff(
                client, entity.organisasjonsnummer, _log
            )
        except httpx.HTTPError as exc:
            _log(f"Proff scrape failed: {exc}")
            company, proff_url, proff_meta = None, None, {"error": str(exc)}
        raw_sources["proff_meta"] = proff_meta
        if proff_url:
            sources.append(SourceRef(name="proff", url=proff_url, fetched_at=utc_now()))

        warnings: list[str] = []
        financials: list[FinancialYear] = []
        shareholders = []
        group_proff: list[GroupLink] = []
        unit = 1000

        if company:
            slim = {
                "orgnr": company.get("orgnr"),
                "name": company.get("name") or company.get("legalName"),
                "companyId": company.get("companyId"),
                "currency": company.get("currency"),
                "companyAccounts": (company.get("companyAccounts") or [])[:MAX_FINANCIAL_YEARS],
                "corporateAccounts": (company.get("corporateAccounts") or [])[:MAX_FINANCIAL_YEARS],
                "shareholders": company.get("shareholders"),
                "corporateStructure": company.get("corporateStructure"),
                "companyType": company.get("companyType"),
                "status": company.get("status"),
            }
            raw_sources["proff_company"] = slim
            currency = str(company.get("currency") or "NOK")
            company_years = accounts_to_years(
                company.get("companyAccounts"),
                statement="company",
                unit=1000,
                fallback_currency=currency,
            )
            group_years = accounts_to_years(
                company.get("corporateAccounts"),
                statement="group",
                unit=1000,
                fallback_currency=currency,
            )
            unit, unit_note = detect_unit(company_years, brreg_summaries)
            if unit_note:
                warnings.append(unit_note)
            if unit != 1000:
                company_years = rescale_years(company_years, unit)
                group_years = rescale_years(group_years, unit)
            financials = [*company_years, *group_years]
            shareholders = parse_shareholders(company)
            group_proff = parse_proff_group(company)
            if ident.org_form_code is None:
                ctype = (company.get("companyType") or {}).get("code")
                if ctype:
                    ident.org_form_code = str(ctype)
                    ident.listed = str(ctype) in LISTED_ORG_FORMS
        else:
            warnings.append("Proff scrape returned no company object; financial history may be empty.")

        if not any(y.statement == "company" for y in financials):
            warnings.append("No multi-year company accounts from Proff.")

        mismatches = _cross_check(financials, brreg_summaries)
        company_year_nums = sorted(
            {y.year for y in financials if y.statement == "company"}, reverse=True
        )
        group_year_nums = sorted(
            {y.year for y in financials if y.statement == "group"}, reverse=True
        )
        missing = _expected_years(company_year_nums)
        if missing:
            warnings.append(
                f"Not all of the last {MAX_FINANCIAL_YEARS} years are present: missing {missing}."
            )

        coverage = Coverage(
            requested_years=MAX_FINANCIAL_YEARS,
            company_years=company_year_nums,
            group_years=group_year_nums,
            missing_years=missing,
            proff_unit=unit,
            proff_url=proff_url,
            brreg_accounts_years=sorted(
                {int(s["year"]) for s in brreg_summaries if s.get("year")}, reverse=True
            ),
            mismatches=mismatches,
            warnings=warnings,
        )
        snapshot = CompanySnapshot(
            identity=ident,
            leadership=leadership,
            shareholders=shareholders,
            group=_merge_group(group_brreg, group_proff),
            financials=financials,
            ratios=compute_ratios(financials),
            coverage=coverage,
            sources=sources,
        )
        folder = write_snapshot(output_root, snapshot, raw_sources)
        _log(f"Saved snapshot to {folder}")
        return RunResult(
            success=True,
            snapshot=snapshot,
            company_dir=folder,
            messages=messages,
        )
