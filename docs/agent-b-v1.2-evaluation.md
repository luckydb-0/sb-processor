# Agent B v1.2 evaluation — 2026-10-24

## Scope and replay

Branch: `feat/agent-b-v1.2`. The refactored review engine remains in
`src/sb_processor/review/`; the university adapter selects evidence and the
compact checklist remains in `src/sb_processor/prompts/`. The canonical full
protocol in the `gd-gdb` vault was read and not edited.

The verified output is `staging/agent_b_v12_replays/run_20261024_v12_verified/`.
It reviews the same 24-change Agent A proposal used for v1.1. The untouched
original is `agent_a/original_proposal.json` (SHA-256
`ff9271de8855c47e442781884815bb059db68c941b236352e9bbca505131c64d`).
The evaluation copy changes one target path, from
`Atlas/Maps/Machine Learning.md` to
`Atlas/Maps/Machine Learning - Map.md`, to match the corrected historical
fixture. Path references in the replay context received the same exact-string
normalization. No note body or source claim was changed. This is a path-only
comparison caveat, not a product compatibility rule.

The initial live per-note review used `gpt-4o-mini` Structured Outputs.
Completed responses were recorded. Four malformed first responses omitted
mandatory checks; the local replay harness repeated those individual calls
and preserved the invalid responses. After tightening the UPDATE integrity
gate, Dataset alone was reviewed live again with the revised checklist.
Other valid per-note responses and matching targeted-retry responses were
reused; the final global batch review was called live against the final
per-note results. `raw_responses/`, `previous_retry_requests/`, and
`agent_b/retries/` make this sequence auditable. This mixed live/replay method
limits conclusions about how often the model would produce the same output
on a wholly fresh run.

| Result | v1.1 | v1.2 verified |
| --- | ---: | ---: |
| PASS | 0 | 2 |
| FIX | 5 | 16 |
| REVIEW_REQUIRED | 19 | 6 |
| Actionable `evidence_gap` issues | 33 | 0 |

The counts are not a quality score. Dataset's final result is `FIX` for direct
PDF provenance and an unresolved `[[Data Preparation]]` link. It no longer
contains the stale-note omission issue. The raw Dataset model response still
incorrectly alleged that the proposed note omitted the transformation caveat;
the evidence gate and targeted retry prevented that allegation from becoming
an actionable issue. This shows that model reliability remains a concern.

The corrected Map resolves `[[Machine Learning - Map]]` in the 14-note
historical snapshot and in the rebuilt SQLite registry. The old Map basename
is absent. Qdrant contains six Concept vectors and no Map vectors, so this
Map-only filename correction required no vector re-embedding. The former
14-note ghost-link pattern is absent from the final review. Other unresolved
links, including `[[Statistics]]` and `[[Business Intelligence]]`, remain
visible as objective findings.

## Retry and context diagnostics

The retry mechanism ran 15 times for 57 failed checks. Six checks became
`PASS`; 51 became `INSUFFICIENT_EVIDENCE`; no live retry recovered a supported
issue. A unit test verifies the supported-issue branch, along with PASS,
insufficient-evidence, and no-unnecessary-retry behavior. The 6 final human
escalations have other retained issues; unsupported checklist failures alone
no longer create human decisions. The global pass grouped direct PDF metadata
across 18 Concept Notes, repeated broken links, and source-dependent wording.

| Estimated input measure | v1.1 | v1.2 verified |
| --- | ---: | ---: |
| Per-note instruction characters | 2,814 | 3,673 |
| Input tokens (serialized characters ÷ 4) | 112,230 | 182,513 |
| Of v1.2 input tokens used by retries | — | 70,581 |

Without retries, v1.2 is approximately 111,932 estimated input tokens,
roughly the same as v1.1. Retries add about 62.6% to total input versus
v1.1. The 3,673-character checklist is 66.0% shorter than the 10,792-character
canonical protocol. These are character-based estimates; image input and
actual billed usage are not measured. The replay selected 45 unique cleaned
source pages, eight affected existing-note bodies, and original visual pages
13, 14, 18, 19, 31, and 48.

## Verification and decision

`.venv/bin/python -m pytest -q`: **162 passed, 1 skipped**. Review-specific
tests cover the Dataset request target, concrete lost-content citations,
targeted retries, the canonical Map link, unsupported Similarity Matching
corrections, explicit aliases, subtype aliases, foundational Dot promotion,
mandatory categories, deterministic provenance, and global grouping.

**Do not freeze Agent B v1.2 yet.** The output is easier for a human to use,
and the three requested integration failures are addressed. However, the
`gpt-4o-mini` first pass still produced four incomplete checklists and many
unsupported failures. All 15 retries returned no supported new issue; 51
checks remained insufficient. Several alias decisions in `SUMMARY.md` are
still weakly evidenced, while the raw Dataset answer repeated a plainly
false omission claim. The next quality gate should calibrate semantic review
and retry output on fresh runs before safe reconciliation or vault writes.
No Agent A, ingestion, real vault note, or safe-write code was changed.
