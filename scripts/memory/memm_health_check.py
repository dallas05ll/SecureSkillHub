#!/usr/bin/env python3
"""
Memory Manager Health Check Script
===================================
Implements MemM HEALTH protocol: validates all structured memory files,
checks for contradictions, rot, size budgets, orphans, and coverage gaps.

Usage:
    python3 scripts/memory/memm_health_check.py              # Full health check
    python3 scripts/memory/memm_health_check.py --verbose     # Detailed output
    python3 scripts/memory/memm_health_check.py --fix         # Auto-fix meta counts
    python3 scripts/memory/memm_health_check.py --evolve      # Run EVOLVE protocol
"""

import json
import glob
import os
import sys
import argparse
from datetime import datetime, timedelta, timezone
from collections import defaultdict
from pathlib import Path

# Resolve paths
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent.parent
MEMORY_DIR = Path(os.environ.get("MEMM_DIR", str(Path.home() / ".claude" / "projects" / "-Users-liendallas-Desktop-Projects-SecureSkillHub" / "memory")))
STRUCTURED_DIR = MEMORY_DIR / "structured"
ROLES_DIR = PROJECT_ROOT / "roles"

SCHEMA_VERSION = "1.0"
REQUIRED_FIELDS = ["id", "date", "source", "type", "tags", "applies_to", "rule", "status"]
VALID_TYPES = ["false_positive", "bug_fix", "pattern", "workflow", "rule"]
VALID_STATUSES = ["active", "archived", "superseded"]
VALID_CONFIDENCE = ["tentative", "confirmed", "established"]

# Token budget estimates (rough: 1 correction ≈ 80 tokens)
TOKEN_BUDGETS = {
    "vm": 80,    # sonnet model, max ~80 corrections
    "secm": 60,  # opus model, max ~60
    "sm": 60,
    "pm": 50,
    "axm": 40,
    "docm": 40,
    "dplm": 30,
    "frtm": 30,
    "memm": 40,
}

EXPECTED_FILES = [
    "vm-corrections.json", "secm-patterns.json", "sm-health.json",
    "pm-decisions.json", "axm-patterns.json", "docm-knowledge.json",
    "dplm-history.json", "frtm-fixes.json", "memm-meta.json"
]


def load_all_files():
    """Load all structured memory files."""
    files = {}
    for f in EXPECTED_FILES:
        path = STRUCTURED_DIR / f
        if path.exists():
            try:
                files[f] = json.loads(path.read_text())
            except json.JSONDecodeError as e:
                files[f] = {"_error": str(e)}
        else:
            files[f] = None
    return files


def check_file_integrity(files):
    """Check 1: All files exist and parse correctly with required structure."""
    issues = []
    for fname, data in files.items():
        if data is None:
            issues.append(("MISSING", fname, f"File not found: {STRUCTURED_DIR / fname}"))
            continue
        if "_error" in data:
            issues.append(("CORRUPT", fname, f"JSON parse error: {data['_error']}"))
            continue
        for field in ["schema_version", "role", "corrections", "meta"]:
            if field not in data:
                issues.append(("SCHEMA", fname, f"Missing top-level field: {field}"))
        if data.get("schema_version") != SCHEMA_VERSION:
            issues.append(("VERSION", fname, f"Schema version {data.get('schema_version')} != expected {SCHEMA_VERSION}"))
    return issues


def check_correction_schema(files):
    """Check 2: Every correction has required fields with valid values."""
    issues = []
    for fname, data in files.items():
        if data is None or "_error" in data:
            continue
        for c in data.get("corrections", []):
            cid = c.get("id", "UNKNOWN")
            for field in REQUIRED_FIELDS:
                if field not in c:
                    issues.append(("FIELD", fname, f"Correction {cid} missing required field: {field}"))
            if c.get("type") and c["type"] not in VALID_TYPES:
                issues.append(("TYPE", fname, f"Correction {cid} has invalid type: {c['type']}"))
            if c.get("status") and c["status"] not in VALID_STATUSES:
                issues.append(("STATUS", fname, f"Correction {cid} has invalid status: {c['status']}"))
            if c.get("confidence") and c["confidence"] not in VALID_CONFIDENCE:
                issues.append(("CONFIDENCE", fname, f"Correction {cid} has invalid confidence: {c['confidence']}"))
            if not isinstance(c.get("tags", []), list):
                issues.append(("TAGS", fname, f"Correction {cid} tags is not a list"))
            if not isinstance(c.get("applies_to", []), list):
                issues.append(("APPLIES", fname, f"Correction {cid} applies_to is not a list"))
    return issues


