# Reconciliation + Human Review v1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Convert a frozen Agent A proposal and Agent B review into an audited, human-resolvable, deterministically validated `FinalChangeSet` without writing to the vault.

**Architecture:** Add a standalone `sb_processor.reconciliation` package that loads immutable upstream artifacts, applies allow-listed objective and exact semantic patches, creates deterministic human decisions for ambiguity, validates the resulting changes, and stages JSON/Markdown review and preview artifacts. The CLI reruns reconciliation from immutable inputs with an optional decision map, so resolution never compounds prior output.

**Tech Stack:** Python 3.11+, Pydantic 2, PyYAML, standard-library `difflib`, pytest

**Spec:** `docs/superpowers/specs/2026-10-25-reconciliation-human-review-v1-design.md`

## Global Constraints

- Do not modify Agent A or Agent B behavior or artifacts.
- Do not write to the real or fixture vault.
- Do not call a cloud model.
- Automatic semantic patches are limited to the exact quoted remove/replace grammar in the design.
- `READY_FOR_WRITE` requires zero pending decisions and zero validation errors; it does not mean a write occurred.
- Work on `feat/reconciliation` and create coherent incremental commits without squashing.

## Review Focus

- A run whose reviewed proposal differs from `original_agent_a_proposal.json` must preserve both hashes and report the structured delta; covered in Task 1 input-loading tests.
- Duplicate Agent B issues and multiple issues on one note must retain stable IDs and independent outcomes; covered in Task 3 engine tests.
- A quoted semantic correction with zero or multiple target occurrences must not patch content; covered in Task 2 fix tests.
- Resolving all decisions by deferring/skipping must produce an unambiguous ready write set without treating blocked changes as writes; covered in Task 3 lifecycle tests.
- A rerun over an existing `reconciliation/` directory must derive output only from immutable Agent A/B inputs and preserve their hashes; covered in Task 5 CLI integration tests.

---

### Task 1: Reconciliation domain models and immutable input loading

**Files:**
- Create: `src/sb_processor/reconciliation/__init__.py`
- Create: `src/sb_processor/reconciliation/models.py`
- Create: `src/sb_processor/reconciliation/inputs.py`
- Create: `tests/reconciliation/__init__.py`
- Create: `tests/reconciliation/helpers.py`
- Create: `tests/reconciliation/test_models_and_inputs.py`

**Interfaces:**
- Consumes: existing `ProcessingProposal`, `ReviewResult`, `Action`, and `StrictModel`.
- Produces: `ReconciliationInputs`, `ReconciledIssue`, `ReconciledChange`, `HumanDecision`, `DecisionOption`, `ValidationFinding`, `FinalChangeSet`, related enums, and `load_reconciliation_inputs(run: Path, vault: Path) -> ReconciliationInputs`.

- [ ] **Step 1: Write failing model and input tests**

Test strict enum/model round trips, stable JSON fields, reviewed/original proposal hash preservation, `agent_a/proposal.json` equality enforcement, Agent B path alignment, input-file SHA-256 capture, and the release fixture's one Map-path pre-review adjustment.

- [ ] **Step 2: Run the tests and verify RED**

Run: `pytest -q tests/reconciliation/test_models_and_inputs.py`

Expected: collection/import failure because the package and interfaces do not exist.

- [ ] **Step 3: Implement the reconciliation models and loader**

Add the exact enums and fields from the approved design. `load_reconciliation_inputs` reads only the run and vault, verifies required artifacts and hashes, identifies the optional original proposal, produces structured field-level pre-review adjustments, and never reads prior reconciliation output.

- [ ] **Step 4: Run the tests and verify GREEN**

Run: `pytest -q tests/reconciliation/test_models_and_inputs.py`

- [ ] **Step 5: Commit**

```bash
git add src/sb_processor/reconciliation tests/reconciliation
git commit -m "feat: add reconciliation domain models"
```

### Task 2: Allow-listed deterministic and exact semantic fixes

**Files:**
- Create: `src/sb_processor/reconciliation/fixes.py`
- Create: `tests/reconciliation/test_fixes.py`

**Interfaces:**
- Consumes: `NoteChange`, `ReviewIssue`, current vault content, and reconciliation issue models from Task 1.
- Produces: `classify_and_apply_fix(change: NoteChange, issue: ReviewIssue, content: str, existing_content: str | None) -> FixResult` and pure helper patch operations.

- [ ] **Step 1: Write failing objective-fix tests**

