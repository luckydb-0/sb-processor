# Docling PDF extraction benchmark

Tested 2026-10-18 with Docling 2.140.0 on `machineLearning-01-intro.pdf` (53 lecture slides). The comparison used the repository's current cleaner and the same page-aware model for every extractor. Timings are one local run on this machine; they include model setup and are not general throughput claims. No LLM or visual API was called.

| Extractor | Extraction time | Raw chars / words | Clean chars / words | Markdown headings | Markdown table lines | Native tables / pictures | Positioned blocks |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| PyMuPDF | 0.65 s | 23,394 / 3,749 | 16,765 / 2,601 | 0 | 0 | n/a | 370 |
| AnyDoc | 0.72 s | 23,720 / 3,408 | 22,092 / 3,147 | 64 | 4 | n/a | 14 |
| PyMuPDF4LLM | 10.18 s | 26,895 / 3,806 | 19,003 / 2,838 | 30 | 0 | n/a | 554 |
| Docling | 38.57 s | 19,739 / 3,126 | 17,489 / 2,817 | 62 | 43 | 0 / 64 | 274 |

All four represented all 53 source pages. Each Docling page retained its original number, positioned text items, and PyMuPDF visual-coverage features. The 64 Docling `picture` items include small recurring slide graphics; the count does **not** mean 64 visually meaningful diagrams. The 43 Markdown table lines came chiefly from repeated agenda/index slides, which Docling represented as `document_index` items. This lecture did not exercise native table recognition on a real content table.

## Representative inspection

- Page 2, agenda: Docling formed a readable two-column Markdown table and the existing cleaner suppressed later repeated agenda pages. PyMuPDF preserved the words but not their table layout. Docling's native label was `document_index`, not `table`.
- Page 7, text and bullets: Docling made a concise heading and bullet list, omitting recurring footer material. PyMuPDF retained the original line and slide structure, which its cleaner later handled. AnyDoc joined several bullet entries into a single paragraph.
- Pages 13 and 18, diagrams: Docling exported only headings; picture objects and bounding boxes were available, but the diagram relationships were absent from text. The visual gate flagged both pages, as it did with the other extractors.
- Page 22, formalized rules: Docling wrapped the rules in a code fence but flattened line breaks and conditional structure. Raw PyMuPDF preserved the separate conditions and conclusion lines better. PyMuPDF4LLM had a malformed, space-free second rule on this slide.
- Page 25, long source quotation: Docling produced a readable paragraph and retained the citation and source text. PyMuPDF carried visual line wraps into raw extraction.
- Page 44, software list: Docling flattened three named tool descriptions into one code block. PyMuPDF4LLM kept separate list entries here. This is a concrete Docling reading-order/structure limitation for this source.
- Page 53, bibliography: Docling preserved the citation as a list item and dropped the recurring footer. The publisher name remained on a separate paragraph.

A separate small PDF with a drawn four-row, three-column grid was classified as one native `table` item and exported with correct headers and values. With `generate_picture_images=True` for slide 13, Docling returned a 203×172 pixel crop for the diagram and a 129×8 pixel crop for a small slide graphic. This demonstrates image-crop support, but the local conversion did not interpret the diagram's relationships. The production adapter deliberately leaves picture raster generation and picture description off; the existing selective visual processor remains responsible for unresolved visual meaning.

## Pipeline compatibility and recommendation

The `ingest-pdf --pdf-extractor docling --skip-visual` run produced a 53-page structured document with `PARTIAL` completeness and unresolved pages `[13, 14, 18, 19, 31, 48]`. Its Agent A representation retained page markers and explicit `VISUAL CONTENT: UNRESOLVED` labels. No visual API calls occurred. A partial Docling conversion is rejected instead of being presented as complete.

Keep **PyMuPDF as the default**: on this PDF it is much faster, has the lightest dependency footprint, preserves the rule/list structure better on important slides, and already works with the cleaner and visual gate. Keep Docling as an opt-in extractor when a source has difficult tables or stronger structural Markdown is useful. Native table detection on the synthetic probe is promising, but this lecture offers no real table to validate it; compare on more documents before changing the default. Docling picture items and crops should not be mistaken for visual understanding. No automatic per-page fallback is warranted from this sample.

The full raw/clean Markdown, structured JSON, cleaning decisions, and metrics are in the ignored local `output/extraction_comparison/` run directory. They are intentionally not committed because they reproduce substantial lecture content.
