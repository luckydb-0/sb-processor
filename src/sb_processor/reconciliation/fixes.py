from __future__ import annotations

import re
from typing import Iterable

import yaml

from ..models import NoteChange, ReviewIssue
from .models import (
    FixResult,
    IssueClassification,
    IssueOutcome,
    PatchKind,
    PatchOperation,
)


_FRONTMATTER = re.compile(r"\A---\s*\r?\n(.*?)\r?\n---(?:\r?\n|\Z)", re.DOTALL)
_DIRECT_PDF_LINE = re.compile(
    r"(?im)^(?:source_file|location):[^\n]*(?:\n|$)|"
    r"^\*\*(?:Source|Location):\*\*[^\n]*(?:\.pdf\b|[/~])[^\n]*(?:\n|$)"
)
_ALIAS_REMOVAL = re.compile(r"^Remove alias (?P<quote>['\"])(?P<alias>.+?)(?P=quote) from frontmatter$")
_CANONICAL_LINK = re.compile(r"^Use \[\[(?P<target>[^\]]+)\]\]$")
_NONCANONICAL_LINK = re.compile(r"Noncanonical wikilink path: \[\[(?P<target>[^\]]+)\]\]")
_SEMANTIC_REMOVE = re.compile(
    r"^Remove (?P<quote>[\"'`])(?P<old>.+?)(?P=quote)(?: from the body)?(?: .*)?$"
)
_SEMANTIC_REPLACE = re.compile(
    r"^Replace (?P<quote>[\"'`])(?P<old>.+?)(?P=quote) with "
    r"(?P=quote)(?P<new>.+?)(?P=quote)(?: in the body)?(?: .*)?$"
)
_SEMANTIC_TYPES = {
    "source_fidelity",
    "claim_strength",
    "source_independent_wording",
    "source_specific_result",
    "cumulative_integrity",
    "existing_note",
}


def _apply_patches(content: str, patches: Iterable[PatchOperation]) -> str:
    result = content
    for patch in sorted(patches, key=lambda item: item.start, reverse=True):
        result = result[:patch.start] + patch.after + result[patch.end:]
    return result


def _result(content: str, classification: IssueClassification, outcome: IssueOutcome,
            reason: str, patches: list[PatchOperation] | None = None) -> FixResult:
    operations = patches or []
    return FixResult(
        classification=classification,
        outcome=outcome,
        content=_apply_patches(content, operations),
        patches=operations,
        reason=reason,
    )


def _frontmatter(content: str) -> dict:
    match = _FRONTMATTER.match(content)
    if match is None:
        return {}
    try:
        value = yaml.safe_load(match.group(1))
    except yaml.YAMLError:
        return {}
    return value if isinstance(value, dict) else {}


def _provenance_fix(issue: ReviewIssue, content: str) -> FixResult | None:
    if (issue.issue_type.value != "provenance"
            or issue.explanation != "Concept Note duplicates direct PDF metadata"
            or "remove direct PDF source_file/location metadata" not in issue.proposed_correction):
        return None
    patches = [
        PatchOperation(kind=PatchKind.REMOVE, start=match.start(), end=match.end(),
                       before=match.group(0), after="")
        for match in _DIRECT_PDF_LINE.finditer(content)
    ]
    if not patches:
        return _result(content, IssueClassification.OBJECTIVE, IssueOutcome.HUMAN_REQUIRED,
                       "No exact direct-PDF metadata lines were found")
    return _result(content, IssueClassification.OBJECTIVE, IssueOutcome.APPLIED,
                   "Removed exact direct-PDF metadata fields and lines", patches)


def _alias_fix(issue: ReviewIssue, content: str, existing_content: str | None) -> FixResult | None:
    if issue.issue_type.value != "alias":
        return None
    directive = _ALIAS_REMOVAL.fullmatch(issue.proposed_correction)
    if directive is None:
        return _result(content, IssueClassification.AMBIGUOUS, IssueOutcome.HUMAN_REQUIRED,
                       "Alias correction is not an exact removal directive")
    alias = directive.group("alias")
    existing_aliases = _frontmatter(existing_content or "").get("aliases", [])
    if alias in existing_aliases:
        return _result(content, IssueClassification.OBJECTIVE, IssueOutcome.HUMAN_REQUIRED,
                       "The requested alias predates Agent A and cannot be removed automatically")
    match = _FRONTMATTER.match(content)
    aliases = _frontmatter(content).get("aliases", [])
    if match is None or alias not in aliases:
        return _result(content, IssueClassification.OBJECTIVE, IssueOutcome.HUMAN_REQUIRED,
                       "The exact alias is not present in valid frontmatter")
    escaped = re.escape(alias)
    item = re.search(
        rf"(?m)^[ \t]*-[ \t]*(?:\"{escaped}\"|'{escaped}'|{escaped})[ \t]*(?:\r?\n|$)",
        content[match.start(1):match.end(1)],
    )
    if item is None:
        return _result(content, IssueClassification.OBJECTIVE, IssueOutcome.HUMAN_REQUIRED,
                       "The alias is not represented by one removable list item")
    start = match.start(1) + item.start()
    end = match.start(1) + item.end()
    if aliases == [alias]:
        header_matches = list(re.finditer(
            r"(?m)^aliases:[ \t]*(?:\r?\n|$)",
            content[match.start(1):start],
        ))
        if not header_matches:
            return _result(content, IssueClassification.OBJECTIVE, IssueOutcome.HUMAN_REQUIRED,
                           "The only alias is not under a removable aliases field")
        start = match.start(1) + header_matches[-1].start()
    patch = PatchOperation(kind=PatchKind.REMOVE, start=start, end=end,
                           before=content[start:end], after="")
    return _result(content, IssueClassification.OBJECTIVE, IssueOutcome.APPLIED,
                   "Removed an exact newly introduced alias", [patch])


