# Reconciliation v1.1 — Human Decision Quality and Pre-Write Safety

## Intent

Strengthen the existing Reconciliation v1 pipeline before a Safe Vault Writer exists. V1.1 keeps
the immutable Agent A/Agent B inputs, deterministic fixes, human-decision file, staged artifacts,
and `FinalChangeSet` contract. It adds an explicit effective-state evaluation between reconciliation
and final validation so batch dependencies, vault-wide identities, decision consequences, and
material content loss are recomputed together.

The normal workflow remains:

1. run reconciliation from immutable Agent A/B artifacts;
2. review a small set of independent questions in `HUMAN_REVIEW.md`;
3. rerun with a decision JSON map;
4. inspect `WRITE_PREVIEW.md` and the `FinalChangeSet`;
5. stop. V1.1 never writes to the vault.

## Goals

- Resolve same-batch wikilinks against the final applicable change set instead of escalating each
  occurrence.
- Preserve dependency state and block/exclude dependents when their target is deferred or skipped.
- Validate canonical filenames, titles, aliases, basenames, link targets, and normalized identities
  against every relevant existing vault note plus applicable batch changes.
- Replace generic approval with category-specific, implementable decision consequences.
- Group one root identity or dependency question across every affected note while retaining a
  per-note audit trail.
- Require explicit, itemized acknowledgement before material existing-content loss can enter the
  applicable write set.
- Recompute actions, dependencies, identities, preservation state, and validation after decisions.
- Make `READY_FOR_WRITE` mean that every included change satisfies all mandatory pre-write checks.
- Make human-facing artifacts sufficient for review without consulting developer JSON.
- Replay the exact v1 fixture without altering Agent A or Agent B artifacts and compare v1/v1.1.

## Non-goals

- No Safe Vault Writer, vault mutation, vault Git commit, or post-write SQLite/Qdrant update.
- No Agent A or Agent B redesign and no mutation of their artifacts.
- No web UI, LangGraph, new embeddings, RAG changes, or additional LLM agent.
- No automatic semantic merge of notes.
- No inferred equivalence from matching titles or aliases.

## Anti-goals

- One human decision per occurrence of a same-batch wikilink.
- A decision option that describes a transformation the engine cannot perform exactly.
- A generic `APPLY_RECONCILED_CHANGE` choice that silently marks an identity or preservation issue
  resolved.
- Removing links merely because their proposed target was deferred.
- Dropping deferred/skipped existing notes from the identity registry.
- `READY_FOR_WRITE` with an applicable identity collision, required dependency failure, or
  unacknowledged material loss.

## Existing architecture retained

V1.1 keeps `sb_processor.reconciliation` and its public flow:

- `inputs.py` loads and hashes immutable Agent A/B inputs and scans the full supplied vault.
- `fixes.py` applies the existing allow-listed deterministic patches.
- `engine.py` remains the orchestrator and rebuilds from immutable inputs on every invocation.
- `validators.py` remains the final mandatory validation boundary.
- `artifacts.py` stages JSON, Markdown, and diffs under `<run>/reconciliation/` only.
- `python -m sb_processor reconcile --run ... --vault ... [--decisions ...]` remains the CLI.

The root Agent A/B Pydantic models remain unchanged. V1.1 extends reconciliation-owned models only.

## Approaches considered

### 1. Additive reconciliation state evaluator — selected

Add focused dependency and identity modules and let the engine run a deterministic evaluate/apply/
reevaluate pipeline. This makes the new safety state inspectable without replacing the v1 package or
CLI.

### 2. Expand `engine.py` and `validators.py` in place

This minimizes files but mixes extraction, grouping, transformations, validation, and rendering in
two already substantial modules. The resulting state transitions would be difficult to test and
audit.

### 3. Generic rule/transformation framework

This could support arbitrary future decision types, but it would be a new architecture and would
encourage transformations beyond the finite v1.1 safety cases.

## Package changes

- Add `dependencies.py`: wikilink extraction, target resolution, dependency records, and final
  dependency findings.
- Add `identities.py`: effective note snapshots, normalized claims, collision groups, and exact
  KEEP_SEPARATE feasibility.
- Extend `models.py`: dependency states/records, decision categories and consequences, issue
  resolution disposition, material-loss records, and accepted risks.
- Refine `engine.py`: build base reconciliation, group root decisions, apply exact consequences,
  recompute effective state, and derive the applicable subset.
- Refine `validators.py`: consume the effective identity/dependency state, treat unaccepted material
  loss as blocking, and enforce write-readiness invariants.
