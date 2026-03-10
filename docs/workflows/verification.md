# Verification Workflow

Practical operator guide for selecting skills, running verification, and rebuilding indexes.

## What Counts As "Fully Verified"

A skill is considered fully verified only when all of these are true:

1. `verification_status == "pass"`
2. `verification_level == "full_pipeline"` **or** `agent_audit.agents_completed >= 5`
3. In current operations, that state is produced by `scripts/verify/run_verify_strict_5agent.py` (A + B + C* + D + E)

This is the same rule used by the site stats/frontend logic.

## Verification Levels

| `verification_level` | Meaning | Script |
|---|---|---|
| `full_pipeline` | Full 5-agent verification (doc-vs-code + scanner + scoring + supervisor) | `scripts/verify/run_verify_strict_5agent.py` |
| `scanner_only` | Agent C* deterministic scanner only | `scripts/verify/run_verify_sample.py` |
| `metadata_only` | Metadata heuristic only (no clone / no code scan) | `scripts/verify/batch_verify_agent_skills.py` |
| empty / missing | Not yet normalized or not verified through current scripts | n/a |

## Verification Statuses and `status-*` Tags

Canonical statuses are:

- `pass`
- `manual_review`
- `fail`
- `unverified`
- `updated_unverified`

Verification scripts normalize aliases (`verified`, `review`, `failed`, `updated-unverified`) to the canonical values above.

### `status-*` tag behavior

Verification scripts sync one status tag when they update a skill:

- `status-pass`
- `status-manual_review`
- `status-fail`
- `status-unverified`
- `status-updated_unverified`

Important: `verification_status` is the canonical field. Treat `status-*` tags as search helpers that may be missing on legacy records until those records are touched by verification scripts.

## Repo Availability (`repo_unavailable`)

`repo_unavailable` means the repo could not be reached/cloned.

When this is detected, scripts write:

- tag: `repo_unavailable`
- tag: `not_reachable` (alias for fast agent/human filtering)
- `repo_status: "unavailable"`
- `repo_check_date`
- `repo_check_error` (truncated)

By default, both verification runners skip `repo_unavailable` skills. Use `--include-repo-unavailable` to include them.

Reachability maintenance:

- `python3 scripts/crawl/check_reachability.py` adds/removes `repo_unavailable`
- `python3 scripts/crawl/check_reachability.py --recheck` retries currently unavailable repos and removes the tag if reachable

## Full Pipeline Outputs (Strict 5-Agent)

`scripts/verify/run_verify_strict_5agent.py` writes:

1. Skill updates in `data/skills/{id}.json`
2. Per-agent reports in `data/scan-reports/{id}/`:
   - `agent_a_docs.json`
   - `agent_b_code.json`
   - `agent_c_scanner.json`
   - `agent_d_scorer.json`
   - `agent_e_supervisor.json`
   - `summary.json`
3. Run report in `data/verification-runs/*_strict5_*.json`
4. Skill-manager log entry (`check_type: verification_run`)

On clone-stage failure, strict runner sets `verification_status` to `manual_review`, adds/keeps `repo_unavailable`, and records repo check metadata.

## Queue and Index Shapes

There are two queue files with different purposes.

### Script queue (`data/verify-queue.json`)

Built by `python3 scripts/build/build_priority.py`.

Shape highlights:

- `generated_at`
- `total_unverified`
- `tiers` (tier metadata)
- `queue` (full summary objects)

### Agent/API queue (`site/api/indexes/verify-queue.json`)

Built by `python3 scripts/build/build_indexes.py`.

Shape highlights:

- `generated_at`, `total_skills`, `generator`
- `total_unverified`
- `tier_counts`
- tier arrays: `tier_1_1000plus`, `tier_2_100_999`, `tier_3_10_99`, `tier_4_1_9`, `tier_5_0`
- each entry: `{ "id", "stars", "name" }`

Notes:

- Queue currently includes only `unverified` skills (not `updated_unverified`).
- `site/api/indexes/by-status.json` is the canonical grouped status view for API consumers.

## Self-Evolving Learn-Write-Back Flow

The verification system uses a feedback loop where Opus (PM/SecM) writes learnings back to Sonnet (VM) memory after every review cycle. This reduces false positives on subsequent runs.

