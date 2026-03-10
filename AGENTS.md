# SecureSkillHub — Parallel Agent Execution Contract

This file is the **canonical workflow contract** for multi-agent work in this repo.
Use it to prevent agent drift, duplicated ad-hoc work, and inconsistent outputs.

## 1) Canonical Sources

**Primary entry point:** `CLAUDE.md` (auto-loaded by Claude Code). It has the full canonical file table, Quick Nav, and project structure.

**This file** adds parallel execution rules and file ownership. Read it when working in multi-agent mode.

Other key files:
- `docs/design/vision.md` — project north star
- `docs/design/principles.md` — 22 design constraints
- `docs/design/verification-architecture.md` — 5-agent pipeline architecture
- `STRATEGY.md` — roadmap direction (not implementation truth)
- `site/entry.md` — external agent/human discovery entry point (not for internal agents)

If docs conflict: **code + CLAUDE.md + schemas win**, then update stale docs.

## 2) Project Structure

See `CLAUDE.md` for the full project structure. Key rule: `site/api/**` is generated output — do not hand-edit it.

## 3) Parallel Agent Workstreams

Assign each spawned agent to exactly one workstream:

- **WS1 Crawler/Data Intake** *(Named role: SM)*
  - Owns: `src/crawler/**`, `scripts/crawl/run_crawl.py`, `scripts/crawl/run_pending_crawlers.py`, `scripts/crawl/crawl_agent_skills.py`, `scripts/crawl/crawl_state.py`, `scripts/crawl/import_agent_skills.py`, `scripts/crawl/process_discovered.py`, `scripts/enrich/enrich_stars.py`, `scripts/enrich/auto_tag.py`, `scripts/crawl/check_reachability.py`
  - May write: `data/discovered/**`, `data/claudeskills_info_complete.json`, `data/crawl-state.json`
- **WS2 Verification (VM)**
  - Owns: `src/scanner/**`, `src/sanitizer/**`, `src/verification/**`, `scripts/verify/run_verify_sample.py`, `scripts/verify/run_verify_strict_5agent.py`, `scripts/verify/batch_verify_agent_skills.py`, `scripts/verify/audit_verification_paths.py`, `scripts/verify/backfill_verification_level.py`
  - May write: `data/scan-reports/**`, `data/verification-runs/**`, `data/skills/**` (verification fields only), `data/skill-manager-log.json` (verification_run entries)
  - Receives requests from: SM (skill selection), PM (trigger)
  - Hands results to: SM (SM-A/SM-B review)
  - Never reviews own output (SM does that). Never decides what to verify (SM does that).
  - See `roles/VERIFICATION_MANAGER.md` for full role definition
- **WS3 Build/Indexing**
  - Owns: `src/build/**`, `scripts/build/build_packages.py`, `scripts/build/build_priority.py`, `scripts/build/build_indexes.py`, `scripts/build/fix_data_quality.py`
  - May write: `site/api/**`, `site/sitemap.xml`, `site/robots.txt`, `data/packages/**`
- **WS4 Frontend/UX (Frontend Manager)**
  - Owns: `site/index.html`, `site/docs.html`, `site/css/**`, `site/js/**`, `site/profile.html`
  - Must not hand-edit generated JSON
  - See `roles/FRONTEND_MANAGER.md` for full role definition
  - Coordinates with: WS3 (data), WS6 AXM (entry.md), WS7 DM (deploy)
- **WS5 API (Cloudflare Worker)** *(Named role: AXM)*
  - Owns: `api/**`
- **WS6 Agent Experience (AXM)**
  - Owns: `cli/**`, `site/entry.md`, `scripts/build/build_packages.py`, `data/packages/**`, `skills/*/SKILL.md`, `.claude-plugin/`, `scripts/build/build_plugin_catalog.py`, `scripts/build/build_marketplace.py`, `scripts/enrich/detect_plugin_repos.py`
  - May write: `site/api/packages/**`
  - Coordinates with: WS4 (frontend), WS3 (build pipeline)
- **WS7 Deploy (DeployM)**
  - Owns: `.github/workflows/**`, `.gitignore`
  - May write: any file (during commit/deploy operations)
  - Executes deploys on PM instruction. Does not decide what to deploy.
  - Coordinates with: PM (approval), AXM (post-deploy testing), DocM (post-deploy Quick Nav check)
- **WS8 Documentation (DocM)**
  - Owns: `README.md`, `roles/DOCUMENTATION_MANAGER.md`
  - May write: any `.md` doc file (during doc-alignment fixes on PM instruction)
  - Maintains the **Global Quick Nav** in `roles/DOCUMENTATION_MANAGER.md` (master file map for all agents)
  - Fixes documentation drift when PM detects inconsistencies (PM detects → DocM fixes)
  - Other agents ask DocM when they can't find a file, doc, or section
  - Has up to **5 sub-agents** for parallel work
  - Coordinates with: PM (receives drift reports), DeployM (commits doc fixes), AXM (entry.md alignment)

If a task spans workstreams, split into separate agents with explicit handoff.

### Cross-Cutting Roles (not workstreams)

These roles oversee multiple workstreams but do not own exclusive file sets. They read from workstream outputs and write decisions/reviews.

- **Project Manager (PM)** — Manual review approvals, doc-alignment detection, goal tracking. See `roles/PROJECT_MANAGER.md`.
  - Reads from: all workstreams (approval authority)
  - Writes to: `data/skills/*.json` (PM review decisions), `data/skill-manager-log.json` (pm_review entries)
  - Detects doc drift → notifies DocM to fix
