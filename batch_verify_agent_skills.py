#!/usr/bin/env python3
"""
batch_verify_agent_skills.py

Batch verification script for unverified agent_skill entries in data/skills/.
Uses metadata-based scoring (no repo cloning) to assign verification_status,
overall_score, risk_level, and findings_summary to each file.

After updating all files, rebuilds the site via:
  python src/build/build_json.py
  python src/build/build_html.py
"""

import json
import os
import glob
import subprocess
import sys

from src.reachability import log_to_skill_manager

# ---------------------------------------------------------------------------
# Scoring constants
# ---------------------------------------------------------------------------
SUSPICIOUS_KEYWORDS = ["hack", "exploit", "bypass", "inject", "steal", "exfiltrate"]
TRUSTED_LANGUAGES = {"typescript", "python", "javascript", "rust", "go"}
TRUSTED_SOURCE = "claude_skills_hub"
STATUS_TAG_PREFIX = "status-"
ALLOWED_STATUSES = {"pass", "manual_review", "fail", "unverified", "updated_unverified"}


def normalize_status(value: str | None) -> str:
    """Normalize verification status labels to canonical values."""
    if not value:
        return "unverified"
    raw = str(value).strip().lower()
    aliases = {
        "verified": "pass",
        "approved": "pass",
        "failed": "fail",
        "invalid": "fail",
        "review": "manual_review",
        "flagged": "manual_review",
        "updated-unverified": "updated_unverified",
    }
    normalized = aliases.get(raw, raw)
    return normalized if normalized in ALLOWED_STATUSES else "unverified"


def sync_status_tag(data: dict, status: str | None) -> None:
    """Ensure exactly one status-* tag matches verification_status."""
    tags_raw = data.get("tags", [])
    tags = [str(tag) for tag in tags_raw] if isinstance(tags_raw, list) else []
    tags = [tag for tag in tags if not tag.startswith(STATUS_TAG_PREFIX)]
    tags.append(f"status-{normalize_status(status)}")
    data["tags"] = list(dict.fromkeys(tags))


def score_skill(data: dict) -> tuple[int, str, str, str]:
    """
    Apply the metadata-based heuristic and return
    (overall_score, verification_status, risk_level, findings_summary).
    """
    notes = []
    score = 70

    # --- Stars ---
    stars = data.get("stars", 0) or 0
    if stars >= 1000:
        score += 15
        notes.append(f"stars={stars} (>=1000, +15)")
    elif stars >= 100:
        score += 10
        notes.append(f"stars={stars} (>=100, +10)")
    elif stars >= 10:
        score += 5
        notes.append(f"stars={stars} (>=10, +5)")
    elif stars == 0:
        score -= 10
        notes.append("stars=0 (-10)")
    else:
        notes.append(f"stars={stars}")

    # --- License ---
    license_val = data.get("license", "") or ""
    if license_val.strip():
        score += 5
        notes.append(f"license='{license_val}' (+5)")
    else:
        notes.append("no license detected")

    # --- Owner ---
    owner = data.get("owner", "") or ""
    if owner.strip():
        score += 3
        notes.append(f"owner='{owner}' (+3)")
    else:
        notes.append("no owner")

    # --- Primary language ---
    lang = data.get("primary_language", "") or ""
    lang_norm = str(lang).strip().lower()
    if lang_norm in TRUSTED_LANGUAGES:
        score += 5
        notes.append(f"primary_language='{lang}' (+5)")
    else:
        notes.append(f"primary_language='{lang}'")

    # --- Suspicious keywords in description ---
    description = (data.get("description", "") or "").lower()
    found_keywords = [kw for kw in SUSPICIOUS_KEYWORDS if kw in description]
    forced_high_risk = False
    if found_keywords:
        score -= 20
        forced_high_risk = True
        notes.append(f"suspicious keywords in description: {found_keywords} (-20, risk_level forced to 'high')")

    # --- Trusted source ---
    source_hub = data.get("source_hub", "") or ""
    if source_hub == TRUSTED_SOURCE:
        score += 5
        notes.append(f"source_hub='{source_hub}' (+5)")
    else:
        notes.append(f"source_hub='{source_hub}'")

    # --- Monorepo child ---
    is_monorepo_child = data.get("is_monorepo_child", False)
    if is_monorepo_child:
        score -= 5
        notes.append("is_monorepo_child=True (-5)")

    # --- Cap score ---
    score = max(0, min(100, score))

    # --- Assign verification_status ---
    if score >= 70:
        verification_status = "pass"
    elif score >= 50:
        verification_status = "manual_review"
    else:
        verification_status = "fail"

    # --- Assign risk_level ---
    if forced_high_risk:
        risk_level = "high"
    elif score >= 80:
        risk_level = "low"
    elif score >= 60:
        risk_level = "medium"
    elif score >= 40:
        risk_level = "high"
    else:
        risk_level = "critical"

    # --- Build findings_summary ---
    findings_summary = (
        f"Metadata-based verification. Score={score}. Signals: {'; '.join(notes)}. "
        f"Status: {verification_status}. Risk: {risk_level}."
    )

    return score, verification_status, risk_level, findings_summary


