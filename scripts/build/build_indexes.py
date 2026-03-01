"""
SecureSkillHub Index Builder.

Generates compact index files in site/api/indexes/ so agents can efficiently
query the skills collection without reading thousands of individual JSON files.

Indexes generated:
  - manifest.json     — Compact per-skill summary (id, name, status, score, stars, ...)
  - by-status.json    — Skill IDs grouped by verification_status
  - by-risk.json      — Skill IDs grouped by risk_level
  - verify-queue.json — Unverified skills sorted by stars, tiered
  - lookup.json       — Hash-based ID prefix lookup (first 2 chars -> IDs)

Usage:
    python3 build_indexes.py                  # Build all indexes
    python3 build_indexes.py --only manifest  # Build just one index
    python3 build_indexes.py --only manifest --only by-status  # Build multiple
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Version
# ---------------------------------------------------------------------------

__version__ = "1.0.0"

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent
DATA_DIR = PROJECT_ROOT / "data"
SKILLS_DIR = DATA_DIR / "skills"
INDEXES_DIR = PROJECT_ROOT / "site" / "api" / "indexes"

# ---------------------------------------------------------------------------
# Status normalization (matches build_json.py / run_verify_strict_5agent.py)
# ---------------------------------------------------------------------------

STATUS_ALIASES: dict[str, str] = {
    "verified": "pass",
    "approved": "pass",
    "failed": "fail",
    "invalid": "fail",
    "review": "manual_review",
    "flagged": "manual_review",
    "updated-unverified": "updated_unverified",
}

CANONICAL_STATUSES = {"pass", "fail", "manual_review", "unverified", "updated_unverified"}
CANONICAL_RISK_LEVELS = {"critical", "high", "medium", "low", "info"}


def normalize_status(value: Any) -> str:
    """Normalize verification status to canonical values.

    Canonical statuses: pass, fail, manual_review, unverified, updated_unverified.
    """
    if not value:
        return "unverified"
    raw = str(value).strip().lower()
    if not raw:
        return "unverified"
    normalized = STATUS_ALIASES.get(raw, raw)
    return normalized if normalized in CANONICAL_STATUSES else "unverified"


def normalize_risk_level(value: Any) -> str:
    """Normalize risk_level to canonical values.

    Canonical levels: critical, high, medium, low, info.
    """
    if not value:
        return "info"
    raw = str(value).strip().lower()
    return raw if raw in CANONICAL_RISK_LEVELS else "info"


def _safe_int(value: Any, default: int = 0) -> int:
    """Safely convert a value to int, returning default on failure."""
    try:
        if value is None:
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


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


def _metadata(total_skills: int) -> dict[str, Any]:
    """Generate standard metadata block for every index file."""
    return {
        "generated_at": _utc_now(),
        "total_skills": total_skills,
        "generator": f"build_indexes.py v{__version__}",
    }


# ---------------------------------------------------------------------------
# Load skills
# ---------------------------------------------------------------------------

def load_all_skills() -> list[dict[str, Any]]:
    """Read all skill JSON files from data/skills/.

    Returns a list of raw skill dicts with normalized status/risk fields.
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


# ---------------------------------------------------------------------------
# Index builders
# ---------------------------------------------------------------------------

def build_manifest(skills: list[dict[str, Any]]) -> dict[str, Any]:
    """Generate compact manifest with essential fields only.

    Fields per skill: id, name, verification_status, overall_score, stars,
    verification_level, risk_level, repo_url.

    This lets agents scan the entire collection without reading 6K+ files.
    """
    logger.info("Building manifest.json ...")

    entries: list[dict[str, Any]] = []
    for skill in skills:
        entries.append({
            "id": skill.get("id", ""),
            "name": skill.get("name", ""),
            "verification_status": normalize_status(skill.get("verification_status")),
            "overall_score": _safe_int(skill.get("overall_score"), 0),
            "stars": _safe_int(skill.get("stars"), 0),
            "verification_level": str(skill.get("verification_level") or ""),
            "risk_level": normalize_risk_level(skill.get("risk_level")),
            "repo_url": str(skill.get("repo_url") or ""),
        })

    # Sort by stars descending for consistent ordering
    entries.sort(key=lambda s: s["stars"], reverse=True)

    output = {
        **_metadata(len(skills)),
        "skills": entries,
    }

    path = INDEXES_DIR / "manifest.json"
    _write_json(path, output)
    logger.info("  -> %s  (%d entries)", path, len(entries))
    return output


