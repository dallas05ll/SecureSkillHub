# SecureSkillHub

A security-first, agent-first skills hub with multi-agent verification pipeline.

## What is this?

SecureSkillHub is a curated catalog of Claude Code skills and MCP servers with security verification metadata. Verified entries are reviewed through a multi-agent pipeline, and unverified entries are clearly labeled. Unlike other skill hubs, SecureSkillHub is designed for **agents to browse**, with human support as secondary.

### Key Features

- **Agent-First Design** — Agents fetch JSON endpoints. Two requests max to find what they need.
- **Multi-Agent Security Verification** — Verified skills are analyzed by 5 specialized agents (4 analysis agents + 1 deterministic scanner); unverified skills remain visible with status labels.
- **Commit-Pinned Installs** — Skills are pinned to the exact verified commit hash, not `latest`.
- **Interactive Discovery** — Agents read an entry point and guide users through a conversation to find the right skills.
- **Zero Cost** — Static site on GitHub Pages. All scanning via Claude Code Max.

## Architecture

```
LOCAL (your machine)                    WEB (GitHub Pages)
+---------------------+   git push    +----------------------+
| Crawler agents       |------------->| Static JSON files     |
| Verification agents  |              | Static HTML/CSS/JS    |
| Build scripts        |              |                       |
| All processing here  |              | Agents fetch JSON     |
+---------------------+              +----------------------+
```

## Project Structure

```
src/
  crawler/       - Hub scraping (mcp.so, glama, claudeskills.info, skills.sh, SkillsMP)
  scanner/       - Deterministic static analysis (semgrep + regex)
  sanitizer/     - Pydantic schema validation + injection stripping
  verification/  - Multi-agent security pipeline (A, B, D, E agents)
  build/         - Static site generator
data/            - JSON data store (skills, reports, tags)
site/            - Generated static site for GitHub Pages
```

## Quick Start

```bash
pip install -r requirements.txt
python3 -m src.build.build_json    # Generate API files
python3 -m src.build.build_html    # Update SEO/meta assets
python3 -m http.server 8000 --directory site  # Serve locally
```

> **Important**: Always serve from `site/`, not the repo root. Running a bare `python3 -m http.server` from the repo root exposes internal project files (`CLAUDE.md`, `PROJECT_MANAGER.md`) to visiting agents, causing them to adopt developer roles instead of the shopping/discovery flow.

## Security Pipeline

Verified skills go through a 5-agent pipeline (Doc Reader, Code Parser, Static Analyzer, Scorer, Supervisor). See `site/entry.md` for full details.

## License

MIT
