"""Small evidence guards around semantic review output, not semantic replacement."""

from __future__ import annotations

import re

from .agent_b_context import AgentBRequest
from .models import AliasRelation, ChangeReview, IssueSeverity, IssueType, ReviewStatus, SourceReference
from .registry import normalize


_ALSO_KNOWN_AS = re.compile(r"\b(?:also known as|also called|also referred to as)\b", re.IGNORECASE)
_EXAMPLE = re.compile(r"\b(?:such as|for example|e\.g\.,?|including|like)\s+([^.;\n]+)", re.IGNORECASE)
_STOP = {"and", "or", "the", "a", "an", "of", "to", "with", "for", "is", "are", "its", "their", "by"}


def explicit_alias_pages(request: AgentBRequest, alias: str) -> list[int]:
    """Find direct identity wording that names both title and alias on a supplied page."""
    title = normalize(request.proposal_change.title)
    name = normalize(alias)
    pages = []
    for page in request.source_evidence:
        lines = page.text.splitlines()
        for index, line in enumerate(lines):
            window = " ".join(lines[index:index + 2])
            normalized = normalize(window)
            raw_pair = (re.search(re.escape(request.proposal_change.title) + r"\s*\(\s*" + re.escape(alias) + r"\s*\)", window, re.IGNORECASE)
                        or re.search(re.escape(alias) + r"\s*\(\s*" + re.escape(request.proposal_change.title) + r"\s*\)", window, re.IGNORECASE))
            if title in normalized and name in normalized and (_ALSO_KNOWN_AS.search(window) or raw_pair):
                pages.append(page.page_number)
                break
    return pages


def _unsupported_examples(correction: str, request: AgentBRequest) -> bool:
    evidence = normalize(" ".join([request.proposal_change.content,
        *(page.text + " " + page.visual_extraction for page in request.source_evidence),
        *(note.body for note in request.affected_existing_notes)]))
    terms = set(evidence.split())
    for match in _EXAMPLE.finditer(correction):
        example_terms = {word for word in normalize(match.group(1)).split() if len(word) > 3 and word not in _STOP}
        if example_terms - terms:
            return True
    return False


def constrain_corrections(request: AgentBRequest, response: ChangeReview) -> None:
    """Replace unsupported invented examples with an evidence-safe deletion proposal."""
    kept = []
    for issue in response.issues:
        if (issue.issue_type.value == "source_fidelity" and
                re.search(r"\b(?:closely follows the source|lack of originality)\b", issue.explanation, re.IGNORECASE) and
                re.search(r"\b(?:unique insights|beyond what is provided|additional context)\b", issue.proposed_correction, re.IGNORECASE)):
            continue
        if _unsupported_examples(issue.proposed_correction, request):
            if issue.issue_type.value == "source_specific_result" and re.search(
                    r"\b(?:does not provide examples|lacks examples)\b", issue.explanation, re.IGNORECASE):
                continue
            issue.proposed_correction = "Remove the unsupported wording; do not add examples absent from supplied evidence"
            issue.corrected_content = None
            if issue.issue_type.value not in {"source_fidelity", "claim_strength", "source_independent_wording"}:
                response.status = ReviewStatus.REVIEW_REQUIRED
        kept.append(issue)
    response.issues = kept


def evidence_supported_alias_relation(request: AgentBRequest, response: ChangeReview) -> None:
    """Explicit source synonymy wins over an unsupported invented subtype claim."""
    for assessment in response.alias_assessments:
        pages = explicit_alias_pages(request, assessment.alias)
        if not pages or assessment.relation == AliasRelation.IDENTITY_EQUIVALENT:
            continue
        contrary = any((ref.note_path and ref.note_path.endswith(".md")) or
                       re.search(r"\b(?:subtype|variant|broader|narrower|implementation)\b", ref.reference, re.IGNORECASE)
                       for ref in assessment.evidence_refs)
        if contrary:
            continue
        assessment.relation = AliasRelation.IDENTITY_EQUIVALENT
        assessment.status = ReviewStatus.PASS
        assessment.explanation = f"Supplied page {pages[0]} explicitly presents this as another name; no contrary evidence cited"
        assessment.proposed_correction = ""


def bind_issue_references(request: AgentBRequest, response: ChangeReview) -> None:
    """Bind directly visible structural issues; reject unsupported semantic assertions as gaps."""
    pages = {page.page_number for page in request.source_evidence}
    structural = {"link", "metadata", "workflow_contamination", "naming", "template", "provenance",
                  "source_independent_wording"}
    for issue in response.issues:
        cited = set(issue.source_pages) | {ref.page for ref in issue.evidence_refs if ref.page is not None}
        if cited - pages:
            issue.source_pages = [page for page in issue.source_pages if page in pages]
            issue.evidence_refs = [ref for ref in issue.evidence_refs if ref.page is None or ref.page in pages]
        if issue.source_pages or issue.evidence_refs:
            continue
        if issue.issue_type.value in structural:
            issue.evidence_refs = [SourceReference(note_path=request.proposal_change.target_path,
                                                    reference="Proposed note content and structure")]
            continue
        issue.issue_type = IssueType.EVIDENCE_GAP
        issue.severity = IssueSeverity.HIGH
        issue.explanation = "Agent B raised a semantic concern without citing supplied evidence: " + issue.explanation
        issue.proposed_correction = "Inspect the selected source and affected note before changing meaning"
        issue.corrected_content = None
        issue.evidence_refs = [SourceReference(note_path=request.proposal_change.target_path,
                                               reference="Uncited Agent B concern; no factual distinction accepted")]
        response.status = ReviewStatus.REVIEW_REQUIRED
