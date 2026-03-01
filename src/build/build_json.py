"""
SecureSkillHub JSON API Builder.

Reads validated data from data/ and generates static JSON API files
under site/api/ for consumption by the frontend and AI agents.

Usage:
    python -m src.build.build_json
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.sanitizer.schemas import (
    HubStats,
    SkillPackage,
    TagTree,
    VerifiedSkill,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tag alias mapping
# ---------------------------------------------------------------------------
# Skills use abbreviated tags (e.g. "prod", "integ", "sec", "util",
# "data-ai") but tags.json defines canonical IDs ("productivity",
# "integrations", "security", "utilities", "data").  This mapping
# translates every known abbreviated skill tag to the closest canonical
# tags.json node ID so that skill_count values are computed correctly.

TAG_ALIASES: dict[str, str] = {
    # ── Productivity ────────────────────────────────────────────────
    "prod":              "productivity",
    "prod-docs":         "productivity-docs",
    "prod-comm":         "productivity-comm",
    "prod-notes":        "productivity-notes",
    "prod-calendar":     "productivity-calendar",
    "prod-pm":           "productivity-pm",
    "prod-aso":          "productivity",
    "prod-automation":   "productivity",
    "prod-backend":      "productivity",
    "prod-finance":      "productivity",
    "prod-kanban":       "productivity-pm",
    "prod-marketplace":  "productivity",
    "prod-memory":       "productivity",
    "prod-microservice": "productivity",
    "prod-mobile":       "productivity",
    "prod-tax":          "productivity",
    # ── Integrations ───────────────────────────────────────────────
    "integ":             "integrations",
    "integ-cloud":       "integrations-cloud",
    "integ-cloud-aws":   "integrations-cloud-aws",
    "integ-cloud-azure": "integrations-cloud-azure",
    "integ-cloud-gcp":   "integrations-cloud-gcp",
    "integ-crm":         "integrations-crm",
    "integ-payment":     "integrations-payment",
    "integ-social":      "integrations-social",
    "integ-vscode":      "integrations",
    # ── Security ───────────────────────────────────────────────────
    "sec":               "security",
    "sec-auth":          "security-auth",
    "sec-crypto":        "security-crypto",
    "sec-scan":          "security-scanning",
    "sec-scanning":      "security-scanning",
    "sec-pentest":       "security-scanning",
    "sec-education":     "security",
    # ── Utilities ──────────────────────────────────────────────────
    "util":              "utilities",
    "util-file":         "utilities-file",
    "util-search":       "utilities-search",
    "util-browser":      "utilities-browser",
    "util-system":       "utilities-system",
    "util-map":          "utilities-browser",
    "util-media":        "utilities-media",
    "util-monitor":      "utilities-monitor",
    "util-automation":   "utilities-system",
    "util-config":       "utilities-system",
    "util-llm":          "utilities",
    "util-memory":       "utilities",
    "util-productivity": "utilities",
    # ── Status ────────────────────────────────────────────────────
    "clone_failure":     "repo_unavailable",
    "repo_unavailable":  "repo_unavailable",
    # ── Data & AI ──────────────────────────────────────────────────
    "data-ai":           "data-ai",
    "data-ai-nlp":       "data-ai-nlp",
    "data-ai-vision":    "data-ai-vision",
    "data-ai-audio":     "data-ai-audio",
    "data-db":           "data-db",
    "data-db-graph":     "data-db-graph",
    "data-db-vector":    "data-db-vector",
    # ── Dev (miscellaneous abbreviated dev tags) ───────────────────
    "dev-testing":       "dev-testing",
    "dev-git":           "dev-git",
    "dev-agents":        "dev-agents",
    "dev-automation":    "dev",
    "dev-backend":       "dev-web-backend",
    "dev-diagramming":   "dev",
    "dev-docs":          "dev",
    "dev-environment":   "dev",
    "dev-framework":     "dev",
    "dev-frontend":      "dev-web-frontend",
    "dev-gamedev":       "dev",
    "dev-infra":         "dev-devops",
    "dev-ios":           "dev-mobile",
    "dev-japan":         "dev",
    "dev-marketplace":   "dev",
    "dev-mcp":           "dev",
    "dev-multi-agent":   "dev-agents",
    "dev-n8n":           "dev",
    "dev-orchestration": "dev",
    "dev-reverse-engineering": "dev",
    "dev-security":      "dev",
    "dev-spec-driven":   "dev",
    "dev-tools":         "dev",
    "dev-unity":         "dev",
    "dev-workflow":      "dev",
}

STATUS_ALIASES: dict[str, str] = {
    "verified": "pass",
    "approved": "pass",
    "failed": "fail",
    "invalid": "fail",
    "review": "manual_review",
    "flagged": "manual_review",
    "updated-unverified": "updated_unverified",
}

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = PROJECT_ROOT / "data"
SITE_API_DIR = PROJECT_ROOT / "site" / "api"

# Data source paths
TAGS_FILE = DATA_DIR / "tags.json"
STATS_FILE = DATA_DIR / "stats.json"
SKILLS_DIR = DATA_DIR / "skills"
PACKAGES_DIR = DATA_DIR / "packages"

# Output paths
API_TAGS = SITE_API_DIR / "tags.json"
API_STATS = SITE_API_DIR / "stats.json"
API_SKILLS_DIR = SITE_API_DIR / "skills"
API_SKILLS_BY_TAG_DIR = API_SKILLS_DIR / "by-tag"
API_SKILLS_BY_TIER_DIR = API_SKILLS_DIR / "by-tier"
API_PACKAGES_DIR = SITE_API_DIR / "packages"
API_SEARCH_INDEX = SITE_API_DIR / "search-index.json"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _read_json(path: Path) -> Any:
    """Read and parse a JSON file, returning the parsed object."""
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def _write_json(path: Path, data: Any) -> None:
    """Write a Python object to a JSON file with consistent formatting."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False, sort_keys=False)
        fh.write("\n")


