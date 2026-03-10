# Agent Experience Manager (AXM) — Memory

## Plugin Ownership

AXM owns `.claude-plugin/` — the SecureSkillHub Claude Code plugin.

| File | Purpose |
|------|---------|
| `.claude-plugin/plugin.json` | Plugin manifest: name="secureskillhub", version="0.1.0" |
| `skills/browse/SKILL.md` | Browse skill: embedded catalog map for in-context navigation without fetching |
| `skills/search/SKILL.md` | Search skill: fetches search-index.json, keyword match against names + tags |
| `skills/install/SKILL.md` | Install skill: fetches skill JSON by ID, shows verification + install + safety |
| `scripts/build/build_plugin_catalog.py` | Regenerates browse.md catalog section from live data/skills/ |

## Build Command

Run after every `build_json` to keep the browse.md catalog section current:

```bash
python3 scripts/build/build_plugin_catalog.py
```

## The 3 Skills

### browse (secureskillhub)
- user-invocable: true
- Loads full catalog structure into context — no fetch needed for browsing
- Embedded catalog map with real counts from data/skills/ (not from by-tag index)
- Calls WebFetch only when user wants a specific category's full skill list or skill detail
- By-tag fetch URL: `https://dallas05ll.github.io/SecureSkillHub/api/skills/by-tag/{tag-id}.json`
- Skill detail URL: `https://dallas05ll.github.io/SecureSkillHub/api/skills/{skill-id}.json`

### search (secureskillhub-search)
- user-invocable: true
- Fetches `https://dallas05ll.github.io/SecureSkillHub/api/search-index.json`
- search-index.json is a flat JSON array (NO top-level wrapper keys)
- Each entry: `{id, name, tags, description, stars, overall_score, verification_status, skill_type}`
- verification_status values: "pass" or "unverified" — there is NO "scanned" value in this index

### install (secureskillhub-install)
- user-invocable: true
- Accepts skill name or skill ID as $ARGUMENTS
- Looks up ID via search-index if given a name; fetches skill detail directly if given an ID
- MUST warn on unverified skills and high/critical risk_level — these warnings must not be removed

## Issues Found and Fixed (2026-03-04)

### 1. build_plugin_catalog.py regex pattern mismatch (FIXED)
- **Bug**: Script searched for `---\n\n## How to Help` but browse.md has `---\n\n## How to Help Users`
- **Effect**: Script always printed "WARNING: No replacement made" and wrote nothing
- **Fix**: Updated pattern to `---\n\n## How to Help Users`; also switched `re.sub` to use a lambda to prevent backslash interpretation in replacement string; removed the false equality check warning

### 2. browse.md overview stats were stale (FIXED)
- **Was**: "6,300+ total skills, 653 verified"
- **Now**: "9,500+ available (11,100+ total), 4,473 verified"
- **Root cause**: Stats were from before PM's large-scale manual review clearance (March 2026)

### 3. [SCANNED] badge referenced non-existent status (FIXED in browse.md and search.md)
- **Bug**: browse.md and search.md described a `[SCANNED]` badge mapped to a "scanned" verification_status
- **Reality**: search-index.json only contains `verification_status: "pass"` or `"unverified"`
- **Fix**: Removed [SCANNED] from badge tables; updated to show only [VERIFIED] and [UNVERIFIED]

## Key Facts

- **Catalog counts (2026-03-04)**: 11,098 total files, 9,523 available (not repo_unavailable), 4,473 pass
- **Catalog counts via build script** (reads raw data/skills/): dev=2,743, data=1,938, utilities=871
- **Catalog counts via by-tag index** (post TAG_ALIASES expansion): dev=2,939, data=2,259, utilities=5,018
  - Discrepancy is because build_json.py expands parent tags and handles TAG_ALIASES; build script reads raw tags
- **search-index.json**: flat array of 11,098 entries; fields: id, name, tags, description, stars, overall_score, verification_status, skill_type
- **by-tag API**: `site/api/skills/by-tag/{tag-id}.json` — returns `{tag, total, verified, top_stars, skills[]}`
- **by-tag/index.json**: top-level keys are `tags`, `by_category`, `sorted_by_count`

## Build Script Technical Notes

- Reads raw tags from `data/skills/*.json` directly (skips `repo_unavailable` tagged skills)
- Does NOT expand TAG_ALIASES — counts differ from `site/api/skills/by-tag/index.json`
- Regex markers: `## Full Catalog Map` (start) and `---\n\n## How to Help Users` (end)
- Uses `re.sub(pattern, lambda m: replacement, content, flags=re.DOTALL)` — lambda prevents backslash interpretation
- Reports "Available skills", "Verified skills", "Total files", "Tags with skills" on success
