# Agent B Freeze Calibration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce an evidence-disciplined Agent B freeze candidate with fewer retries and a higher-quality human decision queue.

**Architecture:** Preserve the v1.2 runner and evidence gates. Add a small retry policy, conservative unsupported-alias handling, prompt calibration, and quality diagnostics, then benchmark configurable reviewer models on an identical fresh fixture.

**Tech Stack:** Python 3.11+, Pydantic 2, pytest, OpenAI Responses Structured Outputs.

**Spec:** `docs/superpowers/specs/2026-10-24-agent-b-freeze-calibration-design.md`

## Global Constraints

- Do not change Agent A, ingestion, retrieval, staging, or global-review architecture.
- Do not write to the real vault.
- Keep model selection provider-neutral at the Agent B abstraction boundary.
- Use TDD for every production behavior change.
- Preserve one-pass retry termination.

## Review Focus

- An unsupported low-impact failure must not consume a retry or reach human review.
- A material unsupported source or boundary failure must consume at most the configured budget.
- A new alias without evidence must be removed as `FIX`, while explicit equivalence and subtype evidence remain distinct.
- Model-response checklist omissions must remain validation failures rather than silent passes.
- Global findings and summary counts must reflect only supported final issues.

---

### Task 1: Selective configurable retry policy

**Files:**
- Modify: `src/sb_processor/review/retry.py`
- Modify: `src/sb_processor/review/runner.py`
- Test: `tests/review/test_agent_b_runner.py`

**Interfaces:**
- Produces: `RetryPolicy`, retry-category selection, terminal skipped-check reconciliation.
- Consumes: existing `unsupported_failures`, `TargetedRetryRequest`, and `ChangeReview`.

- [ ] Write failing tests for low-impact skip, material source/boundary retry, supported failure, terminal insufficiency, max retries, and max checks.
- [ ] Run focused tests and verify expected failures.
- [ ] Implement the minimum retry-policy logic and runner parameters.
- [ ] Run review tests and commit.

### Task 2: Evidence-bound alias outcomes and first-pass prompt

**Files:**
- Modify: `src/sb_processor/review/evidence.py`
- Modify: `src/sb_processor/review/runner.py`
- Modify: `src/sb_processor/prompts/agent_b_university_checklist.md`
- Test: `tests/review/test_agent_b_evidence.py`
- Test: `tests/review/test_agent_b_runner.py`

**Interfaces:**
- Produces: explicit equivalence pass, evidenced subtype fix, unsupported-new-alias fix.
- Consumes: `AgentBRequest.aliases_to_review`, source evidence, affected notes, and alias assessments.

- [ ] Write failing tests for DDD removal, Profiling equivalence, and K-Fold subtype rejection.
- [ ] Run focused tests and verify expected failures.
- [ ] Implement conservative alias resolution and concise positive-evidence prompt rules.
- [ ] Run review tests and commit.

### Task 3: Review-quality diagnostics and human summary

**Files:**
- Modify: `src/sb_processor/review/runner.py`
- Test: `tests/review/test_agent_b_runner.py`

**Interfaces:**
- Produces: unsupported-failure, retry, and unresolved-check diagnostics rendered in `SUMMARY.md`.
- Consumes: retry records and final reviewed checks.

- [ ] Write a failing summary test with literal quality counts.
- [ ] Run it and verify the missing section failure.
- [ ] Add concise diagnostics and summary rendering.
- [ ] Run review tests and commit.

### Task 4: Configurable reviewer settings and benchmark

**Files:**
- Modify: `src/sb_processor/cli.py`
- Modify: `src/sb_processor/review/runner.py`
- Test: `tests/review/test_agent_b_runner.py` or CLI tests
- Create: `docs/agent-b-v1-freeze-evaluation.md`

**Interfaces:**
- Produces: configurable semantic model/settings plus comparable diagnostics.
- Consumes: existing `OpenAIAgentBClient` and fixed v1.2 proposal/evidence fixture.

- [ ] Write a failing test proving reviewer settings reach the structured API call without provider logic in the runner.
- [ ] Implement minimal generic settings support and record model/runtime/token usage when returned.
- [ ] Run full tests and commit the code.
- [ ] Run two entirely fresh model evaluations with identical inputs and policy.
- [ ] Manually score known semantic cases, select the default, document results, and commit evaluation artifacts/documentation.

### Task 5: Final verification and branch review

**Files:**
- Verify all changed files and fresh artifacts.

- [ ] Run `.venv/bin/python -m pytest -q` and inspect output.
- [ ] Inspect `SUMMARY.md`, raw semantic responses, retries, token/cost/runtime diagnostics, and proposal hashes.
- [ ] Verify the real vault has no modified notes.
- [ ] Perform a whole-branch review against the spec and fix only blocking findings with RED→GREEN tests.
- [ ] Package the final fresh artifacts and list all commits.
