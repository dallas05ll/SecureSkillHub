# 10-Agent Comprehensive Review: Verification Workflow

**Date:** 2026-02-28
**Scope:** Full verification pipeline -- code, docs, schemas, CLI, security, scalability
**Agents:** 10 specialized review agents, findings synthesized by supervisor

---

## 1. Executive Summary

The SecureSkillHub verification pipeline is architecturally sound: the 5-agent design with deterministic safety overrides, Pydantic schema enforcement, and separation of LLM/deterministic paths is well-reasoned. However, this review uncovered **significant documentation drift from code reality**, **two critical security gaps** (concurrent file write races and scanner crash bypass), and **scalability bottlenecks** that will break at the 50K-skill target. The documentation layer has accumulated approximately 30 distinct inaccuracies across 6+ files, many telling agents and humans different things about the same behavior. The most urgent fixes are the security vulnerabilities (P0), followed by documentation corrections that could cause incorrect integration by downstream agents reading `entry.md` or `verification.md`.

---

## 2. Finding Deduplication

Many agents independently discovered the same issues. Below, duplicate findings are grouped under a single canonical ID.

### Group A: Agent Audit Trail -- Extra Fields Not in Schema (Agents #3, #7, #1)

`AgentAuditEntry` in `schemas.py` defines 3 fields (`signed`, `signed_at`, `comment`), but `build_agent_audit()` in `run_verify_strict_5agent.py` writes 5-6 fields per agent entry (e.g., `doc_quality_score`, `claimed_permissions` for Agent A; `files_analyzed`, `capabilities_found` for Agent B; `total_findings`, `severity_counts` for C*; `score`, `mismatches`, `safety_overrides_applied` for D; `approved`, `confidence`, `override_reason` for E). These 12 extra fields are undocumented in the schema and in `verification.md`.

**Affected files:** `src/sanitizer/schemas.py` (lines 218-224), `run_verify_strict_5agent.py` (lines 534-605), `docs/workflows/verification.md` (lines 270-308)

### Group B: Agent Comment Format Examples Wrong in Docs (Agents #1, #3, #7)

All 5 agent comment format examples in `verification.md` (lines 283-304) do not match the actual `f-string` templates in `build_agent_audit()`. For example, docs show `"Docs quality 7/10, 3 claimed features, README + SKILL.md found"` but code produces `"Docs quality 7/10. README present. 3 features, 2 permissions claimed."` with period separators and different field order.

**Affected files:** `docs/workflows/verification.md` (lines 283-304), `run_verify_strict_5agent.py` (lines 550-597)

### Group C: Pipeline Stage Count -- 9 vs 8 (Agents #1, #5)

`pipeline.py` documents 9 stages in its docstring (lines 8-21: Clone, Prepare, Scan, Task A+B, Sanitize, Task D, Task E, Write, Build) while `verification.md` documents 8 stages (lines 85-103). The discrepancy is that `pipeline.py` separates "Prepare" as its own stage and merges A+B into one Task stage, while `verification.md` merges preparation into the agent stages.

**Affected files:** `src/verification/pipeline.py` (lines 8-21), `docs/workflows/verification.md` (lines 85-103)

### Group D: D1 Risk Guard Divergence Between Paths (Agents #2, #4)

In the deterministic path (`run_verify_strict_5agent.py` line 434), the D1 critical-findings override only upgrades risk from `INFO` to `HIGH` (`if risk == ScanSeverity.INFO: risk = ScanSeverity.HIGH`). In the LLM path (`agent_d_scorer.py` line 217), it upgrades from anything non-critical (`if parsed.get("risk_level") not in ("critical",): parsed["risk_level"] = ScanSeverity.HIGH.value`). Docs claim "apply identically in both paths" which is false.

**Affected files:** `run_verify_strict_5agent.py` (lines 431-435), `src/verification/agent_d_scorer.py` (lines 214-218), `docs/workflows/verification.md` (line 206)

### Group E: E4 Confidence Boost and E6 Invariant (Agents #2)

