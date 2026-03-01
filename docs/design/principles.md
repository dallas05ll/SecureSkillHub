# SecureSkillHub Design Principles

Numbered constraints and design decisions. Each has a one-sentence rationale. Violating any of these requires explicit justification and approval.

---

1. **No API keys in the pipeline.** Verification runs via Claude Code Task agents -- Claude Code itself is the LLM, so there are no exposed credentials, no server costs, and no key rotation to manage.

2. **Deterministic core (Agent C*) is the anchor.** The static scanner (semgrep + regex) provides the floor of truth that LLM agents build upon; it cannot be prompt-injected, hallucinated past, or socially engineered.

3. **Safety overrides are post-LLM Python code.** `_apply_safety_overrides()` in agents D and E executes after the LLM returns and before output is accepted -- no prompt can bypass deterministic Python conditionals.

4. **Agent A never sees code; Agent B never sees docs.** This information barrier prevents rationalization of mismatches -- an agent that sees both can explain away discrepancies instead of flagging them.

5. **Agent C* findings override LLM judgement.** If C* detects obfuscation, the score is capped at 15 and status is forced to `fail` regardless of what agents D or E conclude.

6. **schemas.py is the single source of truth.** All data contracts (AgentAOutput, AgentBOutput, ScannerOutput, ScorerOutput, SupervisorOutput, VerifiedSkill, etc.) live in one file -- `src/sanitizer/schemas.py`.

7. **All string fields have max_length caps.** Pydantic enforces character limits on every string field to prevent injection propagation through the pipeline.

8. **Static-first architecture.** Everything is pre-built JSON served from GitHub Pages at $0/month -- no servers, no databases, no runtime dependencies.

9. **Agent-first design.** `entry.md` is for machines; `index.html` is for humans; the JSON API requires zero authentication. Agents are the primary consumers.

10. **Stars = priority.** High-star skills get verified first because GitHub stars are the best available proxy for real-world impact and attack surface.

11. **Commit-pinned installs.** Users install the exact `verified_commit` hash that was audited -- not latest, not a branch, not a tag that can be force-pushed.

12. **Transparent status.** Unverified skills are clearly labeled, not hidden. Three distinct tiers (unverified, C*-scanned, fully verified) are displayed honestly.

13. **Model routing is mandatory.** Use sonnet for bulk data work (crawling, scanning, verification agents A/B), opus for architecture and complex reasoning, haiku for simple lookups. Never use opus for bulk processing; never use haiku for building features.

14. **Claude Code IS the orchestration layer.** The verification pipeline runs inside Claude Code sessions using Task agents. No separate infrastructure, no job queues, no container orchestration.

15. **Verification levels are honest.** "C*-scanned" means only the deterministic scanner ran -- no doc-vs-code comparison. "Fully verified" means all 5 agents passed. Never conflate them.

16. **Sanitization is mandatory between agents.** All agent outputs pass through Pydantic re-validation (and the Sanitizer when available) before being forwarded to downstream agents. Raw LLM output never flows directly.

17. **Agent E checks for agent compromise.** The supervisor specifically looks for signs that Agent B was manipulated by adversarial skill content (e.g., B reports "no issues" while C* found critical patterns).

18. **Fail → pass is forbidden.** If Agent D sets status to `fail`, Agent E cannot override to `pass` -- it can only upgrade to `manual_review` at best. This prevents a compromised supervisor from whitewashing failures.

19. **No hand-editing generated files.** `site/api/**` is generated output from the build step. Hand-editing it causes drift and will be overwritten.

20. **Canonical status values are fixed.** The five verification statuses are `pass`, `fail`, `manual_review`, `unverified`, `updated_unverified`. Adding or renaming statuses requires updating schema, build, and UI simultaneously.

21. **If docs conflict with code, code wins.** Then update the stale docs. This applies to all project documentation, not just skill verification.

22. **Each topic has one canonical home.** Never duplicate content across files. Link to the canonical source instead. See the canonical file table in `CLAUDE.md`.
