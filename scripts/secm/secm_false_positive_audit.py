#!/usr/bin/env python3
"""
Security Manager — False Positive Audit Tool.

Investigates scanner findings to determine true vs false positives.
Used by the Security Manager (SecM) role on PM request.

Modes:
  --skill-ids <ids>       Investigate specific skills (comma-separated)
  --pattern <name>        Audit a specific pattern across the catalog
  --run-report <path>     Check all failed/manual_review from a verification run
  --overrides-only        Focus only on safety override triggers
  --limit N               Limit number of skills to audit

After audit, results are logged to data/secm-audit-log.json.

Usage:
    python3 secm_false_positive_audit.py --skill-ids xcodebuildmcp-c8de0f2b
    python3 secm_false_positive_audit.py --pattern regex_markdown_injection
    python3 secm_false_positive_audit.py --run-report data/verification-runs/<report>.json
    python3 secm_false_positive_audit.py --skill-ids id1,id2 --overrides-only
"""

import argparse
import json
import os
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
SKILLS_DIR = PROJECT_ROOT / "data" / "skills"
SCAN_REPORTS_DIR = PROJECT_ROOT / "data" / "scan-reports"
AUDIT_LOG_PATH = PROJECT_ROOT / "data" / "secm-audit-log.json"

# Import shared logging
sys.path.insert(0, str(PROJECT_ROOT))
from src.reachability import log_to_skill_manager
from src.scanner.regex_patterns import (
    ALL_PATTERN_GROUPS,
    OBFUSCATION_HIGH_RISK_NAMES,
)

