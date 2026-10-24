from sb_processor.models import Action, DraftChange, NoteMetadata
from sb_processor.processing.staging import audit_wikilinks


def test_wikilink_audit_classifies_existing_created_and_ghost():
    changes = [DraftChange(action=Action.CREATE, note_type="concept", title="New Topic",
                           target_path="Dots/New Topic.md", reason="fixture", sources=[],
                           content="# New Topic\n[[Dataset]] [[New Topic]] [[Ghost Concept|Ghost]]")]
    metadata = [NoteMetadata(path="Dots/Dataset.md", filename="Dataset.md", title="Dataset",
                             note_type="concept", aliases=["Data Set"], maps=[])]
    result = audit_wikilinks(changes, metadata)
    assert [(item["target"], item["status"]) for item in result] == [
        ("Dataset", "existing note"), ("New Topic", "created in same proposal"),
        ("Ghost Concept", "unresolved / ghost link")]