- Refine `artifacts.py`: render affected notes, option consequences, accepted risks, blocking
  issues, dependencies, and all output groups.

This is a responsibility split, not a new orchestration layer.

## Domain model additions

### Effective note snapshot

Identity and link resolution operate on an effective snapshot:

- Every existing vault note is present initially.
- An applicable UPDATE replaces that path's parsed title/aliases/content for evaluation.
- A deferred or skipped UPDATE does not replace anything; the original vault note remains.
- An applicable CREATE is added.
- A deferred, skipped, blocked, or invalid CREATE is absent.

The snapshot is computed in memory and never written.

### Dependency record

Each wikilink occurrence produces an audited record containing:

- stable source change ID and source path;
- exact token and normalized target identity;
- resolved target path and target change ID when known;
- target state: `TARGET_EXISTS_IN_VAULT`, `TARGET_CREATED_IN_BATCH`,
  `TARGET_UPDATED_IN_BATCH`, `TARGET_DEFERRED`, `TARGET_SKIPPED`, `TARGET_MISSING`, or
  `TARGET_AMBIGUOUS`;
- whether it blocks the source change;
- the root decision ID when the dependency follows another human decision.

Several occurrences may share one root decision. Per-occurrence records remain in the audit.

### Identity claim and collision

Each effective note contributes normalized claims for:

- canonical full path without `.md`;
- basename without `.md`;
- parsed title;
- every alias.

Claims retain their kind and source path. A mechanical collision exists when one normalized link
identity maps to more than one canonical note. This reports ambiguity; it does not assert semantic
equivalence. Path/action conflicts remain ordinary validation errors.

A collision involving only unchanged, unrelated pre-existing notes is retained as a non-blocking
audit condition; v1.1 does not make a reconciliation run responsible for repairing the entire vault.
A collision is blocking when at least one claim comes from an applicable proposed change or when an
applicable change links through that ambiguous identity.

An identity collision group contains its stable normalized identity, every existing and proposed
claim, affected change IDs, dependent change IDs, and a root decision ID when human resolution is
possible.

### Issue resolution disposition

Every reconciled issue has a disposition independent of its patch outcome:

- `ISSUE_FIXED`: an audited transformation removed the problem and revalidation passed;
- `ISSUE_EXPLICITLY_ACCEPTED`: a specific unresolved risk was accepted by an allowed option;
- `ISSUE_UNRESOLVED`: no valid transformation or acceptance exists.

Automatic patches never create an accepted-risk record. Explicit acceptance never claims an issue
was fixed.

### Material loss and accepted risk

Preservation validation emits stable material-loss records rather than free-floating warnings. Each
record contains its change ID, kind (`HEADING` or `PARAGRAPH`), normalized excerpt, source-content
hash, and resolution disposition.

One `CONTENT_PRESERVATION` decision groups all material-loss records for one UPDATE. The decision
lists every concrete loss. Its only write-enabling choice is `ACKNOWLEDGE_CONTENT_LOSS`; selecting it
creates one accepted-risk record per loss with the decision ID, option, affected note, exact excerpt,
and reason. `SKIP_CHANGE` and `DEFER` remain available. Generic apply is not.

Accepted risks are one typed, first-class `FinalChangeSet.accepted_risks` collection and are visible
in `WRITE_PREVIEW.md`. Material-loss acceptance records the loss ID/excerpt; other issue-specific
acceptance uses the same collection with its category, issue IDs, evidence, affected changes,
decision ID, selected option, and stated consequence.

### Human decision categories and options

V1.1 uses structured categories including:

- `CONCEPT_IDENTITY` / `MERGE_OR_SEPARATE`;
- `CONTENT_PRESERVATION`;
- `STRUCTURAL_CHANGE`;
- `UNRESOLVED_DEPENDENCY`;
- a precise fallback category for an Agent B issue that cannot be transformed automatically.

Each option contains a concise label and an explicit consequence description in addition to its
machine effect. Options are emitted only when the consequence is implemented.

For general cases beyond the two fixture regressions:

- `CONCEPT_IDENTITY` offers an exact identity transformation only when it can be represented as an
  audited minimal patch and revalidated; otherwise it offers `DEFER` only.
- `STRUCTURAL_CHANGE` offers a named exact transformation when implemented, plus `SKIP_CHANGE` and
  `DEFER`; it never offers generic acceptance of an invalid structure.
- `UNRESOLVED_DEPENDENCY` attaches to the target's existing root decision when possible. A truly
  missing or ambiguous target with no executable repair offers only conservative exclusion of the
  affected changes (`SKIP_CHANGE` or `DEFER`).
