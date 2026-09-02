"""Streamlit GUI: search a Norwegian company and save a local snapshot."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

from company_financials.config import DEFAULT_OUTPUT_DIR
from company_financials.models import BrregEntity, CompanySnapshot
from company_financials.pipeline import extract_company
from company_financials.resolver import validate_orgnr
from company_financials.storage.local import financials_frame, load_index


def _open_folder(path: Path) -> None:
    path = path.resolve()
    if sys.platform == "win32":
        os.startfile(path)  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.run(["open", str(path)], check=False)
    else:
        subprocess.run(["xdg-open", str(path)], check=False)


def _candidate_label(entity: BrregEntity) -> str:
    form = ""
    if entity.organisasjonsform:
        form = entity.organisasjonsform.get("kode") or ""
    kommune = ""
    if entity.forretningsadresse:
        kommune = entity.forretningsadresse.get("kommune") or ""
    extra = " · ".join(p for p in (form, kommune) if p)
    suffix = f" — {extra}" if extra else ""
    return f"{entity.navn} ({entity.organisasjonsnummer}){suffix}"


def _init_state() -> None:
    defaults = {
        "log_lines": [],
        "candidates": [],
        "snapshot": None,
        "company_dir": None,
        "loaded_from_cache": False,
        "error": None,
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def _append_log(message: str) -> None:
    st.session_state.log_lines.append(message)


def _run_extract(
    name: str,
    orgnr: str | None,
    output: Path,
    refresh: bool,
    entity: BrregEntity | None = None,
) -> None:
    st.session_state.log_lines = []
    st.session_state.error = None
    st.session_state.snapshot = None
    st.session_state.company_dir = None
    result = extract_company(
        company_name=name,
        output_dir=output,
        orgnr=orgnr,
        entity=entity,
        refresh=refresh,
        log=_append_log,
    )
    if result.needs_disambiguation:
        st.session_state.candidates = result.candidates
        st.session_state.error = None
        return
    st.session_state.candidates = []
    if not result.success:
        st.session_state.error = "Could not extract this company. See the log."
        return
    st.session_state.snapshot = result.snapshot
    st.session_state.company_dir = str(result.company_dir) if result.company_dir else None
    st.session_state.loaded_from_cache = result.loaded_from_cache


def _show_snapshot(snapshot: CompanySnapshot, folder: str | None) -> None:
    ident = snapshot.identity
    st.success(f"Saved: **{ident.name}** (`{ident.orgnr}`)")
    if st.session_state.loaded_from_cache:
        st.info("Loaded from the local folder (already extracted). Tick Refresh to fetch again.")
    if folder:
        st.code(folder)
        if st.button("Open folder on this PC"):
            _open_folder(Path(folder))

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Legal form", ident.org_form_code or "n/a")
    c2.metric("Listed (heuristic)", "Yes" if ident.listed else "No")
    c3.metric("Employees", ident.employees if ident.employees is not None else "n/a")
    years = snapshot.coverage.company_years
    c4.metric("Company years", len(years))

    if ident.nace:
        st.caption("Industry: " + ", ".join(f"{n.code} {n.description}" for n in ident.nace))

    if snapshot.coverage.warnings:
        st.warning("\n".join(f"• {w}" for w in snapshot.coverage.warnings))

    fin = financials_frame(snapshot.financials)
    if not fin.empty:
        st.subheader("Financials (normalized full amounts)")
        st.caption(
            "These are full currency units after correcting Proff's published unit "
            "(often thousands). Open financials.csv in Excel if you prefer."
        )
        st.dataframe(fin, use_container_width=True, hide_index=True)

    ratio_rows = [r.model_dump() for r in snapshot.ratios if r.statement == "company"]
    if ratio_rows:
        st.subheader("Margins and ratios (company accounts)")
        rdf = pd.DataFrame(ratio_rows)
        percent_cols = ["ebit_margin", "net_margin", "ebitda_margin", "equity_ratio", "roe"]
        for col in percent_cols:
            if col in rdf.columns:
                rdf[col] = rdf[col].map(lambda x: None if x is None else round(x * 100, 1))
        st.dataframe(rdf, use_container_width=True, hide_index=True)
        st.caption("Margin and ratio columns (except current_ratio) are in percent.")

    if snapshot.leadership:
        st.subheader("Leadership")
        st.dataframe(
            pd.DataFrame(
                [{"role": r.role, "name": r.name, "elected_by": r.elected_by} for r in snapshot.leadership]
            ),
            use_container_width=True,
            hide_index=True,
        )

    if snapshot.shareholders:
        st.subheader("Shareholders (from Proff)")
        st.dataframe(
            pd.DataFrame([s.model_dump() for s in snapshot.shareholders]),
            use_container_width=True,
            hide_index=True,
        )

    if snapshot.coverage.mismatches:
        st.subheader("Brreg vs Proff")
        st.dataframe(
            pd.DataFrame([m.model_dump() for m in snapshot.coverage.mismatches]),
            use_container_width=True,
            hide_index=True,
        )


def main() -> None:
    st.set_page_config(page_title="Norwegian company financials", layout="wide")
    _init_state()

    st.title("Norwegian company financials")
    st.caption(
        "Local V1: type a company name, pick the legal entity, and save structured data "
        "on this PC. Norway only. See VISION.md for the later website integration."
    )

    name = st.text_input("Company name", placeholder="e.g. Equinor ASA")
    orgnr = st.text_input("Organisation number (optional)", placeholder="9 digits")
    output = st.text_input("Output folder", value=DEFAULT_OUTPUT_DIR)
    refresh = st.checkbox("Refresh even if this company was extracted before", value=False)

    extract_clicked = st.button("Extract", type="primary")

    if extract_clicked:
        if not name.strip() and not orgnr.strip():
            st.error("Enter a company name or an organisation number.")
        elif orgnr.strip() and not validate_orgnr(orgnr):
            st.error("Organisation number must be 9 digits.")
        else:
            with st.spinner("Talking to Brreg and Proff (this can take about 10 seconds)..."):
                _run_extract(
                    name.strip() or orgnr.strip(),
                    orgnr.strip() or None,
                    Path(output),
                    refresh,
                )

    if st.session_state.candidates:
        st.subheader("Several companies matched")
        st.write("Pick the **legal entity**, not a department (`avd`).")
        options = st.session_state.candidates
        by_orgnr = {c.organisasjonsnummer: c for c in options}
        choice = st.radio(
            "Matches from Brreg",
            options=list(by_orgnr.keys()),
            format_func=lambda org: _candidate_label(by_orgnr[org]),
        )
        if st.button("Extract selected company"):
            selected = by_orgnr[choice]
            with st.spinner("Extracting the company you picked..."):
                _run_extract(
                    selected.navn,
                    selected.organisasjonsnummer,
                    Path(output),
                    refresh,
                    entity=selected,
                )

    if st.session_state.error:
        st.error(st.session_state.error)

    if st.session_state.snapshot is not None:
        _show_snapshot(st.session_state.snapshot, st.session_state.company_dir)

    if st.session_state.log_lines:
        with st.expander("Log", expanded=not st.session_state.snapshot):
            st.text("\n".join(st.session_state.log_lines))

    index = load_index(Path(output) if output else Path(DEFAULT_OUTPUT_DIR))
    companies = index.get("companies") or []
    if companies:
        st.divider()
        st.subheader("Already on this PC")
        st.dataframe(pd.DataFrame(companies), use_container_width=True, hide_index=True)


if __name__ == "__main__":
    main()
