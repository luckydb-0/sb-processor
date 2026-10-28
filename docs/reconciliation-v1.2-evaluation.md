# Reconciliation v1.2 Freeze Evaluation

Date: 2026-10-28  
Branch: `main`  
Engine: `reconciliation-v1.2`

## Verdict

Reconciliation v1.2 is safe enough to freeze and proceed to the separately
authorized Safe Vault Writer milestone.

The three v1.2 release blockers are closed:

1. repository files and display headings no longer pollute the vault identity
   namespace;
2. grouped human decisions preserve a deterministic, globally valid reference
   graph;
3. `READY_FOR_WRITE` now means a validated, non-empty applicable subset.

No genuinely blocking reconciliation problem remains in the evaluated scope.
This verdict does not authorize writing to the vault, and no Safe Vault Writer
was implemented.

## Evaluation inputs

The v1.1 frozen Agent A/Agent B fixture was replayed without editing its source
artifacts. SHA-256 values before and after reconciliation were identical:

| Artifact | SHA-256 |
|---|---|
| `original_agent_a_proposal.json` | `ff9271de8855c47e442781884815bb059db68c941b236352e9bbca505131c64d` |
| `proposal.json` | `4532fb1cb0ebdaaea20885a3b05559935aebe7569c97ace7d08bc9c79559036f` |
| `agent_a/proposal.json` | `4532fb1cb0ebdaaea20885a3b05559935aebe7569c97ace7d08bc9c79559036f` |
| `agent_b/review.json` | `39e3ab92bda24b6d52bee2d4100f792fe207c61eb1197baf75cbde6993c29208` |

A recursive comparison of the copied fixture vault before and after both runs
reported no differences. The real Obsidian vault was not used as a write
target.

## Metric comparison

| Metric | v1 | v1.1 | v1.2 |
|---|---:|---:|---:|
| Initial human decisions | 41 | 19 | 18 |
| Link/dependency decisions | 27 | 4 | 3 |
| Same-batch link decisions | ~22 | 0 | 0 |
| False `[[Machine Learning]]` ambiguity groups | not isolated | 1 | 0 |
| Unresolved identity conflicts admitted to an applicable READY subset | 1 known | 0 | 0 |
| Dangling human-decision IDs | not measured | 1 known (`HR-018`) | 0 |
| Unacknowledged material content-loss risks in an applicable READY subset | present | 0 | 0 |

Fewer decisions are not used as the correctness criterion. The remaining 18
decisions are independently traceable to semantic risk, content preservation,
concept identity, explicit whole-change review, or one of three genuinely
unresolved targets.

## Identity and dependency results

### Machine Learning regression

The frozen fixture contains 18 `[[Machine Learning]]` dependency occurrences.
All 18 now resolve to:

```text
TARGET_EXISTS_IN_VAULT
Atlas/Dots/Machine Learning.md
blocking: false
```

`Atlas/Maps/Machine Learning - Map.md` may retain the display heading
`# Machine Learning` without claiming the Dot's global identity. `README.md`,
`config/Machine Learning.md`, and prompt files are absent from the effective
identity registry. The v1.1 `HR-023` false ambiguity decision is not emitted.

Explicit frontmatter aliases remain global identities. The real
`Classification` / `Predictive Classification` alias collision is still
detected and receives one shared `CONCEPT_IDENTITY` decision.

### Same-batch and deferred dependencies

The 16 `[[Data Mining - Map]]` occurrences still generate no dedicated human
decision. In the pending frozen fixture the proposed Map has other blocking
decisions, so those occurrences correctly report `TARGET_DEFERRED` rather than
pretending that a proposed CREATE is committed. The positive fixture proves
that a link to an approved same-batch CREATE reports
`TARGET_CREATED_IN_BATCH` and remains non-blocking.

The three remaining dependency decisions concern the genuinely absent targets
`Statistics`, `Business Intelligence`, and `Data Preparation`. Repeated
occurrences are grouped by root target rather than escalated per link.

## Human-decision integrity

The pending frozen result records these deterministic remaps:

