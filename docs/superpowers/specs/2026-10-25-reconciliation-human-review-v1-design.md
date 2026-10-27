# Reconciliation + Human Review v1 design

## Intent

Turn the frozen Agent A proposal and Agent B review for one staged run into an auditable `FinalChangeSet` that a human can resolve and inspect before a later writer exists. Preserve Agent A, Agent B, and reconciliation as separate layers. Never write to the Obsidian vault.

The normal human path is:

1. run reconciliation;
2. open `reconciliation/HUMAN_REVIEW.md`;
3. supply a JSON map of narrow decisions;
4. rerun reconciliation with that map;
5. inspect `reconciliation/WRITE_PREVIEW.md`.

## Goals

- Reconcile every Agent B issue independently instead of collapsing a note to one opaque status.
- Apply objective fixes automatically when the transformation is deterministic and supported.
- Apply a semantic correction automatically only when it is an exact, local deletion or replacement whose target and replacement are explicit in Agent B's structured issue and whose scope can be verified mechanically.
- Turn every remaining ambiguity into a narrow, machine-readable human decision with deterministic option effects.
- Validate final note content, actions, paths, conflicts, provenance, and update preservation before reporting `READY_FOR_WRITE`.
- Produce machine-readable artifacts plus concise human review and write-preview Markdown.
- Demonstrate the complete pending-to-ready lifecycle on the latest Agent B freeze-release fixture.

## Non-goals

- No vault writes, vault Git commits, or post-write indexing.
- No Agent A or Agent B redesign.
- No open-ended model call, Agent C, UI, LangGraph, chatbot, or RAG layer.
- No automatic acceptance of ambiguous Agent B prose.
- No reorganization or mutation of existing Agent A/B artifacts.

## Anti-goals

- A `READY_FOR_WRITE` result that still contains pending decisions, ambiguous actions, invalid content, or unresolved conflicts.
- Human questions that ask broadly how to handle a note.
- A human choice whose meaning is interpreted by an LLM or changes between runs.
- Whole-note regeneration for a local issue.
- Treating `DEFER` as approval of the associated change.

## Existing components to reuse

- `ProcessingProposal`, `NoteChange`, `ReviewResult`, `ReviewedChange`, `ReviewIssue`, and the existing strict Pydantic serialization conventions.
- The immutable reviewed `proposal.json`/`agent_a/proposal.json` and `agent_b/review.json` staging contract.
- Agent B request artifacts for evidence and existing-note context when needed for audit.
- `review.validators.validate_change`, `processing.staging.audit_wikilinks`, vault scanning, and registry normalization for deterministic checks.
- Existing `SUMMARY.md` as an upstream summary. Reconciliation adds its own canonical `HUMAN_REVIEW.md` without replacing it.
- Current CLI and staging conventions.
- The release fixture at `staging/agent_b_v1_freeze_benchmark/gpt-5.4-mini-low-freeze-release` and its matching `staging/two_pass_fixture_vault` vault. All UPDATE hashes in the release proposal match this vault.

### Authoritative inputs and the freeze-fixture normalization

Reconciliation must operate on the top-level `proposal.json`, because that is the exact proposal Agent B reviewed and its paths align with `agent_b/review.json`. `agent_a/proposal.json` must be byte-identical to it when present or input validation fails.

Some benchmark runs, including the release fixture, also contain `original_agent_a_proposal.json`. That file is the earlier untouched Agent A output. In the release fixture it differs only by the deterministic pre-review Map path normalization from `Atlas/Maps/Machine Learning.md` to `Atlas/Maps/Machine Learning - Map.md`. Reconciliation must preserve and hash both files, record a structured `pre_review_adjustments` diff, and never describe the reviewed proposal as byte-identical to the original. For ordinary runs without `original_agent_a_proposal.json`, `proposal.json` is both the original and reviewed Agent A input.

## Approaches considered

### 1. Hybrid deterministic reconciliation — selected

