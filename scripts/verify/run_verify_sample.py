#!/usr/bin/env python3
"""
Run deterministic verification (Agent C* scanner) on a sample of skills.

Clones repos, runs the static scanner (regex + semgrep), and updates
the skill JSON files with scan results.

Usage:
    python3 run_verify_sample.py [--limit N] [--source glama]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from src.reachability import log_to_skill_manager
from src.scanner.scanner import StaticScanner

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("verify_sample")

PROJECT_ROOT = Path(__file__).resolve().parent
SKILLS_DIR = PROJECT_ROOT / "data" / "skills"
REPORTS_DIR = PROJECT_ROOT / "data" / "scan-reports"
STATUS_TAG_PREFIX = "status-"
NOT_REACHABLE_TAG = "not_reachable"
STATUS_TAGS = {
    "status-pass",
    "status-manual_review",
    "status-fail",
    "status-unverified",
    "status-updated_unverified",
}


def get_skills(
    source: str | None,
    only_unverified: bool = False,
    skill_type: str | None = None,
    shard_index: int = 0,
    shard_count: int = 1,
    include_repo_unavailable: bool = False,
) -> list[dict]:
    """Load skill JSONs with optional filters."""
    skills = []
    for f in sorted(SKILLS_DIR.glob("*.json")):
        data = json.loads(f.read_text())
        if source and data.get("source_hub") != source:
            continue
        if skill_type and data.get("skill_type") != skill_type:
            continue
        tags = data.get("tags", [])
        tag_set = {str(t) for t in tags} if isinstance(tags, list) else set()
        if not include_repo_unavailable and ("repo_unavailable" in tag_set or "clone_failure" in tag_set or NOT_REACHABLE_TAG in tag_set):
            continue
        if data.get("repo_url", "").startswith("https://github.com/"):
            if only_unverified and normalize_status(data.get("verification_status")) not in {"unverified", "updated_unverified"}:
                continue
            skills.append(data)
    # Prioritize high-signal repos first.
    skills.sort(key=lambda row: int(row.get("stars") or 0), reverse=True)
    if shard_count > 1:
        skills = [row for i, row in enumerate(skills) if i % shard_count == shard_index]
    return skills


def clone_repo(repo_url: str, dest: Path, timeout: int = 120) -> tuple[bool, str | None]:
    """Shallow clone a repo. Returns (success, short_error)."""
    try:
        result = subprocess.run(
            [
                "git", "clone", "--depth", "1", "--single-branch",
                repo_url, str(dest),
            ],
            capture_output=True, text=True, timeout=timeout,
        )
        if result.returncode == 0:
            return True, None
        error = (result.stderr or result.stdout or "git clone failed").strip()
        error = " ".join(error.split())
        return False, error[:200]
    except (subprocess.TimeoutExpired, Exception) as exc:
        logger.warning("Clone failed for %s: %s", repo_url, exc)
        return False, str(exc)[:200]


def run_scanner(repo_path: str) -> dict:
    """Run deterministic scanner and return results as dict."""
    scanner = StaticScanner(repo_path)
    result = scanner.scan()
    return result.model_dump(mode="json")


def compute_scan_stats(scan_result: dict) -> dict:
    """Compute total_findings, severity_counts, and category_counts from findings list."""
    findings = scan_result.get("findings", [])
    total_findings = len(findings)
    severity_counts: dict[str, int] = {}
    category_counts: dict[str, int] = {}
    for finding in findings:
        sev = finding.get("severity", "info")
        severity_counts[sev] = severity_counts.get(sev, 0) + 1
        cat = finding.get("category", "unknown")
        category_counts[cat] = category_counts.get(cat, 0) + 1
    return {
        "total_findings": total_findings,
        "severity_counts": severity_counts,
        "category_counts": category_counts,
    }


def determine_risk_level(scan_result: dict) -> str:
    """Determine risk level from scan findings."""
    counts = scan_result.get("severity_counts", {})
    if counts.get("critical", 0) > 0:
        return "critical"
    if counts.get("high", 0) > 0:
        return "high"
    if counts.get("medium", 0) > 0:
        return "medium"
    if counts.get("low", 0) > 0:
        return "low"
    return "info"


def determine_score(scan_result: dict) -> int:
    """Rough score based on findings (higher = safer)."""
    total = scan_result.get("total_findings", 0)
    counts = scan_result.get("severity_counts", {})

    if counts.get("critical", 0) > 0:
        return max(10, 40 - counts["critical"] * 10)
    if counts.get("high", 0) > 0:
        return max(30, 60 - counts["high"] * 5)
    if total == 0:
        return 85  # No findings = good baseline
    if total <= 5:
        return 75
    if total <= 15:
        return 60
    return max(20, 50 - total)


def determine_status(score: int, risk: str) -> str:
    """Determine verification status from score and risk."""
    if risk == "critical":
        return "fail"
    if risk == "high":
        return "manual_review"
    if score >= 70:
        return "pass"
    if score >= 50:
        return "manual_review"
    return "fail"


def normalize_status(value: str | None) -> str:
    """Normalize verification status labels to canonical values."""
    if not value:
        return "unverified"
    raw = str(value).strip().lower()
    aliases = {
        "verified": "pass",
        "approved": "pass",
        "failed": "fail",
        "invalid": "fail",
        "review": "manual_review",
        "flagged": "manual_review",
        "updated-unverified": "updated_unverified",
    }
    normalized = aliases.get(raw, raw)
    allowed = {"pass", "fail", "manual_review", "updated_unverified", "unverified"}
    return normalized if normalized in allowed else "unverified"


def sync_status_tag(skill_data: dict, status: str | None) -> None:
    """Ensure exactly one status-* tag matches verification_status."""
    tags_raw = skill_data.get("tags", [])
    tags = [str(tag) for tag in tags_raw] if isinstance(tags_raw, list) else []
    tags = [tag for tag in tags if not tag.startswith(STATUS_TAG_PREFIX)]
    status_tag = f"status-{normalize_status(status)}"
    if status_tag not in STATUS_TAGS:
        status_tag = "status-unverified"
    tags.append(status_tag)
    skill_data["tags"] = list(dict.fromkeys(tags))


def main(
    limit: int = 10,
    source: str | None = None,
    only_unverified: bool = True,
    skill_type: str | None = None,
    shard_index: int = 0,
    shard_count: int = 1,
    include_repo_unavailable: bool = False,
) -> None:
    logger.info("=" * 60)
    logger.info("SecureSkillHub Sample Verification (Agent C* Scanner)")
    logger.info("=" * 60)

    skills = get_skills(
        source,
        only_unverified=only_unverified,
        skill_type=skill_type,
        shard_index=shard_index,
        shard_count=shard_count,
        include_repo_unavailable=include_repo_unavailable,
    )
    logger.info(
        "Selected %d candidate skills for verification (target scans: %d)",
        len(skills),
        limit,
    )
    logger.info(
        "Filters: source=%s only_unverified=%s skill_type=%s shard=%d/%d",
        source or "*",
        only_unverified,
        skill_type or "*",
        shard_index + 1,
        shard_count,
    )
    logger.info("Include repo_unavailable: %s", include_repo_unavailable)

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    scan_date = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    verified_count = 0
    failed_count = 0
    pass_count = 0
    review_count = 0
    clone_fail_count = 0
    scanner_error_count = 0

    attempted_count = 0
    for skill in skills:
        if verified_count >= limit:
            break

        attempted_count += 1
        name = skill["name"]
        repo_url = skill["repo_url"]
        skill_id = skill["id"]

        logger.info("")
        logger.info(
            "[attempt %d | scanned %d/%d] Verifying: %s",
            attempted_count,
            verified_count,
            limit,
            name,
        )
        logger.info("  Repo: %s", repo_url)

        # Clone to temp dir
        with tempfile.TemporaryDirectory(prefix="ssh_scan_") as tmp:
            clone_dest = Path(tmp) / "repo"
            clone_ok, clone_error = clone_repo(repo_url, clone_dest)
            if not clone_ok:
                clone_fail_count += 1
                logger.warning("  SKIP: Clone failed%s", f" ({clone_error})" if clone_error else "")
                skill_file = SKILLS_DIR / f"{skill_id}.json"
                try:
                    skill_data = json.loads(skill_file.read_text())
                    tags = skill_data.get("tags", [])
                    tags = list(tags) if isinstance(tags, list) else []
                    if "repo_unavailable" not in tags:
                        tags.append("repo_unavailable")
                    if NOT_REACHABLE_TAG not in tags:
                        tags.append(NOT_REACHABLE_TAG)
                    skill_data["tags"] = tags
                    skill_data["repo_status"] = "unavailable"
                    skill_data["repo_check_date"] = datetime.now(timezone.utc).isoformat()
                    skill_data["repo_check_error"] = (clone_error or "git clone failed")[:200]
                    sync_status_tag(skill_data, skill_data.get("verification_status"))
                    skill_file.write_text(json.dumps(skill_data, indent=2))
                except Exception as exc:
                    logger.warning(
                        "  Unable to persist clone failure metadata for %s: %s",
                        skill_id,
                        exc,
                    )
                continue

            # Capture verified commit hash
            try:
                commit_result = subprocess.run(
                    ["git", "rev-parse", "HEAD"],
                    capture_output=True, text=True,
                    cwd=str(clone_dest), check=True,
                )
                commit_sha = commit_result.stdout.strip()
            except subprocess.CalledProcessError:
                commit_sha = None

            # Run scanner
            try:
                scan_result = run_scanner(str(clone_dest))
                stats = compute_scan_stats(scan_result)
                scan_result.update(stats)
            except Exception as exc:
                scanner_error_count += 1
                logger.warning("  SKIP: Scanner error: %s", exc)
                continue

        # Determine outcomes
        risk = determine_risk_level(scan_result)
        score = determine_score(scan_result)
        status = determine_status(score, risk)

        total_findings = scan_result.get("total_findings", 0)
        files_scanned = scan_result.get("total_files_scanned", 0)
        severity = scan_result.get("severity_counts", {})

        logger.info(
            "  Result: status=%s score=%d risk=%s findings=%d files=%d",
            status, score, risk, total_findings, files_scanned,
        )
        logger.info("  Severity: %s", severity)

        # Save scan report
        report_dir = REPORTS_DIR / skill_id
        report_dir.mkdir(parents=True, exist_ok=True)
        (report_dir / "scanner_output.json").write_text(
            json.dumps(scan_result, indent=2)
        )

        # Update skill JSON
        skill_file = SKILLS_DIR / f"{skill_id}.json"
        skill_data = json.loads(skill_file.read_text())
        skill_data["verification_status"] = status
        skill_data["overall_score"] = score
        skill_data["risk_level"] = risk
        skill_data["scan_date"] = scan_date
        skill_data["scan_summary"] = {
            "total_findings": total_findings,
            "files_scanned": files_scanned,
            "severity_counts": severity,
            "category_counts": scan_result.get("category_counts", {}),
        }
        skill_data["verification_level"] = "scanner_only"
        if commit_sha:
            skill_data["verified_commit"] = commit_sha
        sync_status_tag(skill_data, status)

        # Build partial audit trail (only Agent C* signed)
        agent_audit = {
            "agents_completed": 1,
            "agents_required": 5,
            "pipeline_run_at": scan_date,
            "agent_a": {"signed": False},
            "agent_b": {"signed": False},
            "agent_c_star": {
                "signed": True,
                "signed_at": scan_date,
                "comment": f"{total_findings} findings: {severity}. "
                           f"{'No critical issues.' if severity.get('critical', 0) == 0 else 'CRITICAL issues found!'}",
                "total_findings": total_findings,
                "severity_counts": severity,
            },
            "agent_d": {"signed": False},
            "agent_e": {"signed": False},
            "manager_summary": f"1/5 agents completed (C* scanner only). {total_findings} findings. Status: {status}.",
        }
        skill_data["agent_audit"] = agent_audit

        skill_file.write_text(json.dumps(skill_data, indent=2))

        verified_count += 1
        if status == "pass":
            pass_count += 1
        elif status == "fail":
            failed_count += 1
        else:
            review_count += 1

    # Update stats from all skill files (not just this sample run).
    stats_file = PROJECT_ROOT / "data" / "stats.json"
    stats = json.loads(stats_file.read_text())

    all_skills = [
        json.loads(skill_file.read_text())
        for skill_file in sorted(SKILLS_DIR.glob("*.json"))
    ]
    status_counts = {
        "pass": 0,
        "fail": 0,
        "manual_review": 0,
        "updated_unverified": 0,
        "unverified": 0,
    }
    for record in all_skills:
        status = normalize_status(record.get("verification_status"))
        status_counts[status] = status_counts.get(status, 0) + 1

    stats["total_skills"] = len(all_skills)
    stats["verified_skills"] = status_counts["pass"]
    stats["failed_skills"] = status_counts["fail"]
    stats["pending_review"] = (
        status_counts["manual_review"] + status_counts["updated_unverified"]
    )
    stats["total_scans_run"] = (
        status_counts["pass"]
        + status_counts["fail"]
        + status_counts["manual_review"]
        + status_counts["updated_unverified"]
    )
    stats["last_verification_run"] = scan_date
    stats_file.write_text(json.dumps(stats, indent=2))

    try:
        log_to_skill_manager(
            check_type="verification_run",
            findings={
                "script": "run_verify_sample.py",
                "source": source or "*",
                "limit": limit,
                "candidates": len(skills),
                "attempted": attempted_count,
                "scanned": verified_count,
                "pass": pass_count,
                "manual_review": review_count,
                "fail": failed_count,
                "clone_failures": clone_fail_count,
                "scanner_errors": scanner_error_count,
                "only_unverified": only_unverified,
                "skill_type": skill_type or "*",
                "shard_index": shard_index,
                "shard_count": shard_count,
                "include_repo_unavailable": include_repo_unavailable,
            },
        )
    except Exception as exc:
        logger.warning("Unable to write skill-manager verification_run log: %s", exc)

    logger.info("")
    logger.info("=" * 60)
    logger.info("VERIFICATION SUMMARY")
    logger.info("=" * 60)
    logger.info("  Scanned: %d", verified_count)
    logger.info("  Passed:  %d", pass_count)
    logger.info("  Failed:  %d", failed_count)
    logger.info("  Review:  %d", review_count)
    logger.info("=" * 60)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--source", type=str, default=None)
    parser.add_argument("--only-unverified", dest="only_unverified", action="store_true", default=True)
    parser.add_argument("--include-verified", dest="only_unverified", action="store_false")
    parser.add_argument("--skill-type", type=str, default=None)
    parser.add_argument("--shard-index", type=int, default=0)
    parser.add_argument("--shard-count", type=int, default=1)
    parser.add_argument("--include-repo-unavailable", action="store_true", default=False)
    args = parser.parse_args()
    if args.shard_count < 1:
        raise ValueError("--shard-count must be >= 1")
    if args.shard_index < 0 or args.shard_index >= args.shard_count:
        raise ValueError("--shard-index must be in [0, shard-count)")
    main(
        limit=args.limit,
        source=args.source,
        only_unverified=args.only_unverified,
        skill_type=args.skill_type,
        shard_index=args.shard_index,
        shard_count=args.shard_count,
        include_repo_unavailable=args.include_repo_unavailable,
    )
