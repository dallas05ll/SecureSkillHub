#!/usr/bin/env python3
"""
Build star-priority verification queue and tag-indexed catalog.

Generates:
  1. data/verify-queue.json — unverified skills sorted by stars (highest first)
  2. site/api/skills/by-tag/{tag_id}.json — tag-indexed, sorted by stars
  3. site/api/skills/by-tier/{tier}.json — star tier buckets
  4. Updates site/api/skills/index.json with star-sorted order

Usage:
    python3 build_priority.py
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("build_priority")

PROJECT_ROOT = Path(__file__).resolve().parent
SKILLS_DIR = PROJECT_ROOT / "data" / "skills"
API_DIR = PROJECT_ROOT / "site" / "api"
BY_TAG_DIR = API_DIR / "skills" / "by-tag"
BY_TIER_DIR = API_DIR / "skills" / "by-tier"

# Star tier definitions
TIERS = [
    ("tier-1", 1000, float("inf"), "1000+ stars — verify immediately"),
    ("tier-2", 100, 999, "100-999 stars — high priority"),
    ("tier-3", 10, 99, "10-99 stars — medium priority"),
    ("tier-4", 1, 9, "1-9 stars — standard priority"),
    ("tier-5", 0, 0, "0 stars — low priority"),
]


def load_all_skills() -> list[dict]:
    """Load all skill JSON files."""
    skills = []
    for f in sorted(SKILLS_DIR.glob("*.json")):
        try:
            data = json.loads(f.read_text())
            skills.append(data)
        except Exception:
            continue
    return skills


def skill_summary(skill: dict) -> dict:
    """Create a compact summary for index files."""
    return {
        "id": skill.get("id", ""),
        "name": skill.get("name", ""),
        "description": skill.get("description", "")[:200],
        "repo_url": skill.get("repo_url", ""),
        "stars": skill.get("stars", 0),
        "tags": skill.get("tags", []),
        "verification_status": skill.get("verification_status", "unverified"),
        "overall_score": skill.get("overall_score", 0),
        "risk_level": skill.get("risk_level", "info"),
        "source_hub": skill.get("source_hub", "unknown"),
        "skill_type": skill.get("skill_type", "mcp_server"),
        "owner": skill.get("owner", ""),
    }


def get_tier(stars: int) -> str:
    """Determine which star tier a skill belongs to."""
    if stars >= 1000:
        return "tier-1"
    if stars >= 100:
        return "tier-2"
    if stars >= 10:
        return "tier-3"
    if stars >= 1:
        return "tier-4"
    return "tier-5"


def main() -> None:
    logger.info("=" * 60)
    logger.info("Building Priority Queue & Tag-Indexed Catalog")
    logger.info("=" * 60)

    skills = load_all_skills()
    logger.info("Loaded %d skills", len(skills))

    # Sort all skills by stars descending
    skills.sort(key=lambda s: (-s.get("stars", 0), s.get("name", "")))

    # === 1. Verification Queue ===
    unverified = [s for s in skills if s.get("verification_status") == "unverified"]
    queue = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "total_unverified": len(unverified),
        "description": "Unverified skills sorted by GitHub stars (highest priority first)",
        "tiers": {},
        "queue": [skill_summary(s) for s in unverified],
    }

    # Tier breakdown in queue
    for tier_id, min_stars, max_stars, desc in TIERS:
        tier_skills = [s for s in unverified
                       if min_stars <= s.get("stars", 0) <= max_stars]
        queue["tiers"][tier_id] = {
            "description": desc,
            "count": len(tier_skills),
            "min_stars": min_stars,
        }

    queue_file = PROJECT_ROOT / "data" / "verify-queue.json"
    queue_file.write_text(json.dumps(queue, indent=2))
    logger.info("Verification queue: %d unverified skills", len(unverified))
    for tier_id, _, _, desc in TIERS:
        count = queue["tiers"][tier_id]["count"]
        if count > 0:
            logger.info("  %s: %d skills (%s)", tier_id, count, desc)

    # === 2. Tag-Indexed Catalog ===
    BY_TAG_DIR.mkdir(parents=True, exist_ok=True)

    # Collect skills by tag
    by_tag: dict[str, list[dict]] = {}
    for skill in skills:
        for tag in skill.get("tags", []):
            by_tag.setdefault(tag, []).append(skill)

    # Write per-tag files (already sorted by stars from the global sort)
    tag_index = {}
    for tag, tag_skills in sorted(by_tag.items()):
        tag_file = BY_TAG_DIR / f"{tag}.json"
        tag_data = {
            "tag": tag,
            "total": len(tag_skills),
            "verified": sum(1 for s in tag_skills if s.get("verification_status") == "pass"),
            "top_stars": tag_skills[0].get("stars", 0) if tag_skills else 0,
            "skills": [skill_summary(s) for s in tag_skills],
        }
        tag_file.write_text(json.dumps(tag_data, indent=2))
        tag_index[tag] = {
            "total": len(tag_skills),
            "verified": tag_data["verified"],
            "top_stars": tag_data["top_stars"],
        }

    # Write tag index
    tag_index_file = BY_TAG_DIR / "index.json"
    tag_index_file.write_text(json.dumps(tag_index, indent=2))
    logger.info("Tag-indexed catalog: %d tags", len(by_tag))

    # === 3. Star Tier Buckets ===
    BY_TIER_DIR.mkdir(parents=True, exist_ok=True)

    for tier_id, min_stars, max_stars, desc in TIERS:
        if max_stars == float("inf"):
            tier_skills = [s for s in skills if s.get("stars", 0) >= min_stars]
        else:
            tier_skills = [s for s in skills
                           if min_stars <= s.get("stars", 0) <= max_stars]

        tier_file = BY_TIER_DIR / f"{tier_id}.json"
        tier_data = {
            "tier": tier_id,
            "description": desc,
            "total": len(tier_skills),
            "verified": sum(1 for s in tier_skills if s.get("verification_status") == "pass"),
            "skills": [skill_summary(s) for s in tier_skills],
        }
        tier_file.write_text(json.dumps(tier_data, indent=2))
        logger.info("  %s: %d skills", tier_id, len(tier_skills))

    # === 4. Update main index with star sort ===
    index_file = API_DIR / "skills" / "index.json"
    index_data = {
        "total": len(skills),
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "sort": "stars_desc",
        "skills": [skill_summary(s) for s in skills],
    }
    index_file.write_text(json.dumps(index_data, indent=2))
    logger.info("Updated main index: %d skills sorted by stars", len(skills))

    logger.info("=" * 60)
    logger.info("Done!")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