def build_by_status(skills: list[dict[str, Any]]) -> dict[str, Any]:
    """Group skill IDs by verification_status.

    Keys: pass, fail, manual_review, unverified, updated_unverified.
    Values: sorted lists of skill IDs.
    """
    logger.info("Building by-status.json ...")

    groups: dict[str, list[str]] = {status: [] for status in sorted(CANONICAL_STATUSES)}

    for skill in skills:
        status = normalize_status(skill.get("verification_status"))
        skill_id = skill.get("id", "")
        if skill_id:
            groups[status].append(skill_id)

    # Sort IDs within each group for deterministic output
    for status in groups:
        groups[status].sort()

    # Add counts summary
    counts = {status: len(ids) for status, ids in groups.items()}

    output = {
        **_metadata(len(skills)),
        "counts": counts,
        **groups,
    }

    path = INDEXES_DIR / "by-status.json"
    _write_json(path, output)
    logger.info("  -> %s  (pass=%d, fail=%d, manual_review=%d, unverified=%d, updated_unverified=%d)",
                path, counts["pass"], counts["fail"], counts["manual_review"],
                counts["unverified"], counts["updated_unverified"])
    return output


def build_by_risk(skills: list[dict[str, Any]]) -> dict[str, Any]:
    """Group skill IDs by risk_level.

    Keys: critical, high, medium, low, info.
    Values: sorted lists of skill IDs.
    """
    logger.info("Building by-risk.json ...")

    groups: dict[str, list[str]] = {level: [] for level in ["critical", "high", "medium", "low", "info"]}

    for skill in skills:
        risk = normalize_risk_level(skill.get("risk_level"))
        skill_id = skill.get("id", "")
        if skill_id:
            groups[risk].append(skill_id)

    # Sort IDs within each group for deterministic output
    for level in groups:
        groups[level].sort()

    counts = {level: len(ids) for level, ids in groups.items()}

    output = {
        **_metadata(len(skills)),
        "counts": counts,
        **groups,
    }

    path = INDEXES_DIR / "by-risk.json"
    _write_json(path, output)
    logger.info("  -> %s  (critical=%d, high=%d, medium=%d, low=%d, info=%d)",
                path, counts["critical"], counts["high"], counts["medium"],
                counts["low"], counts["info"])
    return output


def build_verify_queue(skills: list[dict[str, Any]]) -> dict[str, Any]:
    """Build prioritized verification queue: unverified skills sorted by stars.

    Tiers:
      - tier_1_1000plus: 1000+ stars
      - tier_2_100_999:  100-999 stars
      - tier_3_10_99:    10-99 stars
      - tier_4_1_9:      1-9 stars
      - tier_5_0:        0 stars
    """
    logger.info("Building verify-queue.json ...")

    # Filter to unverified skills only
    unverified = []
    for skill in skills:
        status = normalize_status(skill.get("verification_status"))
        if status == "unverified":
            unverified.append({
                "id": skill.get("id", ""),
                "stars": _safe_int(skill.get("stars"), 0),
                "name": skill.get("name", ""),
            })

    # Sort by stars descending
    unverified.sort(key=lambda s: s["stars"], reverse=True)

    # Split into tiers
    tiers: dict[str, list[dict[str, Any]]] = {
        "tier_1_1000plus": [],
        "tier_2_100_999": [],
        "tier_3_10_99": [],
        "tier_4_1_9": [],
        "tier_5_0": [],
    }

    for entry in unverified:
        stars = entry["stars"]
        if stars >= 1000:
            tiers["tier_1_1000plus"].append(entry)
        elif stars >= 100:
            tiers["tier_2_100_999"].append(entry)
        elif stars >= 10:
            tiers["tier_3_10_99"].append(entry)
        elif stars >= 1:
            tiers["tier_4_1_9"].append(entry)
        else:
            tiers["tier_5_0"].append(entry)

    tier_counts = {tier: len(entries) for tier, entries in tiers.items()}

    output = {
        **_metadata(len(skills)),
        "total_unverified": len(unverified),
        "tier_counts": tier_counts,
        **tiers,
    }

    path = INDEXES_DIR / "verify-queue.json"
    _write_json(path, output)
    logger.info("  -> %s  (%d unverified: t1=%d, t2=%d, t3=%d, t4=%d, t5=%d)",
                path, len(unverified),
                tier_counts["tier_1_1000plus"], tier_counts["tier_2_100_999"],
                tier_counts["tier_3_10_99"], tier_counts["tier_4_1_9"],
                tier_counts["tier_5_0"])
    return output


