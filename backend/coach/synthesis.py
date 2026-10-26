"""Profile synthesis: one structured model call, streamed, then a web check of the next steps.

Why not an agent here? A tool-calling loop costs extra model round trips, and the profile is
one fixed shape. The Pydantic schema goes to the model with the request: on Bedrock as the
input schema of a tool Claude must call, on Ollama as `format`, which constrains decoding.
Either way the answer is JSON in our shape, and clean_draft() clamps what slips through.

The build is an async generator of events, so the setup screen can show what is really
happening (no timers dressed up as progress):
  {"type": "stage", "stage": "read"|"model"|"verify"|"save", "state": "active"|"done"|"skipped", "detail": str}
  {"type": "progress", "section": str, "chars": int, "skills": [...], "weaknesses": [...], "opportunities": [...]}
  {"type": "profile", "profile": CareerProfile}   (last; the API turns it into a "done" event)
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from collections.abc import AsyncIterator
from contextlib import aclosing
from datetime import datetime, timezone
from typing import Any

from .config import Settings
from .ingest import Document, fit_to_budget
from .llm import model_label, model_name, stream_structured
from .memory.base import MemoryStore, note_sentence
from .progress import (LOG_NAME, baseline_document, bounded_notes, drop_completed, ensure_evidence, notes_since,
                       original_sources)
from .schemas import CareerProfile, ProfileDraft, SourceDoc
from .search import WebSearch
from .verify import verify_opportunities

SYSTEM_PROMPT = """You are an experienced, encouraging career coach. You read a person's documents \
and compare them with the career goals they wrote themselves.

Rules:
- Use ONLY facts found in the documents and the progress log. Never invent employers, degrees, \
certifications or numbers.
- Every skill needs evidence: short phrases taken from the documents.
- Rate each skill 1-5 (1 beginner, 3 working proficiency, 5 expert) from the evidence, not from wishes.
- Weaknesses are gaps between the documents and the goals: missing skills, missing proof, missing experience.
- Opportunities are concrete next steps the person could start soon (a course, certification, project, \
networking move or role change). Name the skills each one builds. Only name a specific certification, \
course or program if you are sure it exists, using its official name; otherwise describe the step without a name.
- Don't suggest something the progress log says is already done.
- goal_alignment is 0-100: how ready the person is for the goal today.
- Be specific and kind. Speak to the person as "you".

