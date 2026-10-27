# Reconciliation v1.1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the existing reconciliation pipeline dependency-aware, vault-identity-safe, explicit about material content-loss acceptance, and deterministically revalidated after human decisions without implementing vault writes.

**Architecture:** Extend reconciliation-owned models, add pure `identities.py` and `dependencies.py` evaluators, and refactor the existing engine into base reconciliation → root decision derivation → exact consequence application → effective-state recomputation → mandatory validation. Keep the public CLI, immutable Agent A/B inputs, deterministic fix handlers, artifact directory, and dry-run contract unchanged.

**Tech Stack:** Python 3.11+, Pydantic 2, PyYAML, standard-library `re`, `hashlib`, `difflib`, pytest

**Spec:** `docs/superpowers/specs/2026-10-27-reconciliation-v1.1-design.md`

## Global Constraints

- Do not redesign or modify Agent A/Agent B models, prompts, runners, or source artifacts.
- Do not implement the Safe Vault Writer or mutate any supplied vault.
- Do not call cloud models or add dependencies.
- Continue on `feat/reconciliation`; never work on `main`/`master`.
- Rebuild every result from immutable Agent A/B inputs; never consume prior reconciliation output.
- Emit only decision options whose exact consequence is implemented and revalidated.
- Do not offer `MERGE` without a safe content-preserving merge implementation; v1.1 has none.
- Preserve the untracked `reconciliation-v1-run-outputs.zip` and exclude it from commits.
- Use TDD for every production change and commit each completed task without squashing.

## Review Focus

- An explicit full-path wikilink must resolve to that path even when another note shares its basename; cover in Task 3 dependency tests.
- Duplicate title/alias claims from the same canonical note must not create a collision; cover in Task 2 identity tests.
- A collision between only unchanged, unrelated existing notes must be audited but non-blocking; cover in Task 2 identity tests.
- Incompatible selections affecting one change must be rejected independent of JSON ordering; cover in Task 4 engine tests.
- KEEP_SEPARATE must refuse a stale source hash or an alias representation it cannot patch minimally; cover in Task 4 engine tests.

---

### Task 1: Extend reconciliation safety and audit models

**Files:**
- Modify: `src/sb_processor/reconciliation/models.py`
- Modify: `tests/reconciliation/test_models_and_inputs.py`

**Interfaces:**
- Consumes: existing v1 reconciliation models and strict Pydantic serialization conventions.
- Produces: `DependencyTargetState`, `DependencyRecord`, `IdentityClaimKind`, `IdentityClaim`, `IdentityCollision`, `IssueResolutionDisposition`, `DecisionCategory`, new `DecisionEffect` values, `MaterialLossKind`, `MaterialLossRecord`, and `AcceptedRisk`; adds consequence/blocking metadata to `DecisionOption`/`HumanDecision`; adds dependency/material-loss records to `ReconciledChange`; adds identity/dependency/accepted-risk/applicable-subset fields to `FinalChangeSet`.

- [ ] **Step 1: Write failing strict-model and round-trip tests**

Add tests proving literal enum values, required decision consequences, per-occurrence dependency audit, collision claim provenance, material-loss dispositions, accepted-risk authorization, and backwards construction defaults for existing v1 fixtures.

- [ ] **Step 2: Run model tests and verify RED**

Run: `.venv/bin/python -m pytest -q tests/reconciliation/test_models_and_inputs.py`

Expected: FAIL because the v1.1 model names/fields do not exist.

- [ ] **Step 3: Implement the minimal model extensions**

Use reconciliation-owned Pydantic models only. Keep defaults for additive list fields so existing v1 tests remain valid. Set `RECONCILIATION_VERSION` later in the engine task.

- [ ] **Step 4: Run model and reconciliation tests and verify GREEN**