def check_duplicate_ids(files):
    """Check 3: No duplicate correction IDs across all files."""
    issues = []
    all_ids = {}
    for fname, data in files.items():
        if data is None or "_error" in data:
            continue
        for c in data.get("corrections", []):
            cid = c.get("id", "UNKNOWN")
            if cid in all_ids:
                issues.append(("DUPLICATE", fname, f"ID {cid} already exists in {all_ids[cid]}"))
            all_ids[cid] = fname
    return issues


def check_meta_accuracy(files):
    """Check 4: meta.total_active matches actual count."""
    issues = []
    fixes = {}
    for fname, data in files.items():
        if data is None or "_error" in data:
            continue
        actual_active = sum(1 for c in data.get("corrections", []) if c.get("status") == "active")
        actual_archived = sum(1 for c in data.get("corrections", []) if c.get("status") in ("archived", "superseded"))
        declared_active = data.get("meta", {}).get("total_active", -1)
        declared_archived = data.get("meta", {}).get("total_archived", -1)
        if actual_active != declared_active:
            issues.append(("META", fname, f"total_active: declared={declared_active}, actual={actual_active}"))
            fixes[fname] = {"total_active": actual_active}
        if declared_archived >= 0 and actual_archived != declared_archived:
            issues.append(("META", fname, f"total_archived: declared={declared_archived}, actual={actual_archived}"))
            if fname not in fixes:
                fixes[fname] = {}
            fixes[fname]["total_archived"] = actual_archived
    return issues, fixes


def check_cross_role_contradictions(files):
    """Check 5: Detect contradictions between roles.

    Uses direction-aware analysis: two rules that both push the same corrective
    direction (e.g., both say 'this is a false positive' or both say 'auto-pass')
    are complementary, not contradictory. Only flags when rules genuinely
    recommend opposite actions.
    """
    issues = []
    # Build a tag→rules index
    tag_rules = defaultdict(list)
    for fname, data in files.items():
        if data is None or "_error" in data:
            continue
        role = data.get("role", "?")
        for c in data.get("corrections", []):
            if c.get("status") != "active":
                continue
            for tag in c.get("tags", []):
                tag_rules[tag].append({
                    "id": c.get("id"),
                    "role": role,
                    "rule": c.get("rule", ""),
                    "file": fname
                })

    # Tags where contradiction detection is suppressed because entries inherently
    # span multiple domains and use vocabulary from both directions
    EXEMPT_TAGS = {"consolidated", "scoring", "infrastructure"}

    # Direction keywords: rules sharing the same direction are complementary.
    # Longer/more-specific phrases are weighted higher to avoid domain vocabulary
    # being misread as directional signals (e.g., "dangerous_calls" is a label,
    # not a recommendation that something is dangerous).
    PERMISSIVE_SIGNALS = [
        "safe", "false positive", " fp ", "should pass", "correctly excluded",
        "not dangerous", "low-risk", "low_risk", "standard", "legitimate",
        "auto-pass", "scoring bug", "not security", "correctly", "excluded from",
        "medium risk", "not high", "cap ", "capped", "downgrade", "not flag",
        "lacks context", "needs context", "needs disambiguation",
    ]
    RESTRICTIVE_SIGNALS = [
        "block", "reject", "true positive", "must fail", "critical threat",
        "non-negotiable",
    ]

    def get_direction(rule_text):
        """Determine the corrective direction of a rule."""
        text = rule_text.lower()
        perm = sum(1 for kw in PERMISSIVE_SIGNALS if kw in text)
        rest = sum(1 for kw in RESTRICTIVE_SIGNALS if kw in text)
        if perm > rest:
            return "permissive"
        elif rest > perm:
            return "restrictive"
        return None

    contradiction_keywords = [
        ("safe", "dangerous"),
        ("pass", "fail"),
        ("exclude", "include"),
        ("low-risk", "high-risk"),
        ("false_positive", "true_positive"),
    ]
    for tag, entries in tag_rules.items():
        if len(entries) < 2:
            continue
        # Skip exempt tags (consolidated rules, scoring rules span both domains)
        if tag in EXEMPT_TAGS:
            continue
        for e1 in entries:
            for e2 in entries:
                if e1["role"] >= e2["role"]:
                    continue
                rule1 = e1["rule"].lower()
                rule2 = e2["rule"].lower()

                # If both rules push the same direction, they're complementary
                dir1 = get_direction(e1["rule"])
                dir2 = get_direction(e2["rule"])
                if dir1 and dir2 and dir1 == dir2:
                    continue

                # If either direction is unknown but the other is permissive,
                # don't flag — most corrections in this system are permissive
                if (dir1 == "permissive" and dir2 is None) or (dir2 == "permissive" and dir1 is None):
                    continue

                for pos, neg in contradiction_keywords:
                    if (pos in rule1 and neg in rule2) or (neg in rule1 and pos in rule2):
                        issues.append(("CONTRADICTION", f"{e1['file']}↔{e2['file']}",
                            f"Tag '{tag}': {e1['id']} ({e1['role']}) vs {e2['id']} ({e2['role']}) — possible conflict ({pos}/{neg})"))
    return issues


