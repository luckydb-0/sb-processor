from __future__ import annotations

import hashlib
import re
from difflib import SequenceMatcher
from pathlib import PurePosixPath

from ..models import Action, NoteChange, NoteMetadata
from ..review.validators import validate_change
from ..knowledge.registry import normalize
from .inputs import ReconciliationInputs
from .models import ReconciledChange, ReconciledChangeStatus, ValidationFinding, ValidationSeverity


def _finding(code: str, message: str, *change_ids: str,
             severity: ValidationSeverity = ValidationSeverity.ERROR) -> ValidationFinding:
    return ValidationFinding(code=code, severity=severity, message=message, change_ids=list(change_ids))


def _safe_path(value: str) -> bool:
    if not value or "\\" in value or not value.endswith(".md"):
        return False
    path = PurePosixPath(value)
    return not path.is_absolute() and all(part not in ("", ".", "..") for part in path.parts)


def _metadata(inputs: ReconciliationInputs) -> list[NoteMetadata]:
    return [NoteMetadata(
        path=note.path,
        filename=note.filename,
        title=note.title,
        note_type=note.note_type,
        aliases=note.aliases,
        maps=note.maps,
        content_hash=note.content_hash,
    ) for note in inputs.vault_notes]


def _dependency_only_blocked(change: ReconciledChange) -> bool:
    pending_issues = [issue for issue in change.issues if issue.human_decision_id]
    return (
        change.status is ReconciledChangeStatus.BLOCKED
        and bool(pending_issues)
        and all(issue.agent_b_issue_index == -1 and issue.issue_type.value == "link"
                for issue in pending_issues)
    )


def _as_note_change(inputs: ReconciliationInputs, change: ReconciledChange,
                    *, allow_blocked: bool = False) -> NoteChange | None:
    if ((not allow_blocked
         and change.status in (ReconciledChangeStatus.BLOCKED, ReconciledChangeStatus.DEFERRED)
         and not _dependency_only_blocked(change))
            or change.final_action not in (Action.CREATE, Action.UPDATE)
            or change.final_content is None):
        return None
    source = inputs.reviewed_proposal.note_changes[change.agent_a_change_index]
    return NoteChange(
        action=change.final_action,
        note_type=source.note_type,
        title=source.title,
        target_path=change.final_target_path or source.target_path,
        reason=source.reason,
        content=change.final_content,
        sources=source.sources,
        candidate_existing_notes=source.candidate_existing_notes,
        original_content_hash=source.original_content_hash,
    )


def _blocked_identities(inputs: ReconciliationInputs,
                        changes: list[ReconciledChange]) -> set[str]:
    identities: set[str] = set()
    for item in changes:
        if item.status not in (ReconciledChangeStatus.BLOCKED, ReconciledChangeStatus.DEFERRED):
            continue
        if _dependency_only_blocked(item):
            continue
        source = inputs.reviewed_proposal.note_changes[item.agent_a_change_index]
        path = PurePosixPath(item.final_target_path or item.original_target_path)
        identities.update({
            normalize(source.title),
            normalize(path.stem),
            normalize(path.with_suffix("").as_posix()),
        })
    return identities


def find_blocked_link_dependencies(inputs: ReconciliationInputs,
                                   changes: list[ReconciledChange]) -> list[ValidationFinding]:
    """Find links in blocked changes that would break if their targets stay blocked."""
    metadata = _metadata(inputs)
    blocked_identities = _blocked_identities(inputs, changes)
    active = [
        note_change
        for item in changes
        if (note_change := _as_note_change(inputs, item)) is not None
    ]
    findings: list[ValidationFinding] = []
    for item in changes:
        if item.status is not ReconciledChangeStatus.BLOCKED:
            continue
        note_change = _as_note_change(inputs, item, allow_blocked=True)
        if note_change is None:
            continue
        for issue in validate_change(note_change, metadata, active):
            if issue.issue_type.value != "link":
                continue
            match = re.search(r"Unresolved wikilink: \[\[([^\]]+)\]\]", issue.explanation)
            if not match:
                continue
            target = normalize(match.group(1).split("|", 1)[0].split("#", 1)[0])
            if target in blocked_identities:
                findings.append(_finding(
                    "LINK_TO_BLOCKED_CHANGE",
                    issue.explanation,
                    item.id,
                ))
    return findings