E4 confidence boost (setting confidence to `max(confidence, 90)` on critical findings) exists only in the deterministic path (`run_verify_strict_5agent.py` line 504) but not in the LLM path (`agent_e_supervisor.py`). E6 (the `approved=True requires final_status=pass` invariant) is present in both paths but undocumented in the Safety Overrides section.

**Affected files:** `run_verify_strict_5agent.py` (lines 500-504, 513-514), `src/verification/agent_e_supervisor.py` (lines 230-244), `docs/workflows/verification.md` (lines 217-225)

### Group F: --source Double-Limit Bug (Agents #5, #6)

When `--source` is used with `--skill-ids`, the source filter still applies (`run_verify_strict_5agent.py` line 904), which contradicts the documented behavior that `--skill-ids` "bypasses all filters." Additionally, when `--source` is used without `--skill-ids`, the `[:args.limit]` slice on line 904 re-applies the limit after `load_candidates()` already applied it, potentially reducing the result set below the requested limit.

**Affected files:** `run_verify_strict_5agent.py` (lines 885-904), `docs/workflows/verification.md` (lines 452-454)

### Group G: Scoring Doc Inaccuracies (Agents #1, #4)

Docs say "-15 per finding" (line 357) but code deducts -15 per *category* of B-missed findings (line 405: `score -= 15 * len(missed)` where `missed` is a list of category-level descriptions, not individual findings). The SYSTEM_PROMPT in `agent_d_scorer.py` uses -5/-10/-20/-30 severity tiers while the deterministic path uses only -10/-20 (network/system = -20, file/env = -10).

**Affected files:** `docs/workflows/verification.md` (lines 351-357), `run_verify_strict_5agent.py` (lines 356-405), `src/verification/agent_d_scorer.py` (lines 66-75)

### Group H: entry.md Inaccuracies (Agent #8)

Multiple cross-document inconsistencies in `site/entry.md`:
- Line 195: pass threshold stated as `>= 70` but full pipeline uses `>= 80` and scanner-only uses `>= 70`
- Line 100: `findings_summary` keys listed as `has_readme, dangerous_patterns, notes` -- none of which exist in the actual dict (real keys: `scanner_findings`, `dangerous_calls`, `network_ops`, etc.)
- Line 182: "5-step verification pipeline" -- should be "5-agent" for consistency
- Lines 184-189: Describes agents as sequential "steps" 1-5, but stages 2a/2b can run in parallel

**Affected files:** `site/entry.md` (lines 100, 182-189, 195)

---

## 3. Priority Matrix

### P0 -- CRITICAL (Fix Now: Security/Correctness Risk)

| ID | Finding | Source Agents | Impact |
|----|---------|---------------|--------|
| P0-1 | **Concurrent file writes with no locking.** `worker_group()` runs via `ThreadPoolExecutor` but `update_skill_file()` does read-modify-write on skill JSON files with no file locking. Two workers processing the same skill file (unlikely but possible in edge cases) or `remaining_unverified()` reading mid-write could corrupt data. | #9 (C-1) | Data corruption under concurrency |
| P0-2 | **Scanner crash returns zeroed output (security bypass).** In `pipeline.py` lines 149-155, if `StaticScanner` raises any exception, a zeroed `ScannerOutput` is returned (0 findings, 0 counts). Downstream agents D and E see a "clean" scan, and the skill can pass verification despite the scanner never actually running. | #9 (C-2) | Malicious skill could bypass all scanner checks |
| P0-3 | **D1 risk floor under-enforcement.** In `run_verify_strict_5agent.py` line 434, the critical-findings override only upgrades risk from `INFO`, not from `LOW` or `MEDIUM`. A skill with critical scanner findings but pre-existing `MEDIUM` risk from undocumented capabilities keeps `MEDIUM` risk instead of being forced to at least `HIGH`. | #4 (D1-underenforce), #2 (D1 divergence) | Critical-risk skills could get understated risk ratings |
| P0-4 | **entry.md `findings_summary` keys are wrong.** `site/entry.md` line 100 tells agents the keys are `has_readme, dangerous_patterns, notes` but the real keys are `scanner_findings, dangerous_calls, network_ops, file_ops, env_access, obfuscation, injection_patterns, mismatches, undocumented_capabilities, supervisor_approved, supervisor_confidence`. Any downstream agent parsing `findings_summary` based on entry.md will fail. | #8 (findings_summary keys) | Agents integrating via entry.md will misparse security data |

