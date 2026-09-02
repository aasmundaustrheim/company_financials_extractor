import json

from company_financials.sources.proff import parse_next_data, pick_profile_href


def test_validate_and_normalize():
    from company_financials.resolver import normalize_orgnr, validate_orgnr

    assert validate_orgnr("123456789")
    assert validate_orgnr("123 456 789")
    assert not validate_orgnr("12345")
    assert normalize_orgnr("123 456 789") == "123456789"


def test_resolve_with_orgnr(httpx_mock):
    import httpx

    from company_financials.resolver import resolve_company

    httpx_mock.add_response(
        url="https://data.brreg.no/enhetsregisteret/api/enheter/923609016",
        json={
            "organisasjonsnummer": "923609016",
            "navn": "Equinor ASA",
            "organisasjonsform": {"kode": "ASA"},
        },
    )
    with httpx.Client() as client:
        entity, candidates = resolve_company(client, "Equinor", orgnr="923609016")
    assert entity is not None
    assert entity.navn == "Equinor ASA"
    assert candidates == []


def test_search_multiple_candidates(httpx_mock):
    import httpx

    from company_financials.resolver import search_by_name

    httpx_mock.add_response(
        url="https://data.brreg.no/enhetsregisteret/api/enheter?navn=Test&size=20",
        json={
            "_embedded": {
                "enheter": [
                    {"organisasjonsnummer": "111111111", "navn": "Test AS"},
                    {"organisasjonsnummer": "222222222", "navn": "Test ASA"},
                ]
            }
        },
    )
    with httpx.Client() as client:
        results = search_by_name(client, "Test")
    assert len(results) == 2


def test_pick_profile_skips_departments():
    html = """
    <a href="/selskap/test-as-avd-oslo/oslo/handel/AAA">avd</a>
    <a href="/selskap/test-as/-/-/123456789">legal</a>
    <a href="/selskap/test-as/oslo/handel/BBB">also legal</a>
    """
    href = pick_profile_href(html, "123456789")
    assert href.endswith("123456789")


def test_parse_next_data():
    payload = {"props": {"pageProps": {"company": {"orgnr": "1"}}}}
    html = f'<script id="__NEXT_DATA__" type="application/json">{json.dumps(payload)}</script>'
    data = parse_next_data(html)
    assert data["props"]["pageProps"]["company"]["orgnr"] == "1"
