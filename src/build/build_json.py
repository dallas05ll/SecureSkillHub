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
    "prod-kanban":       "productivity-pm",
    # prod-aso, prod-automation, prod-backend, prod-finance, prod-marketplace,
    # prod-memory, prod-microservice, prod-mobile, prod-tax removed — 0 usage
    # ── Integrations ───────────────────────────────────────────────
    "integ":             "integrations",
    "integ-cloud":       "integrations-cloud",
    "integ-cloud-aws":   "integrations-cloud-aws",
    "integ-cloud-azure": "integrations-cloud-azure",
    "integ-cloud-gcp":   "integrations-cloud-gcp",
    "integ-crm":         "integrations-crm",
    "integ-payment":     "integrations-payment",
    "integ-social":      "integrations-social",
    # integ-vscode removed — 0 usage
    # ── Security ───────────────────────────────────────────────────
    "sec":               "security",
    "sec-auth":          "security-auth",
    "sec-crypto":        "security-crypto",
    "sec-scan":          "security-scanning",
    "sec-scanning":      "security-scanning",
    "sec-pentest":       "security-scanning",
    # sec-education removed — 0 usage
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
    # util-llm, util-memory, util-productivity removed — 0 usage
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
    "data-ml":           "data-ml",
    "data-analysis":     "data-analysis",
    "data-finance":      "data-finance",     # Finance & Trading (new 2026-03-03)
    "data-rag":          "data-rag",         # RAG & Retrieval (new 2026-03-03)
    # ── Data-finance aliases ────────────────────────────────────────
    "finance":           "data-finance",
    "trading":           "data-finance",
    # ── Data-rag aliases ────────────────────────────────────────────
    "rag":               "data-rag",
    "retrieval":         "data-rag",
    # ── Dev (miscellaneous abbreviated dev tags) ───────────────────
    "dev-testing":       "dev-testing",
    "dev-git":           "dev-git",
    "dev-agents":        "dev-agents",
    "dev-mobile":        "dev-mobile",
    "dev-mobile-react-native": "dev-mobile-react-native",
    "dev-mobile-flutter": "dev-mobile-flutter",
    "dev-desktop":       "dev-desktop",
    "dev-desktop-electron": "dev-desktop-electron",
    "dev-desktop-tauri": "dev-desktop-tauri",
    "dev-web-frontend-angular":  "dev-web-frontend-angular",
    "dev-web-frontend-svelte":   "dev-web-frontend-svelte",   # added 2026-03-03
    "dev-web-backend-rust":      "dev-web-backend-rust",      # added 2026-03-03
    "dev-web-fullstack-nuxt": "dev-web-fullstack-nuxt",
    "react":             "dev-web-frontend-react",
    "react-native":      "dev-mobile-react-native",
    "dev-automation":    "dev",
    "dev-backend":       "dev-web-backend",
    "dev-diagramming":   "dev",
    "dev-docs":          "dev",
    "dev-environment":   "dev",
    "dev-framework":     "dev",
    "dev-frontend":      "dev-web-frontend",
    "dev-gamedev":       "dev-gamedev",      # now maps to its own node (new 2026-03-03)
    "gamedev":           "dev-gamedev",
    "game":              "dev-gamedev",
    "dev-infra":         "dev-devops",
    "dev-ios":           "dev-mobile",
    # dev-japan removed — 0 usage
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
    # ── Security (compliance) ───────────────────────────────────────
    "security-compliance": "security-compliance",  # Compliance & Legal (new 2026-03-03)
    "compliance":          "security-compliance",
    "legal":               "security-compliance",
    # ── Integrations (platform-specific) ───────────────────────────
    "integrations-github":     "integrations-github",
    "integrations-slack":      "integrations-slack",
    "integrations-notion":     "integrations-notion",
    "integrations-jira":       "integrations-jira",
    "integrations-messaging":  "integrations-messaging",  # Messaging & Chat (new 2026-03-03)
    "integrations-google":     "integrations-google",     # Google Workspace (new 2026-03-03)
    # ── Integrations aliases ─────────────────────────────────────────
    "messaging":               "integrations-messaging",
    "chat":                    "integrations-messaging",
    # ── Data-AI (sub-tags) ───────────────────────────────────────────
    "data-ai-rag":             "data-ai-rag",     # RAG & Retrieval (new 2026-03-03)
    "data-ai-agents":          "data-ai-agents",  # Agent Frameworks (new 2026-03-03)
    # ── Data-AI aliases ──────────────────────────────────────────────
    "ai-rag":                  "data-ai-rag",
    "vector-search":           "data-ai-rag",
    "ai-agents":               "data-ai-agents",
    "agent-framework":         "data-ai-agents",
    # ── Productivity (platform-specific) ───────────────────────────
    "productivity-email":  "productivity-email",
    # ── Security (secrets management) ──────────────────────────────
    "security-secrets":    "security-secrets",
    # ── Utilities (system-level) ────────────────────────────────────
    "utilities-system":    "utilities-system",
}

