#!/usr/bin/env python3
"""
Re-score skills from existing scanner reports (no clone needed).

Applies corrected D+E scoring logic to scanner_output.json data.
Sets verification_level to "scanner_rescored" (not "full_pipeline"
since Agents A+B did not run on actual repo content).

Usage:
    python3 scripts/verify/rescore_from_scanner.py --skill-ids id1,id2  # dry-run
    python3 scripts/verify/rescore_from_scanner.py --skill-ids id1,id2 --apply
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
SKILLS_DIR = PROJECT_ROOT / "data" / "skills"
REPORTS_DIR = PROJECT_ROOT / "data" / "scan-reports"

sys.path.insert(0, str(PROJECT_ROOT))

from src.sanitizer.schemas import ScanSeverity, VerificationStatus


def severity_counts(scanner: dict) -> dict[str, int]:
    counts = {"critical": 0, "high": 0, "medium": 0, "low": 0, "info": 0}
    for f in scanner.get("findings", []):
        sev = (f.get("severity") or "info").lower()
        if sev in counts:
            counts[sev] += 1
    return counts


def count_real_injection(scanner: dict) -> int:
    """Count injection findings excluding known false positive patterns."""
    fp_patterns = [
        "system :",          # bare system: in config/test files
        "system:",           # same without space
        "data:image/",       # shields.io badge URLs
        "logo=data:",        # shields.io badge parameter
        "shield group",      # HTML comments for badge groups
        "jailbreak",         # security tools defining attack types
        "ignore previous",   # hardening prompts containing the attack string
    ]
    count = 0
    for f in scanner.get("findings", []):
        cat = (f.get("category") or "").lower()
        if "injection" not in cat and "jailbreak" not in cat and "system_override" not in cat:
            continue
        evidence = (f.get("evidence") or "").lower()
        file_path = (f.get("file_path") or "").lower()
        # Skip findings in test/example directories
        if any(d in file_path for d in ["/test/", "/tests/", "/examples/", "/example/", ".test.", ".spec."]):
            continue
        # Skip known FP evidence patterns
        if any(p in evidence for p in fp_patterns):
            continue
        count += 1
    return count


def count_real_critical(scanner: dict) -> int:
    """Count critical findings excluding injection FPs."""
    fp_patterns = [
        "system :", "system:", "data:image/", "logo=data:",
        "shield group", "jailbreak", "ignore previous",
    ]
    count = 0
    for f in scanner.get("findings", []):
        sev = (f.get("severity") or "").lower()
        if sev != "critical":
            continue
        evidence = (f.get("evidence") or "").lower()
        file_path = (f.get("file_path") or "").lower()
        if any(d in file_path for d in ["/test/", "/tests/", "/examples/", "/example/", ".test.", ".spec."]):
            continue
        if any(p in evidence for p in fp_patterns):
            continue
        count += 1
    return count


def rescore(scanner: dict, secm_injection_override: bool = False) -> dict:
    """Apply fixed D+E scoring to scanner data with FP filtering.

    If secm_injection_override=True, ALL injection findings are treated as FP
    (SecM has manually audited and confirmed false positive).

    Returns: score, status, risk, reasoning, approved, confidence
    """
    sev = severity_counts(scanner)
    injection_raw = scanner.get("injection_patterns_count", 0)
    obf_high = scanner.get("obfuscation_high_risk_count", 0)

    if secm_injection_override:
        injection = 0
        critical_real = 0
        fp_count = injection_raw
    else:
        injection = count_real_injection(scanner)
        critical_real = count_real_critical(scanner)
        fp_count = injection_raw - injection

    # Start at 85 (conservative base without A+B doc/code analysis)
    score = 85

    # Scanner penalty (capped at 40) — use raw sev counts (non-injection findings)
    raw_penalty = (sev["high"] * 2) + sev["medium"] + (sev["low"] // 2)
    scanner_penalty = min(40, raw_penalty)
    score -= scanner_penalty

    # Risk determination — use FP-filtered injection/critical counts
    risk = "info"
    if critical_real > 0:
        risk = "critical"
    elif injection > 0 or obf_high > 0:
        risk = "high"
    elif sev["high"] > 0 or sev["medium"] > 0:
        risk = "medium"
    elif sev["low"] > 0:
        risk = "low"

    # Status from score
    score = max(0, min(100, score))
    if risk == "critical":
        status = "fail"
    elif score >= 80:
        status = "pass"
    elif score >= 50:
        status = "manual_review"
    else:
        status = "fail"

    # Safety overrides (deterministic) — use FP-filtered counts
    if critical_real > 0:
        score = min(score, 40)
        status = "fail"
    if obf_high > 0:
        score = min(score, 15)
        status = "fail"
        risk = "critical"
    if injection > 0:
        score = min(score, 10)
        status = "fail"
        risk = "critical"
    score = max(0, min(100, score))

    # Agent E supervisor
    approved = status == "pass"
    confidence = max(50, min(95, score))
    override = None
    if injection > 0:
        approved = False
        status = "fail"
        override = "Deterministic override: injection patterns detected."
        confidence = max(confidence, 95)
    if obf_high > 0:
        approved = False
        status = "fail"
        override = "Deterministic override: high-risk obfuscation detected."
        confidence = max(confidence, 90)
    if score < 50:
        approved = False
        status = "fail"
    elif score < 80:
        approved = False
        if status == "pass":
            status = "manual_review"

    if status != "pass":
        approved = False

    reasoning = (
        f"Scanner rescore (FP-filtered): findings={len(scanner.get('findings', []))}, "
        f"injection_raw={injection_raw}, injection_real={injection}, fp_excluded={fp_count}, "
        f"critical_real={critical_real}, obfuscation_high={obf_high}, "
        f"sev={sev}, penalty={scanner_penalty}, "
        f"score={score}, risk={risk}, status={status}"
    )

    return {
        "score": score,
        "status": status,
        "risk": risk,
        "approved": approved,
        "confidence": confidence,
        "override": override,
        "scanner_penalty": scanner_penalty,
        "reasoning": reasoning,
        "severity_counts": sev,
        "injection_raw": injection_raw,
        "injection_real": injection,
        "injection_fp": fp_count,
        "critical_real": critical_real,
    }


def main():
    parser = argparse.ArgumentParser(description="Re-score skills from existing scanner reports.")
    parser.add_argument("--skill-ids", type=str, required=True)
    parser.add_argument("--apply", action="store_true", default=False)
    parser.add_argument("--secm-fp-override-ids", type=str, default=None,
                        help="Comma-separated skill IDs where SecM has confirmed ALL injection findings are FP")
    args = parser.parse_args()

    secm_override_set = set()
    if args.secm_fp_override_ids:
        secm_override_set = {s.strip() for s in args.secm_fp_override_ids.split(",") if s.strip()}

    ids = [s.strip() for s in args.skill_ids.split(",") if s.strip()]
    valid = re.compile(r'^[a-zA-Z0-9_-]+$')
    ids = [s for s in ids if valid.match(s)]

    scan_date = datetime.now(timezone.utc).isoformat()
    results = []

    for sid in ids:
        scanner_file = REPORTS_DIR / sid / "scanner_output.json"
        skill_file = SKILLS_DIR / f"{sid}.json"

        if not scanner_file.exists():
            print(f"  SKIP {sid}: no scan report")
            results.append({"id": sid, "action": "skip", "reason": "no scan report"})
            continue

        if not skill_file.exists():
            print(f"  SKIP {sid}: no skill file")
            results.append({"id": sid, "action": "skip", "reason": "no skill file"})
            continue

        scanner = json.loads(scanner_file.read_text(encoding="utf-8"))
        skill = json.loads(skill_file.read_text(encoding="utf-8"))

        old_status = skill.get("verification_status", "unknown")
        old_score = skill.get("overall_score", "?")
        old_risk = skill.get("risk_level", "?")

        secm_override = sid in secm_override_set
        result = rescore(scanner, secm_injection_override=secm_override)
        if secm_override:
            print(f"  {sid}: [SecM FP override applied]")

        print(f"  {sid}:")
        print(f"    OLD: status={old_status}, score={old_score}, risk={old_risk}")
        print(f"    NEW: status={result['status']}, score={result['score']}, risk={result['risk']}")
        print(f"    {result['reasoning']}")

        change = old_status != result["status"] or str(old_score) != str(result["score"])
        action = "change" if change else "no_change"

        if args.apply and change:
            skill["verification_status"] = result["status"]
            skill["overall_score"] = result["score"]
            skill["risk_level"] = result["risk"]
            skill["verification_date"] = scan_date
            skill["verification_level"] = "scanner_rescored"
            skill["verification_summary"] = {
                "rescored_from": "scanner_output",
                "scoring_version": "2026-03-02_fixed",
                "approved": result["approved"],
                "confidence": result["confidence"],
                "override": result["override"],
                "scanner_penalty": result["scanner_penalty"],
                "severity_counts": result["severity_counts"],
            }
            # Update status tag
            tags = skill.get("tags", [])
            for old_tag in [t for t in tags if t.startswith("status-")]:
                tags.remove(old_tag)
            tags.append(f"status-{result['status']}")
            skill["tags"] = tags
            skill_file.write_text(json.dumps(skill, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            action = "applied"
            print(f"    -> APPLIED")

        results.append({
            "id": sid,
            "action": action,
            "old": {"status": old_status, "score": old_score, "risk": old_risk},
            "new": {"status": result["status"], "score": result["score"], "risk": result["risk"]},
        })

    # Summary
    print(f"\n--- Summary ---")
    print(f"Total: {len(results)}")
    for r in results:
        flag = "***" if r.get("action") == "applied" or (r.get("action") == "change") else ""
        print(f"  {r['id']}: {r['action']} {flag}")


if __name__ == "__main__":
    main()
