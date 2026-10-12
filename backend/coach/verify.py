"""Check suggested next steps against the web before the profile is saved.

Small models invent plausible names: in playtesting, qwen3:1.7b suggested an "AWS AI Advocate"
certification, which does not exist. So every next step that names a certification, course,
program or event is searched. The model reads the results and says which offering the step
names and which real offering the results show, but CODE makes the call: a name counts as
found only if its distinctive words appear, in order, in a result title. The small model
never gets the final word on what is real.

Outcomes (stored on each opportunity as `verification`):
  verified    the named offering appears in a result; its link is kept as the source
  corrected   it doesn't, but a close real one does; the step is renamed to the real one
  unverified  nothing matching was found; the UI says to check it before acting
  general     general advice that names nothing specific, or a name from the person's own
              documents (their project or course), so there is nothing to check
  unchecked   web search was off, unreachable, or returned nothing (an empty answer usually
              means the search engine refused, so it is never read as "invented")
"""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import AsyncIterator
from typing import Any

from pydantic import BaseModel, Field

from .schemas import CheckedOpportunity, Opportunity
from .search import SearchResult, SearchUnavailable, WebSearch

logger = logging.getLogger(__name__)

# Steps worth a search name a specific offering. Everything else is general advice.
OFFERING_HINT = re.compile(
    r"\b(certif\w*|credential|exam|courses?|bootcamp|programs?|programme|specializ\w*|nanodegree|degree|"
    r"conferences?|summit|hackathons?|fellowship|scholarship|workshops?|badge|training|classes|mooc|"
    r"coursera|udemy|edx|udacity)\b",
    re.IGNORECASE,
)
# Credentials are the riskiest invention, so they are checked even if the model says "nothing named".
CREDENTIAL_HINT = re.compile(r"\b(certif\w*|credential|exam)\b", re.IGNORECASE)
LEADING_VERB = re.compile(
    r"^(take|complete|earn|get|pass|finish|enroll in|enrol in|join|attend|start|study for|prepare for|obtain|pursue)\s+"
    r"(the\s+|an?\s+)?",
    re.IGNORECASE,
)
# Words too common to tell two offerings apart. Matching ignores them on both sides.
GENERIC = frozenset(
    "a an and the of for in on to with by from your my new official online free level "
    "aws amazon web services certification certifications certified certificate certificates cert "
    "course courses program programs programme exam exams training class classes "
    "take earn get pass complete finish consider try explore pursue study start enroll join attend next then".split()
)
# A result can only vouch for a name if it looks like an offering page: playtesting matched the
# generic "Cloud Computing Course" to Wikipedia's "Cloud Computing (horse)", a racehorse.
OFFERING_PAGE = re.compile(
    OFFERING_HINT.pattern
    + r"|\b(skill ?builder|datacamp|pluralsight|linkedin learning|freecodecamp|codecademy|khan academy)\b",
    re.IGNORECASE,
)
LEARNING_SITE = re.compile(
    r"https?://(?:[\w-]+\.)*(?:[\w-]+\.edu|coursera\.org|edx\.org|udemy\.com|udacity\.com|credly\.com|"
    r"comptia\.org|isc2\.org|skillbuilder\.aws)(?:[/:?#]|$)",
    re.IGNORECASE,
)
OFFERING_PATH = re.compile(
    r"https?://[^/]+/(?:[^?#]*/)?(?:certifications?|training|courses?|learn|programs?|specializations?|"
    r"professional-certificates|credentials)(?:[/?#.-]|$)",
    re.IGNORECASE,
)
# Threads where people ask whether something exists can't prove that it does.
DISCUSSION_SITE = re.compile(r"https?://(?:[\w-]+\.)*(?:reddit\.com|quora\.com|stackexchange\.com|stackoverflow\.com)/",
                             re.IGNORECASE)


def offering_like(result: SearchResult) -> bool:
    if DISCUSSION_SITE.match(result.url):
        return False
    return bool(OFFERING_PAGE.search(result.title) or LEARNING_SITE.match(result.url) or OFFERING_PATH.match(result.url))

CHECK_PROMPT = """You check one suggested career step against web search results.
named: copy the exact name of the specific certification, course, program or event that the step \
tells the person to do. A topic is not a name: "Take a cloud computing course" names nothing, so use "". \
"Earn the Google Data Analytics Certificate" names "Google Data Analytics Certificate".
real_match: the name of the real offering in the search results that best matches the named one, \
copied from a result title. Use "" if nothing is named or no result fits."""


