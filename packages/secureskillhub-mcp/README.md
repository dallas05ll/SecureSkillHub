# @secureskillhub/mcp-server

MCP server for [SecureSkillHub](https://dallas05ll.github.io/SecureSkillHub) — search, browse, and install from a catalog of 11,000+ security-verified AI agent skills.

## Quick Start

```bash
npx @secureskillhub/mcp-server
```

Or add to your MCP client config:

```json
{
  "mcpServers": {
    "secureskillhub": {
      "command": "npx",
      "args": ["@secureskillhub/mcp-server"]
    }
  }
}
```

## Tools

| Tool | Description |
|------|-------------|
| `search_skills` | Search skills by keyword, type (MCP/agent), tags, tier, and verification status |
| `get_report` | Get full security report for a specific skill (score, risk level, findings) |
| `get_bundle` | Get a themed package of skills by tag (e.g., `data-db`, `dev-web`) |
| `install` | Get install instructions with security verification details |
| `browse_categories` | Browse the tag hierarchy to discover skill categories |

## Search Examples

```
search_skills({ query: "postgres", type: "mcp", limit: 5 })
search_skills({ tags: "data-db", tier: "S,A", verified_only: true })
get_report({ skill_id: "mcp-supabase-95603cab" })
install({ skill_id: "mcp-supabase-95603cab" })
```

## Security

- All skills are verified through a 5-agent adversarial security pipeline
- Install commands point to specific verified commit hashes, not latest
- Three verification tiers: full_pipeline (5 agents), scanner_only, metadata_only
- Risk levels: info, low, medium, high, critical

## Configuration

| Environment Variable | Default | Description |
|---------------------|---------|-------------|
| `SECURESKILLHUB_API_BASE` | `https://api.secureskillhub.workers.dev` | API base URL (must be https) |

## License

MIT
