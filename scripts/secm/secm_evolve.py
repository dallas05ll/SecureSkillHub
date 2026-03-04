#!/usr/bin/env python3
"""
Security Manager self-evolve loop.

Analyzes PM overrides and verification failures to:
1. Identify new false positive patterns not yet in SecM memory
2. Propose scanner regex fixes for recurring FP categories
3. Track FP rate trends across verification runs
4. Update secm-patterns.json with new learnings

This script should be run AFTER SM evolve to pick up the latest FP patterns.

Usage:
    python3 scripts/secm/secm_evolve.py              # Full evolve cycle
    python3 scripts/secm/secm_evolve.py --report      # Report only (no write)
"""

import argparse
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
SKILLS_DIR = PROJECT_ROOT / "data" / "skills"
SECM_MEMORY_FILE = PROJECT_ROOT / "memory" / "structured" / "secm-patterns.json"
VM_MEMORY_FILE = PROJECT_ROOT / "memory" / "structured" / "vm-corrections.json"
LOG_FILE = PROJECT_ROOT / "data" / "skill-manager-log.json"
sys.path.insert(0, str(PROJECT_ROOT))


def load_secm_memory() -> dict:
    """Load SecM structured memory."""
    if SECM_MEMORY_FILE.exists():
        try:
            return json.load(open(SECM_MEMORY_FILE))
        except Exception:
            pass
    return {"schema_version": "1.0", "role": "security_manager", "entries": []}


def load_vm_memory() -> dict:
    """Load VM corrections for cross-reference."""
    if VM_MEMORY_FILE.exists():
        try:
            return json.load(open(VM_MEMORY_FILE))
        except Exception:
            pass
    return {"entries": []}


def analyze_override_patterns(skills_dir: Path) -> dict:
    """Analyze all PM overrides to find FP pattern categories."""
    overrides_by_type: Counter = Counter()
    overrides_by_org: Counter = Counter()
    empty_scan_report = 0
    injection_fps = []
    obfuscation_fps = []
    structural_fps = []

    for f in sorted(skills_dir.glob("*.json")):
        try:
            s = json.load(open(f))
        except Exception:
            continue

        if not s.get("pm_override"):
            continue

        reason = s.get("pm_override_reason", "")
        repo = s.get("repo_url", "")
        scan = s.get("scan_report", {})
        audit = s.get("agent_audit", {})
        c_star = audit.get("agent_c_star", {})

        # Extract org
        org = ""
        if "github.com/" in repo:
            parts = repo.split("github.com/")[1].split("/")
            if parts:
                org = parts[0].lower()

        # Categorize FP type
        if "structural" in reason.lower() or "large-repo" in reason.lower():
            structural_fps.append({"skill": s.get("name"), "org": org, "reason": reason})
            overrides_by_type["structural_large_repo"] += 1
        elif "injection" in reason.lower() or "inj" in reason.lower():
            injection_fps.append({"skill": s.get("name"), "org": org, "reason": reason})
            overrides_by_type["injection_fp"] += 1
        elif "obfuscation" in reason.lower() or "obf" in reason.lower():
            obfuscation_fps.append({"skill": s.get("name"), "org": org, "reason": reason})
            overrides_by_type["obfuscation_fp"] += 1
        elif "scanner_penalty" in reason.lower():
            overrides_by_type["scanner_penalty"] += 1
        elif "data-uri" in reason.lower() or "base64" in reason.lower():
            overrides_by_type["data_uri_base64"] += 1
        elif "defense" in reason.lower() or "anti-injection" in reason.lower():
            overrides_by_type["defensive_code"] += 1
        else:
            overrides_by_type["other"] += 1

        if org:
            overrides_by_org[org] += 1

        # Check for empty scan_report bug
        if not scan and c_star.get("total_findings", 0) > 0:
            empty_scan_report += 1

    return {
        "total_overrides": sum(overrides_by_type.values()),
        "by_type": dict(overrides_by_type.most_common()),
        "by_org": dict(overrides_by_org.most_common(20)),
        "empty_scan_report_count": empty_scan_report,
        "injection_fps": injection_fps[:10],
        "obfuscation_fps": obfuscation_fps[:10],
        "structural_fps": structural_fps[:10],
    }


