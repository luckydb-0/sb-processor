# Reconciliation v1.2 Implementation Plan

> **For Codex:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Freeze Reconciliation v1.2 by correcting vault identity scope, enforcing human-decision referential integrity, distinguishing valid empty results, and proving a non-empty safe result with the real engine.

**Architecture:** Keep the v1.1 reconciliation pipeline. Add shared identity-namespace helpers at its existing validation boundary, perform deterministic reference remaps when decisions are grouped, run a final integrity validator before state derivation, and add one additive final state. Validate with focused TDD plus unchanged-fixture replay.

**Tech Stack:** Python 3.12, Pydantic, pytest, Markdown/JSON staging artifacts, Git.

---

### Task 1: Restrict identities to the real vault namespace

**Files:**
- Modify: `src/sb_processor/reconciliation/identities.py`
- Modify: `src/sb_processor/reconciliation/dependencies.py`
- Modify: `src/sb_processor/reconciliation/inputs.py` if the shared boundary belongs at load time
- Test: `tests/reconciliation/test_identities.py`
- Test: `tests/reconciliation/test_dependencies.py`

**Step 1: Write failing behavior tests**

Add literal fixtures proving that a Dot and Map with the same H1 do not collide,
non-vault README/config/prompt Markdown does not claim an identity, an explicit
duplicate alias still is ambiguous, a path-qualified Map link resolves, an
approved batch CREATE resolves, and a deferred batch target does not.

**Step 2: Run the focused tests and observe RED**

Run: `.venv/bin/python -m pytest tests/reconciliation/test_identities.py tests/reconciliation/test_dependencies.py -q`

Expected: failures showing H1/repository identity pollution.

**Step 3: Implement the minimal namespace rules**

Share the same indexable-root and explicit-frontmatter-identity logic between
the identity registry and dependency resolver. Do not use fallback H1 titles as
global identities. Preserve existing alias and deferred-note behavior.

**Step 4: Run focused and reconciliation tests**

Run: `.venv/bin/python -m pytest tests/reconciliation/test_identities.py tests/reconciliation/test_dependencies.py tests/reconciliation -q`

Expected: PASS.

**Step 5: Commit**

```bash
git add src/sb_processor/reconciliation/identities.py src/sb_processor/reconciliation/dependencies.py src/sb_processor/reconciliation/inputs.py tests/reconciliation/test_identities.py tests/reconciliation/test_dependencies.py
git commit -m "fix: restrict reconciliation identities to vault notes"
```

### Task 2: Preserve grouped human-decision references

**Files:**
- Modify: `src/sb_processor/reconciliation/models.py`
- Modify: `src/sb_processor/reconciliation/engine.py`
- Modify: `src/sb_processor/reconciliation/artifacts.py`
- Test: `tests/reconciliation/test_engine.py`
- Test: `tests/reconciliation/test_artifacts.py`

**Step 1: Write a failing grouping regression**

Build one root dependency issue referenced by multiple changes and dependency
records. Assert that grouping keeps one stable decision, rewrites every
reference to it, records the remap, and produces identical IDs on replay.

**Step 2: Run the focused test and observe RED**

Run: `.venv/bin/python -m pytest tests/reconciliation/test_engine.py -k "group or remap" -q`

Expected: at least one superseded ID remains referenced or no remap is recorded.

**Step 3: Implement deterministic remapping**

Add an additive `decision_id_remap` field to `FinalChangeSet`. Collapse remap
chains, replace IDs across all existing reference holders, deduplicate stable
lists, and render the remap in the decision artifact.

**Step 4: Run focused and reconciliation tests**

Run: `.venv/bin/python -m pytest tests/reconciliation/test_engine.py tests/reconciliation/test_artifacts.py tests/reconciliation -q`

Expected: PASS.

**Step 5: Commit**

```bash
git add src/sb_processor/reconciliation/models.py src/sb_processor/reconciliation/engine.py src/sb_processor/reconciliation/artifacts.py tests/reconciliation/test_engine.py tests/reconciliation/test_artifacts.py
git commit -m "fix: preserve grouped human decision references"
```

### Task 3: Block dangling human-decision references

**Files:**
- Modify: `src/sb_processor/reconciliation/validators.py`
- Modify: `src/sb_processor/reconciliation/engine.py`
- Modify: `src/sb_processor/reconciliation/artifacts.py`
- Test: `tests/reconciliation/test_validators.py`
- Test: `tests/reconciliation/test_artifacts.py`

**Step 1: Write failing integrity tests**