Run: `.venv/bin/python -m pytest -q tests/reconciliation/test_models_and_inputs.py tests/reconciliation/test_engine.py tests/reconciliation/test_artifacts.py`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/sb_processor/reconciliation/models.py tests/reconciliation/test_models_and_inputs.py
git commit -m "feat: add reconciliation v1.1 safety models"
```

### Task 2: Build the effective vault-wide identity registry

**Files:**
- Create: `src/sb_processor/reconciliation/identities.py`
- Create: `tests/reconciliation/test_identities.py`
- Modify: `tests/reconciliation/helpers.py`

**Interfaces:**
- Consumes: `ReconciliationInputs`, `list[ReconciledChange]`, parsed final Markdown frontmatter/title, and `normalize` from the existing registry.
- Produces: `build_effective_identity_registry(inputs: ReconciliationInputs, changes: list[ReconciledChange]) -> IdentityAnalysis`; `IdentityAnalysis` contains effective note snapshots, claims, collisions, and lookup candidates. `find_identity_collisions(...)` distinguishes blocking collisions from audited pre-existing-only collisions.

- [ ] **Step 1: Write failing complete-registry tests**

Cover canonical path, basename, title, alias, normalized identity, proposed CREATE, applicable UPDATE replacement, unrelated existing note inclusion, and deferred/skipped UPDATE retaining its original identities.

- [ ] **Step 2: Write failing collision-scope tests**

Cover proposed CREATE versus alias on an unmodified note, Classification versus Predictive Classification, two claims from the same note not colliding, and an unrelated pre-existing-only collision being audited but non-blocking.

- [ ] **Step 3: Run identity tests and verify RED**

Run: `.venv/bin/python -m pytest -q tests/reconciliation/test_identities.py`

Expected: collection/import failure for the missing identity evaluator.

- [ ] **Step 4: Implement the effective identity evaluator**

Parse effective title/aliases from final content, retain vault snapshots for excluded UPDATEs, omit excluded CREATEs, deduplicate claims per canonical note, group cross-note normalized claims, and mark a collision blocking only when a proposed applicable claim or applicable dependency target participates.

- [ ] **Step 5: Run identity and validator tests and verify GREEN**

Run: `.venv/bin/python -m pytest -q tests/reconciliation/test_identities.py tests/reconciliation/test_validators.py`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/sb_processor/reconciliation/identities.py tests/reconciliation/test_identities.py tests/reconciliation/helpers.py
git commit -m "fix: validate identities against the complete vault"
```

### Task 3: Resolve and audit batch-level wikilink dependencies

**Files:**
- Create: `src/sb_processor/reconciliation/dependencies.py`
- Create: `tests/reconciliation/test_dependencies.py`
- Modify: `src/sb_processor/reconciliation/validators.py`
- Modify: `tests/reconciliation/test_validators.py`

**Interfaces:**
- Consumes: `IdentityAnalysis` from Task 2 plus reconciled changes and their final/excluded state.
- Produces: `analyze_dependencies(inputs: ReconciliationInputs, changes: list[ReconciledChange], identities: IdentityAnalysis) -> list[DependencyRecord]`; `dependency_findings(records: list[DependencyRecord]) -> list[ValidationFinding]`; replaces the v1 blocked-link occurrence loop with target-state evaluation.

- [ ] **Step 1: Write failing same-batch resolution tests**

Cover a link to an applicable CREATE (`TARGET_CREATED_IN_BATCH`), applicable UPDATE, existing vault note, full explicit path amid basename duplication, and all Data Mining Map occurrences resolving without human decisions.

- [ ] **Step 2: Write failing excluded/ambiguous target tests**

Cover target CREATE pending, deferred, skipped, missing, and ambiguous; dependent changes become blocked/excluded without removing or rewriting their links. Several occurrences retain several audit records but share one normalized target/root decision.

- [ ] **Step 3: Run dependency tests and verify RED**

Run: `.venv/bin/python -m pytest -q tests/reconciliation/test_dependencies.py`

Expected: collection/import failure for the missing dependency resolver.

- [ ] **Step 4: Implement wikilink extraction and target-state resolution**

Parse token, display alias, and heading fragments without changing Markdown. Prefer an exact full-path claim, otherwise require one canonical candidate across path/basename/title/alias claims. Associate proposed targets and their decision/exclusion state; never treat a non-applicable CREATE as existing.

- [ ] **Step 5: Integrate dependency findings into deterministic validation**

Remove the v1 per-occurrence `LINK_TO_BLOCKED_CHANGE` generation path. Produce blocking findings for applicable changes only; dependent changes excluded due a root decision keep dependency records but do not create redundant decisions.

- [ ] **Step 6: Run dependency and validator tests and verify GREEN**

