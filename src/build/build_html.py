"""
SecureSkillHub HTML / SEO Builder.

Injects build-time data into site/index.html meta tags and generates
sitemap.xml and robots.txt for search-engine discoverability.

Usage:
    python -m src.build.build_html
"""

from __future__ import annotations

import json
import logging
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = PROJECT_ROOT / "data"
SITE_DIR = PROJECT_ROOT / "site"

STATS_FILE = DATA_DIR / "stats.json"
API_STATS_FILE = SITE_DIR / "api" / "stats.json"
SKILLS_DIR = DATA_DIR / "skills"
INDEX_HTML = SITE_DIR / "index.html"
SITEMAP_XML = SITE_DIR / "sitemap.xml"
ROBOTS_TXT = SITE_DIR / "robots.txt"

# The canonical base URL for the deployed site.
# Override via environment variable if needed.
BASE_URL = os.environ.get("SITE_BASE_URL", "https://secureskillhub.github.io")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _read_json(path: Path) -> Any:
    """Read and parse a JSON file."""
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def _write_text(path: Path, content: str) -> None:
    """Write text content to a file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        fh.write(content)


# ---------------------------------------------------------------------------
# SEO meta-tag injection
# ---------------------------------------------------------------------------

def inject_stats_meta(stats: dict[str, Any]) -> None:
    """
    Read site/index.html and update the <meta name="description"> tag
    to include live stats for better SEO snippets.

    This is a lightweight touch -- the rest of the HTML is owned by Agent 4.
    """
    if not INDEX_HTML.is_file():
        logger.warning("index.html not found at %s -- skipping meta injection", INDEX_HTML)
        return

    logger.info("Injecting stats into index.html meta tags ...")

    total = stats.get("total_skills", 0)
    verified = stats.get("verified_skills", 0)

    new_description = (
        f"SecureSkillHub - Security-First Agent Skills Hub. "
        f"Browse {total} skills ({verified} fully verified) with multi-agent "
        f"security verification. Discover safe, audited MCP skills."
    )

    html = INDEX_HTML.read_text(encoding="utf-8")

    # Replace existing meta description content
    updated, count = re.subn(
        r'(<meta\s+name="description"\s+content=")([^"]*)(">)',
        rf'\g<1>{new_description}\g<3>',
        html,
        count=1,
    )

    if count == 0:
        logger.warning("Could not find meta description tag in index.html")
        return

    INDEX_HTML.write_text(updated, encoding="utf-8")
    logger.info("  -> Updated meta description in %s", INDEX_HTML)


# ---------------------------------------------------------------------------
# Sitemap generation
# ---------------------------------------------------------------------------

def generate_sitemap(skill_ids: list[str]) -> None:
    """
    Generate site/sitemap.xml listing the homepage and all skill detail pages.
    """
    logger.info("Generating sitemap.xml ...")

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    urls: list[str] = []

    # Homepage
    urls.append(
        f"  <url>\n"
        f"    <loc>{BASE_URL}/</loc>\n"
        f"    <lastmod>{today}</lastmod>\n"
        f"    <changefreq>daily</changefreq>\n"
        f"    <priority>1.0</priority>\n"
        f"  </url>"
    )

    # Entry point for agents
    urls.append(
        f"  <url>\n"
        f"    <loc>{BASE_URL}/entry.md</loc>\n"
        f"    <lastmod>{today}</lastmod>\n"
        f"    <changefreq>weekly</changefreq>\n"
        f"    <priority>0.9</priority>\n"
        f"  </url>"
    )

    # Documentation page
    urls.append(
        f"  <url>\n"
        f"    <loc>{BASE_URL}/docs.html</loc>\n"
        f"    <lastmod>{today}</lastmod>\n"
        f"    <changefreq>weekly</changefreq>\n"
        f"    <priority>0.8</priority>\n"
        f"  </url>"
    )

    # API endpoints (useful for search engines to discover structured data)
    for endpoint in ["api/tags.json", "api/skills/index.json", "api/stats.json"]:
        urls.append(
            f"  <url>\n"
            f"    <loc>{BASE_URL}/{endpoint}</loc>\n"
            f"    <lastmod>{today}</lastmod>\n"
            f"    <changefreq>daily</changefreq>\n"
            f"    <priority>0.6</priority>\n"
            f"  </url>"
        )

    # Individual skill pages
    for skill_id in sorted(skill_ids):
        urls.append(
            f"  <url>\n"
            f"    <loc>{BASE_URL}/api/skills/{skill_id}.json</loc>\n"
            f"    <lastmod>{today}</lastmod>\n"
            f"    <changefreq>weekly</changefreq>\n"
            f"    <priority>0.7</priority>\n"
            f"  </url>"
        )

    sitemap = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        + "\n".join(urls)
        + "\n</urlset>\n"
    )

    _write_text(SITEMAP_XML, sitemap)
    logger.info("  -> %s  (%d URLs)", SITEMAP_XML, len(urls))


# ---------------------------------------------------------------------------
# robots.txt generation
# ---------------------------------------------------------------------------

def generate_robots_txt() -> None:
    """Generate site/robots.txt allowing all crawlers and pointing to sitemap."""
    logger.info("Generating robots.txt ...")

    content = (
        "# SecureSkillHub - Security-First Agent Skills Hub\n"
        "# All content is public and safe for crawling.\n"
        "\n"
        "User-agent: *\n"
        "Allow: /\n"
        "\n"
        f"Sitemap: {BASE_URL}/sitemap.xml\n"
    )

    _write_text(ROBOTS_TXT, content)
    logger.info("  -> %s", ROBOTS_TXT)


# ---------------------------------------------------------------------------
# Main orchestrator
# ---------------------------------------------------------------------------

def build_all() -> None:
    """Run the full HTML/SEO build pipeline."""
    started = datetime.now(timezone.utc)
    logger.info("=" * 60)
    logger.info("SecureSkillHub HTML build started at %s", started.isoformat())
    logger.info("=" * 60)

    # 1. Load stats for meta injection.
    # Prefer site/api/stats.json generated by build_json for consistency.
    stats: dict[str, Any] = {}
    if API_STATS_FILE.is_file():
        stats = _read_json(API_STATS_FILE)
    elif STATS_FILE.is_file():
        stats = _read_json(STATS_FILE)
    else:
        logger.warning("stats.json not found at %s -- using empty stats", STATS_FILE)

    # 2. Inject stats into index.html meta tags
    inject_stats_meta(stats)

    # 3. Collect skill IDs for the sitemap
    skill_ids: list[str] = []
    if SKILLS_DIR.is_dir():
        for skill_file in sorted(SKILLS_DIR.glob("*.json")):
            try:
                data = _read_json(skill_file)
                skill_id = data.get("id", skill_file.stem)
                skill_ids.append(skill_id)
            except Exception:
                logger.exception("Failed to read skill file: %s", skill_file)

    # 4. Generate sitemap.xml
    generate_sitemap(skill_ids)

    # 5. Generate robots.txt
    generate_robots_txt()

    elapsed = datetime.now(timezone.utc) - started
    logger.info("=" * 60)
    logger.info(
        "HTML build complete: %d skill pages in sitemap, %.2fs",
        len(skill_ids),
        elapsed.total_seconds(),
    )
    logger.info("=" * 60)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        stream=sys.stdout,
    )
    build_all()
