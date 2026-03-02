#!/usr/bin/env python3
"""
One-time backfill: set verification_level on all pass skills missing it.

Categories (checked in order):
  full_pipeline   - agent_audit has all 5 agents (A, B, C*, D, E) with signed=True
  metadata_only   - findings_summary.notes contains "Metadata-based" OR verification_level already "metadata_only"
  scanner_only    - has verified_commit or scan_summary or scan_date (evidence of code scanning)
  scanner_only    - fallback for anything else that's pass (scan_date only, etc.)

Run once:
    python3 backfill_verification_level.py
    python3 backfill_verification_level.py --dry-run   # Preview without writing
"""

import argparse
import json
import glob
import os
from collections import Counter
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
SKILLS_DIR = str(PROJECT_ROOT / "data" / "skills")


def all_5_agents_signed(agent_audit: dict) -> bool:
    if not agent_audit:
        return False
    required = ["agent_a", "agent_b", "agent_c_star", "agent_d", "agent_e"]
    for agent in required:
        entry = agent_audit.get(agent)
        if not entry:
            return False
        if not entry.get("signed", False):
            return False
    return True


def categorize_skill(skill: dict) -> str:
    agent_audit = skill.get("agent_audit")
    verified_commit = (skill.get("verified_commit") or "").strip()
    scan_date = (skill.get("scan_date") or "").strip()
    scan_summary = skill.get("scan_summary")
    findings_summary = skill.get("findings_summary")

    # Full pipeline: all 5 agents signed
    if agent_audit and all_5_agents_signed(agent_audit):
        return "full_pipeline"

    # Metadata-only: findings_summary notes say "Metadata-based"
    if isinstance(findings_summary, dict):
        notes = str(findings_summary.get("notes", ""))
        if "Metadata-based" in notes or "metadata" in notes.lower():
            return "metadata_only"

    # Already claimed metadata_only
    if skill.get("verification_level") == "metadata_only":
        return "metadata_only"

    # Scanner-only: has evidence of actual scanning
    has_scan_evidence = (
        bool(verified_commit) or
        bool(scan_date) or
        scan_summary is not None
    )
    if has_scan_evidence:
        return "scanner_only"

    # Metadata-only: findings_summary exists but no scan evidence
    if findings_summary is not None:
        return "metadata_only"

    # Fallback: assume scanner_only (has pass status, likely from older pipeline)
    return "scanner_only"


def main():
    parser = argparse.ArgumentParser(description="Backfill verification_level on pass skills")
    parser.add_argument("--dry-run", action="store_true", help="Preview changes without writing")
    args = parser.parse_args()

    files = sorted(glob.glob(os.path.join(SKILLS_DIR, "*.json")))
    print(f"Total skill files: {len(files)}")

    updated = Counter()
    already_set = 0
    skipped_not_pass = 0
    errors = 0

    for fpath in files:
        try:
            with open(fpath) as fh:
                skill = json.load(fh)
        except (json.JSONDecodeError, OSError):
            errors += 1
            continue

        if skill.get("verification_status") != "pass":
            skipped_not_pass += 1
            continue

        # Already has verification_level set
        if skill.get("verification_level"):
            already_set += 1
            continue

        # Categorize and set
        level = categorize_skill(skill)
        skill["verification_level"] = level
        updated[level] += 1

        if not args.dry_run:
            with open(fpath, "w") as fh:
                json.dump(skill, fh, indent=2, ensure_ascii=False)
                fh.write("\n")

    print()
    print("=" * 60)
    print(f"  Backfill {'(DRY RUN)' if args.dry_run else 'COMPLETE'}")
    print("=" * 60)
    print(f"  Skipped (not pass):     {skipped_not_pass}")
    print(f"  Already had level:      {already_set}")
    print(f"  Errors:                 {errors}")
    print()
    print("  Updated breakdown:")
    for level, count in sorted(updated.items()):
        print(f"    {level:<25} {count:>6}")
    print(f"    {'TOTAL':<25} {sum(updated.values()):>6}")
    print()
    if args.dry_run:
        print("  Re-run without --dry-run to apply changes.")


if __name__ == "__main__":
    os.chdir(str(PROJECT_ROOT))
    main()
