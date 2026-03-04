# Enrichment Workflow

How skills are enriched with additional metadata after collection.

## Quick Nav

- [Star Enrichment](#star-enrichment) — GitHub star counts
- [Auto-Tagging](#auto-tagging) — keyword-based tag assignment
- [Commands](#commands) — copy-paste commands

---

## Star Enrichment

**Script:** `scripts/enrich/enrich_stars.py`

Fetches GitHub star counts for all skills with `repo_url` pointing to github.com. Uses the `gh api` CLI (authenticated, 5,000 req/hr limit).

**How it works:**
1. Loads all skill JSON files from `data/skills/`
2. Filters to skills with GitHub URLs (optionally skips skills that already have stars)
3. Calls `gh api repos/{owner}/{repo}` → extracts `stargazers_count`
4. Updates `stars` field in-place
5. Rate-limited: 0.1s delay between requests

**Star distribution tiers** (used for verification priority):
- 1,000+: Tier 1 (verify first)
- 100-999: Tier 2
- 10-99: Tier 3
- 0-9: Tier 4

**skillsmp skills:** All 4,801 skills from the skillsmp crawler arrive with `stars: 0` because the GitHub mirror does not include star data. Always run `enrich_stars.py --skip-existing` after a skillsmp crawl to populate real star counts before running verification priority queues.

---

## Auto-Tagging

**Script:** `scripts/enrich/auto_tag.py`

Assigns tags from the 4-layer tag hierarchy (`data/tags.json`) based on keyword patterns in the skill's name and description.

**How it works:**
1. Matches skill `name + description` (lowercased) against `TAG_RULES` keyword lists
2. Each rule: `(tag_id, [keywords])` — if any keyword matches, tag is assigned
3. Skills matching no rules get `util` (if "mcp" in text) or `integ` (if "server" in text)
4. Overwrites the `tags` field in each skill JSON

**Tag categories:** dev, data, prod, integ, sec, util — each with 2-4 levels of nesting.

**Important:**
- Auto-tagging **overwrites existing tags**. If a skill has manually curated tags, they will be replaced.
- `scripts/enrich/auto_tag.py` uses a relative path (`Path("data/skills")`) — **must be run from the project root directory**.
- The `installs:N` tag format (e.g., `installs:1000`) encodes install count as a tag for skills sourced from platforms that track installs (such as skillsmp). These are preserved through auto-tagging and displayed as a metadata signal separate from GitHub stars. Do not remove or rename `installs:*` tags — they are used by the build pipeline for display and sorting.

---

## Commands

```bash
# Enrich star counts
python3 scripts/enrich/enrich_stars.py                    # All skills (overwrites existing stars, batch-size=50)
python3 scripts/enrich/enrich_stars.py --skip-existing    # Only skills with stars=0 or missing
python3 scripts/enrich/enrich_stars.py --batch-size 100   # Larger batches (default: 50)

# Auto-tag skills
python3 scripts/enrich/auto_tag.py                        # Tag all skills (overwrites existing tags)
```
