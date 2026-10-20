# Agent B operational checklist mapping

The canonical protocol is `gd-gdb/+ Inbox/Agent B - University Processing Review Instructions.md`. The runtime checklist is `src/sb_processor/prompts/agent_b_university_checklist.md`. Changes to the checklist should be checked against these sections.

| Structured category | Canonical sections |
| --- | --- |
| source_fidelity | 1, 15, 21 |
| claim_strength | 2, 21 |
| source_independence | 3, 21 |
| source_specific_results | 4, 15, 21 |
| provenance | 5, 15, 21 |
| metadata | 6, 18, 21 |
| duplicate_concept | 7, 21 |
| existing_note_integrity | 8, 20, 21 |
| dot_promotion | 9, 21 |
| concept_boundaries | 10, 21 |
| aliases | 11, 21 |
| links | 12, 20, 21 |
| map_structure | 13, 21 |
| course_structure | 14, 21 |
| lecture_structure | 15, 21 |
| synthesis | 16, 18, 21 |
| workflow_contamination | 14, 17, 21 |
| naming | 19, 21 |
| cumulative_integrity | 20, 21 |

The global pass applies sections 7, 9–14, 19–20 across the batch. Objective checks run in Python. Semantic judgments and evidence sufficiency remain with Agent B.
