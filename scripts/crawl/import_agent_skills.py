#!/usr/bin/env python3
"""
Import Agent Skills from claudeskills.info extracted data into data/skills/.

Reads the extracted JSON and creates skill files with skill_type=agent_skill.
Preserves existing MCP skill files.

Usage:
    python3 import_agent_skills.py
"""

import json
import logging
import re
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("import_agent_skills")

PROJECT_ROOT = Path(__file__).resolve().parent
SKILLS_DIR = PROJECT_ROOT / "data" / "skills"
EXTRACTED_FILE = PROJECT_ROOT / "data" / "claudeskills_info_complete.json"


def make_skill_id(name: str, repo_url: str) -> str:
    """Generate a deterministic skill ID."""
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:40]
    ns = uuid.UUID("a1b2c3d4-e5f6-7890-abcd-ef1234567890")
    suffix = str(uuid.uuid5(ns, repo_url))[:8]
    return f"{slug}-{suffix}"


def main():
    logger.info("=" * 60)
    logger.info("Importing Agent Skills from claudeskills.info")
    logger.info("=" * 60)

    data = json.loads(EXTRACTED_FILE.read_text())
    raw_skills = data.get("skills", [])
    logger.info("Found %d skills in extracted data", len(raw_skills))

    SKILLS_DIR.mkdir(parents=True, exist_ok=True)

    imported = 0
    skipped = 0

    for raw in raw_skills:
        name = raw.get("name", "")
        repo_url = raw.get("github_url", "")

        if not name or not repo_url:
            skipped += 1
            continue

        skill_id = make_skill_id(name, repo_url)
        filepath = SKILLS_DIR / f"{skill_id}.json"

        # Map categories to our tag format
        categories = raw.get("categories", [])
        source_tags = raw.get("tags", [])
        tags = []
        for cat in categories:
            tag_map = {
                "dev": "dev",
                "creative": "data-ai-vision",
                "design": "data-ai-vision",
                "productivity": "prod",
                "office": "prod-docs",
                "communication": "prod-comm",
                "ai": "data-ai",
                "data-analysis": "data",
                "security": "sec",
                "testing": "dev-testing",
                "meta": "util",
                "learning": "prod-docs",
                "research": "data-ai",
            }
            mapped = tag_map.get(cat, "util")
            if mapped not in tags:
                tags.append(mapped)

        skill_data = {
            "id": skill_id,
            "name": name,
            "description": raw.get("description", ""),
            "repo_url": repo_url,
            "source_hub": "claude_skills_hub",
            "skill_type": "agent_skill",
            "owner": raw.get("repo_owner", ""),
            "stars": raw.get("stars", 0),
            "forks": raw.get("forks", 0),
            "license": raw.get("license", ""),
            "primary_language": "markdown",
            "tags": tags,
            "source_tags": source_tags,
            "categories": categories,
            "version": raw.get("version", ""),
            "requires_code_execution": raw.get("requires_code_execution", False),
            "verification_status": "unverified",
            "overall_score": 0,
            "risk_level": "info",
            "verified_commit": None,
            "scan_summary": None,
        }

        filepath.write_text(json.dumps(skill_data, indent=2))
        imported += 1

    logger.info("Imported: %d Agent Skills", imported)
    logger.info("Skipped: %d (missing name/url)", skipped)

    # Update stats
    stats_file = PROJECT_ROOT / "data" / "stats.json"
    stats = json.loads(stats_file.read_text())

    # Recount everything
    total = 0
    verified = 0
    sources = {}
    skill_types = {"mcp_server": 0, "agent_skill": 0}

    for f in SKILLS_DIR.glob("*.json"):
        d = json.loads(f.read_text())
        total += 1
        if d.get("verification_status") == "pass":
            verified += 1
        src = d.get("source_hub", "unknown")
        sources[src] = sources.get(src, 0) + 1
        st = d.get("skill_type", "mcp_server")
        skill_types[st] = skill_types.get(st, 0) + 1

    stats["total_skills"] = total
    stats["verified_skills"] = verified
    stats["sources"] = sources
    stats["skill_types"] = skill_types
    stats_file.write_text(json.dumps(stats, indent=2))

    logger.info("")
    logger.info("Updated stats: %d total skills", total)
    logger.info("  MCP Servers: %d", skill_types["mcp_server"])
    logger.info("  Agent Skills: %d", skill_types["agent_skill"])
    logger.info("  Sources: %s", json.dumps(sources))
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
