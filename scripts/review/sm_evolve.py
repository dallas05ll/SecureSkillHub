#!/usr/bin/env python3
"""
Skills Manager self-evolve loop.

Learns from verification runs, tag distribution, and collection health to:
1. Identify false positive patterns from verification history
2. Detect collection coverage gaps (under-represented categories)
3. Track quality distribution changes over time
4. Generate actionable recommendations
5. Write learnings to SM structured memory (Layer 1)

This script should be run AFTER each verification batch to update SM's knowledge.

Usage:
    python3 scripts/review/sm_evolve.py                    # Full evolve cycle
    python3 scripts/review/sm_evolve.py --report           # Report only (no write)
    python3 scripts/review/sm_evolve.py --learn-from-run <path>  # Learn from specific run
"""

import argparse
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
SKILLS_DIR = PROJECT_ROOT / "data" / "skills"
VERIFY_RUNS_DIR = PROJECT_ROOT / "data" / "verification-runs"
SM_MEMORY_FILE = PROJECT_ROOT / "memory" / "structured" / "sm-health.json"
LOG_FILE = PROJECT_ROOT / "data" / "skill-manager-log.json"
sys.path.insert(0, str(PROJECT_ROOT))


def load_all_skills() -> list[dict]:
    """Load all skill JSON files."""
    skills = []
    for f in sorted(SKILLS_DIR.glob("*.json")):
        try:
            skills.append(json.load(open(f)))
        except Exception:
            continue
    return skills


def load_verification_runs() -> list[dict]:
    """Load all verification run reports."""
    runs = []
    if not VERIFY_RUNS_DIR.exists():
        return runs
    for f in sorted(VERIFY_RUNS_DIR.glob("*.json")):
        try:
            runs.append(json.load(open(f)))
        except Exception:
            continue
    return runs


def analyze_tag_distribution(skills: list[dict]) -> dict:
    """Analyze tag coverage and identify gaps."""
    tag_counts: Counter = Counter()
    source_tags: dict[str, Counter] = defaultdict(Counter)
    skills_per_depth: Counter = Counter()  # depth 0 = broad, 1+ = specific

    for s in skills:
        tags = [t for t in s.get("tags", [])
                if not t.startswith("installs:") and t not in ("agent-skills", "repo_unavailable", "clone_failure")
                and not t.startswith("status-")]
        source = s.get("source_hub", "unknown")

        for t in tags:
            tag_counts[t] += 1
            source_tags[source][t] += 1

        # Measure depth: count max hyphens
        max_depth = max((t.count("-") for t in tags), default=0)
        skills_per_depth[max_depth] += 1

    # Identify under-represented categories (< 1% of total)
    total = len(skills)
    threshold = total * 0.01
    top_level = ["dev", "data", "prod", "integ", "sec", "util"]
    gaps = []
    for tl in top_level:
        count = tag_counts.get(tl, 0)
        pct = count * 100 / total if total else 0
        if count < threshold:
            gaps.append({"category": tl, "count": count, "pct": round(pct, 1)})

    return {
        "total_skills": total,
        "unique_tags": len(tag_counts),
        "top_20_tags": dict(tag_counts.most_common(20)),
        "avg_tags_per_skill": round(sum(len([t for t in s.get("tags", [])
            if not t.startswith("installs:") and t not in ("agent-skills", "repo_unavailable", "clone_failure")
            and not t.startswith("status-")]) for s in skills) / max(total, 1), 1),
        "depth_distribution": dict(skills_per_depth),
        "coverage_gaps": gaps,
        "source_diversity": {src: len(tags) for src, tags in source_tags.items()},
    }


def analyze_verification_quality(skills: list[dict]) -> dict:
    """Analyze verification status distribution and quality metrics."""
    status_counts: Counter = Counter()
    level_counts: Counter = Counter()
    score_buckets: Counter = Counter()
    fp_override_count = 0
    overrides_by_reason: Counter = Counter()

    verified = []
    for s in skills:
        status = s.get("verification_status", "unverified")
        level = s.get("verification_level", "none")
        status_counts[status] += 1
        level_counts[level] += 1

        if s.get("pm_override"):
            fp_override_count += 1
            reason = s.get("pm_override_reason", "unknown")
            # Extract category from reason (e.g., "FP: scanner_penalty" → "scanner_penalty")
            if ":" in reason:
                cat = reason.split(":")[0].strip()
            else:
                cat = reason[:30]
            overrides_by_reason[cat] += 1

        score = s.get("verification_score")
        if score is not None:
            if score >= 85:
                score_buckets["85-100"] += 1
            elif score >= 70:
                score_buckets["70-84"] += 1
            elif score >= 50:
                score_buckets["50-69"] += 1
            else:
                score_buckets["0-49"] += 1
            verified.append(s)

    return {
        "status_distribution": dict(status_counts),
        "level_distribution": dict(level_counts),
        "score_distribution": dict(score_buckets),
        "total_verified": len(verified),
        "pm_overrides": fp_override_count,
        "override_categories": dict(overrides_by_reason.most_common(10)),
        "avg_score": round(sum(s.get("verification_score", 0) for s in verified) / max(len(verified), 1), 1),
    }