Run: `.venv/bin/python -m pytest -q tests/reconciliation/test_dependencies.py tests/reconciliation/test_validators.py`

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/sb_processor/reconciliation/dependencies.py src/sb_processor/reconciliation/validators.py tests/reconciliation/test_dependencies.py tests/reconciliation/test_validators.py
git commit -m "feat: resolve batch-level note dependencies"
```

### Task 4: Implement typed shared decisions and exact consequences

**Files:**
- Modify: `src/sb_processor/reconciliation/engine.py`
- Modify: `src/sb_processor/reconciliation/identities.py`
- Modify: `src/sb_processor/reconciliation/validators.py`
- Modify: `tests/reconciliation/test_engine.py`
- Modify: `tests/reconciliation/test_identities.py`
- Modify: `tests/reconciliation/test_validators.py`

**Interfaces:**
- Consumes: base reconciled changes, identity collision groups, dependency records, preservation findings, and optional selection map.
- Produces: stable grouped `HumanDecision` objects; `plan_keep_separate(...) -> IdentityResolutionPlan | None`; exact `KEEP_SEPARATE`, `ACKNOWLEDGE_CONTENT_LOSS`, `ACCEPT_STAGED_RISK`, `SKIP_CHANGE`, and `DEFER` effects; `reconcile(...)` rebuilds and re-evaluates state after consequences.

- [ ] **Step 1: Write failing shared identity-decision tests**

Assert the Classification/Predictive Classification issues and collision produce one decision affecting both changes and relevant dependents. Assert the options are `KEEP_SEPARATE` and `DEFER`, with no `MERGE` or generic APPLY.

- [ ] **Step 2: Write failing KEEP_SEPARATE consequence tests**

Assert selection creates Classification, minimally updates Predictive Classification by removing only the exact colliding alias, preserves its body/other metadata byte-for-byte, records an audited patch, and eliminates the collision. Assert no KEEP_SEPARATE option for stale source hash, multiple ambiguous alias occurrences, or an unsupported YAML representation.

- [ ] **Step 3: Write failing conflict-selection tests**

Assert incompatible effects on one change are rejected regardless of selection-map order. Assert one shared decision updates every affected per-note audit record.

- [ ] **Step 4: Run focused decision tests and verify RED**

Run: `.venv/bin/python -m pytest -q tests/reconciliation/test_engine.py tests/reconciliation/test_identities.py -k 'shared or classification or keep_separate or conflicting'`

Expected: FAIL because v1 emits per-note generic decisions and cannot apply KEEP_SEPARATE.

- [ ] **Step 5: Refactor decision derivation into stable root groups**

Build base changes/fixes first, derive collision/preservation/other issue groups with deterministic keys, assign stable HR IDs, and attach all affected change/issue IDs. Keep exact non-destructive v1 fix handlers unchanged.

- [ ] **Step 6: Implement exact KEEP_SEPARATE and selection compatibility**

Create a minimal patch plan from the scanned existing note and expected hash. Apply only that plan plus the proposed CREATE, then rebuild identities. Reject incompatible effects before mutating any in-memory change.

- [ ] **Step 7: Run all engine/identity tests and verify GREEN**

Run: `.venv/bin/python -m pytest -q tests/reconciliation/test_engine.py tests/reconciliation/test_identities.py`

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add src/sb_processor/reconciliation/engine.py src/sb_processor/reconciliation/identities.py src/sb_processor/reconciliation/validators.py tests/reconciliation/test_engine.py tests/reconciliation/test_identities.py tests/reconciliation/test_validators.py
git commit -m "feat: implement semantic human decision outcomes"
```

### Task 5: Require explicit material-loss acknowledgement and strengthen readiness

**Files:**
- Modify: `src/sb_processor/reconciliation/validators.py`
- Modify: `src/sb_processor/reconciliation/engine.py`
- Modify: `tests/reconciliation/test_validators.py`
- Modify: `tests/reconciliation/test_engine.py`

**Interfaces:**
- Consumes: existing-note content, proposed UPDATE, audited patches, `MaterialLossRecord`, selections, recomputed identity/dependency state.
- Produces: stable material-loss IDs, one `CONTENT_PRESERVATION` decision per affected UPDATE, accepted-risk records, applicable change IDs, and strict `FinalChangeSetState` derivation.

- [ ] **Step 1: Write failing Dataset preservation tests**

Assert Dataset's cumulative-integrity/existing-note issues plus independent paragraph loss produce one itemized decision; generic `APPLY_RECONCILED_CHANGE` is rejected; unresolved loss blocks/excludes the UPDATE.