### P1 -- HIGH (Fix Soon: Accuracy/Consistency Risk)

| ID | Finding | Source Agents | Impact |
|----|---------|---------------|--------|
| P1-1 | **AgentAuditEntry schema covers 3 of 5-6 actual fields.** Code writes `doc_quality_score`, `claimed_permissions`, `files_analyzed`, `capabilities_found`, `total_findings`, `severity_counts`, `score`, `mismatches`, `safety_overrides_applied`, `approved`, `confidence`, `override_reason` -- none defined in the Pydantic model. The `agent_audit` field on `VerifiedSkill` is typed as `Optional[dict]`, bypassing all validation. | #3, #7 | Schema is not enforcing data contracts for audit trail |
| P1-2 | **All 5 agent comment examples wrong in docs.** Every example in verification.md lines 283-304 uses a format that does not match the actual f-string templates in code. | #1, #3, #7 | Misleading for anyone building on the audit trail |
| P1-3 | **O(n) candidate loading reads all skill files.** `load_candidates()` in `run_verify_strict_5agent.py` reads every `.json` file in `data/skills/` (currently ~5K, target 50K). `remaining_unverified()` does a *second* full scan at the end. `run_verify_sample.py` does a *third* full scan for stats. At 50K files this is 150K+ file reads per run. | #10 (CRITICAL) | Pipeline becomes unusably slow at scale |
| P1-4 | **skills/index.json unbounded growth.** At 50K skills the index JSON will be ~36MB, well beyond practical for agent or browser consumption. | #10 (CRITICAL) | API endpoint becomes unusable at scale |
| P1-5 | **Safety overrides documented as "apply identically in both paths" -- false.** D1 risk guard and E4 confidence boost behave differently between deterministic and LLM paths. | #2, #4 | Developers may trust LLM path has same guarantees as deterministic |
| P1-6 | **entry.md pass threshold >= 70 vs code >= 80.** Full pipeline uses `score >= 80` for pass (line 423 of `run_verify_strict_5agent.py`), but `entry.md` line 195 says `>= 70`. Scanner-only uses `>= 70` (line 145 of `run_verify_sample.py`). The entry point gives agents wrong expectations about what "pass" means. | #8 | Agents may recommend skills that should be manual_review |
| P1-7 | **fail_skill() path traversal risk.** `fail_skill()` constructs file path from `skill["id"]` without validation. The `verify_one_skill()` function validates `skill_id` format, but if `fail_skill()` is called from a different code path or the validation is bypassed, arbitrary file writes are possible. | #9 (H-1) | Potential path traversal if called from new code paths |
| P1-8 | **repo_url prefix-only validation.** Line 712 checks `repo_url.startswith("https://github.com/")` which would accept URLs like `https://github.com.evil.com/...`. Should use URL parsing or stricter regex. | #9 (H-2) | Could clone from malicious domains |
| P1-9 | **B-missed check omits obfuscation and injection categories.** `run_verify_strict_5agent.py` lines 397-404 check if B missed dangerous_calls, network, file_ops, and env_access from scanner -- but do not check `obfuscation_count` or `injection_patterns_count`. A compromised Agent B that ignores obfuscation would not be flagged as suspicious. | #9 (H-4) | Agent compromise detection has blind spots |
| P1-10 | **--source filter applies even with --skill-ids.** Line 903-904 applies source filter after skill-id lookup, contradicting the docstring and CLI docs that say --skill-ids "bypasses all filters." | #5, #6 | Unexpected CLI behavior, skills silently dropped |

### P2 -- MEDIUM (Fix When Convenient)

