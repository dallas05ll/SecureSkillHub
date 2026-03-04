# SecureSkillHub — Agent Rules

## Single Source of Truth (MANDATORY)

Each topic has ONE canonical home. Never duplicate content across files. If you need to reference a topic, link to its canonical file instead.

| Topic | Canonical File | Notes |
|-------|---------------|-------|
| Agent rules, structure, build, model routing | `CLAUDE.md` (this file) | Auto-loaded by Claude Code |
| Parallel agent workflow, file ownership | `AGENTS.md` | Workstreams + validation gates |
| API endpoints, external agent discovery entry | `site/entry.md` | External agent/human discovery + API usage |
| Verification execution workflow (commands + stages) | `docs/workflows/verification.md` | Operational source for running verification |
| All data contracts (Pydantic models) | `src/sanitizer/schemas.py` | Single schema source |
| Growth/monetization strategy | `STRATEGY.md` | Direction, not implementation |
| Workflow documentation (verify, crawl, build, etc.) | `docs/workflows/` | 6 workflow files, quick nav below |
| Per-hub crawl tracking | `data/crawl-state.json` | Read/update via `scripts/crawl/crawl_state.py` |
| Project vision & goals | `docs/design/vision.md` | North star for all agents |
| Design principles | `docs/design/principles.md` | 22 numbered constraints |
| Verification architecture | `docs/design/verification-architecture.md` | How 5-agent pipeline works |
| Project manager agent | `roles/PROJECT_MANAGER.md` | Manual review, doc alignment, goal tracking |
| Skills Manager (catalog health, SM-A/SM-B review) | `roles/SKILLS_MANAGER.md` | Dual-agent quality + integrity review, selects what VM verifies |
| Verification Manager (pipeline execution) | `roles/VERIFICATION_MANAGER.md` | Runs 5-agent pipeline, safety override guardian |
| Agent experience (CLI, packages, entry, UX) | `roles/AGENT_EXPERIENCE_MANAGER.md` | Agent-facing UX, CLI, packages, feedback |
| Deploy, git, commit tracking, rollback | `roles/DEPLOY_MANAGER.md` | Executes deploys on PM instruction |
| Frontend visual QA, CSS, rendering bugs | `roles/FRONTEND_MANAGER.md` | Human-facing UI owner |
| Doc librarian, doc-code alignment, Quick Nav | `roles/DOCUMENTATION_MANAGER.md` | Knows all files/paths, fixes doc drift on PM instruction (5 sub-agents) |
| Security Manager (false positive audit, patterns) | `roles/SECURITY_MANAGER.md` | PM's on-demand security consultant, pattern accuracy |
| Memory Manager (memory infrastructure, health) | `roles/MEMORY_MANAGER.md` | Cross-role memory auditor, 9 sub-agents, 4 protocols (LOAD/WRITE/EVOLVE/HEALTH) |
| Structured memory schema + per-role memory | `memory/structured/*.json` | Layer 1: fast-load JSON, tagged, filterable. Owned by MemM |

**Rules:**
- Before writing content, check if it already exists in a canonical file
- Memory files are scratch notes — they must not contradict canonical files
- If docs conflict with code: **code wins**, then update stale docs

Read `AGENTS.md` for the execution contract for parallel agents.

## Model Routing (MANDATORY)

Every Task agent MUST use the correct model for its job type. Set the `model` parameter when launching agents.

| Task Type | Model | Why |
|-----------|-------|-----|
| Scraping, crawling, data enrichment | `sonnet` | Token-efficient, handles structured extraction well |
| Bulk verification, batch scanning | `sonnet` | Repetitive pattern matching, no complex reasoning needed |
| Research, explore, search agents | `sonnet` | Reads lots of code/files, Sonnet is cost-effective |
| Building new features, refactoring | `opus` | Complex reasoning, architecture decisions |
| Planning, system design | `opus` | Needs deep understanding of trade-offs |
| Code review, integration | `opus` | Catches subtle bugs, understands intent |
| Quick file reads, status checks | `haiku` | Fastest, cheapest, sufficient for simple lookups |

**Rule:** Never use Opus for bulk data processing. Never use Haiku for building features.

## Project Structure (Current)

