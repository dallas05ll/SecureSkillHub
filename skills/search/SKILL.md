---
name: secureskillhub-search
description: "Search SecureSkillHub's catalog of 11,000+ security-verified AI agent skills by keyword."
user-invocable: true
allowed-tools:
  - WebFetch
---

# SecureSkillHub Search

Search the SecureSkillHub catalog for AI agent skills matching a keyword or description.

## How to Search

Fetch: `https://dallas05ll.github.io/SecureSkillHub/api/search-index.json`

This returns an array of all skills with their names, IDs, tags, stars, and verification status.

Filter the results by matching `$ARGUMENTS` against skill names and tags. Sort by stars descending.

## Present Results

For each matching skill (show top 10):

```
1. [VERIFIED] Skill Name (12,345 stars)
   Tags: dev-web-backend-python, data-ai
   https://github.com/owner/repo
```

Badges:
- [VERIFIED] = `verification_status: "pass"` — passed full 5-agent security pipeline
- [UNVERIFIED] = `verification_status: "unverified"` — not yet reviewed

## If User Wants Details

Fetch: `https://dallas05ll.github.io/SecureSkillHub/api/skills/{skill-id}.json`

Show full details: description, score, risk level, install commands, security findings.