| ID | Finding | Source Agents | Impact |
|----|---------|---------------|--------|
| P2-1 | **Agent A char cap: docs say 60K, deterministic path uses 12K x 30 files.** `agent_a_md_reader.py` uses `_MAX_DOC_CHARS = 60_000`, but `run_verify_strict_5agent.py` `run_agent_a()` reads `docs[:30]` files at `max_chars=12000` each (360K theoretical max but usually much less). | #1 | Documentation misleading about deterministic path limits |
| P2-2 | **Agent A skip dirs: docs list 6, code has 10-11.** Docs list `.git, node_modules, __pycache__, .venv, dist, build`. Code adds `venv, .tox, .eggs, .mypy_cache, .ruff_cache` and also skips dirs starting with `.` in the deterministic path. | #1 | Incomplete documentation |
| P2-3 | **Agent B code extensions: docs incomplete.** Docs list ~15 extensions; code includes `.mjs, .cjs, .kt, .c, .cpp, .h, .hpp, .bash, .zsh, .fish, .pm, .toml, .yaml, .yml, .json, .cfg, .ini, .env, .dockerfile`. | #1 | Developers may miss supported file types |
| P2-4 | **Pipeline stage count: 9 in pipeline.py vs 8 in verification.md.** Different granularity of stage definitions. | #1, #5 | Confusing for new contributors |
| P2-5 | **scan_summary not in VerifiedSkill schema.** `run_verify_sample.py` writes `scan_summary` to skill JSON, but `VerifiedSkill` in `schemas.py` has no `scan_summary` field. The field survives because skill JSONs are written directly, not via the Pydantic model. | #3 | Schema does not reflect actual data on disk |
| P2-6 | **fail_skill() error-path findings_summary format undocumented.** When a pipeline stage fails, `fail_skill()` writes `{"error": "...", "supervisor_approved": False, "supervisor_confidence": 0}` which differs from the normal `findings_summary` format and is not documented. | #3 | Consumers of findings_summary may not handle error format |
| P2-7 | **manager_summary format wrong in docs.** Docs show `"5/5 agents completed. Score: 85/100. Status: pass. Supervisor approved with 90% confidence."` but code produces `"5/5 agents completed. Score: 85/100, Risk: medium. 1 mismatches, 5 scanner findings. Approved at 90% confidence. No safety overrides."` | #7 | Documentation drift |
| P2-8 | **"Two" vs "Three" verification levels.** `verification-architecture.md` says "Two verification levels: full_pipeline and scanner_only" but `verification.md` and `schemas.py` define three levels (adding `metadata_only`). | #8 | Outdated architecture doc |
| P2-9 | **obfuscation_high_risk_count vs obfuscation_count confusion.** `verification-architecture.md` may reference `obfuscation_count` where safety overrides actually check `obfuscation_high_risk_count`. These are different fields -- `obfuscation_count` includes low-risk patterns, `obfuscation_high_risk_count` is the override trigger. | #8 | Could lead to incorrect override implementation |
| P2-10 | **verify-queue.json path wrong in skills-manager.md.** Referenced file path does not match actual location. | #8 | Broken cross-references |
| P2-11 | **list[str] fields have no Pydantic item-level caps.** Fields like `claimed_features`, `imports`, `system_calls` etc. accept unlimited-length strings within the list. Only the list itself is uncapped (no `max_length` on items). | #9 (H-3) | Potential for oversized individual items |
| P2-12 | **Stats redundant full scan in run_verify_sample.py.** Lines 330-361 read ALL skill files again after verification to recompute stats, even though only a small subset was modified. | #10 | Wasted I/O, especially at scale |
| P2-13 | **No clone cache between runs.** Each verification run clones repos from scratch. For re-verification of previously cloned repos, a local cache would save significant time and bandwidth. | #10 | Slow re-verification cycles |
| P2-14 | **Concurrent semgrep memory explosion.** When `--group-count` is high, multiple semgrep processes run in parallel, each consuming significant memory. No memory guard or semgrep concurrency limit exists. | #10 | OOM risk on resource-constrained systems |
| P2-15 | **D scoring doc conflates LLM guidelines with deterministic logic.** The SYSTEM_PROMPT scoring tiers (-5/-10/-20/-30) differ from the deterministic implementation (-10/-20 only). Docs present them as if they are the same. | #1, #4 | Confusing which scoring rules apply where |
| P2-16 | **Pre-flight skill_id validation not in pipeline diagram.** `verify_one_skill()` validates skill_id format at line 706, but this step is not shown in any pipeline stage diagram. | #5 | Hidden validation step not documented |
| P2-17 | **D and E outputs sanitized inline, not only at Stage 4.** In `run_verify_strict_5agent.py`, D output is sanitized at line 748 and E output at line 754, after Stage 4's sanitization of A/B/C*. The pipeline diagram implies all sanitization happens at Stage 4. | #5 | Pipeline diagram is incomplete |

