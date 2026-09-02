"""Brreg open-data clients (identity, roles, group tree, last-year accounts)."""

from __future__ import annotations

from typing import Any

import httpx

from company_financials.config import (
    BRREG_ENHET_URL,
    BRREG_JSON_ACCEPT,
    BRREG_KONSERN_URL,
    BRREG_REGNSKAP_URL,
    BRREG_ROLLER_ACCEPT,
)
from company_financials.http import fetch, rate_limit
from company_financials.models import GroupLink, LogCallback, RoleHolder


def _person_name(person: dict[str, Any] | None) -> str:
    if not person:
        return ""
    navn = person.get("navn") or {}
    parts = [
        navn.get("fornavn") or "",
        navn.get("mellomnavn") or "",
        navn.get("etternavn") or "",
    ]
    return " ".join(p for p in parts if p).strip()


def parse_roles(payload: dict[str, Any]) -> list[RoleHolder]:
    holders: list[RoleHolder] = []
    for group in payload.get("rollegrupper") or []:
        for rolle in group.get("roller") or []:
            if rolle.get("avregistrert"):
                continue
            rtype = rolle.get("type") or {}
            person = rolle.get("person")
            enhet = rolle.get("enhet") or {}
            elected = (rolle.get("valgtAv") or {}).get("beskrivelse")
            name = _person_name(person)
            orgnr = None
            if not name and enhet:
                name = str(enhet.get("navn") or "")
                orgnr = str(enhet.get("organisasjonsnummer") or "") or None
            if not name:
                continue
            holders.append(
                RoleHolder(
                    name=name,
                    role_code=rtype.get("kode"),
                    role=str(rtype.get("beskrivelse") or rtype.get("kode") or "Role"),
                    birth_date=(person or {}).get("fodselsdato"),
                    organisation_number=orgnr,
                    elected_by=elected,
                )
            )
    return holders


def fetch_roles(
    client: httpx.Client,
    orgnr: str,
    log: LogCallback | None = None,
) -> tuple[list[RoleHolder], dict[str, Any] | None]:
    url = f"{BRREG_ENHET_URL}/{orgnr}/roller"
    try:
        resp = fetch(client, url, headers={"Accept": BRREG_ROLLER_ACCEPT})
    except httpx.HTTPStatusError as exc:
        if log:
            log(f"Brreg roles not available ({exc.response.status_code}).")
        return [], None
    data = resp.json()
    holders = parse_roles(data)
    if log:
        log(f"Brreg roles: {len(holders)} people/entities.")
    return holders, data


def _walk_group(node: Any, relation: str, out: list[GroupLink], depth: int = 0) -> None:
    if depth > 8 or not isinstance(node, dict):
        return
    orgnr = node.get("organisasjonsnummer") or node.get("orgnr")
    name = node.get("navn") or node.get("name")
    if orgnr or name:
        out.append(
            GroupLink(
                name=str(name) if name else None,
                organisation_number=str(orgnr) if orgnr else None,
                country=node.get("landkode") or node.get("land"),
                relation=relation,
            )
        )
    for key, child_rel in (
        ("overordnet", "parent"),
        ("morselskap", "parent"),
        ("parent", "parent"),
        ("underenheter", "subsidiary"),
        ("datterselskaper", "subsidiary"),
        ("barn", "subsidiary"),
        ("children", "subsidiary"),
    ):
        child = node.get(key)
        if isinstance(child, list):
            for item in child:
                _walk_group(item, child_rel, out, depth + 1)
        elif isinstance(child, dict):
            _walk_group(child, child_rel, out, depth + 1)


