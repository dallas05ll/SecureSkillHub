# SecureSkillHub -- Agent Entry Point

SecureSkillHub is a security-first directory of AI-agent skills and MCP servers with verification metadata. It covers **two catalogs**:

1. **Agent Skills** -- SKILL.md instruction packages that teach agents how to perform tasks (coding patterns, workflows, best practices)
2. **MCP Servers** -- Model Context Protocol servers that connect agents to external tools and services (databases, APIs, search)

Verified skills in this catalog are analysed by a multi-agent verification pipeline that compares documentation claims against actual code behaviour, runs deterministic security scans, scores trustworthiness, and flags hidden capabilities. Unverified skills are explicitly labeled.

This file is the machine-readable entry point. If you are an AI agent helping a user discover skills, follow the instructions below.

**Discovery**: This file is available at `entry.md` (relative to site root). A machine-readable config is at `.well-known/agent.json`. Do NOT parse `index.html` — it is a human-facing frontend.

For repository operators: this file is discovery/API guidance, while executable verification operations live in `docs/workflows/verification.md`.

---

## Step 0: Choose a catalog

Before browsing, determine what the user needs:

| Catalog | Type | Use When |
|---------|------|----------|
| `agent_skill` | SKILL.md packages | User wants coding expertise, workflows, best practices, templates |
| `mcp_server` | MCP protocol servers | User wants to connect to external services (DB, API, search, etc.) |
| `both` | All skills | User wants to browse everything |

To filter by catalog, use the `skill_type` field on any skill object.

---

## Quick-start flow

1. Ask the user: **"Are you looking for Agent Skills (expertise/workflows), MCP Servers (tool connections), or both?"**
2. Fetch `api/tags.json` to load the full category tree.
3. Show the top-level categories as options.
4. Navigate the **4-layer tag hierarchy**: Category -> Subcategory -> Specialization -> Stack.
5. Use `api/skills/by-tag/{tag}.json` for fast tag-filtered results (sorted by GitHub stars).
6. Use `api/skills/by-tier/{tier}.json` for popularity-based browsing (tier-1 = 1000+ stars).
7. When the user selects a skill, fetch its detail file for the available security summary and metadata.

---

## API endpoints

All endpoints return JSON and are relative to the site root.

### GET api/tags.json

Full tag navigation tree. Structure:

```
{ "version": "2.0",
  "updated_at": "<ISO-8601>",
  "categories": [ TagNode, ... ] }
```

Each `TagNode` has: `id`, `label`, `description`, `skill_count`, `children: [TagNode]`.

### GET api/skills/index.json

All skills (summarised), sorted by GitHub stars descending. Each entry:

```
{ "id", "name", "description", "overall_score", "verification_status",
  "verification_level", "risk_level", "tags": [...], "stars", "skill_type",
  "source_hub", "owner", "primary_language", "repo_url", "install_url",
  "verified_commit", "agents_completed" }
```

The index includes enough fields for most use cases -- you only need to fetch individual detail files for `findings_summary`, `agent_audit`, and `scan_date`.

Use this to filter, sort, or search across all skills without fetching each detail file. The `verification_level` field (`full_pipeline`, `scanner_only`, `metadata_only`, or null) indicates verification depth.

### GET api/skills/by-tag/{tag_id}.json

Skills filtered by a specific tag, sorted by stars. Faster than loading the full index.

```
{ "tag": "data-db",
  "total": 261, "verified": 21, "top_stars": 2486,
  "skills": [ ... ] }
```

**Tag discovery**: The tag tree (`api/tags.json`) has 71 official hierarchical nodes. However, 388 by-tag files exist including informal source tags (e.g., `accessibility`, `agent-orchestration`). You can request any by-tag file directly if you know the tag name -- not all appear in the tree.

An additional meta-index is available at `api/skills/by-tag/index.json` with three views:
- `tags`: per-tag statistics (total, verified, top_stars)
- `by_category`: tags grouped by top-level category
- `sorted_by_count`: all tags sorted by skill count descending

Use this to discover available tags beyond the hierarchical tree.

### GET api/skills/by-tier/{tier}.json

Skills grouped by GitHub star tier:

| Tier | Stars | Priority |
|------|-------|----------|
| `tier-1` | 1000+ | Verify immediately |
| `tier-2` | 100-999 | High priority |
| `tier-3` | 10-99 | Medium priority |
| `tier-4` | 1-9 | Standard |
| `tier-5` | 0 | Low priority |

### GET api/skills/{id}.json

Full detail for a single skill including:

- `repo_url`, `verified_commit`
- `install_url` -- specific install command URL (may be empty; use `repo_url` as fallback)
- `source_hub`, `trust_level`, `skill_type`
- `verification_status`, `overall_score`, `risk_level`
- `tags`, `stars`, `owner`, `primary_language`
- `findings_summary` -- dict with verification metadata (`scanner_findings`, `dangerous_calls`, `network_ops`, `file_ops`, `env_access`, `mismatches`, `undocumented_capabilities`, etc.)
- `scan_date` (`last_repo_update` may be present for some records)
- `agent_audit` -- Per-agent verification trail (when available). Structure:
  - `agents_completed`: number of agents that signed
  - `pipeline_run_at`: ISO timestamp of pipeline execution
  - `agent_a` through `agent_e`: each has `signed` (bool), `signed_at` (ISO), `comment` (string)
  - Use this to assess verification depth and read individual agent assessments

