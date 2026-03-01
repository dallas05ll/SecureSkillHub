# Verification Workflow

Practical operator guide for selecting skills, running verification, and rebuilding indexes.

## What Counts As "Fully Verified"

A skill is considered fully verified only when all of these are true:

1. `verification_status == "pass"`
2. `verification_level == "full_pipeline"` **or** `agent_audit.agents_completed >= 5`
3. In current operations, that state is produced by `run_verify_strict_5agent.py` (A + B + C* + D + E)

This is the same rule used by the site stats/frontend logic.

## Verification Levels

| `verification_level` | Meaning | Script |
|---|---|---|
| `full_pipeline` | Full 5-agent verification (doc-vs-code + scanner + scoring + supervisor) | `run_verify_strict_5agent.py` |
| `scanner_only` | Agent C* deterministic scanner only | `run_verify_sample.py` |
| `metadata_only` | Metadata heuristic only (no clone / no code scan) | `batch_verify_agent_skills.py` |
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
- `repo_status: "unavailable"`
- `repo_check_date`
- `repo_check_error` (truncated)

By default, both verification runners skip `repo_unavailable` skills. Use `--include-repo-unavailable` to include them.

Reachability maintenance:

- `python3 check_reachability.py` adds/removes `repo_unavailable`
- `python3 check_reachability.py --recheck` retries currently unavailable repos and removes the tag if reachable

## Full Pipeline Outputs (Strict 5-Agent)

`run_verify_strict_5agent.py` writes:

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

Built by `python3 build_priority.py`.

Shape highlights:

- `generated_at`
- `total_unverified`
- `tiers` (tier metadata)
- `queue` (full summary objects)

### Agent/API queue (`site/api/indexes/verify-queue.json`)

Built by `python3 build_indexes.py`.

Shape highlights:

- `generated_at`, `total_skills`, `generator`
- `total_unverified`
- `tier_counts`
- tier arrays: `tier_1_1000plus`, `tier_2_100_999`, `tier_3_10_99`, `tier_4_1_9`, `tier_5_0`
- each entry: `{ "id", "stars", "name" }`

Notes:

- Queue currently includes only `unverified` skills (not `updated_unverified`).
- `site/api/indexes/by-status.json` is the canonical grouped status view for API consumers.

## Practical Run Sequence

1. **(Optional) Refresh reachability first**

```bash
python3 check_reachability.py --only-untagged
python3 check_reachability.py --recheck
```

2. **Select candidates**

```bash
python3 build_indexes.py --only verify-queue --only by-status
```

3. **Run full verification (recommended production path)**

```bash
python3 run_verify_strict_5agent.py --limit 100 --group-count 10 --only-unverified
# target explicit records when needed
python3 run_verify_strict_5agent.py --skill-ids skill_a,skill_b,skill_c
```

4. **(Optional) scanner-only sampling**

```bash
python3 run_verify_sample.py --limit 50 --only-unverified
```

5. **Rebuild site API + HTML**

```bash
.venv/bin/python -m src.build.build_json
.venv/bin/python -m src.build.build_html
python3 build_indexes.py
```

6. **Smoke checks**

```bash
python3 -m http.server 4173 --directory site
# verify: /, /api/stats.json, /api/skills/index.json, /api/search-index.json
```

## Command Reference

```bash
# Full pipeline verification
python3 run_verify_strict_5agent.py --limit 50 --group-count 5 --only-unverified
python3 run_verify_strict_5agent.py --limit 50 --group-count 5 --include-repo-unavailable

# Scanner-only verification
python3 run_verify_sample.py --limit 20 --only-unverified
python3 run_verify_sample.py --limit 20 --shard-index 0 --shard-count 4

# Metadata-only (agent_skill only)
python3 batch_verify_agent_skills.py
```

## Post-Verification Review

After a verification run completes, the Skills Manager reviews all processed skills using a dual-agent pattern:

1. **SM-A (Reviewer)**: Checks verification quality — does `verification_level` match `agent_audit` evidence? Are score thresholds correct? Were safety overrides applied?
2. **SM-B (Auditor)**: Checks data integrity — tags consistent, no duplicates, `findings_summary` is dict, no conflicting fields.
3. **Reconciliation**: Both agree clean → finalize. Both find issues → flag for PM. Disagree → escalate to PM with both perspectives.
4. For `manual_review` results: PM auto-reviews using Decision Tree from `PROJECT_MANAGER.md`.
5. All decisions logged to `data/skill-manager-log.json` with `check_type: "sm_review"` or `"pm_review"`.

```bash
# Auto-review everything from a verification run
python3 skills_manager_review.py --run-report data/verification-runs/<timestamp>_strict5_limit50.json

# PM finalizes manual_review outcomes (writes status + comment to skill JSON)
python3 skills_manager_review.py --run-report data/verification-runs/<timestamp>_strict5_limit50.json --pm-finalize

# Review the manual_review queue (PM-triggered)
python3 skills_manager_review.py --manual-review-queue --limit 10

# PM finalizes a slice of manual_review queue
python3 skills_manager_review.py --manual-review-queue --limit 10 --pm-finalize

# Periodic data quality audit of all pass skills
python3 skills_manager_review.py --periodic
```