Use a registry of explicit objective fix handlers plus a deliberately small exact semantic patch protocol. Escalate everything else to a structured decision. This is deterministic, offline, auditable, and exercises both automatic and human paths on the frozen fixture.

### 2. Constrained model-assisted rewriting

Ask a model to rewrite only affected sections and validate the result. This covers more Agent B prose automatically but introduces another model-dependent loop, larger audit artifacts, and new failure modes before the deterministic core is stable.

### 3. Objective fixes only

Apply only metadata/provenance/alias mechanics and send every semantic issue to a human. This is mechanically safe but creates too many low-value decisions and does not satisfy the milestone's semantic-patch lifecycle.

## Package structure

Add a focused `sb_processor.reconciliation` package:

- `models.py`: reconciliation, decision, validation, provenance, and final-state models.
- `fixes.py`: deterministic fix classification and pure patch functions.
- `validators.py`: final content/action validation, conflict detection, and update-preservation checks.
- `engine.py`: load immutable inputs, reconcile issues, apply decisions, derive statuses, and build `FinalChangeSet`.
- `artifacts.py`: JSON/Markdown serialization and unified diffs.

The root `models.py` remains the frozen Agent A/B contract. Reconciliation imports those types rather than extending or rewriting them.

## Domain model

### Stable identifiers

Changes receive deterministic IDs based on proposal order: `RC-001`, `RC-002`, and so on. Issues receive `RC-001-I01`-style IDs based on the existing `ReviewResult.issues` index for that change. Human decisions receive `HR-001`, `HR-002`, and so on in stable change/issue order.

Identifiers do not depend on random values or prose hashes, so rerunning with a decision file addresses the same objects.

### Reconciled issue

Each Agent B issue becomes a reconciliation record containing:

- its stable issue ID and original Agent B issue index;
- issue type, explanation, correction, and evidence references;
- classification: `OBJECTIVE`, `SEMANTIC_EXACT`, or `AMBIGUOUS`;
- outcome: `APPLIED`, `HUMAN_REQUIRED`, `DEFERRED`, `SKIPPED_WITH_HUMAN_APPROVAL`, or `INVALID`;
- exact patch operations and before/after snippets when applied;
- linked human-decision ID when not automatic.

This preserves issue-level detail even when a note has several different outcomes.

### Reconciled change

`ReconciledChange` contains:

- stable change ID;
- Agent A proposal index, action, target, and content SHA-256;
- Agent B reviewed-change status and issue indices;
- issue reconciliation records and applied fixes;
- whether a decision is required and its IDs;
- final action, target, content, and content SHA-256 when applicable;
- derived change status: `READY`, `FIXED`, `BLOCKED`, `DEFERRED`, or `INVALID`;
- validation findings.

The original full Agent A content and Agent B prose remain in their immutable artifacts. Index/path/hash references avoid unnecessary duplication while keeping the final artifact self-checking. Applied before/after snippets make corrections directly auditable.

### Human decisions

`HumanDecision` contains:

- stable ID, affected change and issue IDs, category, status, question, and context;
- concise Agent A and Agent B positions;
- recommendation, rationale, and confidence when evidence supports one;
- a list of `DecisionOption` objects;
- selected option when resolved.

Statuses are `PENDING`, `RESOLVED`, and `DEFERRED`.

Every option carries a predefined effect, not free-form prose:

- `APPLY_RECONCILED_CHANGE`: keep the Agent A draft plus any already-applied safe patches. When Agent A used `REVIEW_REQUIRED`, infer `CREATE` only if the target does not exist and `UPDATE` only if it does.
- `SKIP_CHANGE`: convert the affected change to `NO_CHANGE` and record explicit human rejection/omission.
- `DEFER`: block this change from the write set and mark the decision `DEFERRED`.

Questions name the smallest issue, such as “Should `Classification.md` be created separately from the existing `Predictive Classification.md`?” The engine never sends selected options to a model.

### Final change set

`FinalChangeSet` contains:

- source run ID;
- reconciliation version;
- provenance paths and SHA-256 values for the original Agent A proposal when separately present, the exact proposal Agent B reviewed, Agent B review, and the supplied decision file;
- any pre-review proposal adjustments, limited to a structured diff between the preserved original and reviewed proposal;
- all reconciled changes;
- current human decisions and unresolved decision IDs;
- global validation findings;
- overall state: `PENDING_HUMAN_REVIEW`, `READY_FOR_WRITE`, or `INVALID`.

`READY_FOR_WRITE` means there are no pending decisions, every included CREATE/UPDATE has valid content, actions and paths are unambiguous, and all deterministic validation passes. Deferred or skipped changes remain explicit but are not included in the future write set.

## Reconciliation rules

### PASS

Copy Agent A action, path, and content unchanged into the reconciled layer, then run final validation. An Agent A `REVIEW_REQUIRED` action never becomes writable merely because Agent B reported PASS; it still needs a human decision.

### Objective FIX

Automatic handlers are allow-listed and pure. V1 handlers cover:

- removal of direct PDF `source_file`/`location` provenance from Concept Notes while retaining Lecture/page provenance;
- removal of a specifically named newly introduced alias when Agent B gives an exact alias value and comparison with existing content confirms it is new;
- exact canonical wikilink replacement only when Agent B supplies the canonical target and the target resolves;
- exact workflow-contamination removal when the offending literal occurs once;
- exact frontmatter field repair when the required field/value is fully specified and schema-valid.

Generic instructions such as “use a verified target or remove the link” do not authorize an automatic mutation.

### Semantic exact FIX

V1 permits only a local patch when all of these hold:

- Agent B supplies a literal source span and an explicit deletion or replacement;
- the span occurs exactly once in the proposed content;
- the replacement is empty or itself quoted in the structured correction;
- the patch does not touch frontmatter unless handled by an objective handler;
- the patch changes one contiguous span or one complete sentence/paragraph explicitly identified by the issue;
- post-patch validation passes and unrelated content hashes by section remain unchanged.

Examples include removing the exact phrase `and data mining` or a precisely identified unsupported sentence. Broad requests to “soften,” “align,” “limit,” or “rewrite” remain human decisions.

V1 recognizes only this finite prose grammar:

- `Remove "<literal>" ...`, `Remove '<literal>' ...`, or the same form with a backtick-delimited literal: delete that literal when it occurs exactly once in the Markdown body.
- `Replace "<old>" with "<new>" ...`, including single-quote or backtick delimiters: replace `<old>` when it occurs exactly once and `<new>` is explicitly present in the correction.

Matching is case-sensitive and does not infer a literal from the explanation when the correction itself does not contain one. Mixed delimiters, multiple occurrences, missing spans, directives such as “remove or soften,” and full `corrected_content` without a matching one-hunk literal operation are not automatic in v1. This intentionally makes the release fixture's exact removal of `and data mining` eligible while leaving broad semantic corrections for human review.

### REVIEW_REQUIRED and ambiguous FIX

Create one narrow decision per independent unresolved issue. Closely duplicated Agent B issues on the same change may share one decision only when they ask the same underlying question and have the same option effects. The change remains blocked while any linked decision is pending.

### Decisions and resumption

The CLI accepts a JSON object mapping decision IDs to allowed option keys. Unknown IDs, unknown option keys, duplicate semantic choices, or choices for already unrelated decisions are errors. Rerunning always starts from immutable Agent A/B artifacts and reapplies deterministic fixes, so decisions cannot compound patches across runs.

`SKIP_CHANGE` and `DEFER` never fabricate content. `APPLY_RECONCILED_CHANGE` uses only the already staged Agent A content plus recorded safe patches.

## Final validation

Validation is deterministic and produces structured findings with codes, affected change IDs, messages, and severity.

Per-change checks:

