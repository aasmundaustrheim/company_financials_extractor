"""Thin HTTP API so Base44 can call extract_company() without copying this repo."""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from company_financials.config import DEFAULT_OUTPUT_DIR
from company_financials.models import BrregEntity, CompanySnapshot
from company_financials.pipeline import extract_company
from company_financials.resolver import normalize_orgnr, validate_orgnr
from company_financials.storage.local import find_cached, load_snapshot

app = FastAPI(
    title="Company financials extractor",
    description=(
        "Extract structured Norwegian company financials. "
        "Value Beyond Wealth (Base44) should call POST /extract and GET /companies/{orgnr}."
    ),
    version="0.1.0",
)


class ExtractRequest(BaseModel):
    company: str = Field(..., description="Company name, or a 9-digit organisation number")
    orgnr: str | None = Field(None, description="9-digit organisation number, if already known")
    refresh: bool = Field(False, description="Fetch again even if a cached snapshot exists")


class Candidate(BaseModel):
    orgnr: str
    name: str
    org_form: str | None = None
    kommune: str | None = None


class ExtractResponse(BaseModel):
    success: bool
    snapshot: CompanySnapshot | None = None
    loaded_from_cache: bool = False
    needs_disambiguation: bool = False
    candidates: list[Candidate] = Field(default_factory=list)
    messages: list[str] = Field(default_factory=list)


class HealthResponse(BaseModel):
    status: str


def output_dir() -> Path:
    return Path(os.environ.get("COMPANY_FINANCIALS_OUTPUT_DIR") or DEFAULT_OUTPUT_DIR)


def require_api_key(x_api_key: str | None = Header(default=None, alias="X-API-Key")) -> None:
    expected = os.environ.get("COMPANY_FINANCIALS_API_KEY", "").strip()
    if not expected:
        return
    if not x_api_key or x_api_key != expected:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")


def _candidate(entity: BrregEntity) -> Candidate:
    form = None
    if entity.organisasjonsform:
        form = entity.organisasjonsform.get("kode") or entity.organisasjonsform.get("beskrivelse")
    kommune = None
    if entity.forretningsadresse:
        kommune = entity.forretningsadresse.get("kommune")
    return Candidate(
        orgnr=entity.organisasjonsnummer,
        name=entity.navn,
        org_form=str(form) if form else None,
        kommune=str(kommune) if kommune else None,
    )


@app.get("/health", response_model=HealthResponse, tags=["meta"])
def health() -> HealthResponse:
    return HealthResponse(status="ok")


@app.post(
    "/extract",
    response_model=ExtractResponse,
    tags=["companies"],
    dependencies=[Depends(require_api_key)],
)
def extract(body: ExtractRequest) -> ExtractResponse:
    if body.orgnr and not validate_orgnr(body.orgnr):
        raise HTTPException(status_code=400, detail="Organisation number must be 9 digits.")
    result = extract_company(
        company_name=body.company,
        output_dir=output_dir(),
        orgnr=body.orgnr,
        refresh=body.refresh,
    )
    if result.needs_disambiguation:
        return ExtractResponse(
            success=False,
            needs_disambiguation=True,
            candidates=[_candidate(c) for c in result.candidates],
            messages=result.messages,
        )
    return ExtractResponse(
        success=result.success,
        snapshot=result.snapshot,
        loaded_from_cache=result.loaded_from_cache,
        messages=result.messages,
    )


@app.get(
    "/companies/{orgnr}",
    response_model=ExtractResponse,
    tags=["companies"],
    dependencies=[Depends(require_api_key)],
)
def get_company(orgnr: str) -> ExtractResponse:
    if not validate_orgnr(orgnr):
        raise HTTPException(status_code=400, detail="Organisation number must be 9 digits.")
    orgnr = normalize_orgnr(orgnr)
    cached = find_cached(output_dir(), orgnr)
    if cached is None:
        raise HTTPException(status_code=404, detail="No cached snapshot for that organisation number.")
    snapshot = load_snapshot(cached)
    return ExtractResponse(
        success=True,
        snapshot=snapshot,
        loaded_from_cache=True,
        messages=[f"Loaded cached snapshot for {orgnr}"],
    )
