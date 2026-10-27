from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from pathlib import PurePosixPath

import yaml

from ..knowledge.registry import normalize
from ..models import Action
from .inputs import ReconciliationInputs
from .models import (
    IdentityClaim,
    IdentityClaimKind,
    IdentityCollision,
    PatchKind,
    PatchOperation,
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


@dataclass(frozen=True)
class IdentityResolutionPlan:
    collision_id: str
    create_change_id: str
    existing_change_id: str
    existing_path: str
    existing_content: str
    final_content: str
    patch: PatchOperation


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
        if (change.status is ReconciledChangeStatus.BLOCKED
                and change.final_action is Action.UPDATE):
            continue
        if (change.status is ReconciledChangeStatus.BLOCKED
                and change.final_action is Action.CREATE
                and not change.human_decision_required):
            continue
        path = change.final_target_path or change.original_target_path
        title, aliases = _content_identity(path, change.final_content)
        existing = notes.get(path)
        identity_changed = (
            change.final_action is Action.CREATE
            or existing is None
            or normalize(existing.title) != normalize(title)
            or {normalize(item) for item in existing.aliases}
            != {normalize(item) for item in aliases}
        )
        notes[path] = EffectiveNote(
            path=path,
            title=title,
            aliases=aliases,
            change_id=change.id if identity_changed else None,
            from_existing_vault=not identity_changed,
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


_INLINE_ALIASES = re.compile(
    r"(?m)^(?P<prefix>[ \t]*aliases:[ \t]*\[)(?P<body>[^\]\n]*)(?P<suffix>\][ \t]*)$"
)


def _exact_alias_patch(content: str, alias: str) -> PatchOperation | None:
    matches = list(_INLINE_ALIASES.finditer(content))
    if len(matches) != 1:
        return None
    match = matches[0]
    raw_items = [item.strip() for item in match.group("body").split(",") if item.strip()]
    decoded: list[str] = []
    for raw in raw_items:
        try:
            value = yaml.safe_load(raw)
        except yaml.YAMLError:
            return None
        if not isinstance(value, str):
            return None
        decoded.append(value)
    matching = [index for index, value in enumerate(decoded) if value == alias]
    if len(matching) != 1:
        return None
    remaining = [raw for index, raw in enumerate(raw_items) if index != matching[0]]
    replacement = f"{match.group('prefix')}{', '.join(remaining)}{match.group('suffix')}"
    return PatchOperation(
        kind=PatchKind.REPLACE,
        start=match.start(),
        end=match.end(),
        before=match.group(0),
        after=replacement,
    )


def plan_keep_separate(
        inputs: ReconciliationInputs,
        collision: IdentityCollision,
        changes: list[ReconciledChange]) -> IdentityResolutionPlan | None:
    """Return the one safe alias-removal recipe supported by v1.1, if available."""
    change_by_id = {item.id: item for item in changes}
    change_by_path = {
        (item.final_target_path or item.original_target_path): item
        for item in changes
    }
    create_ids = {
        claim.change_id
        for claim in collision.claims
        if claim.change_id is not None
        and change_by_id[claim.change_id].final_action is Action.CREATE
    }
    existing_alias_claims = [
        claim for claim in collision.claims
        if claim.kind is IdentityClaimKind.ALIAS and claim.from_existing_vault
    ]
    if len(create_ids) != 1 or len(existing_alias_claims) != 1:
        return None
    existing_claim = existing_alias_claims[0]
    existing_change = change_by_path.get(existing_claim.canonical_path)
    if existing_change is None:
        return None
    scanned = next(
        (note for note in inputs.vault_notes if note.path == existing_claim.canonical_path),
        None,
    )
    if (scanned is None
            or existing_change.expected_existing_content_sha256 != scanned.content_hash):
        return None
    target = Path(inputs.vault) / existing_claim.canonical_path
    existing_content = target.read_text(encoding="utf-8")
    patch = _exact_alias_patch(existing_content, existing_claim.value)
    if patch is None:
        return None
    final_content = (
        existing_content[:patch.start] + patch.after + existing_content[patch.end:]
    )
    return IdentityResolutionPlan(
        collision_id=collision.id,
        create_change_id=next(iter(create_ids)),
        existing_change_id=existing_change.id,
        existing_path=existing_claim.canonical_path,
        existing_content=existing_content,
        final_content=final_content,
        patch=patch,
    )
