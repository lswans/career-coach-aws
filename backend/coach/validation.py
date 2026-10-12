"""Intake rules: no synthesis until the user supplies documents AND real career goals."""

from __future__ import annotations

from .config import Settings
from .ingest import Document


class IntakeError(ValueError):
    """Every intake problem at once, keyed by form field, so the UI can show them together."""

    def __init__(self, fields: dict[str, str]):
        super().__init__("; ".join(f"{key}: {value}" for key, value in fields.items()))
        self.fields = fields


def validate_intake(
    goals: str,
    docs: list[Document],
    settings: Settings,
    file_errors: list[str] | None = None,
) -> str:
    """Return the trimmed goals text, or raise IntakeError."""
    fields: dict[str, str] = {}
    if file_errors:
        fields["files"] = " ".join(file_errors)
    if sum(len(doc.text) for doc in docs) < settings.min_doc_chars:
        fields["documents"] = (
            "Add at least one document: upload a resume (PDF, DOCX, TXT or MD) or paste your "
            f"achievements, certifications or projects ({settings.min_doc_chars}+ characters in total)."
        )
    cleaned = goals.strip()
    if len(cleaned) < settings.min_goal_chars:
        fields["goals"] = (
            f"Describe your career goals in at least {settings.min_goal_chars} characters "
            f"(you have {len(cleaned)}). Say what role you want, by when, and why."
        )
    if fields:
        raise IntakeError(fields)
    return cleaned