def analyze_fp_patterns(skills: list[dict]) -> list[dict]:
    """Extract false positive patterns from PM overrides for scanner learning."""
    patterns = []
    seen = set()

    for s in skills:
        if not s.get("pm_override"):
            continue
        reason = s.get("pm_override_reason", "")
        repo = s.get("repo_url", "")

        # Extract org from repo URL
        org = ""
        if "github.com/" in repo:
            parts = repo.split("github.com/")[1].split("/")
            if parts:
                org = parts[0].lower()

        key = (org, reason[:50])
        if key in seen:
            continue
        seen.add(key)

        patterns.append({
            "skill": s.get("name", "unknown"),
            "org": org,
            "reason": reason,
            "score": s.get("verification_score"),
        })

    return patterns


def build_recommendations(tag_analysis: dict, quality_analysis: dict) -> list[str]:
    """Generate actionable recommendations from analysis."""
    recs = []

    # Tag coverage
    for gap in tag_analysis.get("coverage_gaps", []):
        recs.append(f"COVERAGE_GAP: '{gap['category']}' only has {gap['count']} skills ({gap['pct']}%). Consider targeted crawling.")

    # Tag depth
    depth = tag_analysis.get("depth_distribution", {})
    shallow = depth.get(0, 0) + depth.get(1, 0)
    total = tag_analysis.get("total_skills", 1)
    if shallow > total * 0.5:
        recs.append(f"TAG_DEPTH: {shallow}/{total} skills have shallow tags (depth 0-1). Run auto_tag enrichment.")

    # Verification coverage
    status = quality_analysis.get("status_distribution", {})
    unverified = status.get("unverified", 0) + status.get("updated_unverified", 0)
    if unverified > total * 0.5:
        recs.append(f"VERIFY_COVERAGE: {unverified}/{total} skills still unverified. Run next batch.")

    # FP rate
    overrides = quality_analysis.get("pm_overrides", 0)
    verified = quality_analysis.get("total_verified", 0)
    if verified > 0 and overrides > verified * 0.3:
        fp_rate = round(overrides * 100 / verified, 0)
        recs.append(f"FP_RATE: {fp_rate}% of verified skills needed PM override. Scanner patterns may need tuning.")

    return recs


def load_sm_memory() -> dict:
    """Load existing SM memory or return default structure."""
    if SM_MEMORY_FILE.exists():
        try:
            return json.load(open(SM_MEMORY_FILE))
        except Exception:
            pass

    return {
        "schema_version": "1.0",
        "role": "skills_manager",
        "entries": [],
        "evolve_history": [],
    }


def write_sm_memory(memory: dict):
    """Write SM structured memory."""
    SM_MEMORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    SM_MEMORY_FILE.write_text(json.dumps(memory, indent=2, ensure_ascii=False))


