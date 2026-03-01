"""
claudeskills.info crawler — discovers Agent Skills from Claude Skills Hub.

claudeskills.info is a curated directory of 76+ Claude Code SKILL.md packages.
Each skill page contains JSON-LD structured data with rich metadata including
GitHub stars, license, categories, and version info.

Strategy:
  1. Fetch sitemap at /sitemap_skills.xml for complete skill URL inventory
  2. Fetch each skill page and extract JSON-LD + Next.js metadata
  3. Return skills with full metadata including stars
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone

from bs4 import BeautifulSoup

from src.crawler.base import BaseCrawler
from src.sanitizer.schemas import (
    CrawlerBatch,
    DiscoveredSkill,
    SkillType,
    SourceHub,
    TrustLevel,
)

logger = logging.getLogger(__name__)

_BASE_URL = "https://claudeskills.info"


class ClaudeSkillsCrawler(BaseCrawler):
    """Crawl claudeskills.info for curated Agent Skills."""

    source_hub = SourceHub.CLAUDE_SKILLS_HUB

    def __init__(self, **kwargs) -> None:
        super().__init__(requests_per_second=2.0, **kwargs)

    async def scrape(self) -> CrawlerBatch:
        skills: list[DiscoveredSkill] = []
        errors: list[str] = []

        # Step 1: Get sitemap for all skill URLs
        self._logger.info("Fetching sitemap: %s/sitemap_skills.xml", _BASE_URL)
        try:
            resp = await self.fetch(f"{_BASE_URL}/sitemap_skills.xml")
            slugs = self._extract_slugs_from_sitemap(resp.text)
        except Exception as exc:
            errors.append(f"Sitemap fetch failed: {exc}")
            # Fallback: try explore page
            try:
                resp = await self.fetch(f"{_BASE_URL}/explore")
                slugs = self._extract_slugs_from_html(resp.text)
            except Exception as exc2:
                errors.append(f"Explore page fallback failed: {exc2}")
                slugs = []

        self._logger.info("Found %d skill slugs", len(slugs))

        # Step 2: Fetch each skill page
        for i, slug in enumerate(slugs, 1):
            url = f"{_BASE_URL}/skill/{slug}"
            try:
                resp = await self.fetch(url)
                skill = self._extract_skill(resp.text, slug)
                if skill:
                    skills.append(skill)
                    if i % 20 == 0:
                        self._logger.info("  Progress: %d/%d fetched", i, len(slugs))
            except Exception as exc:
                errors.append(f"Skill {slug}: {exc}")

        self._logger.info("Extracted %d skills from %d pages", len(skills), len(slugs))

        now = datetime.now(timezone.utc).isoformat()
        return CrawlerBatch(
            source_hub=SourceHub.CLAUDE_SKILLS_HUB,
            crawled_at=now[:38],
            skills=skills,
            total_found=len(skills),
            errors=errors[:50],
        )

    @staticmethod
    def _extract_slugs_from_sitemap(xml: str) -> list[str]:
        """Extract skill slugs from sitemap XML."""
        slugs = []
        pattern = re.compile(r"/skill/([^<\s]+)")
        for match in pattern.finditer(xml):
            slug = match.group(1).strip("/")
            if slug and slug not in slugs:
                slugs.append(slug)
        return slugs

    @staticmethod
    def _extract_slugs_from_html(html: str) -> list[str]:
        """Fallback: extract skill slugs from explore page HTML."""
        slugs = []
        pattern = re.compile(r'href="/skill/([^"]+)"')
        for match in pattern.finditer(html):
            slug = match.group(1)
            if slug not in slugs:
                slugs.append(slug)
        return slugs

    def _extract_skill(self, html: str, slug: str) -> DiscoveredSkill | None:
        """Extract skill data from a skill detail page."""
        soup = BeautifulSoup(html, "html.parser")

        # Try JSON-LD first
        ld_scripts = soup.find_all("script", type="application/ld+json")
        for script in ld_scripts:
            try:
                data = json.loads(script.string or "")
                if data.get("@type") == "SoftwareApplication":
                    return self._parse_jsonld_skill(data, slug)
            except (json.JSONDecodeError, TypeError):
                continue

        # Fallback: parse meta tags
        name = ""
        desc = ""
        meta_title = soup.find("meta", {"property": "og:title"})
        if meta_title:
            name = meta_title.get("content", "")
        meta_desc = soup.find("meta", {"property": "og:description"})
        if meta_desc:
            desc = meta_desc.get("content", "")

        if not name:
            title_tag = soup.find("title")
            if title_tag:
                name = title_tag.get_text(strip=True).split("|")[0].strip()

        if not name:
            return None

        # Find GitHub link
        repo_url = ""
        for a in soup.find_all("a", href=re.compile(r"github\.com")):
            url = a.get("href", "")
            if "github.com/" in url:
                repo_url = url
                break

        if not repo_url:
            return None

        owner = ""
        if "github.com/" in repo_url:
            parts = repo_url.split("github.com/")[1].split("/")
            if parts:
                owner = parts[0]

        return DiscoveredSkill(
            name=self._truncate(name, 200),
            repo_url=self._truncate(repo_url, 500),
            source_hub=SourceHub.CLAUDE_SKILLS_HUB,
            skill_type=SkillType.AGENT_SKILL,
            trust_level=TrustLevel.MEDIUM,
            description=self._truncate(desc, 500),
            stars=0,
            source_tags=[],
            owner=self._truncate(owner, 200),
        )

    def _parse_jsonld_skill(
        self, data: dict, slug: str
    ) -> DiscoveredSkill | None:
        """Parse a JSON-LD SoftwareApplication into DiscoveredSkill."""
        name = data.get("name", "").strip()
        if not name:
            return None

        desc = self._truncate(data.get("description", ""), 500)

        # GitHub URL from codeRepository or downloadUrl
        repo_url = data.get("codeRepository", "")
        if not repo_url:
            repo_url = data.get("downloadUrl", "")

        if not repo_url:
            return None

        # Author
        author = data.get("author", {})
        owner = author.get("name", "") if isinstance(author, dict) else ""

        # Categories/tags from keywords
        tags = []
        keywords = data.get("keywords", [])
        if isinstance(keywords, list):
            tags = keywords[:10]
        elif isinstance(keywords, str):
            tags = [k.strip() for k in keywords.split(",")][:10]

        # Stars from aggregateRating or extra fields
        stars = 0
        rating = data.get("aggregateRating", {})
        if rating:
            stars = int(rating.get("ratingCount", 0))

        return DiscoveredSkill(
            name=self._truncate(name, 200),
            repo_url=self._truncate(repo_url, 500),
            source_hub=SourceHub.CLAUDE_SKILLS_HUB,
            skill_type=SkillType.AGENT_SKILL,
            trust_level=TrustLevel.MEDIUM,
            description=desc,
            stars=stars,
            source_tags=tags,
            owner=self._truncate(owner, 200),
        )