- relative `.md` target path with no traversal, absolute path, or backslash;
- action matches target existence (`CREATE` absent, `UPDATE` present);
- nonempty final content for CREATE/UPDATE;
- valid YAML frontmatter and matching note type;
- workflow contamination and unresolved placeholder/status language absent;
- provenance structure valid;
- all wikilinks resolve to the fixture vault or another included CREATE target and use canonical paths when explicit paths are present;
- final content no longer triggers an issue claimed as automatically fixed;
- update content passes the existing Agent B cumulative-integrity check and has no unresolved `cumulative_integrity` or `existing_note` issue;
- update content passes a coarse independent loss guard: every existing Markdown heading remains, and every normalized existing prose paragraph of at least 40 characters is either present verbatim, has a `difflib.SequenceMatcher` ratio of at least `0.90` against one final paragraph, or differs only inside an audited exact patch. A guard failure creates a human decision rather than guessing that the loss is acceptable.

Batch checks:

- duplicate target paths;
- CREATE/UPDATE conflicts;
- different final contents for one target;
- rename/path conflicts represented by competing target identities;
- normalized Map/Dot basename conflicts unless the Map uses the canonical ` - Map` suffix;
- duplicate canonical target identities after normalization.

Any error finding makes the state `INVALID`. Pending decisions take precedence over otherwise valid content and produce `PENDING_HUMAN_REVIEW`.

## Artifacts

All new output stays under `<run>/reconciliation/`:

```text
reconciliation.json
human_decisions.json
HUMAN_REVIEW.md
final_change_set.json
WRITE_PREVIEW.md
diffs/
```

`reconciliation.json` is the detailed issue-by-issue audit. `human_decisions.json` is the editable/machine interface. `HUMAN_REVIEW.md` shows counts and pending decisions only, without developer diagnostics. `final_change_set.json` is the future writer contract. `WRITE_PREVIEW.md` groups CREATE, UPDATE, NO_CHANGE, and BLOCKED/DEFERRED paths and embeds or links unified UPDATE diffs. `diffs/` contains one stable filename per updated change.

Writing these artifacts may replace a previous `reconciliation/` result for the same immutable run. The engine verifies input hashes before and after and never writes elsewhere.

## CLI

Add:

```bash
python -m sb_processor reconcile \
  --run staging/run_<id> \
  --vault staging/fixture_vault \
  [--decisions decisions.json]
```

The command rejects output paths inside the supplied vault, loads `proposal.json` (or the preserved identical `agent_a/proposal.json`) and `agent_b/review.json`, writes reconciliation artifacts, and prints the overall state plus the paths to `HUMAN_REVIEW.md` and `WRITE_PREVIEW.md`.

## Testing and demonstration

Unit tests use small synthetic runs and vaults to cover:

- PASS unchanged;
- objective fix and audit;
- multiple independent fixes on one change;
- review-required decision generation;
- valid resolution and invalid choice rejection;
- deferred/blocked behavior;
- exact semantic patch scope;
- existing-content preservation;
- conflicting paths/actions and Map/Dot collisions;
- invalid path, frontmatter, provenance, and wikilinks;
- complete ready run;
- CLI parsing and artifact output.

An integration test copies the frozen release fixture and `staging/two_pass_fixture_vault` into a temporary directory. It verifies both original/reviewed proposal hashes and their one Map-path adjustment, runs pending reconciliation, supplies deterministic example decisions, resumes, and checks the ready/preview lifecycle without modifying either vault or original artifacts.

The final manual demonstration runs against a copy of the latest freeze-release fixture, shows at least one PASS, objective fix, exact semantic fix, HumanDecision, pending state, resolved/deferred decision, ready state, and UPDATE unified diff. SHA-256 manifests confirm the original Agent A and Agent B artifacts and the real vault are unchanged.

## Constraints and builder calls

- Python 3.11+, Pydantic 2, PyYAML, standard library only; no new dependency is needed.
- Existing Agent A/B models and runner behavior remain frozen unless a blocking integration defect is proven.
- Tests do not require cloud calls.
- Missing optional PDF/semantic dependencies in the current shell are baseline environment failures and are not changed by this milestone.
- The builder may choose small helper names and Markdown wording consistent with the repository, but may not broaden automatic patch eligibility beyond the rules above.
