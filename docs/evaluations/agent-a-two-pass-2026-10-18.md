# Agent A two-pass PoC evaluation — 2026-10-18

## Scope and fixture

This evaluation used the existing Machine Learning introduction PDF and a copy of the previous 13-note PoC fixture. The copy adds one `Atlas/Dots/Dataset.md` note without an alias, making the `Data Set` → `Dataset` lexical variant observable. The controlled fixture contains 14 Markdown files. The real Obsidian vault was not passed to `process`; all outputs are in staging.

Final staged run: `staging/two_pass_fixture_runs/run_20261018T161230Z_ef760c87/`.

The full staged artifact contains `source_analysis.json`, `discovery_selection.json`, both request contexts and diagnostics, `retrieval_evidence.json`, `semantic_diagnostics.json`, `proposal.json`, `wikilinks.json`, proposed Markdown, and `review.md`.

## Retrieval and model

Local embeddings use `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` through FastEmbed ONNX, with persistent Qdrant local mode. This 384-dimensional, approximately 220 MB model supports cross-language similarity for English, Italian, and Spanish at a modest PoC size. The vector index contains six policy-approved `Atlas/Dots/` notes; the SQLite registry contains all 14 fixture Markdown files. The first sync embedded six notes. The final sync embedded zero, reused six, updated zero, and deleted zero, taking 0.002 seconds. Unit tests additionally verify changed-note re-embedding and deleted-note removal.

The initial threshold is 0.50. In the small fixture, exact topic queries scored approximately 0.66–0.78 and most unrelated notes were below 0.48. An Italian Dataset paraphrase scored about 0.54 and a Spanish one about 0.60 against a synthetic Dataset note. This is a candidate-generation cutoff, not an equivalence probability; the distribution needs wider evaluation on a larger vault.

The final run issued 51 local semantic queries. Exact title, filename, alias, normalized spelling, and lexical retrieval remain deterministic and rank before semantic-only hits. A semantic score never triggers CREATE or UPDATE in application code.

## Pass 1

Pass 1 produced 20 selected concepts, including Machine Learning, Data Mining, Classification, Data Set, Clustering, and Data Science. It also named a Lecture Note and Course Note. No concept body was in its request. The processed source retained numbered pages, separate text/visual channels, and `COMPLETE` status with visual pages 13, 14, 18, 19, 31, and 48 all processed. The final run needed no deterministic definition supplement and omitted no candidate due to the cap.

Pass 1 request: 34,795 characters, approximately 8,699 tokens by the repository's characters/4 estimate. Source evidence: 23,993 characters; operational instructions and workflow prompt: 8,377 characters; existing-note bodies: zero.

## Candidate-specific evidence

| Candidate | Selected existing note(s) and evidence | Full body in Pass 2 |
| --- | --- | --- |
| Machine Learning | Machine Learning: exact title + semantic 0.757 | Yes |
| Data Mining | Data Mining: exact title + semantic 0.706; Dataset: semantic 0.630 | Both |
| Discovery Process | Data Mining: lexical | Yes |
| Classification | Predictive Classification: alias + semantic 0.664 | Yes |
| Regression | None | — |
| Clustering | Clustering: exact title + semantic 0.779; Data Mining: semantic 0.536 | Both |
| Supervised Learning | Data Mining, Machine Learning: lexical | Both |
| Unsupervised Learning | Data Mining, Machine Learning: lexical | Both |
| Reinforcement Learning | Machine Learning: lexical | Yes |
| Data Set | Dataset: exact title through an observed term + semantic 0.743; Data Mining: lexical + semantic 0.512 | Both |
| Data-Driven Decision Making | None | — |
| Similarity Matching | Clustering: semantic 0.526 | Yes |
| Co-occurrence Grouping | Clustering: semantic 0.662; Data Mining: semantic 0.551 | Both |
| Profiling | None | — |
| Link Analysis and Prediction | None | — |
| Data Reduction | Data Mining: lexical | Yes |
| Causal Modeling | None | — |
| Business Intelligence | Business Analytics: lexical + semantic 0.612 | Yes |
| Analytics | Business Analytics: alias + semantic 0.567 | Yes |
| Data Science | Data Mining: lexical + semantic 0.520; Dataset: semantic 0.533 | Both |

