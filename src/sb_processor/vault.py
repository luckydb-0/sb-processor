from __future__ import annotations

import hashlib
import logging
import re
from pathlib import Path
from typing import Any, Iterator

import yaml

from .models import ScannedNote

log = logging.getLogger(__name__)
_HEADING = re.compile(r"^#\s+(.+?)\s*$", re.MULTILINE)
_FRONTMATTER = re.compile(r"\A---\s*\r?\n(.*?)\r?\n---\s*\r?\n", re.DOTALL)


def _strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, list):
        return [item for item in value if isinstance(item, str) and item.strip()]
    return []


def parse_note(path: Path, vault_path: Path) -> ScannedNote:
    raw = path.read_bytes()
    content = raw.decode("utf-8-sig", errors="replace")
    match = _FRONTMATTER.match(content)
    frontmatter: dict[str, Any] = {}
    body = content
    if match:
        try:
            parsed = yaml.safe_load(match.group(1))
            if isinstance(parsed, dict):
                frontmatter = parsed
                body = content[match.end():]
            else:
                log.warning("Frontmatter is not a mapping: %s", path)
        except yaml.YAMLError as exc:
            log.warning("Invalid frontmatter in %s: %s", path, exc)
    heading = _HEADING.search(body)
    title_value = frontmatter.get("title")
    title = title_value.strip() if isinstance(title_value, str) and title_value.strip() else (heading.group(1).strip() if heading else path.stem)
    type_value = frontmatter.get("type")
    note_type = type_value.strip() if isinstance(type_value, str) and type_value.strip() else None
    return ScannedNote(
        path=path.relative_to(vault_path).as_posix(),
        filename=path.name,
        title=title,
        note_type=note_type,
        aliases=_strings(frontmatter.get("aliases")),
        maps=_strings(frontmatter.get("maps")),
        frontmatter=frontmatter,
        body=body,
        mtime=path.stat().st_mtime,
        content_hash=hashlib.sha256(raw).hexdigest(),
    )


def scan_vault(vault_path: Path) -> Iterator[ScannedNote]:
    vault_path = Path(vault_path).resolve(strict=True)
    if not vault_path.is_dir():
        raise ValueError(f"Vault is not a directory: {vault_path}")
    for path in sorted(vault_path.rglob("*.md")):
        if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(vault_path):
            log.warning("Skipping unsafe Markdown path: %s", path)
            continue
        log.info("Scanning %s", path.relative_to(vault_path))
        yield parse_note(path, vault_path)
