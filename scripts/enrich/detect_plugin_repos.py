#!/usr/bin/env python3
"""
Detect skills whose GitHub repos contain Claude Code plugin manifests.

Checks each skill's repo for .claude-plugin/plugin.json (or root plugin.json)
using the GitHub API (no clone needed). Sets has_plugin_json=true on matches.

Usage:
    python3 scripts/enrich/detect_plugin_repos.py                    # Check all unscanned
    python3 scripts/enrich/detect_plugin_repos.py --recheck          # Re-check all
    python3 scripts/enrich/detect_plugin_repos.py --batch-size 100   # Limit batch
    python3 scripts/enrich/detect_plugin_repos.py --dry-run          # Preview only
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
logger = logging.getLogger("detect_plugin_repos")

SKILLS_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "skills"

# GitHub API rate limit: 60 req/hr unauthenticated, 5000 with GITHUB_TOKEN / gh auth
RATE_LIMIT_DELAY = 0.15  # seconds between API calls

# Paths to check in repos (in priority order)
PLUGIN_PATHS = [
    ".claude-plugin/plugin.json",
    "plugin.json",
    ".claude/plugin.json",
]


def extract_owner_repo(repo_url: str) -> tuple[str, str] | None:
    """Extract (owner, repo) from a GitHub URL."""
    match = re.match(
        r"https?://github\.com/([^/]+)/([^/]+?)(?:\.git)?/?$",
        repo_url.strip(),
    )
    if match:
        return match.group(1), match.group(2)
    return None


def check_file_exists(owner: str, repo: str, path: str) -> bool:
    """Check if a file exists in a GitHub repo using gh api."""
    try:
        result = subprocess.run(
            ["gh", "api", f"repos/{owner}/{repo}/contents/{path}", "--jq", ".type"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        return result.returncode == 0 and result.stdout.strip() == "file"
    except (subprocess.TimeoutExpired, Exception):
        return False


def detect_plugin(owner: str, repo: str) -> bool:
    """Check if a repo has any Claude Code plugin manifest."""
    for path in PLUGIN_PATHS:
        if check_file_exists(owner, repo, path):
            return True
    return False


def main(
    batch_size: int = 0,
    recheck: bool = False,
    dry_run: bool = False,
) -> None:
    logger.info("=" * 60)
    logger.info("Claude Code Plugin Detection")
    logger.info("=" * 60)

    # Load all skills
    skills: list[tuple[Path, dict]] = []
    for f in sorted(SKILLS_DIR.glob("*.json")):
        try:
            data = json.loads(f.read_text())
            skills.append((f, data))
        except Exception:
            logger.warning("Failed to load: %s", f)

    logger.info("Loaded %d skill files", len(skills))

    # Filter to skills needing detection
    to_check: list[tuple[Path, dict, str, str]] = []
    skipped_unavailable = 0
    skipped_already = 0

    for filepath, data in skills:
        tags = data.get("tags", [])

        # Skip unavailable repos
        if "repo_unavailable" in tags:
            skipped_unavailable += 1
            continue

        # Skip already-checked (unless --recheck)
        if not recheck and data.get("has_plugin_json") is not None:
            skipped_already += 1
            continue

        repo_url = data.get("repo_url", "")
        parsed = extract_owner_repo(repo_url)
        if parsed:
            owner, repo = parsed
            if not re.match(r'^[a-zA-Z0-9._-]+$', owner) or not re.match(r'^[a-zA-Z0-9._-]+$', repo):
                continue
            to_check.append((filepath, data, owner, repo))

    logger.info("Skipped %d unavailable, %d already checked", skipped_unavailable, skipped_already)

    if batch_size > 0:
        to_check = to_check[:batch_size]

    logger.info("%d skills to check for plugin manifests", len(to_check))

    if not to_check:
        logger.info("Nothing to check!")
        return

    # Check each repo
    found = 0
    not_found = 0
    errors = 0

    for i, (filepath, data, owner, repo) in enumerate(to_check, 1):
        try:
            has_plugin = detect_plugin(owner, repo)
            data["has_plugin_json"] = has_plugin

            if has_plugin:
                found += 1
                logger.info("  FOUND plugin: %s/%s (%s)", owner, repo, data.get("name", "?"))
            else:
                not_found += 1

            if not dry_run:
                filepath.write_text(json.dumps(data, indent=2))

            if i % 50 == 0:
                logger.info("  Progress: %d/%d (found: %d)", i, len(to_check), found)

        except Exception:
            logger.exception("Error checking %s/%s", owner, repo)
            errors += 1

        time.sleep(RATE_LIMIT_DELAY)

    logger.info("")
    logger.info("=" * 60)
    logger.info("DETECTION SUMMARY")
    logger.info("=" * 60)
    logger.info("  Total checked:    %d", len(to_check))
    logger.info("  Has plugin.json:  %d", found)
    logger.info("  No plugin.json:   %d", not_found)
    logger.info("  Errors:           %d", errors)
    if dry_run:
        logger.info("  [DRY RUN — no files written]")
    logger.info("=" * 60)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Detect Claude Code plugin manifests in skill repos.",
    )
    parser.add_argument("--batch-size", type=int, default=0, help="Limit number of repos to check (0=all)")
    parser.add_argument("--recheck", action="store_true", help="Re-check repos already scanned")
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing files")
    args = parser.parse_args()
    main(batch_size=args.batch_size, recheck=args.recheck, dry_run=args.dry_run)
