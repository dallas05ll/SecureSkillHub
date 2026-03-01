"""
Abstract base crawler for SecureSkillHub discovery pipeline.

Provides async HTTP client management, rate limiting, retry logic,
and batch serialization. Every concrete scraper inherits from BaseCrawler.
"""

from __future__ import annotations

import abc
import asyncio
import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from types import TracebackType
from typing import Optional, Self

import httpx

from src.sanitizer.schemas import CrawlerBatch, SourceHub

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_OUTPUT_DIR = _PROJECT_ROOT / "data" / "discovered"

_DEFAULT_USER_AGENT = (
    "SecureSkillHub-Crawler/0.1 "
    "(+https://github.com/secureskillhub; security-scanner)"
)

_DEFAULT_TIMEOUT = 30.0
_MAX_RETRIES = 3
_BACKOFF_BASE = 2.0  # seconds — exponential backoff multiplier


class RateLimiter:
    """Token-bucket style rate limiter for async HTTP calls.

    Enforces a maximum number of requests per second by sleeping between
    calls when the limit would otherwise be exceeded.
    """

    def __init__(self, requests_per_second: float) -> None:
        if requests_per_second <= 0:
            raise ValueError("requests_per_second must be positive")
        self._min_interval = 1.0 / requests_per_second
        self._last_call: float = 0.0
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_call
            if elapsed < self._min_interval:
                await asyncio.sleep(self._min_interval - elapsed)
            self._last_call = time.monotonic()