# Safety override patterns — findings from these trigger score cap / forced fail
SAFETY_OVERRIDE_PATTERNS = OBFUSCATION_HIGH_RISK_NAMES | {
    "system_override",
    "ignore_previous",
    "forget_instructions",
    "jailbreak",
    "do_anything_now",
    "hidden_instruction",
    "markdown_injection",
}


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def _safe_load_json(path: Path) -> dict:
    """Load JSON dict safely, return empty dict on errors."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError, FileNotFoundError):
        return {}


def load_skill(skill_id: str) -> dict | None:
    """Load a skill JSON by ID."""
    path = SKILLS_DIR / f"{skill_id}.json"
    if not path.exists():
        return None
    return _safe_load_json(path) or None


def load_scan_report(skill_id: str) -> dict:
    """Load the scanner (Agent C*) report for a skill."""
    return _safe_load_json(SCAN_REPORTS_DIR / skill_id / "agent_c_scanner.json")


def load_summary_report(skill_id: str) -> dict:
    """Load the summary report for a skill."""
    return _safe_load_json(SCAN_REPORTS_DIR / skill_id / "summary.json")


def load_run_report(path: str) -> dict | None:
    """Load a verification run report."""
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, FileNotFoundError):
        return None


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


# ---------------------------------------------------------------------------
# Audit log
# ---------------------------------------------------------------------------

def append_audit_log(entry: dict) -> None:
    """Append an entry to the SecM audit log."""
    log_data = {"log_version": 1, "entries": []}
    if AUDIT_LOG_PATH.exists():
        try:
            log_data = json.loads(AUDIT_LOG_PATH.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            log_data = {"log_version": 1, "entries": []}

    log_data.setdefault("entries", []).append(entry)

    AUDIT_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    AUDIT_LOG_PATH.write_text(
        json.dumps(log_data, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# Per-skill false positive analysis (SecM-FP)
# ---------------------------------------------------------------------------

def classify_finding(finding: dict) -> str:
    """Classify a single scanner finding as likely true/false positive.

    This is a heuristic classifier. For deep analysis, the SecM-FP sub-agent
    (opus model) should clone the repo and read the actual code context.

    Returns: "likely_true_positive", "likely_false_positive", or "needs_investigation"
    """
    pattern_name = str(finding.get("pattern") or finding.get("rule_id") or "")
    matched_text = str(finding.get("matched_text") or finding.get("match") or "")
    file_path = str(finding.get("file") or finding.get("path") or "")
    severity = str(finding.get("severity") or "").lower()

    # Known false positive patterns
    # shields.io badges with data: in URL parameters
    if pattern_name == "regex_markdown_injection":
        if "shields.io" in matched_text or "badge" in matched_text.lower():
            return "likely_false_positive"
        if "logo=data:" in matched_text:
            return "likely_false_positive"
        # data: at URL start is a real injection
        if re.search(r"\]\(\s*data:", matched_text):
            return "likely_true_positive"

    # Buffer.from with base64 in build/config scripts
    if pattern_name == "regex_js_buffer_from":
        if any(ext in file_path for ext in (".sh", ".bash", "Makefile", "config")):
            return "likely_false_positive"

    # ast.literal_eval is safe
    if pattern_name == "regex_py_eval":
        if "literal_eval" in matched_text:
            return "likely_false_positive"

    # JSON files excluded from obfuscation (should not appear, but handle)
    if pattern_name.startswith("regex_") and pattern_name.replace("regex_", "") in OBFUSCATION_HIGH_RISK_NAMES:
        if file_path.endswith(".json"):
            return "likely_false_positive"

    # High-risk obfuscation in actual code = likely true positive
    if pattern_name.replace("regex_", "") in OBFUSCATION_HIGH_RISK_NAMES:
        if severity in ("critical", "high"):
            return "likely_true_positive"

    # Default: needs human/LLM investigation
    return "needs_investigation"


def audit_skill(skill_id: str, overrides_only: bool = False) -> dict:
    """Audit a single skill's scanner findings for false positives.

    Returns an audit result dict.
    """
    skill = load_skill(skill_id)
    if not skill:
        return {
            "skill_id": skill_id,
            "error": "Skill not found",
            "findings_audited": 0,
        }

    scanner = load_scan_report(skill_id)
    findings = scanner.get("findings", [])
    if not isinstance(findings, list):
        findings = []

    status = skill.get("verification_status", "unverified")
    score = _safe_int(skill.get("overall_score"))
    risk = str(skill.get("risk_level") or "").lower()
    stars = _safe_int(skill.get("stars"))
    name = str(skill.get("name") or skill_id)

    # Filter to override-triggering findings if requested
    if overrides_only:
        findings = [
            f for f in findings
            if isinstance(f, dict)
            and str(f.get("pattern") or f.get("rule_id") or "").replace("regex_", "") in SAFETY_OVERRIDE_PATTERNS
        ]

    # Classify each finding
    classifications = Counter()
    audited_findings = []
    for finding in findings:
        if not isinstance(finding, dict):
            continue
        classification = classify_finding(finding)
        classifications[classification] += 1
        audited_findings.append({
            "pattern": str(finding.get("pattern") or finding.get("rule_id") or "unknown"),
            "severity": str(finding.get("severity") or "unknown"),
            "file": str(finding.get("file") or finding.get("path") or "unknown"),
            "classification": classification,
            "matched_text_preview": str(finding.get("matched_text") or finding.get("match") or "")[:120],
        })

    # Compute false positive metrics
    total = len(audited_findings)
    fp_count = classifications.get("likely_false_positive", 0)
    tp_count = classifications.get("likely_true_positive", 0)
    needs_count = classifications.get("needs_investigation", 0)
    fp_rate = (fp_count / total * 100) if total > 0 else 0.0

    # Determine recommendation
    if total == 0:
        recommendation = "no_findings"
    elif fp_count == total:
        recommendation = "all_false_positives — recommend pass"
    elif tp_count > 0 and fp_count == 0:
        recommendation = "all_true_positives — recommend fail"
    elif fp_count > 0 and tp_count == 0:
        recommendation = "only false positives detected — recommend pass (pending investigation of remaining)"
    else:
        recommendation = f"mixed — {tp_count} true, {fp_count} false, {needs_count} needs investigation"

    result = {
        "skill_id": skill_id,
        "name": name,
        "status": status,
        "score": score,
        "risk_level": risk,
        "stars": stars,
        "findings_total": total,
        "likely_true_positive": tp_count,
        "likely_false_positive": fp_count,
        "needs_investigation": needs_count,
        "false_positive_rate": round(fp_rate, 1),
        "recommendation": recommendation,
        "audited_findings": audited_findings[:50],  # Cap for log readability
        "overrides_only": overrides_only,
    }

    return result


# ---------------------------------------------------------------------------
# Pattern-level audit (SecM-PA)
# ---------------------------------------------------------------------------

def audit_pattern(pattern_name: str, limit: int = 100) -> dict:
    """Audit a specific pattern across the catalog.

    Finds all skills where the pattern triggered, classifies matches,
    and calculates the false positive rate.
    """
    affected_skills = []
    total_matches = 0
    classifications = Counter()

    for skill_path in sorted(SKILLS_DIR.glob("*.json")):
        skill_id = skill_path.stem
        scanner = load_scan_report(skill_id)
        findings = scanner.get("findings", [])
        if not isinstance(findings, list):
            continue

        matching_findings = [
            f for f in findings
            if isinstance(f, dict)
            and (
                str(f.get("pattern") or "") == pattern_name
                or str(f.get("rule_id") or "") == pattern_name
                or f"regex_{str(f.get('pattern') or '')}" == pattern_name
                or str(f.get("pattern") or "") == pattern_name.replace("regex_", "")
            )
        ]

        if not matching_findings:
            continue

        skill = _safe_load_json(skill_path)
        skill_id_str = str(skill.get("id") or skill_id)
        stars = _safe_int(skill.get("stars"))

        for finding in matching_findings:
            classification = classify_finding(finding)
            classifications[classification] += 1
            total_matches += 1

        affected_skills.append({
            "skill_id": skill_id_str,
            "name": str(skill.get("name") or skill_id_str),
            "stars": stars,
            "status": str(skill.get("verification_status") or "unverified"),
            "match_count": len(matching_findings),
        })

        if len(affected_skills) >= limit:
            break

    # Sort by stars descending
    affected_skills.sort(key=lambda s: -s["stars"])

    fp_count = classifications.get("likely_false_positive", 0)
    tp_count = classifications.get("likely_true_positive", 0)
    needs_count = classifications.get("needs_investigation", 0)
    fp_rate = (fp_count / total_matches * 100) if total_matches > 0 else 0.0

    # Severity assessment
    if fp_rate > 30:
        severity = "emergency — recommend disable until fixed"
    elif fp_rate > 15:
        severity = "critical — pattern needs immediate fix"
    elif fp_rate > 5:
        severity = "warning — propose pattern refinement"
    else:
        severity = "acceptable"

    return {
        "pattern_name": pattern_name,
        "total_matches": total_matches,
        "affected_skills_count": len(affected_skills),
        "likely_true_positive": tp_count,
        "likely_false_positive": fp_count,
        "needs_investigation": needs_count,
        "false_positive_rate": round(fp_rate, 1),
        "severity": severity,
        "affected_skills": affected_skills[:30],  # Cap for readability
    }


# ---------------------------------------------------------------------------
# Run report audit
# ---------------------------------------------------------------------------

def audit_run_report(report_path: str, overrides_only: bool = False, limit: int | None = None) -> list[dict]:
    """Audit all failed/manual_review skills from a verification run report."""
    report = load_run_report(report_path)
    if not report:
        print(f"ERROR: Could not load run report: {report_path}", file=sys.stderr)
        return []

    # Extract skill IDs from report
    skill_ids = []
    for key in ("processed", "results", "skills", "skill_ids", "ids"):
        val = report.get(key, [])
        if isinstance(val, list) and val:
            if isinstance(val[0], str):
                skill_ids = val
            elif isinstance(val[0], dict):
                skill_ids = [
                    v.get("skill_id") or v.get("id", "")
                    for v in val
                    if isinstance(v, dict)
                ]
            if skill_ids:
                break

    skill_ids = [s for s in skill_ids if s]

    # Filter to failed/manual_review only
    target_ids = []
    for sid in skill_ids:
        skill = load_skill(sid)
        if skill and skill.get("verification_status") in ("fail", "manual_review"):
            target_ids.append(sid)

    if limit:
        target_ids = target_ids[:limit]

    results = []
    for sid in target_ids:
        result = audit_skill(sid, overrides_only=overrides_only)
        results.append(result)

    return results


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def print_skill_audit_report(results: list[dict], mode: str) -> None:
    """Print a formatted report of per-skill audit results."""
    print()
    print("=" * 70)
    print(f"  SecM False Positive Audit — {mode}")
    print("=" * 70)
    print(f"  Skills audited: {len(results)}")
    print()

    for result in results:
        if result.get("error"):
            print(f"  [{result['skill_id']}] ERROR: {result['error']}")
            continue

        stars_str = f"stars={result['stars']:,}" if result.get("stars") else ""
        print(f"  [{result['skill_id']}] {result['name']}")
        print(f"    Status: {result['status']}  Score: {result['score']}  Risk: {result['risk_level']}  {stars_str}")
        print(f"    Findings: {result['findings_total']}  "
              f"TP: {result['likely_true_positive']}  "
              f"FP: {result['likely_false_positive']}  "
              f"Needs: {result['needs_investigation']}  "
              f"FP Rate: {result['false_positive_rate']}%")
        print(f"    Recommendation: {result['recommendation']}")

        # Show false positive details
        fps = [f for f in result.get("audited_findings", []) if f["classification"] == "likely_false_positive"]
        if fps:
            print(f"    False positives ({len(fps)}):")
            for fp in fps[:5]:
                print(f"      - {fp['pattern']} [{fp['severity']}] in {fp['file']}")
                if fp.get("matched_text_preview"):
                    print(f"        Match: {fp['matched_text_preview'][:80]}")
        print()

    # Summary
    total_findings = sum(r.get("findings_total", 0) for r in results if not r.get("error"))
    total_fp = sum(r.get("likely_false_positive", 0) for r in results if not r.get("error"))
    total_tp = sum(r.get("likely_true_positive", 0) for r in results if not r.get("error"))
    total_needs = sum(r.get("needs_investigation", 0) for r in results if not r.get("error"))

    print(f"  Summary: {total_findings} findings audited")
    print(f"    True positives:       {total_tp}")
    print(f"    False positives:      {total_fp}")
    print(f"    Needs investigation:  {total_needs}")
    if total_findings > 0:
        print(f"    Overall FP rate:      {total_fp / total_findings * 100:.1f}%")
    print()
    print("=" * 70)


def print_pattern_audit_report(result: dict) -> None:
    """Print a formatted report of a pattern audit."""
    print()
    print("=" * 70)
    print(f"  SecM Pattern Audit — {result['pattern_name']}")
    print("=" * 70)
    print(f"  Total matches:       {result['total_matches']}")
    print(f"  Affected skills:     {result['affected_skills_count']}")
    print(f"  True positives:      {result['likely_true_positive']}")
    print(f"  False positives:     {result['likely_false_positive']}")
    print(f"  Needs investigation: {result['needs_investigation']}")
    print(f"  False positive rate: {result['false_positive_rate']}%")
    print(f"  Severity:            {result['severity']}")
    print()

    if result["affected_skills"]:
        print("  Top affected skills (by stars):")
        print(f"  {'ID':<40} {'Stars':>8} {'Status':<16} {'Matches':>8}")
        print(f"  {'-' * 74}")
        for skill in result["affected_skills"][:15]:
            print(f"  {skill['skill_id'][:40]:<40} {skill['stars']:>8,} {skill['status']:<16} {skill['match_count']:>8}")
    print()
    print("=" * 70)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="SecM False Positive Audit — investigate scanner findings for accuracy"
    )
    parser.add_argument(
        "--skill-ids",
        type=str,
        help="Comma-separated skill IDs to investigate",
    )
    parser.add_argument(
        "--pattern",
        type=str,
        help="Audit a specific pattern across the catalog",
    )
    parser.add_argument(
        "--run-report",
        type=str,
        help="Path to a verification run report JSON file",
    )
    parser.add_argument(
        "--overrides-only",
        action="store_true",
        help="Focus only on safety override triggers",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limit number of skills to audit",
    )
    args = parser.parse_args()

    if not any([args.skill_ids, args.pattern, args.run_report]):
        parser.print_help()
        print("\nERROR: Specify one of --skill-ids, --pattern, or --run-report")
        sys.exit(1)

    now = datetime.now(timezone.utc).isoformat()

    # Mode: per-skill audit
    if args.skill_ids:
        mode = "skill-ids"
        skill_ids = [s.strip() for s in args.skill_ids.split(",") if s.strip()]
        if args.limit:
            skill_ids = skill_ids[: args.limit]

        results = [audit_skill(sid, overrides_only=args.overrides_only) for sid in skill_ids]
        print_skill_audit_report(results, mode)

        # Log
        total_fp = sum(r.get("likely_false_positive", 0) for r in results if not r.get("error"))
        audit_entry = {
            "timestamp": now,
            "audit_type": "secm_fp_audit",
            "mode": mode,
            "skill_ids": skill_ids,
            "overrides_only": args.overrides_only,
            "total_audited": len(results),
            "total_false_positives": total_fp,
            "results_summary": [
                {
                    "skill_id": r["skill_id"],
                    "findings_total": r.get("findings_total", 0),
                    "fp": r.get("likely_false_positive", 0),
                    "tp": r.get("likely_true_positive", 0),
                    "recommendation": r.get("recommendation", ""),
                }
                for r in results
                if not r.get("error")
            ],
        }
        append_audit_log(audit_entry)

        log_to_skill_manager(
            check_type="secm_fp_audit",
            findings={
                "mode": mode,
                "skill_ids": skill_ids,
                "total_audited": len(results),
                "total_false_positives": total_fp,
                "overrides_only": args.overrides_only,
            },
        )

    # Mode: pattern audit
    elif args.pattern:
        mode = "pattern"
        limit = args.limit or 100
        result = audit_pattern(args.pattern, limit=limit)
        print_pattern_audit_report(result)

        # Log
        audit_entry = {
            "timestamp": now,
            "audit_type": "secm_pattern_audit",
            "pattern_name": args.pattern,
            "total_matches": result["total_matches"],
            "affected_skills": result["affected_skills_count"],
            "false_positive_rate": result["false_positive_rate"],
            "severity": result["severity"],
        }
        append_audit_log(audit_entry)

        log_to_skill_manager(
            check_type="secm_pattern_audit",
            findings={
                "pattern_name": args.pattern,
                "total_matches": result["total_matches"],
                "affected_skills": result["affected_skills_count"],
                "false_positive_rate": result["false_positive_rate"],
                "severity": result["severity"],
            },
        )

    # Mode: run report audit
    elif args.run_report:
        mode = "run-report"
        results = audit_run_report(
            args.run_report,
            overrides_only=args.overrides_only,
            limit=args.limit,
        )
        if results:
            print_skill_audit_report(results, mode)

            total_fp = sum(r.get("likely_false_positive", 0) for r in results if not r.get("error"))
            audit_entry = {
                "timestamp": now,
                "audit_type": "secm_fp_audit",
                "mode": mode,
                "run_report_path": args.run_report,
                "total_audited": len(results),
                "total_false_positives": total_fp,
                "overrides_only": args.overrides_only,
            }
            append_audit_log(audit_entry)

            log_to_skill_manager(
                check_type="secm_fp_audit",
                findings={
                    "mode": mode,
                    "run_report": args.run_report,
                    "total_audited": len(results),
                    "total_false_positives": total_fp,
                },
            )
        else:
            print("No failed/manual_review skills found in run report.")

    print("  Audit logged to data/secm-audit-log.json")
    print("  Skills manager log updated.")


if __name__ == "__main__":
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    main()