def _link_fix(issue: ReviewIssue, content: str, known_targets: set[str]) -> FixResult | None:
    if issue.issue_type.value != "link":
        return None
    directive = _CANONICAL_LINK.fullmatch(issue.proposed_correction)
    source = _NONCANONICAL_LINK.search(issue.explanation)
    if directive is None or source is None:
        return _result(content, IssueClassification.AMBIGUOUS, IssueOutcome.HUMAN_REQUIRED,
                       "Link correction does not provide exact old and canonical targets")
    target = directive.group("target")
    if target not in known_targets:
        return _result(content, IssueClassification.OBJECTIVE, IssueOutcome.HUMAN_REQUIRED,
                       "The proposed canonical target does not resolve")
    old = f"[[{source.group('target')}]]"
    new = f"[[{target}]]"
    if content.count(old) != 1:
        return _result(content, IssueClassification.OBJECTIVE, IssueOutcome.HUMAN_REQUIRED,
                       "The old wikilink does not occur exactly once")
    start = content.index(old)
    patch = PatchOperation(kind=PatchKind.REPLACE, start=start, end=start + len(old), before=old, after=new)
    return _result(content, IssueClassification.OBJECTIVE, IssueOutcome.APPLIED,
                   "Replaced one verified noncanonical wikilink", [patch])


def _semantic_fix(issue: ReviewIssue, content: str) -> FixResult | None:
    if issue.issue_type.value not in _SEMANTIC_TYPES:
        return None
    removal = _SEMANTIC_REMOVE.fullmatch(issue.proposed_correction)
    replacement = _SEMANTIC_REPLACE.fullmatch(issue.proposed_correction)
    if removal is None and replacement is None:
        return _result(content, IssueClassification.AMBIGUOUS, IssueOutcome.HUMAN_REQUIRED,
                       "Semantic correction is not an exact quoted remove/replace directive")
    directive = replacement or removal
    assert directive is not None
    old = directive.group("old")
    new = directive.groupdict().get("new") or ""
    frontmatter = _FRONTMATTER.match(content)
    if frontmatter is None:
        return _result(content, IssueClassification.SEMANTIC_EXACT, IssueOutcome.HUMAN_REQUIRED,
                       "Semantic patches require a valid frontmatter boundary")
    body_start = frontmatter.end()
    body = content[body_start:]
    if body.count(old) != 1 or old == new:
        return _result(content, IssueClassification.SEMANTIC_EXACT, IssueOutcome.HUMAN_REQUIRED,
                       "The quoted semantic span must occur exactly once in the Markdown body")
    start = body_start + body.index(old)
    patch = PatchOperation(
        kind=PatchKind.REPLACE if new else PatchKind.REMOVE,
        start=start,
        end=start + len(old),
        before=old,
        after=new,
    )
    return _result(content, IssueClassification.SEMANTIC_EXACT, IssueOutcome.APPLIED,
                   "Applied one exact quoted semantic patch in the Markdown body", [patch])


def classify_and_apply_fix(change: NoteChange, issue: ReviewIssue, content: str,
                           existing_content: str | None, *,
                           known_targets: set[str] | None = None) -> FixResult:
    """Apply one allow-listed issue correction without mutating its inputs."""
    del change
    for candidate in (
        _provenance_fix(issue, content),
        _alias_fix(issue, content, existing_content),
        _link_fix(issue, content, known_targets or set()),
        _semantic_fix(issue, content),
    ):
        if candidate is not None:
            return candidate
    return _result(content, IssueClassification.AMBIGUOUS, IssueOutcome.HUMAN_REQUIRED,
                   "No allow-listed deterministic correction applies")
