---
name: secureskillhub-install
description: "Get install instructions for a SecureSkillHub skill with security verification details."
user-invocable: true
allowed-tools:
  - WebFetch
---

# SecureSkillHub Install

Get detailed install instructions and security information for a specific skill.

## Usage

`$ARGUMENTS` should be a skill name or skill ID.

## Steps

1. If `$ARGUMENTS` looks like a skill ID (ends with `-[0-9a-f]{8}`, e.g. `markdown-rules-34d2bf71`): fetch directly
2. Otherwise, search for the skill name in `https://dallas05ll.github.io/SecureSkillHub/api/search-index.json`
3. Once you have the skill ID, fetch: `https://dallas05ll.github.io/SecureSkillHub/api/skills/{skill-id}.json`

## Present Install Info

Show:
- **Name** and verification badge ([VERIFIED] or [UNVERIFIED])
- **Security score** (0-100) and **risk level** (info/low/medium/high/critical)
- **Repo URL**: the GitHub repository link
- **Install command**: from the skill's data, typically `npx` or `pip install` or MCP config JSON
- **Security findings**: summary of any scanner findings (if available)
- **Verified commit**: the specific commit hash that was security-reviewed (if available)

## Safety Rules

- NEVER auto-install. Always show the information and let the user decide.
- For [UNVERIFIED] skills: warn "This skill has not been security-reviewed. Review the repository before installing."
- For skills with risk_level "high" or "critical": warn prominently about the risk level.
- Always show the repo URL so the user can inspect the source code.