- **Skills Manager (SM)** — Catalog health, dual-agent SM-A/SM-B review, pipeline monitoring. See `roles/SKILLS_MANAGER.md`.
  - Owns: `scripts/review/skills_manager_review.py`, `scripts/review/health_check.py`
  - Reads from: WS1 (crawl results), VM (verification results), WS3 (build outputs)
  - Writes to: `data/skill-manager-log.json` (sm_review entries), `data/skills/*.json` (review decisions)
  - Selects what VM should verify (priority tiers). Reviews VM's output (SM-A/SM-B).
- **Verification Manager (VM)** — Pipeline execution, scanner maintenance, safety override guardian. See `roles/VERIFICATION_MANAGER.md`.
  - Owns: WS2 file set (src/scanner/**, src/sanitizer/**, src/verification/**, scripts/verify/run_verify_*.py)
  - Reads from: SM (verification requests), PM (trigger signals)
  - Writes to: `data/scan-reports/**`, `data/verification-runs/**`, `data/skills/**` (verification fields), `data/skill-manager-log.json`
  - Never reviews own output (SM does that). Never decides what to verify (SM does that).
- **Security Manager (SecM)** — PM's on-demand security consultant. False positive audit, pattern accuracy. See `roles/SECURITY_MANAGER.md`.
  - Owns: `scripts/secm/secm_false_positive_audit.py`, `scripts/secm/secm_pattern_test.py`, `data/secm-audit-log.json`, `data/pattern-test-cases/`
  - Reads from: WS2 (scan reports, regex_patterns.py), SM (skill data, skill-manager-log.json)
  - Writes to: `data/secm-audit-log.json`, `data/skill-manager-log.json` (secm_fp_audit / secm_pattern_audit entries)
  - Invoked by PM only. Not in the normal verification chain.
- **Memory Manager (MemM)** — Cross-role memory infrastructure, health auditor, 9 sub-agents. See `roles/MEMORY_MANAGER.md`.
  - Owns: `memory/structured/*.json` (all 9 structured memory files)
  - Reads from: all role memory files (unique cross-role visibility)
  - Writes to: `memory/structured/*.json` (maintenance: consolidation, archival, schema migration)
  - 4 Protocols: LOAD (before work), WRITE (after learning), EVOLVE (consolidation), HEALTH (integrity audit)
  - Sub-agents: MemM-PM, MemM-VM, MemM-SecM, MemM-SM, MemM-AXM, MemM-DocM, MemM-DplM, MemM-FrtM, MemM-Self
  - Reports to PM only. Does not decide corrections (PM + SecM do that).

### Pre-Approved Direct Handoffs

These routine operations are pre-approved by PM and do not require PM intermediation each time:

| From | To | Trigger | Scope |
|------|----|---------|-------|
| SM → AXM | After verification batch completes | "Rebuild packages" — AXM runs `build_packages.py` |
| DocM → DeployM | After doc-only fixes complete | Doc-only commits (no code/data changes). DeployM reviews diff is doc-only before committing |
| VM → DocM | After pattern fix implementation | "Pattern X changed — update pattern docs" notification |
| DeployM → FrontendM | After every deploy to production | "Verify human UI" — FrontendM runs visual QA |
| DeployM → AXM | After every deploy to production | "Verify agent endpoints" — AXM tests entry.md + API |
| Any Role → MemM | After writing to own memory | "Audit my write" — MemM sub-agent validates schema + checks contradictions |
| MemM → PM | After HEALTH or EVOLVE protocol | "Health report" / "Cross-role flag" — PM reviews and resolves |

**Rule:** Any handoff that changes verification status, scores, or makes pass/fail decisions still requires PM approval.

## 4) Non-Negotiable Consistency Rules

- No new top-level directories/files without explicit user approval.
- No schema bypass: all structured data contracts derive from `src/sanitizer/schemas.py`.
- No one-off data formats: reuse existing JSON shapes.
- No hardcoded duplicate logic when a builder already exists.
- Do not market features as complete if implementation is partial.
- Do not silently change verification semantics (`pass/fail/manual_review/unverified/updated_unverified`) without updating schema + build + UI.

## 5) Required Task Contract (before coding)

Every agent must declare:

- **Goal**
- **Owned files**
- **Out-of-scope files**
- **Validation commands**
- **Expected outputs**

If a needed file is out of scope, stop and request reassignment/handoff.

Use `AGENT_TASK_TEMPLATE.md` for this contract.

## 6) Build + Validation Gates

Run these after relevant changes:

- Python syntax:
  - `.venv/bin/python -m py_compile src/build/build_json.py src/build/build_html.py scripts/verify/run_verify_sample.py`
- Frontend syntax:
  - `node --check site/js/app.js`
- Build:
  - `.venv/bin/python -m src.build.build_json`
  - `.venv/bin/python -m src.build.build_html`
- Verification:
  - `SM_TARGETS=$(python3 scripts/review/sm_select_targets.py --limit 5 --output-ids) && .venv/bin/python scripts/verify/run_verify_strict_5agent.py --skill-ids "$SM_TARGETS"`
- Smoke:
  - `python3 -m http.server 4173 --directory site`
  - Verify `/`, `/api/stats.json`, `/api/skills/index.json`, `/api/search-index.json`

## 7) Anti-Drift Checklist

Before finishing any multi-agent batch:

- [ ] Did each agent stay inside owned files?
- [ ] Any duplicate logic introduced?
- [ ] Any generated files hand-edited?
- [ ] Are stats/index/package counts internally consistent?
- [ ] Are docs aligned with actual behavior?
- [ ] Is there a concise handoff report with file list + commands run?

## 8) Handoff Report Format

Use this exact structure:

1. Summary of changes
2. Files changed
3. Commands run and result
4. Known risks
5. Next owner (if handoff needed)