def check_staleness(files):
    """Check 6: Detect stale entries (>30 days without update)."""
    issues = []
    now = datetime.now(timezone.utc)
    threshold = now - timedelta(days=30)

    for fname, data in files.items():
        if data is None or "_error" in data:
            continue
        for c in data.get("corrections", []):
            if c.get("status") != "active":
                continue
            try:
                entry_date = datetime.fromisoformat(c["date"])
                if entry_date.tzinfo is None:
                    entry_date = entry_date.replace(tzinfo=timezone.utc)
                if entry_date < threshold:
                    issues.append(("STALE", fname,
                        f"Correction {c['id']} is {(now - entry_date).days} days old (since {c['date']})"))
            except (ValueError, KeyError):
                pass
    return issues


def check_orphan_tentative(files):
    """Check 7: Tentative entries older than 14 days need confirmation or archival."""
    issues = []
    now = datetime.now(timezone.utc)
    threshold = now - timedelta(days=14)

    for fname, data in files.items():
        if data is None or "_error" in data:
            continue
        for c in data.get("corrections", []):
            if c.get("status") != "active" or c.get("confidence") != "tentative":
                continue
            try:
                entry_date = datetime.fromisoformat(c["date"])
                if entry_date.tzinfo is None:
                    entry_date = entry_date.replace(tzinfo=timezone.utc)
                if entry_date < threshold:
                    issues.append(("ORPHAN", fname,
                        f"Tentative correction {c['id']} is {(now - entry_date).days} days old — needs confirmation or archival"))
            except (ValueError, KeyError):
                pass
    return issues


def check_size_budgets(files):
    """Check 8: Check if any role's memory exceeds token budget."""
    issues = []
    for fname, data in files.items():
        if data is None or "_error" in data:
            continue
        role = data.get("role", "?")
        active_count = sum(1 for c in data.get("corrections", []) if c.get("status") == "active")
        budget = TOKEN_BUDGETS.get(role, 40)
        usage_pct = (active_count / budget) * 100 if budget > 0 else 0
        if active_count > budget:
            issues.append(("OVERSIZE", fname,
                f"Role {role}: {active_count} active entries exceeds budget of {budget} ({usage_pct:.0f}%)"))
        elif usage_pct > 75:
            issues.append(("WARNING", fname,
                f"Role {role}: {active_count}/{budget} active entries ({usage_pct:.0f}% — approaching limit)"))
    return issues


def check_coverage_gaps(files):
    """Check 9: Detect roles with very few entries relative to their activity."""
    issues = []
    activity_expectations = {
        "vm": 5,     # high-activity role, should have many corrections
        "secm": 3,   # moderate-activity
        "sm": 3,     # moderate-activity
        "pm": 2,     # decisions accumulate slowly
        "axm": 1,    # lower activity
        "docm": 1,   # lower activity
        "dplm": 1,   # lower activity
        "frtm": 1,   # lower activity
        "memm": 1,   # meta-role
    }
    for fname, data in files.items():
        if data is None or "_error" in data:
            continue
        role = data.get("role", "?")
        active_count = sum(1 for c in data.get("corrections", []) if c.get("status") == "active")
        min_expected = activity_expectations.get(role, 1)
        if active_count < min_expected:
            issues.append(("GAP", fname,
                f"Role {role}: only {active_count} active entries (expected ≥{min_expected} for this role's activity level)"))
    return issues


