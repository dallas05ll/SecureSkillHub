#!/usr/bin/env python3
"""
Batch re-assess failed/manual_review skills using fixed scoring logic.

Reads existing scan reports (no re-scanning needed) and applies the corrected
scoring to determine what the status SHOULD be. Updates skill JSON files.

Usage:
    python3 scripts/secm/batch_reassess.py                    # dry-run, show what would change
    python3 scripts/secm/batch_reassess.py --apply             # apply changes to skill JSON
    python3 scripts/secm/batch_reassess.py --only-clear-fps    # only fix 0-injection 0-obfuscation skills
    python3 scripts/secm/batch_reassess.py --skill-ids id1,id2 # specific skills
"""

from __future__ import annotations

import argparse
import json
import glob
import os
import sys
from datetime import datetime, timezone
from pathlib import Path


def severity_counts(scanner: dict) -> dict[str, int]:
    """Count findings by severity level from scanner report."""
    counts = {"critical": 0, "high": 0, "medium": 0, "low": 0, "info": 0}
    for f in scanner.get("findings", []):
        sev = (f.get("severity") or "info").lower()
        if sev in counts:
            counts[sev] += 1
    return counts


def reassess_skill(scanner: dict) -> dict:
    """Apply fixed scoring logic to a scanner report.

    Returns dict with: score, status, risk, scanner_penalty, reasoning
    """
    sev = severity_counts(scanner)
    injection_count = scanner.get("injection_patterns_count", 0)
    obfuscation_high = scanner.get("obfuscation_high_risk_count", 0)

    # Start at 100 (we don't have agent A/B data to re-run mismatches,
    # so we use the skill's existing base score before scanner penalty)
    # For now, we compute the scanner-driven assessment independently.

    # Fixed scoring: cap scanner penalty at 40
    raw_penalty = (sev["high"] * 2) + sev["medium"] + (sev["low"] // 2)
    scanner_penalty = min(40, raw_penalty)

    # We need the original base score (before scanner penalty was applied).
    # Since we don't store that, we'll compute based on the scanner data.
    # The base score comes from mismatch analysis. For skills that scored 85-100
    # before the old penalty, we can estimate: old_score + old_penalty ≈ base.
    # But we don't need this - we'll just read the scorer report for the base.

    # Risk determination (fixed)
    has_real_threats = injection_count > 0 or obfuscation_high > 0
    risk = "info"
    if sev["critical"] > 0:
        risk = "critical"
    elif has_real_threats:
        risk = "high"
    elif sev["high"] >= 10:
        risk = "high"
    elif sev["high"] > 0 or sev["medium"] > 0:
        risk = "medium"
    elif sev["low"] > 0:
        risk = "low"

    return {
        "risk": risk,
        "scanner_penalty": scanner_penalty,
        "raw_penalty": raw_penalty,
        "has_real_threats": has_real_threats,
        "sev": sev,
        "injection_count": injection_count,
        "obfuscation_high": obfuscation_high,
    }


def compute_new_status(scorer_report: dict, scanner_assess: dict,
                       secm_override: bool = False) -> tuple[int, str, str]:
    """Compute new score and status from scorer base + fixed scanner assessment.

    The scorer reports were generated BEFORE scanner_penalty was added to the
    pipeline. So scorer_report["overall_score"] IS the base score (doc/code
    analysis quality, already includes mismatch/undocumented/missed penalties).

    We do NOT apply scanner_penalty retroactively — it wasn't part of the
    original scoring. Instead, we only fix the risk determination (the real bug)
    so that documented dangerous_calls don't block PASS.

    If secm_override=True, injection/obfuscation safety overrides are skipped
    because SecM has audited all findings as false positives (test/doc/vendor code).

    Returns: (new_score, new_status, new_risk)
    """
    if secm_override:
        # For SecM-overridden skills, the scorer's overall_score was capped at
        # 10-15 by safety overrides (injection/obfuscation). We need to
        # reconstruct the true base score from doc/code analysis components.
        mismatches = len(scorer_report.get("mismatches", []))
        undocumented = len(scorer_report.get("undocumented_capabilities", []))
        missed = len(scorer_report.get("agent_b_missed_findings", []))
        new_score = max(0, 100 - 10 * mismatches - 5 * undocumented - 15 * missed)
    else:
        # Use the scorer's existing score as-is — it already reflects doc/code quality
        new_score = scorer_report.get("overall_score", 0)

    risk = scanner_assess["risk"]

    # When SecM has verified all injection/obfuscation as FPs, downgrade risk.
    # Injection patterns are flagged as "critical" severity by the scanner.
    # If SecM says all injection findings are FPs, those critical counts
    # should not block the status determination.
    if secm_override:
        # Critical findings from injection patterns are false positives
        real_critical = scanner_assess["sev"]["critical"] - scanner_assess["injection_count"]
        if real_critical <= 0:
            # All critical findings were injection FPs
            if scanner_assess["sev"]["high"] > 0:
                risk = "medium"
            elif scanner_assess["sev"]["medium"] > 0:
                risk = "medium"
            else:
                risk = "low"

    # Status determination (fixed logic)
    if risk == "critical":
        new_status = "fail"
    elif new_score >= 80 and risk != "critical":
        new_status = "pass"
    elif new_score >= 50 and risk != "critical":
        new_status = "manual_review"
    else:
        new_status = "fail"

    # Safety overrides — skip if SecM audited all as false positives
    if not secm_override:
        if scanner_assess["sev"]["critical"] > 0:
            new_score = min(new_score, 40)
            new_status = "fail"
            if risk not in ("high", "critical"):
                risk = "high"
        if scanner_assess["obfuscation_high"] > 0:
            new_score = min(new_score, 15)
            new_status = "fail"
            risk = "critical"
        if scanner_assess["injection_count"] > 0:
            new_score = min(new_score, 10)
            new_status = "fail"
            risk = "critical"
    new_score = max(0, min(100, new_score))

    return new_score, new_status, risk


def main():
    parser = argparse.ArgumentParser(description="Batch re-assess failed/manual_review skills")
    parser.add_argument("--apply", action="store_true", help="Apply changes to skill JSON files")
    parser.add_argument("--only-clear-fps", action="store_true",
                        help="Only fix skills with 0 injection and 0 obfuscation")
    parser.add_argument("--skill-ids", type=str, default="",
                        help="Comma-separated skill IDs to reassess")
    parser.add_argument("--secm-override", action="store_true",
                        help="Skip injection/obfuscation safety overrides (SecM audited all as FPs)")
    args = parser.parse_args()

    specific_ids = [s.strip() for s in args.skill_ids.split(",") if s.strip()] if args.skill_ids else []

    skills_dir = Path("data/skills")
    reports_dir = Path("data/scan-reports")

    results = {"upgraded": [], "unchanged": [], "errors": []}

    for skill_file in sorted(skills_dir.glob("*.json")):
        skill = json.loads(skill_file.read_text())
        sid = skill.get("id", "")
        vs = (skill.get("verification_status") or "").lower()
        vl = (skill.get("verification_level") or "").lower()

        # Filter to full_pipeline fail/manual_review
        if vl != "full_pipeline" or vs not in ("fail", "manual_review"):
            continue

        if specific_ids and sid not in specific_ids:
            continue

        # Check for scan report
        scanner_file = reports_dir / sid / "agent_c_scanner.json"
        scorer_file = reports_dir / sid / "agent_d_scorer.json"
        if not scanner_file.exists() or not scorer_file.exists():
            results["errors"].append(f"{sid}: missing scan report")
            continue

        scanner = json.loads(scanner_file.read_text())
        scorer = json.loads(scorer_file.read_text())

        # Skip injection/obfuscation skills unless SecM override or not clear-fps-only
        inj = scanner.get("injection_patterns_count", 0)
        obf = scanner.get("obfuscation_high_risk_count", 0)
        if args.only_clear_fps and not args.secm_override and (inj > 0 or obf > 0):
            continue

        # Re-assess
        assess = reassess_skill(scanner)
        use_secm = args.secm_override and (inj > 0 or obf > 0)
        new_score, new_status, new_risk = compute_new_status(scorer, assess, secm_override=use_secm)

        old_score = skill.get("overall_score", 0)
        old_risk = skill.get("risk_level", "")
        stars = skill.get("stars", 0)

        if new_status != vs or new_score != old_score:
            results["upgraded"].append({
                "id": sid,
                "name": skill.get("name", ""),
                "stars": stars,
                "old_status": vs,
                "new_status": new_status,
                "old_score": old_score,
                "new_score": new_score,
                "old_risk": old_risk,
                "new_risk": new_risk,
                "injection": inj,
                "obfuscation_high": obf,
            })

            if args.apply:
                skill["verification_status"] = new_status
                skill["overall_score"] = new_score
                skill["risk_level"] = new_risk
                # Add reassessment note
                fs = skill.get("findings_summary", {})
                if isinstance(fs, str):
                    fs = {"notes": fs}
                fs["reassessed"] = True
                fs["reassessed_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                if use_secm:
                    fs["reassessment_reason"] = (
                        "SecM audit: all injection/obfuscation findings are false positives "
                        "(test files, documentation, vendored JS, security tools). "
                        "Safety overrides bypassed per PM approval."
                    )
                    fs["secm_override"] = True
                else:
                    fs["reassessment_reason"] = (
                        "Scoring logic fixed: scanner_penalty capped at 40, "
                        "risk=HIGH from documented dangerous_calls no longer blocks PASS"
                    )
                fs["previous_status"] = vs
                fs["previous_score"] = old_score
                skill["findings_summary"] = fs
                skill_file.write_text(json.dumps(skill, indent=2, ensure_ascii=False) + "\n")
        else:
            results["unchanged"].append(sid)

    # Print summary
    print(f"\n{'='*70}")
    print(f"BATCH RE-ASSESSMENT RESULTS {'(DRY RUN)' if not args.apply else '(APPLIED)'}")
    print(f"{'='*70}")
    print(f"  Upgraded:  {len(results['upgraded'])}")
    print(f"  Unchanged: {len(results['unchanged'])}")
    print(f"  Errors:    {len(results['errors'])}")

    if results["upgraded"]:
        print(f"\n{'='*70}")
        print("UPGRADED SKILLS:")
        print(f"{'='*70}")

        pass_count = sum(1 for s in results["upgraded"] if s["new_status"] == "pass")
        mr_count = sum(1 for s in results["upgraded"] if s["new_status"] == "manual_review")
        fail_count = sum(1 for s in results["upgraded"] if s["new_status"] == "fail")
        print(f"  → pass: {pass_count}  |  → manual_review: {mr_count}  |  → fail (unchanged): {fail_count}")

        for s in sorted(results["upgraded"], key=lambda x: -x["stars"]):
            arrow = "→"
            print(
                f"  {s['stars']:>6} ★  {s['name']:<40} "
                f"{s['old_status']:<14} {arrow} {s['new_status']:<14} "
                f"score {s['old_score']:>3} {arrow} {s['new_score']:>3}  "
                f"risk {s['old_risk']:<8} {arrow} {s['new_risk']:<8}"
            )

    if results["errors"]:
        print(f"\nErrors: {results['errors']}")

    if not args.apply and results["upgraded"]:
        print(f"\n>>> Run with --apply to write changes to disk")


if __name__ == "__main__":
    main()