def main():
    project_root = os.path.dirname(os.path.abspath(__file__))
    skills_dir = os.path.join(project_root, "data", "skills")
    pattern = os.path.join(skills_dir, "*.json")

    all_files = sorted(glob.glob(pattern))
    print(f"Found {len(all_files)} total skill files in {skills_dir}")

    processed = 0
    skipped_wrong_type = 0
    skipped_already_verified = 0
    results = {"pass": 0, "manual_review": 0, "fail": 0}

    for filepath in all_files:
        try:
            with open(filepath, "r", encoding="utf-8") as fp:
                data = json.load(fp)
        except Exception as exc:
            print(f"  [ERROR] Could not read {filepath}: {exc}", file=sys.stderr)
            continue

        # Skip non-agent_skill entries
        if data.get("skill_type") != "agent_skill":
            skipped_wrong_type += 1
            continue

        # Skip already-verified entries
        if data.get("verification_status") != "unverified":
            skipped_already_verified += 1
            continue

        # Apply scoring heuristic
        score, verification_status, risk_level, findings_summary = score_skill(data)

        # Update the record in place
        data["verification_status"] = verification_status
        data["overall_score"] = score
        data["risk_level"] = risk_level
        data["findings_summary"] = findings_summary
        data["verification_level"] = "metadata_only"
        sync_status_tag(data, verification_status)

        try:
            with open(filepath, "w", encoding="utf-8") as fp:
                json.dump(data, fp, indent=2, ensure_ascii=False)
                fp.write("\n")
        except Exception as exc:
            print(f"  [ERROR] Could not write {filepath}: {exc}", file=sys.stderr)
            continue

        results[verification_status] += 1
        processed += 1

    # --- Summary ---
    print()
    print("=" * 60)
    print("VERIFICATION COMPLETE")
    print("=" * 60)
    print(f"Files processed (agent_skill + unverified): {processed}")
    print(f"  pass:          {results['pass']}")
    print(f"  manual_review: {results['manual_review']}")
    print(f"  fail:          {results['fail']}")
    print(f"Skipped (wrong type):      {skipped_wrong_type}")
    print(f"Skipped (already verified): {skipped_already_verified}")
    print()

    # --- Rebuild site ---
    build_modules = [
        ("src.build.build_json", "build_json.py"),
        ("src.build.build_html", "build_html.py"),
    ]
    build_results: dict[str, int] = {}

    for module, script_name in build_modules:
        print(f"Running {script_name} ...")
        result = subprocess.run(
            [sys.executable, "-m", module],
            cwd=project_root,
            capture_output=False,
        )
        if result.returncode == 0:
            print(f"  {script_name} completed successfully.")
        else:
            print(f"  [WARNING] {script_name} exited with code {result.returncode}.", file=sys.stderr)
        build_results[script_name] = result.returncode

    try:
        log_to_skill_manager(
            check_type="verification_run",
            findings={
                "script": "batch_verify_agent_skills.py",
                "mode": "metadata_only",
                "total_files": len(all_files),
                "processed": processed,
                "pass": results["pass"],
                "manual_review": results["manual_review"],
                "fail": results["fail"],
                "skipped_wrong_type": skipped_wrong_type,
                "skipped_already_verified": skipped_already_verified,
                "build_return_codes": build_results,
            },
        )
    except Exception as exc:
        print(
            f"[WARNING] Unable to write skill-manager verification_run log: {exc}",
            file=sys.stderr,
        )

    print()
    print("Done.")


if __name__ == "__main__":
    main()
