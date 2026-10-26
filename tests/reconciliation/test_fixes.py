from __future__ import annotations

from sb_processor.models import NoteChange, ReviewIssue
from sb_processor.reconciliation.fixes import classify_and_apply_fix
from sb_processor.reconciliation.models import IssueClassification, IssueOutcome, PatchKind


def note_change(content: str, *, action: str = "CREATE", path: str = "Dots/Topic.md",
                note_type: str = "concept") -> NoteChange:
    return NoteChange(
        action=action,
        note_type=note_type,
        title="Topic",
        target_path=path,
        reason="fixture",
        content=content,
        sources=["lecture.pdf"],
        candidate_existing_notes=[],
        original_content_hash=None,
    )


def issue(kind: str, correction: str, *, explanation: str = "Needs correction") -> ReviewIssue:
    return ReviewIssue(
        change_path="Dots/Topic.md",
        issue_type=kind,
        severity="medium",
        explanation=explanation,
        proposed_correction=correction,
    )


def test_objective_provenance_removes_direct_pdf_lines_but_keeps_lecture_and_pages():
    content = (
        "---\ntype: concept\nsource_file: lecture.pdf\nlocation: /private/lecture.pdf\n---\n"
        "# Topic\n\n## Sources\n\n### [[Lecture 01]]\n\n"
        "**Source:** `lecture.pdf`  \n**Location:** /private/lecture.pdf  \n**Pages/slides:** 3-4\n"
    )
    finding = issue(
        "provenance",
        "Keep the Lecture Note wikilink and page reference; remove direct PDF source_file/location metadata",
        explanation="Concept Note duplicates direct PDF metadata",
    )

    result = classify_and_apply_fix(note_change(content), finding, content, None)

    assert result.classification is IssueClassification.OBJECTIVE
    assert result.outcome is IssueOutcome.APPLIED
    assert "source_file:" not in result.content
    assert "location:" not in result.content.casefold()
    assert "[[Lecture 01]]" in result.content
    assert "**Pages/slides:** 3-4" in result.content
    assert len(result.patches) == 4


def test_direct_pdf_provenance_fix_is_restricted_to_concept_notes():
    content = "---\ntype: lecture\nsource_file: lecture.pdf\n---\n# Lecture\n"
    finding = issue(
        "provenance",
        "Keep the Lecture Note wikilink and page reference; remove direct PDF source_file/location metadata",
        explanation="Concept Note duplicates direct PDF metadata",
    )

    result = classify_and_apply_fix(
        note_change(content, note_type="lecture"), finding, content, None
    )

    assert result.outcome is IssueOutcome.HUMAN_REQUIRED
    assert result.content == content


def test_objective_workflow_contamination_removes_one_exact_body_literal():
    content = (
        "---\ntype: concept\n---\n# Topic\n"
        "Agent A created this in the current batch. Durable explanation.\n"
    )
    finding = issue(
        "workflow_contamination",
        'Remove "Agent A created this in the current batch." from the body',
        explanation="Permanent note contains processing text",
    )

    result = classify_and_apply_fix(note_change(content), finding, content, None)

    assert result.classification is IssueClassification.OBJECTIVE
    assert result.outcome is IssueOutcome.APPLIED
    assert "Agent A created" not in result.content
    assert "Durable explanation." in result.content


def test_objective_frontmatter_repair_sets_one_schema_valid_exact_field():
    content = "---\ntype: map\naliases: []\n---\n# Topic\nBody.\n"
    finding = issue(
        "metadata",
        'Set frontmatter field "type" to "concept"',
        explanation="Frontmatter type differs from proposed note type",
    )

    result = classify_and_apply_fix(note_change(content), finding, content, None)

    assert result.classification is IssueClassification.OBJECTIVE
    assert result.outcome is IssueOutcome.APPLIED
    assert "type: concept" in result.content
    assert "type: map" not in result.content


def test_frontmatter_repair_refuses_type_that_disagrees_with_change_schema():
    content = "---\ntype: map\n---\n# Topic\nBody.\n"
    finding = issue("metadata", 'Set frontmatter field "type" to "map"')

    result = classify_and_apply_fix(note_change(content), finding, content, None)

    assert result.outcome is IssueOutcome.HUMAN_REQUIRED
    assert result.content == content


def test_objective_alias_removes_exact_new_alias():
    content = "---\ntype: concept\naliases:\n  - Existing\n  - New Alias\n---\n# Topic\n"
    existing = "---\ntype: concept\naliases:\n  - Existing\n---\n# Topic\nOld body\n"
    finding = issue("alias", "Remove alias 'New Alias' from frontmatter")

    result = classify_and_apply_fix(note_change(content, action="UPDATE"), finding, content, existing)

    assert result.outcome is IssueOutcome.APPLIED
    assert "New Alias" not in result.content
    assert "Existing" in result.content
    assert result.patches[0].kind is PatchKind.REMOVE


def test_objective_alias_refuses_to_remove_preexisting_alias():
    content = "---\ntype: concept\naliases:\n  - Existing\n---\n# Topic\nNew body\n"
    existing = "---\ntype: concept\naliases:\n  - Existing\n---\n# Topic\nOld body\n"
    finding = issue("alias", "Remove alias 'Existing' from frontmatter")

    result = classify_and_apply_fix(note_change(content, action="UPDATE"), finding, content, existing)

    assert result.outcome is IssueOutcome.HUMAN_REQUIRED
    assert result.content == content
    assert result.patches == []


