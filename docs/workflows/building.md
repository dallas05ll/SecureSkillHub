# Building Workflow

How the static site and API are generated from source data.

## Quick Nav

- [Build Steps](#build-steps) — what to run and in what order
- [Build Overlap](#build-overlap) — build_priority vs build_json
- [What Gets Built](#what-gets-built) — output files and directories
- [Commands](#commands) — copy-paste commands

---

## Build Steps

Run in this order:

| Step | Script | What It Does | Required? |
|------|--------|-------------|-----------|
| 1 | `python3 scripts/build/build_packages.py` | Rebuilds `data/packages/*.json` from tag hierarchy + skill data | Optional/manual |
| 2 | `python3 scripts/build/build_priority.py` | Rebuilds `data/verify-queue.json` plus star-sorted `site/api/skills/by-tag/`, `by-tier/`, `index.json` | Optional/manual |
| 3 | `.venv/bin/python -m src.build.build_json` | Generates all API JSON: skills, stats, tags, by-tag, by-tier, packages | **Required** |
| 4 | `.venv/bin/python -m src.build.build_html` | Updates HTML meta tags, sitemap.xml, robots.txt | **Required** |
| 5 | `python3 scripts/build/build_indexes.py` | Generates agent-access indexes (manifest, by-status, by-risk, lookup, verify-queue) | **Recommended** |

Steps 1-2 are optional preparatory steps. Steps 3-4 are the canonical build. Step 5 builds compact indexes for efficient agent access.

---

## Build Overlap

```
⚠️ scripts/build/build_priority.py and build_json.py BOTH generate site/api/skills/by-tag/ and by-tier/.
   scripts/build/build_priority.py is standalone (manual, optional) — use for quick index updates.
   build_json.py is the canonical build — always run this before deploy.
   If you run both, build_json.py output wins (runs second, overwrites).
```

**Why both exist:**
- `scripts/build/build_priority.py` was created for quick standalone index updates without a full rebuild
- `build_json.py` is the complete build that also generates skills, stats, tags, and packages
- For deploys, always use `build_json.py` — it's the canonical build

---

## What Gets Built

`build_json.py` outputs:

```
site/api/
├── skills/
│   ├── {skill-id}.json        — Individual skill detail pages
│   ├── index.json             — Full skill listing
│   ├── by-tag/{tag-id}.json   — Skills filtered by tag
│   └── by-tier/{tier}.json    — Skills filtered by star tier
├── stats.json                 — Hub-wide statistics
├── tags.json                  — Tag hierarchy
└── packages/
    ├── index.json             — Package listing
    └── {package-id}.json      — Individual packages
```

`scripts/build/build_indexes.py` outputs:

```
site/api/indexes/
├── manifest.json              — Compact per-skill summary (id, name, status, score, stars)
├── by-status.json             — Skill IDs grouped by verification_status
├── by-risk.json               — Skill IDs grouped by risk_level
├── verify-queue.json          — Unverified skills tiered by stars (entry: id, name, stars)
└── lookup.json                — Hash-based prefix lookup for O(1) skill access
```

Queue semantics:

- `data/verify-queue.json` (from `scripts/build/build_priority.py`) is script-facing and contains richer summaries in `queue[]`.
- `site/api/indexes/verify-queue.json` (from `scripts/build/build_indexes.py`) is API-facing and contains compact tier lists for agents.
- Both queues currently include only `verification_status == "unverified"` items.

`build_html.py` outputs:

```
site/
├── index.html                 — Updated meta tags
├── sitemap.xml                — Search engine sitemap
└── robots.txt                 — Crawler directives
```

**Important:** Files in `site/api/` are generated — do not hand-edit them.

---

## Commands

```bash
# Full build (canonical)
.venv/bin/python -m src.build.build_json   # Generate API JSON
.venv/bin/python -m src.build.build_html   # Update HTML assets

# Optional preparatory steps
python3 scripts/build/build_packages.py                  # Rebuild source package files (top 10 per tag)
python3 scripts/build/build_packages.py --top 20         # More skills per package
python3 scripts/build/build_priority.py                  # Rebuild priority indexes (standalone)

# Build agent-access indexes
python3 scripts/build/build_indexes.py                   # All indexes
python3 scripts/build/build_indexes.py --only manifest   # Just the compact manifest

# Complete refresh (run all in order)
python3 scripts/build/build_packages.py && \
python3 scripts/build/build_priority.py && \
.venv/bin/python -m src.build.build_json && \
.venv/bin/python -m src.build.build_html && \
python3 scripts/build/build_indexes.py
```