### P3 -- LOW (Nice to Have)

| ID | Finding | Source Agents | Impact |
|----|---------|---------------|--------|
| P3-1 | **--only-unverified is always True (redundant in examples).** The flag defaults to `True` in `run_verify_strict_5agent.py`, making `--only-unverified` in example commands redundant. | #6 | Minor CLI documentation clarity |
| P3-2 | **No error handling around report writes (Stages 7-8).** `write_report_file()` in the deterministic runner does `mkdir + write_text` but exceptions (disk full, permissions) are not caught. In `pipeline.py`, `write_reports()` catches `OSError` per file. Inconsistent error handling. | #5 | Unhandled exceptions could crash the pipeline |
| P3-3 | **get_head_commit() is a hidden Step 1b.** After cloning, `get_head_commit()` runs as a subprocess but is not documented as a pipeline step. | #5 | Minor documentation gap |
| P3-4 | **"5-step" vs "5-agent" terminology in entry.md.** Line 182 says "5-step verification pipeline" but the correct term used elsewhere is "5-agent." | #8 | Minor terminology inconsistency |
| P3-5 | **Flat directory layout at 50K files.** All skill JSONs live in a single `data/skills/` directory. At 50K files, some filesystems will have degraded `readdir` performance. | #10 | Performance at extreme scale |
| P3-6 | **All skills held in memory during build.** `build_json.py` loads all skill records into memory. At 50K this is manageable but could be improved with streaming. | #10 | Memory usage at scale |
| P3-7 | **Scanner-only scoring and metadata-only scoring absent from verification.md scoring section.** Both scoring systems are documented separately but the scoring section primarily covers full-pipeline scoring. | #4 | Documentation completeness |

---

## 4. Cross-Agent Patterns

The 10-agent review reveals four systemic issues:

### Pattern 1: Documentation Drift

The most pervasive issue. At least 20 findings involve documentation that no longer matches code behavior. This affects `verification.md`, `entry.md`, `verification-architecture.md`, and `skills-manager.md`. Root cause: docs were written during initial design and not updated as the deterministic implementation diverged from the LLM-path reference architecture. The two paths (deterministic in `run_verify_strict_5agent.py` and LLM-ready in `src/verification/`) have subtly different behaviors that docs treat as identical.

**Recommendation:** Establish a doc-update checklist in the PR template. Any change to `run_verify_strict_5agent.py`, `agent_d_scorer.py`, or `agent_e_supervisor.py` must update `docs/workflows/verification.md` and `site/entry.md`.

### Pattern 2: Schema-Code Gap

The `AgentAuditEntry` Pydantic model is unused in practice -- actual audit entries are built as raw dicts with 12 extra fields. The `VerifiedSkill.agent_audit` field is typed as `Optional[dict]`, which means no Pydantic validation occurs. Similarly, `scan_summary` is written to skill JSONs but has no corresponding schema field. The schema is supposed to be "the single source of truth" (per `CLAUDE.md`) but it has gaps where code routes around it.

**Recommendation:** Either update `AgentAuditEntry` to include all fields that `build_agent_audit()` actually writes, or document the intentional use of `dict` and retire the unused schema class.

### Pattern 3: Two-Path Divergence

