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

- **WS1 Crawler/Data Intake**
  - Owns: `src/crawler/**`, `run_crawl.py`, `crawl_agent_skills.py`, `import_agent_skills.py`, `process_discovered.py`, `enrich_stars.py`, `auto_tag.py`, `check_reachability.py`
  - May write: `data/discovered/**`, `data/claudeskills_info_complete.json`
- **WS2 Security/Verification**
  - Owns: `src/scanner/**`, `src/sanitizer/**`, `src/verification/**`, `run_verify_sample.py`, `run_verify_strict_5agent.py`, `batch_verify_agent_skills.py`
  - May write: `data/scan-reports/**`, `data/verification-runs/**`, `data/skills/**`, `data/stats.json`
- **WS3 Build/Indexing**
  - Owns: `src/build/**`, `build_packages.py`, `build_priority.py`, `build_indexes.py`, `fix_data_quality.py`
  - May write: `site/api/**`, `site/sitemap.xml`, `site/robots.txt`, `data/packages/**`
- **WS4 Frontend/UX**
  - Owns: `site/index.html`, `site/docs.html`, `site/entry.md`, `site/css/**`, `site/js/**`
  - Must not hand-edit generated JSON
- **WS5 API/CLI**
  - Owns: `api/**`
- **WS6 Agent Experience (AXM)**
  - Owns: `cli/**`, `site/entry.md`, `build_packages.py`, `data/packages/**`
  - May write: `site/api/packages/**`
  - Coordinates with: WS4 (frontend), WS3 (build pipeline)
- **WS7 Deploy (DM)**
  - Owns: `.github/workflows/**`, `.gitignore`
  - May write: any file (during commit/deploy operations)
  - Executes on PM instruction only. Does not decide what to deploy.
  - Coordinates with: PM (approval), AXM (post-deploy testing)

If a task spans workstreams, split into separate agents with explicit handoff.

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
  - `.venv/bin/python -m py_compile src/build/build_json.py src/build/build_html.py run_verify_sample.py`
- Frontend syntax:
  - `node --check site/js/app.js`
- Build:
  - `.venv/bin/python -m src.build.build_json`
  - `.venv/bin/python -m src.build.build_html`
- Verification:
  - `python3 run_verify_strict_5agent.py --limit 5 --only-unverified`
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
