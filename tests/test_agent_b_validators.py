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