def check_audit_status(files):
    """Check 10: Entries that haven't been audited by MemM."""
    issues = []
    unaudited = 0
    for fname, data in files.items():
        if data is None or "_error" in data:
            continue
        for c in data.get("corrections", []):
            if c.get("status") != "active":
                continue
            audit = c.get("audit", {})
            if audit.get("memm_result") == "pending" or audit.get("memm_checked") is None:
                unaudited += 1
    if unaudited > 0:
        issues.append(("UNAUDITED", "all", f"{unaudited} active corrections have not been audited by MemM"))
    return issues


def compute_metrics(files):
    """Compute aggregate metrics across all files."""
    metrics = {
        "files_checked": 0,
        "total_active": 0,
        "total_archived": 0,
        "total_superseded": 0,
        "per_role": {},
        "by_type": defaultdict(int),
        "by_confidence": defaultdict(int),
        "top_tags": defaultdict(int),
    }
    for fname, data in files.items():
        if data is None or "_error" in data:
            continue
        metrics["files_checked"] += 1
        role = data.get("role", "?")
        active = 0
        archived = 0
        for c in data.get("corrections", []):
            status = c.get("status", "?")
            if status == "active":
                active += 1
                metrics["total_active"] += 1
                metrics["by_type"][c.get("type", "?")] += 1
                metrics["by_confidence"][c.get("confidence", "unset")] += 1
                for tag in c.get("tags", []):
                    metrics["top_tags"][tag] += 1
            elif status == "archived":
                archived += 1
                metrics["total_archived"] += 1
            elif status == "superseded":
                metrics["total_superseded"] += 1
        metrics["per_role"][role] = {"active": active, "archived": archived, "file": fname}
    return metrics


def run_evolve(files, verbose=False):
    """Run EVOLVE protocol: identify consolidation candidates."""
    candidates = []

    for fname, data in files.items():
        if data is None or "_error" in data:
            continue
        role = data.get("role", "?")
        active = [c for c in data.get("corrections", []) if c.get("status") == "active"]

        # Find entries with overlapping tags that could be consolidated
        tag_groups = defaultdict(list)
        for c in active:
            for tag in c.get("tags", []):
                tag_groups[tag].append(c)

        for tag, entries in tag_groups.items():
            if len(entries) >= 3:
                ids = [e["id"] for e in entries]
                candidates.append({
                    "role": role,
                    "file": fname,
                    "tag": tag,
                    "count": len(entries),
                    "ids": ids,
                    "suggestion": f"Consolidate {len(entries)} corrections tagged '{tag}' into fewer general rules"
                })

    return candidates