class OfferingCheck(BaseModel):
    named: str = Field(description="Exact name of the specific offering the step names, or empty")
    real_match: str = Field(description="Closest real offering, copied from a result title, or empty")


def words(text: str) -> list[str]:
    return [w for w in re.findall(r"[a-z0-9+#]+", text.lower()) if w not in GENERIC]


def has_run(have: list[str], want: list[str]) -> bool:
    """True if `want` appears in `have` as adjacent words, in order."""
    return bool(want) and any(have[i : i + len(want)] == want for i in range(len(have) - len(want) + 1))


def find_in_titles(name: str, results: list[SearchResult]) -> SearchResult | None:
    """The first offering-like result whose title has the name's distinctive words, in order and adjacent."""
    want = words(name)
    return next((r for r in results if offering_like(r) and has_run(words(r.title), want)), None)


def fallback_name(opportunity: Opportunity) -> str:
    return LEADING_VERB.sub("", opportunity.title.strip()).strip()


def swap(text: str, old: str, new: str) -> str:
    return re.sub(re.escape(old), new.replace("\\", r"\\"), text, flags=re.IGNORECASE) if old else text


def search_query(opportunity: Opportunity) -> str:
    """The title usually carries the offering's name; fall back to the action when it doesn't."""
    if OFFERING_HINT.search(opportunity.title):
        return opportunity.title
    return f"{opportunity.title} {opportunity.action}"[:200]


def mark(opportunity: Opportunity, verification: str, source: SearchResult | None = None, **changes: str) -> CheckedOpportunity:
    base = opportunity.model_dump(include=set(Opportunity.model_fields))
    return CheckedOpportunity(
        **{**base, **changes},
        verification=verification,
        source_title=source.title if source else "",
        source_url=source.url if source else "",
    )


async def ask(model: Any, opportunity: Opportunity, results: list[SearchResult]) -> OfferingCheck:
    listing = "\n".join(f"[{i}] {r.title}: {r.snippet[:160]}" for i, r in enumerate(results, 1))
    prompt = f"STEP: {opportunity.title}: {opportunity.action}\n\nSEARCH RESULTS:\n{listing or '(none)'}"
    output = None
    async for event in model.structured_output(
        OfferingCheck, [{"role": "user", "content": [{"text": prompt}]}], system_prompt=CHECK_PROMPT
    ):
        if "output" in event:
            output = event["output"]
    return output or OfferingCheck(named="", real_match="")


def judge(opportunity: Opportunity, results: list[SearchResult], check: OfferingCheck, known: str = "") -> CheckedOpportunity:
    """Turn the model's reading of the results into an outcome, using only what the results show.

    `known` is the person's own goals and documents. A name found there that the web doesn't show
    is theirs (in playtesting, the student's "Course Review Classifier" project tripped the course
    detector), so it is neither flagged nor "corrected" to some real course.
    """
    text = f"{opportunity.title}: {opportunity.action}"
    named = check.named.strip()
    if not has_run(words(text), words(named)):  # the model swapped in a name the step never used
        named = ""
    if not named and CREDENTIAL_HINT.search(text):
        named = fallback_name(opportunity)
    if not words(named):
        return mark(opportunity, "general")
    source = find_in_titles(named, results)
    if source:
        return mark(opportunity, "verified", source)
    if has_run(words(known), words(named)):
        return mark(opportunity, "general")
    real = check.real_match.strip()
    source = find_in_titles(real, results) if words(real) != words(named) else None
    if source and has_run(words(named), words(real)):  # e.g. the real name plus an exam code
        return mark(opportunity, "verified", source)
    if source:
        return mark(
            opportunity, "corrected", source,
            title=real, action=swap(opportunity.action, named, real), original_title=opportunity.title,
        )
    return mark(opportunity, "unverified")


def from_their_documents(opportunity: Opportunity, known: str) -> bool:
    """True when every course or program word in the step sits inside a name from the person's own
    documents, such as their "Course Review Classifier" project. That step needs no web check."""
    text = f"{opportunity.title}: {opportunity.action}"
    have = words(known)
    for span in NAME_IN_REPLY.findall(text):
        if OFFERING_HINT.search(span) and has_run(have, words(span)):
            text = text.replace(span, " ")
    return not OFFERING_HINT.search(text)


