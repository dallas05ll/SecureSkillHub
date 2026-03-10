#!/usr/bin/env python3
"""
Regenerate the embedded catalog data inside skills/browse/SKILL.md

Run after every build to keep the skill's embedded data current:
    python3 scripts/build/build_plugin_catalog.py

This updates the "Full Catalog Map" section in browse.md with:
- Current skill counts per tag
- Current verified counts per tag
- Top 5 verified skills per leaf tag (by stars)
"""

import json
import glob
import re
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SKILL_DIR = ROOT / "data" / "skills"
TAGS_FILE = ROOT / "data" / "tags.json"
BROWSE_SKILL = ROOT / "skills" / "browse" / "SKILL.md"


def load_skills():
    """Load all available skills with key fields."""
    skills = []
    for f in SKILL_DIR.glob("*.json"):
        try:
            s = json.loads(f.read_text())
            tags = s.get("tags", [])
            if not tags or "repo_unavailable" in tags:
                continue
            skills.append({
                "id": s.get("id", s.get("skill_id", "")),
                "name": s.get("name", ""),
                "stars": s.get("stars", 0) or 0,
                "status": s.get("verification_status", "unverified"),
                "tags": tags,
                "owner": s.get("owner", ""),
            })
        except Exception:
            pass
    return skills


def count_by_tag(skills):
    """Count total and verified skills per tag."""
    total = defaultdict(int)
    verified = defaultdict(int)
    for s in skills:
        for t in s["tags"]:
            total[t] += 1
            if s["status"] == "pass":
                verified[t] += 1
    return total, verified


def top_skills_by_tag(skills, tag, n=5):
    """Get top N skills for a tag, sorted by stars."""
    matching = [s for s in skills if tag in s["tags"]]
    matching.sort(key=lambda x: x["stars"], reverse=True)
    return matching[:n]


def format_stars(stars):
    """Format star count compactly."""
    if stars >= 1000:
        return f"{stars / 1000:.0f}K" if stars < 100000 else f"{stars // 1000}K"
    return str(stars)


def format_skill_list(skills_list):
    """Format a list of skills as compact inline text."""
    entries = []
    for s in skills_list:
        v = "*" if s["status"] == "pass" else ""
        st = format_stars(s["stars"])
        entries.append(f"{s['name']}({st}{v})")
    return ", ".join(entries)