Cover Concept direct-PDF metadata removal with Lecture/page provenance retained, exact newly introduced alias removal, refusal to remove an existing alias, exact canonical link replacement, and refusal of generic link advice.

- [ ] **Step 2: Run objective tests and verify RED**

Run: `pytest -q tests/reconciliation/test_fixes.py -k 'objective or provenance or alias or link'`

- [ ] **Step 3: Implement the minimal objective fix registry**

Use issue type plus exact correction shape; every successful result records one or more before/after patch operations. Return `HUMAN_REQUIRED` rather than changing text when preconditions fail.

- [ ] **Step 4: Run objective tests and verify GREEN**

Run: `pytest -q tests/reconciliation/test_fixes.py -k 'objective or provenance or alias or link'`

- [ ] **Step 5: Write failing semantic grammar tests**

Cover exact quoted removal, exact quoted replacement, body-only scope, zero/multiple occurrences, mixed delimiters, “remove or soften,” broad rewriting, and unrelated-content preservation.

- [ ] **Step 6: Run semantic tests and verify RED**

Run: `pytest -q tests/reconciliation/test_fixes.py -k semantic`

- [ ] **Step 7: Implement exact semantic patch parsing**

Recognize only the approved finite grammar, require one case-sensitive occurrence in the body, and emit a single audited patch operation. Do not infer text from `explanation` or accept broad `corrected_content`.

- [ ] **Step 8: Run all fix tests and verify GREEN**

Run: `pytest -q tests/reconciliation/test_fixes.py`

- [ ] **Step 9: Commit**

```bash
git add src/sb_processor/reconciliation/fixes.py tests/reconciliation/test_fixes.py
git commit -m "feat: add audited reconciliation fixes"
```

### Task 3: Issue reconciliation and human-decision lifecycle

**Files:**
- Create: `src/sb_processor/reconciliation/engine.py`
- Create: `tests/reconciliation/test_engine.py`

**Interfaces:**
- Consumes: `ReconciliationInputs`, Task 2 fix results, and optional `dict[str, str]` decision selections.
- Produces: `reconcile(inputs: ReconciliationInputs, selections: dict[str, str] | None = None) -> ReconciliationResult` with stable `RC-*`/`HR-*` IDs, reconciled changes, and decisions.

- [ ] **Step 1: Write failing PASS, FIX, and multi-issue tests**

Assert PASS content remains byte-identical, deterministic and exact semantic fixes are audited, and several issues on one change retain independent IDs/outcomes while deriving one change status.

- [ ] **Step 2: Run these tests and verify RED**

Run: `pytest -q tests/reconciliation/test_engine.py -k 'pass or fix or multiple'`

- [ ] **Step 3: Implement issue-by-issue reconciliation**

Align changes by target path, fail on missing/duplicate alignments, apply fixes sequentially in stable issue order, and build reconciled changes without mutating Pydantic inputs.

- [ ] **Step 4: Run these tests and verify GREEN**

Run: `pytest -q tests/reconciliation/test_engine.py -k 'pass or fix or multiple'`

- [ ] **Step 5: Write failing human-decision tests**

Cover narrow questions, stable IDs, allowed option effects, unknown IDs/options, Agent A `REVIEW_REQUIRED` action inference, pending state, `APPLY_RECONCILED_CHANGE`, `SKIP_CHANGE`, and `DEFER`.

- [ ] **Step 6: Run decision tests and verify RED**

Run: `pytest -q tests/reconciliation/test_engine.py -k 'decision or pending or deferred or resolved'`

- [ ] **Step 7: Implement deterministic decisions and resumption**

Build options with predefined effects, validate the selection map exactly, infer CREATE/UPDATE only from target existence, keep unresolved decisions pending, and exclude skipped/deferred changes from the write set without inventing content.

- [ ] **Step 8: Run all engine tests and verify GREEN**

Run: `pytest -q tests/reconciliation/test_engine.py`

- [ ] **Step 9: Commit**

```bash
git add src/sb_processor/reconciliation/engine.py tests/reconciliation/test_engine.py
git commit -m "feat: reconcile reviews with human decisions"
```

### Task 4: Final validation, conflicts, and update preservation

**Files:**
- Create: `src/sb_processor/reconciliation/validators.py`
- Create: `tests/reconciliation/test_validators.py`
- Modify: `src/sb_processor/reconciliation/engine.py`
- Modify: `tests/reconciliation/test_engine.py`

