# SecureSkillHub

A security-first, agent-first directory of **11,000+ Claude Code skills and MCP servers** with multi-agent verification.

## What is this?

SecureSkillHub is a curated catalog of Claude Code skills and MCP servers with security verification metadata. Every entry is either verified through a 5-agent security pipeline or clearly labeled as unverified. Unlike other directories, SecureSkillHub is designed for **agents to browse first**, with human support as secondary.

| Metric | Count |
|--------|-------|
| Total skills | 11,098 |
| MCP servers | 6,415 |
| Agent skills | 4,683 |
| Verified (full pipeline) | 4,003 |
| Sources crawled | 6 |

### Key Features

- **Agent-First Design** — Agents fetch JSON endpoints at `site/entry.md`. Two requests max to find what they need.
- **Multi-Agent Security Verification** — 5 specialized agents (Doc Reader, Code Parser, Static Analyzer, Scorer, Supervisor) review each skill deterministically.
- **Commit-Pinned Installs** — Verified skills are pinned to the exact scanned commit hash, not `latest`.
- **Dual Catalog** — Both MCP servers (installable tools) and Claude Code agent skills (SKILL.md instruction files).
- **62 Curated Packages** — Pre-built skill bundles by domain (AI, web dev, DevOps, security, etc.).
- **Zero Cost** — Static site on GitHub Pages. All scanning runs locally via Claude Code.

## Architecture

```
LOCAL (your machine)                    WEB (GitHub Pages)
+-------------------------+  git push  +------------------------+
| 6 Crawlers              |----------->| Static JSON API        |
| 5-Agent Verification    |            | 62 Curated Packages    |
| Build Pipeline          |            | Search Index (2.3 MB)  |
| 9 Agent Roles           |            | Agent Entry Point      |
+-------------------------+            +------------------------+
```

### Data Sources

| Source | Skills | Type | Method |
|--------|--------|------|--------|
| [mcp.so](https://mcp.so) | 5,616 | MCP servers | HTML scraping |
| [SkillsMP](https://skillsmp.com) | 4,801 | Agent skills | GitHub mirror ([AmazingAng/skilldb](https://github.com/AmazingAng/skilldb)) |
| GitHub Search | 515 | Mixed | `gh` CLI topic + code search |
| [ClaudeSkills](https://claudeskills.info) | 73 | Agent skills | Static import |
| [Glama](https://glama.ai) | 50 | MCP servers | JSON-LD metadata |
| [skills.sh](https://skills.sh) | 44 | Agent skills | API + HTML |

## Project Structure

```
roles/               - 9 agent role definitions (PM, SM, VM, SecM, MemM, AXM, DeployM, DocM, FrontendM)
src/
  crawler/           - 6 hub crawlers (mcp.so, glama, claudeskills, skills.sh, skillsmp, github)
  scanner/           - Deterministic static analysis (semgrep + regex, no LLM)
  sanitizer/         - Pydantic schema validation + injection stripping
  verification/      - 5-agent security pipeline (A/B/C*/D/E)
  build/             - Static site + JSON API generator
scripts/
  crawl/             - Crawl runners, reachability checker, batch processor
  verify/            - Verification runners (full pipeline, sample, batch)
  build/             - Index builders, package builder, priority queue
  review/            - Skills manager review, health checks
  enrich/            - Star enrichment, auto-tagging
  secm/              - Security manager audit tools
data/
  skills/            - 11,099 skill JSON files (source of truth)
  packages/          - 62 curated package definitions
  tags.json          - 4-layer tag hierarchy
  stats.json         - Collection statistics
  crawl-state.json   - Per-source crawl tracking
site/                - Generated static site (GitHub Pages)
  api/               - JSON API endpoints (skills, packages, indexes, search)
  entry.md           - Agent-readable discovery entry point
cli/                 - npx secureskillhub CLI tool
api/                 - Cloudflare Worker API (accounts, custom packages)
docs/
  design/            - Vision, principles, verification architecture
  workflows/         - Crawling, verification, building, deployment, enrichment, SM ops
```

## Quick Start

```bash
# Setup
pip install -r requirements.txt

# Build
python3 -m src.build.build_json              # Generate JSON API
python3 -m src.build.build_html              # Update HTML + sitemap
python3 scripts/build/build_indexes.py       # Build agent-access indexes

# Serve locally
python3 -m http.server 8000 --directory site
```

> **Important**: Always serve from `site/`, not the repo root. Serving from root exposes internal project files to visiting agents.

## Security Pipeline

Every verified skill passes through a **5-agent deterministic pipeline**:

| Agent | Role | Method |
|-------|------|--------|
| **A** (Doc Reader) | Extracts what the skill claims to do | README/docs analysis |
| **B** (Code Parser) | Maps what the code actually does | AST + pattern matching |
| **C*** (Scanner) | Finds security issues | Semgrep + regex (no LLM) |
| **D** (Scorer) | Risk assessment + score | Weighted formula |
| **E** (Supervisor) | Final pass/fail decision | Safety override rules |

Agent C* is fully deterministic — semgrep + regex patterns only, no LLM involvement. This makes it immune to prompt injection.

### Verification Levels

| Level | Badge | What it means |
|-------|-------|---------------|
| `full_pipeline` | Verified (green) | All 5 agents reviewed, commit-pinned |
| `scanner_only` | Scanned (cyan) | Agent C* only, no full review |
| `metadata_only` | Assessed (purple) | Heuristic-based, no code clone |
| `unverified` | — | Not yet scanned |

## 9-Agent Role System

The project is operated by 9 specialized agent roles:

| Role | Scope |
|------|-------|
| **PM** (Project Manager) | Triggers verification, manual review, delegates to roles |
| **SM** (Skills Manager) | Catalog health, selects verification targets, quality review |
| **VM** (Verification Manager) | Executes 5-agent pipeline, safety override guardian |
| **SecM** (Security Manager) | False positive audit, pattern accuracy, threat intel |
| **MemM** (Memory Manager) | Cross-role memory auditor, 4 protocols (LOAD/WRITE/EVOLVE/HEALTH) |
| **AXM** (Agent Experience) | CLI, packages, entry.md, agent UX |
| **DeployM** (Deploy Manager) | Git ops, CI/CD, rollback |
| **DocM** (Documentation Manager) | Doc-code alignment, file registry |
| **FrontendM** (Frontend Manager) | Visual QA, CSS, rendering |

Three-party verification: **VM runs, SM reviews, PM approves**. No single role can both execute and approve.

## For Agents

Point your agent at `site/entry.md` — it contains the full discovery flow, API endpoints, and package catalog. Agents can find and install verified skills in two API calls.

## License

MIT
