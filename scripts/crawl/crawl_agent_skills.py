#!/usr/bin/env python3
"""
Crawl Agent Skills directly from GitHub using gh CLI.

Searches for repos with SKILL.md files and skill-related topics.
No API key needed — uses authenticated gh CLI.

Usage:
    python3 crawl_agent_skills.py [--limit 500]
"""

import argparse
import json
import logging
import re
import subprocess
import sys
import time
import uuid
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("crawl_agent_skills")

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
SKILLS_DIR = PROJECT_ROOT / "data" / "skills"

# GitHub topics that indicate agent skills
TOPICS = [
    "claude-skill",
    "claude-code-skill",
    "claude-skills",
    "agent-skill",
    "skill-md",
    "claude-code-plugin",
    "claude-plugin",
    "codex-skill",
]

# Also search for repos with SKILL.md in name/description
SEARCH_QUERIES = [
    "SKILL.md claude",
    "agent skill claude code",
    "claude code skill",
]


def gh_search_repos(query: str, limit: int = 100, sort: str = "stars") -> list[dict]:
    """Search GitHub repos via gh CLI."""
    try:
        result = subprocess.run(
            [
                "gh", "search", "repos", query,
                "--sort", sort, "--order", "desc",
                "--limit", str(limit),
                "--json", "name,owner,stargazersCount,description,url,updatedAt,license",
            ],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode == 0 and result.stdout.strip():
            return json.loads(result.stdout)
    except Exception as exc:
        logger.warning("Search failed for '%s': %s", query, exc)
    return []


def gh_search_code(query: str, limit: int = 100) -> list[dict]:
    """Search GitHub code via gh CLI to find repos with SKILL.md files."""
    try:
        result = subprocess.run(
            [
                "gh", "search", "code", query,
                "--limit", str(limit),
                "--json", "repository,path",
            ],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode == 0 and result.stdout.strip():
            return json.loads(result.stdout)
    except Exception as exc:
        logger.warning("Code search failed for '%s': %s", query, exc)
    return []


def make_skill_id(name: str, repo_url: str) -> str:
    """Generate a deterministic skill ID."""
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:40]
    ns = uuid.UUID("a1b2c3d4-e5f6-7890-abcd-ef1234567890")
    suffix = str(uuid.uuid5(ns, repo_url))[:8]
    return f"{slug}-{suffix}"


def repo_to_skill(repo: dict) -> dict | None:
    """Convert a GitHub repo result to our skill format."""
    owner = repo.get("owner", {})
    owner_login = owner.get("login", "") if isinstance(owner, dict) else ""
    name = repo.get("name", "")
    url = repo.get("url", "")
    stars = repo.get("stargazersCount", 0)
    desc = repo.get("description", "") or ""
    updated = repo.get("updatedAt", "")
    license_info = repo.get("license", {})
    license_key = ""
    if isinstance(license_info, dict):
        license_key = license_info.get("key", "") or ""

    if not name or not url:
        return None

    skill_id = make_skill_id(name, url)

    return {
        "id": skill_id,
        "name": name,
        "description": desc[:500],
        "repo_url": url,
        "source_hub": "github_search",
        "skill_type": "agent_skill",
        "owner": owner_login,
        "stars": stars,
        "license": license_key,
        "primary_language": "markdown",
        "tags": [],
        "verification_status": "unverified",
        "overall_score": 0,
        "risk_level": "info",
        "verified_commit": None,
        "scan_summary": None,
        "last_updated": updated[:40] if updated else None,
    }


def main(limit: int = 500):
    logger.info("=" * 60)
    logger.info("Crawling Agent Skills from GitHub")
    logger.info("=" * 60)

    seen_urls: set[str] = set()
    all_skills: list[dict] = []

    # Load existing skills to avoid duplicates
    for f in SKILLS_DIR.glob("*.json"):
        try:
            d = json.loads(f.read_text())
            url = d.get("repo_url", "").lower().rstrip("/")
            if url:
                seen_urls.add(url)
        except Exception:
            pass
    logger.info("Loaded %d existing skill URLs for dedup", len(seen_urls))

    # Phase 1: Search by topics
    for topic in TOPICS:
        if len(all_skills) >= limit:
            break

        logger.info("Searching topic: %s", topic)
        repos = gh_search_repos(f"topic:{topic}", limit=100)
        new = 0
        for repo in repos:
            url = (repo.get("url", "") or "").lower().rstrip("/")
            if url in seen_urls:
                continue
            seen_urls.add(url)

            skill = repo_to_skill(repo)
            if skill:
                all_skills.append(skill)
                new += 1

        logger.info("  Found %d repos, %d new (total: %d)", len(repos), new, len(all_skills))
        time.sleep(1)  # Rate limit between searches

    # Phase 2: Search by queries
    for query in SEARCH_QUERIES:
        if len(all_skills) >= limit:
            break

        logger.info("Searching: '%s'", query)
        repos = gh_search_repos(query, limit=100)
        new = 0
        for repo in repos:
            url = (repo.get("url", "") or "").lower().rstrip("/")
            if url in seen_urls:
                continue
            seen_urls.add(url)

            skill = repo_to_skill(repo)
            if skill:
                all_skills.append(skill)
                new += 1

        logger.info("  Found %d repos, %d new (total: %d)", len(repos), new, len(all_skills))
        time.sleep(1)

    # Phase 3: Code search for SKILL.md files
    logger.info("Searching for repos containing SKILL.md files...")
    code_results = gh_search_code("filename:SKILL.md path:/ language:markdown", limit=100)
    new = 0
    code_repos_seen = set()
    for item in code_results:
        repo_info = item.get("repository", {})
        repo_name = repo_info.get("name", "")
        owner = repo_info.get("owner", {}).get("login", "")
        if not repo_name or not owner:
            continue

        url = f"https://github.com/{owner}/{repo_name}".lower()
        if url in seen_urls or url in code_repos_seen:
            continue
        code_repos_seen.add(url)
        seen_urls.add(url)

        # Fetch full repo info for stars
        try:
            result = subprocess.run(
                ["gh", "api", f"repos/{owner}/{repo_name}",
                 "--jq", "{name,stargazers_count,description,html_url,updated_at,license}"],
                capture_output=True, text=True, timeout=15,
            )
            if result.returncode == 0:
                repo_data = json.loads(result.stdout)
                skill = {
                    "id": make_skill_id(repo_data.get("name", repo_name), url),
                    "name": repo_data.get("name", repo_name),
                    "description": (repo_data.get("description", "") or "")[:500],
                    "repo_url": repo_data.get("html_url", url),
                    "source_hub": "github_search",
                    "skill_type": "agent_skill",
                    "owner": owner,
                    "stars": repo_data.get("stargazers_count", 0),
                    "license": (repo_data.get("license") or {}).get("key", "") if isinstance(repo_data.get("license"), dict) else "",
                    "primary_language": "markdown",
                    "tags": [],
                    "verification_status": "unverified",
                    "overall_score": 0,
                    "risk_level": "info",
                    "verified_commit": None,
                    "scan_summary": None,
                }
                all_skills.append(skill)
                new += 1
        except Exception:
            pass
        time.sleep(0.15)

    logger.info("  Code search: %d results, %d new (total: %d)", len(code_results), new, len(all_skills))

    # Trim to limit
    all_skills = all_skills[:limit]

    # Filter out skills that already exist (dedup check)
    new_skills = []
    SKILLS_DIR.mkdir(parents=True, exist_ok=True)
    existing_repos = set()
    for f in SKILLS_DIR.glob("*.json"):
        try:
            d = json.loads(f.read_text())
            repo = d.get("repo_url", "").rstrip("/").lower()
            if repo:
                existing_repos.add(repo)
        except Exception:
            pass

    for skill in all_skills:
        repo = skill.get("repo_url", "").rstrip("/").lower()
        filepath = SKILLS_DIR / f"{skill['id']}.json"
        if not filepath.exists() and repo not in existing_repos:
            new_skills.append(skill)

    logger.info("After dedup: %d new skills (of %d discovered)", len(new_skills), len(all_skills))

    # Reachability check — skip unavailable repos
    from src.reachability import check_and_filter_skills, log_to_skill_manager

    logger.info("Checking reachability for %d new skills...", len(new_skills))
    reachable, unreachable = check_and_filter_skills(
        new_skills,
        source="github_search",
        workers=10,
        timeout=15,
    )
    logger.info("Reachability: %d reachable, %d unreachable (skipped)", len(reachable), len(unreachable))

    # Write only reachable skill files
    written = 0
    for skill in reachable:
        filepath = SKILLS_DIR / f"{skill['id']}.json"
        filepath.write_text(json.dumps(skill, indent=2))
        written += 1

    # Log to skills manager
    log_to_skill_manager(
        check_type="crawl_run",
        findings={
            "source": "github_search",
            "total_discovered": len(all_skills),
            "already_existing": len(all_skills) - len(new_skills),
            "new_checked": len(new_skills),
            "reachable": len(reachable),
            "unreachable_skipped": len(unreachable),
            "written": written,
        },
    )

    logger.info("")
    logger.info("=" * 60)
    logger.info("CRAWL SUMMARY")
    logger.info("=" * 60)
    logger.info("  Total discovered: %d", len(all_skills))
    logger.info("  Already existing: %d", len(all_skills) - len(new_skills))
    logger.info("  Reachable (new):  %d", len(reachable))
    logger.info("  Unreachable:      %d (skipped)", len(unreachable))
    logger.info("  Written to disk:  %d", written)

    # Star distribution
    stars = [s.get("stars", 0) for s in all_skills]
    logger.info("  Stars: 1000+=%d, 100-999=%d, 10-99=%d, 1-9=%d, 0=%d",
                sum(1 for s in stars if s >= 1000),
                sum(1 for s in stars if 100 <= s < 1000),
                sum(1 for s in stars if 10 <= s < 100),
                sum(1 for s in stars if 1 <= s < 10),
                sum(1 for s in stars if s == 0))
    logger.info("=" * 60)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=500)
    args = parser.parse_args()
    main(limit=args.limit)
