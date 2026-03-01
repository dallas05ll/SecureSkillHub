"""
SkillsMP crawler — discovers MCP skills from skillsmp.com.

SkillsMP is an unvetted aggregator with 96K+ skills.
All discoveries are tagged TrustLevel.LOW.
"""

from __future__ import annotations

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

_BASE_URL = "https://skillsmp.com"
_LISTING_PATH = "/skills"


class SkillsMPCrawler(BaseCrawler):
    """Scrapes the SkillsMP skills listing pages.

    SkillsMP provides a paginated HTML listing of MCP-compatible skills.
    Each listing card typically contains:
      - Skill name & link to detail page
      - Repository URL (GitHub/GitLab)
      - Short description
      - Star count
      - Tags / categories
    """

    source_hub = SourceHub.SKILLSMP

    def __init__(
        self,
        *,
        max_pages: int = 100,
        **kwargs,
    ) -> None:
        super().__init__(requests_per_second=2.0, **kwargs)
        self._max_pages = max_pages

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def scrape(self) -> CrawlerBatch:
        """Crawl SkillsMP listing pages and return a CrawlerBatch."""
        skills: list[DiscoveredSkill] = []
        errors: list[str] = []
        page = 1

        while page <= self._max_pages:
            url = self._build_page_url(page)
            self._logger.info("Fetching page %d: %s", page, url)

            try:
                resp = await self.fetch(url)
            except Exception as exc:
                msg = f"Failed to fetch page {page}: {exc}"
                self._logger.error(msg)
                errors.append(self._truncate(msg, 500))
                break

            page_skills, page_errors, has_next = self._parse_listing_page(
                resp.text, page
            )
            skills.extend(page_skills)
            errors.extend(page_errors)

            self._logger.info(
                "Page %d: found %d skills (total so far: %d)",
                page, len(page_skills), len(skills),
            )

            if not has_next or len(page_skills) == 0:
                break

            page += 1

        batch = CrawlerBatch(
            source_hub=SourceHub.SKILLSMP,
            crawled_at=datetime.now(timezone.utc).isoformat(),
            skills=skills,
            total_found=len(skills),
            errors=errors[:50],  # cap stored errors
        )
        return batch

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    @staticmethod
    def _build_page_url(page: int) -> str:
        params = urlencode({"page": page})
        return f"{_BASE_URL}{_LISTING_PATH}?{params}"

    def _parse_listing_page(
        self, html: str, page: int,
    ) -> tuple[list[DiscoveredSkill], list[str], bool]:
        """Parse a single listing page and return (skills, errors, has_next)."""
        skills: list[DiscoveredSkill] = []
        errors: list[str] = []

        soup = BeautifulSoup(html, "html.parser")

        # SkillsMP uses card-based layout.  We look for common card selectors.
        # The exact selectors may need adjustment when the site changes its
        # markup — the approach is intentionally resilient with fallbacks.
        cards = (
            soup.select("div.skill-card")
            or soup.select("article.skill")
            or soup.select("[data-skill]")
            or soup.select("div.card")
        )

        for card in cards:
            try:
                skill = self._parse_card(card)
                if skill is not None:
                    skills.append(skill)
            except Exception as exc:
                msg = f"Page {page}: card parse error — {exc}"
                self._logger.warning(msg)
                errors.append(self._truncate(msg, 500))

        # Detect whether there is a next page.
        has_next = self._has_next_page(soup)

        return skills, errors, has_next

    def _parse_card(self, card: Tag) -> DiscoveredSkill | None:
        """Extract a single DiscoveredSkill from a listing card element."""

        # --- Name -----------------------------------------------------------
        name_el = (
            card.select_one("h2 a")
            or card.select_one("h3 a")
            or card.select_one(".skill-name a")
            or card.select_one("a.title")
        )
        if name_el is None:
            return None
        name = self._truncate(name_el.get_text(strip=True), 200)
        if not name:
            return None

        # --- Repo URL -------------------------------------------------------
        repo_url = self._extract_repo_url(card)
        if not repo_url:
            # Use the detail-page link as a fallback so we still record it.
            href = name_el.get("href", "")
            repo_url = urljoin(_BASE_URL, href) if href else ""
        repo_url = self._truncate(repo_url, 500)

        # --- Description ----------------------------------------------------
        desc_el = (
            card.select_one("p.description")
            or card.select_one(".skill-desc")
            or card.select_one("p")
        )
        description = ""
        if desc_el:
            description = self._truncate(desc_el.get_text(strip=True), 500)

        # --- Stars ----------------------------------------------------------
        stars_el = (
            card.select_one(".stars")
            or card.select_one("[data-stars]")
            or card.select_one(".star-count")
        )
        stars = 0
        if stars_el:
            stars_raw = stars_el.get("data-stars") or stars_el.get_text(strip=True)
            stars = self._safe_int(stars_raw)

        # --- Tags -----------------------------------------------------------
        tag_els = card.select(".tag") or card.select(".badge") or card.select(".label")
        tags = [
            self._truncate(t.get_text(strip=True), 100)
            for t in tag_els
            if t.get_text(strip=True)
        ][:20]  # cap tag count

        # --- Owner ----------------------------------------------------------
        owner_el = card.select_one(".owner") or card.select_one(".author")
        owner = ""
        if owner_el:
            owner = self._truncate(owner_el.get_text(strip=True), 200)
        elif repo_url and "github.com/" in repo_url:
            parts = repo_url.split("github.com/")
            if len(parts) > 1:
                segments = parts[1].strip("/").split("/")
                if segments:
                    owner = self._truncate(segments[0], 200)

        return DiscoveredSkill(
            name=name,
            repo_url=repo_url,
            source_hub=SourceHub.SKILLSMP,
            trust_level=TrustLevel.LOW,
            description=description,
            stars=stars,
            source_tags=tags,
            owner=owner,
        )

    def _extract_repo_url(self, card: Tag) -> str:
        """Try to find a GitHub/GitLab repo link inside the card."""
        for anchor in card.find_all("a", href=True):
            href: str = anchor["href"]
            if any(host in href for host in ("github.com/", "gitlab.com/")):
                return href
        # data attribute fallback
        repo_attr = card.get("data-repo") or card.get("data-url")
        if repo_attr and isinstance(repo_attr, str):
            return repo_attr
        return ""

    @staticmethod
    def _has_next_page(soup: BeautifulSoup) -> bool:
        """Heuristic check for a 'next page' link in the pagination."""
        next_link = (
            soup.select_one("a.next")
            or soup.select_one("a[rel='next']")
            or soup.select_one("li.next a")
            or soup.select_one(".pagination a:last-child")
        )
        if next_link:
            # Ensure it's not disabled.
            parent = next_link.parent
            if parent and "disabled" in (parent.get("class") or []):
                return False
            return True
        return False
