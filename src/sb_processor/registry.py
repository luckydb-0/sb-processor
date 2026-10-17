from __future__ import annotations

import json
import re
import sqlite3
import unicodedata
from pathlib import Path
from typing import Iterable

from .models import CandidateMatch, ScannedNote

_WORD = re.compile(r"\w+", re.UNICODE)


def normalize(value: str) -> str:
    return " ".join(_WORD.findall(unicodedata.normalize("NFKC", value).casefold()))


def tokens(value: str) -> set[str]:
    return set(normalize(value).split())


def lexical_tokens(value: str) -> set[str]:
    return {word for word in tokens(value) if len(word) > 1}


class Registry:
    def __init__(self, database_path: Path):
        self.path = Path(database_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS notes (
                    path TEXT PRIMARY KEY, filename TEXT NOT NULL, filename_norm TEXT NOT NULL,
                    title TEXT NOT NULL, title_norm TEXT NOT NULL, note_type TEXT,
                    aliases_json TEXT NOT NULL, maps_json TEXT NOT NULL,
                    frontmatter_json TEXT NOT NULL, body TEXT NOT NULL,
                    mtime REAL NOT NULL, content_hash TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS aliases (
                    alias_norm TEXT NOT NULL, path TEXT NOT NULL,
                    PRIMARY KEY (alias_norm, path),
                    FOREIGN KEY (path) REFERENCES notes(path) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_notes_title ON notes(title_norm);
                CREATE INDEX IF NOT EXISTS idx_notes_filename ON notes(filename_norm);
                CREATE INDEX IF NOT EXISTS idx_notes_type ON notes(note_type);
                CREATE INDEX IF NOT EXISTS idx_alias_name ON aliases(alias_norm);
            """)

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        return db

    def rebuild(self, notes: Iterable[ScannedNote]) -> int:
        count = 0
        with self._connect() as db:
            db.execute("DELETE FROM aliases")
            db.execute("DELETE FROM notes")
            for note in notes:
                db.execute(
                    "INSERT INTO notes VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (note.path, note.filename, normalize(note.filename), note.title,
                     normalize(note.title), note.note_type, json.dumps(note.aliases),
                     json.dumps(note.maps), json.dumps(note.frontmatter, default=str),
                     note.body, note.mtime, note.content_hash),
                )
                db.executemany("INSERT INTO aliases VALUES (?, ?)", [(normalize(a), note.path) for a in note.aliases])
                count += 1
        return count

    def get(self, path: str) -> ScannedNote | None:
        with self._connect() as db:
            row = db.execute("SELECT * FROM notes WHERE path=?", (path,)).fetchone()
        return self._note(row) if row else None

    def all_notes(self) -> list[ScannedNote]:
        with self._connect() as db:
            rows = db.execute("SELECT * FROM notes ORDER BY path").fetchall()
        return [self._note(row) for row in rows]

    def find_by_type(self, note_type: str) -> list[ScannedNote]:
        with self._connect() as db:
            rows = db.execute("SELECT * FROM notes WHERE note_type=? ORDER BY path", (note_type,)).fetchall()
        return [self._note(row) for row in rows]

    @staticmethod
    def _note(row: sqlite3.Row) -> ScannedNote:
        return ScannedNote(path=row["path"], filename=row["filename"], title=row["title"],
                           note_type=row["note_type"], aliases=json.loads(row["aliases_json"]),
                           maps=json.loads(row["maps_json"]), frontmatter=json.loads(row["frontmatter_json"]),
                           body=row["body"], mtime=row["mtime"], content_hash=row["content_hash"])

    def lookup(self, query: str, limit: int = 10) -> list[CandidateMatch]:
        key = normalize(query)
        if not key:
            return []
        words = lexical_tokens(query)
        results = []
        with self._connect() as db:
            rows = db.execute("SELECT n.*, GROUP_CONCAT(a.alias_norm, char(31)) AS alias_names FROM notes n LEFT JOIN aliases a ON a.path=n.path GROUP BY n.path").fetchall()
        for row in rows:
            aliases = set((row["alias_names"] or "").split("\x1f"))
            if key == row["title_norm"]:
                kind, score = "exact_title", 1.0
            elif key == row["filename_norm"]:
                kind, score = "exact_filename", 0.99
            elif key in aliases:
                kind, score = "alias", 0.98
            else:
                name_words = lexical_tokens(row["title"] + " " + row["filename"] + " " + " ".join(aliases))
                overlap = len(words & name_words)
                if not overlap:
                    continue
                score = overlap / len(words | name_words)
                kind = "lexical"
            results.append(CandidateMatch(path=row["path"], title=row["title"], note_type=row["note_type"], match_kind=kind, score=score))
        return sorted(results, key=lambda m: (-m.score, m.path))[:limit]

    def relevant(self, text: str, limit: int = 8) -> list[ScannedNote]:
        query_words = tokens(text)
        ranked = []
        for note in self.all_notes():
            score = len(query_words & tokens(" ".join([note.title, *note.aliases, note.body[:3000]])))
            if score:
                ranked.append((score, note.path, note))
        return [item[2] for item in sorted(ranked, key=lambda x: (-x[0], x[1]))[:limit]]