**Interfaces:**
- Consumes: reconciled changes, scanned vault metadata/content, Agent B checks/issues, and audited patches.
- Produces: `validate_final_changes(...) -> list[ValidationFinding]`, preservation-decision requests, and overall `FinalChangeSetState` derivation in the engine.

- [ ] **Step 1: Write failing per-change validation tests**

Cover invalid/traversing path, missing content, malformed/wrong frontmatter, provenance, workflow placeholders, unresolved/noncanonical links, target-existence/action mismatch, and a claimed fix whose marker remains.

- [ ] **Step 2: Run per-change tests and verify RED**

Run: `pytest -q tests/reconciliation/test_validators.py -k 'path or content or frontmatter or provenance or workflow or link or action or claimed'`

- [ ] **Step 3: Implement per-change validation by reusing existing validators**

Adapt final CREATE/UPDATE content to `NoteChange` only for validation, reuse `validate_change` and `audit_wikilinks`, add exact state/path checks, and translate findings to reconciliation validation codes.

- [ ] **Step 4: Run per-change tests and verify GREEN**

Run: `pytest -q tests/reconciliation/test_validators.py -k 'path or content or frontmatter or provenance or workflow or link or action or claimed'`

- [ ] **Step 5: Write failing conflict and preservation tests**

Cover duplicate CREATE, CREATE/UPDATE collision, divergent same-target content, normalized target identity, Map/Dot basename conflict, retained headings/paragraphs, high-similarity paragraphs, audited local deletion, and unexplained paragraph loss becoming human review.

- [ ] **Step 6: Run conflict/preservation tests and verify RED**

Run: `pytest -q tests/reconciliation/test_validators.py -k 'conflict or duplicate or map or preservation or paragraph or heading'`

- [ ] **Step 7: Implement batch conflict and preservation validation**

Normalize Markdown blocks exactly as designed, use `SequenceMatcher` threshold `0.90`, distinguish semantic preservation questions from structural validation errors, and integrate generated decisions before final state derivation.

- [ ] **Step 8: Add and pass complete-state tests**

Assert pending decisions yield `PENDING_HUMAN_REVIEW`, validation errors yield `INVALID`, and fully resolved valid changes yield `READY_FOR_WRITE`.

Run: `pytest -q tests/reconciliation/test_validators.py tests/reconciliation/test_engine.py`

- [ ] **Step 9: Commit**

```bash
git add src/sb_processor/reconciliation/validators.py src/sb_processor/reconciliation/engine.py tests/reconciliation
git commit -m "feat: validate final reconciliation change sets"
```

### Task 5: Human-review artifacts, write preview, and CLI

**Files:**
- Create: `src/sb_processor/reconciliation/artifacts.py`
- Create: `tests/reconciliation/test_artifacts.py`
- Modify: `src/sb_processor/cli.py:22-78,93-146`
- Modify: `tests/test_cli.py`
- Modify: `README.md`

**Interfaces:**
- Consumes: `ReconciliationResult`, vault contents, optional decisions path.
- Produces: `stage_reconciliation(run: Path, result: ReconciliationResult, inputs: ReconciliationInputs) -> Path`, `run_reconciliation(run: Path, vault: Path, decisions_path: Path | None) -> FinalChangeSet`, and CLI `reconcile --run --vault [--decisions]`.

- [ ] **Step 1: Write failing artifact tests**

Assert exact output filenames, concise counts/questions/options in `HUMAN_REVIEW.md`, machine-readable decision status/selection, grouped write preview, unified UPDATE diff, stable diff filename, and no files outside `reconciliation/`.

- [ ] **Step 2: Run artifact tests and verify RED**

Run: `pytest -q tests/reconciliation/test_artifacts.py`

- [ ] **Step 3: Implement atomic artifact staging**

Render all JSON from Pydantic models, build Markdown from the same result, create unified diffs with `difflib.unified_diff`, and replace only the run's `reconciliation/` directory after successful rendering.

- [ ] **Step 4: Run artifact tests and verify GREEN**

Run: `pytest -q tests/reconciliation/test_artifacts.py`

- [ ] **Step 5: Write failing CLI tests**

Cover parser fields, decision JSON loading, invalid decision shape, output-inside-vault rejection, pending and resolved status output, and upstream/vault immutability across reruns.

- [ ] **Step 6: Run CLI tests and verify RED**

Run: `pytest -q tests/test_cli.py -k reconcile`

- [ ] **Step 7: Implement the reconcile CLI and README workflow**

