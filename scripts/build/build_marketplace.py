"""
SecureSkillHub Marketplace Builder.

Generates .claude-plugin/marketplace.json from the verified skill catalog,
listing security-verified MCP servers as installable plugins for Claude Code.

Also writes a copy to site/api/marketplace.json for API consumers.

Usage:
    python3 scripts/build/build_marketplace.py                # Build with 200 entries
    python3 scripts/build/build_marketplace.py --limit 50     # Cap at 50 entries
    python3 scripts/build/build_marketplace.py --dry-run      # Preview without writing
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Version
# ---------------------------------------------------------------------------

__version__ = "1.0.0"

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = PROJECT_ROOT / "data"
SKILLS_DIR = DATA_DIR / "skills"
PLUGIN_DIR = PROJECT_ROOT / ".claude-plugin"
API_DIR = PROJECT_ROOT / "site" / "api"

MARKETPLACE_PLUGIN_PATH = PLUGIN_DIR / "marketplace.json"
MARKETPLACE_API_PATH = API_DIR / "marketplace.json"

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SELF_ENTRY: dict[str, Any] = {
    "name": "secureskillhub",
    "source": ".",
    "description": "Browse, search, and install 11,000+ security-verified AI agent skills with verification badges",
    "version": "0.1.0",
    "author": {"name": "SecureSkillHub"},
}

MARKETPLACE_SCHEMA = "https://anthropic.com/claude-code/marketplace.schema.json"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _read_json(path: Path) -> Any:
    """Read and parse a JSON file."""
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def _write_json(path: Path, data: Any) -> None:
    """Write a Python object to a JSON file with consistent formatting."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False, sort_keys=False)
        fh.write("\n")


def _utc_now() -> str:
    """Return current UTC timestamp in ISO format."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _safe_int(value: Any, default: int = 0) -> int:
    """Safely convert a value to int, returning default on failure."""
    try:
        if value is None:
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def _slugify(name: str) -> str:
    """Convert a skill name to a URL-safe slug.

    Lowercases, replaces non-alphanumeric chars with hyphens, collapses
    consecutive hyphens, and strips leading/trailing hyphens.
    """
    slug = name.lower().strip()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    slug = re.sub(r"-{2,}", "-", slug)
    slug = slug.strip("-")
    return slug or "unnamed"


def _parse_github_owner_repo(repo_url: str) -> tuple[str, str] | None:
    """Extract (owner, repo) from a GitHub URL.

    Handles:
        https://github.com/owner/repo
        https://github.com/owner/repo.git
        https://github.com/owner/repo/

    Returns None if the URL is not a valid GitHub repo URL.
    """
    if not repo_url:
        return None
    parsed = urlparse(repo_url)
    if parsed.hostname not in ("github.com", "www.github.com"):
        return None
    parts = [p for p in parsed.path.strip("/").split("/") if p]
    if len(parts) < 2:
        return None
    owner = parts[0]
    repo = parts[1].removesuffix(".git")
    if not owner or not repo:
        return None
    return owner, repo


def _truncate(text: str, max_len: int = 200) -> str:
    """Truncate text to max_len, appending ellipsis if truncated."""
    if not text:
        return ""
    if len(text) <= max_len:
        return text
    return text[: max_len - 3].rstrip() + "..."


def _priority_score(skill: dict[str, Any]) -> int:
    """Compute priority score: max(stars, installs)."""
    stars = _safe_int(skill.get("stars"), 0)
    installs = _safe_int(skill.get("installs"), 0)
    return max(stars, installs)


# ---------------------------------------------------------------------------
# Skill filtering and entry generation
# ---------------------------------------------------------------------------


def load_all_skills() -> list[dict[str, Any]]:
    """Read all skill JSON files from data/skills/.

    Returns a list of raw skill dicts.
    """
    skills: list[dict[str, Any]] = []

    if not SKILLS_DIR.is_dir():
        logger.warning("Skills directory not found: %s", SKILLS_DIR)
        return skills

    skill_files = sorted(SKILLS_DIR.glob("*.json"))
    errors = 0

    for skill_file in skill_files:
        try:
            raw = _read_json(skill_file)
            if not isinstance(raw, dict) or "id" not in raw:
                logger.warning("Skipping invalid skill file (no id): %s", skill_file)
                errors += 1
                continue
            skills.append(raw)
        except Exception:
            logger.exception("Failed to load skill: %s", skill_file)
            errors += 1

    logger.info("Loaded %d skills from %s (%d errors)", len(skills), SKILLS_DIR, errors)
    return skills


def filter_marketplace_skills(skills: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Filter skills eligible for marketplace inclusion.

    Criteria:
      - verification_status == "pass"
      - NOT tagged repo_unavailable
      - Has a valid GitHub repo_url (owner/repo extractable)
    """
    eligible: list[dict[str, Any]] = []

    for skill in skills:
        # Must be verified pass
        status = str(skill.get("verification_status") or "").strip().lower()
        if status != "pass":
            continue

        # Must not be repo_unavailable
        tags = skill.get("tags") or []
        if "repo_unavailable" in tags:
            continue

        # Must have a valid GitHub repo_url
        repo_url = str(skill.get("repo_url") or "")
        if not _parse_github_owner_repo(repo_url):
            continue

        eligible.append(skill)

    logger.info(
        "Filtered to %d marketplace-eligible skills (from %d total)",
        len(eligible),
        len(skills),
    )
    return eligible


