"""The chat coach: a Strands Agent with a memory-backed session.

Context-window discipline (the workshop's orchestration theme):
- The system prompt carries a compact profile summary, not the whole profile.
  The agent calls get_profile_section when it needs detail.
- Only the top few relevant long-term memories are recalled per turn.
- A sliding window keeps the last 20 messages; older turns live on in memory.

Progress tracking is routed in code, not left to the model. In testing, a 1.7B model
never chose to call a "record_progress" tool. Instead, a regex gate spots messages that
might report progress, and only those get one small grammar-constrained extraction call.

Web search is routed the same way: WEB_HINT spots questions about certifications, courses,
jobs or events, the API searches while progress is extracted, and the top results go into
the system prompt as numbered sources the reply can cite.
"""

from __future__ import annotations

import json
import re
from typing import Any, Literal

from pydantic import BaseModel
from strands import Agent, tool
from strands.agent.conversation_manager import SlidingWindowConversationManager

from .memory.base import MemoryStore, note_sentence
from .schemas import NoteKind, ProgressNote
from .search import SearchResult
from .synthesis import now_iso

COACH_PROMPT = """You are a warm, direct career coach. You coach one person, using their profile below.

How to coach:
- Keep replies short: 2-5 sentences or a short list. Ask at most one question per reply.
- Ground advice in their profile and goals. Name the specific skill or gap you are working on.
- Suggest concrete next steps with a timeframe.
- When you need detail (evidence, reasons, actions), call get_profile_section instead of guessing.
- Never invent facts about their past, or the name of a certification, course or program.
- Earlier replies may cite web results like [1] from earlier searches you can no longer see. Those
  citations were right. Never take them back, and don't compare them with new search results.

PROFILE (version {version}, created {created})
{summary}

THINGS YOU REMEMBER ABOUT THEM
{memories}{web}{recorded}"""

# Questions about the outside world get a web search first: a model's memory of certifications,
# courses, jobs and events is exactly where it invents things.
WEB_HINT = re.compile(
    r"\b(certif\w*|credential|exam|courses?|bootcamp|class(es)?|programs?|degree|internships?|jobs?|"
    r"salar\w*|hiring|compan(y|ies)|employers?|conferences?|events?|hackathons?|meetups?|scholarships?|"
    r"fellowships?|books?|tutorials?|resources|latest|current|news|20\d\d)\b",
    re.IGNORECASE,
)
# ...but not questions about this conversation ("Which exam did I just tell you I passed?"):
# the web can't answer those, and unrelated results only confuse the reply.
ABOUT_THIS_CHAT = re.compile(
    r"\b(did I|I (just )?(told|said|mentioned)|you (said|told|suggested|mentioned)|remember|earlier|last time)\b",
    re.IGNORECASE,
)

PROGRESS_HINT = re.compile(
    r"\b(pass(ed)?|finish(ed)?|complet(ed|e)|earn(ed)?|got|receiv(ed)?|buil[td]|ship(ped)?|launch(ed)?|"
    r"deploy(ed)?|publish(ed)?|learn(ed|t)?|start(ed)?|land(ed)?|accept(ed)?|offer(ed)?|interview(ed)?|"
    r"present(ed)?|won|fail(ed)?|struggl\w*|reject(ed)?|certified|joined|attended|submitted)\b",
    re.IGNORECASE,
)

EXTRACT_PROMPT = """Decide whether the message reports the writer's OWN career progress: an exam or \
certification, a finished course, a shipped project, an interview, an offer, a new skill, or a setback. \
Questions and plans for the future are NOT progress. If it is progress, restate it as one short past-tense \
sentence and name the main skill involved (empty string if none)."""


class ProgressExtraction(BaseModel):
    is_progress: bool
    kind: NoteKind
    text: str
    skill: str