def build_lookup(skills: list[dict[str, Any]]) -> dict[str, Any]:
    """Build hash-based ID prefix lookup for O(1) bucket access.

    Maps first 2 characters of each skill ID to a list of matching skill IDs.
    """
    logger.info("Building lookup.json ...")

    buckets: dict[str, list[str]] = {}

    for skill in skills:
        skill_id = skill.get("id", "")
        if not skill_id:
            continue
        # Use first 2 characters as the bucket key.
        # Handle IDs shorter than 2 chars gracefully.
        prefix = skill_id[:2].lower() if len(skill_id) >= 2 else skill_id.lower()
        buckets.setdefault(prefix, []).append(skill_id)

    # Sort IDs within each bucket and sort bucket keys
    for prefix in buckets:
        buckets[prefix].sort()
    sorted_buckets = dict(sorted(buckets.items()))

    output = {
        **_metadata(len(skills)),
        "total_buckets": len(sorted_buckets),
        "avg_bucket_size": round(len(skills) / max(len(sorted_buckets), 1), 1),
        "buckets": sorted_buckets,
    }

    path = INDEXES_DIR / "lookup.json"
    _write_json(path, output)
    logger.info("  -> %s  (%d buckets, avg size %.1f)",
                path, len(sorted_buckets), output["avg_bucket_size"])
    return output


# ---------------------------------------------------------------------------
# Main orchestrator
# ---------------------------------------------------------------------------

ALL_INDEXES = {
    "manifest": build_manifest,
    "by-status": build_by_status,
    "by-risk": build_by_risk,
    "verify-queue": build_verify_queue,
    "lookup": build_lookup,
}


def main() -> None:
    """Orchestrate index building, write files, print stats."""
    parser = argparse.ArgumentParser(
        description="Build compact index files for SecureSkillHub agent access.",
        epilog="Examples:\n"
               "  python3 build_indexes.py                  # Build all indexes\n"
               "  python3 build_indexes.py --only manifest   # Build just manifest\n"
               "  python3 build_indexes.py --only manifest --only by-status\n",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--only",
        action="append",
        choices=list(ALL_INDEXES.keys()),
        metavar="INDEX",
        help="Build only specific index(es). Can be repeated. "
             f"Choices: {', '.join(ALL_INDEXES.keys())}",
    )
    args = parser.parse_args()

    # Determine which indexes to build
    if args.only:
        targets = {name: ALL_INDEXES[name] for name in args.only}
    else:
        targets = ALL_INDEXES

    started = time.monotonic()
    logger.info("=" * 60)
    logger.info("SecureSkillHub Index Builder v%s", __version__)
    logger.info("=" * 60)

    # 1. Load all skills
    skills = load_all_skills()

    if not skills:
        logger.error("No skills found. Aborting.")
        sys.exit(1)

    # 2. Ensure output directory exists
    INDEXES_DIR.mkdir(parents=True, exist_ok=True)

    # 3. Build requested indexes
    results: dict[str, int] = {}
    for name, builder in targets.items():
        result = builder(skills)
        # Track output size for stats
        if isinstance(result, dict):
            if "skills" in result:
                results[name] = len(result["skills"])
            elif "total_unverified" in result:
                results[name] = result["total_unverified"]
            elif "total_buckets" in result:
                results[name] = result["total_buckets"]
            else:
                # Count entries across status/risk groups
                count = sum(
                    len(v) for v in result.values()
                    if isinstance(v, list)
                )
                results[name] = count

    elapsed = time.monotonic() - started

    # 4. Print summary
    logger.info("=" * 60)
    logger.info("Index build complete in %.2fs", elapsed)
    logger.info("  Skills loaded: %d", len(skills))
    logger.info("  Output dir:    %s", INDEXES_DIR)
    for name, count in results.items():
        logger.info("  %-15s %d entries", name + ":", count)
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
    main()