def build_plugin_entry(skill: dict[str, Any]) -> dict[str, Any]:
    """Convert a skill dict into a marketplace plugin entry."""
    repo_url = str(skill.get("repo_url") or "")
    parsed = _parse_github_owner_repo(repo_url)

    # This should not happen since we filtered, but guard anyway
    if not parsed:
        raise ValueError(f"Cannot parse repo_url: {repo_url}")

    owner, repo = parsed

    # Build source string with optional commit pinning
    verified_commit = str(skill.get("verified_commit") or "").strip()
    source = f"github:{owner}/{repo}"

    # Description from one_liner or description
    description = str(skill.get("one_liner") or skill.get("description") or "")
    description = _truncate(description, 200)

    # Verification metadata
    verification: dict[str, Any] = {
        "status": str(skill.get("verification_status") or "unverified"),
        "score": _safe_int(skill.get("overall_score"), 0),
        "risk_level": str(skill.get("risk_level") or "info"),
    }
    if verified_commit:
        verification["verified_commit"] = verified_commit

    entry: dict[str, Any] = {
        "name": _slugify(skill.get("name") or repo),
        "source": source,
        "description": description,
        "version": "0.1.0",
        "author": {"name": owner},
        "verification": verification,
    }

    # Include commit-pinned sha if available
    if verified_commit:
        entry["sha"] = verified_commit

    return entry


# ---------------------------------------------------------------------------
# Main build
# ---------------------------------------------------------------------------