def generate_scanner_proposals(analysis: dict, secm_memory: dict) -> list[dict]:
    """Generate scanner fix proposals based on FP patterns."""
    proposals = []
    known_ids = {e["id"] for e in secm_memory.get("entries", [])}

    # Proposal: empty scan_report bug
    if analysis["empty_scan_report_count"] > 0 and "secm-p-013" not in known_ids:
        proposals.append({
            "id": "secm-p-013",
            "title": "Bug: empty scan_report with findings in agent_audit",
            "category": "pipeline_bug",
            "description": f"Scanner produces findings (in agent_c_star audit) but scan_report field is empty {{}}. "
                          f"Auto-clear cannot inspect findings. Affects {analysis['empty_scan_report_count']} skills. "
                          f"Fix: ensure pipeline.py writes scan_report from scanner output.",
            "priority": "P0",
            "action": "Fix pipeline.py to always write scan_report from scanner results",
        })

    # Proposal: data-URI / base64 image FPs
    data_uri_count = analysis["by_type"].get("data_uri_base64", 0)
    if data_uri_count > 0 and "secm-p-014" not in known_ids:
        proposals.append({
            "id": "secm-p-014",
            "title": "Scanner FP: Python data-URI f-strings",
            "category": "false_positive",
            "description": f"f'![{{alt}}](data:{{mime}};base64,{{data}})' triggers regex_markdown_injection. "
                          f"Legitimate image embedding for PDF/API. Affects {data_uri_count} overrides.",
            "priority": "P1",
            "action": "Exclude data: in f-string interpolation from markdown_injection pattern",
        })

    # Proposal: defensive/anti-injection code
    defense_count = analysis["by_type"].get("defensive_code", 0)
    if defense_count > 0 and "secm-p-015" not in known_ids:
        proposals.append({
            "id": "secm-p-015",
            "title": "Scanner FP: anti-injection defense prompts",
            "category": "false_positive",
            "description": f"Security hooks documenting injection phrases in defensive context "
                          f"(e.g., 'Avoid phrases like \"ignore previous instructions\"') trigger injection scanner. "
                          f"Affects {defense_count} overrides.",
            "priority": "P1",
            "action": "Add context-aware skip for quoted examples in defensive/educational text",
        })

    # Proposal: structural large-repo FPs
    structural_count = analysis["by_type"].get("structural_large_repo", 0)
    if structural_count > 5 and "secm-p-016" not in known_ids:
        proposals.append({
            "id": "secm-p-016",
            "title": "Structural FP: skillsmp full-repo scanning",
            "category": "root_cause",
            "description": f"SkillsMP skills link to full project repos. Scanner scans entire massive codebase. "
                          f"{structural_count} overrides from this pattern alone.",
            "priority": "P0",
            "action": "Scope scanner to skill-specific directory (skillPath) instead of full repo clone",
        })

    return proposals


def evolve(report_only: bool = False):
    """Run SecM self-evolve cycle."""
    now = datetime.now(timezone.utc).isoformat()
    print("=" * 60)
    print("SecM Self-Evolve Cycle")
    print("=" * 60)

    # Step 1: Read prior learnings
    secm_memory = load_secm_memory()
    vm_memory = load_vm_memory()
    print(f"\nSecM memory: {len(secm_memory.get('entries', []))} entries")
    print(f"VM corrections: {len(vm_memory.get('entries', []))} entries")

    # Step 2: Analyze all PM overrides
    analysis = analyze_override_patterns(SKILLS_DIR)
    print(f"\n--- Override Analysis ---")
    print(f"Total overrides: {analysis['total_overrides']}")
    print(f"By type: {analysis['by_type']}")
    print(f"Empty scan_report bug: {analysis['empty_scan_report_count']} skills affected")
    print(f"Top orgs: {dict(list(analysis['by_org'].items())[:10])}")

    # Step 3: Generate scanner fix proposals
    proposals = generate_scanner_proposals(analysis, secm_memory)
    print(f"\n--- Scanner Fix Proposals ---")
    if proposals:
        for p in proposals:
            print(f"  [{p['priority']}] {p['title']}")
            print(f"       Action: {p['action']}")
    else:
        print("  No new proposals — all known patterns already tracked")

    # Step 4: Cross-reference with VM corrections
    vm_fixes = [e for e in vm_memory.get("entries", []) if e.get("status") == "fixed"]
    vm_pending = [e for e in vm_memory.get("entries", []) if e.get("status") not in ("fixed", "implemented", "superseded_by_vm-c-017")]
    print(f"\n--- VM Cross-Reference ---")
    print(f"  VM fixes applied: {len(vm_fixes)}")
    print(f"  VM items pending: {len(vm_pending)}")

    if report_only:
        print("\n[Report only mode — no memory written]")
        return

    # Step 5: Write new entries to SecM memory
    entry_map = {e["id"]: e for e in secm_memory.get("entries", [])}
    new_count = 0
    for p in proposals:
        if p["id"] not in entry_map:
            entry_map[p["id"]] = {
                "id": p["id"],
                "title": p["title"],
                "category": p["category"],
                "description": p["description"],
                "priority": p.get("priority"),
                "action": p.get("action"),
                "discovered": now,
            }
            new_count += 1

    secm_memory["entries"] = list(entry_map.values())
    secm_memory["last_evolve"] = now

    if not secm_memory.get("evolve_history"):
        secm_memory["evolve_history"] = []
    secm_memory["evolve_history"].append({
        "timestamp": now,
        "total_overrides": analysis["total_overrides"],
        "by_type": analysis["by_type"],
        "proposals_generated": len(proposals),
        "new_entries_added": new_count,
    })

    SECM_MEMORY_FILE.write_text(json.dumps(secm_memory, indent=2, ensure_ascii=False))
    print(f"\nSecM memory updated: {SECM_MEMORY_FILE} (+{new_count} new entries)")

    # Log
    try:
        log = json.load(open(LOG_FILE)) if Path(LOG_FILE).exists() else {"entries": []}
        log["entries"].append({
            "type": "secm_evolve",
            "timestamp": now,
            "summary": {
                "total_overrides_analyzed": analysis["total_overrides"],
                "proposals_generated": len(proposals),
                "new_patterns_learned": new_count,
                "empty_scan_report_bug": analysis["empty_scan_report_count"],
            },
        })
        Path(LOG_FILE).write_text(json.dumps(log, indent=2, ensure_ascii=False))
    except Exception:
        pass


def main():
    parser = argparse.ArgumentParser(description="SecM self-evolve loop")
    parser.add_argument("--report", action="store_true", help="Report only, no memory write")
    args = parser.parse_args()
    evolve(report_only=args.report)


if __name__ == "__main__":
    main()
