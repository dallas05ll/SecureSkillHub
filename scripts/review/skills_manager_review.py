#!/usr/bin/env python3
"""
Skills Manager Review — Dual-agent post-verification review orchestrator.

Two review agents cross-validate verification decisions:
  SM-A (Reviewer): verification quality — does the verification_level match the evidence?
  SM-B (Auditor):  data integrity — are tags, fields, and metadata consistent?

Modes:
  --run-report <path>     Review all skills from a verification run report
  --skill-ids <ids>       Review specific skills (comma-separated)
  --manual-review-queue   Review all current manual_review skills
  --periodic              Full collection audit (data quality sweep)
  --limit N               Limit number of skills to review

After review, decisions are logged to data/skill-manager-log.json.
Manual_review skills are flagged for PM attention.

Usage:
    python3 skills_manager_review.py --run-report data/verification-runs/20260301T050752Z_strict5_limit50.json
    python3 skills_manager_review.py --manual-review-queue --limit 10
    python3 skills_manager_review.py --periodic
    python3 skills_manager_review.py --skill-ids skill_a,skill_b
"""

import argparse
import json
import os
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
SKILLS_DIR = PROJECT_ROOT / "data" / "skills"
VERIFICATION_RUNS_DIR = PROJECT_ROOT / "data" / "verification-runs"
SCAN_REPORTS_DIR = PROJECT_ROOT / "data" / "scan-reports"
STATUS_TAG_PREFIX = "status-"
STATUS_TAGS = {
    "status-pass",
    "status-manual_review",
    "status-fail",
    "status-unverified",
    "status-updated_unverified",
}
PM_REVIEWER = "pm_dual_agent"

# Import shared logging
sys.path.insert(0, str(PROJECT_ROOT))
from src.reachability import log_to_skill_manager


# ---------------------------------------------------------------------------
# Skill loading
# ---------------------------------------------------------------------------

def load_skill(skill_id: str) -> dict | None:
    """Load a skill JSON by ID."""
    path = SKILLS_DIR / f"{skill_id}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def load_skills_by_ids(skill_ids: list[str]) -> list[dict]:
    """Load multiple skills by ID."""
    skills = []
    for sid in skill_ids:
        skill = load_skill(sid)
        if skill:
            skills.append(skill)
    return skills


def load_run_report(path: str) -> dict | None:
    """Load a verification run report."""
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, FileNotFoundError):
        return None


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


def sync_status_tag(skill_data: dict, status: str) -> None:
    """Ensure exactly one status-* tag matches verification_status."""
    tags_raw = skill_data.get("tags", [])
    tags = [str(tag) for tag in tags_raw] if isinstance(tags_raw, list) else []
    tags = [tag for tag in tags if not tag.startswith(STATUS_TAG_PREFIX)]
    status_tag = f"{STATUS_TAG_PREFIX}{normalize_status(status)}"
    if status_tag not in STATUS_TAGS:
        status_tag = "status-unverified"
    tags.append(status_tag)
    skill_data["tags"] = list(dict.fromkeys(tags))


