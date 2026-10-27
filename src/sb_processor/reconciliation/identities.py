from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import PurePosixPath

import yaml

from ..knowledge.registry import normalize
from ..models import Action
from .inputs import ReconciliationInputs
from .models import (
    IdentityClaim,
    IdentityClaimKind,
    IdentityCollision,
    ReconciledChange,
    ReconciledChangeStatus,
)


_FRONTMATTER = re.compile(r"\A---\s*\r?\n(.*?)\r?\n---(?:\r?\n|\Z)", re.DOTALL)
_TITLE = re.compile(r"(?m)^#\s+(.+?)\s*$")
_EXCLUDED = {
    ReconciledChangeStatus.DEFERRED,
    ReconciledChangeStatus.SKIPPED,
    ReconciledChangeStatus.INVALID,
}


@dataclass(frozen=True)
class EffectiveNote:
    path: str
    title: str
    aliases: tuple[str, ...]
    change_id: str | None
    from_existing_vault: bool


@dataclass(frozen=True)
class IdentityAnalysis:
    notes: tuple[EffectiveNote, ...]
    claims: tuple[IdentityClaim, ...]
    collisions: tuple[IdentityCollision, ...]
    by_normalized: dict[str, tuple[IdentityClaim, ...]]


def _strings(value: object) -> tuple[str, ...]:
    if isinstance(value, str):
        return (value,) if value.strip() else ()
    if isinstance(value, list):
        return tuple(item for item in value if isinstance(item, str) and item.strip())
    return ()


def _content_identity(path: str, content: str) -> tuple[str, tuple[str, ...]]:
    match = _FRONTMATTER.match(content)
    metadata: dict = {}
    if match is not None:
        try:
            parsed = yaml.safe_load(match.group(1))
        except yaml.YAMLError:
            parsed = None
        if isinstance(parsed, dict):
            metadata = parsed
    body = content[match.end():] if match is not None else content
    heading = _TITLE.search(body)
    title_value = metadata.get("title")
    title = (
        title_value.strip()
        if isinstance(title_value, str) and title_value.strip()
        else heading.group(1).strip()
        if heading is not None
        else PurePosixPath(path).stem
    )
    return title, _strings(metadata.get("aliases"))


def _effective_notes(inputs: ReconciliationInputs,
                     changes: list[ReconciledChange]) -> list[EffectiveNote]:
    notes = {
        note.path: EffectiveNote(
            path=note.path,
            title=note.title,
            aliases=tuple(note.aliases),
            change_id=None,
            from_existing_vault=True,
        )
        for note in inputs.vault_notes
    }
    for change in changes:
        if (change.status in _EXCLUDED
                or change.final_action not in (Action.CREATE, Action.UPDATE)
                or change.final_content is None):
            continue
        path = change.final_target_path or change.original_target_path
        title, aliases = _content_identity(path, change.final_content)
        notes[path] = EffectiveNote(
            path=path,
            title=title,
            aliases=aliases,
            change_id=change.id,
            from_existing_vault=False,
        )
    return [notes[path] for path in sorted(notes)]


def _claims(notes: list[EffectiveNote]) -> list[IdentityClaim]:
    claims: list[IdentityClaim] = []
    for note in notes:
        path = PurePosixPath(note.path)
        values = [
            (path.with_suffix("").as_posix(), IdentityClaimKind.CANONICAL_PATH),
            (path.stem, IdentityClaimKind.BASENAME),
            (note.title, IdentityClaimKind.TITLE),
            *((alias, IdentityClaimKind.ALIAS) for alias in note.aliases),
        ]
        seen: set[tuple[str, IdentityClaimKind]] = set()
        for value, kind in values:
            normalized = normalize(value)
            key = (normalized, kind)
            if not normalized or key in seen:
                continue
            seen.add(key)
            claims.append(IdentityClaim(
                value=value,
                normalized=normalized,
                kind=kind,
                canonical_path=note.path,
                change_id=note.change_id,
                from_existing_vault=note.from_existing_vault,
            ))
    return claims


def build_effective_identity_registry(
        inputs: ReconciliationInputs,
        changes: list[ReconciledChange]) -> IdentityAnalysis:
    """Build the in-memory post-reconciliation identity view without writing the vault."""
    notes = _effective_notes(inputs, changes)
    claims = _claims(notes)
    grouped: dict[str, list[IdentityClaim]] = {}
    for claim in claims:
        grouped.setdefault(claim.normalized, []).append(claim)

    collisions: list[IdentityCollision] = []
    for normalized in sorted(grouped):
        group = grouped[normalized]
        canonical_paths = {item.canonical_path for item in group}
        if len(canonical_paths) < 2:
            continue
        change_ids = sorted({item.change_id for item in group if item.change_id is not None})
        collisions.append(IdentityCollision(
            id=f"IDENTITY-{len(collisions) + 1:03d}",
            normalized_identity=normalized,
            claims=group,
            change_ids=change_ids,
            blocking=bool(change_ids),
        ))

    return IdentityAnalysis(
        notes=tuple(notes),
        claims=tuple(claims),
        collisions=tuple(collisions),
        by_normalized={key: tuple(value) for key, value in grouped.items()},
    )