The Map candidate `Machine Learning - Map` retrieved the existing `Atlas/Maps/Machine Learning.md` by canonical name; the course context retrieved the existing Course Note. The eight unique full bodies sent to Pass 2 were Machine Learning, Data Mining, Dataset, Predictive Classification, Clustering, Business Analytics, the Machine Learning Map, and the Machine Learning Course Note. All 51 queries and their scores, including results below threshold, are in `retrieval_evidence.json`. Raw score observations are intentionally absent from the LLM request.

Pass 2 request: 64,677 characters, approximately 16,170 tokens. Source evidence: 23,993; workflow instructions/prompt: 8,946; templates: 3,092; existing bodies: 5,111; candidate metadata: 11,386. There were 131 per-candidate metadata evaluations, eight unique selected notes, and eight loaded bodies. The fixed system message is not included in these request-payload estimates.

The excluded paths were `README.md`, `prompts/Agent A.md`, `config/Machine Learning.md`, and the three `+ Inbox` instructions/template files. None entered the Pass 2 candidate context. The long historical university rules were not included.

## Final proposal and comparison

The validated final proposal has 15 CREATE, six UPDATE, and three REVIEW_REQUIRED changes. Key actions:

- CREATE the Lecture Note and UPDATE the Course Note.
- UPDATE Machine Learning and Data Mining using their complete existing bodies.
- UPDATE Dataset after the Data Set candidate retrieved it specifically.
- REVIEW_REQUIRED for the broader Classification versus narrower Predictive Classification boundary, and for Business Analytics normalization.
- UPDATE the existing Machine Learning Map at its current path; CREATE a Data Mining Map.

The previous single-pass/global-retrieval replay had `Data Mining.md` in metadata but did not load its body, so it returned REVIEW_REQUIRED for Data Mining. Repeating the old global retrieval on the augmented 14-note fixture still leaves both Data Mining and Dataset bodies unloaded after the four-concept body limit. The two-pass run loaded both and proposed UPDATE. The old replay proposed CREATE for Data Set because that fixture did not yet contain Dataset; this part of the comparison is therefore a controlled scenario change, not an isolated algorithm A/B result. The old replay already kept Predictive Classification under review; the final run preserves that caution.

The final run's Concept Note drafts contained zero occurrences of the monitored phrases “In this lecture,” “The lecture introduces,” and “The source presents.” This wording check remains a priority for Agent B because earlier runs did show occurrences. Wikilink audit classified 69 references to existing notes, 117 to notes created in the same proposal, and 20 unresolved/ghost links. In particular, `[[Machine Learning - Map]]` may not resolve to the existing `Machine Learning.md` map path. The audit reports these links without blocking staging.

The controlled fixture's 14-file SHA-256 manifest was `315a1ced5673c71786d1554fa690f415c6c6bdea0404d799be3f5a992d3b013a` before and after processing. The real vault was not used as the `--vault` argument, and no vault-write operation exists in this pipeline.

## Verification and assessment

`SB_RUN_LOCAL_MODEL_TEST=1 .venv/bin/pytest -q` passed: 95 tests. This includes fake-LLM two-pass orchestration, exact/alias/variant ranking, wrong-type exclusion, local multilingual retrieval, incremental vector synchronization, partial-document propagation, safe staging, and optional-dependency import behavior.

**Assessment:** Freeze the Agent A v1 *orchestration and retrieval architecture* and move to Agent B. The main observed failure of global retrieval is resolved, and conceptual ambiguity remains staged for review. Do not treat staged Markdown as approved vault content. Remaining weaknesses are the small threshold sample, discovery/model variability across repeated runs, survey-depth overproduction of new Concept Notes, and 20 unresolved wikilinks. Those are concrete high-priority Agent B checks; no Agent B implementation is included here.