def fetch_group(
    client: httpx.Client,
    orgnr: str,
    log: LogCallback | None = None,
) -> tuple[list[GroupLink], dict[str, Any] | None]:
    url = f"{BRREG_KONSERN_URL}/{orgnr}"
    try:
        resp = fetch(client, url, headers={"Accept": BRREG_JSON_ACCEPT})
    except httpx.HTTPStatusError as exc:
        if log and exc.response.status_code != 404:
            log(f"Brreg group structure not available ({exc.response.status_code}).")
        return [], None
    data = resp.json()
    links: list[GroupLink] = []
    _walk_group(data, "self", links)
    links = [g for g in links if g.relation != "self"]
    if log:
        log(f"Brreg group links: {len(links)}.")
    return links, data


def _as_records(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    if isinstance(data, dict):
        if "regnskapsperiode" in data or "resultatregnskapResultat" in data:
            return [data]
        for key in ("regnskap", "items", "_embedded"):
            inner = data.get(key)
            if isinstance(inner, list):
                return [x for x in inner if isinstance(x, dict)]
    return []


def nested_number(obj: Any, *path: str) -> float | None:
    cur: Any = obj
    for key in path:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(key)
    if isinstance(cur, (int, float)):
        return float(cur)
    return None


def _numeric(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, dict):
        for key in ("driftsresultat", "sum", "belop", "amount"):
            inner = value.get(key)
            if isinstance(inner, (int, float)):
                return float(inner)
    return None


def summarize_brreg_year(record: dict[str, Any]) -> dict[str, Any]:
    period = record.get("regnskapsperiode") or {}
    end = str(period.get("tilDato") or "")
    year = int(end[:4]) if end[:4].isdigit() else None
    resultat = record.get("resultatregnskapResultat") or {}
    drifts = resultat.get("driftsresultat") or {}
    if not isinstance(drifts, dict):
        drifts = {}
    egen = record.get("egenkapitalGjeld") or {}
    eiendeler = record.get("eiendeler") or {}
    return {
        "year": year,
        "currency": record.get("valuta") or "NOK",
        "revenue": nested_number(drifts, "driftsinntekter", "sumDriftsinntekter"),
        "operating_profit": _numeric((resultat.get("driftsresultat") or {}).get("driftsresultat"))
        if isinstance(resultat.get("driftsresultat"), dict)
        else _numeric(resultat.get("driftsresultat")),
        "profit_before_tax": nested_number(resultat, "ordinaertResultatFoerSkattekostnad"),
        "net_profit": nested_number(resultat, "aarsresultat"),
        "total_assets": nested_number(eiendeler, "sumEiendeler"),
        "equity": nested_number(egen, "egenkapital", "sumEgenkapital"),
        "total_debt": nested_number(egen, "gjeldOversikt", "sumGjeld"),
        "current_assets": nested_number(eiendeler, "omloepsmidler", "sumOmloepsmidler"),
        "current_liabilities": nested_number(
            egen, "gjeldOversikt", "kortsiktigGjeld", "sumKortsiktigGjeld"
        ),
        "statement": str(record.get("regnskapstype") or "SELSKAP").lower(),
    }


def fetch_accounts(
    client: httpx.Client,
    orgnr: str,
    log: LogCallback | None = None,
) -> tuple[list[dict[str, Any]], Any]:
    url = f"{BRREG_REGNSKAP_URL}/{orgnr}"
    try:
        rate_limit(url)
        resp = client.get(url, headers={"Accept": BRREG_JSON_ACCEPT})
        if resp.status_code == 404:
            if log:
                log("No Brreg accounts filed for this entity.")
            return [], None
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        if log:
            log(f"Brreg accounts request failed: {exc}")
        return [], None

    ctype = (resp.headers.get("content-type") or "").lower()
    if "json" in ctype:
        data = resp.json()
    else:
        if log:
            log("Brreg accounts came back as non-JSON; saved raw only.")
        return [], {"_raw_text": resp.text[:200000]}

    records = _as_records(data)
    summaries = [summarize_brreg_year(r) for r in records]
    summaries = [s for s in summaries if s.get("year")]
    if log:
        years = [s["year"] for s in summaries]
        log(f"Brreg accounts years: {years or 'none'}.")
    return summaries, data
