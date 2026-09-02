"""HTTP API tests. Gathering is mocked — this file only checks the wrapper."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from company_financials.api import app
from company_financials.models import BrregEntity, CompanySnapshot, Identity, RunResult


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("COMPANY_FINANCIALS_API_KEY", "test-key")
    monkeypatch.setenv("COMPANY_FINANCIALS_OUTPUT_DIR", str(tmp_path))
    return TestClient(app)


def _snapshot() -> CompanySnapshot:
    return CompanySnapshot(
        identity=Identity(orgnr="123456789", name="Test AS", org_form_code="AS")
    )


def test_health_is_public(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_openapi_lists_extract_and_lookup(client):
    spec = client.get("/openapi.json").json()
    assert "/extract" in spec["paths"]
    assert "/companies/{orgnr}" in spec["paths"]
    assert "/health" in spec["paths"]


def test_extract_rejects_missing_api_key(client):
    response = client.post("/extract", json={"company": "Test AS"})
    assert response.status_code == 401


def test_extract_rejects_wrong_api_key(client):
    response = client.post(
        "/extract",
        json={"company": "Test AS"},
        headers={"X-API-Key": "wrong"},
    )
    assert response.status_code == 401


def test_extract_success(client, monkeypatch):
    snap = _snapshot()

    def fake_extract(**kwargs):
        return RunResult(success=True, snapshot=snap, messages=["ok"], loaded_from_cache=False)

    monkeypatch.setattr("company_financials.api.extract_company", fake_extract)
    response = client.post(
        "/extract",
        json={"company": "Test AS", "orgnr": "123456789"},
        headers={"X-API-Key": "test-key"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["snapshot"]["identity"]["orgnr"] == "123456789"
    assert "company_dir" not in body


def test_extract_disambiguation(client, monkeypatch):
    def fake_extract(**kwargs):
        return RunResult(
            success=False,
            needs_disambiguation=True,
            candidates=[
                BrregEntity.from_api(
                    {
                        "organisasjonsnummer": "123456789",
                        "navn": "Test AS",
                        "organisasjonsform": {"kode": "AS"},
                        "forretningsadresse": {"kommune": "OSLO"},
                    }
                )
            ],
            messages=["several matches"],
        )

    monkeypatch.setattr("company_financials.api.extract_company", fake_extract)
    response = client.post(
        "/extract",
        json={"company": "Test"},
        headers={"X-API-Key": "test-key"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["needs_disambiguation"] is True
    assert body["candidates"][0]["orgnr"] == "123456789"
    assert body["candidates"][0]["kommune"] == "OSLO"
    assert body["snapshot"] is None


def test_extract_rejects_bad_orgnr(client):
    response = client.post(
        "/extract",
        json={"company": "Test", "orgnr": "12"},
        headers={"X-API-Key": "test-key"},
    )
    assert response.status_code == 400


def test_get_company_cache_hit(client, tmp_path):
    from company_financials.storage.local import write_snapshot

    write_snapshot(tmp_path, _snapshot(), {})
    response = client.get("/companies/123456789", headers={"X-API-Key": "test-key"})
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["loaded_from_cache"] is True
    assert body["snapshot"]["identity"]["name"] == "Test AS"


def test_get_company_cache_miss(client):
    response = client.get("/companies/123456789", headers={"X-API-Key": "test-key"})
    assert response.status_code == 404
