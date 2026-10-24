# Agent B freeze calibration design

## Intent

Calibrate the existing Agent B v1.2 architecture into a freeze candidate by improving first-pass semantic discipline, reducing retries, resolving unsupported new aliases conservatively, and exposing review quality in `SUMMARY.md`.

## Goals

- Require positive supplied evidence for semantic `FAIL` results.
- Retry only unsupported failures that can materially affect the note outcome.
- Bound retries with configurable per-change and per-request limits.
- Convert a new unsupported alias into an evidence-bound `FIX` that removes it.
- Keep supported equivalence, supported subtype distinctions, and genuine concept ambiguity intact.
- Compare the current and stronger reviewer models on the same fresh fixture and policy.

## Non-goals

No Agent A, ingestion, retrieval, deterministic-validator, staging, global-review architecture, reconciliation, vault-write, or UI redesign.

## Approach

Use one policy object passed to the existing review runner. It ranks unsupported checks by materiality, caps categories in one retry, and terminally converts skipped unsupported failures to `INSUFFICIENT_EVIDENCE`. The evidence layer handles alias outcomes: explicit equivalence passes, positive non-equivalence fixes, and a new alias with no supplied support fixes by removing the alias. Existing naming conflicts may still require review. The compact checklist states the same evidence rule before the model responds.

This is preferred over replacing the reviewer flow or moving semantic judgments into deterministic validators because the existing architecture already contains unsupported findings safely. Calibration should improve the inputs and call policy while preserving those safety gates.

## Verification

Test first for selective retries, budgets, unsupported aliases, explicit aliases, subtypes, summary quality metrics, and model configuration. Then run the full suite. Finally run entirely fresh end-to-end evaluations for the current reviewer model and one stronger available model with identical inputs and policy, and assess the known semantic benchmark cases manually.

## Constraints

- The canonical Agent B protocol remains unchanged.
- The real vault is read-only for this milestone.
- One targeted retry is the default maximum per change.
- `INSUFFICIENT_EVIDENCE` is terminal after the retry budget.
- Model selection remains a configuration value on the existing client/CLI.