- Issue-specific acceptance is available only for a clearly stated non-structural semantic risk and
  creates an accepted-risk record; it cannot override identity, dependency, path, frontmatter, or
  preservation gates.

## Decision semantics

### Classification / Predictive Classification

The fixture's proposed `Classification.md` collides mechanically with the existing alias
`Classification` on `Predictive Classification.md`. The two Agent B `existing_note` concerns and
the effective-registry collision form one shared decision whose affected set includes both changes
and related dependents.

V1.1 can offer:

- `KEEP_SEPARATE` only when it can construct a minimal UPDATE from the exact current
  `Predictive Classification.md` content, remove only the exact colliding alias from frontmatter,
  preserve every other byte/field/body span, retain the expected source hash, and validate the
  resulting two identities. The same option includes the proposed Classification CREATE.
- `DEFER`, which excludes the Classification CREATE, preserves Predictive Classification exactly as
  it exists, and recomputes all dependencies.

V1.1 does not offer `MERGE` for this fixture because no safe, content-preserving canonical merge
recipe is present. A future version may add it, but a label alone is not an implementation.

### Other unresolved semantic issues

An issue-specific acceptance option may keep staged content only when the question names the exact
unresolved assertion/risk and selection records it as `ISSUE_EXPLICITLY_ACCEPTED`. `SKIP_CHANGE`
and `DEFER` are always conservative alternatives. A broad option does not resolve identity,
dependency, or preservation findings.

### Shared decisions

Decision grouping uses stable root keys rather than prose similarity:

- identity: normalized collided identity plus participating canonical paths;
- preservation: change ID plus its material-loss IDs;
- dependency: normalized target identity plus the root target decision when one exists;
- other Agent B issues: issue category and exact affected reconciliation object.

One shared decision lists all affected changes and issue IDs. Applying it updates each linked audit
record before reevaluation. Duplicate HR records are not generated for downstream occurrences.

## Batch dependency resolution

The resolver parses final Markdown wikilinks and resolves them against the effective snapshot using
Obsidian-relevant full paths, basenames, titles, and aliases.

- A unique existing target resolves as `TARGET_EXISTS_IN_VAULT`.
- An included CREATE resolves as `TARGET_CREATED_IN_BATCH`.
- An included UPDATE resolves as `TARGET_UPDATED_IN_BATCH`.
- A target change excluded by a human choice is reported as deferred or skipped.
- No claim is missing; several canonical claims are ambiguous.

Same-batch CREATE/UPDATE targets require no human decision when the target change is independently
applicable. The resolver never treats a merely proposed CREATE as committed: if its root decision is
pending, the dependency points to that decision; if the target is deferred/skipped, dependent
changes are marked `BLOCKED` and excluded from the applicable subset. Links remain unchanged.

For the Data Mining Map regression, all links to the one applicable Map CREATE resolve through one
target record and generate zero per-occurrence decisions. If that Map is deferred, all dependent
records change state deterministically and their source changes become blocked without link deletion.

## Effective identity validation

The validator builds the complete effective identity registry on every run:

1. start with all scanned vault notes, including unrelated notes;
2. retain original identities for deferred/skipped/blocked UPDATEs;
3. replace identities only for applicable UPDATEs;
4. add identities only for applicable CREATEs;
5. resolve every canonical path, basename, title, alias, and wikilink target against that registry;
6. emit blocking collision groups and ambiguous-link findings.

An unresolved collision blocks every participating proposed change and any dependent applicable
change. It cannot be downgraded by a generic note approval.

## Preservation safety

The existing heading/paragraph comparison remains deliberately coarse: harmless rewording may be
recognized by the current similarity threshold and exact audited patches. Findings that remain are
material-risk candidates and block the UPDATE until they are fixed, explicitly acknowledged, or the
change is skipped/deferred.

For `Dataset.md`, the Agent B cumulative-integrity/existing-note issues and independent paragraph
loss become one `CONTENT_PRESERVATION` decision. `APPLY_RECONCILED_CHANGE` is not an allowed option.
Acknowledgement names the omitted training/evaluation and labels material and creates visible
accepted-risk records. Without that exact acknowledgement, Dataset cannot enter the applicable
write set.

## Deterministic recomputation pipeline

Every invocation begins from immutable inputs; prior reconciliation output is never consumed.

1. Build base reconciled changes and apply existing deterministic fixes.
2. Build the initial full vault identity registry and proposed-change dependency graph.
3. Derive stable root decisions for identity, preservation, structural, dependency, and remaining
   Agent B issues.
