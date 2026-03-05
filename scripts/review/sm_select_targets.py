#!/usr/bin/env python3
"""Skills Manager (SM) target selection for verification.

SM selects which skills VM should verify next, based on:
  1. Priority tiers (high-star first)
  2. Category coverage (spread across domains)
  3. Avoid repo_unavailable
  4. Prefer skills with installs: tags (real usage signal)
  5. Balance MCP servers vs agent skills

Usage:
    python3 scripts/review/sm_select_targets.py --limit 100
    python3 scripts/review/sm_select_targets.py --limit 100 --output-ids
    python3 scripts/review/sm_select_targets.py --limit 100 --strategy stars
    python3 scripts/review/sm_select_targets.py --limit 100 --strategy balanced
    python3 scripts/review/sm_select_targets.py --limit 100 --type agent   # Agent skills only
    python3 scripts/review/sm_select_targets.py --limit 100 --type mcp     # MCP servers only

Output: prints selected skill IDs (comma-separated with --output-ids,
        or detailed table without).

The --output-ids flag produces a string suitable for piping to VM:
    VM_TARGETS=$(python3 scripts/review/sm_select_targets.py --limit 100 --output-ids)
    python3 scripts/verify/run_verify_strict_5agent.py --skill-ids "$VM_TARGETS"
"""

import argparse
import collections
import json
import sys
from pathlib import Path

SKILLS_DIR = Path("data/skills")
SM_LOG = Path("data/skill-manager-log.json")


def is_agent_skill(skill: dict) -> bool:
    """Check if a skill is an agent skill (vs MCP server)."""
    return "agent-skills" in (skill.get("tags") or [])


