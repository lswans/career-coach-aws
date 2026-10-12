"""Local brain: JSON-lines files on disk. Works offline with no AWS account."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from strands.session.file_session_manager import FileSessionManager

from .base import MemoryStore, note_sentence

_WORD = re.compile(r"[a-z0-9+#]{3,}")
_STOP = {"the", "and", "for", "with", "that", "this", "you", "your", "what", "how", "should", "about", "have", "was"}


def _words(text: str) -> set[str]:
    return set(_WORD.findall(text.lower())) - _STOP


class LocalMemoryStore(MemoryStore):
    backend = "local"

    def __init__(self, data_dir: Path) -> None:
        self.root = Path(data_dir)

    def _dir(self, user_id: str) -> Path:
        path = self.root / user_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    @staticmethod
    def _append(path: Path, record: dict[str, Any]) -> None:
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    @staticmethod
    def _read(path: Path) -> list[dict[str, Any]]:
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]

    def save_profile(self, user_id: str, profile: dict[str, Any]) -> None:
        self._append(self._dir(user_id) / "profiles.jsonl", profile)

    def profile_history(self, user_id: str) -> list[dict[str, Any]]:
        return self._read(self.root / user_id / "profiles.jsonl")

    def add_note(self, user_id: str, note: dict[str, Any]) -> None:
        self._append(self._dir(user_id) / "notes.jsonl", note)

    def list_notes(self, user_id: str) -> list[dict[str, Any]]:
        return self._read(self.root / user_id / "notes.jsonl")

    def recall(self, user_id: str, query: str, top_k: int = 5) -> list[str]:
        """Keyword-overlap search; falls back to the most recent notes when nothing matches."""
        notes = self.list_notes(user_id)
        wanted = _words(query)
        scored = [(len(wanted & _words(note_sentence(n))), i, n) for i, n in enumerate(notes)]
        hits = sorted((s for s in scored if s[0] > 0), key=lambda s: (s[0], s[1]), reverse=True)
        chosen = [n for _, _, n in hits[:top_k]] or notes[-top_k:]
        return [note_sentence(n) for n in chosen]

    def session_manager(self, user_id: str, session_id: str) -> FileSessionManager:
        return FileSessionManager(session_id=session_id, storage_dir=str(self._dir(user_id) / "sessions"))
