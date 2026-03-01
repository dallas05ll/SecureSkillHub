# Skills Manager Workflow

How to monitor, prioritize, and manage the skill collection.

## Quick Nav

- [Dashboard](#collection-dashboard) — what files to read for the full picture
- [Health Checks](#health-checks) — what to monitor
- [Pipeline Supervision](#pipeline-supervision) — crawl + verification oversight
- [Verification Priority](#verification-priority) — what to verify next
- [Package Recommendations](#package-recommendations) — when to build packages
- [Skill Manager Memory](#skill-manager-memory) — persistent log of checks and findings
- [Commands](#commands) — copy-paste commands

---

## Collection Dashboard

Read these files for a complete picture of the collection:

| Data Source | File | What It Tells You |
|-------------|------|-------------------|
| Hub statistics | `data/stats.json` | Total skills, verified/failed/pending counts, per-source totals |
| Crawl state | `data/crawl-state.json` | Per-hub crawl status, last crawl dates, completion |
| Verify queue (scripts) | `data/verify-queue.json` | Tier breakdown (by stars), built by `build_priority.py` |
| Verify queue (agents) | `site/api/indexes/verify-queue.json` | Same data, agent-accessible API path, built by `build_indexes.py` |
| Package index | `data/packages/index.json` | Auto-curated packages, tag coverage, avg scores |
| Tag hierarchy | `data/tags.json` | 4-layer taxonomy, all valid tag IDs |
| Individual skills | `data/skills/*.json` | Full skill records (6,307 files) |
| Reachability log | `data/reachability-check.json` | Batch reachability scan results with timestamps |
| Skill manager log | `data/skill-manager-log.json` | Unified log: crawl, reachability, verification, health checks |

---

## Health Checks

Run `python3 health_check.py` for an automated dashboard, or check manually:

### 1. Collection Coverage

- How many total skills? (target: grow steadily)
- Per-source breakdown: are any hubs under-crawled?
- Are there hubs in crawl-state with `status: pending`?

### 2. Verification Coverage

- What % of skills are verified? (`data/stats.json` → verified_skills / total_skills)
- Run `python3 health_check.py` for live numbers (do not rely on hardcoded stats)
- How many `fail` or `manual_review` need attention?

### 3. Data Quality

- Skills with `verified_commit: null` — were they scanned without capturing the commit?
- Skills with `findings_summary` as a string (should be dict) — run `fix_data_quality.py`
- Skills with `scan_date: null` but `verification_status != unverified` — data inconsistency

### 4. Tag Coverage

- Are there skills with empty `tags: []`? → Run `python3 auto_tag.py`
- Are tags balanced or concentrated in a few categories?

### 5. Package Gaps

- Are there top-level tags with no packages? → Run `python3 build_packages.py`
- Do packages have enough high-quality skills (score ≥ 70, verified)?

---

## Pipeline Supervision

The skills manager supervises both crawl and verification pipelines through `data/skill-manager-log.json`. All pipelines log their results there automatically.

### Log Entry Types

| `check_type` | Source | What It Records |
|--------------|--------|-----------------|
| `crawl_run` | `process_discovered.py`, `crawl_agent_skills.py` | Skills discovered, deduped, reachable, written |
| `crawl_reachability` | `src/reachability.py` (inline) | Per-batch reachability results during crawl |
| `reachability_run` | `check_reachability.py` (batch) | Full-collection reachability scan |
| `health_check` | `health_check.py` | Collection stats, verification coverage, quality |
| `verification_run` | `run_verify_strict_5agent.py`, `run_verify_sample.py`, `batch_verify_agent_skills.py` | Verification pipeline results (full/scanner-only/metadata-only) |

### What the Manager Monitors

1. **Crawl quality** — What fraction of each hub's discoveries are dead repos? High unreachable rate (>30%) = low-quality hub, reconsider priority.
2. **Collection decay** — Are previously-reachable repos going offline? Run `check_reachability.py --recheck` periodically.
3. **Duplicate prevention** — Crawl scripts now check existing `repo_url` before adding. Log tracks new vs merged.
4. **Verification progress** — How many skills have `verification_level: full_pipeline` vs `scanner_only` vs `unverified`?
5. **Unavailable skills** — monitor `repo_unavailable` tag volume via `python3 check_reachability.py --report`; verification scripts skip these by default.
6. **Status search tags** — verification scripts sync one `status-*` tag on touched records (`status-pass`, `status-manual_review`, etc.); use `verification_status` as canonical for full-collection analytics.

### Reading the Log

```bash
python3 health_check.py --history 5   # Last 5 log entries
python3 -c "import json; [print(e['check_type'], e['timestamp'][:16], json.dumps(e.get('findings',{}))) for e in json.load(open('data/skill-manager-log.json')).get('entries',[])]"
```

---

## Verification Priority

Skills are prioritized by GitHub stars (highest first). Use `data/verify-queue.json` (local scripts) or `site/api/indexes/verify-queue.json` (agent API) tiers:

| Tier | Stars | Priority | Action |
|------|-------|----------|--------|
| Tier 1 | 1,000+ | Critical | Verify immediately — these are the most visible |
| Tier 2 | 100-999 | High | Verify next — significant community signal |
| Tier 3 | 10-99 | Medium | Verify as bandwidth allows |
| Tier 4 | 1-9 | Low | Batch verification |
| Tier 5 | 0 | Lowest | Low priority — no community signal |

**Guidance:** Always verify Tier 1 first, then Tier 2. Scanner-only works on any tier (any skill with a GitHub URL). Metadata-only is useful for quick triage of large backlogs.

---

## Package Recommendations

Packages are auto-curated by `build_packages.py` based on:

1. **Tag hierarchy** — packages follow the tag tree (e.g., `dev-web-backend-python`)
2. **Minimum skills** — need ≥ 1 skill with score ≥ 50 and status not `unverified`/`fail`
3. **Top N** — each package takes the top 10 skills by stars (configurable: `--top N`)
4. **Score threshold** — avg score displayed for quality signal

**When to rebuild packages:**
- After a bulk verification run (new skills verified)
- After star enrichment (rankings may change)
- After adding a new tag category
- Run: `python3 build_packages.py`

**Current packages:** 16 (concentrated in dev and data domains)

---

## Skill Manager Memory

The skill manager maintains a persistent log at `data/skill-manager-log.json`. This is the skill manager's own memory — a logbook that records what it found, when it checked, and what changed over time.

**This is NOT a replacement for scan reports** (`data/scan-reports/`). Scan reports are per-skill detailed security findings. The skill manager log is a high-level operational log of the collection's health trajectory.

### What It Records

Each entry in the log captures:

| Field | Description |
|-------|-------------|
| `timestamp` | When the check ran (UTC ISO 8601) |
| `check_type` | What kind of check: `health_check`, `verification_run`, `crawl_run`, `reachability_run`, `crawl_reachability` |
| `findings` | Type-specific metrics payload (shape varies by `check_type`) |
| `recommendations` | Optional recommendations (commonly present on health/crawl checks) |
| `changes_since_last` | Optional delta payload (typically health-check generated) |

### Summary Counters

Some environments maintain aggregate counters at the log root. Treat these as optional and rely on `entries[]` as the canonical history stream.

### How to View History

```bash
python3 health_check.py --history       # Show last 5 entries
python3 health_check.py --history 10    # Show last 10 entries
python3 health_check.py --history 1     # Show only the most recent entry
```

### Behavior Tracking

Over time, the log builds a picture of the collection's health trajectory. By reviewing history, the skill manager can answer:

- When was the last check? What did it find?
- Are issues being resolved or accumulating?
- How fast is the collection growing? (new skills per check)
- Is verification keeping pace with new crawls?
- When was the collection last fully healthy?

---

## Commands

```bash
# Health dashboard (also logs to data/skill-manager-log.json)
python3 health_check.py

# View skill manager history
python3 health_check.py --history           # Last 5 entries
python3 health_check.py --history 10        # Last 10 entries

# Priority verification
python3 build_indexes.py --only verify-queue --only by-status
python3 run_verify_sample.py --only-unverified --limit 20  # Scanner-only sample
python3 run_verify_strict_5agent.py --limit 20 --group-count 5 --only-unverified

# Enrichment
python3 enrich_stars.py --skip-existing                     # Update star counts
python3 auto_tag.py                                         # Re-tag all skills

# Package management
python3 build_packages.py                                   # Rebuild packages

# Data quality
python3 fix_data_quality.py                                 # Fix schema inconsistencies

# Full rebuild
.venv/bin/python -m src.build.build_json                    # Rebuild API JSON
.venv/bin/python -m src.build.build_html                    # Rebuild HTML assets
```
