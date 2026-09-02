"""Margins and ratios from normalized (full-currency) amounts."""

from __future__ import annotations

from company_financials.models import FinancialYear, RatioYear


def _pct(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator is None or denominator == 0:
        return None
    return round(numerator / denominator, 6)


def _ratio(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator is None or denominator == 0:
        return None
    return round(numerator / denominator, 4)


def _amt(line: object | None) -> float | None:
    if line is None:
        return None
    return getattr(line, "normalized", None)


def ratios_for_year(year: FinancialYear) -> RatioYear:
    revenue = _amt(year.revenue)
    ebit = _amt(year.operating_profit)
    net = _amt(year.net_profit)
    ebitda = _amt(year.ebitda)
    equity = _amt(year.equity)
    assets = _amt(year.total_assets)
    current_assets = _amt(year.current_assets)
    current_liabilities = _amt(year.current_liabilities)
    return RatioYear(
        year=year.year,
        statement=year.statement,
        ebit_margin=_pct(ebit, revenue),
        net_margin=_pct(net, revenue),
        ebitda_margin=_pct(ebitda, revenue),
        equity_ratio=_pct(equity, assets),
        roe=_pct(net, equity),
        current_ratio=_ratio(current_assets, current_liabilities),
    )


def compute_ratios(years: list[FinancialYear]) -> list[RatioYear]:
    return [ratios_for_year(y) for y in years]
