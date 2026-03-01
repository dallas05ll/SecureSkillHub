#!/usr/bin/env python3
"""
Audit script: Categorize all 'pass' skills by their actual verification path.

Categories:
  full_pipeline   - Has agent_audit with all 5 agents (A, B, C*, D, E) signed
  scanner_only    - Has scan data (scan_summary or verified_commit) but no full agent_audit
  metadata_only   - Has verification_status=pass but no scan data, no full agent_audit
  unknown_other   - Anything else that doesn't fit the above

Verification level field: also read the verification_level field if present to compare
against what the data actually shows.
"""

import json
import glob
import os
from collections import defaultdict

SKILLS_DIR = "data/skills"

def all_5_agents_signed(agent_audit: dict) -> bool:
    """Return True only if all 5 agents are present and signed=True."""
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
    """Determine the true verification path for a skill."""
    agent_audit = skill.get("agent_audit")
    verified_commit = (skill.get("verified_commit") or "").strip()
    scan_date = (skill.get("scan_date") or "").strip()
    scan_summary = skill.get("scan_summary")
    findings_summary = skill.get("findings_summary")
    verification_level = skill.get("verification_level", "")

    # Full pipeline: all 5 agents signed in agent_audit
    if agent_audit and all_5_agents_signed(agent_audit):
        return "full_pipeline"

    # Check if verification_level explicitly claims full_pipeline
    # (but agent_audit doesn't support it — that's an inconsistency)
    if verification_level == "full_pipeline":
        # Either we already returned full_pipeline above, or the data is inconsistent
        return "full_pipeline_claimed_but_incomplete"

    # Scanner-only: has real scan data (verified_commit means code was cloned)
    # scan_summary or scan_date also indicate actual scanning occurred
    has_scan_evidence = (
        bool(verified_commit) or
        bool(scan_date) or
        scan_summary is not None
    )
    if has_scan_evidence:
        # Check if it only has C* data (scanner only)
        if agent_audit:
            # Partial agent_audit — incomplete pipeline
            agents_signed = sum(
                1 for k in ["agent_a", "agent_b", "agent_c_star", "agent_d", "agent_e"]
                if agent_audit.get(k, {}).get("signed", False)
            )
            if agents_signed > 0:
                return f"partial_pipeline_{agents_signed}of5"
        return "scanner_only"

    # Metadata-only: no real scan evidence
    if findings_summary is not None:
        # findings_summary exists but no scan data
        return "metadata_only"

    # verification_level field says metadata_only
    if verification_level == "metadata_only":
        return "metadata_only"

    return "unknown_other"