Wire load → reconcile → validate → stage; print state and canonical artifact paths. Document the four-step human workflow and explicitly state that no vault write exists.

- [ ] **Step 8: Run CLI and reconciliation tests and verify GREEN**

Run: `pytest -q tests/reconciliation tests/test_cli.py tests/review tests/processing`

- [ ] **Step 9: Commit**

```bash
git add src/sb_processor/reconciliation/artifacts.py src/sb_processor/cli.py tests/reconciliation/test_artifacts.py tests/test_cli.py README.md
git commit -m "feat: stage human review and write previews"
```

### Task 6: Frozen-fixture lifecycle and release evidence

**Files:**
- Create: `tests/reconciliation/test_freeze_fixture.py`
- Create: `docs/reconciliation-v1-evaluation.md`
- Modify: `README.md`

**Interfaces:**
- Consumes: release run `staging/agent_b_v1_freeze_benchmark/gpt-5.4-mini-low-freeze-release`, vault `staging/two_pass_fixture_vault`, and public CLI/engine APIs.
- Produces: deterministic integration coverage and a recorded freeze recommendation.

- [ ] **Step 1: Write the frozen-fixture integration test**

Copy run/vault into `tmp_path`, hash all original Agent A/B artifacts and vault files, assert PASS unchanged, provenance auto-fix, exact `and data mining` semantic removal, pending HumanDecisions, resolution via generated example choices, final validation, ready state, preview groups, and at least one UPDATE diff. Assert every preexisting hash remains unchanged.

- [ ] **Step 2: Run the integration test and verify its first failure**

Run: `pytest -q tests/reconciliation/test_freeze_fixture.py`

Expected: fail on the first fixture behavior not yet covered by the synthetic implementation.

- [ ] **Step 3: Fix only fixture-exposed integration gaps**

Do not broaden the automatic patch grammar. Correct path alignment, artifact lookup, decision grouping, or validation adapters as required by the frozen contracts.

- [ ] **Step 4: Run reconciliation and relevant suites**

Run: `pytest -q tests/reconciliation tests/test_cli.py tests/review tests/processing tests/knowledge/test_retrieval.py tests/knowledge/test_vault_registry.py`

Expected: all selected tests pass.

- [ ] **Step 5: Run the available full suite and record baseline-only failures**

Run: `pytest -q`

Expected in the current shell: reconciliation tests pass; pre-existing optional-dependency failures may remain for `pymupdf4llm`, `docling`, `qdrant_client`, and non-installed subprocess import. Report every failure by name.

- [ ] **Step 6: Generate the demonstration artifacts from a copied release fixture**

Run the CLI first without decisions, copy the generated allowed option keys into an example decision JSON, rerun, and inspect `HUMAN_REVIEW.md`, `final_change_set.json`, `WRITE_PREVIEW.md`, and one UPDATE diff. Hash the real `../gd-gdb` vault before and after.

- [ ] **Step 7: Write evaluation evidence**

Record counts, examples, artifact paths, test output, hashes, remaining limitations, and the explicit answer to whether v1 is reliable enough to freeze.

- [ ] **Step 8: Commit**

```bash
git add tests/reconciliation/test_freeze_fixture.py docs/reconciliation-v1-evaluation.md README.md src/sb_processor/reconciliation
git commit -m "test: verify reconciliation v1 lifecycle"
```

### Task 7: Final branch verification and review

**Files:**
- Modify only if verification exposes a reconciliation defect, with a failing regression test first.

**Interfaces:**
- Consumes: complete branch.
- Produces: verified commit history and handoff evidence.

- [ ] **Step 1: Verify repository state and commit history**

Run: `git status --short --branch` and `git log --oneline feat/agent-b-v1.2..HEAD`

- [ ] **Step 2: Re-run the complete relevant suite**

Run: `pytest -q tests/reconciliation tests/test_cli.py tests/review tests/processing tests/knowledge/test_retrieval.py tests/knowledge/test_vault_registry.py`

- [ ] **Step 3: Re-run the copied fixture lifecycle and hash checks**

Confirm `PENDING_HUMAN_REVIEW` then `READY_FOR_WRITE`, preview/diff presence, immutable Agent A/B inputs, immutable fixture vault, and immutable real vault.

- [ ] **Step 4: Request whole-branch code review and address only verified findings**

Use the requesting-code-review workflow, then add regression tests before any fix.

- [ ] **Step 5: Run final verification and report**

Run relevant and full tests again, ensure `git status` is clean, and list every commit and any baseline environment failures.
