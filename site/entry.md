# SecureSkillHub — Agent Entry Point

SecureSkillHub is a security-first directory of AI-agent skills and MCP servers with multi-agent verification. It covers **two catalogs**:

1. **MCP Servers** — Model Context Protocol servers that connect agents to external tools and services (databases, APIs, search). Priority signal: **GitHub stars**.
2. **Agent Skills** — SKILL.md instruction packages that teach agents how to perform tasks (coding patterns, workflows, best practices). Priority signal: **installs**.

This file is the machine-readable entry point. A machine-readable config is also at `.well-known/agent.json`. Do NOT parse `index.html` — it is a human-facing frontend.

---

## Quick Start (Progressive Disclosure)

Start with the smallest, cheapest endpoint. Only go deeper if needed.

### Step 1: Pre-Built Packages (~5KB each) — TRY THIS FIRST

For common project types, grab a ready-made verified bundle:

```
GET api/packages/index.json          → List all available packages
GET api/packages/{tag-path}.json     → Get a specific package (e.g. data-db, dev-web, security)
```

Each package contains top verified skills auto-curated by priority and security score. This is the fastest path — one fetch, done.

### Step 2: Browse by Catalog (~70KB each) — Lightweight Meta Files

If packages don't cover what you need, browse the full catalog efficiently:

```
GET api/v2/meta/mcp_servers_top.json   → Top 200 MCP servers by stars (~68KB)
GET api/v2/meta/agent_skills_top.json  → Top 200 agent skills by installs (~72KB)
GET api/v2/meta/categories.json        → Tag tree summary with counts (~9KB)
GET api/v2/meta/stats.json             → Quick catalog stats (~200B)
```

Each item in the meta files has: `id`, `name`, `score`, `score_type` (stars or installs), `tier` (S/A/B/C/D/E), `verified`, `tags`, `one_liner`.

**To switch catalogs** (MCP ↔ Agent Skills): just fetch the other meta file. No need to reload anything.

### Step 3: Get Skill Details (~2KB each)

Once you've picked a skill from Step 1 or 2:

```
GET api/skills/{id}.json              → Full detail with security report
```

### Step 4: Filter by Tag or Tier (larger files — use only if needed)

For precise tag-based browsing:

```
GET api/tags.json                      → Full tag navigation tree (~18KB)
GET api/skills/by-tag/{tag_id}.json    → All skills for a tag (size varies)
GET api/skills/by-tier/{tier}.json     → Skills by priority tier
```

Note: by-tag and by-tier files can be large (100KB-4MB). Prefer Step 1-3 for most queries.

### Step 5: Full Catalogs (large files — last resort)

```
GET api/skills/index.json              → Complete catalog (~9MB)
GET api/search-index.json              → Search index (~4.5MB)
```

Only use these for exhaustive search. Most agents should never need to load these files.

---

## Conversation Flow

```
Agent: (reads entry.md — ~800 tokens)

Agent → User:
  "I can help you find verified skills. What are you looking for?
   1. MCP Servers — connect to databases, APIs, and services
   2. Agent Skills — coding expertise, workflows, best practices
   3. Browse everything"

User: "MCP Servers for databases"

Agent: (fetches api/packages/data-db.json — ~5KB)
Agent → User:
  "Here's the Database package — 10 verified MCP servers:
   1. mcp-supabase (Score: 87, ★2,486, verified)
   2. postgres-mcp (Score: 78, ★2,188, verified)
   3. dbhub (Score: 80, ★2,177, verified)
   Want details or the security report for any of these?"

User: "Show me agent skills for coding"

Agent: (fetches api/v2/meta/agent_skills_top.json — ~15KB, filters by tags)
Agent → User:
  "Top coding agent skills by installs:
   1. Code Review (97,732 installs, tier S)
   2. TypeScript Patterns (45,210 installs, tier S)
   Want details on any of these?"

User: "Tell me more about skill X"

Agent: (fetches api/skills/X.json — ~2KB)
Agent → User: (shows security report, findings, install command)
```

**Token budget**: Package-only flow costs ~4,000 tokens. Meta-file browsing flow costs ~22,000 tokens. Compare to the old flow which cost 1,100,000+ tokens.

---

## Unified Priority System

MCP servers and agent skills use different popularity signals but the same tier thresholds:

| Tier | Threshold | MCP Signal | Agent Signal |
|------|-----------|------------|-------------|
| S | 10,000+ | GitHub stars | Installs |
| A | 1,000-9,999 | GitHub stars | Installs |
| B | 100-999 | GitHub stars | Installs |
| C | 10-99 | GitHub stars | Installs |
| D | 1-9 | GitHub stars | Installs |
| E | 0 | GitHub stars | Installs |

The `score` field in meta files always contains the relevant signal. The `score_type` field tells you whether it's `"stars"` or `"installs"`.

---

## API Endpoints Reference

All endpoints return JSON and are relative to the site root.

