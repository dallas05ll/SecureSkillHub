#!/usr/bin/env python3
"""
Build General Packages — auto-curated skill bundles per tag level.

At each tag level in the 4-layer hierarchy, the "General Package" is the
top N verified skills sorted by GitHub stars. This is the lazy install:
user picks a category and gets the best-of-breed bundle automatically.

Generates:
  data/packages/{tag-path}.json — per-tag package
  data/packages/index.json      — package index for agent discovery

Usage:
    python3 build_packages.py [--top N]
"""

from __future__ import annotations

import argparse
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("build_packages")

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
SKILLS_DIR = PROJECT_ROOT / "data" / "skills"
TAGS_FILE = PROJECT_ROOT / "data" / "tags.json"
PACKAGES_DIR = PROJECT_ROOT / "data" / "packages"

# How many skills per package
DEFAULT_TOP_N = 10

# Import TAG_ALIASES from build_json for consistent tag resolution
def _load_tag_aliases() -> dict[str, str]:
    """Load TAG_ALIASES from src.build.build_json to resolve abbreviated tags."""
    import importlib
    try:
        mod = importlib.import_module("src.build.build_json")
        return getattr(mod, "TAG_ALIASES", {})
    except Exception:
        return {}

TAG_ALIASES = _load_tag_aliases()

# Tags that should not generate packages (system tags, not content categories)
PACKAGE_BLOCKLIST = {
    "repo_unavailable",
    "clone_failure",
    "status",
    "status-pass",
    "status-fail",
    "status-manual_review",
    "status-unverified",
    "status-updated_unverified",
}


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


def _parse_installs(skill: dict) -> int:
    """Parse installs count from tags array (e.g. 'installs:97732')."""
    installs = int(skill.get("installs") or 0)
    if installs == 0:
        for t in skill.get("tags", []):
            if isinstance(t, str) and t.startswith("installs:"):
                try:
                    installs = int(t.split(":", 1)[1])
                except ValueError:
                    pass
                break
    return installs


def _priority_score(skill: dict) -> int:
    """Unified priority: max(stars, installs)."""
    return max(int(skill.get("stars") or 0), _parse_installs(skill))


def skill_entry(skill: dict) -> dict:
    """Create a package entry for a skill."""
    return {
        "id": skill.get("id", ""),
        "name": skill.get("name", ""),
        "description": skill.get("description", "")[:200],
        "repo_url": skill.get("repo_url", ""),
        "stars": skill.get("stars", 0),
        "installs": _parse_installs(skill),
        "overall_score": skill.get("overall_score", 0),
        "verification_status": skill.get("verification_status", "unverified"),
        "risk_level": skill.get("risk_level", "info"),
        "primary_language": skill.get("primary_language", "unknown"),
        "install_url": skill.get("install_url", skill.get("repo_url", "")),
        "skill_type": skill.get("skill_type", "mcp_server"),
        "verified_commit": skill.get("verified_commit", ""),
    }


def collect_tag_ids(node: dict) -> list[str]:
    """Recursively collect all tag IDs from a node (self + descendants)."""
    ids = [node["id"]]
    for child in node.get("children", []):
        ids.extend(collect_tag_ids(child))
    return ids