### GET api/stats.json

Hub-wide statistics:

```
{ "total_skills", "verified_skills", "failed_skills",
  "pending_review", "total_scans_run",
  "last_crawl", "last_build",
  "skill_types": { "mcp_server": N, "agent_skill": N },
  "sources": { "<hub>": <count> },
  "verification_tiers": { "full_pipeline": N, "scanner_only": N, "metadata_only": N } }
```

`verified_skills` counts only `full_pipeline` skills. Use `verification_tiers` for the full breakdown.

### GET api/search-index.json

Lightweight search index for client-side fuzzy search. Each entry:

```
{ "id", "name", "tags", "description", "stars", "overall_score",
  "verification_status", "skill_type" }
```

Use this for fast filtering by score, verification status, or skill type without fetching detail files.

### GET api/packages/{tag_path}.json

Pre-curated skill packages for a tag. Contains the top verified skills auto-curated by stars and score.

```
{ "tag_path", "label", "description",
  "skill_ids": [...], "total_skills", "avg_score", "generated_at" }
```

Use `skill_ids` to fetch detail files for each skill in the package.

### Agent-Optimized Indexes

These endpoints provide pre-computed views optimized for agent workflows. All are under `api/indexes/`.

#### GET api/indexes/manifest.json

Lightweight manifest of all skills with core fields (`id`, `name`, `verification_status`, `verification_level`, `overall_score`, `stars`, `risk_level`, `repo_url`). Faster than loading the full index when you only need basic metadata.

#### GET api/indexes/by-status.json

Skills grouped by verification status. Structure:

```
{ "generated_at": "<ISO-8601>",
  "total_skills": N,
  "counts": { "pass": N, "fail": N, "manual_review": N, "unverified": N, "updated_unverified": N },
  "pass": ["skill-id-1", "skill-id-2", ...],
  "fail": [...],
  "manual_review": [...],
  "unverified": [...],
  "updated_unverified": [...]
}
```

Status arrays are top-level keys (not nested). Use `data.pass` for the ID list and `data.counts.pass` for the count.

#### GET api/indexes/by-risk.json

Skills grouped by risk level. Same flat structure as by-status, with top-level keys for each risk level (`info`, `low`, `medium`, `high`, `critical`) and a `counts` dict.

#### GET api/indexes/verify-queue.json

Unverified skills prioritized by star tier (`tier_1_1000plus` through `tier_5_0`). Use this to find the highest-impact skills that need verification.

#### GET api/indexes/lookup.json

Bucketed skill ID lookup by 2-character prefix. Use for O(1) skill existence checks without loading the full index.

### Error handling

All endpoints return static JSON files. If a skill ID or tag does not exist, the server returns a 404 status with no body. Always check the HTTP status code before parsing the response.

---

## Example conversation flow

```
Agent: (reads /entry.md)

Agent -> User:
  "I can help you find verified skills. What are you looking for?
   1. Agent Skills -- expertise, coding patterns, workflows
   2. MCP Servers -- connect to databases, APIs, and services
   3. Browse everything"

User: "Agent Skills for React development"

Agent: (fetches api/skills/by-tag/dev-web-frontend-react.json, filters skill_type=agent_skill)
Agent -> User:
  "I found 2 verified React Agent Skills:
   1. claude-skills (Score: 82, 538 stars, verified) -- Claude Code skill packages
   2. claude-code-workflows (Score: 85, 158 stars, verified) -- Workflow patterns
   Want details or the security report for any of these?"

User: "What MCP servers work well with React?"

Agent: (fetches api/skills/by-tag/dev-web-frontend-react.json, filters skill_type=mcp_server)
Agent -> User:
  "Here are MCP servers tagged for React development:
   1. Figma-Context-MCP (Score: 82, 13248 stars, verified) -- Figma design context for AI coding
   2. mcp-adapter (566 stars, unverified) -- Spin up MCP servers on Next.js, Nuxt.js, and more
   Want the security report for any of these?"

User: "Show me database MCP servers"

Agent: (fetches api/skills/by-tag/data-db.json)
Agent -> User:
  "Top database MCP servers (405 total, 177 verified):
   1. mcp-supabase (Score: 87, 2486 stars, verified) -- Supabase integration
   2. postgres-mcp (Score: 78, 2188 stars, verified) -- PostgreSQL access
   3. dbhub (Score: 80, 2177 stars, verified) -- Universal database hub
   Want to install any of these?"
```

---

## Security information

Each verified skill goes through a 5-agent verification pipeline:

Operational run commands and batch workflow details are documented in `docs/workflows/verification.md`. Safety overrides and pipeline architecture are in `docs/design/verification-architecture.md`.

