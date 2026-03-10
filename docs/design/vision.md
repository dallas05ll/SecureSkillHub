# SecureSkillHub Vision

## What It Is

SecureSkillHub is the trust layer for the AI agent ecosystem. It is not another directory of MCP servers and agent skills. The verification pipeline is the product; the catalog is the surface area.

The platform adversarially verifies agent skills by comparing what documentation claims against what code actually does, anchored by a deterministic static scanner (Agent C*) that cannot be prompt-injected.

## The Problem

AI agent skills and MCP servers can claim to do anything in their README. Current trust models rely on publisher identity -- trivially gameable. A skill that says "read-only database helper" can contain `os.system()`, `eval()`, reverse shells, or data exfiltration. Nobody checks until something breaks. Snyk's ToxicSkills report (Feb 2026) found 36.82% of agent skills have security flaws. Most catalogs have no verification at all.

## The Unique Value

1. **Doc-vs-code comparison.** Agent A reads docs only. Agent B reads code only. Agent D compares them. This catches the #1 attack vector: skills that claim X but do Y.
2. **Adversarial multi-agent pipeline.** 5 agents check each other. Agent E watches for signs that other agents were compromised by malicious skill content.
3. **Deterministic anchor.** Agent C* (semgrep + regex) provides a floor of truth. It cannot be prompt-injected. Its findings trigger hard safety overrides that no LLM output can bypass.
4. **No API keys in the pipeline.** Verification runs via Claude Code Task agents. Claude Code IS the LLM. No exposed credentials, no server costs, no infrastructure.

## Architecture Philosophy

- **Static-first.** $0 hosting on GitHub Pages. All data is pre-built JSON. No server-side rendering.
- **Agent-first.** `entry.md` is for machines. `index.html` is for humans. The JSON API requires zero authentication.
- **Dual priority: `max(stars, installs)`.** High-impact skills are verified first. MCP servers use GitHub stars as primary proxy; agent skills use install counts. Unified priority score is `max(github_stars, install_count)`.
- **Claude Code is the execution environment.** The verification pipeline runs inside Claude Code sessions using Task agents. No separate infrastructure needed.
- **Commit-pinned installs.** Users install the exact version that was audited via `verified_commit`.

## Verification Levels

**Fully Verified** -- All 5 agents passed:
- Agent A extracted doc claims. Agent B extracted code behavior. Agent C* found no critical/obfuscation/injection patterns. Agent D confirmed docs match code (score >= 80). Agent E approved. All safety overrides cleared. This is the gold standard.

**C*-Scanned** -- Only the deterministic scanner ran:
- Catches known-bad patterns (dangerous calls, obfuscation, injection, suspicious URLs) but performs no doc-vs-code comparison. Fast, cheap, no LLM needed. Currently the majority of scanned skills fall here. Honest labeling: "scanned" is not "verified."

**Unverified** -- No analysis performed:
- Clearly labeled. Not hidden. Transparency over false confidence.

## North Star Metric

**Programmatic verification checks per month** -- how often agents and CI pipelines query SecureSkillHub before installing a skill. This measures whether SecureSkillHub is becoming infrastructure, not just a website.

## What Success Looks Like

Every MCP-aware agent consults SecureSkillHub before installing any skill. The `secureskillhub-mcp` server, `entry.md`, and the JSON API are embedded in developer workflows. Skill authors embed verification badges in their READMEs. The unverified gap trends toward zero.

## Canonical References

| Topic | File |
|-------|------|
| Strategy and roadmap | `STRATEGY.md` |
| Agent execution rules | `AGENTS.md` |
| Project conventions | `CLAUDE.md` |
| Data contracts | `src/sanitizer/schemas.py` |
| Verification architecture | `docs/design/verification-architecture.md` |
| Design principles | `docs/design/principles.md` |
