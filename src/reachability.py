"""
Shared repo reachability checking and skills manager logging.

Used by:
  - check_reachability.py (batch mode)
  - process_discovered.py (inline during crawl)
  - crawl_agent_skills.py (inline during crawl)
  - health_check.py (reading logs)
"""
from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

TAG_UNAVAILABLE = "repo_unavailable"
TAG_CLONE_FAILURE = "clone_failure"  # Legacy, mapped to repo_unavailable
TAG_NOT_REACHABLE = "not_reachable"  # Human/agent friendly alias

SKILL_MANAGER_LOG = Path("data/skill-manager-log.json")


def check_repo(repo_url: str, timeout: int = 15) -> dict:
    """Check if a repo is reachable via git ls-remote.

    Returns:
        {"reachable": bool, "returncode": int, "error": str|None}
    """
    if not repo_url:
        return {"reachable": False, "returncode": -1, "error": "no repo_url"}
    try:
        result = subprocess.run(
            ["git", "ls-remote", "--exit-code", "--heads", repo_url],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return {
            "reachable": result.returncode == 0,
            "returncode": result.returncode,
            "error": result.stderr.strip()[:200] if result.returncode != 0 else None,
        }
    except subprocess.TimeoutExpired:
        return {"reachable": False, "returncode": -1, "error": "timeout"}
    except Exception as e:
        return {"reachable": False, "returncode": -1, "error": str(e)[:200]}


def is_unavailable(skill_data: dict) -> bool:
    """Check if a skill is already tagged as unavailable."""
    tags = skill_data.get("tags", [])
    return TAG_UNAVAILABLE in tags or TAG_CLONE_FAILURE in tags or TAG_NOT_REACHABLE in tags


def mark_unavailable(skill_data: dict, error_msg: str | None = None) -> dict:
    """Add repo_unavailable tag to a skill dict (in-memory, does not write to disk)."""
    tags = list(skill_data.get("tags", []))
    if TAG_CLONE_FAILURE in tags:
        tags.remove(TAG_CLONE_FAILURE)
    if TAG_UNAVAILABLE not in tags:
        tags.append(TAG_UNAVAILABLE)
    if TAG_NOT_REACHABLE not in tags:
        tags.append(TAG_NOT_REACHABLE)
    skill_data["tags"] = tags
    skill_data["repo_status"] = "unavailable"
    skill_data["repo_check_date"] = datetime.now(timezone.utc).isoformat()
    if error_msg:
        skill_data["repo_check_error"] = error_msg[:200]
    return skill_data


def log_to_skill_manager(
    check_type: str,
    findings: dict,
    recommendations: list[str] | None = None,
) -> None:
    """Append an entry to the skills manager log.

    Args:
        check_type: One of "crawl_run", "reachability_run", "health_check",
                    "verification_run"
        findings: Dict with type-specific metrics
        recommendations: Optional list of action items
    """
    log_data = {"log_version": 1, "entries": []}
    if SKILL_MANAGER_LOG.exists():
        try:
            log_data = json.loads(SKILL_MANAGER_LOG.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            log_data = {"log_version": 1, "entries": []}

    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "check_type": check_type,
        "findings": findings,
    }
    if recommendations:
        entry["recommendations"] = recommendations

    log_data.setdefault("entries", []).append(entry)

    SKILL_MANAGER_LOG.parent.mkdir(parents=True, exist_ok=True)
    SKILL_MANAGER_LOG.write_text(
        json.dumps(log_data, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def check_and_filter_skills(
    skills: list[dict],
    source: str = "unknown",
    workers: int = 10,
    timeout: int = 15,
) -> tuple[list[dict], list[dict]]:
    """Check reachability for a list of skill dicts and split into reachable/unreachable.

    Returns:
        (reachable_skills, unreachable_skills) — unreachable are tagged with repo_unavailable
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    reachable = []
    unreachable = []

    if not skills:
        return reachable, unreachable

    def _check(skill: dict) -> tuple[dict, dict]:
        repo = skill.get("repo_url", "")
        return skill, check_repo(repo, timeout=timeout)

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(_check, s): s for s in skills}
        for future in as_completed(futures):
            skill, result = future.result()
            if result["reachable"]:
                reachable.append(skill)
            else:
                mark_unavailable(skill, result.get("error"))
                unreachable.append(skill)

    # Log to skills manager
    log_to_skill_manager(
        check_type="crawl_reachability",
        findings={
            "source": source,
            "total_checked": len(skills),
            "reachable": len(reachable),
            "unreachable": len(unreachable),
        },
        recommendations=(
            [f"High unreachable rate ({len(unreachable)}/{len(skills)}) from {source} — consider reviewing hub quality"]
            if len(unreachable) > len(skills) * 0.3
            else None
        ),
    )

    return reachable, unreachable
