"""End-to-end against the real model. Opt-in: Bedrock costs about a cent a run, Ollama is slow on CPU.

    COACH_LIVE=1 uv run pytest tests/test_live_model.py -s                       # Claude Haiku 5.5 on Bedrock
    COACH_LIVE=1 COACH_PROVIDER=ollama COACH_MODEL=qwen3:1.7b uv run pytest tests/test_live_model.py -s
"""

import asyncio
import json
import os
import time

import pytest
from fastapi.testclient import TestClient

from coach.api import create_app
from coach.config import DEFAULT_BEDROCK_MODEL, Settings
from coach.llm import build_model, model_status
from coach.memory.local import LocalMemoryStore
from coach.schemas import Opportunity
from coach.search import make_search
from coach.verify import verify_opportunities
from tests.conftest import GOALS, SAMPLE_DIR

pytestmark = pytest.mark.skipif(os.environ.get("COACH_LIVE") != "1", reason="set COACH_LIVE=1 to run")


def live_settings(tmp_path) -> Settings:
    return Settings(
        provider=os.environ.get("COACH_PROVIDER", "bedrock"),
        bedrock_model_id=os.environ.get("COACH_BEDROCK_MODEL", DEFAULT_BEDROCK_MODEL),
        model_id=os.environ.get("COACH_MODEL", "qwen3:4b-instruct"),
        num_ctx=int(os.environ.get("COACH_NUM_CTX", "8192")),
        aws_region=os.environ.get("AWS_REGION", "us-east-1"),
        data_dir=tmp_path,
    )


def test_real_search_and_model_catch_an_invented_certification(tmp_path):
    """The playtest hallucination, checked against the real web and the real model."""
    settings = live_settings(tmp_path)
    steps = [
        Opportunity(title="AWS AI Advocate Certification", action="Earn the AWS AI Advocate certification",
                    timeframe="this quarter", related_skills=["AWS"]),
        Opportunity(title="AWS Certified Cloud Practitioner", action="Pass the AWS Certified Cloud Practitioner exam",
                    timeframe="this month", related_skills=["AWS"]),
        Opportunity(title="Mock interviews", action="Do two live-coding mock interviews each week",
                    timeframe="this week", related_skills=["Interviewing"]),
    ]

    async def run():
        model = build_model(settings, "verify")
        return [e async for e in verify_opportunities(steps, search=make_search(settings), model=model)]

    started = time.perf_counter()
    events = asyncio.run(run())
    if events[-1]["items"][0].verification == "unchecked":  # ddgs answered with nothing (rate limit): retry once
        time.sleep(65)
        events = asyncio.run(run())
    items = events[-1]["items"]
    print(f"\nVERIFY ({settings.active_model_id}) {time.perf_counter() - started:.1f}s")
    for item in items:
        print(f"  {item.verification:10} {item.title!r} <- {item.original_title!r} {item.source_url}")
    assert items[0].verification in {"corrected", "unverified"}, "the invented certification must not pass"
    assert items[1].verification == "verified"
    assert items[2].verification == "general"


def test_real_model_synthesizes_and_coaches(tmp_path):
    settings = live_settings(tmp_path)
    status = model_status(settings)
    assert status["model_ready"], status["detail"]
    store = LocalMemoryStore(tmp_path)
    client = TestClient(create_app(settings=settings, store=store))

    started = time.perf_counter()
    response = client.post(
        "/api/users/jordan-rivera/profile",
        data={"goals": GOALS,
              "entries": json.dumps([{"label": "Achievements",
                                      "text": (SAMPLE_DIR / "jordan-achievements.txt").read_text(encoding="utf-8")}])},
        files=[("files", ("jordan-resume.md", (SAMPLE_DIR / "jordan-resume.md").read_bytes(), "text/markdown"))],
    )
    synth_s = time.perf_counter() - started
    assert response.status_code == 201, response.text
    profile = response.json()["profile"]
    print(f"\nSYNTHESIS ({profile['model']}) {synth_s:.1f}s  alignment={profile['goal_alignment']}  "
          f"target={profile['target_role']}")
    print("skills:", [(s["name"], s["level"], s["relevance"]) for s in profile["skills"]])
    print("weaknesses:", [w["area"] for w in profile["weaknesses"]])
    for o in profile["opportunities"]:
        print(f"  [{o['timeframe']}] {o['verification']:10} {o['title']}: {o['action']}")
    assert len(profile["skills"]) >= 2 and profile["weaknesses"] and profile["opportunities"]

    def chat(message: str) -> dict:
        started = time.perf_counter()
        reply = client.post("/api/users/jordan-rivera/chat", json={"message": message, "session_id": "live-1"})
        events = [json.loads(line[6:]) for line in reply.text.splitlines() if line.startswith("data: ")]
        print(f"CHAT {time.perf_counter() - started:.1f}s  {[e['type'] for e in events if e['type'] != 'delta']}")
        for event in events:
            if event["type"] == "sources":
                print("  sources:", [s["title"] for s in event["items"]])
            if event["type"] == "check":
                print("  flagged:", event["unverified"])
        print(events[-1].get("text") or events[-1])
        return events[-1]

    done = chat("I just passed my AWS Cloud Practitioner exam! What should I focus on next?")
    assert done["type"] == "done" and done["text"]
    assert done["recorded"] and store.list_notes("jordan-rivera"), "progress should have been captured"
    # A second turn replays the first from the session, so this proves the history round-trips.
    done = chat("Which exam did I just tell you I passed?")
    assert done["type"] == "done" and "practitioner" in done["text"].lower()
