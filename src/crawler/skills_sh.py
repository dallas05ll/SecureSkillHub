"""
skills.sh crawler — discovers MCP skills from skills.sh.

skills.sh performs Snyk-based security scanning, so discoveries are
tagged TrustLevel.MEDIUM.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from urllib.parse import urljoin, urlencode

from bs4 import BeautifulSoup, Tag

from src.crawler.base import BaseCrawler
from src.sanitizer.schemas import (
    CrawlerBatch,
    DiscoveredSkill,
    SourceHub,
    TrustLevel,
)

logger = logging.getLogger(__name__)

_BASE_URL = "https://skills.sh"
_LISTING_PATH = "/skills"
# skills.sh may also expose a JSON API; we try that first.
_API_PATH = "/api/skills"


class SkillsSHCrawler(BaseCrawler):
    """Scrapes the skills.sh skill directory.

    skills.sh has ~60K+ skills and applies Snyk vulnerability scanning.
    We first attempt to use a JSON API endpoint (faster, more reliable).
    If the API is unavailable, we fall back to HTML scraping.
    """

    source_hub = SourceHub.SKILLS_SH

    def __init__(
        self,
        *,
        max_pages: int = 100,
        page_size: int = 50,
        **kwargs,
    ) -> None:
        super().__init__(requests_per_second=2.0, **kwargs)
        self._max_pages = max_pages
        self._page_size = page_size

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def scrape(self) -> CrawlerBatch:
        """Crawl skills.sh and return a CrawlerBatch."""
        # Try JSON API first.
        skills, errors = await self._scrape_via_api()

        if not skills:
            self._logger.info(
                "API yielded no results — falling back to HTML scraping"
            )
            skills, errors = await self._scrape_via_html()

        batch = CrawlerBatch(
            source_hub=SourceHub.SKILLS_SH,
            crawled_at=datetime.now(timezone.utc).isoformat(),
            skills=skills,
            total_found=len(skills),
            errors=errors[:50],
        )
        return batch

    # ------------------------------------------------------------------
    # Strategy 1: JSON API
    # ------------------------------------------------------------------

    async def _scrape_via_api(
        self,
    ) -> tuple[list[DiscoveredSkill], list[str]]:
        skills: list[DiscoveredSkill] = []
        errors: list[str] = []
        page = 1

        while page <= self._max_pages:
            url = f"{_BASE_URL}{_API_PATH}"
            params = {"page": str(page), "limit": str(self._page_size)}
            self._logger.info("API page %d: %s", page, url)

            try:
                resp = await self.fetch(url, params=params)
            except Exception as exc:
                msg = f"API page {page} failed: {exc}"
                self._logger.warning(msg)
                errors.append(self._truncate(msg, 500))
                break

            # Expect JSON. If not, bail and let caller try HTML.
            content_type = resp.headers.get("content-type", "")
            if "json" not in content_type:
                self._logger.info("API did not return JSON — aborting API path")
                break

            try:
                payload = resp.json()
            except (json.JSONDecodeError, ValueError) as exc:
                msg = f"API page {page}: invalid JSON — {exc}"
                self._logger.warning(msg)
                errors.append(self._truncate(msg, 500))
                break

            items = self._extract_api_items(payload)
            if not items:
                break

            for item in items:
                try:
                    skill = self._parse_api_item(item)
                    if skill is not None:
                        skills.append(skill)
                except Exception as exc:
                    msg = f"API item parse error: {exc}"
                    self._logger.warning(msg)
                    errors.append(self._truncate(msg, 500))

            self._logger.info(
                "API page %d: %d items (total: %d)", page, len(items), len(skills)
            )

            # Check if there are more pages.
            if len(items) < self._page_size:
                break

            page += 1

        return skills, errors

    @staticmethod
    def _extract_api_items(payload: dict | list) -> list[dict]:
        """Normalize the API response into a list of item dicts."""
        if isinstance(payload, list):
            return payload
        # Common response shapes: { "data": [...] }, { "skills": [...] },
        # { "results": [...] }
        for key in ("data", "skills", "results", "items"):
            if key in payload and isinstance(payload[key], list):
                return payload[key]
        return []

    def _parse_api_item(self, item: dict) -> DiscoveredSkill | None:
        """Map a single JSON item to DiscoveredSkill."""
        name = item.get("name") or item.get("title") or ""
        name = self._truncate(str(name).strip(), 200)
        if not name:
            return None

        repo_url = (
            item.get("repo_url")
            or item.get("repository")
            or item.get("github_url")
            or item.get("url")
            or ""
        )
        repo_url = self._truncate(str(repo_url).strip(), 500)

        description = (
            item.get("description")
            or item.get("summary")
            or item.get("short_description")
            or ""
        )
        description = self._truncate(str(description).strip(), 500)

        stars = self._safe_int(item.get("stars") or item.get("stargazers_count"))

        tags_raw = item.get("tags") or item.get("categories") or []
        if isinstance(tags_raw, str):
            tags_raw = [t.strip() for t in tags_raw.split(",") if t.strip()]
        tags = [self._truncate(str(t), 100) for t in tags_raw][:20]

        owner = str(item.get("owner") or item.get("author") or "").strip()
        if not owner and repo_url and "github.com/" in repo_url:
            parts = repo_url.split("github.com/")
            if len(parts) > 1:
                segments = parts[1].strip("/").split("/")
                if segments:
                    owner = segments[0]
        owner = self._truncate(owner, 200)

        last_updated = item.get("last_updated") or item.get("updated_at")
        if last_updated:
            last_updated = self._truncate(str(last_updated), 30)

        return DiscoveredSkill(
            name=name,
            repo_url=repo_url,
            source_hub=SourceHub.SKILLS_SH,
            trust_level=TrustLevel.MEDIUM,
            description=description,
            stars=stars,
            source_tags=tags,
            owner=owner,
            last_updated=last_updated,
        )

    # ------------------------------------------------------------------
    # Strategy 2: HTML scraping (fallback)
    # ------------------------------------------------------------------

    async def _scrape_via_html(
        self,
    ) -> tuple[list[DiscoveredSkill], list[str]]:
        skills: list[DiscoveredSkill] = []
        errors: list[str] = []
        page = 1

        while page <= self._max_pages:
            params = urlencode({"page": page})
            url = f"{_BASE_URL}{_LISTING_PATH}?{params}"
            self._logger.info("HTML page %d: %s", page, url)

            try:
                resp = await self.fetch(url)
            except Exception as exc:
                msg = f"HTML page {page} failed: {exc}"
                self._logger.error(msg)
                errors.append(self._truncate(msg, 500))
                break

            page_skills, page_errors, has_next = self._parse_html_page(
                resp.text, page
            )
            skills.extend(page_skills)
            errors.extend(page_errors)

            self._logger.info(
                "HTML page %d: %d skills (total: %d)",
                page, len(page_skills), len(skills),
            )

            if not has_next or len(page_skills) == 0:
                break

            page += 1

        return skills, errors

    def _parse_html_page(
        self, html: str, page: int,
    ) -> tuple[list[DiscoveredSkill], list[str], bool]:
        """Parse an HTML listing page. Returns (skills, errors, has_next)."""
        skills: list[DiscoveredSkill] = []
        errors: list[str] = []

        soup = BeautifulSoup(html, "html.parser")

        cards = (
            soup.select("div.skill-card")
            or soup.select("article.skill")
            or soup.select("[data-skill]")
            or soup.select("div.card")
            or soup.select("tr.skill-row")
        )

        for card in cards:
            try:
                skill = self._parse_html_card(card)
                if skill is not None:
                    skills.append(skill)
            except Exception as exc:
                msg = f"HTML page {page} card error: {exc}"
                self._logger.warning(msg)
                errors.append(self._truncate(msg, 500))

        has_next = self._has_next_page(soup)
        return skills, errors, has_next

    def _parse_html_card(self, card: Tag) -> DiscoveredSkill | None:
        """Extract a DiscoveredSkill from an HTML card element."""

        # --- Name ---
        name_el = (
            card.select_one("h2 a")
            or card.select_one("h3 a")
            or card.select_one(".skill-name")
            or card.select_one("a.title")
        )
        if name_el is None:
            return None
        name = self._truncate(name_el.get_text(strip=True), 200)
        if not name:
            return None

        # --- Repo URL ---
        repo_url = self._extract_repo_url(card)
        if not repo_url:
            href = name_el.get("href", "")
            repo_url = urljoin(_BASE_URL, href) if href else ""
        repo_url = self._truncate(repo_url, 500)

        # --- Description ---
        desc_el = card.select_one("p.description") or card.select_one("p")
        description = ""
        if desc_el:
            description = self._truncate(desc_el.get_text(strip=True), 500)

        # --- Stars ---
        stars_el = (
            card.select_one(".stars")
            or card.select_one("[data-stars]")
            or card.select_one(".star-count")
        )
        stars = 0
        if stars_el:
            stars_raw = stars_el.get("data-stars") or stars_el.get_text(strip=True)
            stars = self._safe_int(stars_raw)

        # --- Owner ---
        owner = ""
        if repo_url and "github.com/" in repo_url:
            parts = repo_url.split("github.com/")
            if len(parts) > 1:
                segments = parts[1].strip("/").split("/")
                if segments:
                    owner = self._truncate(segments[0], 200)

        return DiscoveredSkill(
            name=name,
            repo_url=repo_url,
            source_hub=SourceHub.SKILLS_SH,
            trust_level=TrustLevel.MEDIUM,
            description=description,
            stars=stars,
            owner=owner,
        )

    @staticmethod
    def _extract_repo_url(card: Tag) -> str:
        for anchor in card.find_all("a", href=True):
            href: str = anchor["href"]
            if "github.com/" in href or "gitlab.com/" in href:
                return href
        repo_attr = card.get("data-repo") or card.get("data-url")
        if repo_attr and isinstance(repo_attr, str):
            return repo_attr
        return ""

    @staticmethod
    def _has_next_page(soup: BeautifulSoup) -> bool:
        next_link = (
            soup.select_one("a.next")
            or soup.select_one("a[rel='next']")
            or soup.select_one("li.next a")
            or soup.select_one(".pagination a:last-child")
        )
        if next_link:
            parent = next_link.parent
            if parent and "disabled" in (parent.get("class") or []):
                return False
            return True
        return False