def main():
    files = sorted(glob.glob(os.path.join(SKILLS_DIR, "*.json")))
    print(f"Total skill files: {len(files)}")

    # Counters and sample collectors
    total_pass = 0
    categories = defaultdict(list)

    # Aggregate field presence counters (pass skills only)
    has_verified_commit = 0
    has_agent_audit = 0
    has_scan_date = 0
    has_findings_summary = 0
    has_scan_summary = 0
    has_verification_level = 0

    # verification_level field value distribution
    vl_distribution = defaultdict(int)

    # agents_completed distribution (for skills with agent_audit)
    agents_completed_dist = defaultdict(int)

    for fpath in files:
        with open(fpath) as fh:
            try:
                skill = json.load(fh)
            except json.JSONDecodeError:
                continue

        if skill.get("verification_status") != "pass":
            continue

        total_pass += 1
        skill_id = skill.get("id", os.path.basename(fpath))

        # Field presence tracking
        vc = skill.get("verified_commit") or ""
        if vc.strip():
            has_verified_commit += 1
        if skill.get("agent_audit"):
            has_agent_audit += 1
            ac = skill["agent_audit"].get("agents_completed", "?")
            agents_completed_dist[ac] += 1
        if skill.get("scan_date", "").strip():
            has_scan_date += 1
        if skill.get("findings_summary") is not None:
            has_findings_summary += 1
        if skill.get("scan_summary") is not None:
            has_scan_summary += 1
        if skill.get("verification_level"):
            has_verification_level += 1
            vl_distribution[skill["verification_level"]] += 1

        # Categorize
        category = categorize_skill(skill)
        categories[category].append(skill_id)

    # --------------------------------------------------------------------------
    # Report
    # --------------------------------------------------------------------------
    print()
    print("=" * 70)
    print("VERIFICATION PATH AUDIT — PASS SKILLS ONLY")
    print("=" * 70)
    print(f"Total 'pass' skills: {total_pass}")
    print()

    print("BREAKDOWN BY VERIFICATION PATH:")
    print("-" * 50)
    for cat in sorted(categories.keys()):
        count = len(categories[cat])
        pct = count / total_pass * 100
        print(f"  {cat:<45} {count:>6}  ({pct:.1f}%)")

    print()
    print("FIELD PRESENCE (all pass skills):")
    print("-" * 50)
    print(f"  has verified_commit                        {has_verified_commit:>6}  ({has_verified_commit/total_pass*100:.1f}%)")
    print(f"  has agent_audit                            {has_agent_audit:>6}  ({has_agent_audit/total_pass*100:.1f}%)")
    print(f"  has scan_date                              {has_scan_date:>6}  ({has_scan_date/total_pass*100:.1f}%)")
    print(f"  has scan_summary                           {has_scan_summary:>6}  ({has_scan_summary/total_pass*100:.1f}%)")
    print(f"  has findings_summary                       {has_findings_summary:>6}  ({has_findings_summary/total_pass*100:.1f}%)")
    print(f"  has verification_level field               {has_verification_level:>6}  ({has_verification_level/total_pass*100:.1f}%)")

    print()
    print("verification_level FIELD VALUE DISTRIBUTION (pass skills with the field):")
    print("-" * 50)
    for vl, cnt in sorted(vl_distribution.items()):
        print(f"  {vl:<45} {cnt:>6}")

    if agents_completed_dist:
        print()
        print("agents_completed DISTRIBUTION (skills with agent_audit):")
        print("-" * 50)
        for ac, cnt in sorted(agents_completed_dist.items()):
            print(f"  agents_completed={ac:<5}                        {cnt:>6}")

    print()
    print("SAMPLE SKILL IDs — 3 FROM EACH CATEGORY:")
    print("-" * 50)
    for cat in sorted(categories.keys()):
        samples = categories[cat][:3]
        print(f"\n  [{cat}]")
        for s in samples:
            print(f"    - {s}")

    print()
    print("=" * 70)
    print("SUMMARY / KEY FINDINGS")
    print("=" * 70)
    full_pipeline_count = len(categories.get("full_pipeline", []))
    scanner_only_count = len(categories.get("scanner_only", []))
    metadata_only_count = len(categories.get("metadata_only", []))
    other_count = sum(
        len(v) for k, v in categories.items()
        if k not in ("full_pipeline", "scanner_only", "metadata_only")
    )

    print(f"  Truly verified (5-agent full pipeline): {full_pipeline_count}")
    print(f"  Scanner-only (code cloned + scanned):   {scanner_only_count}")
    print(f"  Metadata-only (no clone, no scan):      {metadata_only_count}")
    print(f"  Other/partial/inconsistent:             {other_count}")
    print()
    print(f"  => Only {full_pipeline_count} of {total_pass} 'pass' skills ({full_pipeline_count/total_pass*100:.1f}%)")
    print(f"     have passed the genuine 5-agent security pipeline.")
    print()

    # Deep-dive: for scanner_only, check if they have findings_summary vs just scan_summary
    so_skills = categories.get("scanner_only", [])
    if so_skills:
        # Load a few to show
        so_detail = {"has_scan_summary": 0, "has_findings_summary": 0, "both": 0, "neither": 0}
        for fpath in files:
            with open(fpath) as fh:
                try:
                    skill = json.load(fh)
                except Exception:
                    continue
            if skill.get("verification_status") != "pass":
                continue
            if categorize_skill(skill) != "scanner_only":
                continue
            has_ss = skill.get("scan_summary") is not None
            has_fs = skill.get("findings_summary") is not None
            if has_ss and has_fs:
                so_detail["both"] += 1
            elif has_ss:
                so_detail["has_scan_summary"] += 1
            elif has_fs:
                so_detail["has_findings_summary"] += 1
            else:
                so_detail["neither"] += 1

        print("SCANNER-ONLY BREAKDOWN:")
        print("-" * 50)
        for k, v in so_detail.items():
            print(f"  {k:<45} {v:>6}")


if __name__ == "__main__":
    import os
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    main()
