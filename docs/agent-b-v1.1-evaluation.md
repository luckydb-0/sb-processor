# Agent B v1.1 evaluation — 2026-10-20

## Run and comparison

The live per-note reviewer (`gpt-4o-mini`, Structured Outputs) reviewed the unchanged 24-change Agent A proposal from `staging/two_pass_fixture_runs/run_20261018T161230Z_ef760c87/`. The final global call was live; completed per-note responses were reused while objective post-review gates were refined. The final staged result is `staging/agent_b_v11_replays/run_20261020_v11_release/`. Its `proposal.json` SHA-256 is `ff9271de8855c47e442781884815bb059db68c941b236352e9bbca505131c64d`, byte-identical to the original. The matching historical fixture snapshot lives under `staging/agent_b_v11_original_vault_snapshot/`; the active two-pass fixture has the corrected `Machine Learning - Map.md` name. No real `gd-gdb` vault note was written.

| Status | Agent B v1 | Agent B v1.1 |
| --- | ---: | ---: |
| PASS | 0 | 0 |
| FIX | 11 | 9 |
| REVIEW_REQUIRED | 13 | 15 |

The counts are not a quality score. New objective provenance detection correctly flags 18 Concept Notes that duplicate direct PDF metadata. The old `[[Machine Learning - Map]]` mismatch appears in 14 notes because the exact old proposal and its matching historical snapshot were used for the comparison. The active fixture Map was renamed, SQLite rebuilt (14 notes), Qdrant synced (six Concept vectors reused), and a canonical link lookup verified. Future proposals from that fixture use the corrected path.

## What changed

- The canonical review protocol remains `../gd-gdb/+ Inbox/Agent B - University Processing Review Instructions.md`. The 2,814-character operational checklist lives in `src/sb_processor/prompts/agent_b_university_checklist.md`; `docs/agent_b_protocol_mapping.md` maps every check to the full protocol.
- Each note returns all required checks. Missing categories fail validation; source, claim strength, provenance, duplicate/equivalence, Dot promotion, boundaries, aliases, and cumulative integrity cannot be silently omitted for Concept Notes.
- Deterministic checks cover frontmatter field types and required Lecture fields, Concept/Map field restrictions, direct PDF provenance in Concept Notes, workflow contamination, wikilink resolution and canonical paths, Map basename collisions, and source-dependent phrase prechecks. The phrase detector is a hint for semantic review, not an automatic rejection.
- Semantic corrections are constrained to supplied source/existing-note evidence. The Similarity Matching regression prevents adding unsourced Euclidean or cosine examples. The final `review.json` contains neither term. Its remaining Dot-promotion objection still requires human inspection.
- Explicit `regression (value estimation)` and `profiling / also known as behavior description` source wording supports those aliases. Regression and Profiling moved from `REVIEW_REQUIRED` in v1 to `FIX` for objective provenance/link cleanup. A cited K-Fold subtype remains distinct from Cross-Validation in regression tests.
- Regression and Reinforcement Learning pass the mandatory Dot-promotion check; Reinforcement Learning still has an unrelated uncited model concern, so its overall status remains `REVIEW_REQUIRED`. A positive foundational identity satisfies the protocol even when the note is short.
- A single global call inspects compact per-note summaries. Unsupported model suggestions are preserved in raw response/debug data and rejected from the actionable result. Objective global groups retain the 18-note provenance pattern and repeated link problems. The human `SUMMARY.md` shows each root issue once and separates conceptual decisions from reviewer evidence gaps.

## Evidence and context

Concept evidence selection prioritizes explicit page/slide citations, then Agent A Pass 1 provenance, then title occurrence fallback. The Lecture Note receives its cited page ranges. The replay loaded 45 unique cleaned source pages and eight affected existing-note bodies, without sending the vault wholesale. Original rendered PDF pages 13, 14, 18, 19, 31, and 48 were supplied to reviews of visually enriched claims; the Machine Learning Concept request includes original page images for pages 31 and 48. The final global request contained summaries and issue references, with no full PDF text or images.

| Context measure | v1 | v1.1 |
| --- | ---: | ---: |
| Per-note instruction characters | 10,792 | 2,814 (73.9% less) |
| Serialized Agent B input characters | 594,209 | 442,885 (25.5% less, including 35,523-character batch request) |
| Estimated input tokens (characters ÷ 4) | 148,553 | 110,722 |

## Remaining weaknesses and freeze decision

**Do not freeze Agent B v1.1 yet.** The structured contract and objective checks improved, but the live model still returned 15 `REVIEW_REQUIRED` changes, including uncited semantic concerns and debatable Dot-promotion objections. Its global call proposed four cross-note claims without enough per-note support; the gate rejected them. The mandatory checklist proves categories were considered, but it does not prove that every source claim in a long Lecture Note was verified. A stronger or calibrated reviewer, claim-level evidence checks, and review-response consistency checks are still needed. Reconciliation, human approval, and safe vault writes remain future work.
