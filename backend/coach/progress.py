"""Deterministic helpers for refreshing a profile from the progress log. No model calls.

A chat-driven refresh cannot reread the person's documents: raw uploads are never kept. So the
previous profile is the trusted baseline, turned into one bounded synthetic document, and the
progress log says what changed since. Two checks here run after the model, in code, so a
refresh is right even when a small model ignores its instructions:

- drop_completed: a next step the log shows is done is removed (strong normalized match only).
- ensure_evidence: a milestone reported since the last profile shows up as evidence on the
  skill the note names, when the model left it out.

Context policy for the progress log (documented in docs/DESIGN.md):
- the model sees the newest notes, oldest first, up to REFRESH_MAX_NOTES notes and
  REFRESH_LOG_CHARS characters, each note clipped to NOTE_MAX_CHARS;
- the code checks above always read the complete log, so an old completion still counts.
"""

from __future__ import annotations

import re
from typing import Any

from .ingest import Document
from .memory.base import note_sentence
from .verify import CREDENTIAL_HINT, LEADING_VERB, has_run, words

REFRESH_MAX_NOTES = 40
REFRESH_LOG_CHARS = 6_000
NOTE_MAX_CHARS = 300
EVIDENCE_MAX_CHARS = 120
BASELINE_NAME = "Profile version {version} (baseline)"
LOG_NAME = "Progress log ({count})"
# Source entries a refresh adds. A later refresh drops them before adding its own,
# so the list keeps naming the original documents instead of growing every time.
DERIVED_SOURCE = re.compile(r"^(Profile version \d+ \(baseline\)|Progress log \(.*\))$")

COMPLETED_KINDS = frozenset({"win", "learning", "certification", "project"})
COMPLETION = re.compile(
    r"\b(pass(ed)?|earn(ed)?|complet(ed|e)|finish(ed)?|got|receiv(ed)?|achiev(ed)?|certified|obtain(ed)?|"
    r"ship(ped)?|launch(ed)?|deploy(ed)?|publish(ed)?|buil[td]|won|awarded)\b",
    re.IGNORECASE,
)
IN_PROGRESS = re.compile(
    r"\b(start(ed|ing)?|studying|preparing|prepping|scheduled|registered|signed up|enrolled|booked|"
    r"plan(ning|ned)?|working (on|toward)|halfway|will)\b",
    re.IGNORECASE,
)


def _stem(word: str) -> str:
    for suffix in ("ing", "ed", "s"):
        if len(word) > len(suffix) + 3 and word.endswith(suffix):
            return word[: -len(suffix)]
    return word


def key_words(text: str) -> list[str]:
    """Distinctive words (verify.GENERIC removed), lightly stemmed so 'deployed' meets 'deploy'."""
    return [_stem(w) for w in words(text)]


def is_completion(note: dict[str, Any]) -> bool:
    """A note that reports something finished, not started or planned."""
    text = str(note.get("text", ""))
    return (str(note.get("kind", "")) in COMPLETED_KINDS and bool(COMPLETION.search(text))
            and not IN_PROGRESS.search(text))


def completed_by(opportunity: dict[str, Any], notes: list[dict[str, Any]]) -> dict[str, Any] | None:
    """The completion note that strongly matches this next step, or None.

    Strong means the step's distinctive title words appear in the note, adjacent and in order.
    One distinctive word is only enough for credentials ("CKA certification" vs "Passed the CKA
    certification"), because "Advanced Python course" must survive "Learned Python".
    """
    for title in {str(opportunity.get("title", "")), str(opportunity.get("original_title", ""))}:
        want = key_words(LEADING_VERB.sub("", title.strip()))
        if not want:
            continue
        for note in notes:
            if not is_completion(note):
                continue
            text = str(note.get("text", ""))
            if not has_run(key_words(text), want):
                continue
            if len(want) >= 2 or (CREDENTIAL_HINT.search(title) and CREDENTIAL_HINT.search(text)
                                  and note.get("kind") == "certification"):
                return note
    return None


def drop_completed(opportunities: list[Any], notes: list[dict[str, Any]]) -> tuple[list[Any], list[str]]:
    """Remove next steps the log shows are done. Works on Pydantic models or dicts."""
    kept, dropped = [], []
    for opp in opportunities:
        data = opp.model_dump() if hasattr(opp, "model_dump") else dict(opp)
        if completed_by(data, notes):
            dropped.append(str(data.get("title", "")))
        else:
            kept.append(opp)
    return kept, dropped


