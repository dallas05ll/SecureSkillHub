#!/usr/bin/env python3
"""
Process discovered skill batches into data/skills/ JSON files.

Reads all batch-*.json files from data/discovered/, deduplicates by
repo_url (preferring Glama entries for richer descriptions), generates
deterministic skill IDs, and writes individual skill JSON files.

Usage:
    python3 process_discovered.py [--limit N]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import re
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("process_discovered")

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DISCOVERED_DIR = PROJECT_ROOT / "data" / "discovered"
SKILLS_DIR = PROJECT_ROOT / "data" / "skills"

# Priority order for deduplication (higher = preferred)
SOURCE_PRIORITY = {
    "glama": 10,     # Rich descriptions, license info
    "mcp_so": 5,     # Good volume but sparser data
    "skillsmp": 3,   # Claude Code skills via skilldb mirror, install-count proxy
    "skills_sh": 3,  # skills.sh directory
}


def load_all_batches() -> list[dict]:
    """Load all batch JSON files and return flat list of skill dicts."""
    all_skills = []
    for batch_file in sorted(DISCOVERED_DIR.glob("batch-*.json")):
        logger.info("Loading %s", batch_file.name)
        data = json.loads(batch_file.read_text())
        skills = data.get("skills", [])
        source = data.get("source_hub", "unknown")
        for s in skills:
            s["_source_hub"] = source
            s["_batch_file"] = batch_file.name
        all_skills.extend(skills)
    return all_skills


def normalize_repo_url(url: str) -> str:
    """Normalize GitHub URL for deduplication."""
    url = url.strip().rstrip("/").lower()
    url = re.sub(r"\.git$", "", url)
    url = re.sub(r"^https?://", "", url)
    url = re.sub(r"^www\.", "", url)
    # Remove /tree/main etc.
    url = re.sub(r"/tree/.*$", "", url)
    return url


def deduplicate(skills: list[dict]) -> list[dict]:
    """Deduplicate by normalized repo_url, preferring higher-priority sources."""
    by_url: dict[str, dict] = {}

    for skill in skills:
        repo = skill.get("repo_url", "")
        if not repo:
            continue
        key = normalize_repo_url(repo)
        if not key:
            continue

        source = skill.get("_source_hub", skill.get("source_hub", ""))
        priority = SOURCE_PRIORITY.get(source, 0)

        existing = by_url.get(key)
        if existing is None:
            skill["_priority"] = priority
            by_url[key] = skill
        else:
            if priority > existing.get("_priority", 0):
                skill["_priority"] = priority
                by_url[key] = skill
            elif priority == existing.get("_priority", 0):
                # Merge: prefer the one with a description
                if not existing.get("description") and skill.get("description"):
                    skill["_priority"] = priority
                    by_url[key] = skill

    return list(by_url.values())


def make_skill_id(name: str, repo_url: str) -> str:
    """Generate a deterministic skill ID."""
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:40]
    ns = uuid.UUID("a1b2c3d4-e5f6-7890-abcd-ef1234567890")
    suffix = str(uuid.uuid5(ns, repo_url))[:8]
    return f"{slug}-{suffix}"


def skill_to_json(skill: dict) -> dict:
    """Convert a discovered skill dict to our data/skills/ format."""
    name = skill.get("name", "Unknown")
    repo_url = skill.get("repo_url", "")
    skill_id = make_skill_id(name, repo_url)

    # Extract owner from repo_url if not set
    owner = skill.get("owner", "")
    if not owner and "github.com/" in repo_url:
        parts = repo_url.split("github.com/")
        if len(parts) > 1:
            segments = parts[1].strip("/").split("/")
            if segments:
                owner = segments[0]

    # Determine source hub
    source = skill.get("_source_hub", skill.get("source_hub", "unknown"))

    # Tags
    tags = skill.get("source_tags", [])
    if not tags:
        tags = skill.get("tags", [])

    # Determine skill_type (default mcp_server for backwards compat)
    skill_type = skill.get("skill_type", "mcp_server")
    # Handle enum values from Pydantic
    if hasattr(skill_type, "value"):
        skill_type = skill_type.value

    return {
        "id": skill_id,
        "name": name,
        "description": skill.get("description", ""),
        "repo_url": repo_url,
        "source_hub": source,
        "skill_type": skill_type,
        "owner": owner,
        "stars": skill.get("stars", 0),
        "primary_language": "unknown",
        "tags": tags,
        "verification_status": "unverified",
        "overall_score": 0,
        "risk_level": "info",
        "verified_commit": None,
        "scan_summary": None,
    }


def main(limit: int = 0, merge: bool = False, skip_reachability: bool = False) -> None:
    logger.info("=" * 60)
    logger.info("Processing discovered skills (merge=%s, reachability=%s)", merge, not skip_reachability)
    logger.info("=" * 60)

    # Load all batches
    all_skills = load_all_batches()
    logger.info("Loaded %d raw skills from all batches", len(all_skills))

    # Deduplicate
    unique = deduplicate(all_skills)
    logger.info("After deduplication: %d unique skills", len(unique))

    # Apply limit
    if limit > 0:
        unique = unique[:limit]
        logger.info("Limited to %d skills", limit)

    SKILLS_DIR.mkdir(parents=True, exist_ok=True)

    # Reachability check — filter out unreachable repos before writing
    unreachable_skills = []
    if not skip_reachability:
        from src.reachability import check_and_filter_skills, log_to_skill_manager

        logger.info("Checking repo reachability for %d skills...", len(unique))
        reachable, unreachable_skills = check_and_filter_skills(
            [{"repo_url": s.get("repo_url", "")} for s in unique],
            source="batch_crawl",
            workers=15,
            timeout=15,
        )
        # Build a set of reachable URLs for filtering
        reachable_urls = {s["repo_url"] for s in reachable}
        before = len(unique)
        unique = [s for s in unique if s.get("repo_url", "") in reachable_urls]
        skipped = before - len(unique)
        logger.info("Reachability: %d reachable, %d unreachable (skipped)", len(unique), skipped)
    else:
        logger.info("Skipping reachability check (--skip-reachability)")

    # Load existing skill data to preserve enrichment (stars, verification, etc.)
    existing_data: dict[str, dict] = {}
    if merge:
        for f in SKILLS_DIR.glob("*.json"):
            try:
                data = json.loads(f.read_text())
                # Index by normalized repo_url for matching
                repo = normalize_repo_url(data.get("repo_url", ""))
                if repo:
                    existing_data[repo] = data
            except Exception:
                pass
        logger.info("Loaded %d existing skills for merge", len(existing_data))
    else:
        # Remove old files if not merging
        old_files = list(SKILLS_DIR.glob("*.json"))
        if old_files:
            logger.info("Removing %d old skill files", len(old_files))
            for f in old_files:
                f.unlink()

    # Write skill files
    written = 0
    merged = 0
    for skill_dict in unique:
        output = skill_to_json(skill_dict)
        filename = f"{output['id']}.json"
        filepath = SKILLS_DIR / filename

        # Merge with existing data if available
        repo_key = normalize_repo_url(output.get("repo_url", ""))
        if repo_key in existing_data:
            old = existing_data[repo_key]
            # Preserve enrichment fields from existing data
            for key in ("stars", "verification_status", "overall_score",
                        "risk_level", "verified_commit", "scan_summary",
                        "scan_date", "tags", "skill_type", "verification_level"):
                if old.get(key) and (not output.get(key) or output[key] in (0, "unverified", "info", None, [])):
                    output[key] = old[key]
            merged += 1

        # Also preserve stars from discovered data
        discovered_stars = skill_dict.get("stars", 0)
        if discovered_stars > output.get("stars", 0):
            output["stars"] = discovered_stars

        filepath.write_text(json.dumps(output, indent=2), encoding="utf-8")
        written += 1

    logger.info("Wrote %d skill files (%d merged with existing data)", written, merged)

    # Update stats
    stats_file = PROJECT_ROOT / "data" / "stats.json"
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # Count verification statuses, types, tiers from ALL skills on disk
    total_on_disk = 0
    verified = 0
    failed = 0
    pending = 0
    sources: dict[str, int] = {}
    skill_types: dict[str, int] = {}
    verification_tiers: dict[str, int] = {}
    has_scan = 0
    for f in SKILLS_DIR.glob("*.json"):
        data = json.loads(f.read_text())
        total_on_disk += 1
        status = data.get("verification_status", "unverified")
        if status == "pass":
            verified += 1
        elif status == "fail":
            failed += 1
        elif status == "manual_review":
            pending += 1
        src = data.get("source_hub", "unknown")
        sources[src] = sources.get(src, 0) + 1
        st = data.get("skill_type", "mcp_server")
        skill_types[st] = skill_types.get(st, 0) + 1
        vl = data.get("verification_level", "")
        if vl:
            verification_tiers[vl] = verification_tiers.get(vl, 0) + 1
        if data.get("scan_report") or data.get("findings_summary"):
            has_scan += 1

    stats = {
        "total_skills": total_on_disk,
        "verified_skills": verified,
        "failed_skills": failed,
        "pending_review": pending,
        "total_scans_run": has_scan,
        "last_crawl": now,
        "last_build": now,
        "sources": sources,
        "skill_types": skill_types,
        "verification_tiers": verification_tiers,
    }
    stats_file.write_text(json.dumps(stats, indent=2), encoding="utf-8")
    logger.info("Updated stats.json: %s", json.dumps(sources))

    # Log to skills manager
    if not skip_reachability:
        log_to_skill_manager(
            check_type="crawl_run",
            findings={
                "source": "batch_crawl",
                "total_discovered": len(all_skills),
                "after_dedup": len(unique) + len(unreachable_skills),
                "reachable": len(unique),
                "unreachable_skipped": len(unreachable_skills),
                "written": written,
                "merged": merged,
            },
        )

    logger.info("=" * 60)
    logger.info("Done! %d skills ready (%d merged, %d unreachable skipped)", written, merged, len(unreachable_skills))
    logger.info("=" * 60)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--limit", type=int, default=0,
        help="Limit number of skills to process (0 = all)",
    )
    parser.add_argument(
        "--merge", action="store_true",
        help="Merge with existing skills (preserve stars, verification data)",
    )
    parser.add_argument(
        "--skip-reachability", action="store_true",
        help="Skip repo reachability check (faster, but may include dead repos)",
    )
    args = parser.parse_args()
    main(limit=args.limit, merge=args.merge, skip_reachability=args.skip_reachability)