# Reverse alias mapping: abbreviated → canonical.
# Used by build_tag_and_tier_indexes() to write by-tag files under BOTH the
# abbreviated tag ID (as found on skills) and the canonical tag ID (as listed
# in tags.json).  Only includes entries where abbreviated != canonical.
REVERSE_ALIASES: dict[str, str] = {
    abbrev: canonical
    for abbrev, canonical in TAG_ALIASES.items()
    if abbrev != canonical
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
API_V2_META_DIR = SITE_API_DIR / "v2" / "meta"


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
    # Translate abbreviated tags to canonical tags.json IDs via TAG_ALIASES
    # so that skill tags match the sidebar tag tree for frontend filtering.
    raw_tags = list(dict.fromkeys(tags)) if isinstance(tags, list) else []
    normalized["tags"] = list(dict.fromkeys(
        TAG_ALIASES.get(t, t) for t in raw_tags
    ))
    normalized["stars"] = _safe_int(normalized.get("stars"), 0)
    # Parse installs from tags (e.g. "installs:97732") into a proper field
    installs = _safe_int(normalized.get("installs"), 0)
    if installs == 0:
        for t in raw_tags:
            if isinstance(t, str) and t.startswith("installs:"):
                installs = _safe_int(t.split(":", 1)[1], 0)
                break
    normalized["installs"] = installs
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

        # Count verification tiers for all assessed skills
        if level in verification_tiers:
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


def _priority_score(skill: dict[str, Any]) -> int:
    """Unified priority: max(stars, installs). MCP uses stars, agents use installs."""
    return max(int(skill.get("stars") or 0), int(skill.get("installs") or 0))


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
            "installs": skill.get("installs", 0),
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
            "has_plugin_json": skill.get("has_plugin_json"),
        }
        index.append(summary)

        # Full detail file
        detail_path = API_SKILLS_DIR / f"{skill['id']}.json"
        _write_json(detail_path, skill)

    # Sort by unified priority (max of stars, installs) descending
    index.sort(key=lambda s: _priority_score(s), reverse=True)
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

    # Keep a stable, priority-sorted order across all derived indexes.
    # Uses unified priority: max(stars, installs) so agent skills rank by installs.
    sorted_index = sorted(index, key=lambda s: _priority_score(s), reverse=True)

    # -------- by-tag --------
    by_tag: dict[str, list[dict[str, Any]]] = {}
    for skill in sorted_index:
        for tag in skill.get("tags", []):
            if not tag:
                continue
            by_tag.setdefault(str(tag), []).append(skill)

    by_tag_index: dict[str, dict[str, int]] = {}

    # Accumulate skills for canonical tag IDs that don't already have their
    # own direct by_tag bucket.  Multiple abbreviated tags may map to the
    # same canonical (e.g. sec-scan, sec-scanning, sec-pentest → security-scanning),
    # so we merge them via a seen-ID set to avoid duplicates.
    canonical_buckets: dict[str, list[dict[str, Any]]] = {}
    canonical_seen_ids: dict[str, set[str]] = {}

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
            "top_priority": _priority_score(tag_skills[0]) if tag_skills else 0,
            "skills": tag_skills,
        }
        _write_json(API_SKILLS_BY_TAG_DIR / f"{tag}.json", payload)
        by_tag_index[tag] = {
            "total": payload["total"],
            "verified": payload["verified"],
            "top_stars": payload["top_stars"],
        }

        # Accumulate skills into canonical bucket for later writing.
        canonical = REVERSE_ALIASES.get(tag)
        if canonical and canonical != tag and canonical not in by_tag:
            if canonical not in canonical_buckets:
                canonical_buckets[canonical] = []
                canonical_seen_ids[canonical] = set()
            for skill in tag_skills:
                skill_id = skill.get("id", "")
                if skill_id not in canonical_seen_ids[canonical]:
                    canonical_seen_ids[canonical].add(skill_id)
                    canonical_buckets[canonical].append(skill)

    # Write canonical alias files (merging all abbreviated variants).
    for canonical, canon_skills in sorted(canonical_buckets.items()):
        # Re-sort by unified priority descending to match the rest of the by-tag files.
        canon_skills.sort(key=lambda s: _priority_score(s), reverse=True)
        verified = sum(
            1 for s in canon_skills
            if _normalize_verification_status(s.get("verification_status")) == "pass"
        )
        canonical_payload = {
            "tag": canonical,
            "total": len(canon_skills),
            "verified": verified,
            "top_stars": canon_skills[0].get("stars", 0) if canon_skills else 0,
            "skills": canon_skills,
        }
        _write_json(API_SKILLS_BY_TAG_DIR / f"{canonical}.json", canonical_payload)
        by_tag_index[canonical] = {
            "total": canonical_payload["total"],
            "verified": canonical_payload["verified"],
            "top_stars": canonical_payload["top_stars"],
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
        # Look up category by canonical ID first (tags.json uses canonical).
        # If the tag_id is abbreviated, resolve via REVERSE_ALIASES so it
        # lands in the correct category instead of "uncategorized".
        cat = tag_to_category.get(tag_id)
        if cat is None:
            canonical = REVERSE_ALIASES.get(tag_id)
            if canonical:
                cat = tag_to_category.get(canonical)
        if cat is None:
            cat = "uncategorized"
        by_category_index["by_category"].setdefault(cat, []).append(tag_id)

    # Sort tags within each category by skill count (descending)
    for cat in by_category_index["by_category"]:
        by_category_index["by_category"][cat].sort(
            key=lambda t: by_tag_index.get(t, {}).get("total", 0),
            reverse=True,
        )

    _write_json(API_SKILLS_BY_TAG_DIR / "index.json", by_category_index)

    # -------- by-tier --------
    # Uses unified priority: max(stars, installs) so agent skills rank correctly.
    # MCP servers tier by stars, agent skills tier by installs — both use the same thresholds.
    tiers = [
        ("tier-1", 1000, None, "1000+ priority — verify immediately"),
        ("tier-2", 100, 999, "100-999 priority — high priority"),
        ("tier-3", 10, 99, "10-99 priority — medium priority"),
        ("tier-4", 1, 9, "1-9 priority — standard priority"),
        ("tier-5", 0, 0, "0 priority — low priority"),
    ]

    for tier_id, min_stars, max_stars, desc in tiers:
        if max_stars is None:
            tier_skills = [s for s in sorted_index if _priority_score(s) >= min_stars]
        else:
            tier_skills = [
                s for s in sorted_index if min_stars <= _priority_score(s) <= max_stars
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
            "installs": skill.get("installs", 0),
            "overall_score": skill.get("overall_score", 0),
            "verification_status": skill.get("verification_status", "unverified"),
            "skill_type": skill.get("skill_type", "mcp_server"),
            "verified_commit": (skill.get("verified_commit") or "")[:7],
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

    # Clean output directory to remove stale packages from previous builds.
    if API_PACKAGES_DIR.is_dir():
        import shutil
        shutil.rmtree(API_PACKAGES_DIR)
    API_PACKAGES_DIR.mkdir(parents=True, exist_ok=True)

    # Build a lookup for skill-level quality filtering in source packages.
    _skills_by_id: dict[str, dict[str, Any]] = {
        s.get("id", ""): s for s in skills if s.get("id")
    }

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

    # Blocklist for source package files (same tags as fallback blocklist).
    _SOURCE_PKG_BLOCKLIST = {"repo_unavailable", "clone_failure", "status",
                             "status-pass", "status-fail", "status-manual_review",
                             "status-unverified", "status-updated_unverified"}

    for pkg_file in package_files:
        # Skip blocklisted source packages.
        if pkg_file.stem in _SOURCE_PKG_BLOCKLIST:
            continue
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

            # Re-validate individual skills: remove stale, unavailable, and
            # low-quality entries using current skill data.
            _BAD_TAGS = {"repo_unavailable", "clone_failure"}
            _GOOD_STATUSES = {"pass", "manual_review"}
            raw_skills = raw.get("skills", []) if isinstance(raw, dict) else []
            raw_ids = raw.get("skill_ids", []) if isinstance(raw, dict) else []
            clean_skills = []
            clean_ids = []
            for sid in raw_ids:
                current = _skills_by_id.get(sid)
                if not current:
                    continue  # stale ID
                if _BAD_TAGS & set(current.get("tags", [])):
                    continue  # repo unavailable
                if _normalize_verification_status(current.get("verification_status")) not in _GOOD_STATUSES:
                    continue
                if int(current.get("overall_score", 0) or 0) < 50:
                    continue
                clean_ids.append(sid)
                # Prefer the matching embedded skill object if present
                embedded = next((s for s in raw_skills if s.get("id") == sid), None)
                clean_skills.append(embedded if embedded else current)

            # Skip empty packages after filtering.
            if not clean_ids:
                continue

            avg_score = round(
                sum(float(s.get("overall_score", 0) or 0) for s in clean_skills) / len(clean_skills), 1
            ) if clean_skills else 0.0
            output.update({
                "skill_ids": clean_ids,
                "skills": clean_skills,
                "total_skills": len(clean_ids),
                "total_candidates": raw.get("total_candidates", len(clean_ids)) if isinstance(raw, dict) else len(clean_ids),
                "top_stars": int(clean_skills[0].get("stars", 0) or 0) if clean_skills else 0,
                "avg_score": avg_score,
                "selection_mode": raw.get("selection_mode", "verified_only") if isinstance(raw, dict) else "verified_only",
            })
            _write_json(API_PACKAGES_DIR / pkg_file.name, output)
            package_manifest[pkg_file.stem] = _manifest_row(output)
            count += 1
        except Exception:
            logger.exception("Failed to load/validate package: %s", pkg_file)

    # Fallback generation: guarantee one package per canonical tag node.
    # Skip system/status tags that shouldn't have packages.
    _PACKAGE_BLOCKLIST = {"repo_unavailable", "clone_failure", "status",
                          "status-pass", "status-fail", "status-manual_review",
                          "status-unverified", "status-updated_unverified"}
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    top_n = 10
    for category in tag_tree.get("categories", []):
        stack = [category]
        while stack:
            node = stack.pop()
            tag_id = str(node.get("id", ""))
            if not tag_id or tag_id in _PACKAGE_BLOCKLIST:
                stack.extend(node.get("children", []) or [])
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

            # Quality floor: only include skills that meet curation standards.
            # - verification_status must be "pass" or "manual_review"
            # - risk_level must not be "critical"
            # - overall_score must be >= 50
            # - must not be repo_unavailable or clone_failure
            _CURATED_STATUSES = {"pass", "manual_review"}
            _EXCLUDE_TAGS = {"repo_unavailable", "clone_failure"}
            qualified = [
                s for s in candidates
                if (
                    _normalize_verification_status(s.get("verification_status")) in _CURATED_STATUSES
                    and str(s.get("risk_level", "info")).lower() != "critical"
                    and int(s.get("overall_score", 0) or 0) >= 50
                    and not (_EXCLUDE_TAGS & set(s.get("tags", [])))
                )
            ]

            # Skip package generation if no qualifying skills remain.
            if not qualified:
                stack.extend(node.get("children", []) or [])
                continue

            selected = qualified[:top_n]
            selection_mode = "verified_only"

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
                    f"Top {len(selected)} verified skills for {node.get('label', tag_id)}, "
                    f"auto-curated by stars and security score."
                ),
                "skill_ids": [s.get("id", "") for s in selected if s.get("id")],
                "skills": selected,
                "total_skills": len(selected),
                "total_candidates": len(qualified),
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
# v2 Meta Files — lightweight agent-first indexes
# ---------------------------------------------------------------------------

def build_v2_meta(skills: list[dict[str, Any]], tag_tree: dict[str, Any]) -> None:
    """
    Build lightweight v2 meta files for efficient agent consumption.

    Generates:
      - api/v2/meta/mcp_servers_top.json  (top 200 MCP servers by stars, ~15KB)
      - api/v2/meta/agent_skills_top.json (top 200 agent skills by installs, ~15KB)
      - api/v2/meta/mcp_servers.json      (all MCP servers, compact)
      - api/v2/meta/agent_skills.json     (all agent skills, compact)
      - api/v2/meta/categories.json       (tag tree summary with per-type counts)
      - api/v2/meta/stats.json            (quick stats for agents)
    """
    logger.info("Building v2 meta files ...")
    API_V2_META_DIR.mkdir(parents=True, exist_ok=True)

    # Tier label from priority score
    def _tier_label(score: int) -> str:
        if score >= 10000: return "S"
        if score >= 1000: return "A"
        if score >= 100: return "B"
        if score >= 10: return "C"
        if score >= 1: return "D"
        return "E"

    # Compact item for meta files — 7 fields max
    def _meta_item(skill: dict[str, Any]) -> dict[str, Any]:
        score = _priority_score(skill)
        is_agent = skill.get("skill_type") == "agent_skill"
        # Filter out system/installs tags, keep only content tags
        tags = [
            t for t in (skill.get("tags") or [])
            if isinstance(t, str)
            and not t.startswith("installs:")
            and t not in ("agent-skills", "mcp_server", "repo_unavailable", "clone_failure")
        ]
        return {
            "id": skill["id"],
            "name": skill.get("name", ""),
            "score": score,
            "score_type": "installs" if is_agent else "stars",
            "tier": _tier_label(score),
            "verified": _normalize_verification_status(skill.get("verification_status")) == "pass",
            "tags": tags[:3],  # Max 3 tags to keep compact
            "one_liner": _truncate(skill.get("description", ""), 80),
        }

    # Split by type
    mcp_skills = [s for s in skills if s.get("skill_type") != "agent_skill"]
    agent_skills = [s for s in skills if s.get("skill_type") == "agent_skill"]

    # Sort each by their respective priority
    mcp_skills.sort(key=lambda s: _priority_score(s), reverse=True)
    agent_skills.sort(key=lambda s: _priority_score(s), reverse=True)

    mcp_verified = sum(1 for s in mcp_skills if _normalize_verification_status(s.get("verification_status")) == "pass")
    agent_verified = sum(1 for s in agent_skills if _normalize_verification_status(s.get("verification_status")) == "pass")

    # Top 200 files (~15KB each)
    for label, subset, verified_count in [
        ("mcp_servers", mcp_skills, mcp_verified),
        ("agent_skills", agent_skills, agent_verified),
    ]:
        top_items = [_meta_item(s) for s in subset[:200]]
        top_payload = {
            "generated": datetime.now(timezone.utc).isoformat(),
            "total": len(subset),
            "verified": verified_count,
            "showing": len(top_items),
            "sort": "priority_desc",
            "items": top_items,
        }
        _write_json(API_V2_META_DIR / f"{label}_top.json", top_payload)
        logger.info("  -> v2/meta/%s_top.json  (%d items)", label, len(top_items))

        # Full catalog file (all items, still compact)
        all_items = [_meta_item(s) for s in subset]
        full_payload = {
            "generated": datetime.now(timezone.utc).isoformat(),
            "total": len(subset),
            "verified": verified_count,
            "sort": "priority_desc",
            "items": all_items,
        }
        _write_json(API_V2_META_DIR / f"{label}.json", full_payload)
        logger.info("  -> v2/meta/%s.json  (%d items)", label, len(all_items))

    # Categories file — tag tree summary with per-type counts
    categories = []
    if tag_tree:
        def _walk_categories(node: dict[str, Any], depth: int = 0) -> dict[str, Any]:
            cat = {
                "id": node.get("id", ""),
                "label": node.get("label", ""),
                "skill_count": node.get("skill_count", 0),
            }
            children = node.get("children", [])
            if children and depth < 2:  # Only 2 levels deep for compact output
                cat["children"] = [_walk_categories(c, depth + 1) for c in children]
            elif children:
                cat["child_count"] = len(children)
            return cat

        for top_cat in tag_tree.get("categories", []):
            categories.append(_walk_categories(top_cat))

    categories_payload = {
        "generated": datetime.now(timezone.utc).isoformat(),
        "total_categories": len(categories),
        "mcp_servers": len(mcp_skills),
        "agent_skills": len(agent_skills),
        "categories": categories,
    }
    _write_json(API_V2_META_DIR / "categories.json", categories_payload)
    logger.info("  -> v2/meta/categories.json  (%d categories)", len(categories))

    # Quick stats for agents
    stats_payload = {
        "mcp_servers": {"total": len(mcp_skills), "verified": mcp_verified},
        "agent_skills": {"total": len(agent_skills), "verified": agent_verified},
        "last_build": datetime.now(timezone.utc).isoformat(),
    }
    _write_json(API_V2_META_DIR / "stats.json", stats_payload)
    logger.info("  -> v2/meta/stats.json")


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

    # 7. Build v2 meta files (lightweight agent-first indexes)
    build_v2_meta(skills, tags)

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
