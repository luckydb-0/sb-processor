# Reconciliation v1.1 evaluation

Evaluated on 2026-10-27 against the unchanged frozen Agent A/Agent B release at
`staging/agent_b_v1_freeze_benchmark/gpt-5.4-mini-low-freeze-release` and a copied
`staging/two_pass_fixture_vault`. No Safe Vault Writer was implemented or invoked.

## Freeze answer

**Yes. Reconciliation v1.1 is safe enough to freeze and proceed to the Safe Vault Writer
milestone.** The applicable subset now fails closed: unresolved identities, dependencies,
content loss, unsafe transformations, and non-atomic identity outcomes are excluded before
`READY_FOR_WRITE`. The frozen replay deliberately reaches `READY_FOR_WRITE` with an empty
applicable subset because every proposed CREATE and ordinary UPDATE still has at least one
blocking dependency. That is the correct result, not a success metric regression.

There are no known safety blockers for freezing reconciliation. The future writer must consume
only `applicable_change_ids` and must treat an empty list as a no-op.

## v1 versus v1.1

| Metric | v1 | v1.1 |
| --- | ---: | ---: |
| Proposed note changes | 24 | 24 |
| Human decisions initially required | 41 | 19 |
| Link-related decisions | 27 | 4 grouped root decisions |
| Same-batch link occurrence decisions | ~22 | 0 |
| `Data Mining - Map` dependency occurrences | not grouped | 16 audited, 0 separate decisions |
| Blocking identity conflicts in `READY_FOR_WRITE` | 1 known | 0 |
| Unacknowledged material losses in applicable changes | present | 0 |
| Accepted-risk records | not typed | 5 |
| Accepted material-loss records | not itemized | 7 |

The 23-decision reduction in link review comes from batch dependency analysis and grouping, not
from suppressing validation. All 206 pending dependency occurrences remain in the JSON audit.
`Statistics`, `Business Intelligence`, `Data Preparation`, and the pre-existing ambiguous
`Machine Learning` target become four shared `UNRESOLVED_DEPENDENCY` decisions.

## Pending human review

The pending replay contains 19 independent decisions:

- 4 grouped unresolved-dependency decisions;
- 1 shared `Classification` identity decision;
- 5 content-preservation decisions;
- 8 explicit semantic-risk decisions;
- 1 whole-change existing-note decision.

`Classification.md` versus the existing `Predictive Classification.md` alias produces one shared
decision covering both identity participants and dependent notes. The only executable semantic
outcomes are `KEEP_SEPARATE` and `DEFER`; `MERGE` is not offered. `KEEP_SEPARATE` is available only
when the existing note hash matches and one exact inline alias can be minimally removed.

The `Dataset.md` preservation decision lists the exact missing paragraph. It offers
`ACKNOWLEDGE_CONTENT_LOSS`, `SKIP_CHANGE`, and `DEFER`; generic
`APPLY_RECONCILED_CHANGE` is rejected. Semantic concerns similarly require
`ACCEPT_STAGED_RISK`, which records the exact Agent B concern rather than treating a generic note
approval as validation.

## Decision replay and recomputation

The demonstration choices intentionally exercise all safety paths:

- exact unresolved link markup is removed only after a grouped human decision;
- source-specific changes with incompatible risks are deferred;
- `KEEP_SEPARATE` applies the exact Classification alias-removal plan;
- three content-preservation decisions explicitly accept seven listed losses;
- two semantic risks are explicitly accepted and recorded;
- every identity and dependency is recomputed to a fixed point after decisions.

The Classification create later becomes dependency-blocked. Atomic consequence propagation then
also blocks the alias-removal UPDATE, preventing an orphaned removal of the existing
`Classification` alias. The final effective registry retains the current vault identity and has no
blocking collision.

The resolved result is:

- state: `READY_FOR_WRITE`;
- pending decisions: 0;
- validation errors: 0;
- blocking identity collisions: 0;
- statuses: 20 `BLOCKED`, 4 `DEFERRED`;
- staged actions outside the applicable subset: 15 CREATE, 5 UPDATE;
- applicable actions: 0 CREATE, 0 UPDATE;
- accepted risks: 5, including 7 itemized material losses;
- unacknowledged material losses in the applicable subset: 0.