async def verify_opportunities(
    opportunities: list[Opportunity], *, search: WebSearch, model: Any, known: str = ""
) -> AsyncIterator[dict[str, Any]]:
    """Yields progress events for the build screen, then {"type": "checked", "items": [...]}.
    `known` is the person's goals and documents (see judge)."""
    todo = [i for i, o in enumerate(opportunities) if OFFERING_HINT.search(f"{o.title} {o.action}")]
    checked: dict[int, CheckedOpportunity] = {
        i: mark(o, "general") for i, o in enumerate(opportunities) if i not in todo
    }
    if not todo:
        yield stage("skipped", "None of the next steps name a course or certification to check")
    elif not search.enabled:
        checked.update({i: mark(opportunities[i], "unchecked") for i in todo})
        yield stage("skipped", "Web search is off (COACH_WEB_SEARCH=off)")
    else:
        yield stage("active", f"Searching the web for {len(todo)} named next step{'s' * (len(todo) != 1)}")
        found = await asyncio.gather(
            *(search.asearch(search_query(opportunities[i]), 5) for i in todo), return_exceptions=True
        )
        for n, (i, results) in enumerate(zip(todo, found), 1):
            opportunity = opportunities[i]
            if isinstance(results, SearchUnavailable) or results == []:  # no results: couldn't check, not "invented"
                checked[i] = mark(opportunity, "general" if from_their_documents(opportunity, known) else "unchecked")
                continue
            if isinstance(results, BaseException):
                raise results
            yield stage("active", f"Checking {n} of {len(todo)}: {opportunity.title}")
            try:
                check = await ask(model, opportunity, results)
            except Exception:  # noqa: BLE001 - bad JSON or a model hiccup: judge on the step's own text
                logger.warning("next-step check failed for %r", opportunity.title, exc_info=True)
                check = OfferingCheck(named="", real_match="")
            checked[i] = judge(opportunity, results, check, known)
        labels = {"verified": "verified", "corrected": "corrected", "unverified": "not found online",
                  "unchecked": "not checked (search unavailable)"}
        counts = {k: sum(1 for c in checked.values() if c.verification == k) for k in labels}
        yield stage("done", ", ".join(f"{v} {labels[k]}" for k, v in counts.items() if v))
    yield {"type": "checked", "items": [checked[i] for i in range(len(opportunities))]}


def stage(state: str, detail: str) -> dict[str, Any]:
    return {"type": "stage", "stage": "verify", "state": state, "detail": detail}


# ---- the same check for chat replies ------------------------------------------------------------
# Only credentials are checked in replies: they are what small models invent, and real ones are
# well indexed. Course and program names are too loose to judge without false alarms.
# A name is a capitalized run of words ("AWS Certified Security - Specialty"), joined only by
# and/of/for/&/-, optionally followed by a lowercase "exam", "certification" or "certificate".
_WORD = r"[A-Z0-9][\w+#./'’]*"
NAME_IN_REPLY = re.compile(
    rf"{_WORD}(?:\s+(?:{_WORD}|(?:and|of|for|&|-|–)(?=\s+{_WORD})))*(?:\s+(?:certification|certificate|exam))?"
)
REPLY_CHECK_SECS = 6  # the reply is already on screen; don't hold the chat box longer than this


def names_in_reply(text: str) -> list[str]:
    """Certification names a coach reply mentions, at most three."""
    names: list[str] = []
    for span in NAME_IN_REPLY.findall(text):
        span = span.rstrip(".,;:!?)'’")
        if len(span.split()) >= 2 and CREDENTIAL_HINT.search(span) and words(span) and span not in names:
            names.append(span)
    return names[:3]


async def unbacked_names(
    reply: str, message: str, sources: list[SearchResult], search: WebSearch, known: str = ""
) -> list[str]:
    """Certification names in a reply that no web result backs up, so the UI can say "check this".

    A name is backed if its distinctive words appear, in order, in a source the coach was given,
    or in an offering-like result title from a fresh search. Names the person typed, or that come
    from their own goals and evidence (`known`), are skipped: they are theirs, not the model's.
    If a fresh search can't run in time, the name is not flagged: "couldn't check" is not "invented".
    """
    pending = [
        name for name in names_in_reply(reply)
        if not has_run(words(f"{message} {known}"), words(name))
        and not any(has_run(words(f"{s.title} {s.snippet}"), words(name)) for s in sources)
    ]
    if not pending or not search.enabled:
        return []
    try:
        found = await asyncio.wait_for(
            asyncio.gather(*(search.asearch(name, 5) for name in pending), return_exceptions=True), REPLY_CHECK_SECS
        )
    except TimeoutError:
        return []
    # No results at all usually means the search engine quietly refused, not that the name is invented.
    return [name for name, results in zip(pending, found)
            if not isinstance(results, BaseException) and results and not find_in_titles(name, results)]