### Lightweight (recommended for agents)

| Endpoint | Size | Description |
|----------|------|-------------|
| `api/v2/meta/stats.json` | ~200B | Catalog counts |
| `api/v2/meta/categories.json` | ~9KB | Tag tree summary |
| `api/v2/meta/mcp_servers_top.json` | ~68KB | Top 200 MCP servers |
| `api/v2/meta/agent_skills_top.json` | ~72KB | Top 200 agent skills |
| `api/packages/{tag}.json` | ~5KB | Pre-curated verified bundles |
| `api/skills/{id}.json` | ~2KB | Full skill detail + security report |

### Medium (use when lightweight isn't enough)

| Endpoint | Size | Description |
|----------|------|-------------|
| `api/tags.json` | ~18KB | Full 4-layer tag hierarchy |
| `api/v2/meta/mcp_servers.json` | ~500KB | All MCP servers (compact) |
| `api/v2/meta/agent_skills.json` | ~400KB | All agent skills (compact) |
| `api/skills/by-tag/{tag}.json` | varies | Skills for a specific tag |
| `api/skills/by-tier/{tier}.json` | varies | Skills by priority tier |

### Heavy (avoid unless necessary)

| Endpoint | Size | Description |
|----------|------|-------------|
| `api/skills/index.json` | ~9MB | Complete catalog with all fields |
| `api/search-index.json` | ~4.5MB | Full search index |
| `api/indexes/manifest.json` | ~3.4MB | Agent-optimized manifest |

### Agent-Optimized Indexes

| Endpoint | Description |
|----------|-------------|
| `api/indexes/by-status.json` | Skills grouped by verification status |
| `api/indexes/by-risk.json` | Skills grouped by risk level |
| `api/indexes/verify-queue.json` | Unverified skills by priority tier |
| `api/indexes/lookup.json` | Bucketed ID lookup by 2-char prefix |

---

## Skill Detail Fields

Each skill detail file (`api/skills/{id}.json`) contains:

- `id`, `name`, `description`, `repo_url`, `verified_commit`
- `install_url` — specific install command URL (use `repo_url` as fallback)
- `source_hub`, `trust_level`, `skill_type` (`mcp_server` or `agent_skill`)
- `stars`, `installs` — popularity signals
- `verification_status` (`pass`, `fail`, `manual_review`, `unverified`, `updated_unverified`)
- `verification_level` (`full_pipeline`, `scanner_only`, `metadata_only`, or empty)
- `overall_score` (0-100), `risk_level` (`info`, `low`, `medium`, `high`, `critical`)
- `tags`, `owner`, `primary_language`
- `findings_summary` — verification metadata
- `agent_audit` — per-agent verification trail with `signed`, `signed_at`, `comment` for agents A-E

---

## Security Information

Each verified skill goes through a 5-agent verification pipeline:

| Step | Agent | What it checks |
|------|-------|----------------|
| 1 | Doc Reader (A) | What the skill *claims* to do |
| 2 | Code Parser (B) | What the code *actually* does |
| 3 | Scanner (C*) | Deterministic static analysis (semgrep + regex) |
| 4 | Scorer (D) | Compares A vs B vs C* — flags mismatches, scores 0-100 |
| 5 | Supervisor (E) | Final review, checks for compromised agents |

### Verification Levels

| Level | Badge | Confidence |
|-------|-------|------------|
| `full_pipeline` | Verified (green) | Highest — full 5-agent pipeline |
| `scanner_only` | Scanned (cyan) | Medium — deterministic scanner only |
| `metadata_only` | Assessed (purple) | Low — no code scanned |

When recommending skills, **prefer `full_pipeline`** skills. For `metadata_only`, add a disclaimer.

### Risk Levels

`info` < `low` < `medium` < `high` < `critical`

**Important**: Risk level indicates **capability scope**, not **security threat**. A `pass` + `high` risk skill uses powerful capabilities (browser control, file I/O) that are legitimate for its purpose but require user awareness.

---

## Custom Packages

Users can create personalized skill packages tied to their GitHub account.

1. Ask: "Do you have a SecureSkillHub profile? What's your GitHub handle?"
2. Fetch `https://api.secureskillhub.workers.dev/v1/agent/profile/{github_handle}`
3. Use returned `tags` and `pinned_skills` to query the API.
4. CLI alternative: `npx secureskillhub install`

---

## Tips for Agents

- **Start cheap**: packages (~5KB) → meta files (~15KB) → by-tag → full catalog. Never start with the full catalog.
- Prefer `full_pipeline` skills with `overall_score >= 80`.
- Always show `risk_level` and `findings_summary` when recommending.
- Use `score_type` to understand what `score` means: `"stars"` for MCP, `"installs"` for agent skills.
- Tag IDs follow a hierarchical pattern: `category-subcategory-specialization-stack` (e.g., `dev-web-frontend-react`).
- If the user has a SecureSkillHub account, check their custom packages first.
