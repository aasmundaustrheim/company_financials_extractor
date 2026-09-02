"""Canonical snapshot models. This JSON is what a later AI researcher should consume."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from pydantic import BaseModel, Field

from company_financials.config import SCHEMA_VERSION


LogCallback = Callable[[str], None]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class NaceCode(BaseModel):
    code: str | None = None
    description: str | None = None


class Address(BaseModel):
    street: list[str] = Field(default_factory=list)
    postal_code: str | None = None
    city: str | None = None
    municipality: str | None = None
    country: str | None = None


class RoleHolder(BaseModel):
    name: str
    role_code: str | None = None
    role: str
    birth_date: str | None = None
    organisation_number: str | None = None
    elected_by: str | None = None


class Shareholder(BaseModel):
    name: str
    share_percent: float | None = None
    number_of_shares: float | None = None
    organisation_number: str | None = None


class GroupLink(BaseModel):
    name: str | None = None
    organisation_number: str | None = None
    country: str | None = None
    relation: str | None = None


class Identity(BaseModel):
    orgnr: str
    name: str
    org_form_code: str | None = None
    org_form: str | None = None
    listed: bool = False
    employees: int | None = None
    website: str | None = None
    purpose: str | None = None
    nace: list[NaceCode] = Field(default_factory=list)
    address: Address | None = None
    founded: str | None = None
    last_accounts_year: str | None = None
    bankrupt: bool | None = None
    under_liquidation: bool | None = None
    in_group: bool | None = None


class MoneyLine(BaseModel):
    """One published number, plus a full-currency amount after unit correction."""

    raw: float
    unit: int = 1
    currency: str = "NOK"
    normalized: float

    @classmethod
    def from_raw(cls, raw: float | None, unit: int, currency: str) -> MoneyLine | None:
        if raw is None:
            return None
        return cls(raw=raw, unit=unit, currency=currency, normalized=raw * unit)


class FinancialYear(BaseModel):
    year: int
    period_start: str | None = None
    period_end: str | None = None
    currency: str = "NOK"
    unit: int = 1000
    statement: str = "company"  # company | group
    revenue: MoneyLine | None = None
    sales_revenue: MoneyLine | None = None
    operating_profit: MoneyLine | None = None
    profit_before_tax: MoneyLine | None = None
    net_profit: MoneyLine | None = None
    ebitda: MoneyLine | None = None
    total_assets: MoneyLine | None = None
    equity: MoneyLine | None = None
    total_debt: MoneyLine | None = None
    current_assets: MoneyLine | None = None
    current_liabilities: MoneyLine | None = None
    noncurrent_assets: MoneyLine | None = None
    noncurrent_liabilities: MoneyLine | None = None
    employees: int | None = None


class RatioYear(BaseModel):
    year: int
    statement: str = "company"
    ebit_margin: float | None = None
    net_margin: float | None = None
    ebitda_margin: float | None = None
    equity_ratio: float | None = None
    roe: float | None = None
    current_ratio: float | None = None


class Mismatch(BaseModel):
    year: int
    field: str
    brreg: float | None = None
    proff: float | None = None
    note: str


class Coverage(BaseModel):
    requested_years: int = 5
    company_years: list[int] = Field(default_factory=list)
    group_years: list[int] = Field(default_factory=list)
    missing_years: list[int] = Field(default_factory=list)
    proff_unit: int | None = None
    proff_url: str | None = None
    brreg_accounts_years: list[int] = Field(default_factory=list)
    mismatches: list[Mismatch] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class SourceRef(BaseModel):
    name: str
    url: str | None = None
    fetched_at: str | None = None


class CompanySnapshot(BaseModel):
    schema_version: str = SCHEMA_VERSION
    extracted_at: str = Field(default_factory=utc_now)
    identity: Identity
    leadership: list[RoleHolder] = Field(default_factory=list)
    shareholders: list[Shareholder] = Field(default_factory=list)
    group: list[GroupLink] = Field(default_factory=list)
    financials: list[FinancialYear] = Field(default_factory=list)
    ratios: list[RatioYear] = Field(default_factory=list)
    coverage: Coverage = Field(default_factory=Coverage)
    sources: list[SourceRef] = Field(default_factory=list)


class BrregEntity(BaseModel):
    organisasjonsnummer: str
    navn: str
    organisasjonsform: dict[str, Any] | None = None
    hjemmeside: str | None = None
    forretningsadresse: dict[str, Any] | None = None
    naeringskode1: dict[str, Any] | None = None
    naeringskode2: dict[str, Any] | None = None
    naeringskode3: dict[str, Any] | None = None
    antallAnsatte: int | None = None
    vedtektsfestetFormaal: list[str] | None = None
    stiftelsesdato: str | None = None
    sisteInnsendteAarsregnskap: str | None = None
    konkurs: bool | None = None
    underAvvikling: bool | None = None
    erIKonsern: bool | None = None
    raw: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> BrregEntity:
        return cls(
            organisasjonsnummer=str(data.get("organisasjonsnummer", "")),
            navn=str(data.get("navn", "")),
            organisasjonsform=data.get("organisasjonsform"),
            hjemmeside=data.get("hjemmeside"),
            forretningsadresse=data.get("forretningsadresse"),
            naeringskode1=data.get("naeringskode1"),
            naeringskode2=data.get("naeringskode2"),
            naeringskode3=data.get("naeringskode3"),
            antallAnsatte=data.get("antallAnsatte"),
            vedtektsfestetFormaal=data.get("vedtektsfestetFormaal"),
            stiftelsesdato=data.get("stiftelsesdato"),
            sisteInnsendteAarsregnskap=data.get("sisteInnsendteAarsregnskap"),
            konkurs=data.get("konkurs"),
            underAvvikling=data.get("underAvvikling"),
            erIKonsern=data.get("erIKonsern"),
            raw=data,
        )


class RunResult(BaseModel):
    success: bool
    snapshot: CompanySnapshot | None = None
    company_dir: Path | None = None
    messages: list[str] = Field(default_factory=list)
    needs_disambiguation: bool = False
    candidates: list[BrregEntity] = Field(default_factory=list)
    loaded_from_cache: bool = False
