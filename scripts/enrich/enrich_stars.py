#!/usr/bin/env python3
"""
Enrich skill JSON files with GitHub star counts.

Uses `gh api` (GitHub CLI) to fetch stargazers_count for each
skill that has a github.com repo URL. Updates the skill files in-place.

Usage:
    python3 enrich_stars.py [--batch-size 50] [--skip-existing]
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import subprocess
import sys
import time
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("enrich_stars")

SKILLS_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "skills"

# GitHub API rate limit: 5000 req/hr authenticated
# We batch requests and add small delays to stay safe
RATE_LIMIT_DELAY = 0.1  # seconds between requests


def extract_owner_repo(repo_url: str) -> tuple[str, str] | None:
    """Extract (owner, repo) from a GitHub URL."""
    match = re.match(
        r"https?://github\.com/([^/]+)/([^/]+?)(?:\.git)?/?$",
        repo_url.strip(),
    )
    if match:
        return match.group(1), match.group(2)
    return None


def fetch_stars_gh_api(owner: str, repo: str) -> int | None:
    """Fetch star count using gh api command."""
    try:
        result = subprocess.run(
            ["gh", "api", f"repos/{owner}/{repo}", "--jq", ".stargazers_count"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if result.returncode == 0 and result.stdout.strip():
            return int(result.stdout.strip())
    except (subprocess.TimeoutExpired, ValueError, Exception):
        pass
    return None


def fetch_stars_batch(owner_repos: list[tuple[str, str, str]]) -> dict[str, int]:
    """Fetch stars for a batch of repos. Returns {skill_id: stars}."""
    results = {}
    for skill_id, owner, repo in owner_repos:
        stars = fetch_stars_gh_api(owner, repo)
        if stars is not None:
            results[skill_id] = stars
        time.sleep(RATE_LIMIT_DELAY)
    return results


def main(batch_size: int = 50, skip_existing: bool = False) -> None:
    logger.info("=" * 60)
    logger.info("GitHub Star Enrichment")
    logger.info("=" * 60)

    # Load all skills
    skills = []
    for f in sorted(SKILLS_DIR.glob("*.json")):
        data = json.loads(f.read_text())
        skills.append((f, data))

    logger.info("Loaded %d skill files", len(skills))

    # Filter to skills needing star enrichment
    skipped_unavailable = 0
    to_enrich = []
    for filepath, data in skills:
        repo_url = data.get("repo_url", "")
        current_stars = data.get("stars", 0)
        tags = data.get("tags", [])

        # Skip repos marked as unavailable — no point hitting GitHub API for dead repos
        if "repo_unavailable" in tags:
            skipped_unavailable += 1
            continue

        if skip_existing and current_stars > 0:
            continue

        parsed = extract_owner_repo(repo_url)
        if parsed:
            owner, repo = parsed
            to_enrich.append((filepath, data, owner, repo))

    logger.info("Skipped %d skills with repo_unavailable tag", skipped_unavailable)

    logger.info("%d skills have GitHub URLs needing star enrichment", len(to_enrich))

    if not to_enrich:
        logger.info("Nothing to enrich!")
        return

    # Process in batches
    enriched = 0
    failed = 0
    star_distribution = {"1000+": 0, "100-999": 0, "10-99": 0, "1-9": 0, "0": 0}

    for i in range(0, len(to_enrich), batch_size):
        batch = to_enrich[i:i + batch_size]
        batch_num = i // batch_size + 1
        total_batches = (len(to_enrich) + batch_size - 1) // batch_size

        logger.info(
            "Batch %d/%d: enriching %d skills...",
            batch_num, total_batches, len(batch),
        )

        for filepath, data, owner, repo in batch:
            stars = fetch_stars_gh_api(owner, repo)

            if stars is not None:
                data["stars"] = stars
                filepath.write_text(json.dumps(data, indent=2))
                enriched += 1

                # Track distribution
                if stars >= 1000:
                    star_distribution["1000+"] += 1
                elif stars >= 100:
                    star_distribution["100-999"] += 1
                elif stars >= 10:
                    star_distribution["10-99"] += 1
                elif stars >= 1:
                    star_distribution["1-9"] += 1
                else:
                    star_distribution["0"] += 1

                if enriched % 25 == 0:
                    logger.info(
                        "  Progress: %d/%d enriched (failed: %d)",
                        enriched, len(to_enrich), failed,
                    )
            else:
                failed += 1

            time.sleep(RATE_LIMIT_DELAY)

    logger.info("")
    logger.info("=" * 60)
    logger.info("ENRICHMENT SUMMARY")
    logger.info("=" * 60)
    logger.info("  Total skills:  %d", len(skills))
    logger.info("  Enriched:      %d", enriched)
    logger.info("  Failed:        %d", failed)
    logger.info("  Star tiers:")
    for tier, count in star_distribution.items():
        logger.info("    %8s: %d", tier, count)
    logger.info("=" * 60)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch-size", type=int, default=50)
    parser.add_argument("--skip-existing", action="store_true")
    args = parser.parse_args()
    main(batch_size=args.batch_size, skip_existing=args.skip_existing)
