#!/usr/bin/env python3
"""
Read and update data/crawl-state.json.

Provides helper functions and a CLI for managing crawl state.

Usage:
    python3 crawl_state.py show
    python3 crawl_state.py mark-done mcp_so --total 5421 --pages 115
    python3 crawl_state.py mark-partial claude_skills_hub --total 76 --pages 1
    python3 crawl_state.py add-hub new_hub --url https://example.com --crawler src/crawler/new.py
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
CRAWL_STATE_FILE = PROJECT_ROOT / "data" / "crawl-state.json"


def load_state() -> dict:
    """Load crawl state from data/crawl-state.json."""
    if not CRAWL_STATE_FILE.exists():
        return {"hubs": {}, "last_updated": None}
    return json.loads(CRAWL_STATE_FILE.read_text())


def save_state(state: dict) -> None:
    """Save crawl state to data/crawl-state.json."""
    state["last_updated"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    CRAWL_STATE_FILE.write_text(json.dumps(state, indent=2) + "\n")


def mark_done(hub_key: str, total_collected: int, pages_crawled: int) -> None:
    """Mark a hub as fully crawled."""
    state = load_state()
    if hub_key not in state["hubs"]:
        print(f"[ERROR] Hub '{hub_key}' not found in crawl-state.json", file=sys.stderr)
        sys.exit(1)
    state["hubs"][hub_key]["status"] = "done"
    state["hubs"][hub_key]["total_collected"] = total_collected
    state["hubs"][hub_key]["pages_crawled"] = pages_crawled
    state["hubs"][hub_key]["last_crawl"] = datetime.now(timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    save_state(state)
    print(f"Marked {hub_key} as done (collected: {total_collected}, pages: {pages_crawled})")


def mark_partial(hub_key: str, total_collected: int, pages_crawled: int) -> None:
    """Mark a hub as partially crawled."""
    state = load_state()
    if hub_key not in state["hubs"]:
        print(f"[ERROR] Hub '{hub_key}' not found in crawl-state.json", file=sys.stderr)
        sys.exit(1)
    state["hubs"][hub_key]["status"] = "partial"
    state["hubs"][hub_key]["total_collected"] = total_collected
    state["hubs"][hub_key]["pages_crawled"] = pages_crawled
    state["hubs"][hub_key]["last_crawl"] = datetime.now(timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    save_state(state)
    print(f"Marked {hub_key} as partial (collected: {total_collected}, pages: {pages_crawled})")


def add_hub(
    hub_key: str,
    url: str,
    crawler_path: str,
    notes: str = "",
    trust_level: str = "LOW",
) -> None:
    """Register a new hub in crawl state."""
    state = load_state()
    if hub_key in state["hubs"]:
        print(f"[ERROR] Hub '{hub_key}' already exists in crawl-state.json", file=sys.stderr)
        sys.exit(1)
    state["hubs"][hub_key] = {
        "url": url,
        "crawler": crawler_path,
        "status": "pending",
        "total_collected": 0,
        "pages_crawled": 0,
        "last_crawl": None,
        "trust_level": trust_level,
        "notes": notes,
    }
    save_state(state)
    print(f"Added hub '{hub_key}' ({url})")


def show() -> None:
    """Print formatted crawl state to stdout."""
    state = load_state()
    hubs = state.get("hubs", {})

    if not hubs:
        print("No hubs registered in crawl-state.json")
        return

    print()
    print("=" * 72)
    print("  Crawl State Dashboard")
    print("=" * 72)
    print()
    print(f"  {'Hub':<22s} {'Status':<10s} {'Collected':>10s} {'Pages':>7s} {'Trust':<8s} {'Last Crawl'}")
    print(f"  {'-'*22} {'-'*10} {'-'*10} {'-'*7} {'-'*8} {'-'*20}")

    for key, hub in sorted(hubs.items()):
        last = hub.get("last_crawl") or "never"
        print(
            f"  {key:<22s} {hub.get('status', '?'):<10s} "
            f"{hub.get('total_collected', 0):>10,} "
            f"{hub.get('pages_crawled', 0):>7} "
            f"{hub.get('trust_level', '?'):<8s} "
            f"{last}"
        )

        notes = hub.get("notes", "")
        if notes:
            print(f"  {'':22s} └─ {notes}")

    print()
    print(f"  Last updated: {state.get('last_updated', '?')}")
    print("=" * 72)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Manage data/crawl-state.json"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # show
    subparsers.add_parser("show", help="Display crawl state")

    # mark-done
    done_parser = subparsers.add_parser("mark-done", help="Mark hub as fully crawled")
    done_parser.add_argument("hub", help="Hub key (e.g., mcp_so)")
    done_parser.add_argument("--total", type=int, required=True, help="Total skills collected")
    done_parser.add_argument("--pages", type=int, required=True, help="Pages crawled")

    # mark-partial
    partial_parser = subparsers.add_parser("mark-partial", help="Mark hub as partially crawled")
    partial_parser.add_argument("hub", help="Hub key")
    partial_parser.add_argument("--total", type=int, required=True, help="Total skills collected")
    partial_parser.add_argument("--pages", type=int, required=True, help="Pages crawled")

    # add-hub
    add_parser = subparsers.add_parser("add-hub", help="Register a new hub")
    add_parser.add_argument("hub", help="Hub key (e.g., new_source)")
    add_parser.add_argument("--url", required=True, help="Hub URL")
    add_parser.add_argument("--crawler", required=True, help="Path to crawler file")
    add_parser.add_argument("--notes", default="", help="Description/notes")
    add_parser.add_argument(
        "--trust", default="LOW", choices=["LOW", "MEDIUM", "HIGH"],
        help="Trust level (default: LOW)",
    )

    args = parser.parse_args()

    if args.command == "show":
        show()
    elif args.command == "mark-done":
        mark_done(args.hub, args.total, args.pages)
    elif args.command == "mark-partial":
        mark_partial(args.hub, args.total, args.pages)
    elif args.command == "add-hub":
        add_hub(args.hub, args.url, args.crawler, args.notes, args.trust)


if __name__ == "__main__":
    main()