def build_package_for_tag(
    tag_node: dict,
    skills_by_tag: dict[str, list[dict]],
    top_n: int,
    now_str: str,
) -> dict | None:
    """Build a general package for a tag node.

    Includes skills tagged with this tag OR any descendant tag,
    deduplicated and sorted by stars.
    """
    # Collect all tag IDs under this node
    all_tag_ids = collect_tag_ids(tag_node)

    # Gather all skills matching any of these tags (deduplicate by ID and repo_url)
    seen_ids = set()
    seen_repos = set()
    candidates = []
    for tag_id in all_tag_ids:
        for skill in skills_by_tag.get(tag_id, []):
            sid = skill.get("id", "")
            repo = skill.get("repo_url", "")
            if sid not in seen_ids and (not repo or repo not in seen_repos):
                seen_ids.add(sid)
                if repo:
                    seen_repos.add(repo)
                candidates.append(skill)

    # Quality floor: only include skills that meet curation standards.
    # - verification_status must be "pass" or "manual_review"
    # - risk_level must not be "critical"
    # - overall_score must be >= 50
    _CURATED_STATUSES = {"pass", "manual_review"}
    verified = [
        s for s in candidates
        if (
            str(s.get("verification_status", "")).strip().lower() in _CURATED_STATUSES
            and str(s.get("risk_level", "info")).strip().lower() != "critical"
            and int(s.get("overall_score", 0) or 0) >= 50
        )
    ]
    verified.sort(key=lambda s: (-_priority_score(s), s.get("name", "")))

    top_skills = verified[:top_n]

    if not top_skills:
        return None

    avg_score = sum(s.get("overall_score", 0) for s in top_skills) / len(top_skills)

    return {
        "tag_path": tag_node["id"],
        "label": f"General {tag_node['label']} Package",
        "description": f"Top {len(top_skills)} verified {tag_node['label'].lower()} skills, auto-curated by GitHub stars and security score.",
        "skill_ids": [s["id"] for s in top_skills],
        "skills": [skill_entry(s) for s in top_skills],
        "total_skills": len(top_skills),
        "total_candidates": len(verified),
        "avg_score": round(avg_score, 1),
        "min_score": min(s.get("overall_score", 0) for s in top_skills),
        "top_stars": top_skills[0].get("stars", 0) if top_skills else 0,
        "generated_at": now_str,
    }


def walk_tag_tree(
    node: dict,
    skills_by_tag: dict[str, list[dict]],
    top_n: int,
    now_str: str,
    packages: dict[str, dict],
) -> None:
    """Recursively build packages for a tag node and all its children."""
    if node["id"] not in PACKAGE_BLOCKLIST:
        pkg = build_package_for_tag(node, skills_by_tag, top_n, now_str)
        if pkg:
            packages[node["id"]] = pkg

    for child in node.get("children", []):
        walk_tag_tree(child, skills_by_tag, top_n, now_str, packages)


def main(top_n: int = DEFAULT_TOP_N) -> None:
    logger.info("=" * 60)
    logger.info("Building General Packages (top %d per tag)", top_n)
    logger.info("=" * 60)

    # Load skills
    skills = load_all_skills()
    logger.info("Loaded %d skills", len(skills))

    # Index skills by tag (resolve abbreviated tags via TAG_ALIASES)
    skills_by_tag: dict[str, list[dict]] = {}
    for skill in skills:
        for tag in skill.get("tags", []):
            canonical = TAG_ALIASES.get(tag, tag)
            skills_by_tag.setdefault(canonical, []).append(skill)
            # Also index under the raw tag for direct matches
            if canonical != tag:
                skills_by_tag.setdefault(tag, []).append(skill)

    # Load tag tree
    tags_data = json.loads(TAGS_FILE.read_text())
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # Build packages for every tag node in the tree
    packages: dict[str, dict] = {}
    for category in tags_data.get("categories", []):
        walk_tag_tree(category, skills_by_tag, top_n, now_str, packages)

    # Write package files
    PACKAGES_DIR.mkdir(parents=True, exist_ok=True)

    for tag_id, pkg in packages.items():
        pkg_file = PACKAGES_DIR / f"{tag_id}.json"
        pkg_file.write_text(json.dumps(pkg, indent=2))

    # Write package index
    index = {
        "generated_at": now_str,
        "total_packages": len(packages),
        "top_n": top_n,
        "packages": {
            tag_id: {
                "label": pkg["label"],
                "total_skills": pkg["total_skills"],
                "total_candidates": pkg["total_candidates"],
                "avg_score": pkg["avg_score"],
                "top_stars": pkg["top_stars"],
            }
            for tag_id, pkg in sorted(packages.items())
        },
    }
    (PACKAGES_DIR / "index.json").write_text(json.dumps(index, indent=2))

    logger.info("Generated %d packages in %s", len(packages), PACKAGES_DIR)
    for tag_id, pkg in sorted(packages.items(), key=lambda x: -x[1]["total_skills"]):
        logger.info(
            "  %s: %d skills (avg score %.0f, top stars %s)",
            tag_id, pkg["total_skills"], pkg["avg_score"], f"{pkg['top_stars']:,}",
        )

    logger.info("=" * 60)
    logger.info("Done! %d packages generated.", len(packages))
    logger.info("=" * 60)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--top", type=int, default=DEFAULT_TOP_N,
                        help="Top N skills per package (default: 10)")
    args = parser.parse_args()
    main(top_n=args.top)
