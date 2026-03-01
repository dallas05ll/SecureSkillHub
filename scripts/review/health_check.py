#!/usr/bin/env python3
"""
Skills Manager health check — collection dashboard.

Reads data files and outputs a formatted dashboard to stdout.
Logs every run to data/skill-manager-log.json so the skill manager
has persistent memory of past checks, findings, and behavior patterns.

No external dependencies required.

Usage:
    python3 health_check.py             # Run dashboard + log entry
    python3 health_check.py --history   # Show last 5 log entries
    python3 health_check.py --history 10  # Show last 10 log entries
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
SKILLS_DIR = PROJECT_ROOT / "data" / "skills"
STATS_FILE = PROJECT_ROOT / "data" / "stats.json"
CRAWL_STATE_FILE = PROJECT_ROOT / "data" / "crawl-state.json"
VERIFY_QUEUE_FILE = PROJECT_ROOT / "data" / "verify-queue.json"
PACKAGES_INDEX = PROJECT_ROOT / "data" / "packages" / "index.json"
TAGS_FILE = PROJECT_ROOT / "data" / "tags.json"
LOG_FILE = PROJECT_ROOT / "data" / "skill-manager-log.json"


# ── Log helpers ───────────────────────────────────────────────────


def load_json(path: Path) -> dict | list | None:
    """Load a JSON file, return None if missing or invalid."""
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def load_log() -> dict:
    """Load the skill manager log, or return a fresh structure."""
    log = load_json(LOG_FILE)
    if isinstance(log, dict) and "entries" in log:
        return log
    return {
        "log_version": 1,
        "entries": [],
        "last_check": None,
        "summary": {
            "total_checks": 0,
            "issues_found_lifetime": 0,
            "last_healthy": None,
        },
    }


def save_log(log: dict) -> None:
    """Write the log back to disk."""
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    LOG_FILE.write_text(json.dumps(log, indent=2, ensure_ascii=False) + "\n")


def get_previous_entry(log: dict) -> dict | None:
    """Return the most recent entry, or None if no history."""
    entries = log.get("entries", [])
    return entries[-1] if entries else None


def compute_changes(current_findings: dict, previous_entry: dict | None) -> dict:
    """Compute what changed since the last logged entry."""
    if previous_entry is None:
        return {
            "new_skills": 0,
            "newly_verified": 0,
            "status_changes": ["First run — no previous data to compare"],
        }

    prev = previous_entry.get("findings", {})
    changes = {}

    prev_total = prev.get("total_skills", 0)
    curr_total = current_findings.get("total_skills", 0)
    changes["new_skills"] = curr_total - prev_total

    prev_verified = prev.get("verified", 0)
    curr_verified = current_findings.get("verified", 0)
    changes["newly_verified"] = curr_verified - prev_verified

    status_changes = []
    if changes["new_skills"] > 0:
        status_changes.append(f"+{changes['new_skills']} new skills added")
    elif changes["new_skills"] < 0:
        status_changes.append(f"{changes['new_skills']} skills removed")

    if changes["newly_verified"] > 0:
        status_changes.append(f"+{changes['newly_verified']} newly verified")
    elif changes["newly_verified"] < 0:
        status_changes.append(f"{changes['newly_verified']} verifications lost")

    prev_unverified = prev.get("unverified", 0)
    curr_unverified = current_findings.get("unverified", 0)
    delta_unverified = curr_unverified - prev_unverified
    if delta_unverified != 0:
        sign = "+" if delta_unverified > 0 else ""
        status_changes.append(f"{sign}{delta_unverified} unverified delta")

    if not status_changes:
        status_changes.append("No changes since last check")

    changes["status_changes"] = status_changes
    return changes


def append_log_entry(
    log: dict,
    check_type: str,
    findings: dict,
    recommendations: list[str],
    changes: dict,
) -> None:
    """Append a new entry and update summary counters."""
    now = datetime.now(timezone.utc).isoformat()

    entry = {
        "timestamp": now,
        "check_type": check_type,
        "findings": findings,
        "recommendations": recommendations,
        "changes_since_last": changes,
    }

    log["entries"].append(entry)
    log["last_check"] = now
    log["summary"]["total_checks"] += 1
    log["summary"]["issues_found_lifetime"] += len(findings.get("issues", []))

    if not findings.get("issues"):
        log["summary"]["last_healthy"] = now


# ── Display helpers ───────────────────────────────────────────────


def section(title: str) -> None:
    """Print a section header."""
    print()
    print("=" * 60)
    print(f"  {title}")
    print("=" * 60)


def show_history(n: int = 5) -> None:
    """Display the last N entries from the skill manager log."""
    log = load_log()
    entries = log.get("entries", [])

    print("=" * 60)
    print("  SecureSkillHub — Skills Manager History")
    print("=" * 60)

    print(f"\n  Total checks recorded: {log['summary']['total_checks']}")
    print(f"  Issues found (lifetime): {log['summary']['issues_found_lifetime']}")
    print(f"  Last healthy check: {log['summary'].get('last_healthy', 'never')}")

    if not entries:
        print("\n  No history recorded yet. Run `python3 health_check.py` first.")
        return

    # Show last N entries, most recent first
    recent = entries[-n:][::-1]
    print(f"\n  Showing last {len(recent)} of {len(entries)} entries:\n")

    for i, entry in enumerate(recent):
        ts = entry.get("timestamp", "?")
        check_type = entry.get("check_type", "?")
        findings = entry.get("findings", {})
        recs = entry.get("recommendations", [])
        changes = entry.get("changes_since_last", {})

        print(f"  {'─' * 56}")
        print(f"  [{i + 1}] {ts}")
        print(f"      Type: {check_type}")
        print(f"      Skills: {findings.get('total_skills', '?')}  "
              f"Verified: {findings.get('verified', '?')}  "
              f"Unverified: {findings.get('unverified', '?')}")

        issues = findings.get("issues", [])
        if issues:
            print(f"      Issues ({len(issues)}):")
            for issue in issues:
                print(f"        - {issue}")
        else:
            print("      Issues: none")

        if recs:
            print(f"      Recommendations:")
            for rec in recs:
                # Strip leading whitespace that was used for dashboard display
                print(f"        - {rec.strip()}")

        status_changes = changes.get("status_changes", [])
        if status_changes:
            print(f"      Changes:")
            for sc in status_changes:
                print(f"        - {sc}")

        print()

    print("=" * 60)


# ── Main dashboard ────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Skills Manager health check dashboard"
    )
    parser.add_argument(
        "--history",
        nargs="?",
        const=5,
        type=int,
        metavar="N",
        help="Show last N log entries (default: 5) instead of running a new check",
    )
    args = parser.parse_args()

    if args.history is not None:
        show_history(args.history)
        return

    # Load log to show previous-check info and compute deltas later
    log = load_log()
    previous_entry = get_previous_entry(log)

    print("=" * 60)
    print("  SecureSkillHub — Skills Manager Dashboard")
    print("=" * 60)

    # ── Last Check Info ───────────────────────────────────────────
    if log["last_check"]:
        print(f"\n  Last check: {log['last_check']}")
        print(f"  Total checks so far: {log['summary']['total_checks']}")
    else:
        print("\n  Last check: never (first run)")

    # ── 1. Collection Summary ──────────────────────────────────
    section("1. Collection Summary")

    stats = load_json(STATS_FILE)
    if stats:
        print(f"  Total skills:     {stats.get('total_skills', '?')}")
        print(f"  Verified (pass):  {stats.get('verified_skills', '?')}")
        print(f"  Failed:           {stats.get('failed_skills', '?')}")
        print(f"  Pending review:   {stats.get('pending_review', '?')}")
        print(f"  Total scans run:  {stats.get('total_scans_run', '?')}")
        print(f"  Last crawl:       {stats.get('last_crawl', '?')}")
        print(f"  Last build:       {stats.get('last_build', '?')}")

        sources = stats.get("sources", {})
        if sources:
            print()
            print("  Per-source breakdown:")
            for src, count in sorted(sources.items(), key=lambda x: -x[1]):
                print(f"    {src:25s} {count:>6,}")

        skill_types = stats.get("skill_types", {})
        if skill_types:
            print()
            print("  Per-type breakdown:")
            for stype, count in sorted(skill_types.items(), key=lambda x: -x[1]):
                print(f"    {stype:25s} {count:>6,}")
    else:
        print("  [WARNING] data/stats.json not found or invalid")

    # ── 2. Crawl State ─────────────────────────────────────────
    section("2. Crawl State")

    crawl_state = load_json(CRAWL_STATE_FILE)
    if crawl_state:
        hubs = crawl_state.get("hubs", {})
        print(f"  {'Hub':<25s} {'Status':<12s} {'Collected':>10s} {'Pages':>8s} {'Trust':<8s}")
        print(f"  {'-'*25} {'-'*12} {'-'*10} {'-'*8} {'-'*8}")
        for key, hub in sorted(hubs.items()):
            print(
                f"  {key:<25s} {hub.get('status', '?'):<12s} "
                f"{hub.get('total_collected', 0):>10,} "
                f"{hub.get('pages_crawled', 0):>8} "
                f"{hub.get('trust_level', '?'):<8s}"
            )
        last_updated = crawl_state.get("last_updated", "?")
        print(f"\n  Last updated: {last_updated}")
    else:
        print("  [WARNING] data/crawl-state.json not found or invalid")

    # ── 3. Verification Coverage ───────────────────────────────
    section("3. Verification Coverage")

    skill_files = sorted(SKILLS_DIR.glob("*.json")) if SKILLS_DIR.exists() else []
    # Initialize variables used later in recommendations and logging
    status_counts = {}
    vl_counts_early = {"full_pipeline": 0, "scanner_only": 0, "metadata_only": 0}
    missing_commit = 0
    null_scan_date = 0
    string_findings = 0
    star_tiers = {"1000+": 0, "100-999": 0, "10-99": 0, "1-9": 0, "0": 0}
    total = 0
    verified = 0

    if skill_files:
        for f in skill_files:
            try:
                data = json.loads(f.read_text())
            except (json.JSONDecodeError, OSError):
                continue

            vs = data.get("verification_status", "unverified") or "unverified"
            status_counts[vs] = status_counts.get(vs, 0) + 1

            vl = (data.get("verification_level") or "").strip().lower()
            if vs == "pass" and vl in ("full_pipeline", "scanner_only", "metadata_only"):
                vl_counts_early[vl] = vl_counts_early.get(vl, 0) + 1

            if vs != "unverified" and not data.get("verified_commit"):
                missing_commit += 1
            if vs != "unverified" and not data.get("scan_date"):
                null_scan_date += 1
            if isinstance(data.get("findings_summary"), str):
                string_findings += 1

            stars = data.get("stars", 0) or 0
            if stars >= 1000:
                star_tiers["1000+"] += 1
            elif stars >= 100:
                star_tiers["100-999"] += 1
            elif stars >= 10:
                star_tiers["10-99"] += 1
            elif stars >= 1:
                star_tiers["1-9"] += 1
            else:
                star_tiers["0"] += 1

        total = len(skill_files)
        verified = status_counts.get("pass", 0)
        pct = (verified / total * 100) if total else 0

        print(f"  Total skill files:  {total:,}")
        print(f"  Verification rate:  {pct:.1f}%")
        print()
        print("  Status breakdown:")
        for status, count in sorted(status_counts.items(), key=lambda x: -x[1]):
            print(f"    {status:25s} {count:>6,}")

        print()
        print("  Verification depth (pass skills only):")
        for vl_name, vl_label in [("full_pipeline", "Full pipeline (5-agent)"),
                                   ("scanner_only", "Scanner only (Agent C*)"),
                                   ("metadata_only", "Metadata only (no scan)")]:
            print(f"    {vl_label:30s} {vl_counts_early.get(vl_name, 0):>6,}")
        print()
        print("  Star tiers:")
        for tier, count in [("1000+", star_tiers["1000+"]),
                            ("100-999", star_tiers["100-999"]),
                            ("10-99", star_tiers["10-99"]),
                            ("1-9", star_tiers["1-9"]),
                            ("0", star_tiers["0"])]:
            print(f"    {tier:>10s} stars: {count:>6,}")

        # ── 4. Data Quality Flags ──────────────────────────────
        section("4. Data Quality Flags")

        issues_list = []
        if missing_commit:
            issues_list.append(f"{missing_commit} verified skills with null verified_commit")
        if null_scan_date:
            issues_list.append(f"{null_scan_date} verified skills with null scan_date")
        if string_findings:
            issues_list.append(f"{string_findings} skills with findings_summary as string (should be dict)")

        if issues_list:
            for issue in issues_list:
                print(f"  {issue}")
            print()
            print("  Fix: python3 fix_data_quality.py")
        else:
            print("  No data quality issues detected.")
    else:
        print("  [WARNING] No skill files found in data/skills/")
        issues_list = []

    # ── 5. Package Coverage ────────────────────────────────────
    section("5. Package Coverage")

    packages = load_json(PACKAGES_INDEX)
    if packages:
        pkg_list = packages.get("packages", {})
        print(f"  Total packages: {len(pkg_list)}")
        print()
        print(f"  {'Package':<35s} {'Skills':>7s} {'Avg Score':>10s} {'Top Stars':>10s}")
        print(f"  {'-'*35} {'-'*7} {'-'*10} {'-'*10}")
        for pkg_id, pkg in sorted(pkg_list.items()):
            print(
                f"  {pkg_id:<35s} "
                f"{pkg.get('total_skills', 0):>7} "
                f"{pkg.get('avg_score', 0):>10.1f} "
                f"{pkg.get('top_stars', 0):>10,}"
            )
    else:
        print("  [WARNING] data/packages/index.json not found or invalid")

    # ── 6. Recommendations ─────────────────────────────────────
    section("6. Recommendations")

    recommendations = []

    if crawl_state:
        pending_hubs = [k for k, v in crawl_state.get("hubs", {}).items()
                        if v.get("status") == "pending"]
        if pending_hubs:
            recommendations.append(
                f"Crawl pending hubs: {', '.join(pending_hubs)}"
            )

    if stats:
        stats_total = stats.get("total_skills", 0)
        stats_verified = stats.get("verified_skills", 0)
        if stats_total and (stats_verified / stats_total) < 0.25:
            unverified_count = stats_total - stats_verified - stats.get("failed_skills", 0) - stats.get("pending_review", 0)
            recommendations.append(
                f"Verify more skills: {unverified_count:,} unverified "
                f"(only {stats_verified/stats_total*100:.0f}% verified)"
            )

    if string_findings:
        recommendations.append(
            f"Run fix_data_quality.py to normalize {string_findings} findings_summary fields"
        )

    if missing_commit:
        recommendations.append(
            f"Investigate {missing_commit} verified skills with null verified_commit"
        )

    if recommendations:
        for rec in recommendations:
            print(f"  {rec}")
    else:
        print("  No urgent recommendations.")

    # ── 7. Changes Since Last Check ────────────────────────────
    # Build current findings for logging and comparison
    unverified_count = status_counts.get("unverified", 0)

    # Count verification_level from actual skill data (not status_counts)
    vl_counts = {"full_pipeline": 0, "scanner_only": 0, "metadata_only": 0}
    with_agent_audit = 0
    if skill_files:
        for f in skill_files:
            try:
                data = json.loads(f.read_text())
            except (json.JSONDecodeError, OSError):
                continue
            vl = (data.get("verification_level") or "").strip().lower()
            if vl in vl_counts:
                vl_counts[vl] += 1
            if data.get("agent_audit"):
                with_agent_audit += 1

    current_findings = {
        "total_skills": total,
        "verified": verified,
        "unverified": unverified_count,
        "full_pipeline": vl_counts["full_pipeline"],
        "scanner_only": vl_counts["scanner_only"],
        "metadata_only": vl_counts["metadata_only"],
        "with_agent_audit": with_agent_audit,
        "status_breakdown": dict(sorted(status_counts.items(), key=lambda x: -x[1])),
        "star_tiers": star_tiers,
        "issues": issues_list,
    }

    changes = compute_changes(current_findings, previous_entry)

    section("7. Changes Since Last Check")

    if previous_entry:
        prev_ts = previous_entry.get("timestamp", "unknown")
        print(f"  Compared to: {prev_ts}")
        print()
        for sc in changes.get("status_changes", []):
            print(f"  {sc}")
        new_skills = changes.get("new_skills", 0)
        newly_verified = changes.get("newly_verified", 0)
        print(f"\n  Skills delta:      {'+' if new_skills >= 0 else ''}{new_skills}")
        print(f"  Verified delta:    {'+' if newly_verified >= 0 else ''}{newly_verified}")
    else:
        print("  First run — no previous data to compare.")

    # ── Log this run ──────────────────────────────────────────
    append_log_entry(
        log=log,
        check_type="health_check",
        findings=current_findings,
        recommendations=recommendations,
        changes=changes,
    )
    save_log(log)

    print()
    print("=" * 60)
    print("  Dashboard complete. Entry logged to data/skill-manager-log.json")
    print("=" * 60)


if __name__ == "__main__":
    main()
