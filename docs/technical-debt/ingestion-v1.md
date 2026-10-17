Second Brain Processor — Ingestion v1 / Agent A TODO
======================================================

Status
------
Ingestion v1 is considered good enough to freeze and move on to the Agent A PoC.
The items below are improvements or follow-up work, not reasons to keep polishing the PDF cleaner.

P0 — Address when implementing Agent A
--------------------------------------

1. Reduce Agent A context bloat
   - Do not send both the full University Material Processing Rules and the compact University Processing Instructions.
   - Use the compact operational instructions during normal runs.
   - Keep the long specification available only for exceptional/ambiguous cases if needed.
   - Current test artifacts show substantial duplicated prompt context.

2. Fix retrieval of "relevant existing notes"
   - Current retrieval can select unrelated notes such as GitHub/project README notes and even Agent A/B instruction files.
   - Exclude protocol/config/instruction files from knowledge-note retrieval.
   - Prefer type-aware and path-aware filtering before lexical/semantic ranking.
   - Retrieve candidate Concept Notes / Maps / Course Notes appropriate to the workflow, not arbitrary Markdown.
   - Do not pass large note bodies unless a note is genuinely relevant.
   - Retrieve metadata first; load full bodies only for the small set of candidates that need equivalence/merge evaluation.

3. Enforce document completeness in Agent A
   - COMPLETE documents may proceed normally.
   - PARTIAL documents must expose unresolved visual pages to Agent A.
   - Continuing with unresolved visuals must require the explicit override and should produce review-required/qualified output.
   - Never let PARTIAL silently behave as COMPLETE.

4. Keep text and visual provenance available to Agent A
   - Preserve page numbers.
   - Keep TEXT and VISUAL CONTENT distinguishable.
   - Ensure claims derived from visual material remain traceable to the page/image.

P1 — Useful improvements after Agent A works
--------------------------------------------

5. Make visual enrichment more concise and semantic
   - Current visual descriptions can be verbose relative to the source document.
   - Prefer semantic information missing from text extraction: entities, relations, arrows, containment, hierarchy, axes, flow, labels.
   - Avoid describing colors, positions, layout, or decorative elements unless they carry meaning.
   - Consider a structured VisualPageContent schema instead of one long prose field.
   - Consider a reasonable output/token budget per page.

6. Treat visual uncertainty explicitly
   - A successful API response is not automatically the same thing as high-confidence extraction.
   - If VisualPageContent.uncertain is true, or limitations indicate material ambiguity, surface this to Agent A / Agent B.
   - Consider distinguishing "processed" from "reliably resolved".
   - Do not necessarily block the whole document; REVIEW_REQUIRED may be enough.

7. Give Agent B access to visual evidence when needed
   - Agent B should be able to inspect the original rendered page for claims based materially on visual extraction.
   - Visual extraction can contain small interpretation errors (e.g. counts, arrow endpoints, layout relationships).
   - Source-fidelity review should not rely only on Agent A's or the visual extractor's prose.

8. Add robust multimodal API retry/backoff if not already present
   - Test artifacts contained transient APIConnectionError runs.
   - Fail closed: unresolved page => PARTIAL.
   - Add bounded retry/backoff for transient failures without hiding persistent failures.

9. Track visual-processing cost
   - Record number of visual calls, cache hits, input/output tokens where available, and estimated cost.
   - This will help tune the visual detector and per-page output budget later.

10. Keep cache invalidation reproducible
    - Cache key should depend on source/page hash, render configuration, visual model/provider, prompt/schema version.
    - A change in extraction prompt or schema should not silently reuse incompatible cached enrichment.

P2 — Deferred ingestion improvements (only if real documents justify them)
--------------------------------------------------------------------------

11. Improve detection of vector-only diagrams
    - Current visual heuristic may miss diagrams composed of many small vector shapes.
    - Do not solve pre-emptively; collect failures first.

12. Cross-block paragraph reflow
    - Some line continuations across PDF blocks remain split.
    - Current LLMs can generally understand them; defer unless it becomes a recurring extraction problem.

13. Typographic/spacing repair
    - Examples such as ligature normalization can leave cases like "staffto" instead of "staff to".
    - Avoid language-based autocorrection in the deterministic cleaner for now.
    - Revisit only if these errors materially affect retrieval or Agent A.

14. Specialized table fallback
    - Do not add AnyDoc/other per-table fallback until repeated table extraction failures are observed.
    - If added later, keep PyMuPDF as canonical provenance and reconcile the specialized output carefully.

15. OCR/scanned-document workflow
    - Add only when scanned/image-only PDFs become a real input category.
    - Keep this separate from the current born-digital PDF path.

16. More document types
    - Add source-specific adapters for PPTX/DOCX/EPUB/etc. as those inputs are introduced.
    - Keep the core ExtractedDocument contract source-agnostic.

Notes from the current visual-ingestion test
--------------------------------------------
- 53 source pages were preserved.
- 6 pages were flagged for selective visual processing.
- All 6 can be enriched successfully and the document becomes COMPLETE.
- Cache reuse was demonstrated successfully for all 6 pages.
- A deliberately unresolved page correctly leaves the document PARTIAL.
- Visual enrichment recovered meaningful information from diagrams that text extraction alone did not contain.
- Some visual descriptions are more verbose than necessary and contain minor possible interpretation inaccuracies; this is expected to be handled by concise visual schemas plus Agent B review rather than further PDF-cleaner complexity.

Decision
--------
Freeze ingestion v1.

Next main milestone:
    Agent A PoC, beginning with a lean/context-efficient retrieval and context assembly layer.