def build_marketplace(
    skills: list[dict[str, Any]],
    limit: int = 200,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Build the marketplace manifest from verified skills.

    Steps:
      1. Filter to eligible skills
      2. Sort by priority (max(stars, installs)) descending
      3. Cap at limit entries
      4. Generate plugin entries
      5. Prepend SecureSkillHub self-entry
      6. Write to .claude-plugin/marketplace.json and site/api/marketplace.json
    """
    # Filter
    eligible = filter_marketplace_skills(skills)

    # Sort by priority descending
    eligible.sort(key=_priority_score, reverse=True)

    # Cap
    capped = eligible[:limit]
    logger.info(
        "Selected top %d skills (from %d eligible, limit=%d)",
        len(capped),
        len(eligible),
        limit,
    )

    # Generate entries
    plugins: list[dict[str, Any]] = [SELF_ENTRY]
    skipped = 0

    for skill in capped:
        try:
            entry = build_plugin_entry(skill)
            plugins.append(entry)
        except Exception:
            logger.exception(
                "Failed to build entry for skill %s", skill.get("id", "?")
            )
            skipped += 1

    if skipped:
        logger.warning("Skipped %d skills due to errors", skipped)

    # Build manifest
    manifest: dict[str, Any] = {
        "$schema": MARKETPLACE_SCHEMA,
        "name": "secureskillhub-marketplace",
        "description": (
            "Security-verified AI skills marketplace — "
            f"{len(eligible)} verified skills with 5-agent adversarial security pipeline"
        ),
        "version": "1.0.0",
        "generated_at": _utc_now(),
        "generator": f"build_marketplace.py v{__version__}",
        "owner": {
            "name": "SecureSkillHub",
            "url": "https://dallas05ll.github.io/SecureSkillHub",
        },
        "total_plugins": len(plugins),
        "plugins": plugins,
    }

    if dry_run:
        logger.info("[DRY RUN] Would write %d plugins. Skipping file writes.", len(plugins))
        # Print first few entries as preview
        preview = json.dumps(manifest, indent=2, ensure_ascii=False)
        # Truncate preview for dry-run output
        lines = preview.split("\n")
        if len(lines) > 80:
            print("\n".join(lines[:80]))
            print(f"  ... ({len(lines) - 80} more lines)")
        else:
            print(preview)
    else:
        _write_json(MARKETPLACE_PLUGIN_PATH, manifest)
        logger.info("Wrote %s (%d plugins)", MARKETPLACE_PLUGIN_PATH, len(plugins))

        _write_json(MARKETPLACE_API_PATH, manifest)
        logger.info("Wrote %s (%d plugins)", MARKETPLACE_API_PATH, len(plugins))

    return manifest


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    """Parse arguments and run the marketplace build."""
    parser = argparse.ArgumentParser(
        description="Build Claude Code Plugin Marketplace from verified skill catalog.",
        epilog=(
            "Examples:\n"
            "  python3 scripts/build/build_marketplace.py                # Build with 200 entries\n"
            "  python3 scripts/build/build_marketplace.py --limit 50     # Cap at 50\n"
            "  python3 scripts/build/build_marketplace.py --dry-run      # Preview only\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=200,
        help="Maximum number of plugin entries (default: 200)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview output without writing files",
    )
    args = parser.parse_args()

    started = time.monotonic()
    logger.info("=" * 60)
    logger.info("SecureSkillHub Marketplace Builder v%s", __version__)
    logger.info("=" * 60)

    # Load skills
    skills = load_all_skills()
    if not skills:
        logger.error("No skills found. Aborting.")
        sys.exit(1)

    # Build marketplace
    manifest = build_marketplace(skills, limit=args.limit, dry_run=args.dry_run)

    elapsed = time.monotonic() - started

    # Summary stats
    plugins = manifest.get("plugins", [])
    external = [p for p in plugins if p.get("source") != "."]
    with_commit = sum(1 for p in external if p.get("sha"))

    logger.info("=" * 60)
    logger.info("Marketplace build complete in %.2fs", elapsed)
    logger.info("  Total skills loaded:     %d", len(skills))
    logger.info("  Total plugins:           %d (1 self + %d external)", len(plugins), len(external))
    logger.info("  Commit-pinned:           %d / %d", with_commit, len(external))
    if external:
        scores = [p.get("verification", {}).get("score", 0) for p in external]
        logger.info("  Score range:             %d - %d", min(scores), max(scores))
    if not args.dry_run:
        logger.info("  Output (plugin):         %s", MARKETPLACE_PLUGIN_PATH)
        logger.info("  Output (API):            %s", MARKETPLACE_API_PATH)
    logger.info("=" * 60)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        stream=sys.stdout,
    )
    main()
