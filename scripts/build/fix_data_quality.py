#!/usr/bin/env python3
"""
One-time data quality migration for SecureSkillHub.

Fixes:
  (a) Populate trust_level from source_hub mapping
  (b) Clear bogus install_url (was copy of repo_url)
  (c) Normalize verification_status to schema enum values
  (d) Backfill scan_date from file mtime for verified/reviewed skills
  (e) Normalize findings_summary (string→dict, null→dict)
"""

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
SKILLS_DIR = PROJECT_ROOT / "data" / "skills"

# source_hub → trust_level mapping (matches TrustLevel enum in schemas.py)
SOURCE_TRUST: dict[str, str] = {
    "claude_skills_hub": "medium",
    "glama": "medium",
    "awesome_list": "medium",
    "skillhub": "medium",
    "mcp_so": "low",
    "skillsmp": "low",
    "skills_sh": "low",
    "skills_directory": "low",
    "github_search": "low",
    "pulsemcp": "low",
    "smithery": "low",
}

# verification_status normalization (matches STATUS_ALIASES in build_json.py)
STATUS_NORMALIZE: dict[str, str] = {
    "verified": "pass",
    "approved": "pass",
    "failed": "fail",
    "invalid": "fail",
    "review": "manual_review",
    "flagged": "manual_review",
    "updated-unverified": "updated_unverified",
}
VALID_STATUSES = {"pass", "fail", "manual_review", "unverified", "updated_unverified"}

# Statuses that should have a scan_date
SCANNED_STATUSES = {"pass", "fail", "manual_review", "updated_unverified"}


def fix_skill(filepath: Path) -> dict[str, int]:
    """Fix one skill file. Returns dict of fix counts."""
    counts = {
        "trust_level": 0,
        "install_url": 0,
        "status": 0,
        "scan_date": 0,
        "findings": 0,
    }

    with open(filepath) as f:
        data = json.load(f)

    changed = False

    # (a) trust_level from source_hub
    source = data.get("source_hub", "")
    expected_trust = SOURCE_TRUST.get(source, "dangerous")
    if data.get("trust_level") != expected_trust:
        data["trust_level"] = expected_trust
        changed = True
        counts["trust_level"] = 1

    # (b) Clear bogus install_url
    install = data.get("install_url", "")
    repo = data.get("repo_url", "")
    if install and install == repo:
        data["install_url"] = ""
        changed = True
        counts["install_url"] = 1
    elif install == "":
        pass  # already correct
    elif not install:
        data["install_url"] = ""
        changed = True
        counts["install_url"] = 1

    # (c) Normalize verification_status
    status = data.get("verification_status", "")
    if status and status not in VALID_STATUSES:
        normalized = STATUS_NORMALIZE.get(status.lower(), "unverified")
        data["verification_status"] = normalized
        changed = True
        counts["status"] = 1

    # (d) Backfill scan_date from file mtime
    final_status = data.get("verification_status", "unverified")
    if final_status in SCANNED_STATUSES and not data.get("scan_date"):
        mtime = os.path.getmtime(filepath)
        data["scan_date"] = datetime.fromtimestamp(mtime, tz=timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        changed = True
        counts["scan_date"] = 1

    # (e) Normalize findings_summary
    fs = data.get("findings_summary")
    if fs is None:
        data["findings_summary"] = {}
        changed = True
        counts["findings"] = 1
    elif isinstance(fs, str):
        data["findings_summary"] = {"notes": fs}
        changed = True
        counts["findings"] = 1

    if changed:
        with open(filepath, "w") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.write("\n")

    return counts


def main() -> None:
    if not SKILLS_DIR.is_dir():
        print(f"ERROR: {SKILLS_DIR} not found", file=sys.stderr)
        sys.exit(1)

    files = sorted(SKILLS_DIR.glob("*.json"))
    print(f"Processing {len(files)} skill files...")

    totals = {
        "trust_level": 0,
        "install_url": 0,
        "status": 0,
        "scan_date": 0,
        "findings": 0,
    }

    for filepath in files:
        counts = fix_skill(filepath)
        for k, v in counts.items():
            totals[k] += v

    print(f"\nResults:")
    print(f"  trust_level set:      {totals['trust_level']}")
    print(f"  install_url cleared:  {totals['install_url']}")
    print(f"  status normalized:    {totals['status']}")
    print(f"  scan_date backfilled: {totals['scan_date']}")
    print(f"  findings normalized:  {totals['findings']}")
    print(f"\nDone.")


if __name__ == "__main__":
    main()