def load_unverified(skill_type: str | None = None) -> list[dict]:
    """Load all unverified skills with GitHub repos.

    Args:
        skill_type: Filter by type — "agent" for agent skills, "mcp" for MCP servers, None for all.
    """
    candidates = []
    for path in sorted(SKILLS_DIR.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        status = str(data.get("verification_status", "unverified")).lower()
        if status not in ("unverified", "updated_unverified"):
            continue
        repo = str(data.get("repo_url", ""))
        if not repo.startswith("https://github.com/"):
            continue
        tags = data.get("tags", [])
        if isinstance(tags, list) and ("repo_unavailable" in tags or "clone_failure" in tags):
            continue
        # Type filter
        if skill_type == "agent" and not is_agent_skill(data):
            continue
        if skill_type == "mcp" and is_agent_skill(data):
            continue
        candidates.append(data)
    return candidates


def priority_score(skill: dict) -> int:
    """Unified priority score: stars for MCP, installs for agent skills.

    Normalization: installs and stars are on different scales.
    Top MCP: 350K stars. Top agent: 243K installs.
    We treat them as equivalent signals — both indicate real usage.
    """
    stars = int(skill.get("stars") or 0)
    installs = int(skill.get("installs") or 0)
    return max(stars, installs)


def strategy_stars(candidates: list[dict], limit: int) -> list[dict]:
    """Pure priority-based selection (stars for MCP, installs for agent skills)."""
    candidates.sort(key=lambda d: (-priority_score(d), str(d.get("id", ""))))
    return candidates[:limit]


def strategy_balanced(candidates: list[dict], limit: int) -> list[dict]:
    """Balanced selection: mix of high-star, category coverage, and type diversity.

    Allocation:
      - 60% highest-star (across all categories)
      - 25% category coverage (round-robin across under-represented domains)
      - 15% type balance (ensure MCP/agent-skill mix)
    """
    star_count = int(limit * 0.60)
    category_count = int(limit * 0.25)
    type_count = limit - star_count - category_count

    selected_ids = set()
    selected = []

    def add(skill):
        sid = skill.get("id", "")
        if sid not in selected_ids:
            selected_ids.add(sid)
            selected.append(skill)
            return True
        return False

    # --- Tier 1: Highest priority (stars for MCP, installs for agent skills) ---
    by_priority = sorted(candidates, key=lambda d: (-priority_score(d), str(d.get("id", ""))))
    for s in by_priority:
        if len(selected) >= star_count:
            break
        add(s)

    # --- Tier 2: Category round-robin ---
    # Group remaining by top-level domain tag
    domain_buckets: dict[str, list[dict]] = collections.defaultdict(list)
    for s in candidates:
        if s.get("id") in selected_ids:
            continue
        tags = s.get("tags", [])
        top_domain = "other"
        for t in tags:
            if isinstance(t, str) and t in ("dev", "data", "integ", "util", "security", "prod"):
                top_domain = t
                break
        domain_buckets[top_domain].append(s)

    # Sort each bucket by stars
    for domain in domain_buckets:
        domain_buckets[domain].sort(key=lambda d: (-int(d.get("stars") or 0),))

    # Round-robin across domains
    domain_keys = sorted(domain_buckets.keys())
    added = 0
    idx = 0
    max_rounds = category_count * 2  # safety limit
    rounds = 0
    while added < category_count and rounds < max_rounds:
        domain = domain_keys[idx % len(domain_keys)]
        bucket = domain_buckets[domain]
        if bucket:
            s = bucket.pop(0)
            if add(s):
                added += 1
        idx += 1
        rounds += 1

    # --- Tier 3: Type balance ---
    # Check current MCP vs agent-skill ratio in selected
    mcp_count = sum(1 for s in selected if "agent-skills" not in (s.get("tags") or []))
    agent_count = sum(1 for s in selected if "agent-skills" in (s.get("tags") or []))

    # Prefer whichever type is under-represented
    prefer_agent = mcp_count > agent_count
    remaining = [s for s in candidates if s.get("id") not in selected_ids]
    if prefer_agent:
        remaining.sort(key=lambda d: (
            0 if "agent-skills" in (d.get("tags") or []) else 1,
            -int(d.get("stars") or 0),
        ))
    else:
        remaining.sort(key=lambda d: (
            1 if "agent-skills" in (d.get("tags") or []) else 0,
            -int(d.get("stars") or 0),
        ))

    for s in remaining:
        if len(selected) >= limit:
            break
        add(s)

    return selected[:limit]


def log_selection(selected: list[dict], strategy: str, total_unverified: int, skill_type: str | None = None):
    """Log SM selection to skill-manager-log.json."""
    import datetime

    entry = {
        "type": "sm_target_selection",
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "strategy": strategy,
        "skill_type_filter": skill_type or "all",
        "selected_count": len(selected),
        "total_unverified": total_unverified,
        "priority_range": f"{min(priority_score(s) for s in selected)}-{max(priority_score(s) for s in selected)}" if selected else "0-0",
        "selected_ids": [s.get("id", "") for s in selected],
    }

    log_path = SM_LOG
    if log_path.exists():
        log = json.loads(log_path.read_text(encoding="utf-8"))
    else:
        log = []
    if isinstance(log, list):
        log.append(entry)
    else:
        log.setdefault("entries", []).append(entry)
    log_path.write_text(json.dumps(log, indent=2), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description="SM target selection for verification")
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--strategy", choices=["stars", "balanced"], default="balanced",
                        help="Selection strategy: stars (pure star-sort) or balanced (category+type coverage)")
    parser.add_argument("--output-ids", action="store_true",
                        help="Output comma-separated IDs only (for piping to VM)")
    parser.add_argument("--type", choices=["mcp", "agent"], default=None,
                        help="Filter by skill type: mcp (MCP servers) or agent (agent skills)")
    parser.add_argument("--no-log", action="store_true",
                        help="Skip logging to skill-manager-log.json")
    args = parser.parse_args()

    candidates = load_unverified(skill_type=args.type)

    if args.strategy == "stars":
        selected = strategy_stars(candidates, args.limit)
    else:
        selected = strategy_balanced(candidates, args.limit)

    if not args.no_log:
        log_selection(selected, args.strategy, len(candidates), skill_type=args.type)

    if args.output_ids:
        print(",".join(s.get("id", "") for s in selected))
    else:
        type_label = f", type: {args.type}" if args.type else ""
        print(f"SM Target Selection: {len(selected)}/{len(candidates)} unverified (strategy: {args.strategy}{type_label})")
        print(f"{'='*80}")

        # Stats
        prios = [priority_score(s) for s in selected]
        tags_counter = collections.Counter()
        types = collections.Counter()
        for s in selected:
            stags = s.get("tags", [])
            if is_agent_skill(s):
                types["agent_skill"] += 1
            else:
                types["mcp_server"] += 1
            for t in stags:
                if isinstance(t, str) and t in ("dev", "data", "integ", "util", "security", "prod"):
                    tags_counter[t] += 1

        print(f"  Priority range: {min(prios)}-{max(prios)} (avg {sum(prios)/len(prios):.0f})")
        print(f"  Types: {dict(types)}")
        print(f"  Domains: {dict(tags_counter.most_common())}")

        # --- Separate tier breakdowns ---
        tier_labels = ["S (10K+)", "A (1K-10K)", "B (100-999)", "C (10-99)", "D (1-9)", "E (0)"]
        tier_bounds = [(10000, None), (1000, 10000), (100, 1000), (10, 100), (1, 10), (0, 1)]

        def get_tier(p):
            for label, (lo, hi) in zip(tier_labels, tier_bounds):
                if hi is None:
                    if p >= lo:
                        return label
                elif lo <= p < hi:
                    return label
            return "E (0)"

        mcp_sel = [s for s in selected if not is_agent_skill(s)]
        agent_sel = [s for s in selected if is_agent_skill(s)]

        for label, subset, metric in [("MCP Servers", mcp_sel, "stars"), ("Agent Skills", agent_sel, "installs")]:
            if not subset:
                continue
            tier_counts = collections.Counter(get_tier(priority_score(s)) for s in subset)
            print(f"\n  {label} ({len(subset)} selected, priority={metric}):")
            for t in tier_labels:
                c = tier_counts.get(t, 0)
                if c > 0:
                    print(f"    {t}: {c}")

        print(f"\n  Top 10 by priority (★=stars, ↓=installs):")
        selected_by_prio = sorted(selected, key=lambda d: -priority_score(d))
        for s in selected_by_prio[:10]:
            st = int(s.get('stars') or 0)
            ins = int(s.get('installs') or 0)
            indicator = f"★{st:>6,}" if st > 0 else f"↓{ins:>6,}"
            typ = "[agent]" if is_agent_skill(s) else "[mcp]"
            print(f"    {s.get('id',''):45s} {indicator}  {typ} {s.get('name','')}")
        print(f"\n  IDs (for --skill-ids):")
        print(f"  {','.join(s.get('id','') for s in selected[:5])},...({len(selected)} total)")


if __name__ == "__main__":
    main()
