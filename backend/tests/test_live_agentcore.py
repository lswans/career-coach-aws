"""Live checks against a real Amazon Bedrock AgentCore Memory. Opt-in; costs a fraction of a cent.

    uv run python scripts/create_agentcore_memory.py      # once, writes backend/.env
    COACH_LIVE_AGENTCORE=1 uv run pytest tests/test_live_agentcore.py -s

Each run uses a fresh actor id, so runs never see each other's data. Deleting the memory
(--delete) removes everything these tests wrote. The model is a scripted stand-in, so
no Ollama is needed: this file tests the memory, not the model.
"""

from __future__ import annotations

import json
import os
import time
import uuid
from collections.abc import Callable
from typing import Any

import pytest

from coach.coach_agent import build_coach
from coach.config import get_settings
from coach.memory.agentcore import AgentCoreMemoryStore
from tests.conftest import ScriptedChatModel

SETTINGS = get_settings()
pytestmark = pytest.mark.skipif(
    os.environ.get("COACH_LIVE_AGENTCORE") != "1" or not SETTINGS.agentcore_memory_id,
    reason="set COACH_LIVE_AGENTCORE=1 and create a memory first",
)

# COACH_LIVE_ACTOR lets a second run re-check the extraction of an earlier run's chat.
ACTOR = os.environ.get("COACH_LIVE_ACTOR") or f"live-{uuid.uuid4().hex[:8]}"
NOTE = {
    "kind": "certification",
    "text": "Passed the AWS Cloud Practitioner exam",
    "skill": "AWS",
    "created_at": "2026-10-07T15:00:00Z",
}
PROFILE = {
    "version": 1,
    "created_at": "2026-10-07T14:00:00Z",
    "headline": "Data-minded CS student",
    "summary": "Builds Python data tools.",
    "target_role": "Machine Learning Engineer",
    "goal_alignment": 40,
    "goals": "Become a machine learning engineer on a cloud AI team.",
    "skills": [{"name": "Python", "category": "technical", "level": 4, "relevance": "high", "evidence": ["ETL job"]}],
    "weaknesses": [{"area": "Model deployment", "why_it_matters": "Core to the role", "severity": "high"}],
    "opportunities": [
        {"title": "Ship a model", "action": "Deploy it behind an API", "timeframe": "this month", "related_skills": ["AWS"]}
    ],
}


def wait_for(fetch: Callable[[], Any], done: Callable[[Any], bool], timeout: float, every: float = 5) -> tuple[Any, float]:
    """Poll until done(value) or the timeout; return the last value and the seconds waited."""
    started = time.monotonic()
    while True:
        value = fetch()
        if done(value) or time.monotonic() - started > timeout:
            return value, time.monotonic() - started
        time.sleep(every)


@pytest.fixture(scope="module")
def store() -> AgentCoreMemoryStore:
    print(f"\nactor id for this run: {ACTOR}")
    return AgentCoreMemoryStore(SETTINGS.agentcore_memory_id, SETTINGS.aws_region)


def test_profile_snapshots_round_trip(store):
    store.save_profile(ACTOR, PROFILE)
    store.save_profile(ACTOR, {**PROFILE, "version": 2, "created_at": "2026-10-07T16:00:00Z", "goal_alignment": 55})
    history, waited = wait_for(lambda: store.profile_history(ACTOR), lambda h: len(h) >= 2, timeout=30, every=2)
    print(f"profile history after {waited:.1f}s: versions {[p['version'] for p in history]}")
    assert [p["version"] for p in history] == [1, 2]
    assert history[0]["skills"][0]["name"] == "Python"  # nested JSON survives the blob round trip
    assert store.latest_profile(ACTOR)["goal_alignment"] == 55


def test_progress_note_is_listed_and_found_by_meaning(store):
    store.add_note(ACTOR, NOTE)
    assert store.list_notes(ACTOR) == [NOTE]
    hits, waited = wait_for(
        lambda: store.recall(ACTOR, "which certifications have I earned?", top_k=3),
        lambda h: any("Cloud Practitioner" in t for t in h),
        timeout=180,
    )
    print(f"semantic recall after {waited:.0f}s: {hits}")
    assert any("Cloud Practitioner" in t for t in hits)


def test_chat_history_survives_a_new_request(store):
    session = f"s-{uuid.uuid4().hex[:8]}"
    first = ScriptedChatModel([{"text": "Noted: remote roles, and you love Rust."}])
    agent = build_coach(store=store, model=first, user_id=ACTOR, session_id=session, profile=PROFILE, user_message="hi")
    agent("I want a remote internship next summer, and my favorite programming language is Rust.")

    # A new request builds a new Agent for the same session; the session manager restores the turns.
    second = ScriptedChatModel([{"text": "Rust."}])
    question = "What is my favorite language?"
    agent = build_coach(store=store, model=second, user_id=ACTOR, session_id=session, profile=PROFILE, user_message=question)
    agent(question)
    seen = json.dumps(second.calls[-1]["messages"])
    print(f"restored {len(second.calls[-1]['messages'])} messages for session {session}")
    assert "my favorite programming language is Rust" in seen
    assert "Noted: remote roles, and you love Rust." in seen


def test_long_term_memory_extracts_facts_from_the_chat(store):
    """Extraction is asynchronous, so this waits up to 5 minutes for the built-in strategies."""

    def search() -> list[str]:
        texts: list[str] = []
        for namespace in (f"/facts/{ACTOR}/", f"/preferences/{ACTOR}/"):
            for record in store.client.retrieve_memories(
                memory_id=store.memory_id,
                namespace_path=namespace,
                query="favorite programming language and internship preferences",
                top_k=5,
            ):
                texts.append(f"{namespace} {(record.get('content') or {}).get('text', '')}")
        return texts

    found, waited = wait_for(search, lambda f: any("rust" in t.lower() for t in f), timeout=300, every=15)
    print(f"long-term records after {waited:.0f}s:")
    for line in found:
        print(f"  {line}")
    assert any("rust" in t.lower() for t in found)
