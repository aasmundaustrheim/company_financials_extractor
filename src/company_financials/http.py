"""HTTP helpers with per-host rate limiting."""

from __future__ import annotations

import os
import time
from urllib.parse import urlparse

import httpx
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from company_financials.config import (
    BRREG_RATE_LIMIT_SECONDS,
    PROFF_RATE_LIMIT_SECONDS,
    REQUEST_TIMEOUT,
    USER_AGENT,
)

_last_request: dict[str, float] = {}


def _host(url: str) -> str:
    return urlparse(url).netloc.lower()


def _delay_for(url: str) -> float:
    host = _host(url)
    if "proff.no" in host:
        return PROFF_RATE_LIMIT_SECONDS
    if "brreg.no" in host:
        return BRREG_RATE_LIMIT_SECONDS
    return 0.25


def rate_limit(url: str) -> None:
    if os.environ.get("COMPANY_FINANCIALS_NO_SLEEP") == "1":
        return
    host = _host(url)
    wait = _delay_for(url)
    now = time.monotonic()
    last = _last_request.get(host, 0.0)
    elapsed = now - last
    if elapsed < wait:
        time.sleep(wait - elapsed)
    _last_request[host] = time.monotonic()


def create_client() -> httpx.Client:
    return httpx.Client(
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "nb-NO,nb;q=0.9,en-US;q=0.8,en;q=0.7",
        },
        timeout=REQUEST_TIMEOUT,
        follow_redirects=True,
    )


def _should_retry(exc: BaseException) -> bool:
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code >= 500
    return isinstance(exc, (httpx.TimeoutException, httpx.TransportError))


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=8),
    retry=retry_if_exception(_should_retry),
    reraise=True,
)
def fetch(
    client: httpx.Client,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    params: dict[str, str | int] | None = None,
) -> httpx.Response:
    rate_limit(url)
    resp = client.get(url, headers=headers, params=params)
    resp.raise_for_status()
    return resp