def _truncate(text: str, max_length: int = 120) -> str:
    """Truncate a string to max_length, appending ellipsis if needed."""
    if len(text) <= max_length:
        return text
    return text[: max_length - 3].rstrip() + "..."


def _normalize_verification_status(status: Any) -> str:
    """Map legacy / inconsistent verification statuses to canonical values."""
    if status is None:
        return "unverified"
    value = str(status).strip().lower()
    if not value:
        return "unverified"
    normalized = STATUS_ALIASES.get(value, value)
    allowed = {"pass", "fail", "manual_review", "unverified", "updated_unverified"}
    return normalized if normalized in allowed else "unverified"


def _normalize_skill_record(raw: dict[str, Any]) -> dict[str, Any]:
    """Apply defensive normalization so index/detail JSON is consistent."""
    normalized = dict(raw)

    def _safe_int(value: Any, default: int = 0) -> int:
        try:
            if value is None:
                return default
            return int(value)
        except (TypeError, ValueError):
            return default

    normalized["verified_commit"] = str(normalized.get("verified_commit") or "")
    normalized["install_url"] = str(normalized.get("install_url") or normalized.get("repo_url") or "")
    normalized["source_hub"] = str(normalized.get("source_hub") or "mcp_so")
    normalized["trust_level"] = str(normalized.get("trust_level") or "low")
    normalized["verification_status"] = _normalize_verification_status(normalized.get("verification_status"))
    normalized["overall_score"] = _safe_int(normalized.get("overall_score"), 0)
    normalized["risk_level"] = str(normalized.get("risk_level") or "info")
    normalized["scan_date"] = str(normalized.get("scan_date") or "")
    normalized["description"] = str(normalized.get("description") or "")
    tags = normalized.get("tags")
    normalized["tags"] = list(dict.fromkeys(tags)) if isinstance(tags, list) else []
    normalized["stars"] = _safe_int(normalized.get("stars"), 0)
    normalized["owner"] = str(normalized.get("owner") or "")
    normalized["primary_language"] = str(normalized.get("primary_language") or "unknown")
    findings_summary = normalized.get("findings_summary")
    normalized["findings_summary"] = findings_summary if isinstance(findings_summary, dict) else {}
    normalized["skill_type"] = str(normalized.get("skill_type") or "mcp_server")
    normalized["verification_level"] = str(normalized.get("verification_level") or "")
    normalized["agent_audit"] = normalized.get("agent_audit") or {}

    return normalized


