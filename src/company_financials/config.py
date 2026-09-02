"""Application configuration."""

from __future__ import annotations

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)

BRREG_ENHET_URL = "https://data.brreg.no/enhetsregisteret/api/enheter"
BRREG_KONSERN_URL = "https://data.brreg.no/enhetsregisteret/api/konsernstruktur"
BRREG_REGNSKAP_URL = "https://data.brreg.no/regnskapsregisteret/regnskap"

BRREG_ENHET_ACCEPT = "application/vnd.brreg.enhetsregisteret.enhet.v2+json"
BRREG_ROLLER_ACCEPT = "application/vnd.brreg.enhetsregisteret.rolle.v1+json"
BRREG_JSON_ACCEPT = "application/json"

PROFF_BASE = "https://www.proff.no"
PROFF_SEARCH_URL = "https://www.proff.no/bransjesøk"

REQUEST_TIMEOUT = 30.0
BRREG_RATE_LIMIT_SECONDS = 0.35
PROFF_RATE_LIMIT_SECONDS = 1.2

SCHEMA_VERSION = "1.0"
MAX_FINANCIAL_YEARS = 5
DEFAULT_OUTPUT_DIR = ".local-output"

LISTED_ORG_FORMS = {"ASA", "SE", "SCE"}
