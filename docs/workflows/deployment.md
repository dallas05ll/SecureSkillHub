# Deployment Workflow

How the site gets deployed to production.

## Quick Nav

- [CI/CD Pipeline](#cicd-pipeline) — automatic deployment
- [Manual Deploy](#manual-deploy) — when CI isn't enough
- [Full Refresh Sequence](#full-refresh-sequence) — end-to-end data pipeline

---

## CI/CD Pipeline

**File:** `.github/workflows/deploy.yml`

Triggered on push to `main` branch (or manual `workflow_dispatch`).

**Job 1: `build`** (runs on ubuntu-latest)
1. Checkout repository
2. Set up Python 3.11
3. Install dependencies (`pip install -r requirements.txt`)
4. Build JSON API (`python -m src.build.build_json`)
5. Build HTML/SEO assets (`python -m src.build.build_html`)
6. Configure GitHub Pages (`actions/configure-pages@v4`)
7. Upload Pages artifact (`actions/upload-pages-artifact@v3`, path: `site`)

**Job 2: `deploy`** (depends on `build`)
1. Deploy to GitHub Pages (`actions/deploy-pages@v4`)

**Concurrency:** Only one deployment runs at a time (`cancel-in-progress: true`).

**Permissions:** `contents: read`, `pages: write`, `id-token: write`.

**Important:** CI only runs build_json and build_html. It does NOT run crawlers, verification, enrichment, or package building. Those must be run locally before pushing.

---

## Manual Deploy

If you need to deploy without CI:

```bash
# Build locally
.venv/bin/python -m src.build.build_json
.venv/bin/python -m src.build.build_html

# Commit and push
git add site/
git commit -m "Rebuild site"
git push origin main
# CI picks up the push and deploys
```

---

## Full Refresh Sequence

Complete end-to-end pipeline — from crawling to deployment:

```bash
# 1. Crawl new skills (reachability check is now inline — dead repos are auto-skipped)
python3 run_crawl.py --max-pages 20
python3 process_discovered.py --merge      # ⚠️ ALWAYS use --merge for incremental updates
                                           # Includes inline reachability check (use --skip-reachability to bypass)

# 1b. Check existing collection for dead repos (optional, periodic)
python3 check_reachability.py --only-untagged   # Tag newly-dead repos
python3 check_reachability.py --recheck         # Recovery check for previously-dead repos

# 2. Enrich metadata
python3 enrich_stars.py --skip-existing
python3 auto_tag.py

# 3. Verify (skip repo_unavailable skills — they can't be cloned)
python3 run_verify_strict_5agent.py --only-unverified --limit 50   # Full 5-agent pipeline
python3 run_verify_sample.py --only-unverified --limit 50          # Scanner-only (faster)
python3 batch_verify_agent_skills.py       # ⚠️ Also auto-runs build_json + build_html

# 3b. Skills Manager review (post-verification)
python3 skills_manager_review.py --run-report data/verification-runs/<latest>.json
# For manual_review results, PM auto-reviews:
python3 skills_manager_review.py --manual-review-queue --limit 20

# 4. Fix data quality issues
python3 fix_data_quality.py

# 5. Build packages (optional)
python3 build_packages.py

# 6. Build priority indexes (optional)
python3 build_priority.py

# 7. Build site (required)
.venv/bin/python -m src.build.build_json
.venv/bin/python -m src.build.build_html
python3 build_indexes.py                              # Agent-access indexes

# 8. Review skills manager log
python3 health_check.py --history 5

# 9. Commit and deploy
git add data/ site/
git commit -m "Full refresh: crawl + verify + build"
git push origin main
```

**Time estimate guidance:** Steps 1-3 are the most time-consuming (network-bound). Steps 4-7 run in seconds. Step 8 triggers CI deployment.