This demonstrates both dependency outcomes. Focused regression tests show a link to an approved
same-batch CREATE as `TARGET_CREATED_IN_BATCH`. The frozen replay shows the conservative path:
`Data Mining - Map` is excluded after its own dependency closure fails, so its 14 remaining
downstream occurrences recompute to `TARGET_DEFERRED` without generating occurrence-level human
decisions or rewriting links.

## Review artifacts

The final local dry-run demonstration is under
`staging/reconciliation_v1_1_demo_release/` (Git-ignored):

- pending review: `pending-release/HUMAN_REVIEW.md`;
- pending machine state: `pending-release/final_change_set.json`;
- explicit selections: `decisions.json`;
- resolved review audit: `resolved-release/human_decisions.json`;
- safety preview: `resolved-release/WRITE_PREVIEW.md`;
- final writer contract: `resolved-release/final_change_set.json`.

`HUMAN_REVIEW.md` shows affected paths, evidence, blocking state, recommendation, and exact option
consequences. `WRITE_PREVIEW.md` separates CREATE, UPDATE, UNCHANGED, SKIPPED, DEFERRED, BLOCKED,
and INVALID; it also groups dependency states and shows accepted risks. Risks whose changes are
excluded are labeled as outside the applicable subset.

## Immutability and dry-run evidence

The original artifacts remain byte-identical:

| Artifact | SHA-256 |
| --- | --- |
| `original_agent_a_proposal.json` | `ff9271de8855c47e442781884815bb059db68c941b236352e9bbca505131c64d` |
| reviewed `proposal.json` | `4532fb1cb0ebdaaea20885a3b05559935aebe7569c97ace7d08bc9c79559036f` |
| `agent_b/review.json` | `39e3ab92bda24b6d52bee2d4100f792fe207c61eb1197baf75cbde6993c29208` |

The source and copied-run relative manifest hashes both equal
`d6d2ac29aed5d9855a84527d00d3c9e4250371d1656aa54d3f6f74732e7ba319`. The source and copied
fixture-vault manifests both equal
`188cf235cd1739625489e28e68169ca4733ec794f9431e0de0001a02eed00497`.

The demonstration passed only the copied vault path to reconciliation. No Markdown file in the
real `../gd-gdb` vault was modified on 2026-10-27; its non-Obsidian-content manifest is
`afd0c861ae12f1e798cbc5fdc7d27d04e19c181b339c2d7a6991b4969936d223`. The live Obsidian app did
update `.obsidian/workspace.json` independently during the evaluation, so that UI-state file is
excluded from the note-content manifest and is not attributed to reconciliation.

## Verification

- Focused reconciliation suite: 108 passed.
- Reconciliation/CLI/review/processing/knowledge suite: 228 passed.
- Full repository suite after the final review fixes: 285 passed, 1 skipped.

The whole-branch safety review found four fail-closed gaps and each received a RED-to-GREEN
regression before this final run:

- a post-selection UPDATE that introduces a new global identity collision is excluded and its
  dependencies are recomputed;
- `KEEP_SEPARATE` conflict and atomicity checks use both exact transformation participants rather
  than inferring participants from issue IDs;
- generic existing-note approval is no longer an executable option; and
- the exact vault bytes used by `KEEP_SEPARATE` must still match the scanned source hash.

All tests and demonstrations remain staging-only; no vault writer, Git commit to a vault, SQLite
update, or Qdrant update exists in v1.1.

## Non-blocking limitations

- The frozen fixture is highly connected, so fixed-point dependency closure excludes the whole
  proposed graph rather than pretending an unsafe partial batch is writable.
- Complex semantic merging remains unsupported and blocked; `MERGE` is intentionally absent.
- Explicit risk acceptance records authorization but does not repair prose.
- The supported inline alias patch reconstructs the alias list and may normalize unusual spacing
  around unaffected aliases. This is an audited formatting limitation, not a knowledge-loss or
  readiness bypass; exact semantic contents and all unrelated note bytes are preserved.
- A future Safe Vault Writer still needs its own atomic filesystem, hash, backup, and Git safety
  contract. It must not reinterpret reconciliation decisions.