Calibration (small models over-rate; follow these anchors):
- Level 5 needs years of professional evidence. Students and interns are usually 1-3. Level 4 needs \
strong, repeated proof such as a shipped project plus work experience with that skill.
- If the documents say the person has not used a skill in practice, rate it 1 and list the gap as a weakness.
- goal_alignment: 0-30 just starting, 31-60 building foundations, 61-80 ready to apply for entry-level roles \
in the target field, 81-100 already doing this job."""

PROGRESS_EVERY = 0.4  # seconds between live progress events
MAX_NOTES = 15
SECTION = re.compile(r'"(headline|summary|target_role|goal_alignment|skills|weaknesses|opportunities)"\s*:')
ITEMS = {  # each list's items carry a key no other part of the schema uses
    "skills": re.compile(r'"name"\s*:\s*"((?:[^"\\]|\\.)*)"'),
    "weaknesses": re.compile(r'"area"\s*:\s*"((?:[^"\\]|\\.)*)"'),
    "opportunities": re.compile(r'"title"\s*:\s*"((?:[^"\\]|\\.)*)"'),
}


class SynthesisError(RuntimeError):
    """The model answered, but not with a usable profile."""


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def stage(name: str, state: str, detail: str) -> dict[str, Any]:
    return {"type": "stage", "stage": name, "state": state, "detail": detail}


def build_prompt(goals: str, corpus: str, notes: list[dict[str, Any]] | None = None) -> str:
    log = "\n".join(f"- {note_sentence(n)}" for n in (notes or [])[-MAX_NOTES:])
    return (
        "CAREER GOALS (written by the person):\n"
        f"{goals}\n\n"
        "DOCUMENTS:\n"
        f"{corpus}\n\n"
        + (f"PROGRESS LOG (what the person told their coach since earlier profiles):\n{log}\n\n" if log else "")
        + "Return the career profile as JSON: 5-10 skills, 3-5 weaknesses, 3-5 opportunities. "
        "The headline is a one-line professional tagline about the person, not just their name. "
        "Keep every text field under 200 characters."
    )


def build_refresh_prompt(goals: str, baseline: str, notes: list[dict[str, Any]], fresh: list[dict[str, Any]],
                         left_out: int) -> str:
    log = "\n".join(f"- {note_sentence(n)}" for n in notes) or "- (empty)"
    new = "\n".join(f"- {note_sentence(n)}" for n in fresh) or "- Nothing new; re-check the profile against the log."
    older = f"\n({left_out} older notes are not shown.)" if left_out else ""
    return (
        "CAREER GOALS (written by the person; keep them as they are):\n"
        f"{goals}\n\n"
        "BASELINE PROFILE:\n"
        f"{baseline}\n\n"
        f"PROGRESS LOG (oldest first):\n{log}{older}\n\n"
        f"NEW SINCE THE BASELINE:\n{new}\n\n"
        "Update the baseline profile with the progress log. Keep baseline skills and their evidence unless "
        "the log changes them. Add each finished certification, course or project as evidence (quote the log) "
        "on the skill it proves, and raise that skill's level only if the log is real proof. Recalculate "
        "goal_alignment, weaknesses and opportunities against the goals. Never suggest a step the log shows is "
        "done: replace it with the next logical step.\n\n"
        "Return the career profile as JSON: 5-10 skills, 3-5 weaknesses, 3-5 opportunities. "
        "Keep every text field under 200 characters."
    )


def next_version(history: list[dict[str, Any]]) -> int:
    """One past the highest saved version. Counting alone would reuse a number if a record were missing."""
    return max([len(history), *(int(p.get("version", 0) or 0) for p in history)]) + 1


def progress_event(text: str) -> dict[str, Any]:
    """What the model has written so far, read off its partial JSON (keys arrive in schema order)."""

    def unescape(raw: str) -> str:
        try:
            return json.loads(f'"{raw}"')
        except json.JSONDecodeError:
            return raw

    sections = SECTION.findall(text)
    return {
        "type": "progress",
        "section": sections[-1] if sections else "",
        "chars": len(text),
        **{key: [unescape(m) for m in pattern.findall(text)] for key, pattern in ITEMS.items()},
    }


def _clean_list(values: list[str], limit: int) -> list[str]:
    out: list[str] = []
    for value in values:
        value = value.strip()
        if value and value.lower() not in {v.lower() for v in out}:
            out.append(value)
    return out[:limit]


def clean_draft(draft: ProfileDraft) -> ProfileDraft:
    """Clamp numbers, drop duplicates and enforce list sizes the grammar may not have."""
    seen: set[str] = set()
    skills = []
    for skill in draft.skills:
        name = skill.name.strip()
        if not name or name.lower() in seen:
            continue
        seen.add(name.lower())
        skills.append(
            skill.model_copy(
                update={
                    "name": name,
                    "level": min(5, max(1, skill.level)),
                    "evidence": _clean_list(skill.evidence, 3),
                }
            )
        )
    if not skills:
        raise SynthesisError("The model returned no skills. Try again, or set COACH_MODEL to a larger model.")
    weaknesses = [w for w in draft.weaknesses if w.area.strip()][:5]
    opportunities = [
        o.model_copy(update={"related_skills": _clean_list(o.related_skills, 4)})
        for o in draft.opportunities
        if o.title.strip()
    ][:5]
    return draft.model_copy(
        update={
            "headline": draft.headline.strip(),
            "summary": draft.summary.strip(),
            "target_role": draft.target_role.strip(),
            "goal_alignment": min(100, max(0, draft.goal_alignment)),
            "skills": skills[:12],
            "weaknesses": weaknesses,
            "opportunities": opportunities,
        }
    )


async def _draft(model: Any, messages: list[dict[str, Any]], name: str) -> AsyncIterator[dict[str, Any]]:
    """Stream the profile draft, retrying once if the finished JSON doesn't validate."""
    for attempt in (1, 2):
        last = 0.0
        try:
            async with aclosing(stream_structured(model, ProfileDraft, messages, SYSTEM_PROMPT)) as stream:
                async for event in stream:
                    if event["type"] == "output":
                        yield event
                        return
                    if (now := time.monotonic()) - last >= PROGRESS_EVERY:
                        last = now
                        yield progress_event(event["text"])
        except ValueError as exc:  # rare: the JSON didn't fit the schema
            if attempt == 2:
                raise SynthesisError(f"The model's answer could not be read twice in a row ({exc}).") from exc
            yield stage("model", "active", f"{name}'s answer didn't parse, so it's writing it again")
    raise SynthesisError("The model returned no output.")