```
roles/                — agent role definition files (8 *_MANAGER.md files)
scripts/crawl/        — crawl scripts (run_crawl, crawl_state, check_reachability, etc.)
scripts/verify/       — verification scripts (run_verify_strict_5agent, run_verify_sample, etc.)
scripts/build/        — build scripts (build_indexes, build_packages, build_priority, fix_data_quality)
scripts/review/       — review scripts (skills_manager_review, health_check)
scripts/enrich/       — enrichment scripts (enrich_stars, auto_tag)
scripts/secm/         — security manager scripts (secm_false_positive_audit, secm_pattern_test)
data/skills/          — skill JSON files (source of truth)
data/packages/        — source package definitions
data/tags.json        — 4-layer tag hierarchy
data/stats.json       — hub-wide statistics
data/crawl-state.json — per-hub crawl tracking (6 sources)
data/pattern-test-cases/ — test corpus for scanner pattern regression testing
data/secm-audit-log.json — SecM audit trail (append-only)
docs/workflows/       — workflow documentation (6 files)
docs/design/          — vision, principles, verification architecture (north star docs)
src/sanitizer/        — schemas.py (Pydantic models), sanitizer.py
src/scanner/          — semgrep + regex static analysis
src/reachability.py   — shared repo reachability checking + skills manager logging
src/verification/     — 5-agent pipeline (prepare/validate pattern, no API keys)
src/crawler/          — crawlers for mcp.so, glama.ai, claudeskills, skills.sh, skillsmp
src/build/            — build_json.py, build_html.py (static site generator)
site/                 — static frontend (vanilla HTML/CSS/JS)
site/api/             — generated JSON API endpoints (do not hand-edit)
site/entry.md         — agent-readable discovery entry point
api/                  — Cloudflare Worker API (user accounts, custom packages)
cli/                  — npx secureskillhub CLI tool
```

## Workflows

> **Quick Nav** — Find what you need in one hop:
>
> | I need to... | File | Section |
> |--------------|------|---------|
> | Crawl a new skill hub | `docs/workflows/crawling.md` | Target Process |
> | Check what's already been crawled | `docs/workflows/crawling.md` | Current Crawlers |
> | Verify skills (scan for security) | `docs/workflows/verification.md` | Command Reference |
> | Understand the 5-agent pipeline | `docs/design/verification-architecture.md` | Data Flow |
> | See the post-verification JSON format | `docs/design/verification-architecture.md` | Stage 8 (VerifiedSkill) |
> | Know the safety override rules | `docs/design/verification-architecture.md` | Safety Overrides |
> | See per-agent audit trail format | `docs/design/verification-architecture.md` | (in `build_agent_audit()`) |
> | Run verification (practical guide) | `docs/workflows/verification.md` | Practical Run Sequence |
> | Enrich star counts or auto-tag | `docs/workflows/enrichment.md` | Commands |
> | Build the site (JSON + HTML) | `docs/workflows/building.md` | Build Steps |
> | Deploy to production | `docs/workflows/deployment.md` | CI/CD Pipeline |
> | Check collection health | `docs/workflows/skills-manager.md` | Health Checks |
> | Decide what to verify next | `docs/workflows/skills-manager.md` | Verification Priority |
> | Build/recommend packages | `docs/workflows/skills-manager.md` | Package Recommendations |
> | Fix data quality issues | `docs/workflows/skills-manager.md` | Commands |
> | Check repo reachability | `scripts/crawl/check_reachability.py` | `--report` for stats, `--recheck` for re-test |
> | Quickly find skills by status/risk/ID | `site/api/indexes/` | manifest, by-status, by-risk, lookup |
> | See what needs verification next | `site/api/indexes/verify-queue.json` | Tiered by stars |
> | Run the full refresh (crawl→deploy) | `docs/workflows/deployment.md` | Full Refresh Sequence |
> | Understand the project vision | `docs/design/vision.md` | Full document |
> | Know the design principles | `docs/design/principles.md` | Full document |
> | Understand verification architecture | `docs/design/verification-architecture.md` | Full document |
> | Run the full 5-agent verification | `docs/workflows/verification.md` | Command Reference |
> | See how verification catches attacks | `docs/case-studies/clawhub-crisis.md` | Full walkthrough |

All workflows documented in `docs/workflows/`. Each file: Purpose → Quick Nav → Steps → Commands → Data Flow.

### Build Commands (Quick Reference)

