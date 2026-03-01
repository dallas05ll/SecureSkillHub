#!/usr/bin/env python3
"""
Batch repo reachability checker.

Tests all skills' GitHub repos using `git ls-remote` and tags unreachable
ones with `repo_unavailable`.

Usage:
    python3 check_reachability.py                    # Check all skills
    python3 check_reachability.py --limit 50         # Check first 50 only
    python3 check_reachability.py --only-untagged     # Skip already-tagged ones
    python3 check_reachability.py --report            # Just print current stats
    python3 check_reachability.py --workers 20        # Concurrent workers (default: 10)
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from src.reachability import (
    TAG_CLONE_FAILURE,
    TAG_NOT_REACHABLE,
    TAG_UNAVAILABLE,
    check_repo,
    log_to_skill_manager,
    mark_unavailable,
)

SKILLS_DIR = Path("data/skills")
LOG_FILE = Path("data/reachability-check.json")


def load_skills() -> list[dict]:
    """Load all skill JSON files."""
    skills = []
    for path in sorted(SKILLS_DIR.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            data["_path"] = str(path)
            skills.append(data)
        except (json.JSONDecodeError, OSError):
            continue
    return skills


def tag_skill_unavailable(skill_data: dict, error_msg: str | None = None) -> bool:
    """Add repo_unavailable tag to a skill and write to disk. Returns True if modified."""
    was_unavailable = TAG_UNAVAILABLE in skill_data.get("tags", []) or TAG_NOT_REACHABLE in skill_data.get("tags", [])
    had_clone_failure = TAG_CLONE_FAILURE in skill_data.get("tags", [])

    mark_unavailable(skill_data, error_msg)

    modified = not was_unavailable or had_clone_failure
    if modified:
        path = Path(skill_data["_path"])
        write_data = {k: v for k, v in skill_data.items() if k != "_path"}
        path.write_text(
            json.dumps(write_data, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    return modified


def remove_unavailable_tag(skill_data: dict) -> bool:
    """Remove repo_unavailable tag from a skill that is now reachable."""
    tags = skill_data.get("tags", [])
    modified = False

    if TAG_UNAVAILABLE in tags:
        tags.remove(TAG_UNAVAILABLE)
        modified = True
    if TAG_CLONE_FAILURE in tags:
        tags.remove(TAG_CLONE_FAILURE)
        modified = True
    if TAG_NOT_REACHABLE in tags:
        tags.remove(TAG_NOT_REACHABLE)
        modified = True

    if modified:
        skill_data["tags"] = tags
        skill_data["repo_status"] = "reachable"
        skill_data["repo_check_date"] = datetime.now(timezone.utc).isoformat()
        skill_data.pop("repo_check_error", None)
        path = Path(skill_data["_path"])
        write_data = {k: v for k, v in skill_data.items() if k != "_path"}
        path.write_text(
            json.dumps(write_data, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    return modified


def print_report(skills: list[dict]) -> None:
    """Print current reachability stats."""
    unavailable = [s for s in skills if TAG_UNAVAILABLE in s.get("tags", [])]
    not_reachable = [s for s in skills if TAG_NOT_REACHABLE in s.get("tags", [])]
    clone_fail = [s for s in skills if TAG_CLONE_FAILURE in s.get("tags", [])]
    has_check = [s for s in skills if s.get("repo_check_date")]

    print(f"\n{'='*60}")
    print(f"  Repo Reachability Report")
    print(f"{'='*60}")
    print(f"  Total skills:            {len(skills):>6}")
    print(f"  Tagged repo_unavailable: {len(unavailable):>6}")
    print(f"  Tagged not_reachable:    {len(not_reachable):>6}")
    print(f"  Tagged clone_failure:    {len(clone_fail):>6} (legacy)")
    print(f"  Previously checked:      {len(has_check):>6}")
    print(f"  Never checked:           {len(skills) - len(has_check):>6}")
    print(f"{'='*60}\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Check repo reachability for all skills")
    parser.add_argument("--limit", type=int, default=0, help="Max skills to check (0=all)")
    parser.add_argument("--only-untagged", action="store_true", help="Skip already-tagged skills")
    parser.add_argument("--report", action="store_true", help="Print stats only, no checks")
    parser.add_argument("--workers", type=int, default=10, help="Concurrent workers (default: 10)")
    parser.add_argument("--timeout", type=int, default=20, help="Per-repo timeout in seconds")
    parser.add_argument("--recheck", action="store_true", help="Re-check previously unavailable repos")
    args = parser.parse_args()

    skills = load_skills()
    print(f"Loaded {len(skills)} skills")

    if args.report:
        print_report(skills)
        return

    # Filter skills to check
    to_check = skills
    if args.only_untagged:
        to_check = [
            s for s in skills
            if TAG_UNAVAILABLE not in s.get("tags", [])
            and TAG_NOT_REACHABLE not in s.get("tags", [])
            and TAG_CLONE_FAILURE not in s.get("tags", [])
        ]
        print(f"Filtering to {len(to_check)} untagged skills")
    elif args.recheck:
        to_check = [
            s for s in skills
            if TAG_UNAVAILABLE in s.get("tags", [])
            or TAG_NOT_REACHABLE in s.get("tags", [])
            or TAG_CLONE_FAILURE in s.get("tags", [])
        ]
        print(f"Re-checking {len(to_check)} previously unavailable skills")

    if args.limit > 0:
        to_check = to_check[: args.limit]
        print(f"Limited to {len(to_check)} skills")

    if not to_check:
        print("No skills to check.")
        return

    # Run checks in parallel
    results = {"reachable": 0, "unreachable": 0, "tagged": 0, "untagged": 0, "errors": []}
    start_time = time.time()
    total = len(to_check)

    print(f"\nChecking {total} repos with {args.workers} workers...\n")

    def check_one(skill: dict) -> tuple[dict, dict]:
        repo_url = skill.get("repo_url", "")
        if not repo_url:
            return skill, {"reachable": False, "returncode": -1, "error": "no repo_url"}
        return skill, check_repo(repo_url, timeout=args.timeout)

    checked = 0
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {executor.submit(check_one, s): s for s in to_check}

        for future in as_completed(futures):
            skill, result = future.result()
            checked += 1

            if result["reachable"]:
                results["reachable"] += 1
                # If previously tagged as unavailable, remove the tag
                if remove_unavailable_tag(skill):
                    results["untagged"] += 1
                    print(f"  [{checked}/{total}] RECOVERED: {skill.get('id', '?')}")
            else:
                results["unreachable"] += 1
                if tag_skill_unavailable(skill, result.get("error")):
                    results["tagged"] += 1
                    print(f"  [{checked}/{total}] UNREACHABLE: {skill.get('id', '?')} - {result.get('error', '?')[:80]}")

            # Progress every 100
            if checked % 100 == 0:
                elapsed = time.time() - start_time
                rate = checked / elapsed if elapsed > 0 else 0
                eta = (total - checked) / rate if rate > 0 else 0
                print(f"\n  Progress: {checked}/{total} ({rate:.1f}/s, ETA: {eta:.0f}s)\n")

    elapsed = time.time() - start_time

    # Save log
    log_entry = {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "total_checked": total,
        "reachable": results["reachable"],
        "unreachable": results["unreachable"],
        "newly_tagged": results["tagged"],
        "recovered": results["untagged"],
        "elapsed_seconds": round(elapsed, 1),
    }

    log_data = []
    if LOG_FILE.exists():
        try:
            log_data = json.loads(LOG_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            log_data = []
    log_data.append(log_entry)
    LOG_FILE.write_text(json.dumps(log_data, indent=2) + "\n", encoding="utf-8")

    # Also log to skills manager
    log_to_skill_manager(
        check_type="reachability_run",
        findings=log_entry,
        recommendations=(
            [f"High unreachable rate ({results['unreachable']}/{total}) — consider reviewing collection quality"]
            if results["unreachable"] > total * 0.3
            else None
        ),
    )

    print(f"\n{'='*60}")
    print(f"  Results ({elapsed:.1f}s)")
    print(f"{'='*60}")
    print(f"  Checked:        {total:>6}")
    print(f"  Reachable:      {results['reachable']:>6}")
    print(f"  Unreachable:    {results['unreachable']:>6}")
    print(f"  Newly tagged:   {results['tagged']:>6}")
    print(f"  Recovered:      {results['untagged']:>6}")
    print(f"{'='*60}")
    print(f"  Log saved to: {LOG_FILE}")


if __name__ == "__main__":
    main()
