"""Resolve Norwegian companies via Brreg Enhetsregisteret."""

from __future__ import annotations

import re

import httpx

from company_financials.config import BRREG_ENHET_ACCEPT, BRREG_ENHET_URL
from company_financials.http import fetch
from company_financials.models import BrregEntity, LogCallback


def validate_orgnr(orgnr: str) -> bool:
    digits = re.sub(r"\D", "", orgnr)
    return len(digits) == 9 and digits.isdigit()


def normalize_orgnr(orgnr: str) -> str:
    return re.sub(r"\D", "", orgnr)


def looks_like_orgnr(text: str) -> bool:
    return validate_orgnr(text)


def fetch_by_orgnr(client: httpx.Client, orgnr: str) -> BrregEntity | None:
    orgnr = normalize_orgnr(orgnr)
    url = f"{BRREG_ENHET_URL}/{orgnr}"
    resp = fetch(client, url, headers={"Accept": BRREG_ENHET_ACCEPT})
    if resp.status_code == 404:
        return None
    return BrregEntity.from_api(resp.json())


def search_by_name(client: httpx.Client, name: str, size: int = 20) -> list[BrregEntity]:
    resp = fetch(
        client,
        BRREG_ENHET_URL,
        headers={"Accept": BRREG_ENHET_ACCEPT},
        params={"navn": name, "size": size},
    )
    data = resp.json()
    embedded = data.get("_embedded") or {}
    enheter = embedded.get("enheter") or []
    return [BrregEntity.from_api(e) for e in enheter]


def resolve_company(
    client: httpx.Client,
    company_name: str,
    orgnr: str | None = None,
    log: LogCallback | None = None,
) -> tuple[BrregEntity | None, list[BrregEntity]]:
    """Return (selected_entity, candidates_for_disambiguation)."""

    def _log(msg: str) -> None:
        if log:
            log(msg)

    query = (orgnr or "").strip() or company_name.strip()
    if not orgnr and looks_like_orgnr(company_name):
        orgnr = company_name

    if orgnr:
        if not validate_orgnr(orgnr):
            _log("Invalid organisation number (must be 9 digits).")
            return None, []
        _log(f"Looking up organisation number {normalize_orgnr(orgnr)}...")
        try:
            entity = fetch_by_orgnr(client, orgnr)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                _log("No company found for that organisation number.")
                return None, []
            raise
        if entity:
            _log(f"Found: {entity.navn}")
            return entity, []
        _log("No company found for that organisation number.")
        return None, []

    _log(f"Searching Brreg for '{query}'...")
    candidates = search_by_name(client, query)
    if not candidates:
        _log("No matching companies in Brreg.")
        return None, []

    if len(candidates) == 1:
        _log(f"Found: {candidates[0].navn} ({candidates[0].organisasjonsnummer})")
        return candidates[0], []

    _log(f"Found {len(candidates)} matches — pick the legal entity, not a department.")
    return None, candidates