```
┌─────────────────────────────────────────────────────────┐
│  SELF-EVOLVING VERIFICATION LOOP                        │
│                                                         │
│  1. VM (Sonnet) reads memory/structured/vm-corrections.json │
│  2. VM runs pipeline → produces pass/fail/MR            │
│  3. PM + SecM (Opus) reviews → discovers FP patterns    │
│  4. PM + SecM writes learnings → VM memory file         │
│  5. Next run: VM reads updated memory → fewer FPs       │
│                                                         │
│  Opus learns → writes to memory → Sonnet reads → fewer  │
│  FPs → less PM review → more verified skills per cycle  │
└─────────────────────────────────────────────────────────┘
```

**Memory file:** `memory/structured/vm-corrections.json` — contains:
- Known FP categories with trigger conditions, examples, root causes
- Scoring formula bug documentation
- PM-verified organizations (auto-trust list)
- Scanner exclusion requests
- Operational notes

**Mandatory steps:**
- VM MUST read memory before every run (pre-flight step 1)
- PM MUST write learnings after every review (post-review step)
- SecM MUST write findings after every investigation

## Practical Run Sequence

1. **Read VM memory** (MANDATORY pre-flight)

```bash
# VM reads memory/structured/vm-corrections.json before every run
# This contains PM/SecM learnings from previous cycles
```

2. **(Optional) Refresh reachability first**

```bash
python3 scripts/crawl/check_reachability.py --only-untagged
python3 scripts/crawl/check_reachability.py --recheck
```

3. **SM selects candidates (MANDATORY — never skip this step)**

SM produces an explicit skill_ids list from the verify-queue, sorted by tier priority:
```bash
# SM reads the verify-queue
python3 scripts/build/build_indexes.py --only verify-queue --only by-status

# SM selects from highest available tier (Tier 1 → 2 → 3 → 4 → 5)
python3 -c "
import json
q = json.load(open('site/api/indexes/verify-queue.json'))
for tier in ['tier_1_1000plus', 'tier_2_100_999', 'tier_3_10_99', 'tier_4_1_9', 'tier_5_0']:
    items = q.get(tier, [])
    if items:
        ids = [i['id'] for i in items[:100]]
        print(f'SM Selection: {len(ids)} from {tier}')
        print(','.join(ids))
        break
"
```

**RULE:** Never use `--limit N` or `--only-unverified` without SM's explicit skill_ids. Never mix 0-star skills with higher-tier availability.

4. **VM runs verification using SM's skill_ids**

```bash
# VM uses SM's exact skill_ids (from step 3)
.venv/bin/python scripts/verify/run_verify_strict_5agent.py --skill-ids id1,id2,id3,...
# target explicit records when needed
.venv/bin/python scripts/verify/run_verify_strict_5agent.py --skill-ids skill_a,skill_b,skill_c
```

5. **(Optional) scanner-only sampling**

```bash
python3 scripts/verify/run_verify_sample.py --limit 50 --only-unverified
```

6. **PM audits ALL non-pass results** (MANDATORY — NEVER SKIP)

This is a two-part audit. PM must check BOTH new and existing non-pass items:

```bash
# 6a: Review THIS run's non-pass (fail + MR + skip)
# For each: legitimate catch or FP? Override/keep/investigate?
# Check auto_clear log: did auto_clear_known_fp() fire? How many?

# 6b: Audit ALL existing MR + fail items (cumulative backlog)
python3 -c "
import json
bs = json.load(open('site/api/indexes/by-status.json'))
print('MR:', [s['id'] for s in bs.get('manual_review', [])])
print('Fail:', [s['id'] for s in bs.get('fail', [])])
"
# For each MR: still pending? Can resolve now? Need SecM?
# For each fail: confirmed legitimate? Need re-investigation?
# For persistent skips: mark repo_unavailable or retry?
# New runs DO NOT excuse old open items.
```

7. **PM writes learnings to ALL memories + code** (MANDATORY after review)

PM owns the entire learning chain. After EVERY review, PM must update:

