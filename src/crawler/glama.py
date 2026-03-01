"""
Glama.ai MCP Servers crawler.

Scrapes structured JSON-LD data + React hydration data from
https://glama.ai/mcp/servers.

JSON-LD provides: name, description, author, license, URL
React hydration provides: stargazers (GitHub stars), weeklyDownloads

Strategy:
  1. Fetch the main /mcp/servers page (top 50 popular)
  2. Extract stars from React hydration data
  3. Discover category links from the page
  4. Fetch each category page for category-specific listings
  5. Deduplicate across all pages by repo_url
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone

from bs4 import BeautifulSoup

from src.crawler.base import BaseCrawler
from src.sanitizer.schemas import CrawlerBatch, DiscoveredSkill, SourceHub

logger = logging.getLogger(__name__)

_BASE_URL = "https://glama.ai"
_SERVERS_URL = f"{_BASE_URL}/mcp/servers"


class GlamaCrawler(BaseCrawler):
    """Crawl Glama.ai MCP server listings via JSON-LD + React hydration data."""

    source_hub = SourceHub.GLAMA

    def __init__(
        self,
        *,
        max_pages: int = 100,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self._max_pages = max_pages

    async def scrape(self) -> CrawlerBatch:
        skills: list[DiscoveredSkill] = []
        errors: list[str] = []
        seen_urls: set[str] = set()

        # --- Step 1: Fetch main listing page ---
        self._logger.info("Fetching main page: %s", _SERVERS_URL)
        try:
            resp = await self.fetch(_SERVERS_URL)
            main_html = resp.text
        except Exception as exc:
            errors.append(f"Main page fetch failed: {exc}")
            now = datetime.now(timezone.utc).isoformat()
            return CrawlerBatch(
                source_hub=SourceHub.GLAMA,
                crawled_at=now[:38],
                skills=[], total_found=0, errors=errors[:50],
            )

        # Extract stars from React hydration data
        star_map = self._extract_stars_from_hydration(main_html)
        self._logger.info("Extracted stars for %d servers from hydration data", len(star_map))

        page_skills = self._extract_jsonld(main_html, errors)
        for skill in page_skills:
            # Match stars by repo URL or name
            self._apply_stars(skill, star_map)
            if skill.repo_url not in seen_urls:
                seen_urls.add(skill.repo_url)
                skills.append(skill)
        self._logger.info("Main page: %d skills", len(skills))

        # --- Step 2: Discover category pages ---
        categories = self._extract_categories(main_html)
        self._logger.info("Found %d category pages to crawl", len(categories))

        # --- Step 3: Crawl each category ---
        pages_fetched = 1
        for cat_path in categories:
            if pages_fetched >= self._max_pages:
                break

            cat_url = f"{_BASE_URL}{cat_path}"
            self._logger.info("Fetching category: %s", cat_url)

            try:
                resp = await self.fetch(cat_url)
                pages_fetched += 1
            except Exception as exc:
                errors.append(f"Category {cat_path} failed: {exc}")
                continue

            cat_html = resp.text
            cat_star_map = self._extract_stars_from_hydration(cat_html)
            star_map.update(cat_star_map)

            cat_skills = self._extract_jsonld(cat_html, errors)
            new_count = 0
            for skill in cat_skills:
                cat_name = cat_path.split("/")[-1].replace("-", " ").title()
                if cat_name and cat_name not in skill.source_tags:
                    skill.source_tags.append(cat_name)

                self._apply_stars(skill, star_map)

                if skill.repo_url not in seen_urls:
                    seen_urls.add(skill.repo_url)
                    skills.append(skill)
                    new_count += 1

            self._logger.info(
                "Category %s: %d skills (%d new, total: %d)",
                cat_path.split("/")[-1], len(cat_skills), new_count, len(skills),
            )

        now = datetime.now(timezone.utc).isoformat()
        return CrawlerBatch(
            source_hub=SourceHub.GLAMA,
            crawled_at=now[:38],
            skills=skills,
            total_found=len(skills),
            errors=errors[:50],
        )

    @staticmethod
    def _extract_stars_from_hydration(html: str) -> dict[str, int]:
        """Extract GitHub star counts from React hydration/RSC data.

        Glama embeds server metadata in serialized React state.
        Pattern: ...,"@author/repo-name",...,"stargazers",N,...
        We look for slug->stargazers pairs in the raw HTML.
        """
        star_map: dict[str, int] = {}

        # Pattern 1: Look for server slug followed by stargazers count
        # React RSC format: ..."@brave/brave-search-mcp-server"..."stargazers",681...
        slug_pattern = re.compile(
            r'"@([^"]+/[^"]+)".*?"stargazers"\s*,\s*(\d+)',
            re.DOTALL,
        )
        for match in slug_pattern.finditer(html):
            slug = match.group(1)  # e.g. "brave/brave-search-mcp-server"
            stars = int(match.group(2))
            repo_url = f"https://github.com/{slug}"
            star_map[repo_url.lower()] = stars

        # Pattern 2: More granular — find all "stargazers",N patterns
        # and try to associate with nearby server identifiers
        star_vals = re.findall(r'"stargazers"\s*,\s*(\d+)', html)
        if star_vals and not star_map:
            # Fallback: find all @org/repo patterns and zip with stars
            slugs = re.findall(r'"@([a-zA-Z0-9_-]+/[a-zA-Z0-9_.-]+)"', html)
            # Remove duplicates while preserving order
            seen = set()
            unique_slugs = []
            for s in slugs:
                if s not in seen:
                    seen.add(s)
                    unique_slugs.append(s)

            for slug, stars in zip(unique_slugs, star_vals):
                repo_url = f"https://github.com/{slug}"
                star_map[repo_url.lower()] = int(stars)

        return star_map

    @staticmethod
    def _apply_stars(skill: DiscoveredSkill, star_map: dict[str, int]) -> None:
        """Apply star count from star_map to a skill if found."""
        repo_key = skill.repo_url.lower().rstrip("/")
        if repo_key in star_map:
            skill.stars = star_map[repo_key]

    @staticmethod
    def _extract_categories(html: str) -> list[str]:
        """Find all category page links from the main listing."""
        pattern = re.compile(r'href="(/mcp/servers/categories/[^"]+)"')
        return sorted(set(pattern.findall(html)))

    def _extract_jsonld(
        self, html: str, errors: list[str]
    ) -> list[DiscoveredSkill]:
        """Parse JSON-LD from page HTML to extract SoftwareApplication entries."""
        results: list[DiscoveredSkill] = []

        soup = BeautifulSoup(html, "html.parser")
        ld_scripts = soup.find_all("script", type="application/ld+json")

        for script in ld_scripts:
            try:
                data = json.loads(script.string or "")
            except (json.JSONDecodeError, TypeError):
                continue

            graph = data.get("@graph", [data])
            for node in graph:
                # Main listing pages
                if node.get("@type") == "SearchResultsPage":
                    elements = (
                        node.get("mainEntity", {}).get("itemListElement", [])
                    )
                    for el in elements:
                        item = el.get("item", {})
                        if item.get("@type") != "SoftwareApplication":
                            continue
                        skill = self._parse_item(item, el.get("url", ""))
                        if skill:
                            results.append(skill)

                # Category pages may use CollectionPage or similar
                if node.get("@type") in ("CollectionPage", "ItemList"):
                    elements = node.get("itemListElement", [])
                    for el in elements:
                        item = el.get("item", {})
                        if item.get("@type") == "SoftwareApplication":
                            skill = self._parse_item(item, el.get("url", ""))
                            if skill:
                                results.append(skill)

        return results

    def _parse_item(
        self, item: dict, detail_url: str
    ) -> DiscoveredSkill | None:
        """Convert a JSON-LD SoftwareApplication to DiscoveredSkill."""
        name = item.get("name", "").strip()
        if not name:
            return None

        description = self._truncate(
            item.get("description", ""), 500
        )

        author_data = item.get("author", {})
        owner = author_data.get("name", "")
        github_org = author_data.get("sameAs", "")

        # Build repo URL from Glama detail URL pattern:
        # /mcp/servers/@author/repo-name -> github.com/author/repo-name
        repo_url = ""
        if detail_url:
            match = re.search(r"/mcp/servers/@([^/]+)/(.+)", detail_url)
            if match:
                repo_url = f"https://github.com/{match.group(1)}/{match.group(2)}"
        if not repo_url and github_org:
            repo_url = github_org

        if not repo_url:
            return None

        tags = []
        category = item.get("applicationCategory", "")
        if category:
            tags.append(category)

        return DiscoveredSkill(
            name=self._truncate(name, 200),
            repo_url=self._truncate(repo_url, 500),
            description=description,
            source_hub=SourceHub.GLAMA,
            stars=0,
            source_tags=tags[:10],
            owner=self._truncate(owner, 200),
        )
