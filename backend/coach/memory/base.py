"""The coach's "brain" interface. Two implementations: local files and AgentCore Memory."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


def note_sentence(note: dict[str, Any]) -> str:
    """Render a progress note as one sentence for prompts and semantic search."""
    day = str(note.get("created_at", ""))[:10]
    skill = f" (skill: {note['skill']})" if note.get("skill") else ""
    return f"{day} {str(note.get('kind', 'note')).title()}: {note.get('text', '')}{skill}".strip()


class MemoryUnavailable(RuntimeError):
    """The memory backend could not be reached. The message says how to fix it."""


class MemoryStore(ABC):
    """Profiles are versioned snapshots (oldest first) so the app can show trends over time."""

    backend: str = "abstract"

    @abstractmethod
    def save_profile(self, user_id: str, profile: dict[str, Any]) -> None: ...

    @abstractmethod
    def profile_history(self, user_id: str) -> list[dict[str, Any]]: ...

    def latest_profile(self, user_id: str) -> dict[str, Any] | None:
        history = self.profile_history(user_id)
        return history[-1] if history else None

    @abstractmethod
    def add_note(self, user_id: str, note: dict[str, Any]) -> None: ...

    @abstractmethod
    def list_notes(self, user_id: str) -> list[dict[str, Any]]: ...

    @abstractmethod
    def recall(self, user_id: str, query: str, top_k: int = 5) -> list[str]:
        """Long-term memories relevant to `query`, as short sentences."""

    @abstractmethod
    def session_manager(self, user_id: str, session_id: str) -> Any:
        """A Strands SessionManager that persists one chat session's turns."""