def _collect_descendant_tag_ids(node: dict[str, Any]) -> list[str]:
    """Collect a tag node id plus all descendant ids."""
    ids = [str(node.get("id", ""))]
    for child in node.get("children", []) or []:
        ids.extend(_collect_descendant_tag_ids(child))
    return [t for t in ids if t]


# ---------------------------------------------------------------------------
# Tag skill_count updater
# ---------------------------------------------------------------------------

def _collect_all_tag_ids(node: dict) -> list[str]:
    """Recursively collect all tag IDs from a tag node and its children."""
    ids = [node["id"]]
    for child in node.get("children", []):
        ids.extend(_collect_all_tag_ids(child))
    return ids


def _map_tags_to_category(
    node: dict, top_category: str, result: dict[str, str]
) -> None:
    """Recursively map tag IDs to their top-level category."""
    result[node["id"]] = top_category
    for child in node.get("children", []):
        _map_tags_to_category(child, top_category, result)


def _update_tag_counts(node: dict, skill_tag_counts: dict[str, int]) -> int:
    """
    Recursively update skill_count for a tag node.

    A parent node's count is the sum of its children's counts plus any skills
    tagged directly with the parent's ID.
    """
    direct_count = skill_tag_counts.get(node["id"], 0)
    children_count = 0
    for child in node.get("children", []):
        children_count += _update_tag_counts(child, skill_tag_counts)
    total = direct_count + children_count
    node["skill_count"] = total
    return total


# ---------------------------------------------------------------------------
# Core build functions
# ---------------------------------------------------------------------------

def build_tags(skills: list[dict[str, Any]]) -> dict[str, Any]:
    """
    Read data/tags.json, update skill_counts from actual skills data,
    validate against TagTree schema, and write to site/api/tags.json.

    Returns the tag tree dict.
    """
    logger.info("Building tags.json ...")

    raw = _read_json(TAGS_FILE)

    # Count how many skills reference each tag.
    # Resolve abbreviated tags to their canonical tags.json IDs via
    # TAG_ALIASES so that skills using e.g. "prod-docs" are counted
    # under the "productivity-docs" node (and its ancestors).
    skill_tag_counts: dict[str, int] = {}
    for skill in skills:
        for tag in skill.get("tags", []):
            canonical = TAG_ALIASES.get(tag, tag)
            skill_tag_counts[canonical] = skill_tag_counts.get(canonical, 0) + 1

    # Update counts in the tree
    for category in raw.get("categories", []):
        _update_tag_counts(category, skill_tag_counts)

    # Validate
    tag_tree = TagTree.model_validate(raw)
    output = tag_tree.model_dump(mode="json")

    _write_json(API_TAGS, output)
    n_categories = len(output.get("categories", []))
    logger.info("  -> %s  (%d top-level categories)", API_TAGS, n_categories)
    return output