async def synthesize_events(
    *,
    user_id: str,
    goals: str,
    docs: list[Document],
    settings: Settings,
    store: MemoryStore,
    model: Any,
    checker: Any = None,
    search: WebSearch | None = None,
    notes: list[dict[str, Any]] | None = None,
    baseline: dict[str, Any] | None = None,
    request_id: str = "",
) -> AsyncIterator[dict[str, Any]]:
    """Build and save one profile version.

    With `baseline` (a chat-driven refresh), `docs` is ignored: the previous profile becomes the
    one source document and `goals` should be the baseline's own goals. `notes` is always the
    complete progress log; the model sees a bounded part of it (coach/progress.py), while the
    completed-step check reads all of it.
    """
    notes = notes or []
    fresh: list[dict[str, Any]] = []
    if baseline is None:
        corpus, sources = fit_to_budget(docs, settings.max_doc_chars)
        detail = f"{plural(len(sources), 'document')} · {sum(s.chars for s in sources):,} characters"
        if any(s.truncated for s in sources):
            detail += " (long ones trimmed to fit)"
        if notes:
            detail += f" · {plural(min(len(notes), MAX_NOTES), 'progress note')}"
        prompt = build_prompt(goals, corpus, notes)
        notes_used = min(len(notes), MAX_NOTES)
    else:
        shown, left_out = bounded_notes(notes)
        fresh = notes_since(notes, str(baseline.get("created_at", "")))
        corpus, sources = fit_to_budget([baseline_document(baseline, settings.max_doc_chars)], settings.max_doc_chars)
        sources = [*_kept_sources(baseline), *sources,
                   SourceDoc(name=LOG_NAME.format(count=plural(len(shown), "note")), kind="text",
                             chars=sum(len(note_sentence(n)) for n in shown))]
        detail = (f"Profile version {baseline.get('version', '?')} as the baseline · "
                  f"{plural(len(shown), 'progress note')}" + (f" ({left_out} older left out)" if left_out else ""))
        prompt = build_refresh_prompt(goals, corpus, shown, fresh, left_out)
        notes_used = len(shown)
    yield stage("read", "done", detail)

    name = model_name(model, settings.active_model_id)
    label = model_label(name)
    place = "on Amazon Bedrock" if settings.provider == "bedrock" else "on this computer"
    yield stage("model", "active", f"{label} is reading them {place}")
    messages = [{"role": "user", "content": [{"text": prompt}]}]
    draft: ProfileDraft | None = None
    async with aclosing(_draft(model, messages, label)) as drafts:
        async for event in drafts:
            if event["type"] == "output":
                draft = event["output"]
            else:
                yield event
    draft = clean_draft(draft)
    # Checked in code, not left to the model: a finished step is never suggested again, and a new
    # milestone shows up as evidence on the skill it proves.
    opportunities, dropped = drop_completed(draft.opportunities, notes)
    draft = draft.model_copy(update={"opportunities": opportunities, "skills": ensure_evidence(draft.skills, fresh)})
    done_detail = (f"{plural(len(draft.skills), 'skill')} · {plural(len(draft.weaknesses), 'gap')} · "
                   f"{plural(len(draft.opportunities), 'next step')}")
    if dropped:
        done_detail += f" · dropped {plural(len(dropped), 'finished step')}"
    yield stage("model", "done", done_detail)

    checked: list[Any] = []
    async for event in verify_opportunities(draft.opportunities, search=search or WebSearch("off", None),
                                            model=checker, known=f"{goals}\n{corpus}"):
        if event["type"] == "checked":
            checked = event["items"]
        else:
            yield event

    where = "AgentCore Memory" if store.backend == "agentcore" else "local files"
    yield stage("save", "active", f"Saving to {where}")
    version = next_version(await asyncio.to_thread(store.profile_history, user_id))
    profile = CareerProfile(
        **draft.model_dump(exclude={"opportunities"}),
        opportunities=checked,
        user_id=user_id,
        version=version,
        created_at=now_iso(),
        goals=goals,
        sources=sources,
        model=name,
        origin="intake" if baseline is None else "refresh",
        request_id=request_id,
        notes_used=notes_used,
    )
    await asyncio.to_thread(store.save_profile, user_id, profile.model_dump(mode="json"))
    yield stage("save", "done", f"Version {version} saved to {where}")
    yield {"type": "profile", "profile": profile}


def _kept_sources(baseline: dict[str, Any]) -> list[SourceDoc]:
    """The original documents the baseline came from (refresh-made entries are replaced, not stacked)."""
    kept = []
    for source in original_sources(baseline):
        try:
            kept.append(SourceDoc.model_validate(source))
        except ValueError:  # a malformed old entry is not worth failing a refresh over
            continue
    return kept


async def synthesize_profile(**kwargs: Any) -> CareerProfile:
    """Run a whole build and return the saved profile (the JSON API and the tests use this)."""
    async with aclosing(synthesize_events(**kwargs)) as events:
        async for event in events:
            if event["type"] == "profile":
                return event["profile"]
    raise SynthesisError("The build ended without a profile.")