- [ ] **Step 2: Write failing explicit-acceptance tests**

Assert `ACKNOWLEDGE_CONTENT_LOSS` marks only the listed loss IDs explicitly accepted, preserves the exact excerpts and authorization in `accepted_risks`, and allows the UPDATE only if every other mandatory validator passes. Partial/mismatched acceptance stays blocked.

- [ ] **Step 3: Write failing final-state tests**

Cover no pending blocking decisions, no applicable identity collision, no conflicting action/path, no unresolved dependency, no unacknowledged loss, valid frontmatter/path, and validated corrections. Confirm skipped/deferred/blocked changes are excluded from `applicable_change_ids`; a safe subset may be ready.

- [ ] **Step 4: Run preservation/readiness tests and verify RED**

Run: `.venv/bin/python -m pytest -q tests/reconciliation/test_validators.py tests/reconciliation/test_engine.py -k 'dataset or loss or accepted or ready or applicable'`

Expected: FAIL because v1 warnings and generic APPLY can reach `READY_FOR_WRITE`.

- [ ] **Step 5: Implement material-loss records and accepted-risk coverage**

Replace free preservation warnings with stable records derived from existing content hash/kind/excerpt. Keep harmless similarity/audited-patch exemptions. Convert unresolved material loss to a blocking gate; explicit acknowledgement creates typed accepted risks without claiming a fix.

- [ ] **Step 6: Implement full post-decision recomputation and readiness derivation**

After exact effects, rebuild effective snapshots, dependencies, identity collisions, preservation, and final validators. Propagate deferred/skipped targets to dependents, then derive applicable IDs and overall state from the recomputed result.

- [ ] **Step 7: Run engine and validator suites and verify GREEN**

Run: `.venv/bin/python -m pytest -q tests/reconciliation/test_engine.py tests/reconciliation/test_validators.py tests/reconciliation/test_dependencies.py tests/reconciliation/test_identities.py`

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add src/sb_processor/reconciliation/engine.py src/sb_processor/reconciliation/validators.py tests/reconciliation/test_engine.py tests/reconciliation/test_validators.py
git commit -m "fix: require explicit acceptance of content loss"
```

### Task 6: Improve human review and pre-write preview artifacts

**Files:**
- Modify: `src/sb_processor/reconciliation/artifacts.py`
- Modify: `tests/reconciliation/test_artifacts.py`
- Modify: `README.md`

**Interfaces:**
- Consumes: v1.1 `FinalChangeSet` decisions, accepted risks, dependency records, applicable/excluded statuses, findings, and UPDATE contents.
- Produces: concise `HUMAN_REVIEW.md`; `WRITE_PREVIEW.md` sections `CREATE`, `UPDATE`, `UNCHANGED`, `SKIPPED`, `DEFERRED`, `BLOCKED`, `INVALID`, `Accepted risks`, `Blocking issues`, and `Dependencies`; keeps existing JSON filenames/diffs/CLI.

- [ ] **Step 1: Write failing human-review tests**

Assert one shared decision lists all affected paths, evidence, blocking state, recommendation, and each option's exact consequence. Resolved decisions are omitted from the normal pending interface but remain in JSON.

- [ ] **Step 2: Write failing preview tests**

Assert all seven status sections, useful UPDATE diffs, accepted Dataset loss and authorizing HR ID, blocking collision/dependency messages, and same-batch dependency states are readable in Markdown. Assert the no-vault-write statement remains.

- [ ] **Step 3: Run artifact tests and verify RED**

Run: `.venv/bin/python -m pytest -q tests/reconciliation/test_artifacts.py`

Expected: FAIL because v1 lacks the new sections/consequences.

- [ ] **Step 4: Implement Markdown rendering from the v1.1 result**

Render only model state; do not recompute logic in artifacts. Rename presentation `NO_CHANGE` to `UNCHANGED` and show SKIPPED distinctly. Keep staging paths and input/vault hash verification unchanged.

- [ ] **Step 5: Update CLI documentation and run artifact/CLI tests**

Run: `.venv/bin/python -m pytest -q tests/reconciliation/test_artifacts.py tests/test_cli.py -k 'reconcil or preview or decision'`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/sb_processor/reconciliation/artifacts.py tests/reconciliation/test_artifacts.py README.md
git commit -m "feat: improve reconciliation safety review artifacts"
```

