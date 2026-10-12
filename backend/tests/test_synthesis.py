import asyncio

import pytest
from strands.models.ollama import OllamaModel

import coach.llm as llm_module
import coach.synthesis as synthesis_module
from coach.ingest import Document
from coach.schemas import ProfileDraft, SkillAssessment
from coach.synthesis import SynthesisError, progress_event, synthesize_events, synthesize_profile
from tests.conftest import GOALS, FakeStructuredModel, make_draft

DOCS = [
    Document("resume.md", "file", "Software Engineering Intern at Northwind Analytics. Python ETL."),
    Document("Achievements", "text", "2nd place hackathon."),
]


def run(settings, store, model, user_id="jordan-rivera", **extra):
    return asyncio.run(
        synthesize_profile(user_id=user_id, goals=GOALS, docs=DOCS, settings=settings, store=store, model=model, **extra)
    )


async def collect(events):
    return [event async for event in events]


def test_progress_log_reaches_the_prompt(settings, store):
    with_notes, without = FakeStructuredModel(), FakeStructuredModel()
    notes = [{"kind": "certification", "text": "Passed the AWS Cloud Practitioner exam", "skill": "AWS",
              "created_at": "2026-10-06T22:00:00Z"}]
    run(settings, store, with_notes, notes=notes)
    run(settings, store, without)
    assert "PROGRESS LOG" in with_notes.prompts[0] and "Passed the AWS Cloud Practitioner exam" in with_notes.prompts[0]
    assert "PROGRESS LOG" not in without.prompts[0]


def test_progress_is_read_off_partial_json():
    partial = '{"headline": "Data person", "summary": "x", "target_role": "MLE", "goal_alignment": 40, ' \
              '"skills": [{"name": "Python", "category": "technical"}, {"name": "C\\u002b\\u002b", "cat'
    event = progress_event(partial)
    assert event["section"] == "skills" and event["chars"] == len(partial)
    assert event["skills"] == ["Python", "C++"] and event["opportunities"] == []


def test_an_ollama_build_streams_live_progress(settings, store, monkeypatch):
    answer = make_draft().model_dump_json()
    chunks = [answer[i : i + 40] for i in range(0, len(answer), 40)]

    class FakeAsyncClient:
        def __init__(self, host, **kwargs):
            pass

        async def chat(self, **request):
            assert request["stream"] is True and request["format"]["title"] == "ProfileDraft"

            async def gen():
                for piece in chunks:
                    yield type("Chunk", (), {"message": type("Msg", (), {"content": piece})()})()

            return gen()

    monkeypatch.setattr(llm_module.ollama, "AsyncClient", FakeAsyncClient)
    monkeypatch.setattr(synthesis_module, "PROGRESS_EVERY", 0)
    model = OllamaModel("http://127.0.0.1:11434", model_id="qwen3:1.7b")
    events = asyncio.run(collect(synthesize_events(user_id="jordan-rivera", goals=GOALS, docs=DOCS,
                                                   settings=settings, store=store, model=model)))
    progress = [e for e in events if e["type"] == "progress"]
    assert len(progress) == len(chunks)
    assert progress[-1]["skills"] == ["Python", "SQL", "Mentoring"] and progress[-1]["section"] == "opportunities"
    assert [e["chars"] for e in progress] == sorted(e["chars"] for e in progress)
    assert events[-1]["type"] == "profile" and events[-1]["profile"].model == "qwen3:1.7b"


def test_prompt_carries_goals_and_every_document(settings, store):
    model = FakeStructuredModel()
    run(settings, store, model)
    prompt = model.prompts[0]
    assert GOALS in prompt
    assert "### resume.md" in prompt and "### Achievements" in prompt
    assert "Use ONLY facts" in model.system_prompt


def test_profile_is_saved_with_versions_and_sources(settings, store):
    first = run(settings, store, FakeStructuredModel())
    second = run(settings, store, FakeStructuredModel())
    assert (first.version, second.version) == (1, 2)
    assert [p["version"] for p in store.profile_history("jordan-rivera")] == [1, 2]
    assert [s.name for s in first.sources] == ["resume.md", "Achievements"]
    assert first.goals == GOALS and first.model == "test-model"
    assert first.created_at.endswith("Z")


def test_out_of_range_values_are_clamped_and_duplicates_dropped(settings, store):
    draft = make_draft(
        goal_alignment=140,
        skills=[
            SkillAssessment(name=" Python ", category="technical", level=9, relevance="high",
                            evidence=["a", "a", "b", "c", "d"]),
            SkillAssessment(name="python", category="technical", level=2, relevance="low", evidence=["dup"]),
            SkillAssessment(name="Git", category="tool", level=0, relevance="medium", evidence=["git"]),
        ],
    )
    profile = run(settings, store, FakeStructuredModel(draft))
    assert profile.goal_alignment == 100
    assert [(s.name, s.level) for s in profile.skills] == [("Python", 5), ("Git", 1)]
    assert profile.skills[0].evidence == ["a", "b", "c"]


def test_no_skills_is_an_error_and_nothing_is_saved(settings, store):
    with pytest.raises(SynthesisError):
        run(settings, store, FakeStructuredModel(make_draft(skills=[])))
    assert store.profile_history("jordan-rivera") == []


def test_schema_sent_to_the_model_is_bounded():
    schema = ProfileDraft.model_json_schema()
    assert schema["properties"]["skills"]["maxItems"] == 10
    assert schema["properties"]["goal_alignment"]["maximum"] == 100
    skill = schema["$defs"]["SkillAssessment"]["properties"]
    assert (skill["level"]["minimum"], skill["level"]["maximum"]) == (1, 5)
    assert skill["category"]["enum"] == ["technical", "tool", "domain", "soft"]
    assert skill["evidence"]["maxItems"] == 3