```json
{
  "HR-010": "HR-009",
  "HR-013": "HR-011",
  "HR-016": "HR-001",
  "HR-018": "HR-004"
}
```

Every reference from changes, issues, per-change dependencies, top-level
dependencies, identity collisions, material losses, accepted risks, unresolved
summaries, and remap targets resolves to an emitted `HumanDecision`. The same
IDs and remaps are reproduced on replay.

The final integrity validator emits
`DANGLING_HUMAN_DECISION_REFERENCE` with the exact origin for any missing ID.
That ERROR forces `INVALID` and appears under **Blocking issues** in
`WRITE_PREVIEW.md`.

## Frozen fixture outcomes

### Initial review

| Category | Decisions |
|---|---:|
| `CONCEPT_IDENTITY` | 1 |
| `CONTENT_PRESERVATION` | 5 |
| `SEMANTIC_RISK` | 8 |
| `UNRESOLVED_DEPENDENCY` | 3 |
| explicit existing-note review | 1 |
| **Total** | **18** |

Initial state: `PENDING_HUMAN_REVIEW`.

### Decisions replayed

Only options emitted by the engine were selected. Missing-link markup was
removed where explicitly selected; semantic changes without sufficient support
were deferred; `KEEP_SEPARATE` used the existing exact alias-removal recipe;
and individual content losses were acknowledged only through their dedicated
content-preservation decisions.

### Resolved result

| Result | Count |
|---|---:|
| Blocked changes | 20 |
| Deferred changes | 4 |
| Applicable CREATE | 0 |
| Applicable UPDATE | 0 |
| Accepted risks | 5 |
| Blocking identity collisions | 0 |
| Validation errors | 0 |
| Dangling decision references | 0 |

Final state: `NO_APPLICABLE_CHANGES`.

This is a valid conservative result, not a positive write-ready result. Many
changes remain dependency-blocked after the chosen deferrals, so admitting none
to the applicable subset is the safe outcome.

## Positive non-empty READY proof

`tests/reconciliation/test_positive_integration.py` runs the real load →
reconcile → stage pipeline with:

- one CREATE (`Atlas/Dots/New Concept.md`);
- one UPDATE (`Atlas/Dots/Existing Concept.md`);
- exact preservation of the durable existing paragraph;
- valid lecture-note provenance;
- links to an existing note and an approved same-batch CREATE.

The result is `READY_FOR_WRITE` with `applicable_change_ids = [RC-001,
RC-002]`, no human decisions, no blocking dependencies, no collisions, no
validation findings, and an actual unified UPDATE diff. Fixture-vault hashes
remain identical after staging.

This proves that `NO_APPLICABLE_CHANGES` did not merely rename every successful
path: non-empty, fully validated batches still reach `READY_FOR_WRITE`.

## Safety regressions covered

- Dot/Map shared H1 does not create an identity collision.
- Repository Markdown outside configured note roots is ignored.
- Duplicate explicit aliases remain ambiguous.
- Approved same-batch CREATE dependencies resolve.
- Deferred targets block dependents without rewriting their links.
- Grouped decisions remap every reference deterministically.
- Missing decision references invalidate the result and appear in the preview.
- Generic approval cannot bypass Dataset material-loss review.
- Explicit content-loss acceptance remains itemized in Accepted risks.
- A valid empty result is not labeled READY.
- A non-empty CREATE/UPDATE result reaches READY and renders its diff.
- All reconciliation remains staging-only.

## Verification

```text
pytest: 293 passed, 1 skipped
reconciliation subset: 116 passed
separate lint/type command: not configured in pyproject.toml
```

The only warnings are existing Python extension deprecation warnings emitted by
optional document-layout dependencies.

## Freeze recommendation

Freeze Reconciliation v1.2. The later Safe Vault Writer may consume only a
non-empty `READY_FOR_WRITE` applicable subset and must still require its own
explicit write authorization. `NO_APPLICABLE_CHANGES`, `INVALID`, and
`PENDING_HUMAN_REVIEW` are not writable states.
