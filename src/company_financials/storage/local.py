"""Write snapshot folders and a local orgnr index."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from company_financials.models import CompanySnapshot, FinancialYear, MoneyLine


def slugify(name: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9æøåÆØÅ]+", "-", name.lower())
    slug = slug.strip("-")
    return slug[:60] or "company"


def company_dir(output_root: Path, name: str, orgnr: str) -> Path:
    return output_root / f"{slugify(name)}_{orgnr}"


def index_path(output_root: Path) -> Path:
    return output_root / "index.json"


def load_index(output_root: Path) -> dict:
    path = index_path(output_root)
    if not path.exists():
        return {"companies": []}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"companies": []}


def find_cached(output_root: Path, orgnr: str) -> Path | None:
    idx = load_index(output_root)
    for row in idx.get("companies") or []:
        if str(row.get("orgnr")) == orgnr:
            raw = row.get("folder") or ""
            folder = Path(raw) if Path(raw).is_absolute() else output_root / raw
            if (folder / "snapshot.json").exists():
                return folder
    if output_root.exists():
        for child in output_root.iterdir():
            if child.is_dir() and child.name.endswith(f"_{orgnr}") and (child / "snapshot.json").exists():
                return child
    return None


def load_snapshot(folder: Path) -> CompanySnapshot:
    data = json.loads((folder / "snapshot.json").read_text(encoding="utf-8"))
    return CompanySnapshot.model_validate(data)


def _money(line: MoneyLine | None) -> float | None:
    return None if line is None else line.normalized


def financials_frame(years: list[FinancialYear]) -> pd.DataFrame:
    rows = []
    for y in years:
        rows.append(
            {
                "statement": y.statement,
                "year": y.year,
                "currency": y.currency,
                "unit_published": y.unit,
                "revenue": _money(y.revenue),
                "operating_profit": _money(y.operating_profit),
                "profit_before_tax": _money(y.profit_before_tax),
                "net_profit": _money(y.net_profit),
                "ebitda": _money(y.ebitda),
                "total_assets": _money(y.total_assets),
                "equity": _money(y.equity),
                "total_debt": _money(y.total_debt),
                "current_assets": _money(y.current_assets),
                "current_liabilities": _money(y.current_liabilities),
                "employees": y.employees,
            }
        )
    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.sort_values(["statement", "year"], ascending=[True, False])
    return df


def _fmt_money(line: MoneyLine | None) -> str:
    if line is None:
        return "n/a"
    return f"{line.normalized:,.0f} {line.currency}".replace(",", " ")


def render_snapshot_md(snapshot: CompanySnapshot) -> str:
    ident = snapshot.identity
    nace = ", ".join(f"{n.code} {n.description}".strip() for n in ident.nace) or "n/a"
    lines = [
        f"# {ident.name}",
        "",
        f"- Organisation number: `{ident.orgnr}`",
        f"- Legal form: {ident.org_form or ident.org_form_code or 'n/a'}",
        f"- Listed (heuristic): {'yes' if ident.listed else 'no'}",
        f"- Employees (Brreg): {ident.employees if ident.employees is not None else 'n/a'}",
        f"- Industry: {nace}",
        f"- Website: {ident.website or 'n/a'}",
        f"- Extracted at: {snapshot.extracted_at}",
        "",
        "## Financials (normalized full amounts)",
        "",
    ]
    for y in snapshot.financials:
        if y.statement != "company":
            continue
        lines.extend(
            [
                f"### {y.year} ({y.currency}, published unit ×{y.unit})",
                f"- Revenue: {_fmt_money(y.revenue)}",
                f"- Operating profit: {_fmt_money(y.operating_profit)}",
                f"- Profit before tax: {_fmt_money(y.profit_before_tax)}",
                f"- Net profit: {_fmt_money(y.net_profit)}",
                f"- Equity: {_fmt_money(y.equity)}",
                f"- Total assets: {_fmt_money(y.total_assets)}",
                "",
            ]
        )
    lines.extend(["## Leadership", ""])
    for role in snapshot.leadership[:30]:
        lines.append(f"- {role.role}: {role.name}")
    if not snapshot.leadership:
        lines.append("- (none)")
    lines.extend(["", "## Shareholders", ""])
    for sh in snapshot.shareholders:
        pct = f"{sh.share_percent}%" if sh.share_percent is not None else "n/a"
        lines.append(f"- {sh.name}: {pct}")
    if not snapshot.shareholders:
        lines.append("- (none on Proff page)")
    lines.append("")
    lines.append("_Generated for local quality checking. See VISION.md for the later Base44 path._")
    return "\n".join(lines)


def render_quality_md(snapshot: CompanySnapshot) -> str:
    cov = snapshot.coverage
    lines = [
        "# Quality notes",
        "",
        f"- Company years: {cov.company_years or 'none'}",
        f"- Group years: {cov.group_years or 'none'}",
        f"- Missing of last 5 calendar years: {cov.missing_years or 'none'}",
        f"- Proff published unit: {cov.proff_unit}",
        f"- Proff URL: {cov.proff_url or 'n/a'}",
        f"- Brreg account years: {cov.brreg_accounts_years or 'none'}",
        "",
        "## Warnings",
        "",
    ]
    for w in cov.warnings:
        lines.append(f"- {w}")
    if not cov.warnings:
        lines.append("- none")
    lines.extend(["", "## Brreg vs Proff (same year, normalized)", ""])
    for m in cov.mismatches:
        lines.append(
            f"- {m.year} {m.field}: Brreg={m.brreg} Proff={m.proff} ({m.note})"
        )
    if not cov.mismatches:
        lines.append("- no mismatches flagged")
    lines.extend(
        [
            "",
            "Proff often publishes amounts in thousands. Normalized values are `raw × unit`.",
            "Last-year Brreg figures are the official cross-check when both sources have that year.",
        ]
    )
    return "\n".join(lines)


def write_snapshot(
    output_root: Path,
    snapshot: CompanySnapshot,
    raw_sources: dict[str, object],
) -> Path:
    output_root.mkdir(parents=True, exist_ok=True)
    folder = company_dir(output_root, snapshot.identity.name, snapshot.identity.orgnr)
    folder.mkdir(parents=True, exist_ok=True)
    sources_dir = folder / "sources"
    sources_dir.mkdir(exist_ok=True)

    (folder / "snapshot.json").write_text(
        snapshot.model_dump_json(indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    df = financials_frame(snapshot.financials)
    df.to_csv(folder / "financials.csv", index=False, encoding="utf-8-sig")

    (folder / "snapshot.md").write_text(render_snapshot_md(snapshot), encoding="utf-8")
    (folder / "quality.md").write_text(render_quality_md(snapshot), encoding="utf-8")

    written = [
        "snapshot.json",
        "financials.csv",
        "snapshot.md",
        "quality.md",
        "manifest.json",
    ]
    for name, payload in raw_sources.items():
        safe = re.sub(r"[^a-zA-Z0-9._-]+", "_", name)
        dest = sources_dir / safe
        if isinstance(payload, (dict, list)):
            dest = dest.with_suffix(".json")
            dest.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        else:
            dest = dest.with_suffix(".txt")
            dest.write_text(str(payload), encoding="utf-8")
        written.append(f"sources/{dest.name}")

    manifest = {
        "orgnr": snapshot.identity.orgnr,
        "name": snapshot.identity.name,
        "extracted_at": snapshot.extracted_at,
        "schema_version": snapshot.schema_version,
        "files": written,
        "folder": folder.name,
    }
    (folder / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    idx = load_index(output_root)
    companies = [
        c for c in idx.get("companies") or [] if str(c.get("orgnr")) != snapshot.identity.orgnr
    ]
    companies.append(
        {
            "orgnr": snapshot.identity.orgnr,
            "name": snapshot.identity.name,
            "extracted_at": snapshot.extracted_at,
            "folder": folder.name,
            "listed": snapshot.identity.listed,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
    )
    companies.sort(key=lambda r: r.get("name") or "")
    index_path(output_root).write_text(
        json.dumps({"companies": companies}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return folder
