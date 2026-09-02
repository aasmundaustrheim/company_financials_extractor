from company_financials.models import FinancialYear, MoneyLine
from company_financials.ratios import compute_ratios
from company_financials.sources.proff import accounts_to_years, detect_unit, parse_shareholders, rescale_years


def test_ratios_basic():
    year = FinancialYear(
        year=2024,
        currency="NOK",
        unit=1,
        revenue=MoneyLine.from_raw(100, 1, "NOK"),
        operating_profit=MoneyLine.from_raw(20, 1, "NOK"),
        net_profit=MoneyLine.from_raw(10, 1, "NOK"),
        ebitda=MoneyLine.from_raw(25, 1, "NOK"),
        equity=MoneyLine.from_raw(50, 1, "NOK"),
        total_assets=MoneyLine.from_raw(200, 1, "NOK"),
        current_assets=MoneyLine.from_raw(40, 1, "NOK"),
        current_liabilities=MoneyLine.from_raw(20, 1, "NOK"),
    )
    ratio = compute_ratios([year])[0]
    assert ratio.ebit_margin == 0.2
    assert ratio.net_margin == 0.1
    assert ratio.equity_ratio == 0.25
    assert ratio.roe == 0.2
    assert ratio.current_ratio == 2.0


def test_accounts_to_years_maps_codes():
    periods = [
        {
            "year": "2024",
            "periodStart": "2024-01-01",
            "periodEnd": "2024-12-31",
            "currency": "NOK",
            "accounts": [
                {"code": "SDI", "amount": "10000"},
                {"code": "DR", "amount": 1500},
                {"code": "AARS", "amount": 1000},
                {"code": "SED", "amount": 8000},
                {"code": "SEK", "amount": 5000},
                {"code": "SG", "amount": 3000},
                {"code": "ANT", "amount": 12},
            ],
        }
    ]
    years = accounts_to_years(periods, statement="company", unit=1000, fallback_currency="NOK")
    assert len(years) == 1
    assert years[0].revenue is not None
    assert years[0].revenue.normalized == 10_000_000
    assert years[0].employees == 12
    assert years[0].net_profit.normalized == 1_000_000


def test_detect_unit_thousands():
    years = accounts_to_years(
        [
            {
                "year": "2024",
                "currency": "NOK",
                "accounts": [{"code": "SDI", "amount": 10000}],
            }
        ],
        statement="company",
        unit=1000,
        fallback_currency="NOK",
    )
    unit, note = detect_unit(years, [{"year": 2024, "revenue": 10_000_000}])
    assert unit == 1000
    assert note is None


def test_detect_unit_already_full():
    years = accounts_to_years(
        [
            {
                "year": "2024",
                "currency": "NOK",
                "accounts": [{"code": "SDI", "amount": 10_000_000}],
            }
        ],
        statement="company",
        unit=1000,
        fallback_currency="NOK",
    )
    unit, note = detect_unit(years, [{"year": 2024, "revenue": 10_000_000}])
    assert unit == 1
    assert note is not None
    rescaled = rescale_years(years, unit)
    assert rescaled[0].revenue.normalized == 10_000_000


def test_parse_shareholders():
    company = {
        "shareholders": [
            {"name": "Holding AS", "share": "67", "numberOfShares": 100, "companyId": "912660680"},
            {"name": "Øvrige", "share": "33", "companyId": None},
        ]
    }
    rows = parse_shareholders(company)
    assert rows[0].share_percent == 67
    assert rows[0].organisation_number == "912660680"
    assert len(rows) == 2
