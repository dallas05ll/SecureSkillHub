#!/usr/bin/env python3
"""
Bulk re-tag integrations skills with more specific sub-tags.

Finds all skills tagged `integ` or `integrations` that lack a more-specific
`integrations-*` sub-tag, then applies keyword-based sub-tags.

Modes:
  --dry-run   (default) Print counts and samples without writing
  --execute   Apply changes and log to skill-manager-log.json

Usage:
    python3 scripts/enrich/retag_integ_bulk.py --dry-run
    python3 scripts/enrich/retag_integ_bulk.py --execute
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
SKILLS_DIR = PROJECT_ROOT / "data" / "skills"
SM_LOG = PROJECT_ROOT / "data" / "skill-manager-log.json"

# ---------------------------------------------------------------------------
# Keyword rules: (sub_tag_id, keyword_list)
# Order matters — first match wins for reporting, but ALL matches are applied.
# ---------------------------------------------------------------------------
INTEG_RULES: list[tuple[str, list[str]]] = [
    # github/gitlab: match as product names, not as URL domains.
    # "github" in name/desc means the skill is about GitHub the platform.
    ("integrations-github",    ["github api", "github integration", "github actions",
                                 "github cli", "github issues", "github pr",
                                 "github pull", "github repo", "github tool",
                                 "gitlab api", "gitlab integration", "gitlab ci",
                                 "bitbucket api", "bitbucket integration"]),
    ("integrations-messaging", ["slack", "discord", "telegram", "microsoft teams",
                                 " teams ", "matrix chat", "whatsapp", "mattermost",
                                 "zulip", "rocketchat"]),
    ("data-db",                ["database", " sql ", "postgres", "postgresql",
                                 "mysql", "mongodb", "sqlite", "redis", "supabase",
                                 "firebase", "firestore", "dynamodb", "cassandra",
                                 "mariadb", "cockroachdb"]),
    ("integrations-cloud",     [" aws ", "amazon web services", " azure ",
                                 "microsoft azure", " gcp ", "google cloud"]),
    # "email" alone is too broad (many tools *find* emails without being email tools).
    # Require specific email service names or action phrases.
    ("productivity-email",     ["gmail", " smtp", "outlook mail", "sendgrid",
                                 "mailgun", "mailchimp", "send email", "email client",
                                 "email integration", "email server", "email api"]),
    ("integrations-crm",       ["salesforce", "hubspot", " crm ", "pipedrive",
                                 "zoho crm"]),
    ("integrations-payment",   ["stripe", "paypal", "payment", "billing",
                                 "shopify", "woocommerce", "square payment",
                                 "checkout"]),
    ("integrations-social",    ["twitter", "x.com", "linkedin", "instagram",
                                 "youtube", "reddit", "bluesky", "facebook",
                                 "tiktok", "pinterest"]),
    ("integrations-notion",    ["notion"]),
    ("integrations-jira",      ["jira", "confluence", "atlassian"]),
    ("integrations-google",    ["google drive", "google docs", "google sheets",
                                 "google calendar", "google workspace",
                                 "gsuite", "g suite"]),
]

# Tags that indicate a skill already has a more-specific integrations sub-tag
SPECIFIC_INTEG_TAGS: set[str] = {
    "integrations-github", "integrations-messaging", "integrations-cloud",
    "integrations-cloud-aws", "integrations-cloud-azure", "integrations-cloud-gcp",
    "integrations-crm", "integrations-payment", "integrations-social",
    "integrations-notion", "integrations-jira", "integrations-google",
    "integrations-slack",
    # abbreviated forms also count
    "integ-cloud", "integ-cloud-aws", "integ-cloud-azure", "integ-cloud-gcp",
    "integ-crm", "integ-payment", "integ-social",
}


def has_integ_base(tags: list[str]) -> bool:
    """Return True if skill has generic integ/integrations tag."""
    return bool({"integ", "integrations"} & set(tags))


def has_specific_integ(tags: list[str]) -> bool:
    """Return True if skill already has a specific integrations sub-tag."""
    return bool(SPECIFIC_INTEG_TAGS & set(tags))


def match_rules(text: str, rules: list[tuple[str, list[str]]]) -> list[str]:
    """Return all sub-tag IDs whose keywords appear in text."""
    matches = []
    for tag_id, keywords in rules:
        for kw in keywords:
            if kw in text:
                matches.append(tag_id)
                break
    return matches


def load_skill(path: Path) -> dict[str, Any] | None:
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return None


def save_skill(path: Path, data: dict[str, Any]) -> None:
    with open(path, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")


def log_to_sm(entry: dict[str, Any]) -> None:
    """Append to skill-manager-log.json (supports both list and dict-with-entries format)."""
    try:
        if SM_LOG.exists():
            with open(SM_LOG) as f:
                log = json.load(f)
        else:
            log = {"log_version": "1.0", "entries": []}

        if isinstance(log, list):
            log.append(entry)
        elif isinstance(log, dict):
            if "entries" not in log:
                log["entries"] = []
            log["entries"].append(entry)
        else:
            log = [entry]

        with open(SM_LOG, "w") as f:
            json.dump(log, f, indent=2, ensure_ascii=False)
            f.write("\n")
    except Exception as exc:
        print(f"  [warn] Could not write SM log: {exc}", file=sys.stderr)


def run(execute: bool) -> None:
    mode = "EXECUTE" if execute else "DRY-RUN"
    print(f"\n=== retag_integ_bulk.py  [{mode}] ===\n")

    all_skills = sorted(SKILLS_DIR.glob("*.json"))
    print(f"Total skill files: {len(all_skills)}")

    candidates: list[tuple[Path, dict[str, Any]]] = []
    for path in all_skills:
        data = load_skill(path)
        if data is None:
            continue
        tags = data.get("tags", [])
        if has_integ_base(tags) and not has_specific_integ(tags):
            candidates.append((path, data))

    print(f"Candidates (integ base, no specific sub-tag): {len(candidates)}\n")

    # Tally results
    tag_counts: dict[str, int] = {}
    changed: list[dict[str, Any]] = []
    unchanged: int = 0

    for path, data in candidates:
        tags = data.get("tags", [])
        name = (data.get("name") or "").lower()
        desc = (data.get("description") or "").lower()
        # NOTE: repo_url is intentionally excluded — it always contains "github.com"
        # which would cause every skill to be tagged integrations-github.
        # Match only on human-readable name + description.
        text = f"{name} {desc}"

        new_tags = match_rules(text, INTEG_RULES)
        if not new_tags:
            unchanged += 1
            continue

        added = [t for t in new_tags if t not in tags]
        if not added:
            unchanged += 1
            continue

        for t in added:
            tag_counts[t] = tag_counts.get(t, 0) + 1

        changed.append({
            "id": data.get("id", path.stem),
            "name": data.get("name", ""),
            "added": added,
            "existing_tags": tags[:5],
        })

        if execute:
            data["tags"] = sorted(set(tags + added))
            save_skill(path, data)

    # ---- Report ----
    print(f"Skills that will be updated: {len(changed)}")
    print(f"Skills with no keyword match: {unchanged}\n")

    print("Sub-tags that will be added (counts):")
    for tag, count in sorted(tag_counts.items(), key=lambda x: -x[1]):
        print(f"  {tag:40s}  {count:>4}")

    print("\nSample changes (first 20):")
    for item in changed[:20]:
        print(f"  [{item['id'][:40]}]  {item['name'][:50]}")
        print(f"    + {item['added']}")

    # ---- SM log ----
    log_entry = {
        "type": "retag_integ_bulk",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "mode": mode,
        "candidates": len(candidates),
        "updated": len(changed) if execute else 0,
        "dry_run_projected": len(changed),
        "tag_counts": tag_counts,
    }
    if execute:
        log_to_sm(log_entry)
        print(f"\nWrote {len(changed)} skill files. Logged to skill-manager-log.json.")
    else:
        print(f"\n[dry-run] No files written. Run with --execute to apply.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Bulk re-tag integrations skills.")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--dry-run", action="store_true", default=True,
                       help="Preview changes without writing (default)")
    group.add_argument("--execute", action="store_true",
                       help="Apply changes and write skill files")
    args = parser.parse_args()
    run(execute=args.execute)


if __name__ == "__main__":
    main()
