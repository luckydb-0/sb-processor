"""Objective checks that do not require semantic judgment."""

from __future__ import annotations

import re

import yaml

from .models import Action, IssueSeverity, NoteChange, NoteMetadata, ReviewIssue
from .registry import normalize
from .staging import audit_wikilinks


_FRONTMATTER = re.compile(r"\A---\s*\r?\n(.*?)\r?\n---(?:\r?\n|\Z)", re.DOTALL)
_CONTAMINATION = re.compile(
    r"\b(?:Agent A|this batch|current batch|this processing session|current processing|"
    r"available files|no note was found|remaining files have not been processed|"
    r"the three PDFs processed)\b", re.IGNORECASE)
_STATUS_MARKER = re.compile(r"\b(?:CREATE|UPDATE|NO CHANGE)\b")


def _issue(change: NoteChange, kind: str, explanation: str, correction: str,
           severity: IssueSeverity = IssueSeverity.MEDIUM) -> ReviewIssue:
    return ReviewIssue(change_path=change.target_path, issue_type=kind, severity=severity,
                       explanation=explanation, proposed_correction=correction)


def validate_change(change: NoteChange, existing: list[NoteMetadata],
                    other_changes: list[NoteChange]) -> list[ReviewIssue]:
    """Validate complete proposed Markdown; semantic ambiguity remains for Agent B."""
    if change.action == Action.NO_CHANGE or (change.action == Action.REVIEW_REQUIRED and not change.content.strip()):
        return []
    issues: list[ReviewIssue] = []
    content = change.content
    match = _FRONTMATTER.match(content)
    if match is None:
        issues.append(_issue(change, "metadata", "Missing YAML frontmatter", "Add frontmatter with a valid type"))
    else:
        try:
            metadata = yaml.safe_load(match.group(1))
        except yaml.YAMLError:
            metadata = None
        if not isinstance(metadata, dict):
            issues.append(_issue(change, "metadata", "Frontmatter is not valid YAML mapping", "Repair YAML frontmatter"))
        else:
            if metadata.get("type") != change.note_type:
                issues.append(_issue(change, "metadata", "Frontmatter type differs from proposed note type",
                                     f"Set type to {change.note_type}"))
            for key in ("aliases", "maps"):
                if key in metadata and (not isinstance(metadata[key], list)
                                        or any(not isinstance(value, str) for value in metadata[key])):
                    issues.append(_issue(change, "metadata", f"{key} must be a list of strings",
                                         f"Repair {key} frontmatter"))
            if change.note_type == "lecture":
                lecture = metadata.get("lecture")
                if lecture is not None and (not isinstance(lecture, str)
                                            or not re.fullmatch(r"\d+[a-zA-Z]?", lecture)):
                    issues.append(_issue(change, "metadata", "Lecture identifier contains a title or invalid format",
                                         "Use only the lecture identifier, e.g. 03a"))
            for key in ("course", "institution", "professor", "source_file", "location"):
                if key in metadata and metadata[key] is not None and not isinstance(metadata[key], str):
                    issues.append(_issue(change, "metadata", f"{key} must be text or blank",
                                         f"Repair {key} frontmatter"))
    body = content[match.end():] if match else content
    contamination = _CONTAMINATION.search(body) or _STATUS_MARKER.search(body)
    if contamination:
        issues.append(_issue(change, "workflow_contamination",
                             f"Permanent note contains processing text: {contamination.group(0)}",
                             "Remove the processing-state wording from the permanent note"))
    audit = audit_wikilinks([change, *other_changes], existing)
    seen_links: set[tuple[str, str]] = set()
    for link in audit:
        if link["from"] != change.target_path:
            continue
        identity = (link["target"], link["status"])
        if identity in seen_links:
            continue
        seen_links.add(identity)
        if link["status"] == "unresolved / ghost link":
            issues.append(_issue(change, "link", f"Unresolved wikilink: [[{link['target']}]]",
                                 "Use a verified canonical target or remove the link"))
        elif "/" in link["target"] and normalize(link["target"].removesuffix(".md")) != normalize(link["resolved_path"].removesuffix(".md")):
            issues.append(_issue(change, "link", f"Noncanonical wikilink path: [[{link['target']}]]",
                                 f"Use [[{link['resolved_path'].removesuffix('.md')}]]"))
    return issues