def test_objective_alias_removal_does_not_leave_null_aliases_field():
    content = "---\ntype: concept\naliases:\n  - Only Alias\nmaps: []\n---\n# Topic\n"
    finding = issue("alias", "Remove alias 'Only Alias' from frontmatter")

    result = classify_and_apply_fix(note_change(content), finding, content, None)

    assert result.outcome is IssueOutcome.APPLIED
    assert "aliases:" not in result.content
    assert "maps: []" in result.content


def test_objective_link_replaces_explicit_resolved_canonical_target():
    content = "---\ntype: concept\n---\n# Topic\nSee [[Statistics]].\n"
    finding = issue(
        "link",
        "Use [[Atlas/Dots/Statistics]]",
        explanation="Noncanonical wikilink path: [[Statistics]]",
    )

    result = classify_and_apply_fix(
        note_change(content), finding, content, None, known_targets={"Atlas/Dots/Statistics"}
    )

    assert result.outcome is IssueOutcome.APPLIED
    assert "[[Atlas/Dots/Statistics]]" in result.content
    assert result.patches[0].before == "[[Statistics]]"


def test_objective_link_refuses_generic_or_unverified_advice():
    content = "---\ntype: concept\n---\n# Topic\nSee [[Statistics]].\n"
    generic = issue("link", "Use a verified canonical target or remove the link",
                    explanation="Unresolved wikilink: [[Statistics]]")
    explicit = issue("link", "Use [[Atlas/Dots/Statistics]]",
                     explanation="Noncanonical wikilink path: [[Statistics]]")

    generic_result = classify_and_apply_fix(note_change(content), generic, content, None,
                                            known_targets={"Atlas/Dots/Statistics"})
    unverified_result = classify_and_apply_fix(note_change(content), explicit, content, None,
                                               known_targets=set())

    assert generic_result.outcome is IssueOutcome.HUMAN_REQUIRED
    assert unverified_result.outcome is IssueOutcome.HUMAN_REQUIRED
    assert generic_result.content == unverified_result.content == content


def test_semantic_exact_removal_changes_only_the_quoted_body_span():
    content = (
        "---\ntype: concept\n---\n# Regression\n\n"
        "Regression is a task family in machine learning and data mining.\n\n"
        "## Definition\n\nEstimate a numeric value.\n"
    )
    finding = issue("source_fidelity", 'Remove "and data mining" from the body unless evidence is added')

    result = classify_and_apply_fix(note_change(content), finding, content, None)

    assert result.classification is IssueClassification.SEMANTIC_EXACT
    assert result.outcome is IssueOutcome.APPLIED
    assert result.content == content.replace("and data mining", "")
    assert result.patches == [result.patches[0]]
    assert result.patches[0].before == "and data mining"
    assert result.patches[0].after == ""


def test_semantic_exact_replacement_uses_both_explicit_literals():
    content = "---\ntype: concept\n---\n# Topic\nA broader claim appears here.\n"
    finding = issue("claim_strength", 'Replace "broader claim" with "supported claim" in the body')

    result = classify_and_apply_fix(note_change(content), finding, content, None)

    assert result.outcome is IssueOutcome.APPLIED
    assert "A supported claim appears here." in result.content
    assert result.patches[0].kind is PatchKind.REPLACE


def test_semantic_scope_counts_occurrences_only_in_markdown_body():
    content = (
        "---\ntype: concept\ndescription: and data mining\n---\n"
        "# Topic\nMachine learning and data mining.\n"
    )
    finding = issue("source_fidelity", 'Remove "and data mining" from the body')

    result = classify_and_apply_fix(note_change(content), finding, content, None)

    assert result.outcome is IssueOutcome.APPLIED
    assert "description: and data mining" in result.content
    assert "Machine learning ." in result.content


def test_semantic_removal_refuses_zero_or_multiple_body_occurrences():
    missing = "---\ntype: concept\n---\n# Topic\nNo target.\n"
    repeated = "---\ntype: concept\n---\n# Topic\nand data mining; and data mining.\n"
    finding = issue("source_fidelity", 'Remove "and data mining" from the body')

    missing_result = classify_and_apply_fix(note_change(missing), finding, missing, None)
    repeated_result = classify_and_apply_fix(note_change(repeated), finding, repeated, None)

    assert missing_result.outcome is IssueOutcome.HUMAN_REQUIRED
    assert repeated_result.outcome is IssueOutcome.HUMAN_REQUIRED
    assert missing_result.content == missing
    assert repeated_result.content == repeated


def test_semantic_parser_refuses_mixed_delimiters_and_nonliteral_advice():
    content = "---\ntype: concept\n---\n# Topic\nAn unsupported claim.\n"
    mixed = issue("source_fidelity", 'Replace "unsupported claim\' with "supported claim"')
    optional = issue("source_fidelity", 'Remove or soften "unsupported claim"')
    trailing_optional = issue(
        "source_fidelity", 'Remove "unsupported claim" from the body or soften it'
    )
    trailing_replacement = issue(
        "source_fidelity",
        'Replace "unsupported claim" with "supported claim" or "qualified claim"',
    )
    broad = issue("source_fidelity", "Align the paragraph with the lecture wording")

    results = [classify_and_apply_fix(note_change(content), item, content, None)
               for item in (mixed, optional, trailing_optional, trailing_replacement, broad)]

    assert all(result.classification is IssueClassification.AMBIGUOUS for result in results)
    assert all(result.outcome is IssueOutcome.HUMAN_REQUIRED for result in results)
    assert all(result.content == content for result in results)