class BaseCrawler(abc.ABC):
    """Abstract base crawler with HTTP lifecycle, rate limiting, and retry.

    Usage::

        async with MyCrawler() as crawler:
            batch = await crawler.scrape()
            crawler.save_batch(batch)
    """

    # Subclasses MUST set these.
    source_hub: SourceHub

    def __init__(
        self,
        *,
        requests_per_second: float = 2.0,
        user_agent: str = _DEFAULT_USER_AGENT,
        timeout: float = _DEFAULT_TIMEOUT,
        output_dir: Path | str | None = None,
        max_retries: int = _MAX_RETRIES,
    ) -> None:
        self._rps = requests_per_second
        self._user_agent = user_agent
        self._timeout = timeout
        self._output_dir = Path(output_dir) if output_dir else _DEFAULT_OUTPUT_DIR
        self._max_retries = max_retries

        self._rate_limiter = RateLimiter(self._rps)
        self._client: httpx.AsyncClient | None = None

        self._logger = logging.getLogger(
            f"{__name__}.{self.__class__.__name__}"
        )

    # -- async context manager ---------------------------------------------

    async def __aenter__(self) -> Self:
        self._client = httpx.AsyncClient(
            headers={"User-Agent": self._user_agent},
            timeout=httpx.Timeout(self._timeout),
            follow_redirects=True,
        )
        self._logger.info(
            "Crawler %s started (rate_limit=%.1f req/s)",
            self.__class__.__name__,
            self._rps,
        )
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None
            self._logger.info("Crawler %s shut down", self.__class__.__name__)

    # -- HTTP helper with retry + rate limiting ----------------------------

    async def fetch(
        self,
        url: str,
        *,
        params: dict | None = None,
        headers: dict | None = None,
    ) -> httpx.Response:
        """GET *url* with automatic rate limiting and exponential-backoff retry.

        Retries on 429 (Too Many Requests), 5xx server errors, and transient
        network failures.  Non-retryable 4xx errors raise immediately.

        Returns:
            The successful ``httpx.Response``.

        Raises:
            httpx.HTTPStatusError: After all retries are exhausted or on a
                non-retryable client error.
            RuntimeError: If the crawler was not entered as a context manager.
        """
        if self._client is None:
            raise RuntimeError(
                "Client not initialised — use 'async with' to enter the crawler"
            )

        last_exc: BaseException | None = None

        for attempt in range(1, self._max_retries + 1):
            await self._rate_limiter.acquire()

            try:
                response = self._client.get(url, params=params, headers=headers)
                resp = await response if asyncio.iscoroutine(response) else response  # type: ignore[arg-type]
            except (httpx.ConnectError, httpx.ReadTimeout, httpx.WriteTimeout,
                    httpx.PoolTimeout, httpx.ConnectTimeout) as exc:
                last_exc = exc
                wait = _BACKOFF_BASE ** attempt
                self._logger.warning(
                    "Attempt %d/%d for %s failed (%s). Retrying in %.1fs …",
                    attempt, self._max_retries, url, exc, wait,
                )
                await asyncio.sleep(wait)
                continue

            # Successful request — check status.
            if resp.status_code < 400:
                return resp

            # Rate-limited or server error → retry.
            if resp.status_code == 429 or resp.status_code >= 500:
                last_exc = httpx.HTTPStatusError(
                    f"HTTP {resp.status_code}",
                    request=resp.request,
                    response=resp,
                )
                retry_after = resp.headers.get("Retry-After")
                if retry_after and retry_after.isdigit():
                    wait = min(float(retry_after), 60.0)
                else:
                    wait = _BACKOFF_BASE ** attempt
                self._logger.warning(
                    "Attempt %d/%d for %s returned %d. Retrying in %.1fs …",
                    attempt, self._max_retries, url, resp.status_code, wait,
                )
                await asyncio.sleep(wait)
                continue

            # Non-retryable client error — fail immediately.
            resp.raise_for_status()

        # Exhausted all retries.
        assert last_exc is not None
        self._logger.error(
            "All %d retries exhausted for %s", self._max_retries, url,
        )
        raise last_exc

    # -- abstract ----------------------------------------------------------

    @abc.abstractmethod
    async def scrape(self) -> CrawlerBatch:
        """Scrape the source hub and return a ``CrawlerBatch``.

        Implementations should populate ``CrawlerBatch.skills`` with every
        ``DiscoveredSkill`` found, and record any non-fatal issues in
        ``CrawlerBatch.errors``.
        """

    # -- batch persistence -------------------------------------------------

    def save_batch(
        self,
        batch: CrawlerBatch,
        *,
        counter: int = 0,
    ) -> Path:
        """Write *batch* as JSON to ``data/discovered/``.

        File naming: ``batch-{source}-{date}-{counter}.json``

        Returns:
            The ``Path`` to the written file.
        """
        self._output_dir.mkdir(parents=True, exist_ok=True)

        date_str = datetime.now(timezone.utc).strftime("%Y%m%d")
        filename = f"batch-{batch.source_hub.value}-{date_str}-{counter}.json"
        filepath = self._output_dir / filename

        # Avoid accidental overwrites — increment counter if file exists.
        while filepath.exists():
            counter += 1
            filename = f"batch-{batch.source_hub.value}-{date_str}-{counter}.json"
            filepath = self._output_dir / filename

        filepath.write_text(
            batch.model_dump_json(indent=2),
            encoding="utf-8",
        )
        self._logger.info(
            "Saved batch → %s  (%d skills, %d errors)",
            filepath,
            len(batch.skills),
            len(batch.errors),
        )
        return filepath

    # -- helpers for subclasses --------------------------------------------

    @staticmethod
    def _truncate(value: str, max_length: int) -> str:
        """Truncate *value* to *max_length*, appending '...' when clipped."""
        if len(value) <= max_length:
            return value
        return value[: max_length - 3] + "..."

    @staticmethod
    def _safe_int(raw: str | int | None, *, default: int = 0) -> int:
        """Parse an int from a possibly messy string (e.g. '1.2k')."""
        if raw is None:
            return default
        if isinstance(raw, int):
            return raw
        raw = raw.strip().lower().replace(",", "")
        try:
            if raw.endswith("k"):
                return int(float(raw[:-1]) * 1_000)
            if raw.endswith("m"):
                return int(float(raw[:-1]) * 1_000_000)
            return int(float(raw))
        except (ValueError, TypeError):
            return default