The codebase maintains two parallel implementations: the active deterministic path (`run_verify_strict_5agent.py`) and the LLM-ready path (`src/verification/agent_*.py` + `pipeline.py`). These have diverged in at least 3 safety-critical behaviors (D1 risk guard, E4 confidence boost, E6 invariant documentation). When the LLM path is activated, it will behave differently from the deterministic path that has been tested in production.

**Recommendation:** Add integration tests that verify both paths produce equivalent safety override results for the same inputs. Alternatively, have the deterministic runner call the safety override methods from the agent classes rather than re-implementing them.

### Pattern 4: Scalability Assumptions

The pipeline was designed for ~5K skills and works well at that scale. Multiple agents independently identified that the O(n) full-scan patterns (load_candidates, remaining_unverified, stats recompute) and unbounded index files will not scale to 50K. These are not urgent but should be addressed before the next order-of-magnitude growth.

**Recommendation:** Build a lightweight index/cache file (skill_id, status, stars, source_hub) that avoids full-file parsing for candidate selection. Cap index.json with pagination.

---

## 5. Recommended Fix Order

Ordered by impact, urgency, and dependency chain.

### Phase 1: Security Fixes (1-2 days)

1. **Fix P0-2: Scanner crash bypass in pipeline.py.** Change the fallback `ScannerOutput` to set `risk_level` or a flag indicating scanner failure. Downstream agents D/E should treat a scanner-error output as `manual_review` at minimum, not as a clean scan. Also update `run_verify_strict_5agent.py` -- currently it calls `fail_skill()` on scanner exception (correct), but `pipeline.py` silently returns zeroed output (incorrect).

2. **Fix P0-3: D1 risk floor under-enforcement.** In `run_verify_strict_5agent.py` line 434, change `if risk == ScanSeverity.INFO:` to `if risk not in (ScanSeverity.HIGH, ScanSeverity.CRITICAL):` to match the LLM-path behavior in `agent_d_scorer.py` line 217.

3. **Fix P0-1: Add file locking for concurrent writes.** Wrap `update_skill_file()` in a file lock (e.g., `filelock` library or `fcntl.flock`). Also protect `write_report_file()` calls.

4. **Fix P1-8: Strengthen repo_url validation.** Replace prefix check with URL parsing: `urllib.parse.urlparse(repo_url).netloc == "github.com"`.

5. **Fix P1-7: Validate skill_id in fail_skill().** Add the same `re.match(r'^[a-zA-Z0-9_-]+$', skill_id)` check that `verify_one_skill()` uses.

6. **Fix P1-9: Add obfuscation/injection to B-missed check.** After line 404, add checks for `scanner.obfuscation_count > 0` and `scanner.injection_patterns_count > 0` against Agent B findings.

### Phase 2: Critical Documentation Corrections (1 day)

7. **Fix P0-4: Correct entry.md findings_summary keys.** Replace line 100's `(has_readme, dangerous_patterns, notes, etc.)` with the actual keys from `findings_summary()` in `run_verify_strict_5agent.py`.

8. **Fix P1-6: Correct entry.md pass threshold.** Clarify that full-pipeline pass requires `>= 80` and scanner-only pass requires `>= 70`.

9. **Fix P1-2: Update all 5 agent comment examples** in `verification.md` lines 283-304 to match the actual f-string templates from `build_agent_audit()`.

10. **Fix P1-5: Remove "apply identically in both paths" claim** from verification.md line 206. Document the specific differences between deterministic and LLM safety overrides.

11. **Fix P2-7: Update manager_summary example** in verification.md to match the actual format string.

12. **Fix P2-8: Update verification-architecture.md** to include `metadata_only` as a third verification level.

### Phase 3: Schema Alignment (0.5 days)

13. **Fix P1-1: Expand AgentAuditEntry or document the dict pattern.** Either add all 12 extra fields to the Pydantic model and use it in `build_agent_audit()`, or add a docstring to `VerifiedSkill.agent_audit` explaining the intentional dict usage and listing all expected keys.

14. **Fix P2-5: Add scan_summary to VerifiedSkill** or document why it is intentionally outside the schema.

