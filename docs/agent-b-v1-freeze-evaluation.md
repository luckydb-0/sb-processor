# Agent B v1 freeze evaluation

Date: 2026-10-25  
Branch: `feat/agent-b-v1.2`  
Selected reviewer: `gpt-5.4-mini`, reasoning effort `low`

## Outcome

Agent B is ready to freeze as v1. The release-candidate run leaves only three human decisions, all of them genuine concept-boundary questions already identified by Agent A:

- Classification versus Predictive Classification;
- whether the existing Predictive Classification note should be merged, renamed, or retained separately;
- Analytics versus Business Analytics.

The remaining 19 non-passing changes are objective or conservative fixes. No reviewer-mechanism failure is exposed as a human decision.

## Controlled model comparison

Both models received the same 24-change Agent A proposal, source evidence, compact checklist, deterministic findings, retry policy, and API defaults except for the stronger model's `low` reasoning effort.

| Metric | `gpt-4o-mini` | `gpt-5.4-mini` low |
|---|---:|---:|
| Initial semantic calls | 35 | 24 |
| Targeted retries | 18 | 4 |
| Checks retried | 43 | 8 |
| Initial unsupported FAILs | 60 | 9 |
| Checks ending insufficient | 35 | 4 |
| PASS / FIX / REVIEW_REQUIRED | 1 / 13 / 10 | 2 / 19 / 3 |
| Input tokens | 1,065,118 | 161,017 |
| Output tokens | 32,974 | 49,313 |
| Reasoning tokens (included in output usage) | 0 | 15,873 |
| Total API calls | 54 | 29 |
| Runtime | 393.322 s | 303.065 s |
| Estimated token cost | USD 0.180 | USD 0.343 |

The cost estimate assumes uncached standard token rates and no regional-processing uplift. Current official rates used were USD 0.15/M input and USD 0.60/M output for [`gpt-4o-mini`](https://developers.openai.com/api/docs/models/gpt-4o-mini), and USD 0.75/M input and USD 4.50/M output for [`gpt-5.4-mini`](https://developers.openai.com/api/docs/models/gpt-5.4-mini).

The stronger reviewer costs roughly USD 0.16 more for this fixture but removes 51 unsupported first-pass failures, 14 retry calls, 11 malformed initial responses, and seven false human escalations. `gpt-4o-mini` is also currently marked deprecated in the official model catalog.

## Fresh release-candidate run

Artifact: `staging/agent_b_v1_freeze_benchmark/gpt-5.4-mini-low-freeze-release`

This run made fresh API calls for every semantic review. No semantic response was replayed.

| Metric | Result |
|---|---:|
| Changes | 24 |
| PASS | 2 |
| FIX | 19 |
| REVIEW_REQUIRED | 3 |
| Initial unsupported FAILs | 4 |
| Targeted retries | 4 |
| Checks retried | 4 |
| Retry issues recovered | 1 |
| Checks changed to PASS | 1 |
| Checks ending insufficient | 2 |
| Malformed responses | 0 |
| Semantic / retry / batch calls | 24 / 4 / 1 |
| Input / output / reasoning tokens | 167,049 / 50,944 / 17,293 |
| Estimated serialized request tokens | 136,915 |
| Runtime | 255.475 s |
| Estimated token cost | USD 0.355 |

## Semantic benchmark results

- Similarity Matching did not gain Euclidean distance, cosine similarity, or any other external example.
- Dataset was reviewed as proposed final content. Agent B did not repeat the stale-note complaint that the broader data-form and transformation explanation was missing. It did identify a separate cumulative-integrity concern about the older train/evaluate purpose sentence.
- Profiling / Behavior Description passed with direct `also known as` evidence.
- Regression / Value Estimation passed with direct `regression (value estimation)` evidence.
- Data Set passed as an evidence-backed orthographic variant of Dataset.
- DDD passed because the supplied visual evidence explicitly contains `Automated DDD` under Data-Driven Decision Making. The regression test still requires an unsupported DDD alias to be removed conservatively.
- Cross-Validation / K-Fold Cross-Validation remains rejected by the subtype regression test.
- Regression and Reinforcement Learning both passed Dot promotion with foundational-identity evidence.
- Classification / Predictive Classification and Analytics / Business Analytics remain human decisions.

## Safety and structural checks

The deterministic layer ran:

- frontmatter schema;
- Lecture identifier and source metadata;
- Concept direct-PDF provenance;
- workflow contamination;
- wikilink integrity;
- canonical link paths;
- Map basename collision;
- source-dependent phrase precheck.

The Machine Learning Map is addressed only as `Atlas/Maps/Machine Learning - Map.md`; `[[Machine Learning - Map]]` is not reported as unresolved. Direct PDF provenance is grouped as one systematic issue affecting 18 Concept Notes.

Recovered retry issues retain the problem, evidence, and minimal correction, but never carry generated full-note replacement content into the actionable review.

## Preservation

The release run's `proposal.json` SHA-256 is identical to the v1.2 fixture proposal:

`4532fb1cb0ebdaaea20885a3b05559935aebe7569c97ace7d08bc9c79559036f`

The preserved original Agent A proposal SHA-256 is also identical:

`ff9271de8855c47e442781884815bb059db68c941b236352e9bbca505131c64d`

All outputs are under repository staging. The real Obsidian vault was not written.

## Verification

`.venv/bin/pytest -q`: 173 passed, 1 skipped, 7 warnings.

The skipped test is optional-dependency/platform-specific; no Agent B test was skipped.

