#!/usr/bin/env python3
"""
Runner for the two pending crawlers: skills_sh and skillsmp.

Usage:
    .venv/bin/python run_pending_crawlers.py [--max-pages N]

This script runs both crawlers, saves batch files to data/discovered/,
then reports what was found.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx
from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).resolve().parent))

from src.sanitizer.schemas import (
    CrawlerBatch,
    DiscoveredSkill,
    SourceHub,
    TrustLevel,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("run_pending_crawlers")


OUTPUT_DIR = Path(__file__).resolve().parent / "data" / "discovered"


# ---------------------------------------------------------------------------
# skills.sh scraper (homepage leaderboard — the /skills route is 404)
# ---------------------------------------------------------------------------

async def scrape_skills_sh(max_pages: int = 10) -> CrawlerBatch:
    """
    skills.sh uses Next.js and renders the leaderboard on the homepage.
    The /skills path returns 404, and the /api/skills endpoint also 404s.

    Strategy: scrape the homepage leaderboard (paginated via ?page=N),
    then follow individual skill links /{owner}/{repo}/{skill-name} to
    get GitHub repo URLs.
    """
    skills: list[DiscoveredSkill] = []
    errors: list[str] = []

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }

    async with httpx.AsyncClient(follow_redirects=True, timeout=20.0, headers=headers) as client:
        page = 1
        while page <= max_pages:
            url = f"https://skills.sh/" if page == 1 else f"https://skills.sh/?page={page}"
            logger.info("skills.sh: fetching leaderboard page %d: %s", page, url)

            try:
                r = await client.get(url)
                r.raise_for_status()
            except Exception as exc:
                msg = f"skills.sh page {page} fetch error: {exc}"
                logger.error(msg)
                errors.append(msg[:500])
                break

            soup = BeautifulSoup(r.text, "html.parser")

            # Find skill links of the form /{owner}/{repo}/{skill-name}
            page_skills = []
            for a in soup.find_all("a", href=True):
                href: str = a["href"]
                parts = href.strip("/").split("/")
                if len(parts) == 3 and all(re.match(r"^[\w\-\.]+$", p) for p in parts):
                    owner, repo, skill_name = parts
                    # Try to extract install counts from nearby text (e.g. "350.0K installs")
                    # The leaderboard renders install counts inside the row, look for sibling text
                    # containing "K" or "M" suffix (actual install metrics, not rank numbers)
                    parent = a.find_parent("div") or a.find_parent("tr") or a.find_parent("li")
                    parent_text = parent.get_text(separator=" ", strip=True) if parent else ""
                    # Only extract if the value looks like a real install count (has K/M suffix)
                    install_count = _extract_install_count_from_leaderboard(parent_text)

                    # Reconstruct GitHub URL: owner/repo is the GitHub repo
                    github_url = f"https://github.com/{owner}/{repo}"

                    skill = DiscoveredSkill(
                        name=skill_name.replace("-", " ").title(),
                        repo_url=github_url,
                        source_hub=SourceHub.SKILLS_SH,
                        trust_level=TrustLevel.MEDIUM,
                        description=f"Agent skill: {skill_name} from {owner}/{repo}",
                        stars=install_count,
                        owner=owner,
                        source_tags=["agent-skill", "skills-sh"],
                    )
                    page_skills.append(skill)

            logger.info("skills.sh page %d: found %d skill links (total: %d)",
                        page, len(page_skills), len(skills) + len(page_skills))
            skills.extend(page_skills)

            # Check for next page link
            has_next = bool(
                soup.select_one("a.next")
                or soup.select_one("a[rel='next']")
                or soup.select_one("li.next a")
            )
            # Also check for ?page= links that suggest more pages
            next_page_links = [
                a["href"] for a in soup.find_all("a", href=True)
                if f"page={page + 1}" in a.get("href", "")
            ]
            if next_page_links:
                has_next = True

            if not has_next or len(page_skills) == 0:
                logger.info("skills.sh: no more pages after page %d", page)
                break

            page += 1
            await asyncio.sleep(0.5)  # polite rate limiting

    batch = CrawlerBatch(
        source_hub=SourceHub.SKILLS_SH,
        crawled_at=datetime.now(timezone.utc).isoformat(),
        skills=skills,
        total_found=len(skills),
        errors=errors[:50],
    )
    return batch


def _extract_install_count_from_leaderboard(text: str) -> int:
    """
    Parse install counts like '350.0K' or '1.2M' from leaderboard row text.
    Only matches values with K/M suffix to avoid treating rank numbers as counts.
    Returns 0 if no K/M-suffixed number found.
    """
    # Must have K or M suffix to be an install count (rank numbers are plain integers)
    m = re.search(r"([\d,.]+)\s*([KkMm])\b", text)
    if not m:
        return 0
    val_str = m.group(1).replace(",", "")
    suffix = m.group(2).upper()
    try:
        val = float(val_str)
        if suffix == "K":
            return int(val * 1_000)
        if suffix == "M":
            return int(val * 1_000_000)
        return int(val)
    except ValueError:
        return 0


# ---------------------------------------------------------------------------
# skillsmp.com scraper — Cloudflare-protected, attempt with headers
# ---------------------------------------------------------------------------

async def scrape_skillsmp(max_pages: int = 10) -> CrawlerBatch:
    """
    skillsmp.com returns 403 (Cloudflare challenge) for automated requests.
    We attempt with realistic browser headers; if still blocked we document
    the failure.
    """
    skills: list[DiscoveredSkill] = []
    errors: list[str] = []

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
    }

    async with httpx.AsyncClient(follow_redirects=True, timeout=20.0, headers=headers) as client:
        page = 1
        while page <= max_pages:
            url = f"https://skillsmp.com/skills?page={page}"
            logger.info("skillsmp: fetching page %d: %s", page, url)

            try:
                r = await client.get(url)
                if r.status_code == 403:
                    msg = (
                        f"skillsmp page {page}: HTTP 403 Forbidden — "
                        "Cloudflare bot protection active. "
                        "Site requires JavaScript challenge or cookies to access."
                    )
                    logger.warning(msg)
                    errors.append(msg)
                    break
                r.raise_for_status()
            except httpx.HTTPStatusError as exc:
                msg = f"skillsmp page {page} HTTP error: {exc}"
                logger.error(msg)
                errors.append(msg[:500])
                break
            except Exception as exc:
                msg = f"skillsmp page {page} fetch error: {exc}"
                logger.error(msg)
                errors.append(msg[:500])
                break

            soup = BeautifulSoup(r.text, "html.parser")

            # Detect Cloudflare challenge page
            if "Attention Required" in r.text or "cf-challenge" in r.text or "cloudflare" in r.text.lower()[:500]:
                msg = (
                    f"skillsmp page {page}: Cloudflare JS challenge page returned. "
                    "Cannot proceed without a JS-capable browser."
                )
                logger.warning(msg)
                errors.append(msg)
                break

            # Parse skill cards
            cards = (
                soup.select("div.skill-card")
                or soup.select("article.skill")
                or soup.select("[data-skill]")
                or soup.select("div.card")
            )

            page_skills = []
            for card in cards:
                skill = _parse_skillsmp_card(card)
                if skill:
                    page_skills.append(skill)

            logger.info("skillsmp page %d: %d skills (total: %d)",
                        page, len(page_skills), len(skills) + len(page_skills))
            skills.extend(page_skills)

            # Check for next page
            has_next = bool(
                soup.select_one("a.next")
                or soup.select_one("a[rel='next']")
                or soup.select_one("li.next a")
            )
            if not has_next or len(page_skills) == 0:
                break

            page += 1
            await asyncio.sleep(0.5)

    batch = CrawlerBatch(
        source_hub=SourceHub.SKILLSMP,
        crawled_at=datetime.now(timezone.utc).isoformat(),
        skills=skills,
        total_found=len(skills),
        errors=errors[:50],
    )
    return batch


def _parse_skillsmp_card(card) -> DiscoveredSkill | None:
    name_el = (
        card.select_one("h2 a") or card.select_one("h3 a")
        or card.select_one(".skill-name a") or card.select_one("a.title")
    )
    if not name_el:
        return None
    name = name_el.get_text(strip=True)[:200]
    if not name:
        return None

    repo_url = ""
    for a in card.find_all("a", href=True):
        href: str = a["href"]
        if "github.com/" in href or "gitlab.com/" in href:
            repo_url = href
            break
    if not repo_url:
        href = name_el.get("href", "")
        repo_url = f"https://skillsmp.com{href}" if href.startswith("/") else href

    desc_el = card.select_one("p.description") or card.select_one(".skill-desc") or card.select_one("p")
    description = desc_el.get_text(strip=True)[:500] if desc_el else ""

    stars_el = card.select_one(".stars") or card.select_one("[data-stars]") or card.select_one(".star-count")
    stars = 0
    if stars_el:
        raw = stars_el.get("data-stars") or stars_el.get_text(strip=True)
        try:
            stars = int(str(raw).replace(",", "").strip())
        except (ValueError, TypeError):
            stars = 0

    owner = ""
    if repo_url and "github.com/" in repo_url:
        parts = repo_url.split("github.com/")
        if len(parts) > 1:
            segs = parts[1].strip("/").split("/")
            if segs:
                owner = segs[0][:200]

    return DiscoveredSkill(
        name=name,
        repo_url=repo_url,
        source_hub=SourceHub.SKILLSMP,
        trust_level=TrustLevel.LOW,
        description=description,
        stars=stars,
        owner=owner,
    )


# ---------------------------------------------------------------------------
# Save batch helper
# ---------------------------------------------------------------------------

def save_batch(batch: CrawlerBatch) -> Path:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    date_str = datetime.now(timezone.utc).strftime("%Y%m%d")
    counter = 0
    filename = f"batch-{batch.source_hub.value}-{date_str}-{counter}.json"
    filepath = OUTPUT_DIR / filename
    while filepath.exists():
        counter += 1
        filename = f"batch-{batch.source_hub.value}-{date_str}-{counter}.json"
        filepath = OUTPUT_DIR / filename
    filepath.write_text(batch.model_dump_json(indent=2), encoding="utf-8")
    logger.info("Saved batch -> %s (%d skills, %d errors)", filepath, len(batch.skills), len(batch.errors))
    return filepath


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def main(max_pages: int = 10) -> None:
    logger.info("=" * 60)
    logger.info("Running pending crawlers: skills_sh + skillsmp")
    logger.info("Max pages: %d", max_pages)
    logger.info("=" * 60)

    results = []

    # Run both crawlers
    for name, coro_fn in [("skills_sh", scrape_skills_sh), ("skillsmp", scrape_skillsmp)]:
        logger.info("")
        logger.info("--- %s ---", name)
        try:
            batch = await coro_fn(max_pages=max_pages)
            filepath = save_batch(batch)
            results.append({
                "hub": name,
                "status": "success",
                "skills_found": len(batch.skills),
                "errors": len(batch.errors),
                "file": str(filepath),
                "error_details": batch.errors[:3],
            })
        except Exception as exc:
            logger.exception("FAILED: %s", name)
            results.append({"hub": name, "status": "failed", "error": str(exc)})

    logger.info("")
    logger.info("=" * 60)
    logger.info("SUMMARY")
    logger.info("=" * 60)
    total = 0
    for r in results:
        if r["status"] == "success":
            total += r["skills_found"]
            logger.info("  %s: %d skills, %d errors -> %s", r["hub"], r["skills_found"], r["errors"], r["file"])
            for e in r.get("error_details", []):
                logger.warning("    error: %s", e)
        else:
            logger.error("  %s: FAILED - %s", r["hub"], r.get("error", "unknown"))
    logger.info("Total new skills discovered: %d", total)
    logger.info("=" * 60)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run skills_sh and skillsmp crawlers")
    parser.add_argument("--max-pages", type=int, default=10)
    args = parser.parse_args()
    asyncio.run(main(max_pages=args.max_pages))