4. Validate the supplied selection map against only the options on those decisions.
5. Apply exact consequences to a fresh in-memory change set.
6. Rebuild the effective note snapshot.
7. Recompute dependencies and propagate target states to dependents.
8. Rebuild and validate global identities.
9. Recompute preservation findings and accepted-risk coverage.
10. Run final per-change and batch validators over the applicable subset.
11. Derive statuses and overall state, then stage artifacts.

No new decision is invented only after applying selections. Downstream dependency effects attach to
the stable root decision that caused them, which keeps decision IDs reproducible across reruns.

Before applying consequences, the engine builds the affected-change/effect set for all selections.
Selections whose consequences conflict on one change are rejected as an invalid decision map. In
particular, an acceptance/apply consequence cannot be combined with `SKIP_CHANGE` or `DEFER`, and
`SKIP_CHANGE` cannot be combined with `DEFER`. The engine never resolves conflicts by precedence or
selection order.

## Status and readiness semantics

Change presentation distinguishes `CREATE`, `UPDATE`, `UNCHANGED`, `SKIPPED`, `DEFERRED`,
`BLOCKED`, and `INVALID`. Internally, skipped and deferred changes remain audited but are excluded
from the applicable subset.

`READY_FOR_WRITE` means:

- no unresolved blocking decision;
- every applicable change has a safe canonical path and valid frontmatter;
- no applicable path/action/content conflict;
- no unresolved global identity or basename/alias/title collision;
- every required dependency resolves uniquely in the effective snapshot;
- no unacknowledged material loss;
- every claimed semantic/objective fix revalidates;
- all accepted risks are explicit and linked to a resolved decision.

Deferred, skipped, blocked, and invalid changes are never writable. A result can be
`READY_FOR_WRITE` for a safe applicable subset when deliberate deferral causes dependents to become
blocked and excluded. A structural error in an otherwise applicable change makes the result
`INVALID`; pending blocking decisions produce `PENDING_HUMAN_REVIEW`.

Readiness is not authorization to write.

## Human-facing artifacts

### `HUMAN_REVIEW.md`

Show pending independent decisions only. Each decision includes category, affected paths, concise
question, relevant evidence, recommendation, blocking status, and each option's exact consequence.

### `WRITE_PREVIEW.md`

Show separate sections for:

- `CREATE`, `UPDATE`, `UNCHANGED`, `SKIPPED`, `DEFERRED`, `BLOCKED`, and `INVALID`;
- UPDATE diffs;
- accepted risks with the authorizing decision and exact omitted content;
- blocking issues with affected paths;
- dependencies grouped by source change and target state.

The preview always states that no vault files were written.

### JSON audit

`reconciliation.json`, `human_decisions.json`, and `final_change_set.json` retain original provenance
hashes, per-note issues/patches, dependency records, identity collisions, selected consequences,
accepted risks, final validation, and the applicable/excluded distinction.

## Testing strategy

Use deterministic synthetic vaults plus the unchanged frozen v1 fixture. Tests cover:

- included same-batch CREATE and UPDATE link targets;
- target deferral/skip and dependent blocking without link deletion;
- one root dependency decision shared across occurrences;
- alias/title/basename collisions with unrelated existing notes;
- retained identities for a deferred existing-note UPDATE;
- Classification shared identity decision;
- feasible KEEP_SEPARATE exact alias removal and post-transform revalidation;
- no MERGE option without a safe recipe;
- Dataset generic approval rejection;
- explicit Dataset loss acknowledgement and visible accepted risks;
- recomputation after decisions;
- mandatory readiness invariants and no vault writes;
- improved human review and preview sections;
- immutable Agent A/B and vault hashes.

The frozen fixture evaluation reports v1 versus v1.1 initial decisions, link decisions, same-batch
link decisions, unresolved write-ready collisions, unacknowledged loss risks, automatically resolved
dependencies, semantic decisions, excluded changes, accepted risks, final action counts, and tests.

## Constraints and builder calls

- Python 3.11+, Pydantic 2, PyYAML, and the standard library only; add no dependency.
- Keep Agent A/B contracts frozen.
- Preserve the untracked user-requested `reconciliation-v1-run-outputs.zip`; do not commit it.
- Continue on `feat/reconciliation`; do not develop on `main`/`master`.
- Use incremental TDD commits and do not squash.
- Do not touch the real vault; demonstrations use copied fixtures and before/after manifests.
- Exact helper names and Markdown prose may follow repository conventions, but decision options and
  their consequences may not be broadened beyond this design.