15. **Fix P2-6: Document error-path findings_summary format** in verification.md.

### Phase 4: CLI and Behavioral Fixes (0.5 days)

16. **Fix P1-10: Skip source filter when --skill-ids is provided.** Move the `if args.source:` filter inside the `else` branch of the `if args.skill_ids:` check.

17. **Fix P2-1, P2-2, P2-3: Update Agent A/B documentation tables** with accurate char caps, skip dirs, and code extensions from the actual code.

18. **Fix P2-4, P2-16, P2-17: Update pipeline stage diagram** to reflect the actual execution order including pre-flight validation, get_head_commit, and post-Stage-4 sanitization of D/E outputs.

### Phase 5: Safety Override Convergence (0.5 days)

19. **Converge D1 risk guard** between both paths (either update LLM path to match deterministic, or vice versa -- recommendation: update deterministic to match LLM path as done in step 2).

20. **Add E4 confidence boost to LLM path** in `agent_e_supervisor.py` `_apply_safety_overrides()`.

21. **Document E6 invariant** (approved=True requires final_status=pass) in the Safety Overrides table in verification.md.

### Phase 6: Scalability (2-3 days, can defer)

22. **Build a lightweight skill index** for candidate loading. A single `data/skills-index.json` with `{id, status, stars, source_hub, skill_type, repo_url}` per skill, updated atomically after each verification run. Replace `load_candidates()` and `remaining_unverified()` to read this index instead of globbing all files.

23. **Paginate skills/index.json** in the API. Add `page` and `per_page` parameters, or split into tier-based files (already partially done with by-tier).

24. **Add clone caching** with a local bare-repo cache keyed by repo_url hash.

25. **Add semgrep concurrency guard** to limit parallel semgrep processes.

---

## 6. Scope Assessment

### Files Requiring Changes

| File | Changes Needed | Estimated Effort |
|------|---------------|-----------------|
| `run_verify_strict_5agent.py` | D1 risk fix, skill_id validation in fail_skill, B-missed check expansion, --source filter fix, file locking | 2-3 hours |
| `src/verification/pipeline.py` | Scanner-crash bypass fix | 30 min |
| `src/verification/agent_e_supervisor.py` | Add E4 confidence boost | 15 min |
| `src/sanitizer/schemas.py` | Expand AgentAuditEntry, optionally add scan_summary | 30 min |
| `docs/workflows/verification.md` | ~15 corrections across safety overrides, examples, scoring, pipeline diagram | 2-3 hours |
| `site/entry.md` | findings_summary keys, pass threshold, 5-step -> 5-agent | 30 min |
| `docs/design/verification-architecture.md` | Add metadata_only level, fix obfuscation field name | 30 min |
| `docs/workflows/skills-manager.md` | Fix verify-queue.json path | 15 min |

**Total files:** 8 files for Phase 1-5 fixes, plus build/index infrastructure for Phase 6.

### Estimated Total Effort

| Phase | Effort | Priority |
|-------|--------|----------|
| Phase 1: Security fixes | 1-2 days | Immediate |
| Phase 2: Documentation corrections | 1 day | This week |
| Phase 3: Schema alignment | 0.5 days | This week |
| Phase 4: CLI/behavioral fixes | 0.5 days | This week |
| Phase 5: Safety override convergence | 0.5 days | This week |
| Phase 6: Scalability | 2-3 days | Before next 10x growth |
| **Total** | **~6-8 days** | |

### Risk if Unfixed

- **P0 items:** Active security vulnerabilities. A malicious skill could exploit the scanner-crash bypass (P0-2) or the risk under-enforcement (P0-3) to pass verification with a higher score/status than warranted. Concurrent write corruption (P0-1) could silently damage skill data during parallel runs.
- **P1 items:** Downstream agents reading entry.md will misparse findings_summary (P0-4/P1-6). The LLM path, when activated, will have weaker safety guarantees than the deterministic path (P1-5). The audit trail schema is not enforcing its contract (P1-1).
- **P2/P3 items:** Technical debt and documentation drift that increases onboarding friction and bug risk over time.
