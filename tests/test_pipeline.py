import json

import httpx

from company_financials.pipeline import extract_company
from company_financials.sources.brreg import parse_roles, summarize_brreg_year


BRREG_ACCOUNT = {
    "regnskapstype": "SELSKAP",
    "valuta": "NOK",
    "regnskapsperiode": {"fraDato": "2024-01-01", "tilDato": "2024-12-31"},
    "resultatregnskapResultat": {
        "aarsresultat": 1_000_000,
        "ordinaertResultatFoerSkattekostnad": 1_200_000,
        "driftsresultat": {
            "driftsresultat": 1_500_000,
            "driftsinntekter": {"sumDriftsinntekter": 10_000_000},
        },
    },
    "egenkapitalGjeld": {
        "egenkapital": {"sumEgenkapital": 5_000_000},
        "gjeldOversikt": {
            "sumGjeld": 3_000_000,
            "kortsiktigGjeld": {"sumKortsiktigGjeld": 1_000_000},
        },
    },
    "eiendeler": {
        "sumEiendeler": 8_000_000,
        "omloepsmidler": {"sumOmloepsmidler": 2_000_000},
    },
}

PROFF_COMPANY = {
    "orgnr": "123456789",
    "name": "Test AS",
    "legalName": "Test AS",
    "companyId": "ABC123",
    "currency": "NOK",
    "companyType": {"code": "AS"},
    "companyAccounts": [
        {
            "year": "2024",
            "periodStart": "2024-01-01",
            "periodEnd": "2024-12-31",
            "currency": "NOK",
            "accounts": [
                {"code": "SDI", "amount": 10000},
                {"code": "DR", "amount": 1500},
                {"code": "ORS", "amount": 1200},
                {"code": "AARS", "amount": 1000},
                {"code": "SED", "amount": 8000},
                {"code": "SEK", "amount": 5000},
                {"code": "SG", "amount": 3000},
                {"code": "SOM", "amount": 2000},
                {"code": "SKG", "amount": 1000},
                {"code": "ANT", "amount": 9},
            ],
        },
        {
            "year": "2023",
            "periodStart": "2023-01-01",
            "periodEnd": "2023-12-31",
            "currency": "NOK",
            "accounts": [
                {"code": "SDI", "amount": 9000},
                {"code": "AARS", "amount": 800},
            ],
        },
    ],
    "corporateAccounts": [],
    "shareholders": [
        {"name": "Owner AS", "share": "100", "numberOfShares": 100, "companyId": "111111111"}
    ],
    "corporateStructure": {
        "parentCompanyOrganisationNumber": "111111111",
        "parentCompanyName": "Owner AS",
        "parentCompanyCountryCode": "NO",
    },
}


def _next_html(company: dict) -> str:
    payload = {"props": {"pageProps": {"company": company}}}
    return (
        "<html><head><title>Test AS</title></head><body>"
        '<a href="/selskap/test-as/-/-/123456789">Test AS</a>'
        f'<script id="__NEXT_DATA__" type="application/json">{json.dumps(payload)}</script>'
        "</body></html>"
    )


def test_summarize_brreg_year():
    summary = summarize_brreg_year(BRREG_ACCOUNT)
    assert summary["year"] == 2024
    assert summary["revenue"] == 10_000_000
    assert summary["operating_profit"] == 1_500_000
    assert summary["net_profit"] == 1_000_000


def test_parse_roles():
    payload = {
        "rollegrupper": [
            {
                "roller": [
                    {
                        "avregistrert": False,
                        "type": {"kode": "DAGL", "beskrivelse": "Daglig leder"},
                        "person": {
                            "fodselsdato": "1970-01-01",
                            "navn": {"fornavn": "Kari", "etternavn": "Nordmann"},
                        },
                    }
                ]
            }
        ]
    }
    roles = parse_roles(payload)
    assert roles[0].name == "Kari Nordmann"
    assert roles[0].role == "Daglig leder"


def test_extract_company_end_to_end(httpx_mock, tmp_path):
    html = _next_html(PROFF_COMPANY)

    def dispatch(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.endswith("/enheter/123456789"):
            return httpx.Response(
                200,
                json={
                    "organisasjonsnummer": "123456789",
                    "navn": "Test AS",
                    "organisasjonsform": {"kode": "AS", "beskrivelse": "Aksjeselskap"},
                    "antallAnsatte": 9,
                    "naeringskode1": {"kode": "62.010", "beskrivelse": "Programmering"},
                    "forretningsadresse": {
                        "adresse": ["Storgata 1"],
                        "postnummer": "0155",
                        "poststed": "OSLO",
                        "kommune": "OSLO",
                        "land": "Norge",
                    },
                },
            )
        if url.endswith("/enheter/123456789/roller"):
            return httpx.Response(
                200,
                json={
                    "rollegrupper": [
                        {
                            "roller": [
                                {
                                    "avregistrert": False,
                                    "type": {"kode": "DAGL", "beskrivelse": "Daglig leder"},
                                    "person": {
                                        "navn": {"fornavn": "Kari", "etternavn": "Nordmann"}
                                    },
                                }
                            ]
                        }
                    ]
                },
            )
        if "konsernstruktur/123456789" in url:
            return httpx.Response(404, json={"error": "not found"})
        if url.endswith("/regnskap/123456789"):
            return httpx.Response(
                200,
                json=[BRREG_ACCOUNT],
                headers={"content-type": "application/json"},
            )
        if "proff.no" in url and "bransje" in url:
            return httpx.Response(200, text=html)
        if "proff.no" in url:
            return httpx.Response(200, text=html)
        return httpx.Response(404, json={"error": url})

    httpx_mock.add_callback(dispatch, is_reusable=True)

    result = extract_company(
        "Test AS",
        output_dir=tmp_path,
        orgnr="123456789",
        refresh=True,
    )
    assert result.success, result.messages
    snap = result.snapshot
    assert snap is not None
    assert snap.identity.orgnr == "123456789"
    company_years = [y for y in snap.financials if y.statement == "company"]
    assert [y.year for y in company_years] == [2024, 2023]
    assert company_years[0].revenue is not None
    assert company_years[0].revenue.normalized == 10_000_000
    assert company_years[0].unit == 1000
    assert snap.shareholders[0].name == "Owner AS"
    assert snap.leadership[0].name == "Kari Nordmann"
    assert result.company_dir is not None
    assert (result.company_dir / "snapshot.json").exists()
    assert not snap.coverage.mismatches

    cached = extract_company(
        "Test AS",
        output_dir=tmp_path,
        orgnr="123456789",
        refresh=False,
    )
    assert cached.loaded_from_cache