| Step | Agent | What it checks |
|------|-------|----------------|
| 1 | Doc Reader (A) | What the skill *claims* to do based on README and docs |
| 2 | Code Parser (B) | What the code *actually* does -- imports, syscalls, network, file ops |
| 3 | Scanner (C*) | Deterministic static analysis -- obfuscation, injection, env access |
| 4 | Scorer (D) | Compares A vs B vs C* -- flags mismatches, assigns score 0-100 |
| 5 | Supervisor (E) | Final review, checks for compromised agents, signs off |

### Verification levels

Not all "pass" skills are verified equally. The `verification_level` field indicates how deeply a skill was checked:

| `verification_level` | Badge | What it means | Confidence |
|---|---|---|---|
| `full_pipeline` | Verified (green) | Full 5-agent pipeline: doc reader + code parser + scanner + scorer + supervisor | Highest |
| `scanner_only` | Scanned (cyan) | Agent C* deterministic scanner only — code was cloned and scanned | Medium |
| `metadata_only` | Assessed (purple) | Metadata heuristics only — no code was cloned or scanned | Low |

When recommending skills, **prefer `full_pipeline`** skills. For `metadata_only` skills, add a disclaimer that no code scan was performed.

The `verification_level` field appears in both index.json entries and detail files.

### Verification statuses

- **`pass`** -- All checks passed, docs match code. Score >= 80 (full 5-agent pipeline) or >= 70 (scanner-only).
- **`manual_review`** -- Minor mismatches, human review pending.
- **`fail`** -- Dangerous patterns detected or major doc/code mismatch.
- **`unverified`** -- Not yet scanned.
- **`updated_unverified`** -- Repo changed since last scan; re-verification needed.

### Trust levels

- **High** -- From Anthropic official sources.
- **Medium** -- From curated directories (claudeskills.info).
- **Low** -- From unvetted sources (SkillsMP, mcp.so).
- **Dangerous** -- From unknown origins; extra scrutiny applied.

### Risk levels

`info` < `low` < `medium` < `high` < `critical`. Skills rated `high` or `critical` are flagged with a secondary badge.

**Important**: Risk level is separate from verification status. A skill can be `pass` (verified safe) AND `high` risk. This means the skill uses powerful capabilities (browser control, file I/O, network access, env variables) that are legitimate for its purpose but require user awareness. Example: Playwright MCP Server is verified safe but rated `high` because it controls browsers and accesses the filesystem. Risk level indicates **capability scope**, not **security threat**.

---

## Custom Packages

Users can create personalized skill packages tied to their GitHub account. Resolve their curated stack in one API call.

### Discovering a user's package

1. Ask the user: "Do you have a SecureSkillHub profile? What's your GitHub handle?"
2. Fetch `https://api.secureskillhub.workers.dev/v1/agent/profile/{github_handle}`
3. If the user has public packages, you'll receive:

```json
{
  "github_handle": "username",
  "packages": [
    {
      "name": "My Stack",
      "tags": ["dev-web-frontend-react", "data-db", "security"],
      "pinned_skills": ["skill-id-1", "skill-id-2"],
      "total_resolved": 23
    }
  ]
}
```

4. Each package lists `tags` and `pinned_skills` — use these to query `api/skills/by-tag/{tag}.json` for the full skill list.

### Installing a user's usual stack

If the user says "install my usual stack" or "set up my tools":
1. Look up their profile packages and resolve skills via the by-tag and detail endpoints.
2. Each skill has a `repo_url` field — for MCP servers, generate install commands based on `primary_language` (TypeScript/JavaScript → `npx`, Python → `uvx`, other → `git clone`).
3. Prefer skills with `verification_status: "pass"` and warn about unverified ones.
4. The user can also install via CLI: `npx secureskillhub install`

---

## Tips for agents

- Prefer skills with `verification_level: "full_pipeline"` and `overall_score >= 80`. These are the most thoroughly checked.
- Skills with `verification_level: "scanner_only"` are code-scanned but not LLM-reviewed. Acceptable for low-risk use cases.
- Skills with `verification_level: "metadata_only"` were not code-scanned — add a disclaimer when recommending these.
- Always show the `risk_level` and `findings_summary` when recommending a skill.
- If a skill is `updated_unverified`, warn the user that the code has changed since the last audit.
- Use `api/skills/by-tag/{tag}.json` for fast filtered results instead of loading the full index.
- Use the `skill_type` field to filter between Agent Skills and MCP Servers.
- Tag IDs follow a hierarchical pattern: `category-subcategory-specialization-stack` (e.g., `dev-web-frontend-react`).
- Star count indicates community adoption — higher stars = more widely used = higher verification priority.
- **Agent skills use installs as priority signal** — look for `installs:N` in the `tags` array (e.g., `"installs:97732"`). Higher installs = more widely used. MCP servers use `stars` instead.
- If the user has a SecureSkillHub account, check their custom packages first before browsing the full catalog.