_FRONTMATTER = re.compile(r"\A---\s*\r?\n.*?\r?\n---(?:\r?\n|\Z)", re.DOTALL)
_HEADING = re.compile(r"(?m)^#{1,6}\s+(.+?)\s*$")


def _body(content: str) -> str:
    match = _FRONTMATTER.match(content)
    return content[match.end():] if match else content


def _normalized_headings(content: str) -> set[str]:
    return {" ".join(match.group(1).split()).casefold() for match in _HEADING.finditer(_body(content))}


def _normalized_paragraphs(content: str) -> list[str]:
    result = []
    for block in re.split(r"\r?\n\s*\r?\n", _body(content)):
        normalized = " ".join(block.split())
        if len(normalized) < 40 or normalized.startswith("#"):
            continue
        result.append(normalized)
    return result


def _preservation_findings(inputs: ReconciliationInputs,
                           change: ReconciledChange) -> list[ValidationFinding]:
    if change.final_action is not Action.UPDATE or change.final_content is None:
        return []
    target = inputs.vault / (change.final_target_path or change.original_target_path)
    if not target.is_file():
        return []
    existing = target.read_text(encoding="utf-8")
    final_headings = _normalized_headings(change.final_content)
    findings = []
    for heading in sorted(_normalized_headings(existing) - final_headings):
        findings.append(_finding(
            "UPDATE_HEADING_LOSS",
            f"Existing heading is absent from the final update: {heading}",
            change.id,
            severity=ValidationSeverity.WARNING,
        ))
    final_paragraphs = _normalized_paragraphs(change.final_content)
    for paragraph in _normalized_paragraphs(existing):
        candidates = [paragraph]
        patched = paragraph
        for patch in change.applied_fixes:
            if patch.before in patched:
                patched = patched.replace(patch.before, patch.after, 1)
        if patched != paragraph:
            candidates.append(" ".join(patched.split()))
        preserved = any(
            SequenceMatcher(None, candidate, final).ratio() >= 0.90
            for candidate in candidates
            for final in final_paragraphs
        )
        if not preserved:
            findings.append(_finding(
                "UPDATE_PARAGRAPH_LOSS",
                f"Existing paragraph has no preserved counterpart: {paragraph[:120]}",
                change.id,
                severity=ValidationSeverity.WARNING,
            ))
    return findings


def _conflict_findings(changes: list[ReconciledChange]) -> list[ValidationFinding]:
    active = [item for item in changes if item.status not in (
                  ReconciledChangeStatus.BLOCKED, ReconciledChangeStatus.DEFERRED)
              and item.final_action in (Action.CREATE, Action.UPDATE)
              and item.final_target_path]
    findings: list[ValidationFinding] = []
    by_path: dict[str, list[ReconciledChange]] = {}
    for item in active:
        by_path.setdefault(item.final_target_path or "", []).append(item)
    for path, group in by_path.items():
        if len(group) < 2:
            continue
        ids = [item.id for item in group]
        findings.append(_finding("DUPLICATE_TARGET_PATH", f"Multiple changes target {path}", *ids))
        if len({item.final_action for item in group}) > 1:
            findings.append(_finding("CONFLICTING_ACTIONS", f"Conflicting actions target {path}", *ids))
        if len({item.final_content_sha256 for item in group}) > 1:
            findings.append(_finding("CONFLICTING_CONTENT", f"Different final contents target {path}", *ids))

    by_identity: dict[str, list[ReconciledChange]] = {}
    for item in active:
        path = PurePosixPath(item.final_target_path or "")
        identity = normalize(path.with_suffix("").as_posix())
        by_identity.setdefault(identity, []).append(item)
    for group in by_identity.values():
        paths = {item.final_target_path for item in group}
        if len(paths) > 1:
            findings.append(_finding(
                "DUPLICATE_CANONICAL_TARGET",
                f"Targets normalize to the same identity: {', '.join(sorted(path for path in paths if path))}",
                *(item.id for item in group),
            ))

    dots: dict[str, list[ReconciledChange]] = {}
    maps: dict[str, list[ReconciledChange]] = {}
    for item in active:
        path = PurePosixPath(item.final_target_path or "")
        stem = path.stem
        if "Dots" in path.parts:
            dots.setdefault(normalize(stem), []).append(item)
        if "Maps" in path.parts and not stem.casefold().endswith(" - map"):
            maps.setdefault(normalize(stem), []).append(item)
    for identity in sorted(dots.keys() & maps.keys()):
        group = [*dots[identity], *maps[identity]]
        findings.append(_finding(
            "MAP_DOT_BASENAME_CONFLICT",
            "Map and Dot share a basename without the canonical ' - Map' suffix",
            *(item.id for item in group),
        ))
    return findings