async def extract_progress(model: Any, message: str) -> ProgressNote | None:
    """Return a note if the message reports progress. Costs zero model calls when the gate says no."""
    if not PROGRESS_HINT.search(message):
        return None
    output = None
    async for event in model.structured_output(
        ProgressExtraction, [{"role": "user", "content": [{"text": message}]}], system_prompt=EXTRACT_PROMPT
    ):
        if "output" in event:
            output = event["output"]
    if output is None or not output.is_progress or not output.text.strip():
        return None
    return ProgressNote(kind=output.kind, text=output.text.strip(), skill=output.skill.strip(), created_at=now_iso())


def summarize_profile(profile: dict[str, Any]) -> str:
    skills = sorted(profile.get("skills", []), key=lambda s: (-int(s.get("level", 0)), s.get("name", "")))
    lines = [
        f"Headline: {profile.get('headline', '')}",
        f"Target role: {profile.get('target_role', '')} (goal alignment {profile.get('goal_alignment', 0)}/100)",
        f"Goals: {profile.get('goals', '')[:400]}",
        "Top skills: "
        + "; ".join(f"{s['name']} {s['level']}/5 ({s['relevance']} relevance)" for s in skills[:6]),
        "Gaps: " + "; ".join(f"{w['area']} ({w['severity']})" for w in profile.get("weaknesses", [])),
        "Opportunities: "
        + "; ".join(f"{o['title']} [{o['timeframe']}]" for o in profile.get("opportunities", [])),
    ]
    return "\n".join(lines)


def web_query(message: str, profile: dict[str, Any]) -> str | None:
    """A search for messages that ask about the outside world, or None. Adds the target role for context."""
    if not WEB_HINT.search(message) or ABOUT_THIS_CHAT.search(message):
        return None
    return f"{message.strip()[:200]} {profile.get('target_role', '')}".strip()


def web_block(query: str, results: list[SearchResult]) -> str:
    if not results:
        return ""
    lines = "\n".join(f"[{i}] {r.title}: {r.snippet[:220]}" for i, r in enumerate(results, 1))
    return (
        f'\n\nWEB SEARCH RESULTS for the latest message only (searched just now for "{query}")\n{lines}\n'
        "Use these for facts about certifications, courses, jobs or events, and cite them like [1]. "
        "Only name a certification or course that appears in these results. "
        "If they don't answer the question, say you aren't sure instead of guessing. "
        "Citation numbers in your earlier replies refer to earlier searches, not to these."
    )


def build_system_prompt(
    profile: dict[str, Any],
    memories: list[str],
    recorded: ProgressNote | None = None,
    web: str = "",
) -> str:
    note = (
        f"\n\nJUST SAVED TO THEIR PROGRESS LOG: {note_sentence(recorded.model_dump())}\n"
        "Congratulate or encourage them briefly, then connect it to their goals."
        if recorded
        else ""
    )
    return COACH_PROMPT.format(
        version=profile.get("version", 1),
        created=str(profile.get("created_at", ""))[:10],
        summary=summarize_profile(profile),
        memories="\n".join(f"- {m}" for m in memories) or "- Nothing yet.",
        web=web,
        recorded=note,
    )


def make_tools(profile: dict[str, Any]) -> list[Any]:
    @tool
    def get_profile_section(section: Literal["skills", "weaknesses", "opportunities", "sources"]) -> str:
        """Fetch one section of the user's career profile in full detail.

        Args:
            section: One of skills, weaknesses, opportunities, sources.
        """
        return json.dumps(profile.get(section, []), ensure_ascii=False)

    return [get_profile_section]


def build_coach(
    *,
    store: MemoryStore,
    model: Any,
    user_id: str,
    session_id: str,
    profile: dict[str, Any],
    user_message: str,
    recorded: ProgressNote | None = None,
    web: str = "",
) -> Agent:
    memories = store.recall(user_id, user_message, top_k=5)
    if recorded:
        memories = [m for m in memories if m != note_sentence(recorded.model_dump())]
    return Agent(
        model=model,
        name="career-coach",
        system_prompt=build_system_prompt(profile, memories, recorded, web),
        tools=make_tools(profile),
        session_manager=store.session_manager(user_id, session_id),
        conversation_manager=SlidingWindowConversationManager(window_size=20),
        callback_handler=None,
    )