def build_stats(skills: list[dict[str, Any]]) -> dict[str, Any]:
    """
    Read data/stats.json, enrich with a skill_types breakdown computed
    from the loaded skills, validate against HubStats schema, and write
    to site/api/stats.json.

    Returns the stats dict.
    """
    logger.info("Building stats.json ...")

    raw = _read_json(STATS_FILE)

    # Compute stats from the actual skills payload used to build site/api/skills.
    # Security-first "verified" means pass + full 5-agent verification.
    status_counts = {
        "pass": 0,
        "fail": 0,
        "manual_review": 0,
        "updated_unverified": 0,
        "unverified": 0,
    }
    skill_types: dict[str, int] = {}
    source_counts: dict[str, int] = {}
    full_pipeline_verified = 0
    verification_tiers: dict[str, int] = {
        "full_pipeline": 0,
        "scanner_only": 0,
        "metadata_only": 0,
    }

    for skill in skills:
        status = _normalize_verification_status(skill.get("verification_status"))
        status_counts[status] = status_counts.get(status, 0) + 1
        level = str(skill.get("verification_level") or "").strip().lower()
        agents_completed = int((skill.get("agent_audit") or {}).get("agents_completed", 0) or 0)
        if status == "pass" and (level == "full_pipeline" or agents_completed >= 5):
            full_pipeline_verified += 1

        # Count verification tiers for pass skills
        if status == "pass" and level in verification_tiers:
            verification_tiers[level] += 1

        st = str(skill.get("skill_type") or "mcp_server")
        skill_types[st] = skill_types.get(st, 0) + 1

        source = str(skill.get("source_hub") or "unknown")
        source_counts[source] = source_counts.get(source, 0) + 1

    raw["total_skills"] = len(skills)
    raw["verified_skills"] = full_pipeline_verified
    raw["failed_skills"] = status_counts["fail"]
    raw["pending_review"] = (
        status_counts["manual_review"]
        + status_counts["updated_unverified"]
        + max(0, status_counts["pass"] - full_pipeline_verified)
    )
    raw["total_scans_run"] = status_counts["pass"] + status_counts["fail"] + status_counts["manual_review"] + status_counts["updated_unverified"]
    raw["sources"] = source_counts
    raw["skill_types"] = skill_types
    raw["verification_tiers"] = verification_tiers

    stats = HubStats.model_validate(raw)
    output = stats.model_dump(mode="json")

    _write_json(API_STATS, output)
    _write_json(STATS_FILE, output)  # Keep source in sync
    logger.info("  -> %s  (skill_types: %s)", API_STATS, skill_types)
    return output


def load_skills() -> list[dict[str, Any]]:
    """
    Load all skill JSON files from data/skills/, validate each against
    VerifiedSkill schema, and return the list of validated dicts.
    """
    skills: list[dict[str, Any]] = []

    if not SKILLS_DIR.is_dir():
        logger.warning("Skills directory not found: %s", SKILLS_DIR)
        return skills

    skill_files = sorted(SKILLS_DIR.glob("*.json"))
    for skill_file in skill_files:
        try:
            raw = _read_json(skill_file)
            # Try strict validation first; if it fails, accept raw with defaults
            try:
                validated = VerifiedSkill.model_validate(raw)
                skills.append(_normalize_skill_record(validated.model_dump(mode="json")))
            except Exception:
                # Unverified / partially valid skill — normalize with sensible defaults.
                skills.append(_normalize_skill_record(raw))
        except Exception:
            logger.exception("Failed to load skill: %s", skill_file)

    logger.info("Loaded %d skills from %s", len(skills), SKILLS_DIR)
    return skills


