"""Command-line entry: extract one Norwegian company to a local folder."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from company_financials.config import DEFAULT_OUTPUT_DIR
from company_financials.pipeline import extract_company
from company_financials.resolver import validate_orgnr


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Extract structured Norwegian company financials into a local folder."
    )
    parser.add_argument("--company", required=True, help="Company name (or 9-digit orgnr)")
    parser.add_argument("--orgnr", help="9-digit organisation number")
    parser.add_argument(
        "--output",
        default=DEFAULT_OUTPUT_DIR,
        help=f"Output folder (default: {DEFAULT_OUTPUT_DIR})",
    )
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Fetch again even if this orgnr already has a snapshot",
    )
    args = parser.parse_args(argv)

    orgnr = args.orgnr
    if orgnr and not validate_orgnr(orgnr):
        print("Organisation number must be 9 digits.", file=sys.stderr)
        return 2

    def log(msg: str) -> None:
        print(msg)

    result = extract_company(
        company_name=args.company,
        output_dir=Path(args.output),
        orgnr=orgnr,
        refresh=args.refresh,
        log=log,
    )
    if result.needs_disambiguation:
        print("Several companies matched. Re-run with --orgnr of the legal entity:")
        for cand in result.candidates:
            form = (cand.organisasjonsform or {}).get("kode", "")
            kommune = (cand.forretningsadresse or {}).get("kommune", "")
            print(f"  {cand.organisasjonsnummer}  {cand.navn}  {form}  {kommune}")
        return 3
    if not result.success:
        print("Extraction failed. See messages above.", file=sys.stderr)
        return 1
    print(f"Done. Folder: {result.company_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