def build_catalog_section(skills, total_counts, verified_counts):
    """Build the full catalog map markdown section."""

    def tag_line(tag_id, label, skills_data):
        t = total_counts.get(tag_id, 0)
        v = verified_counts.get(tag_id, 0)
        top = top_skills_by_tag(skills_data, tag_id)
        top_str = format_skill_list(top) if top else ""
        count_str = f"{t} skills, {v} verified" if v > 0 else f"{t} skills"
        if top_str:
            return f"- {label} ({t}): {top_str}"
        return f"- {label} ({t})"

    lines = []

    # === DEV ===
    dt = total_counts.get("dev", 0)
    dv = verified_counts.get("dev", 0)
    lines.append(f"### dev: Development Tools ({dt:,} skills, {dv:,} verified)")
    lines.append("")

    lines.append(f"**dev-web-frontend** ({total_counts.get('dev-web-frontend', 0)} skills):")
    for tag, label in [("dev-web-frontend-react", "React"), ("dev-web-frontend-vue", "Vue"),
                        ("dev-web-frontend-svelte", "Svelte"), ("dev-web-frontend-angular", "Angular")]:
        top = top_skills_by_tag(skills, tag)
        lines.append(f"{tag_line(tag, label, skills)}")
    lines.append("")

    lines.append(f"**dev-web-backend** ({total_counts.get('dev-web-backend', 0)} skills):")
    for tag, label in [("dev-web-backend-python", "Python"), ("dev-web-backend-node", "Node.js"),
                        ("dev-web-backend-rust", "Rust"), ("dev-web-backend-go", "Go")]:
        lines.append(f"{tag_line(tag, label, skills)}")
    lines.append("")

    lines.append(f"**dev-web-fullstack** ({total_counts.get('dev-web-fullstack', 0)} skills):")
    for tag, label in [("dev-web-fullstack-nextjs", "Next.js"), ("dev-web-fullstack-nuxt", "Nuxt")]:
        lines.append(f"{tag_line(tag, label, skills)}")
    lines.append("")

    for tag, label in [("dev-testing", "dev-testing"), ("dev-git", "dev-git"),
                        ("dev-agents", "dev-agents")]:
        t = total_counts.get(tag, 0)
        top = format_skill_list(top_skills_by_tag(skills, tag))
        lines.append(f"**{tag}** ({t} skills): {top}")
    lines.append("")

    lines.append(f"**dev-devops** ({total_counts.get('dev-devops', 0)} skills):")
    for tag, label in [("dev-devops-docker", "Docker"), ("dev-devops-k8s", "Kubernetes"), ("dev-devops-ci", "CI/CD")]:
        lines.append(f"{tag_line(tag, label, skills)}")
    lines.append("")

    for tag, label in [("dev-mobile", "dev-mobile"), ("dev-desktop", "dev-desktop"), ("dev-gamedev", "dev-gamedev")]:
        t = total_counts.get(tag, 0)
        top = format_skill_list(top_skills_by_tag(skills, tag))
        lines.append(f"**{tag}** ({t} skills): {top}")
    lines.append("")

    # === DATA ===
    dt = total_counts.get("data", 0)
    dv = verified_counts.get("data", 0)
    lines.append(f"### data: Data & AI ({dt:,} skills, {dv:,} verified)")
    lines.append("")

    lines.append(f"**data-ai** ({total_counts.get('data-ai', 0)} skills):")
    for tag, label in [("data-ai-nlp", "NLP & Text"), ("data-ai-vision", "Vision"),
                        ("data-ai-audio", "Audio & Speech"), ("data-ai-rag", "RAG & Retrieval")]:
        lines.append(f"{tag_line(tag, label, skills)}")
    lines.append("")

    lines.append(f"**data-db** ({total_counts.get('data-db', 0)} skills):")
    for tag, label in [("data-db-vector", "Vector"), ("data-db-graph", "Graph")]:
        lines.append(f"{tag_line(tag, label, skills)}")
    t_db = total_counts.get("data-db", 0)
    top_db = format_skill_list(top_skills_by_tag(skills, "data-db"))
    lines.append(f"- General DB: {top_db}")
    lines.append("")

    for tag, label in [("data-ml", "data-ml"), ("data-analysis", "data-analysis"), ("data-finance", "data-finance")]:
        t = total_counts.get(tag, 0)
        top = format_skill_list(top_skills_by_tag(skills, tag))
        lines.append(f"**{tag}** ({t} skills): {top}")
    lines.append("")

    # === INTEGRATIONS ===
    int_tags = ["integrations-github", "integrations-google", "integrations-messaging",
                "integrations-slack", "integrations-notion", "integrations-jira"]
    int_total = sum(total_counts.get(t, 0) for t in int_tags)
    int_verified = sum(verified_counts.get(t, 0) for t in int_tags)
    lines.append(f"### integrations: Integrations ({int_total} skills, {int_verified} verified)")
    lines.append("")
    for tag, label in [("integrations-github", "GitHub"), ("integrations-google", "Google"),
                        ("integrations-messaging", "Messaging"), ("integrations-slack", "Slack"),
                        ("integrations-notion", "Notion"), ("integrations-jira", "Jira")]:
        lines.append(f"{tag_line(tag, label, skills)}")
    lines.append("")

    # === SECURITY ===
    # Use parent tag only to avoid double-counting skills in both parent and child tags
    sec_total = total_counts.get("security", 0)
    sec_verified = verified_counts.get("security", 0)
    lines.append(f"### security: Security ({sec_total} skills, {sec_verified} verified)")
    lines.append("")
    for tag, label in [("security-secrets", "Secrets"), ("security-compliance", "Compliance & Legal")]:
        lines.append(f"{tag_line(tag, label, skills)}")
    lines.append("")

    # === UTILITIES ===
    lines.append(f"### utilities: Utilities ({total_counts.get('utilities', 0)} skills, {verified_counts.get('utilities', 0)} verified)")
    lines.append("")
    for tag, label in [("utilities-system", "System Tools"), ("productivity-email", "Email")]:
        lines.append(f"{tag_line(tag, label, skills)}")

    return "\n".join(lines)


def update_browse_skill():
    """Update the browse.md skill file with current catalog data."""
    if not BROWSE_SKILL.exists():
        print(f"ERROR: {BROWSE_SKILL} not found")
        return False

    content = BROWSE_SKILL.read_text()

    # Load data
    skills = load_skills()
    total_counts, verified_counts = count_by_tag(skills)

    # Build new catalog section
    new_catalog = build_catalog_section(skills, total_counts, verified_counts)

    # Replace between markers
    pattern = r"(## Full Catalog Map\n)(.*?)(---\n\n## How to Help Users)"
    replacement = f"## Full Catalog Map\n\n{new_catalog}\n\n---\n\n## How to Help Users"

    # Use a lambda to prevent re.sub from interpreting backslashes in replacement string
    new_content = re.sub(pattern, lambda m: replacement, content, flags=re.DOTALL)

    if not re.search(pattern, content, flags=re.DOTALL):
        print("ERROR: Markers not found in browse.md — cannot update catalog section")
        return False

    BROWSE_SKILL.write_text(new_content)

    # Update stats
    available = len(skills)
    verified = sum(1 for s in skills if s["status"] == "pass")
    total_all = len(list(SKILL_DIR.glob("*.json")))

    print(f"Updated browse.md catalog:")
    print(f"  Available skills: {available:,}")
    print(f"  Verified skills: {verified:,}")
    print(f"  Total files: {total_all:,}")
    print(f"  Tags with skills: {sum(1 for v in total_counts.values() if v > 0)}")

    return True


if __name__ == "__main__":
    update_browse_skill()