def build_skills_index(skills: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Generate the skills index (summarised view) and individual skill detail
    files.

    Writes:
      - site/api/skills/index.json  (array of summaries)
      - site/api/skills/{id}.json   (full detail per skill)

    Returns the index array.
    """
    logger.info("Building skills index and detail files ...")

    API_SKILLS_DIR.mkdir(parents=True, exist_ok=True)

    index: list[dict[str, Any]] = []
    for skill in skills:
        # Summary for the index
        summary = {
            "id": skill["id"],
            "name": skill["name"],
            "description": skill.get("description", ""),
            "overall_score": skill.get("overall_score", 0),
            "verification_status": _normalize_verification_status(skill.get("verification_status", "unverified")),
            "tags": skill.get("tags", []),
            "stars": skill.get("stars", 0),
            "source_hub": skill.get("source_hub", ""),
            "skill_type": skill.get("skill_type", "mcp_server"),
            "owner": skill.get("owner", ""),
            "primary_language": skill.get("primary_language", "unknown"),
            "risk_level": skill.get("risk_level", "info"),
            "repo_url": skill.get("repo_url", ""),
            "install_url": skill.get("install_url", ""),
            "verified_commit": skill.get("verified_commit", ""),
            "verification_level": skill.get("verification_level", ""),
            "agents_completed": (skill.get("agent_audit") or {}).get("agents_completed", 0),
        }
        index.append(summary)

        # Full detail file
        detail_path = API_SKILLS_DIR / f"{skill['id']}.json"
        _write_json(detail_path, skill)

    # Sort by stars descending for API consumers
    index.sort(key=lambda s: s.get("stars", 0), reverse=True)
    _write_json(API_SKILLS_DIR / "index.json", index)
    logger.info(
        "  -> %s/index.json  (%d skills)",
        API_SKILLS_DIR,
        len(index),
    )
    logger.info("  -> %d individual skill detail files", len(skills))
    return index


def build_tag_and_tier_indexes(index: list[dict[str, Any]], tag_tree_data: dict[str, Any] | None = None) -> tuple[int, int]:
    """
    Generate by-tag and by-tier skill indexes from the normalized summary index.

    Writes:
      - site/api/skills/by-tag/{tag}.json
      - site/api/skills/by-tag/index.json
      - site/api/skills/by-tier/{tier}.json

    Returns:
      (tag_count, tier_count)
    """
    logger.info("Building by-tag and by-tier indexes ...")

    API_SKILLS_BY_TAG_DIR.mkdir(parents=True, exist_ok=True)
    API_SKILLS_BY_TIER_DIR.mkdir(parents=True, exist_ok=True)

    # Keep a stable, star-sorted order across all derived indexes.
    sorted_index = sorted(index, key=lambda s: s.get("stars", 0), reverse=True)

    # -------- by-tag --------
    by_tag: dict[str, list[dict[str, Any]]] = {}
    for skill in sorted_index:
        for tag in skill.get("tags", []):
            if not tag:
                continue
            by_tag.setdefault(str(tag), []).append(skill)

    by_tag_index: dict[str, dict[str, int]] = {}
    for tag, tag_skills in sorted(by_tag.items()):
        verified = sum(
            1 for s in tag_skills
            if _normalize_verification_status(s.get("verification_status")) == "pass"
        )
        payload = {
            "tag": tag,
            "total": len(tag_skills),
            "verified": verified,
            "top_stars": tag_skills[0].get("stars", 0) if tag_skills else 0,
            "skills": tag_skills,
        }
        _write_json(API_SKILLS_BY_TAG_DIR / f"{tag}.json", payload)
        by_tag_index[tag] = {
            "total": payload["total"],
            "verified": payload["verified"],
            "top_stars": payload["top_stars"],
        }

    # Build category-grouped tag index for fast frontend navigation
    by_category_index: dict[str, Any] = {
        "tags": by_tag_index,
        "by_category": {},
        "sorted_by_count": sorted(
            by_tag_index.keys(),
            key=lambda t: by_tag_index[t]["total"],
            reverse=True,
        ),
    }

    # Map each tag to its top-level category
    tag_to_category: dict[str, str] = {}
    if tag_tree_data:
        for cat in tag_tree_data.get("categories", []):
            cat_id = cat.get("id", "")
            _map_tags_to_category(cat, cat_id, tag_to_category)

    for tag_id in by_tag_index:
        cat = tag_to_category.get(tag_id, "uncategorized")
        by_category_index["by_category"].setdefault(cat, []).append(tag_id)

    # Sort tags within each category by skill count (descending)
    for cat in by_category_index["by_category"]:
        by_category_index["by_category"][cat].sort(
            key=lambda t: by_tag_index.get(t, {}).get("total", 0),
            reverse=True,
        )

    _write_json(API_SKILLS_BY_TAG_DIR / "index.json", by_category_index)

    # -------- by-tier --------
    tiers = [
        ("tier-1", 1000, None, "1000+ stars — verify immediately"),
        ("tier-2", 100, 999, "100-999 stars — high priority"),
        ("tier-3", 10, 99, "10-99 stars — medium priority"),
        ("tier-4", 1, 9, "1-9 stars — standard priority"),
        ("tier-5", 0, 0, "0 stars — low priority"),
    ]

    for tier_id, min_stars, max_stars, desc in tiers:
        if max_stars is None:
            tier_skills = [s for s in sorted_index if s.get("stars", 0) >= min_stars]
        else:
            tier_skills = [
                s for s in sorted_index if min_stars <= s.get("stars", 0) <= max_stars
            ]
        verified = sum(
            1 for s in tier_skills
            if _normalize_verification_status(s.get("verification_status")) == "pass"
        )
        payload = {
            "tier": tier_id,
            "description": desc,
            "total": len(tier_skills),
            "verified": verified,
            "skills": tier_skills,
        }
        _write_json(API_SKILLS_BY_TIER_DIR / f"{tier_id}.json", payload)

    logger.info(
        "  -> %s  (%d tags)",
        API_SKILLS_BY_TAG_DIR,
        len(by_tag),
    )
    logger.info(
        "  -> %s  (%d tiers)",
        API_SKILLS_BY_TIER_DIR,
        len(tiers),
    )
    return len(by_tag), len(tiers)


def build_search_index(skills: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Generate a lightweight search index for client-side search.

    Each entry contains: id, name, tags, description snippet.

    Writes site/api/search-index.json.
    Returns the search index array.
    """
    logger.info("Building search-index.json ...")

    entries: list[dict[str, Any]] = []
    for skill in skills:
        entry = {
            "id": skill["id"],
            "name": skill["name"],
            "tags": skill.get("tags", []),
            "description": _truncate(skill.get("description", ""), 120),
            "stars": skill.get("stars", 0),
            "overall_score": skill.get("overall_score", 0),
            "verification_status": skill.get("verification_status", "unverified"),
            "skill_type": skill.get("skill_type", "mcp_server"),
        }
        entries.append(entry)

    _write_json(API_SEARCH_INDEX, entries)
    logger.info("  -> %s  (%d entries)", API_SEARCH_INDEX, len(entries))
    return entries


def build_packages(skills: list[dict[str, Any]], tag_tree: dict[str, Any]) -> int:
    """
    Copy all package JSON files from data/packages/ to site/api/packages/,
    validating each against SkillPackage schema. Then ensure every tag node
    in the canonical tree has a "general package" JSON available (fallback
    generated from current skills when missing).

    Returns the number of packages copied.
    """
    logger.info("Building packages ...")

    if not PACKAGES_DIR.is_dir():
        logger.warning("Packages directory not found: %s", PACKAGES_DIR)
        return 0

    API_PACKAGES_DIR.mkdir(parents=True, exist_ok=True)

    package_files = sorted(PACKAGES_DIR.glob("*.json"))
    count = 0
    copied_index = False
    package_manifest: dict[str, dict[str, Any]] = {}

    def _manifest_row(pkg: dict[str, Any]) -> dict[str, Any]:
        skills_in_pkg = pkg.get("skills", [])
        top_stars = 0
        if isinstance(skills_in_pkg, list) and skills_in_pkg:
            top_stars = int(skills_in_pkg[0].get("stars", 0) or 0)
        return {
            "label": pkg.get("label", ""),
            "total_skills": int(pkg.get("total_skills", 0) or 0),
            "total_candidates": int(
                pkg.get("total_candidates", pkg.get("total_skills", 0)) or 0
            ),
            "avg_score": float(pkg.get("avg_score", 0) or 0),
            "top_stars": top_stars,
            "selection_mode": pkg.get("selection_mode", "verified_only"),
        }

    for pkg_file in package_files:
        try:
            raw = _read_json(pkg_file)
            # data/packages/index.json is a manifest, not a SkillPackage payload.
            # Copy it through unchanged so clients can discover available packages.
            if pkg_file.name == "index.json":
                _write_json(API_PACKAGES_DIR / pkg_file.name, raw)
                copied_index = True
                if isinstance(raw, dict) and isinstance(raw.get("packages"), dict):
                    for tag_id, row in raw.get("packages", {}).items():
                        if isinstance(row, dict):
                            package_manifest[str(tag_id)] = dict(row)
                continue

            validated = SkillPackage.model_validate(raw)
            output = validated.model_dump(mode="json")
            if isinstance(raw, dict):
                output.update({
                    "skills": raw.get("skills", []),
                    "total_candidates": raw.get("total_candidates", output.get("total_skills", 0)),
                    "top_stars": raw.get("top_stars", 0),
                    "selection_mode": raw.get("selection_mode", "verified_only"),
                })
            _write_json(API_PACKAGES_DIR / pkg_file.name, output)
            package_manifest[pkg_file.stem] = _manifest_row(output)
            count += 1
        except Exception:
            logger.exception("Failed to load/validate package: %s", pkg_file)

    # Fallback generation: guarantee one package per canonical tag node.
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    top_n = 10
    for category in tag_tree.get("categories", []):
        stack = [category]
        while stack:
            node = stack.pop()
            tag_id = str(node.get("id", ""))
            if not tag_id:
                continue

            out_path = API_PACKAGES_DIR / f"{tag_id}.json"
            if out_path.exists():
                if tag_id not in package_manifest:
                    try:
                        existing = _read_json(out_path)
                        if isinstance(existing, dict):
                            package_manifest[tag_id] = _manifest_row(existing)
                    except Exception:
                        logger.exception("Failed to read existing package: %s", out_path)
                stack.extend(node.get("children", []) or [])
                continue

            descendant_ids = set(_collect_descendant_tag_ids(node))
            candidates = [
                s for s in skills
                if any(tag in descendant_ids for tag in s.get("tags", []))
            ]
            candidates.sort(
                key=lambda s: (
                    int(s.get("stars", 0) or 0),
                    int(s.get("overall_score", 0) or 0),
                ),
                reverse=True,
            )

            verified = [
                s for s in candidates
                if _normalize_verification_status(s.get("verification_status")) == "pass"
            ]
            selected = verified[:top_n]
            selection_mode = "verified_only"
            if len(selected) < top_n:
                fallback = [s for s in candidates if s not in selected]
                selected = (selected + fallback)[:top_n]
                if fallback:
                    selection_mode = "verified_plus_fallback"

            avg_score = (
                round(
                    sum(float(s.get("overall_score", 0) or 0) for s in selected) / len(selected),
                    1,
                )
                if selected
                else 0.0
            )
            payload = {
                "tag_path": tag_id,
                "label": f"General {node.get('label', tag_id)} Package",
                "description": (
                    f"Top {len(selected)} skills for {node.get('label', tag_id)} "
                    f"(selection mode: {selection_mode.replace('_', ' ')})."
                ),
                "skill_ids": [s.get("id", "") for s in selected if s.get("id")],
                "skills": selected,
                "total_skills": len(selected),
                "total_candidates": len(candidates),
                "avg_score": avg_score,
                "top_stars": int(selected[0].get("stars", 0) or 0) if selected else 0,
                "selection_mode": selection_mode,
                "generated_at": now_str,
            }
            _write_json(out_path, payload)
            package_manifest[tag_id] = _manifest_row(payload)
            count += 1

            stack.extend(node.get("children", []) or [])

    # Rewrite package manifest so it includes all generated packages.
    manifest_payload = {
        "generated_at": now_str,
        "total_packages": len(package_manifest),
        "top_n": 10,
        "packages": dict(sorted(package_manifest.items())),
    }
    _write_json(API_PACKAGES_DIR / "index.json", manifest_payload)
    copied_index = True

    if copied_index:
        logger.info("  -> %s/index.json  (package manifest)", API_PACKAGES_DIR)
    logger.info("  -> %s  (%d packages)", API_PACKAGES_DIR, count)
    return count


# ---------------------------------------------------------------------------
# Main orchestrator
# ---------------------------------------------------------------------------

def build_all() -> None:
    """Run the full JSON API build pipeline."""
    started = datetime.now(timezone.utc)
    logger.info("=" * 60)
    logger.info("SecureSkillHub JSON API build started at %s", started.isoformat())
    logger.info("=" * 60)

    # 1. Load and validate all skills
    skills = load_skills()

    # 2. Build tags (with updated skill_counts)
    tags = build_tags(skills)

    # 3. Build stats (with skill_types breakdown from loaded skills)
    build_stats(skills)

    # 4. Build skills index + detail files
    index = build_skills_index(skills)

    # 4b. Build by-tag / by-tier indexes for fast agent navigation
    build_tag_and_tier_indexes(index, tags)

    # 5. Build search index
    build_search_index(skills)

    # 6. Build packages
    pkg_count = build_packages(skills, tags)

    elapsed = datetime.now(timezone.utc) - started
    logger.info("=" * 60)
    logger.info(
        "Build complete: %d skills, %d packages in %.2fs",
        len(skills),
        pkg_count,
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
