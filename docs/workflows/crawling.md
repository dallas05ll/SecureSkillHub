# Crawling Workflow

How skills are discovered and collected from external hubs.

## Quick Nav

- [Current Crawlers](#current-crawlers) — what hubs exist, what's been crawled
- [Current Process](#current-process) — how crawling works today
- [Reachability Checks](#reachability-checks) — inline filtering of dead repos
- [Target Process](#target-process) — 2-agent pattern (not yet implemented)
- [Hub Discovery](#hub-discovery) — finding and registering new hubs
- [Crawl State](#crawl-state) — data/crawl-state.json format
- [Commands](#commands) — copy-paste commands to run
- [Data Flow](#data-flow) — what goes where

---

## Current Crawlers

| Hub | Crawler File | Runner | Status | Collected | Trust |
|-----|-------------|--------|--------|-----------|-------|
| mcp.so | `src/crawler/mcp_so.py` | `run_crawl.py` | Done | 5,421 | LOW — unvetted directory |
| Glama.ai | `src/crawler/glama.py` | `run_crawl.py` | Done | 51 | MEDIUM — curated |
| GitHub Search | `crawl_agent_skills.py` | Direct CLI | Done | 499 | MEDIUM — GitHub topics/code search |
| ClaudeSkills.info | `src/crawler/claudeskills.py` | None (import only) | Partial | 76 | MEDIUM — curated |
| Skills.sh | `src/crawler/skills_sh.py` | None | Pending | 0 | MEDIUM — Snyk scanning |
| SkillsMP | `src/crawler/skillsmp.py` | None | Pending | 0 | LOW — 96K+ unvetted aggregator |

**Total skills collected:** 6,047

---

## Current Process

How crawling actually works today (not aspirational):

### Path 1: Batch Pipeline (mcp.so + Glama)

```
run_crawl.py
  → runs GlamaCrawler + MCPSoCrawler in parallel (asyncio)
  → each crawler writes to data/discovered/batch-{source}-{timestamp}.json
  → process_discovered.py merges batches into data/skills/
     - deduplication by repo_url
     - generates deterministic skill IDs
     - ✅ REACHABILITY CHECK: filters out unreachable repos before writing
     - logs results to skills manager (data/skill-manager-log.json)

⚠️ CRITICAL: process_discovered.py has TWO modes:
   - `python3 process_discovered.py --merge` → preserves existing stars, verification, scan data
   - `python3 process_discovered.py` (no flag) → DELETES ALL existing skill files first
   Always use --merge for incremental updates.
   Use --skip-reachability to skip the reachability check (faster but includes dead repos).
```

### Path 2: Direct Write (GitHub Search)

```
crawl_agent_skills.py
  → uses `gh` CLI to search GitHub topics + code
  → ✅ DEDUP CHECK: skips repos already in data/skills/
  → ✅ REACHABILITY CHECK: filters out unreachable repos before writing
  → writes only reachable new skills to data/skills/
  → logs results to skills manager (data/skill-manager-log.json)
```

### Path 3: Static Import (ClaudeSkills)

```
import_agent_skills.py
  → reads a static JSON dump from ClaudeSkills.info
  → maps categories to our tag hierarchy
  → writes to data/skills/ with skill_type="agent_skill"
```

### Path 4: Not Yet Run

`src/crawler/skills_sh.py` and `src/crawler/skillsmp.py` exist as crawler classes but have no runner script. They would need to be added to `run_crawl.py` or get their own runner.

---

## Reachability Checks

Every crawl path now checks repo reachability BEFORE writing to `data/skills/`. This prevents dead repos from entering the collection.

### How It Works

```
Crawl discovers repo_url
  → git ls-remote --exit-code --heads <repo_url>
  → returncode 0 = reachable → write to data/skills/
  → returncode != 0 = unreachable → SKIP (do not write)
  → log result to data/skill-manager-log.json
```

### Shared Module: `src/reachability.py`

All crawl scripts import from `src/reachability.py`:

| Function | Purpose |
|----------|---------|
| `check_repo(url)` | Test single repo reachability (15s timeout) |
| `check_and_filter_skills(skills, source)` | Batch check with thread pool, returns (reachable, unreachable) |
| `mark_unavailable(skill_data)` | Add `repo_unavailable` tag to skill dict (in-memory) |
| `is_unavailable(skill_data)` | Check if already tagged |
| `log_to_skill_manager(type, findings)` | Append entry to skills manager log |

### Batch Reachability (post-save)

For skills already in the collection, use `check_reachability.py`:

```bash
python3 check_reachability.py --report          # View stats
python3 check_reachability.py --only-untagged   # Check new skills only
python3 check_reachability.py --recheck         # Re-test unavailable repos (recovery)
```

### Stats (as of 2026-02-28)

- **1,556 / 6,307** skills have unreachable repos (24.7%)
- Tagged with `repo_unavailable` in their skill JSON
- Visible on frontend with red "Unavailable" badge
- Filterable via "Hide unavailable" toggle

---

## Target Process

**`[NOT YET IMPLEMENTED]`** — This is the planned 2-agent crawl pattern.

### Agent 1 — Evaluator

Reads `data/crawl-state.json`, evaluates hub quality, estimates yield, decides go/no-go.

```
Input: data/crawl-state.json + hub metadata
Decision: Should we crawl this hub? How many pages? What's the expected yield?
Output: Crawl plan (hub_key, max_pages, expected_skills, priority)
```

### Agent 2 — Crawler

Executes the actual crawl, processes results, updates state.

```
Input: Crawl plan from Evaluator
Execution: run_crawl.py or individual crawler
Post-processing: process_discovered.py → merge into data/skills/
Output: Updated data/crawl-state.json with results
```

### Why 2 Agents?

Separation prevents a single agent from both deciding to crawl a low-quality hub AND executing the crawl without oversight. The evaluator catches bad decisions before resources are spent.

---

## Hub Discovery

To register a new skill hub:

1. Add a crawler class in `src/crawler/` extending `BaseCrawler`
2. Register the hub using `crawl_state.py` (preferred) or edit `data/crawl-state.json` manually:
   ```bash
   python3 crawl_state.py add-hub new_hub_key \
     --url https://example.com \
     --crawler src/crawler/new_hub.py \
     --trust LOW \
     --notes "Description of the hub"
   ```
   This adds the hub inside the `"hubs"` object in `data/crawl-state.json`. If editing manually, ensure the entry is nested under `"hubs"`:
   ```json
   {
     "hubs": {
       "new_hub_key": {
         "url": "https://example.com",
         "crawler": "src/crawler/new_hub.py",
         "status": "pending",
         "total_collected": 0,
         "pages_crawled": 0,
         "last_crawl": null,
         "trust_level": "LOW",
         "notes": "Description of the hub"
       }
     }
   }
   ```
3. Add the crawler to `run_crawl.py` imports and `crawlers` list
4. Run a test crawl: `python3 run_crawl.py --max-pages 2`

---

## Crawl State

Tracked in `data/crawl-state.json`. See that file for current state of all 6 sources.

Use `crawl_state.py` to read/update:

```bash
python3 crawl_state.py show                          # Print formatted state
python3 crawl_state.py mark-done mcp_so --total 5421 --pages 115
python3 crawl_state.py mark-partial claude_skills_hub --total 76 --pages 1
python3 crawl_state.py add-hub new_hub --url https://example.com --crawler src/crawler/new.py
```

---

## Commands

```bash
# Run active crawlers (Glama + mcp.so)
python3 run_crawl.py --max-pages 10

# Process discovered batches into data/skills/
python3 process_discovered.py --merge                   # ⚠️ ALWAYS use --merge for incremental updates
python3 process_discovered.py --merge --limit 100       # Limit to first 100 skills (for testing)
# python3 process_discovered.py                         # ⚠️ WITHOUT --merge: deletes ALL existing files

# Crawl GitHub for agent skills
python3 crawl_agent_skills.py                           # Default: up to 500 skills
python3 crawl_agent_skills.py --limit 50                # Limit collection size

# Import from ClaudeSkills.info static dump
python3 import_agent_skills.py                          # Reads data/claudeskills_info_complete.json

# Check crawl state
python3 crawl_state.py show
```

---

## Data Flow

```
                    ┌──────────────┐
                    │  run_crawl.py│
                    │ (Glama+mcp.so)│
                    └──────┬───────┘
                           │ batch JSON
                           ▼
              ┌──────────────────────┐
              │ data/discovered/     │
              │ batch-*.json         │
              └──────────┬───────────┘
                         │
                         ▼
              ┌──────────────────────┐
              │ process_discovered.py│──────────────┐
              │ (merge + dedup)      │              │
              └──────────┬───────────┘              │
                         │                          │
                         ▼                          │
              ┌──────────────────────┐              │
              │ data/skills/*.json   │◄─────────────┤
              │ (source of truth)    │              │
              └──────────────────────┘              │
                         ▲                          │
                         │ direct write             │
              ┌──────────┴───────────┐   ┌─────────┴──────────┐
              │crawl_agent_skills.py │   │import_agent_skills.py│
              │ (GitHub search)      │   │ (ClaudeSkills dump)  │
              └──────────────────────┘   └──────────────────────┘
```