Inject missing IDs independently through a change, issue, dependency, collision,
loss/risk, and unresolved summary. Assert deterministic blocking findings with
the reference origin. Assert the preview exposes the finding.

**Step 2: Run tests and observe RED**

Run: `.venv/bin/python -m pytest tests/reconciliation/test_validators.py tests/reconciliation/test_artifacts.py -k "decision_reference or dangling" -q`

Expected: missing IDs are not reported or do not block readiness.

**Step 3: Implement and integrate the validator**

Return ERROR-level validation findings for each dangling reference, call it
after recomputation/remapping and before state derivation, and include those
findings in the preview's Blocking issues section.

**Step 4: Run reconciliation tests**

Run: `.venv/bin/python -m pytest tests/reconciliation -q`

Expected: PASS.

**Step 5: Commit**

```bash
git add src/sb_processor/reconciliation/validators.py src/sb_processor/reconciliation/engine.py src/sb_processor/reconciliation/artifacts.py tests/reconciliation/test_validators.py tests/reconciliation/test_artifacts.py
git commit -m "fix: validate human decision reference integrity"
```

### Task 4: Make write readiness non-empty and prove the positive path

**Files:**
- Modify: `src/sb_processor/reconciliation/models.py`
- Modify: `src/sb_processor/reconciliation/engine.py`
- Modify: `src/sb_processor/reconciliation/artifacts.py`
- Create: `tests/reconciliation/test_positive_integration.py`
- Modify: existing reconciliation tests that intentionally produce empty valid results

**Step 1: Write failing state and integration tests**

Assert a valid empty batch returns `NO_APPLICABLE_CHANGES`. Build an actual
staging fixture with one CREATE and one UPDATE, explicit valid metadata, an
existing update target, preserved durable content, and valid provenance. Assert
the engine returns `READY_FOR_WRITE`, both changes are applicable, and the
preview contains CREATE, UPDATE, and a unified diff.

**Step 2: Run tests and observe RED**

Run: `.venv/bin/python -m pytest tests/reconciliation/test_positive_integration.py tests/reconciliation -q`

Expected: missing enum or the empty result still reports READY.

**Step 3: Implement minimal state derivation and rendering**

Add `NO_APPLICABLE_CHANGES`; derive it only after all mandatory validations
pass and the applicable list is empty. Keep `READY_FOR_WRITE` for non-empty
valid subsets only. Update human-readable artifact wording.

**Step 4: Run reconciliation and full tests**

Run: `.venv/bin/python -m pytest tests/reconciliation -q`

Run: `.venv/bin/python -m pytest -q`

Expected: PASS.

**Step 5: Commit**

```bash
git add src/sb_processor/reconciliation tests/reconciliation
git commit -m "feat: distinguish empty reconciliation results"
```

### Task 5: Replay the frozen fixture and publish freeze evidence

**Files:**
- Modify: `src/sb_processor/reconciliation/engine.py` (version only if not already updated)
- Create: `docs/reconciliation-v1.2-evaluation.md`
- Create: staging-only v1.2 run artifacts and downloadable archive

**Step 1: Hash and replay unchanged inputs**

Record hashes for the frozen Agent A/B artifacts, replay through the real v1.2
engine, answer only the emitted implementable decisions, and verify the hashes
again. Do not edit source artifacts or the vault.

**Step 2: Verify freeze invariants**

Confirm the false Machine Learning ambiguity is absent, no emitted artifact has
a dangling decision reference, genuine semantic decisions remain, final state
semantics are correct, and the positive fixture remains non-empty READY.

**Step 3: Write the evaluation and archive**

Document v1.1/v1.2 metrics, automatically resolved ambiguities, remaining
decisions, blocked/deferred/applicable counts, test output, file hashes, and the
freeze recommendation. Package the run outputs without adding the archive to
Git.

**Step 4: Run final verification**

Run: `.venv/bin/python -m pytest -q`

Run repository lint/type checks if configured.

Expected: all relevant checks PASS and no vault file changes.

**Step 5: Commit tracked evidence**

```bash
git add docs/reconciliation-v1.2-evaluation.md src/sb_processor/reconciliation/engine.py
git commit -m "test: verify reconciliation v1.2 freeze lifecycle"
```

### Task 6: Final review and handoff

**Step 1: Review the complete main-branch delta**

Use a fresh reviewer against the v1.2 specification. Resolve every blocking or
material finding with a failing test, minimal fix, and fresh suite run.

**Step 2: Verify repository state**

Report branch, commits, tracked/untracked files, tests, frozen hashes, artifact
paths, and whether v1.2 is safe to freeze. Do not implement or invoke the Safe
Vault Writer.