```bash
.venv/bin/python -m src.build.build_json   # Generate API JSON (skills, stats, tags, by-tag, by-tier, packages)
.venv/bin/python -m src.build.build_html   # Update HTML meta + sitemap + robots
python3 scripts/build/build_packages.py                  # Rebuild source package files in data/packages/ (optional/manual)
python3 scripts/build/build_priority.py                  # Rebuild source priority indexes in data + site/api (optional/manual)
python3 scripts/review/health_check.py                   # Skills manager dashboard
python3 scripts/crawl/crawl_state.py show                # View crawl state for all hubs
python3 scripts/verify/run_verify_strict_5agent.py --limit 50  # Full 5-agent deterministic verification
python3 scripts/build/build_indexes.py                   # Rebuild agent-access indexes (manifest, by-status, by-risk, verify-queue, lookup)
```

## Key Conventions

- **schemas.py is the single source of truth** — All data models live here. Read it before modifying any data pipeline.
- **AGENTS.md controls parallel execution** — Use file ownership to avoid overlap and drift.
- **Static-first** — The site runs on GitHub Pages ($0). No server-side rendering. All JSON pre-built.
- **Agent-first** — entry.md is for agents. Humans use index.html. Design for machines first.
- **Stars = priority** — Skills sorted by GitHub stars everywhere. High-star skills get verified first.
- **TAG_ALIASES in build_json.py** — Maps abbreviated tags to canonical IDs. Check this when tags don't match.
- **Commit-pinned installs** — Skills link to verified commit hashes, not latest.
- **Status normalization is mandatory** — Canonical statuses are `pass`, `fail`, `manual_review`, `unverified`, `updated_unverified`.
- **No API keys in the pipeline** — All verification runs locally. Agents A/B/D/E use prepare()/validate_and_override() pattern.
- **Three verification levels** — `full_pipeline` (5 agents), `scanner_only` (C* only), `metadata_only` (no clone). Don't conflate them.
- **scripts/verify/run_verify_strict_5agent.py is the primary runner** — Full 5-agent deterministic verification. Use this, not pipeline.py.

## Security Rules

- Agent C* (static scanner) is deterministic — semgrep + regex only, no LLM. Cannot be prompt-injected.
- All Pydantic string fields have max_length caps to prevent injection propagation.
- Never trust crawler output — always validate through sanitizer before writing to data/skills/.
- Risk levels: info < low < medium < high < critical.

## Data Integrity Rules

- **No duplicate skills allowed.** Before adding a skill, check if its `repo_url` already exists in `data/skills/`. If it does, update the existing entry — never create a second file for the same repo.
- When re-verifying a skill, update the existing file in-place. Do not create a new entry alongside the old one.
- If duplicates are found, keep the entry with the deeper `verification_level` (full_pipeline > scanner_only > metadata_only). Delete the other.
- Deduplication check: `python3 -c "import json,glob,collections; repos=collections.Counter(json.load(open(f)).get('repo_url','') for f in glob.glob('data/skills/*.json')); print([r for r,c in repos.items() if c>1 and r])"`

## Crawl Agent Rules (MANDATORY)

Every agent that discovers or imports new skills MUST follow these rules:

1. **No duplicates** — Before adding ANY skill, check if its `repo_url` already exists in `data/skills/`. If it does, update the existing entry. Never create a second file.
2. **Check reachability** — Before adding a new skill, verify the repo is reachable: `git ls-remote --exit-code --heads <repo_url>` (returncode 0 = reachable). Tag unreachable repos with `repo_unavailable`.
3. **Tag unavailable repos** — If a repo returns non-zero from `git ls-remote`, add `repo_unavailable` to its `tags` array and set `repo_status: "unavailable"` and `repo_check_date` to current ISO timestamp.
4. **Never import known unavailable** — If a skill already has `repo_unavailable` tag, do not re-import it. Skip it during crawl.
5. **Reachability check script** — `python3 scripts/crawl/check_reachability.py` can batch-check all repos. Use `--recheck` to re-test previously unavailable repos (they may come back online).
6. **Normalize legacy tags** — The old `clone_failure` tag is deprecated. Use `repo_unavailable` instead. TAG_ALIASES in build_json.py maps `clone_failure` → `repo_unavailable`.

### Reachability Quick Reference
```bash
python3 scripts/crawl/check_reachability.py --report          # See current stats
python3 scripts/crawl/check_reachability.py --only-untagged   # Check new skills only
python3 scripts/crawl/check_reachability.py --recheck         # Re-test unavailable repos
python3 scripts/crawl/check_reachability.py --limit 100       # Quick sample check
```