def _tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9+#]+", text.lower())


def skill_matches(skill_name: str, note_skill: str) -> bool:
    """'AWS' matches 'AWS' and 'AWS Cloud'; 'Cloud architecture' matches 'Cloud Architecture'."""
    have, want = _tokens(skill_name), _tokens(note_skill)
    return bool(want) and (has_run(have, want) or has_run(want, have))


def ensure_evidence(skills: list[Any], fresh: list[dict[str, Any]]) -> list[Any]:
    """Make each new milestone visible as evidence on the skill its note names.

    Only notes reported since the baseline count (older ones already shaped earlier versions),
    and only when the skill exists in the draft: the code never invents a skill or its level.
    """
    out = list(skills)
    for note in fresh:
        if not is_completion(note) or not str(note.get("skill", "")).strip():
            continue
        core = set(key_words(str(note.get("text", ""))))
        for i, skill in enumerate(out):
            if not skill_matches(skill.name, str(note["skill"])):
                continue
            if any(len(core & set(key_words(e))) >= min(2, len(core)) for e in skill.evidence):
                break  # the model already cited it
            evidence = [str(note["text"]).strip()[:EVIDENCE_MAX_CHARS], *skill.evidence][:3]
            out[i] = skill.model_copy(update={"evidence": evidence})
            break
    return out


def bounded_notes(notes: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    """The newest notes that fit the refresh budget, oldest first, plus how many were left out."""
    chosen: list[dict[str, Any]] = []
    used = 0
    for note in reversed(notes):
        if len(chosen) >= REFRESH_MAX_NOTES:
            break
        clipped = {**note, "text": str(note.get("text", ""))[:NOTE_MAX_CHARS]}
        size = len(note_sentence(clipped)) + 3
        if used + size > REFRESH_LOG_CHARS:
            break
        chosen.append(clipped)
        used += size
    chosen.reverse()
    return chosen, len(notes) - len(chosen)


def notes_since(notes: list[dict[str, Any]], created_at: str) -> list[dict[str, Any]]:
    """Notes saved since a profile was built. ISO 8601 UTC strings compare in time order; timestamps
    have one-second resolution, so a note from the same second counts as new (ensure_evidence skips
    anything the profile already cites)."""
    return [n for n in notes if str(n.get("created_at", "")) >= created_at]


def baseline_document(profile: dict[str, Any], max_chars: int) -> Document:
    """The previous profile as one synthetic source document, clipped to `max_chars`.

    It says plainly that the original documents are not kept, so the model treats it as the
    record of what they showed rather than as something the person wrote.
    """
    version = profile.get("version", 1)
    originals = ", ".join(str(s.get("name", "")) for s in original_sources(profile)) or "not recorded"
    lines = [
        f"The coach's previous assessment of this person (profile version {version}, "
        f"built {str(profile.get('created_at', ''))[:10]}). The original documents ({originals}) are not "
        "kept; this assessment is the trusted record of what they showed.",
        f"Headline: {profile.get('headline', '')}",
        f"Summary: {profile.get('summary', '')}",
        f"Target role: {profile.get('target_role', '')}",
        f"Goal alignment then: {profile.get('goal_alignment', 0)}/100",
        "Skills:",
        *(f"- {s.get('name', '')} ({s.get('category', '')}, level {s.get('level', 0)}/5, "
          f"{s.get('relevance', '')} relevance). Evidence: {'; '.join(map(str, s.get('evidence', [])))}"
          for s in profile.get("skills", [])),
        "Gaps:",
        *(f"- {w.get('area', '')} ({w.get('severity', '')}): {w.get('why_it_matters', '')}"
          for w in profile.get("weaknesses", [])),
        "Next steps suggested then (drop any the progress log shows are done):",
        *(f"- {o.get('title', '')} [{o.get('timeframe', '')}]: {o.get('action', '')}"
          for o in profile.get("opportunities", [])),
    ]
    text = "\n".join(lines)
    return Document(name=BASELINE_NAME.format(version=version), kind="text", text=text[:max_chars])


def original_sources(profile: dict[str, Any]) -> list[dict[str, Any]]:
    return [s for s in profile.get("sources", []) if not DERIVED_SOURCE.match(str(s.get("name", "")))]
