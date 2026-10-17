import json

import pymupdf

from sb_processor.ingestion import ingest_pdf, stage_ingestion


def test_ingestion_artifacts_keep_raw_clean_visual_and_completeness(tmp_path):
    source = tmp_path / "lecture.pdf"
    pdf = pymupdf.open()
    pdf.new_page().insert_text((72, 72), "First lecture")
    pdf.save(source)
    pdf.close()
    document, stats = ingest_pdf(source, visual_extractor=None, cache_dir=tmp_path / "cache")
    run = stage_ingestion(document, stats, tmp_path / "stage")
    assert "[Page 1]" in (run / "text_raw.md").read_text()
    assert "[Page 1]" in (run / "text_clean.md").read_text()
    assert "TEXT:" in (run / "agent_context.md").read_text()
    assert json.loads((run / "document.json").read_text())["pages"][0]["page_number"] == 1
    assert json.loads((run / "summary.json").read_text())["completeness"]["status"] == "COMPLETE"