def evolve(report_only: bool = False, run_path: str | None = None):
    """Run the full SM evolve cycle."""
    now = datetime.now(timezone.utc).isoformat()
    print("=" * 60)
    print("SM Self-Evolve Cycle")
    print("=" * 60)

    # Load skills
    skills = load_all_skills()
    print(f"\nLoaded {len(skills)} skills")

    # Analyze
    tag_analysis = analyze_tag_distribution(skills)
    quality_analysis = analyze_verification_quality(skills)
    fp_patterns = analyze_fp_patterns(skills)
    recommendations = build_recommendations(tag_analysis, quality_analysis)

    # Print report
    print(f"\n--- Tag Distribution ---")
    print(f"Unique tags: {tag_analysis['unique_tags']}")
    print(f"Avg tags/skill: {tag_analysis['avg_tags_per_skill']}")
    print(f"Depth distribution: {tag_analysis['depth_distribution']}")
    if tag_analysis['coverage_gaps']:
        print(f"Coverage gaps: {[g['category'] for g in tag_analysis['coverage_gaps']]}")

    print(f"\n--- Verification Quality ---")
    print(f"Status: {quality_analysis['status_distribution']}")
    print(f"Avg score: {quality_analysis['avg_score']}")
    print(f"PM overrides: {quality_analysis['pm_overrides']}")
    print(f"Override categories: {quality_analysis['override_categories']}")

    print(f"\n--- Recommendations ---")
    for r in recommendations:
        print(f"  • {r}")

    if report_only:
        print("\n[Report only mode — no memory written]")
        return

    # Write to SM memory
    memory = load_sm_memory()

    evolve_entry = {
        "id": f"sm-evolve-{now[:19].replace(':', '')}",
        "timestamp": now,
        "tag_analysis": {
            "total_skills": tag_analysis["total_skills"],
            "unique_tags": tag_analysis["unique_tags"],
            "avg_tags_per_skill": tag_analysis["avg_tags_per_skill"],
            "coverage_gaps": tag_analysis["coverage_gaps"],
        },
        "quality_analysis": {
            "status_distribution": quality_analysis["status_distribution"],
            "avg_score": quality_analysis["avg_score"],
            "pm_overrides": quality_analysis["pm_overrides"],
            "override_categories": quality_analysis["override_categories"],
        },
        "fp_pattern_count": len(fp_patterns),
        "recommendations": recommendations,
    }

    memory["evolve_history"].append(evolve_entry)

    # Update or add key entries
    entry_map = {e["id"]: e for e in memory.get("entries", [])}

    # sm-h-001: Collection state
    entry_map["sm-h-001"] = {
        "id": "sm-h-001",
        "title": "Collection state snapshot",
        "updated": now,
        "data": {
            "total_skills": tag_analysis["total_skills"],
            "unique_tags": tag_analysis["unique_tags"],
            "avg_tags_per_skill": tag_analysis["avg_tags_per_skill"],
            "status_distribution": quality_analysis["status_distribution"],
            "source_diversity": tag_analysis["source_diversity"],
        },
    }

    # sm-h-002: Top tags
    entry_map["sm-h-002"] = {
        "id": "sm-h-002",
        "title": "Top 20 tags by skill count",
        "updated": now,
        "data": tag_analysis["top_20_tags"],
    }

    # sm-h-003: Quality metrics
    entry_map["sm-h-003"] = {
        "id": "sm-h-003",
        "title": "Verification quality metrics",
        "updated": now,
        "data": {
            "total_verified": quality_analysis["total_verified"],
            "avg_score": quality_analysis["avg_score"],
            "score_distribution": quality_analysis["score_distribution"],
            "pm_overrides": quality_analysis["pm_overrides"],
        },
    }

    # sm-h-004: FP patterns learned
    entry_map["sm-h-004"] = {
        "id": "sm-h-004",
        "title": "False positive patterns from verification",
        "updated": now,
        "data": {
            "total_fps": len(fp_patterns),
            "top_categories": quality_analysis["override_categories"],
            "sample_patterns": fp_patterns[:10],
        },
    }

    # sm-h-005: Recommendations
    entry_map["sm-h-005"] = {
        "id": "sm-h-005",
        "title": "Current recommendations",
        "updated": now,
        "data": recommendations,
    }

    memory["entries"] = list(entry_map.values())
    memory["last_evolve"] = now

    write_sm_memory(memory)
    print(f"\nSM memory updated: {SM_MEMORY_FILE}")

    # Log to skill-manager-log
    log_entry = {
        "type": "sm_evolve",
        "timestamp": now,
        "summary": {
            "total_skills": tag_analysis["total_skills"],
            "unique_tags": tag_analysis["unique_tags"],
            "recommendations_count": len(recommendations),
            "fp_patterns_learned": len(fp_patterns),
        },
    }

    try:
        log = json.load(open(LOG_FILE)) if Path(LOG_FILE).exists() else {"entries": []}
        log["entries"].append(log_entry)
        Path(LOG_FILE).write_text(json.dumps(log, indent=2, ensure_ascii=False))
        print(f"Logged to: {LOG_FILE}")
    except Exception as e:
        print(f"Warning: Could not log: {e}")


def main():
    parser = argparse.ArgumentParser(description="SM self-evolve loop")
    parser.add_argument("--report", action="store_true", help="Report only, no memory write")
    parser.add_argument("--learn-from-run", help="Learn from a specific verification run file")
    args = parser.parse_args()

    evolve(report_only=args.report, run_path=args.learn_from_run)


if __name__ == "__main__":
    main()