def validate_final_changes(inputs: ReconciliationInputs,
                           changes: list[ReconciledChange]) -> list[ValidationFinding]:
    """Run deterministic final validation without writing any target file."""
    findings: list[ValidationFinding] = []
    metadata = _metadata(inputs)
    materialized = [(item, _as_note_change(inputs, item)) for item in changes]
    note_changes = [item for _, item in materialized if item is not None]
    blocked_identities = _blocked_identities(inputs, changes)

    for reconciled, note_change in materialized:
        if reconciled.status in (ReconciledChangeStatus.BLOCKED, ReconciledChangeStatus.DEFERRED):
            continue
        target = reconciled.final_target_path or reconciled.original_target_path
        if reconciled.final_action in (Action.CREATE, Action.UPDATE) and not _safe_path(target):
            findings.append(_finding("INVALID_TARGET_PATH", f"Unsafe target path: {target}", reconciled.id))
        if reconciled.final_action in (Action.CREATE, Action.UPDATE) and not (reconciled.final_content or "").strip():
            findings.append(_finding("MISSING_FINAL_CONTENT", "CREATE/UPDATE requires final Markdown", reconciled.id))
            continue
        target_exists = (inputs.vault / target).is_file() if _safe_path(target) else False
        if reconciled.final_action is Action.CREATE and target_exists:
            findings.append(_finding("CREATE_TARGET_EXISTS", f"CREATE target already exists: {target}", reconciled.id))
        if reconciled.final_action is Action.UPDATE and not target_exists:
            findings.append(_finding("UPDATE_TARGET_MISSING", f"UPDATE target does not exist: {target}", reconciled.id))
        if reconciled.final_content is not None and reconciled.final_content_sha256 is not None:
            actual = hashlib.sha256(reconciled.final_content.encode("utf-8")).hexdigest()
            if actual != reconciled.final_content_sha256:
                findings.append(_finding("FINAL_CONTENT_HASH_MISMATCH", "Final content hash does not match", reconciled.id))
        if reconciled.final_content is not None:
            for patch in reconciled.applied_fixes:
                if patch.before and patch.before in reconciled.final_content:
                    findings.append(_finding(
                        "CLAIMED_FIX_REMAINS",
                        f"A span claimed as fixed remains in final content: {patch.before!r}",
                        reconciled.id,
                    ))
        if note_change is None:
            continue
        other = [item for item in note_changes if item is not note_change]
        for issue in validate_change(note_change, metadata, other):
            code = issue.issue_type.value.upper()
            if issue.issue_type.value == "link":
                match = re.search(r"Unresolved wikilink: \[\[([^\]]+)\]\]", issue.explanation)
                if match and normalize(match.group(1).split("|", 1)[0].split("#", 1)[0]) in blocked_identities:
                    code = "LINK_TO_BLOCKED_CHANGE"
            findings.append(_finding(
                code,
                issue.explanation,
                reconciled.id,
            ))
        findings.extend(_preservation_findings(inputs, reconciled))
    findings.extend(_conflict_findings(changes))
    return findings