def _safe_load_json(path: Path) -> dict:
    """Load JSON dict safely and return empty dict on errors."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError, FileNotFoundError):
        return {}


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def get_manual_review_skills(limit: int | None = None) -> list[dict]:
    """Get all skills with manual_review status."""
    skills = []
    for f in sorted(SKILLS_DIR.glob("*.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if data.get("verification_status") == "manual_review":
            skills.append(data)
            if limit and len(skills) >= limit:
                break
    return skills


def get_all_pass_skills(limit: int | None = None) -> list[dict]:
    """Get all pass skills for periodic audit."""
    skills = []
    for f in sorted(SKILLS_DIR.glob("*.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if data.get("verification_status") == "pass":
            skills.append(data)
            if limit and len(skills) >= limit:
                break
    return skills


# ---------------------------------------------------------------------------
# PM: Final review decision writer
# ---------------------------------------------------------------------------

def pm_decide(skill: dict) -> tuple[str, str, dict]:
    """Project Manager final decision for a manual_review skill.

    Security-first deterministic tree:
    - Repo unavailable/clone issues -> keep manual_review (needs retry)
    - Critical/obfuscation/injection -> fail
    - High-risk findings -> fail
    - High-confidence safe profile -> pass
    - Else keep manual_review
    """
    skill_id = str(skill.get("id") or "")
    tags_raw = skill.get("tags", [])
    tags = {str(t) for t in tags_raw} if isinstance(tags_raw, list) else set()
    repo_unavailable = (
        "repo_unavailable" in tags
        or "clone_failure" in tags
        or str(skill.get("repo_status") or "").lower() == "unavailable"
    )

    scanner = _safe_load_json(SCAN_REPORTS_DIR / skill_id / "agent_c_scanner.json")
    findings = scanner.get("findings", [])
    findings = findings if isinstance(findings, list) else []

    high_findings = 0
    critical_findings = 0
    for finding in findings:
        if not isinstance(finding, dict):
            continue
        sev = str(finding.get("severity") or "").lower()
        if sev == "high":
            high_findings += 1
        elif sev == "critical":
            critical_findings += 1

    obfuscation_high = _safe_int(scanner.get("obfuscation_high_risk_count"))
    injection_patterns = _safe_int(scanner.get("injection_patterns_count"))
    score = _safe_int(skill.get("overall_score"))
    risk = str(skill.get("risk_level") or "").lower()

    evidence = {
        "score": score,
        "risk_level": risk,
        "high_findings": high_findings,
        "critical_findings": critical_findings,
        "obfuscation_high_risk_count": obfuscation_high,
        "injection_patterns_count": injection_patterns,
        "repo_unavailable": repo_unavailable,
    }

    if repo_unavailable:
        return (
            "manual_review",
            "PM kept manual_review: repo unavailable or clone failure; retry verification after reachability recovery.",
            evidence,
        )
    if critical_findings > 0 or obfuscation_high > 0 or injection_patterns > 0:
        return (
            "fail",
            "PM final decision: fail due to critical/obfuscation/injection security signals.",
            evidence,
        )
    if risk in {"high", "critical"} or high_findings > 0:
        return (
            "fail",
            "PM final decision: fail due to high-risk scanner findings.",
            evidence,
        )
    if score >= 80 and risk in {"info", "low", "medium"} and high_findings == 0 and critical_findings == 0:
        return (
            "pass",
            "PM final decision: pass (high score with no high/critical findings).",
            evidence,
        )
    if score < 50:
        return (
            "fail",
            "PM final decision: fail (low score).",
            evidence,
        )
    return (
        "manual_review",
        "PM kept manual_review: ambiguous medium-risk profile; requires direct repository inspection.",
        evidence,
    )


def apply_pm_decision(skill_id: str, previous_status: str, decision: str, reason: str, evidence: dict, mode: str) -> None:
    """Write PM decision to skill JSON and log to skills-manager memory."""
    path = SKILLS_DIR / f"{skill_id}.json"
    if not path.exists():
        return
    skill_data = _safe_load_json(path)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # Status + tags
    skill_data["verification_status"] = normalize_status(decision)
    sync_status_tag(skill_data, skill_data["verification_status"])

    # Store PM decision comment directly in findings_summary and manager summary.
    findings_summary = skill_data.get("findings_summary")
    if not isinstance(findings_summary, dict):
        findings_summary = {}
    findings_summary["pm_review"] = {
        "reviewed_at": now,
        "reviewer": PM_REVIEWER,
        "previous_status": normalize_status(previous_status),
        "decision": normalize_status(decision),
        "reason": reason[:500],
        "mode": mode,
        "evidence": evidence,
    }
    skill_data["findings_summary"] = findings_summary

    agent_audit = skill_data.get("agent_audit")
    if not isinstance(agent_audit, dict):
        agent_audit = {}
    previous_summary = str(agent_audit.get("manager_summary") or "").strip()
    note = f"[{now}] PM review: {normalize_status(decision)}. {reason}"
    agent_audit["manager_summary"] = (previous_summary + "\n" + note).strip() if previous_summary else note
    skill_data["agent_audit"] = agent_audit

    path.write_text(json.dumps(skill_data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    # Per-skill PM memory entry
    log_to_skill_manager(
        check_type="pm_review",
        findings={
            "skill_id": skill_id,
            "previous_status": normalize_status(previous_status),
            "decision": normalize_status(decision),
            "reason": reason[:300],
            "reviewer": PM_REVIEWER,
            "mode": mode,
        },
    )


def finalize_manual_reviews(skills: list[dict], mode: str) -> dict:
    """Apply PM final decisions for manual_review skills."""
    decisions = Counter()
    reviewed = 0
    for skill in skills:
        skill_id = str(skill.get("id") or "")
        if not skill_id:
            continue
        current = normalize_status(skill.get("verification_status"))
        if current != "manual_review":
            continue
        decision, reason, evidence = pm_decide(skill)
        apply_pm_decision(skill_id, current, decision, reason, evidence, mode)
        decisions[decision] += 1
        reviewed += 1

    summary = {
        "reviewed": reviewed,
        "decision_counts": dict(decisions),
    }
    return summary


# ---------------------------------------------------------------------------
# SM-A: Verification Quality Reviewer
# ---------------------------------------------------------------------------

def all_5_agents_signed(agent_audit: dict) -> bool:
    """Check if all 5 agents signed the audit."""
    if not agent_audit:
        return False
    required = ["agent_a", "agent_b", "agent_c_star", "agent_d", "agent_e"]
    return all(
        agent_audit.get(a, {}).get("signed", False)
        for a in required
    )


def review_verification_quality(skill: dict) -> dict:
    """SM-A: Review verification quality for a single skill.

    Checks:
    - verification_level matches agent_audit evidence
    - Score thresholds are appropriate
    - Safety overrides were applied where needed
    - verified_commit is non-null for scanner+ levels
    - For manual_review: identifies WHY it was flagged
    """
    skill_id = skill.get("id", "unknown")
    status = skill.get("verification_status", "unverified")
    level = skill.get("verification_level", "")
    agent_audit = skill.get("agent_audit")
    score = skill.get("overall_score", 0)
    verified_commit = (skill.get("verified_commit") or "").strip()
    risk_level = skill.get("risk_level", "info")
    findings_summary = skill.get("findings_summary")

    issues = []
    info = []

    # Check verification_level consistency
    if status == "pass":
        if not level:
            issues.append("MISSING verification_level on pass skill")

        if level == "full_pipeline" and not all_5_agents_signed(agent_audit or {}):
            issues.append("Claims full_pipeline but not all 5 agents signed")

        if level in ("full_pipeline", "scanner_only") and not verified_commit:
            issues.append(f"Level={level} but no verified_commit (code was cloned but commit not recorded)")

        if level == "full_pipeline" and score < 80:
            issues.append(f"Full pipeline pass with score {score} (expected >= 80)")

        if level == "scanner_only" and score < 70:
            issues.append(f"Scanner-only pass with score {score} (expected >= 70)")

    # Check safety overrides
    if agent_audit:
        agent_d = agent_audit.get("agent_d", {})
        if isinstance(agent_d, dict) and agent_d.get("signed"):
            # D signed — check if risk level is appropriate
            if risk_level in ("high", "critical") and status == "pass":
                info.append(f"Pass with {risk_level} risk — verify safety override was intentional")

    # Manual review analysis
    if status == "manual_review":
        reasons = []
        if isinstance(findings_summary, dict):
            scanner_findings = findings_summary.get("scanner_findings", 0)
            if scanner_findings and int(scanner_findings) > 0:
                reasons.append(f"{scanner_findings} scanner findings")
            mismatches = findings_summary.get("mismatches", 0)
            if mismatches and int(mismatches) > 0:
                reasons.append(f"{mismatches} doc/code mismatches")
            undoc = findings_summary.get("undocumented_capabilities", 0)
            if undoc and int(undoc) > 0:
                reasons.append(f"{undoc} undocumented capabilities")
        if agent_audit:
            agent_e = agent_audit.get("agent_e", {})
            if isinstance(agent_e, dict):
                comment = agent_e.get("comment", "")
                if comment:
                    reasons.append(f"Agent E: {comment[:100]}")
        if not reasons:
            reasons.append("Unknown — no clear trigger found in data")
        info.append(f"Manual review triggers: {'; '.join(reasons)}")

    return {
        "skill_id": skill_id,
        "agent": "SM-A",
        "status": status,
        "verification_level": level,
        "issues": issues,
        "info": info,
        "verdict": "issue" if issues else "ok",
    }


# ---------------------------------------------------------------------------
# SM-B: Data Integrity Auditor
# ---------------------------------------------------------------------------

def review_data_integrity(skill: dict) -> dict:
    """SM-B: Review data integrity for a single skill.

    Checks:
    - Tags are consistent (no duplicates)
    - verification_level is set
    - findings_summary is dict (not string)
    - No conflicting fields
    - Star count is reasonable
    - Required fields present
    """
    skill_id = skill.get("id", "unknown")
    status = skill.get("verification_status", "unverified")
    level = skill.get("verification_level", "")

    issues = []
    info = []

    # Tag integrity
    tags = skill.get("tags", [])
    if isinstance(tags, list):
        unique_tags = list(dict.fromkeys(tags))
        if len(unique_tags) != len(tags):
            dup_count = len(tags) - len(unique_tags)
            issues.append(f"{dup_count} duplicate tag(s)")
    else:
        issues.append("tags field is not a list")

    # verification_level check
    if status == "pass" and not level:
        issues.append("Pass skill missing verification_level")

    # findings_summary type check
    findings_summary = skill.get("findings_summary")
    if isinstance(findings_summary, str):
        issues.append("findings_summary is string (should be dict)")

    # Conflicting fields
    if status == "pass" and "repo_unavailable" in (tags if isinstance(tags, list) else []):
        issues.append("Pass status but tagged repo_unavailable — conflicting state")

    if status == "fail" and level == "full_pipeline":
        info.append("Fail with full_pipeline — may be intentional (detected threats)")

    # Required fields
    if not skill.get("name"):
        issues.append("Missing name field")
    if not skill.get("repo_url"):
        issues.append("Missing repo_url field")
    if not skill.get("id"):
        issues.append("Missing id field")

    # Star count sanity
    stars = skill.get("stars", 0) or 0
    if stars > 500000:
        info.append(f"Unusually high star count: {stars} — verify accuracy")

    # scan_date for verified skills
    if status in ("pass", "fail", "manual_review") and not skill.get("scan_date"):
        issues.append("Verified/scanned skill missing scan_date")

    return {
        "skill_id": skill_id,
        "agent": "SM-B",
        "status": status,
        "verification_level": level,
        "issues": issues,
        "info": info,
        "verdict": "issue" if issues else "ok",
    }


# ---------------------------------------------------------------------------
# Reconciliation
# ---------------------------------------------------------------------------

def reconcile(sm_a: dict, sm_b: dict) -> dict:
    """Reconcile findings from SM-A and SM-B.

    - Both agree no issues → finalize
    - Both find issues → flag for PM with combined evidence
    - Disagree → escalate with both perspectives
    """
    skill_id = sm_a["skill_id"]
    a_ok = sm_a["verdict"] == "ok"
    b_ok = sm_b["verdict"] == "ok"
    status = sm_a["status"]

    all_issues = sm_a["issues"] + sm_b["issues"]
    all_info = sm_a["info"] + sm_b["info"]

    if a_ok and b_ok:
        decision = "clean"
        action = "No action needed"
    elif not a_ok and not b_ok:
        decision = "flag_for_pm"
        action = f"Both agents found issues ({len(all_issues)} total) — flag for PM review"
    else:
        decision = "escalate"
        agent_with_issue = "SM-A" if not a_ok else "SM-B"
        action = f"Split decision ({agent_with_issue} found issues) — escalate to PM"

    # For manual_review skills, always flag for PM
    if status == "manual_review":
        decision = "pm_review_needed"
        action = "Manual review skill — requires PM decision (pass/fail/keep)"

    return {
        "skill_id": skill_id,
        "status": status,
        "verification_level": sm_a.get("verification_level", ""),
        "decision": decision,
        "action": action,
        "sm_a_verdict": sm_a["verdict"],
        "sm_b_verdict": sm_b["verdict"],
        "sm_a_issues": sm_a["issues"],
        "sm_b_issues": sm_b["issues"],
        "all_issues": all_issues,
        "all_info": all_info,
        "sm_a_agreed": a_ok,
        "sm_b_agreed": b_ok,
    }


# ---------------------------------------------------------------------------
# Review orchestrator
# ---------------------------------------------------------------------------

def review_batch(skills: list[dict], mode: str) -> list[dict]:
    """Run dual-agent review on a batch of skills."""
    results = []

    for skill in skills:
        # Run both agents
        sm_a_result = review_verification_quality(skill)
        sm_b_result = review_data_integrity(skill)

        # Reconcile
        reconciled = reconcile(sm_a_result, sm_b_result)
        results.append(reconciled)

    # Log to skills manager
    decision_counts = Counter(r["decision"] for r in results)
    total_issues = sum(len(r["all_issues"]) for r in results)
    pm_needed = [r["skill_id"] for r in results if r["decision"] in ("flag_for_pm", "escalate", "pm_review_needed")]

    log_to_skill_manager(
        check_type="sm_review",
        findings={
            "mode": mode,
            "total_reviewed": len(results),
            "decision_counts": dict(decision_counts),
            "total_issues": total_issues,
            "pm_review_needed": pm_needed[:20],  # Cap at 20 for log readability
            "pm_review_count": len(pm_needed),
        },
        recommendations=(
            [f"PM review needed for {len(pm_needed)} skill(s)"]
            if pm_needed else None
        ),
    )

    return results


def print_report(results: list[dict], mode: str, pm_summary: dict | None = None) -> None:
    """Print a formatted report of review results."""
    print()
    print("=" * 70)
    print(f"  Skills Manager Review — {mode}")
    print("=" * 70)
    print(f"  Total reviewed: {len(results)}")
    print()

    decision_counts = Counter(r["decision"] for r in results)
    print("  Decision summary:")
    for decision, count in sorted(decision_counts.items()):
        label = {
            "clean": "Clean (no action)",
            "flag_for_pm": "Flagged for PM (both agents found issues)",
            "escalate": "Escalated (agents disagree)",
            "pm_review_needed": "PM review needed (manual_review skills)",
        }.get(decision, decision)
        print(f"    {label:<55} {count:>4}")

    # Show issues
    issues_results = [r for r in results if r["all_issues"]]
    if issues_results:
        print()
        print(f"  Skills with issues ({len(issues_results)}):")
        print(f"  {'-' * 66}")
        for r in issues_results[:20]:  # Show max 20
            print(f"    {r['skill_id'][:40]:<42} [{r['decision']}]")
            for issue in r["all_issues"]:
                print(f"      - {issue}")
            if r["all_info"]:
                for info in r["all_info"]:
                    print(f"      > {info}")

    # PM review queue
    pm_needed = [r for r in results if r["decision"] in ("flag_for_pm", "escalate", "pm_review_needed")]
    if pm_needed:
        print()
        print(f"  PM Review Queue ({len(pm_needed)} skills):")
        print(f"  {'-' * 66}")
        for r in pm_needed[:20]:
            print(f"    {r['skill_id'][:40]:<42} status={r['status']}")
            if r["all_issues"]:
                for issue in r["all_issues"][:3]:
                    print(f"      - {issue}")

    if pm_summary is not None:
        print()
        print("  PM Final Decisions:")
        print(f"  {'-' * 66}")
        print(f"    Reviewed manual_review skills: {pm_summary.get('reviewed', 0)}")
        for key, count in sorted((pm_summary.get("decision_counts") or {}).items()):
            print(f"    {key:<30} {count:>6}")

    print()
    print("=" * 70)
    print("  Review logged to data/skill-manager-log.json")
    print("=" * 70)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Skills Manager dual-agent post-verification review"
    )
    parser.add_argument(
        "--run-report",
        type=str,
        help="Path to a verification run report JSON file",
    )
    parser.add_argument(
        "--skill-ids",
        type=str,
        help="Comma-separated skill IDs to review",
    )
    parser.add_argument(
        "--manual-review-queue",
        action="store_true",
        help="Review all manual_review skills",
    )
    parser.add_argument(
        "--periodic",
        action="store_true",
        help="Full collection audit of all pass skills",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limit number of skills to review",
    )
    parser.add_argument(
        "--pm-finalize",
        action="store_true",
        help="Apply PM final decision for manual_review skills and write back to data/skills/*.json",
    )
    args = parser.parse_args()

    # Determine mode and load skills
    if args.run_report:
        mode = "run-report"
        report = load_run_report(args.run_report)
        if not report:
            print(f"ERROR: Could not load run report: {args.run_report}", file=sys.stderr)
            sys.exit(1)
        # Extract skill IDs from run report
        processed = report.get("processed", [])
        if isinstance(processed, list):
            skill_ids = [
                p.get("skill_id") or p.get("id", "")
                for p in processed
                if isinstance(p, dict)
            ]
        else:
            skill_ids = []
        # Also check results key
        if not skill_ids:
            results_list = report.get("results", [])
            if isinstance(results_list, list):
                skill_ids = [
                    r.get("skill_id") or r.get("id", "")
                    for r in results_list
                    if isinstance(r, dict)
                ]
        if not skill_ids:
            # Try to extract from other common formats
            for key in ("skills", "skill_ids", "ids", "selected_ids"):
                val = report.get(key, [])
                if isinstance(val, list) and val:
                    if isinstance(val[0], str):
                        skill_ids = val
                    elif isinstance(val[0], dict):
                        skill_ids = [v.get("skill_id") or v.get("id", "") for v in val]
                    break
        skill_ids = [s for s in skill_ids if s]
        if args.limit:
            skill_ids = skill_ids[:args.limit]
        skills = load_skills_by_ids(skill_ids)
        print(f"Loaded {len(skills)} skills from run report ({len(skill_ids)} IDs found)")

    elif args.skill_ids:
        mode = "skill-ids"
        skill_ids = [s.strip() for s in args.skill_ids.split(",") if s.strip()]
        if args.limit:
            skill_ids = skill_ids[:args.limit]
        skills = load_skills_by_ids(skill_ids)
        print(f"Loaded {len(skills)} of {len(skill_ids)} requested skills")

    elif args.manual_review_queue:
        mode = "manual-review-queue"
        skills = get_manual_review_skills(limit=args.limit)
        print(f"Loaded {len(skills)} manual_review skills")

    elif args.periodic:
        mode = "periodic"
        skills = get_all_pass_skills(limit=args.limit)
        print(f"Loaded {len(skills)} pass skills for periodic audit")

    else:
        parser.print_help()
        print("\nERROR: Specify one of --run-report, --skill-ids, --manual-review-queue, or --periodic")
        sys.exit(1)

    if not skills:
        print("No skills to review.")
        sys.exit(0)

    # Run review
    results = review_batch(skills, mode)
    pm_summary = None
    if args.pm_finalize:
        pm_summary = finalize_manual_reviews(skills, mode)
    print_report(results, mode, pm_summary=pm_summary)


if __name__ == "__main__":
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    main()