```bash
# Step 7a: Write to VM memory (FP patterns, categories, orgs, run stats)
# File: memory/structured/vm-corrections.json

# Step 7b: Update pipeline CODE if FP pattern confirmed across 2+ runs
# Scanner exclusions: src/scanner/scanner.py (path/file exclusions)
# Scoring auto-clear: scripts/verify/run_verify_strict_5agent.py (PM_VERIFIED_ORGS, thresholds)
# THIS IS WHAT MAKES THE PIPELINE ACTUALLY LEARN

# Step 7c: Sync MEMORY.md with current catalog state
# File: memory/MEMORY.md (pass/MR/fail counts, verified org count)

# Step 7d: Log to SM operational log
# check_type: "pm_learning" in data/skill-manager-log.json

# Step 7e: Update PM decisions memory (sync timestamps, code change status)
# File: memory/structured/pm-decisions.json
```

**Bond rule:** PM decisions memory (`memory/structured/pm-decisions.json`) is the central bond. All memories reference it. PM updates it last to confirm sync.

8. **Rebuild site API + HTML**

```bash
.venv/bin/python -m src.build.build_json
.venv/bin/python -m src.build.build_html
python3 scripts/build/build_indexes.py
```

9. **Smoke checks**

```bash
python3 -m http.server 4173 --directory site
# verify: /, /api/stats.json, /api/skills/index.json, /api/search-index.json
```

## Command Reference

```bash
# Full pipeline verification (SM-first, MANDATORY)
SM_TARGETS=$(python3 scripts/review/sm_select_targets.py --limit 50 --output-ids)
.venv/bin/python scripts/verify/run_verify_strict_5agent.py --skill-ids "$SM_TARGETS"

# Full pipeline — repo-unavailable included (SM-first)
SM_TARGETS=$(python3 scripts/review/sm_select_targets.py --limit 50 --output-ids)
.venv/bin/python scripts/verify/run_verify_strict_5agent.py --skill-ids "$SM_TARGETS" --include-repo-unavailable

# Scanner-only verification
python3 scripts/verify/run_verify_sample.py --limit 20 --only-unverified
python3 scripts/verify/run_verify_sample.py --limit 20 --shard-index 0 --shard-count 4

# Metadata-only (agent_skill only)
python3 scripts/verify/batch_verify_agent_skills.py
```

## Post-Verification Review

After a verification run completes, the Skills Manager reviews all processed skills using a dual-agent pattern:

1. **SM-A (Reviewer)**: Checks verification quality — does `verification_level` match `agent_audit` evidence? Are score thresholds correct? Were safety overrides applied?
2. **SM-B (Auditor)**: Checks data integrity — tags consistent, no duplicates, `findings_summary` is dict, no conflicting fields.
3. **Reconciliation**: Both agree clean → finalize. Both find issues → flag for PM. Disagree → escalate to PM with both perspectives.
4. For `manual_review` results: PM auto-reviews using Decision Tree from `roles/PROJECT_MANAGER.md`.
5. All decisions logged to `data/skill-manager-log.json` with `check_type: "sm_review"` or `"pm_review"`.
6. **PM writes learnings to ALL memories + pipeline code** (see Step 6 above). Central tracker: `memory/structured/pm-decisions.json`.
7. **Pipeline auto-clear:** `auto_clear_known_fp()` in scoring script auto-clears known FP patterns (Cat 9 monorepo, Cat 10 verified orgs, Cat 11 incidental). Check `agent_audit.auto_clear` field for auto-clear decisions.

```bash
# Auto-review everything from a verification run
python3 scripts/review/skills_manager_review.py --run-report data/verification-runs/<timestamp>_strict5_limit50.json

# PM finalizes manual_review outcomes (writes status + comment to skill JSON)
python3 scripts/review/skills_manager_review.py --run-report data/verification-runs/<timestamp>_strict5_limit50.json --pm-finalize

# Review the manual_review queue (PM-triggered)
python3 scripts/review/skills_manager_review.py --manual-review-queue --limit 10

# PM finalizes a slice of manual_review queue
python3 scripts/review/skills_manager_review.py --manual-review-queue --limit 10 --pm-finalize

# Periodic data quality audit of all pass skills
python3 scripts/review/skills_manager_review.py --periodic
```
