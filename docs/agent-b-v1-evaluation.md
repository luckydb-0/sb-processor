# Agent B v1 evaluation — 2026-10-19

## Fixture and outcome

Agent B reviewed the latest staged Agent A two-pass fixture at `staging/two_pass_fixture_runs/run_20261018T161230Z_ef760c87/`, using its matching `staging/two_pass_fixture_vault/` and the authoritative review instructions from `../gd-gdb/+ Inbox/Agent B - University Processing Review Instructions.md`. The live reviewer was `gpt-4o-mini` via Structured Outputs. The 24 proposed changes yielded:

| Status | Count | Example |
| --- | ---: | --- |
| PASS | 0 | The real fixture had no clean item; a mocked integration test verifies the PASS path. |
| FIX | 11 | `Dataset.md` has unresolved `[[Machine Learning - Map]]` and `[[Data Preparation]]` links. |
| REVIEW_REQUIRED | 13 | `Classification.md` needs a decision against existing `Predictive Classification.md`; `Co-occurrence Grouping.md` has non-equivalent method/application aliases and a debatable Dot boundary. |

The raw structured result, per-change report, exact requests, and diagnostics are under that run's `agent_b/` folder. The original `proposal.json` and both the fixture vault and real vault were byte-identical before and after the evaluation.

## Evidence and deterministic checks

Each change received selected cleaned, page-aware text from Agent A's staged context. Concept Note requests prioritized explicit `Pages/slides` citations, then Pass 1 candidate provenance, then title-occurrence fallback. The Lecture Note request used its explicit parenthetical page citations, covering 45 relevant extracted pages. Agent B received only related existing-note bodies and candidate retrieval records, not the full vault. Six original rendered visual pages (13, 14, 18, 19, 31, 48) were inspected across the run. The `Machine Learning.md` review, for example, included pages 31 and 48 with their visual extraction and original PDF images.

Before the model review, validators checked frontmatter mapping and field types, workflow-state contamination, wikilink resolution against existing and same-proposal notes, and explicit canonical link paths. The runner also rejected mismatched vault snapshots by note count and original hashes. It preserved Agent A's `REVIEW_REQUIRED` action and marked missing visual evidence or missing required alias/Dot assessment for review.

## Context diagnostics

| Measure | Value |
| --- | ---: |
| Agent A proposal | 67,905 characters |
| Proposed changes | 24 |
| Existing-note bodies loaded | 8 unique |
| Source pages loaded | 45 unique |
| Original visual pages inspected | 6 unique |
| Agent B review instructions | 10,792 characters |
| All serialized per-change requests | 594,209 characters |
| Estimated request tokens | 148,553 across 24 calls |

The token estimate is characters divided by four and is not API usage accounting. Repeating the instructions per change is the largest context cost.

## Freeze decision

Agent B v1 should **not yet be frozen** as a reliable approval gate. It is useful as a critical, auditable second pass and catches real link, alias, and conceptual-boundary problems, but its semantic findings need human inspection. In this run it also produced vague source-fidelity objections, sometimes treated a short foundational Dot as debatable, and occasionally omitted the required promotion assessment (which the runner correctly escalated). It cannot prove that all claims in a long Lecture Note were checked merely because the relevant pages were supplied. The 0-PASS result may reflect both genuine proposal defects and excessive reviewer caution.

Remaining work before a freeze decision: calibrate semantic review on labeled good and bad notes, tighten claim-level provenance for long source notes, reduce repeated instruction context, verify alias judgments against reference cases, and evaluate a stronger reviewer model. Reconciliation, human approval, and vault writes remain separate future stages.
