from sb_processor.agent_b_validators import validate_change
from sb_processor.models import Action, NoteChange, NoteMetadata, ReviewStatus


def change(content: str, note_type: str = "concept") -> NoteChange:
    return NoteChange(action=Action.CREATE, note_type=note_type, title="A", target_path="Dots/A.md",
                      reason="fixture", content=content, sources=[], candidate_existing_notes=[],
                      original_content_hash=None)


def test_valid_existing_and_same_batch_links_pass():
    notes = [NoteMetadata(path="Dots/B.md", filename="B.md", title="B", note_type="concept",
                          aliases=[], maps=[])]
    another = change("---\ntype: concept\n---\n# C")
    another.title, another.target_path = "C", "Dots/C.md"
    issues = validate_change(change("---\ntype: concept\n---\n# A\n[[B]] [[C]]"), notes, [another])
    assert issues == []


def test_ghost_link_invalid_metadata_and_contamination_are_fixable():
    issues = validate_change(change("---\ntype: lecture\naliases: [A]\n---\n# A\n[[Ghost]]\nThis batch"), [], [])
    assert {item.issue_type for item in issues} == {"metadata", "link", "workflow_contamination"}
    assert all(item.change_path == "Dots/A.md" for item in issues)


def test_missing_or_invalid_frontmatter_is_caught():
    issues = validate_change(change("# A"), [], [])
    assert any(item.issue_type == "metadata" for item in issues)


def test_noncanonical_explicit_path_is_caught():
    notes = [NoteMetadata(path="Atlas/Dots/B.md", filename="B.md", title="B", note_type="concept",
                          aliases=[], maps=[])]
    issues = validate_change(change("---\ntype: concept\n---\n# A\n[[Dots/B]]"), notes, [])
    assert any(item.issue_type == "link" for item in issues)


def test_review_required_without_draft_has_no_frontmatter_error():
    item = change("")
    item.action = Action.REVIEW_REQUIRED
    assert validate_change(item, [], []) == []


def test_ordinary_create_verb_is_not_workflow_contamination():
    assert validate_change(change("---\ntype: concept\n---\n# A\nThese steps create a model."), [], []) == []


def test_lecture_required_metadata_when_source_is_known():
    item = change("---\ntype: lecture\n---\n# A", note_type="lecture")
    issues = validate_change(item, [], [], source_metadata={"filename": "s.pdf", "path": "/s.pdf"})
    assert sum(issue.issue_type == "metadata" for issue in issues) == 7


def test_concept_direct_pdf_provenance_is_objective_fix():
    item = change('---\ntype: concept\nsource_file: lecture.pdf\nlocation: /source/lecture.pdf\n---\n# A\n## Sources\n### [[Lecture 01]]\n**Source:** `lecture.pdf`\n**Location:** `/source/lecture.pdf`')
    issues = validate_change(item, [], [])
    assert any(issue.issue_type == "provenance" for issue in issues)
    assert all("Lecture" in issue.proposed_correction for issue in issues if issue.issue_type == "provenance")


def test_source_dependent_phrase_is_flagged_for_semantic_review():
    for phrase in ("The lecture introduces A.", "In the lecture framing, A is defined."):
        issues = validate_change(change("---\ntype: concept\n---\n# A\n" + phrase), [], [])
        assert any(issue.issue_type == "source_independent_wording" for issue in issues)


def test_map_filename_collision_is_flagged_without_compatibility_mapping():
    item = change("---\ntype: map\n---\n# Machine Learning", "map")
    item.title, item.target_path = "Machine Learning", "Atlas/Maps/Machine Learning.md"
    notes = [NoteMetadata(path="Atlas/Dots/Machine Learning.md", filename="Machine Learning.md",
                          title="Machine Learning", note_type="concept", aliases=[], maps=[])]
    issues = validate_change(item, notes, [])
    assert any(issue.issue_type == "naming" and "Machine Learning - Map.md" in issue.proposed_correction for issue in issues)


def test_concept_disallows_lecture_only_frontmatter():
    issues = validate_change(change("---\ntype: concept\nlecture: 01\ncourse: ML\n---\n# A"), [], [])
    assert any(issue.issue_type == "metadata" and "lecture" in issue.explanation for issue in issues)


def test_map_disallows_source_specific_frontmatter():
    item = change("---\ntype: map\nsource_file: s.pdf\nlocation: /s.pdf\n---\n# A", "map")
    issues = validate_change(item, [], [])
    assert sum(issue.issue_type == "metadata" for issue in issues) == 2
