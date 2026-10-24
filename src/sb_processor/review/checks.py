"""Required semantic review coverage derived from the canonical Agent B protocol."""

from ..models import ReviewCategory, ReviewCheck


COMMON = (
    ReviewCategory.SOURCE_FIDELITY, ReviewCategory.CLAIM_STRENGTH,
    ReviewCategory.PROVENANCE, ReviewCategory.LINKS,
    ReviewCategory.WORKFLOW_CONTAMINATION, ReviewCategory.NAMING,
    ReviewCategory.CUMULATIVE_INTEGRITY,
)
BY_TYPE = {
    "concept": COMMON + (
        ReviewCategory.SOURCE_INDEPENDENCE, ReviewCategory.SOURCE_SPECIFIC_RESULTS,
        ReviewCategory.DUPLICATE_CONCEPT, ReviewCategory.EXISTING_NOTE_INTEGRITY,
        ReviewCategory.DOT_PROMOTION, ReviewCategory.CONCEPT_BOUNDARIES,
        ReviewCategory.ALIASES,
    ),
    "lecture": COMMON + (
        ReviewCategory.SOURCE_SPECIFIC_RESULTS, ReviewCategory.EXISTING_NOTE_INTEGRITY,
        ReviewCategory.METADATA, ReviewCategory.LECTURE_STRUCTURE, ReviewCategory.SYNTHESIS,
    ),
    "course": COMMON + (
        ReviewCategory.EXISTING_NOTE_INTEGRITY, ReviewCategory.METADATA,
        ReviewCategory.COURSE_STRUCTURE,
    ),
    "map": COMMON + (
        ReviewCategory.DUPLICATE_CONCEPT, ReviewCategory.EXISTING_NOTE_INTEGRITY,
        ReviewCategory.METADATA, ReviewCategory.MAP_STRUCTURE,
        ReviewCategory.CONCEPT_BOUNDARIES,
    ),
}


def required_checks(note_type: str) -> list[ReviewCategory]:
    if note_type not in BY_TYPE:
        raise ValueError(f"No Agent B checklist for note type: {note_type}")
    return list(BY_TYPE[note_type])


def validate_check_coverage(checks: list[ReviewCheck], note_type: str) -> None:
    expected = set(required_checks(note_type))
    actual = [check.category for check in checks]
    if len(actual) != len(set(actual)) or set(actual) != expected:
        missing = sorted(item.value for item in expected - set(actual))
        extra = sorted(item.value for item in set(actual) - expected)
        raise ValueError(f"Invalid Agent B checklist for {note_type}: missing={missing}; extra={extra}; duplicates={len(actual) != len(set(actual))}")
