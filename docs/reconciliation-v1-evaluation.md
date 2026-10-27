# Reconciliation + Human Review v1 evaluation

Evaluated on 2026-10-26 against the frozen Agent B release
`staging/agent_b_v1_freeze_benchmark/gpt-5.4-mini-low-freeze-release` and a copied
`staging/two_pass_fixture_vault`. Reconciliation did not write to either the fixture vault or the
real `../gd-gdb` vault.

## Result

**Freeze recommendation: yes.** Reconciliation + Human Review v1 is reliable enough to freeze and
proceed to the Safe Vault Writer milestone. The frozen lifecycle completed from immutable Agent A/B
inputs through `PENDING_HUMAN_REVIEW`, explicit decisions, deterministic revalidation, and
`READY_FOR_WRITE`. The remaining limitations are non-blocking and are listed below.

## Demonstrated lifecycle

The final verified local demonstration is under `staging/reconciliation_v1_demo_release/`
(Git-ignored):

- pending review: `pending/HUMAN_REVIEW.md` and `pending/final_change_set.json`;
- example choices: `decisions.json`;
- resolved review: `run/reconciliation/HUMAN_REVIEW.md`;
- writer contract: `run/reconciliation/final_change_set.json`;
- dry run: `run/reconciliation/WRITE_PREVIEW.md` and `run/reconciliation/diffs/`.

The pending run contained 24 changes and 41 narrow decisions, with no validation errors. Of those
decisions, 18 came from original Agent B/review-required issues; 22 were exact link dependencies on
directly blocked CREATEs; and one was the update-preservation guard. Dependency-only pending CREATEs
were deliberately not allowed to recursively multiply the review queue.

The example decision file selected:

- 22 `APPLY_RECONCILED_CHANGE` choices;
- 10 `REMOVE_LINK` choices, each replacing only exact wikilink markup while retaining visible text;
- 9 `DEFER` choices, affecting four changes.

The resumed result contained 15 CREATEs, 5 UPDATEs, and 4 deferred changes. It reached
`READY_FOR_WRITE` with zero pending decisions and zero error findings. Nine update-preservation
warnings remain recorded after explicit human approval; warnings do not bypass an error gate.

## Required examples

- **PASS unchanged:** before decisions, `RC-001`, the lecture note, retained Agent A's content byte
  for byte (`original_content_sha256 == final_content_sha256`) with no automatic patch.
- **Objective FIX:** `RC-006`, `Atlas/Dots/Clustering.md`, removed direct PDF provenance while
  retaining the Lecture Note reference and page/slide evidence.
- **Semantic exact FIX:** `RC-009`, `Atlas/Dots/Regression.md`, removed only the unsupported exact
  phrase `and data mining`.
- **HumanDecision:** the run emitted explicit `HR-*` records with question, context, Agent A/B
  positions, allowed effects, status, and selected option. `REMOVE_LINK` is available only for one
  exact unresolved wikilink token and is audited as patch operations.
- **Dry-run diff:** `diffs/RC-006.diff` shows the Clustering UPDATE; no writer was invoked.

Across the resolved result, 23 objective issues and one exact semantic issue were classified for
automatic handling. The audit contains 53 patch operations. Ambiguous choices remain represented in
the final JSON even when deferred or explicitly accepted.

## Immutability evidence

The copied upstream artifacts retained the same SHA-256 values as the frozen release:

| Artifact | SHA-256 |
| --- | --- |
| `original_agent_a_proposal.json` | `ff9271de8855c47e442781884815bb059db68c941b236352e9bbca505131c64d` |
| reviewed `proposal.json` | `4532fb1cb0ebdaaea20885a3b05559935aebe7569c97ace7d08bc9c79559036f` |
| `agent_b/review.json` | `39e3ab92bda24b6d52bee2d4100f792fe207c61eb1197baf75cbde6993c29208` |

The copied fixture vault manifest hash was
`773e58ac7a9191e5f0459774b48d2b0f916c9480a813be38576fca26089dd551` before and after the
final replay. The real `../gd-gdb` vault remained untouched. All generated files stayed under the
copied run's `reconciliation/` directory or the Git-ignored demonstration directory. The resumed
result also records the absolute human-decision source and its SHA-256
(`2e885a549b1957682373b6bb5ae5195cf12e27d49e01667ca364a1830f9c6ac4`) in the final writer
contract.

## Verification

The reconciliation, CLI, review, processing, retrieval, and vault-registry suite passes: 200 tests.
The full suite passes with 257 tests and 1 skipped test. The focused safety coverage includes stale
UPDATE rejection, canonical path and symlink containment, Agent B issue ownership, whole-change
review escalation, exact semantic-fix boundaries, human-decision provenance, and staging-time input
immutability.

## Remaining non-blocking limitations

- This milestone stages a writer contract only; it cannot modify the vault.
- Semantic ambiguity still requires explicit human judgment; v1 does not regenerate prose with an
  LLM.
- `REMOVE_LINK` preserves visible text but cannot infer a better canonical target. The human may
  instead apply, skip, or defer the whole change.
- Dependency decisions are generated for direct/root blocked CREATEs. A later choice that defers a
  dependency-only CREATE can still make a downstream result invalid; the user must revise choices
  and rerun rather than receiving an automatic semantic guess.
- Update-loss warnings are coarse guards and remain visible after human acceptance.