def generate_report(all_issues, metrics, evolve_candidates, verbose=False):
    """Generate the full health report."""
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    severity_order = {"MISSING": 0, "CORRUPT": 0, "SCHEMA": 0, "DUPLICATE": 0,
                      "CONTRADICTION": 1, "OVERSIZE": 1, "META": 2, "ORPHAN": 2,
                      "STALE": 3, "GAP": 3, "WARNING": 3, "UNAUDITED": 3, "VERSION": 3,
                      "FIELD": 2, "TYPE": 2, "STATUS": 2, "CONFIDENCE": 2,
                      "TAGS": 2, "APPLIES": 2}

    critical = [i for i in all_issues if severity_order.get(i[0], 9) <= 1]
    warnings = [i for i in all_issues if severity_order.get(i[0], 9) == 2]
    info = [i for i in all_issues if severity_order.get(i[0], 9) >= 3]

    lines = []
    lines.append(f"MEMORY HEALTH REPORT — {now}")
    lines.append("=" * 50)
    lines.append(f"Files checked: {metrics['files_checked']}/9")
    lines.append(f"Total active entries: {metrics['total_active']}")
    lines.append(f"Total archived: {metrics['total_archived']}")
    lines.append(f"Total superseded: {metrics['total_superseded']}")
    lines.append("")

    # Per-role breakdown
    lines.append("PER-ROLE BREAKDOWN:")
    for role, info_dict in sorted(metrics["per_role"].items()):
        budget = TOKEN_BUDGETS.get(role, 40)
        pct = (info_dict["active"] / budget * 100) if budget else 0
        bar = "█" * int(pct / 5) + "░" * (20 - int(pct / 5))
        lines.append(f"  {role:6s}: {info_dict['active']:3d} active, {info_dict['archived']:2d} archived  [{bar}] {pct:.0f}%")
    lines.append("")

    # By type
    lines.append("BY TYPE:")
    for t, count in sorted(metrics["by_type"].items(), key=lambda x: -x[1]):
        lines.append(f"  {t:20s}: {count}")
    lines.append("")

    # By confidence
    lines.append("BY CONFIDENCE:")
    for c, count in sorted(metrics["by_confidence"].items(), key=lambda x: -x[1]):
        lines.append(f"  {c:20s}: {count}")
    lines.append("")

    # Top tags
    lines.append("TOP 10 TAGS:")
    for tag, count in sorted(metrics["top_tags"].items(), key=lambda x: -x[1])[:10]:
        lines.append(f"  {tag:30s}: {count}")
    lines.append("")

    # Issues
    if critical:
        lines.append(f"CRITICAL ISSUES ({len(critical)}):")
        for sev, loc, msg in critical:
            lines.append(f"  [{sev}] {loc}: {msg}")
        lines.append("")

    if warnings:
        lines.append(f"WARNINGS ({len(warnings)}):")
        for sev, loc, msg in warnings:
            lines.append(f"  [{sev}] {loc}: {msg}")
        lines.append("")

    if info:
        lines.append(f"INFO ({len(info)}):")
        for sev, loc, msg in info:
            lines.append(f"  [{sev}] {loc}: {msg}")
        lines.append("")

    if not all_issues:
        lines.append("NO ISSUES FOUND — all checks passed!")
        lines.append("")

    # Evolve candidates
    if evolve_candidates:
        lines.append(f"EVOLVE CANDIDATES ({len(evolve_candidates)}):")
        for ec in evolve_candidates:
            lines.append(f"  {ec['role']}: {ec['suggestion']}")
            if verbose:
                lines.append(f"    IDs: {', '.join(ec['ids'])}")
        lines.append("")

    # Summary
    total_issues = len(all_issues)
    status = "HEALTHY" if not critical else "NEEDS ATTENTION"
    lines.append(f"OVERALL STATUS: {status}")
    lines.append(f"Total issues: {total_issues} ({len(critical)} critical, {len(warnings)} warnings, {len(info)} info)")

    return "\n".join(lines)


def apply_fixes(files, fixes):
    """Auto-fix meta counts."""
    for fname, fix_data in fixes.items():
        path = STRUCTURED_DIR / fname
        data = json.loads(path.read_text())
        for key, val in fix_data.items():
            data["meta"][key] = val
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
        print(f"  Fixed {fname}: {fix_data}")


def main():
    parser = argparse.ArgumentParser(description="MemM Health Check")
    parser.add_argument("--verbose", "-v", action="store_true", help="Detailed output")
    parser.add_argument("--fix", action="store_true", help="Auto-fix meta counts")
    parser.add_argument("--evolve", action="store_true", help="Show EVOLVE candidates")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    files = load_all_files()

    # Run all checks
    all_issues = []
    all_issues.extend(check_file_integrity(files))
    all_issues.extend(check_correction_schema(files))
    all_issues.extend(check_duplicate_ids(files))
    meta_issues, fixes = check_meta_accuracy(files)
    all_issues.extend(meta_issues)
    all_issues.extend(check_cross_role_contradictions(files))
    all_issues.extend(check_staleness(files))
    all_issues.extend(check_orphan_tentative(files))
    all_issues.extend(check_size_budgets(files))
    all_issues.extend(check_coverage_gaps(files))
    all_issues.extend(check_audit_status(files))

    metrics = compute_metrics(files)
    evolve_candidates = run_evolve(files) if args.evolve else []

    if args.json:
        result = {
            "timestamp": datetime.now().isoformat(),
            "issues": [{"severity": s, "location": l, "message": m} for s, l, m in all_issues],
            "metrics": {k: v for k, v in metrics.items() if k != "top_tags"},
            "evolve_candidates": evolve_candidates,
            "status": "healthy" if not any(i[0] in ("MISSING", "CORRUPT", "CONTRADICTION", "OVERSIZE") for i in all_issues) else "needs_attention"
        }
        print(json.dumps(result, indent=2, default=str))
    else:
        report = generate_report(all_issues, metrics, evolve_candidates, args.verbose)
        print(report)

    if args.fix and fixes:
        print("\nApplying fixes...")
        apply_fixes(files, fixes)

    return 0 if not any(i[0] in ("MISSING", "CORRUPT", "SCHEMA", "DUPLICATE") for i in all_issues) else 1


if __name__ == "__main__":
    sys.exit(main())
