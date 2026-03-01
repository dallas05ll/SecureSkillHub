"""
mcp.so crawler — discovers MCP servers from mcp.so.

mcp.so is an unvetted directory of ~17K MCP servers built on Next.js.
Listing pages: https://mcp.so/servers?page=N
Detail pages:  https://mcp.so/server/{name}/{author}

Data is extracted by parsing href links from the listing HTML, then
optionally visiting detail pages to find GitHub repo URLs.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone

from bs4 import BeautifulSoup

from src.crawler.base import BaseCrawler
from src.sanitizer.schemas import CrawlerBatch, DiscoveredSkill, SourceHub

logger = logging.getLogger(__name__)

_BASE_URL = "https://mcp.so"


class MCPSoCrawler(BaseCrawler):
    """Scrapes the mcp.so MCP-server directory via HTML listing pages."""

    source_hub = SourceHub.MCP_SO

    def __init__(
        self,
        *,
        max_pages: int = 100,
        fetch_details: bool = False,
        **kwargs,
    ) -> None:
        super().__init__(requests_per_second=1.5, **kwargs)
        self._max_pages = max_pages
        self._fetch_details = fetch_details

    async def scrape(self) -> CrawlerBatch:
        skills: list[DiscoveredSkill] = []
        errors: list[str] = []
        seen: set[str] = set()

        for page in range(1, self._max_pages + 1):
            url = f"{_BASE_URL}/servers"
            params = {"page": str(page)}
            self._logger.info("Fetching page %d: %s?page=%d", page, url, page)

            try:
                resp = await self.fetch(url, params=params)
            except Exception as exc:
                errors.append(f"Page {page} fetch failed: {exc}")
                break

            html = resp.text
            page_links = self._extract_server_links(html)

            if not page_links:
                self._logger.info("Page %d: 0 server links — stopping", page)
                break

            new_count = 0
            for name, author, link_path, card_desc in page_links:
                key = f"{author}/{name}"
                if key in seen:
                    continue
                seen.add(key)
                new_count += 1

                repo_url = f"https://github.com/{author}/{name}"
                desc = card_desc or ""

                # Optionally fetch detail page for richer data
                if self._fetch_details:
                    detail_url = f"{_BASE_URL}{link_path}"
                    try:
                        detail_resp = await self.fetch(detail_url)
                        detail_desc, gh = self._extract_detail(detail_resp.text)
                        if detail_desc:
                            desc = detail_desc
                        if gh:
                            repo_url = gh
                    except Exception:
                        pass

                skills.append(DiscoveredSkill(
                    name=self._truncate(name, 200),
                    repo_url=self._truncate(repo_url, 500),
                    source_hub=SourceHub.MCP_SO,
                    description=self._truncate(desc, 500),
                    stars=0,
                    source_tags=[],
                    owner=self._truncate(author, 200),
                ))

            self._logger.info(
                "Page %d: %d links (%d new, total: %d)",
                page, len(page_links), new_count, len(skills),
            )

            # Check if there's a "Next" page
            if not self._has_next(html):
                break

        now = datetime.now(timezone.utc).isoformat()
        return CrawlerBatch(
            source_hub=SourceHub.MCP_SO,
            crawled_at=now[:38],
            skills=skills,
            total_found=len(skills),
            errors=errors[:50],
        )

    @staticmethod
    def _extract_server_links(html: str) -> list[tuple[str, str, str, str]]:
        """Extract (name, author, path, description) tuples from listing HTML.

        mcp.so links look like: /server/{name}/{author}
        Cards contain a <p> with description text.
        """
        results = []
        soup = BeautifulSoup(html, "html.parser")

        # Find all server card links
        for link in soup.find_all("a", href=re.compile(r"^/server/[^/]+/[^/]+$")):
            href = link.get("href", "")
            match = re.match(r"/server/([^/]+)/([^/]+)", href)
            if not match:
                continue
            name = match.group(1)
            author = match.group(2)

            # Extract description from the card's <p> tag
            desc = ""
            p_tag = link.find("p")
            if p_tag:
                desc = p_tag.get_text(strip=True)

            results.append((name, author, href, desc))
        return results

    @staticmethod
    def _extract_detail(html: str) -> tuple[str, str]:
        """From a detail page, extract (description, github_url)."""
        desc = ""
        github_url = ""

        # Meta description
        meta = re.search(
            r'<meta name="description" content="([^"]*)"', html
        )
        if meta:
            desc = meta.group(1).replace("&#x27;", "'")

        # GitHub repo link
        gh_match = re.search(
            r'href="(https://github\.com/[^"]+/[^"]+)"', html
        )
        if gh_match:
            url = gh_match.group(1)
            # Skip issue/PR links
            if "/issues" not in url and "/pull" not in url:
                github_url = url

        return desc, github_url

    @staticmethod
    def _has_next(html: str) -> bool:
        """Check if pagination has a 'Next' link."""
        return bool(re.search(r'>Next<', html, re.IGNORECASE))
