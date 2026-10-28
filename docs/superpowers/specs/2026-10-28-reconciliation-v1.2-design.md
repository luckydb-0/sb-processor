# Reconciliation v1.2 — Final Fixes and Freeze Validation

## Intent

Reconciliation v1.2 is a narrow safety release over v1.1. It fixes the false
`[[Machine Learning]]` ambiguity, guarantees that human-decision references
remain internally consistent after decisions are grouped, distinguishes a
valid empty result from an actually write-ready batch, and proves the positive
write-ready path with the real reconciliation engine.

The architecture remains unchanged. The Safe Vault Writer, vault mutation,
post-write indexing, Agent A/B redesign, and new LLM behavior are out of scope.

## Root causes

### Identity pollution

The reconciliation loader scans every Markdown file below the supplied root.
`ScannedNote.title` falls back to the first H1, and the identity registry treats
that fallback as a global title. Consequently:

- repository documents such as READMEs and prompts enter the note namespace;
- a Map whose H1 is `Machine Learning` claims the same lexical identity as the
  canonical `Machine Learning.md` Dot;
- display headings become global link targets even when they are not explicit
  note metadata.

### Dangling decision references

Dependency decisions are grouped deterministically, but the grouping operation
currently replaces only references local to the matching issue. Other changes
and dependency records can continue to reference a removed decision ID (the
frozen fixture exposes `HR-018`). No final referential-integrity gate detects
that corruption.

### Ambiguous successful emptiness

`READY_FOR_WRITE` currently covers both a non-empty applicable change set and a
valid result containing no applicable changes. This weakens the meaning of a
positive freeze-validation result.

## Chosen design

### 1. Vault-scoped identity namespace

Identity validation and dependency resolution will share one definition of an
indexable vault note:

- only configured knowledge roots are eligible (`Dots`, `Maps`, and
  `Sources/University`, optionally beneath `Atlas`);
- canonical relative path and filename stem are identities;
- only an explicit frontmatter `title` is a title identity;
- valid frontmatter aliases remain identities;
- H1 headings are display content, not global identities.

The same rules apply to existing notes and proposed batch content. Existing
notes remain present when their updates are deferred or skipped. Path-qualified
links and true duplicate aliases continue to produce precise resolution or real
ambiguity. A proposed CREATE becomes an available target only when it belongs
to the final applicable batch, preserving v1.1 dependency semantics.

This reuses the repository's established retrieval-root policy rather than
adding a second vault architecture. Hard-coded filename exclusions were
rejected because they would only move the false-positive boundary. Treating
every H1 as an alias was rejected because headings are not an Obsidian-wide
identity declaration.

### 2. Deterministic decision remapping and integrity validation

When several decisions represent one root issue, the lexically first stable ID
remains canonical. All superseded IDs are remapped to it across:

- change-level decision lists;
- issue decision references;
- dependency root decisions;
- identity collisions;
- material-loss records and accepted risks;
- unresolved-decision summaries.

The final change set records the old-to-canonical mapping for auditability.
Remaps are transitively collapsed and reference lists are deduplicated without
changing their stable order.

A final deterministic validator enumerates every decision reference and checks
that it resolves to an emitted `HumanDecision`. A dangling reference emits a
blocking validation error with its origin and prevents write readiness. The
same error is visible in `WRITE_PREVIEW.md`; it is never hidden only in JSON.

Silent deletion of dangling references was rejected because it would destroy
the audit trail. Regenerating all decision IDs after each pass was rejected
because it would make resumed human review unstable.

### 3. Explicit empty-applicable state

`READY_FOR_WRITE` will require at least one applicable CREATE or UPDATE and all
mandatory validations to pass. A valid result with zero applicable changes
will use `NO_APPLICABLE_CHANGES`. Invalid or unresolved results keep their
existing `INVALID` and `PENDING_HUMAN_REVIEW` meanings.

This is additive and does not authorize writing. It only makes the reconciliation
state precise enough for the later Safe Writer contract.

## Processing flow

1. Load immutable Agent A/B artifacts and scan the vault.
2. Restrict scanned and proposed identities to the configured note namespace.
3. Reconcile changes, issues, content preservation, and batch dependencies.
4. Apply human decisions and deterministically remap grouped decision IDs.
5. Recompute dependencies, identities, losses, and applicable changes.
6. Validate all human-decision references.
7. Derive final state:
   - blocking validation error -> `INVALID`;
   - unresolved blocking decision -> `PENDING_HUMAN_REVIEW`;
   - valid but empty subset -> `NO_APPLICABLE_CHANGES`;
   - valid non-empty subset -> `READY_FOR_WRITE`.
8. Render the complete state, blocking findings, decisions, dependencies,
   accepted risks, and diffs into staging-only artifacts.

## Compatibility and auditability

- Existing v1.1 Pydantic payloads remain readable; new fields have defaults.
- Original Agent A and Agent B files are copied and hashed, never rewritten.
- The decision-remap table is additive evidence, not a replacement for original
  decision records.
- The real vault remains read-only throughout tests and evaluation.

## Verification

Focused tests will prove:

- a Dot and Map may share an H1 without making an unqualified Dot link
  ambiguous;
- repository Markdown outside note roots is excluded;
- explicit duplicate aliases remain ambiguous;
- approved batch creates resolve and deferred targets block dependents;
- grouped decisions leave no dangling references and replay deterministically;
- deliberately missing decision IDs invalidate the change set and appear in
  the preview;
- empty valid batches return `NO_APPLICABLE_CHANGES`;
- a real one-CREATE/one-UPDATE fixture reaches non-empty `READY_FOR_WRITE` and
  produces an update diff.

Finally, the frozen v1.1 inputs will be replayed unchanged. The evaluation will
record input hashes, corrected decision/dependency metrics, final state,
applicable/blocked counts, full test results, and confirmation that no vault
file was modified.