### Task 7: Replay the v1 fixture and record v1.1 evidence

**Files:**
- Modify: `tests/reconciliation/test_freeze_fixture.py`
- Create: `docs/reconciliation-v1.1-evaluation.md`
- Modify: `README.md`

**Interfaces:**
- Consumes: unchanged frozen Agent A/B release, copied fixture vault, public reconciliation/CLI APIs, and v1 metrics from `docs/reconciliation-v1-evaluation.md`.
- Produces: deterministic pending/resolved/deferred fixture lifecycle, v1/v1.1 metric table, staged demonstration artifacts, and freeze recommendation.

- [ ] **Step 1: Write failing fixture regression assertions**

Assert same-batch Data Mining Map links produce zero redundant decisions; Classification collision cannot silently pass; Classification uses one shared decision; Dataset generic approval is invalid; explicit loss acceptance remains visible; both resolved and deferred target dependency paths are demonstrated; original Agent A/B and copied vault hashes remain unchanged.

- [ ] **Step 2: Run fixture test and verify RED**

Run: `.venv/bin/python -m pytest -q tests/reconciliation/test_freeze_fixture.py`

Expected: FAIL on v1 decision counts/options/readiness.

- [ ] **Step 3: Fix fixture-only integration defects without broadening policy**

Adjust stable grouping keys, fixture adapters, or rendering only when synthetic tests already define the intended behavior. Add a focused failing test before each production fix.

- [ ] **Step 4: Run the full relevant suite**

Run: `.venv/bin/python -m pytest -q tests/reconciliation tests/test_cli.py tests/review tests/processing tests/knowledge/test_retrieval.py tests/knowledge/test_vault_registry.py`

Expected: PASS.

- [ ] **Step 5: Generate a fresh copied-fixture demonstration**

Run pending reconciliation, create decisions using only emitted valid options, run an explicit-loss-acceptance path and a deferred-dependency path, and preserve both artifact sets. Hash Agent A/B artifacts, copied vault, and real vault before/after.

- [ ] **Step 6: Write the evaluation**

Record v1/v1.1 metrics, auto-resolved dependencies, remaining semantic decisions, excluded changes, accepted risks, final CREATE/UPDATE counts, human/preview examples, test results, immutable hashes, and the explicit freeze answer.

- [ ] **Step 7: Run full suite and verify release evidence**

Run: `.venv/bin/python -m pytest -q`

Expected: PASS with only documented skips/warnings and no failure.

- [ ] **Step 8: Commit**

```bash
git add tests/reconciliation/test_freeze_fixture.py docs/reconciliation-v1.1-evaluation.md README.md src/sb_processor/reconciliation
git commit -m "test: verify reconciliation v1.1 safety lifecycle"
```

### Task 8: Final branch verification and review

**Files:**
- Modify only if final review exposes a Critical/Important defect, with a failing regression test first.

**Interfaces:**
- Consumes: complete branch, approved spec, implementation plan, SDD ledger, and copied demonstration artifacts.
- Produces: review package, one whole-branch review, verified fix pass if needed, clean branch, and integration handoff.

- [ ] **Step 1: Verify status, commits, and immutable artifacts**

Run `git status --short --branch`, `git log --oneline 22b8560..HEAD`, upstream SHA-256 checks, and copied/real vault manifests. The only expected untracked file is the preserved ZIP.

- [ ] **Step 2: Run relevant and full suites**

Run the Task 7 relevant command, then `.venv/bin/python -m pytest -q`.

Expected: both pass.

- [ ] **Step 3: Build the Superpowers review package and request one whole-branch review**

Use the plan workspace, approved spec, Review Focus section, ledger rulings, base commit `22b8560`, and current HEAD. The review must verify every final-deliverable demonstration and explicitly look for ways an unsafe applicable change could still reach `READY_FOR_WRITE`.

- [ ] **Step 4: Re-grade findings and perform at most one TDD fix pass**

Fix Critical/Important findings with RED→GREEN regression tests and full suite. Ledger deferred minors and any rulings exactly as required by `superpowers:executing-plans`.

- [ ] **Step 5: Run final verification and use the finishing workflow**

Run full relevant/full tests again, confirm clean tracked state and preserved ZIP, report commits/metrics/artifact links/rulings/deferred minors, answer the freeze question, and present the branch integration choices without merging or pushing automatically.
