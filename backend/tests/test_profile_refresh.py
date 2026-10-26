"""Chat-driven profile refresh: a reported milestone becomes profile version N+1."""

from __future__ import annotations

import asyncio
import dataclasses
import json

import httpx
import pytest
from fastapi.testclient import TestClient

import coach.api as api_module
from coach.api import create_app
from coach.coach_agent import ProgressExtraction, wants_refresh
from coach.memory.agentcore import NOTES_SESSION, AgentCoreMemoryStore
from coach.memory.local import LocalMemoryStore
from coach.progress import bounded_notes, completed_by, drop_completed, REFRESH_MAX_NOTES
from coach.schemas import Opportunity, SkillAssessment, Weakness
from coach.synthesis import next_version
from tests.conftest import GOALS, FakeChecker, FakeExtractor, FakeSearch, ScriptedChatModel, make_draft
from tests.test_api import create_profile, events_of
from tests.test_auth import CLIENT, POOL, USER, FakeKeys, auth
from tests.test_memory import FakeMemoryClient

USER_ID = "jordan-rivera"
SAA = "AWS Certified Solutions Architect - Associate"
EARNED = ProgressExtraction(is_progress=True, kind="certification",
                            text=f"Earned the {SAA} certification", skill="AWS")
CERT_MESSAGE = "I earned the AWS Solutions Architect Associate certification! Please update my profile."

BEFORE = make_draft(
    goal_alignment=42,
    skills=[
        SkillAssessment(name="Python", category="technical", level=4, relevance="high", evidence=["Built a Python ETL job"]),
        SkillAssessment(name="AWS", category="tool", level=2, relevance="high", evidence=["Deployed a Lambda for class"]),
    ],
    weaknesses=[Weakness(area="No cloud certification", why_it_matters="Employers screen for it", severity="high")],
    opportunities=[
        Opportunity(title=SAA, action="Book the SAA-C03 exam and study the official guide", timeframe="this quarter",
                    related_skills=["AWS"]),
        Opportunity(title="Mock interviews", action="Two live-coding mocks per week", timeframe="this week",
                    related_skills=["Interviewing"]),
    ],
)
# The refresh draft is deliberately non-compliant: it repeats the finished certification and leaves the
# certification out of the evidence, so the tests prove the code checks rather than the model's manners.
AFTER = make_draft(
    goal_alignment=58,
    skills=[
        SkillAssessment(name="Python", category="technical", level=4, relevance="high", evidence=["Built a Python ETL job"]),
        SkillAssessment(name="AWS", category="tool", level=3, relevance="high", evidence=["Deployed a Lambda for class"]),
    ],
    weaknesses=[Weakness(area="Model deployment at scale", why_it_matters="Core to ML engineering", severity="medium")],
    opportunities=[
        Opportunity(title=f"Earn the {SAA}", action="Book the exam", timeframe="this quarter", related_skills=["AWS"]),
        Opportunity(title="Serve the review classifier on SageMaker", action="Deploy it behind an endpoint",
                    timeframe="this month", related_skills=["AWS", "Python"]),
    ],
)


class ScriptedSynthesis:
    """Synthesis stand-in: the first call returns BEFORE, later calls AFTER (or fail, or pause)."""

    def __init__(self) -> None:
        self.drafts = [BEFORE]
        self.prompts: list[str] = []
        self.fail = False
        self.delay = 0.0

    async def structured_output(self, output_model, prompt, system_prompt=None, **kwargs):
        self.prompts.append(prompt[0]["content"][0]["text"])
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.fail:
            raise RuntimeError("ThrottlingException: slow down")
        yield {"output": self.drafts.pop(0) if len(self.drafts) > 1 else self.drafts[0]}


@pytest.fixture
def models():
    synthesis = ScriptedSynthesis()
    synthesis.drafts = [BEFORE, AFTER]
    return {"synthesis": synthesis, "verify": FakeChecker(), "extract": FakeExtractor(), "chat": ScriptedChatModel()}


def app_for(settings, store, models, **kwargs):
    return create_app(settings=settings, store=store, model_factory=models.__getitem__, search=FakeSearch(), **kwargs)


@pytest.fixture
def client(settings, store, models, monkeypatch):
    monkeypatch.setattr(api_module, "model_status", lambda s: {"reachable": True, "model_ready": True, "detail": "ok"})
    return TestClient(app_for(settings, store, models))


def chat(client, message, request_id=None, session_id="s1", user=USER_ID, headers=None):
    body = {"message": message, "session_id": session_id, **({"request_id": request_id} if request_id else {})}
    response = client.post(f"/api/users/{user}/chat", json=body, headers=headers)
    return response, events_of(response)


def of_type(events, kind):
    return [e for e in events if e["type"] == kind]


def test_a_certification_becomes_one_note_and_profile_version_n_plus_1(client, models, store):
    assert create_profile(client).status_code == 201
    models["extract"].result = EARNED
    models["chat"].turns = [{"text": "Congratulations! Your profile is updated."}]

    response, events = chat(client, CERT_MESSAGE, request_id="req-cert-0001")

    assert response.status_code == 200
    notes = store.list_notes(USER_ID)
    assert len(notes) == 1 and notes[0]["request_id"] == "req-cert-0001"
    history = store.profile_history(USER_ID)
    assert [p["version"] for p in history] == [1, 2]
    latest = history[-1]
    assert latest["origin"] == "refresh" and latest["request_id"] == "req-cert-0001"
    assert latest["goals"] == history[0]["goals"] == GOALS  # the person's goal is never rewritten
    # the new certification is evidence on the skill it proves (added by code: the draft left it out)
    aws = next(s for s in latest["skills"] if s["name"] == "AWS")
    assert any(SAA in e for e in aws["evidence"])
    # recalculated from the refreshed draft; the finished certification is gone, the replacement stays
    assert latest["goal_alignment"] == 58
    titles = [o["title"] for o in latest["opportunities"]]
    assert not any("Solutions Architect" in t for t in titles)
    assert "Serve the review classifier on SageMaker" in titles
    assert [w["area"] for w in latest["weaknesses"]] == ["Model deployment at scale"]

    kinds = [e["type"] for e in events]
    assert kinds[0] == "memory" and "profile_refresh" in kinds
    assert kinds.index("profile_updated") < kinds.index("delta") and kinds[-1] == "done"
    updated = of_type(events, "profile_updated")[0]
    assert updated["profile"] == latest  # the complete ProfileResponse, ready to replace app state
    assert updated["insights"]["stats"]["goal_alignment"] == 58
    assert [s["version"] for s in updated["insights"]["trends"]["snapshots"]] == [1, 2]
    assert not any("Solutions Architect" in n["label"] for n in updated["insights"]["graph"]["nodes"]
                   if n["type"] == "opportunity")
    assert events[-1]["profile_version"] == 2
    assert client.get(f"/api/users/{USER_ID}/profile").json()["profile"]["version"] == 2

    # the refresh read the baseline profile and the log, and said the documents are not reread
    prompt = models["synthesis"].prompts[-1]
    assert "BASELINE PROFILE" in prompt and "are not kept" in prompt and f"Earned the {SAA}" in prompt
    assert "Deployed a Lambda for class" in prompt
    # the coach replied from version 2 and was told the refresh really happened
    system = models["chat"].calls[0]["system_prompt"]
    assert "PROFILE (version 2" in system and "PROFILE REFRESHED" in system


def test_the_extractor_sees_the_current_next_steps(client, models):
    create_profile(client)
    models["extract"].result = EARNED
    chat(client, "I passed that certification you suggested!", request_id="req-that-0001")
    assert SAA in models["extract"].calls[0] and "MESSAGE:" in models["extract"].calls[0]


def test_ordinary_chat_never_builds_a_profile(client, models, store):
    create_profile(client)
    builds = len(models["synthesis"].prompts)
    for message in ("What should I focus on this month?", "Should I update my LinkedIn profile?"):
        _, events = chat(client, message, request_id=f"req-plain-{len(message):04d}")
        assert not [e for e in events if e["type"].startswith("profile")]
        assert events[-1]["profile_version"] is None
    assert len(models["synthesis"].prompts) == builds
    assert [p["version"] for p in store.profile_history(USER_ID)] == [1]


def test_refresh_hint_only_matches_the_coach_profile():
    assert wants_refresh("Can you refresh my profile?") and wants_refresh("Please update my career profile")
    assert not wants_refresh("Should I update my LinkedIn profile?")
    assert not wants_refresh("What does my profile say about SQL?")


def test_an_explicit_refresh_uses_the_stored_notes(client, models, store):
    create_profile(client)
    store.add_note(USER_ID, {"kind": "certification", "text": f"Earned the {SAA} certification", "skill": "AWS",
                             "created_at": "2999-01-01T00:00:00Z"})  # saved earlier, without a request id

    _, events = chat(client, "Please refresh my profile", request_id="req-refresh-01")

    assert models["extract"].calls == []  # nothing new was reported, so nothing was extracted
    assert len(store.list_notes(USER_ID)) == 1
    assert of_type(events, "profile_updated")[0]["profile"]["version"] == 2
    assert f"Earned the {SAA}" in models["synthesis"].prompts[-1]


def test_explicit_refresh_with_an_empty_log_says_so(client, models, store):
    create_profile(client)
    _, events = chat(client, "Refresh my profile", request_id="req-empty-001")
    failed = of_type(events, "profile_refresh_failed")[0]
    assert failed["code"] == "NO_PROGRESS" and failed["note_saved"] is False
    assert len(store.profile_history(USER_ID)) == 1


@pytest.mark.parametrize("request_id", ["req-retry-0001", None])  # None: an older client, deduped by content
def test_a_retried_request_adds_no_second_note_or_version(client, models, store, request_id):
    create_profile(client)
    models["extract"].result = EARNED
    _, first = chat(client, CERT_MESSAGE, request_id=request_id)
    _, again = chat(client, CERT_MESSAGE, request_id=request_id)

    assert len(store.list_notes(USER_ID)) == 1
    assert [p["version"] for p in store.profile_history(USER_ID)] == [1, 2]
    assert len(models["synthesis"].prompts) == 2  # the intake and one refresh; the retry replayed it
    assert of_type(again, "profile_updated")[0]["profile"] == of_type(first, "profile_updated")[0]["profile"]
    assert len(models["extract"].calls) == 1


def test_a_failed_refresh_keeps_the_note_and_can_be_retried(client, models, store):
    create_profile(client)
    models["extract"].result = EARNED
    models["synthesis"].fail = True

    _, events = chat(client, CERT_MESSAGE, request_id="req-fail-0001")

    assert len(store.list_notes(USER_ID)) == 1
    assert [p["version"] for p in store.profile_history(USER_ID)] == [1]
    assert not of_type(events, "profile_updated")
    failed = of_type(events, "profile_refresh_failed")[0]
    assert failed["note_saved"] is True and failed["retryable"] is True
    assert failed["message"].startswith("Your profile was not refreshed")
    assert events[-1]["type"] == "done" and events[-1]["profile_version"] is None
    assert "PROFILE NOT UPDATED" in models["chat"].calls[0]["system_prompt"]

    models["synthesis"].fail = False  # the same request again: the note is reused, the refresh runs
    _, retry = chat(client, CERT_MESSAGE, request_id="req-fail-0001")
    assert len(store.list_notes(USER_ID)) == 1
    assert of_type(retry, "profile_updated")[0]["profile"]["version"] == 2


def test_concurrent_refreshes_never_share_a_version(settings, store, models, monkeypatch):
    monkeypatch.setattr(api_module, "model_status", lambda s: {"reachable": True, "model_ready": True, "detail": "ok"})
    app = app_for(settings, store, models)
    with TestClient(app) as sync:
        assert create_profile(sync).status_code == 201
    store.add_note(USER_ID, {"kind": "project", "text": "Shipped the classifier API", "skill": "Python",
                             "created_at": "2999-01-01T00:00:00Z"})
    models["synthesis"].delay = 0.05  # long enough for both requests to be mid-build without the lock

    async def both():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
            return await asyncio.gather(*(
                http.post(f"/api/users/{USER_ID}/chat",
                          json={"message": "Refresh my profile", "session_id": "s1", "request_id": f"req-race-{i:04d}"})
                for i in range(3)
            ))

    responses = asyncio.run(both())
    assert all(r.status_code == 200 for r in responses)
    versions = [p["version"] for p in store.profile_history(USER_ID)]
    assert sorted(versions) == [1, 2, 3, 4] and len(set(versions)) == len(versions)


def test_next_version_never_reuses_a_number():
    assert next_version([]) == 1
    assert next_version([{"version": 1}, {"version": 2}]) == 3
    assert next_version([{"version": 1}, {"version": 5}]) == 6  # a gap is never refilled
    assert next_version([{}, {}]) == 3  # very old records without a version still count


def test_nobody_can_refresh_someone_elses_profile(settings, store, models, monkeypatch):
    monkeypatch.setattr(api_module, "model_status", lambda s: {"reachable": True, "model_ready": True, "detail": "ok"})
    hosted = dataclasses.replace(settings, auth="cognito", cognito_pool_id=POOL, cognito_client_id=CLIENT,
                                 daily_builds=2, daily_chats=10)
    client = TestClient(app_for(hosted, store, models, keys=FakeKeys()))
    victim = "u-someone-else"
    store.save_profile(victim, {**BEFORE.model_dump(), "user_id": victim, "version": 1, "created_at": "2026-10-01T00:00:00Z",
                                "goals": GOALS, "sources": [], "model": "m"})
    models["extract"].result = EARNED

    response, _ = chat(client, CERT_MESSAGE, request_id="req-steal-001", user=victim, headers=auth())
    assert response.status_code == 403 and response.json()["error"]["code"] == "FORBIDDEN"
    unsigned, _ = chat(client, CERT_MESSAGE, request_id="req-steal-002", user=victim)
    assert unsigned.status_code == 401
    assert store.list_notes(victim) == [] and len(store.profile_history(victim)) == 1
    assert models["extract"].calls == []

    # the signed-in person's own refresh works, and counts against today's profile builds
    assert create_profile(client, user=USER, headers=auth()).status_code == 201
    _, events = chat(client, CERT_MESSAGE, request_id="req-own-00001", user=USER, headers=auth())
    assert of_type(events, "profile_updated")[0]["profile"]["user_id"] == USER
    _, events = chat(client, "Refresh my profile", request_id="req-own-00002", user=USER, headers=auth())
    assert of_type(events, "profile_refresh_failed")[0]["code"] == "DAILY_LIMIT"
    assert [p["version"] for p in store.profile_history(USER)] == [1, 2]


def test_profiles_and_notes_saved_before_refresh_existed_still_work(client, models, store):
    legacy = {  # no origin, request_id or notes_used; a source without "truncated"
        **{k: v for k, v in BEFORE.model_dump().items()}, "user_id": USER_ID, "version": 1,
        "created_at": "2026-09-01T12:00:00Z", "goals": GOALS, "model": "qwen3:1.7b",
        "sources": [{"name": "jordan-resume.md", "kind": "file", "chars": 1200}],
    }
    store.save_profile(USER_ID, legacy)
    store.add_note(USER_ID, {"kind": "win", "text": "Won the fall hackathon", "skill": "Python",
                             "created_at": "2026-09-10T12:00:00Z"})

    body = client.get(f"/api/users/{USER_ID}/profile").json()
    assert body["profile"]["version"] == 1 and body["insights"]["trends"]["recent_notes"][0]["text"] == "Won the fall hackathon"

    models["synthesis"].drafts = [AFTER]
    _, events = chat(client, "Refresh my profile", request_id="req-legacy-01")
    profile = of_type(events, "profile_updated")[0]["profile"]
    assert profile["version"] == 2 and profile["goals"] == GOALS
    names = [s["name"] for s in profile["sources"]]
    assert names[0] == "jordan-resume.md" and names[1] == "Profile version 1 (baseline)"
    assert store.profile_history(USER_ID)[0] == legacy  # earlier versions are kept untouched
    assert "Won the fall hackathon" in models["synthesis"].prompts[-1]

    _, events = chat(client, "Refresh my profile again", request_id="req-legacy-02")
    sources = [s["name"] for s in of_type(events, "profile_updated")[0]["profile"]["sources"]]
    assert sources.count("jordan-resume.md") == 1 and "Profile version 2 (baseline)" in sources
    assert "Profile version 1 (baseline)" not in sources  # refresh entries are replaced, not stacked


def test_a_request_id_must_be_well_formed(client):
    create_profile(client)
    for bad in ("short", "../../etc", "x" * 101, "id with spaces"):
        response = client.post(f"/api/users/{USER_ID}/chat",
                               json={"message": "hi", "session_id": "s1", "request_id": bad})
        assert response.status_code == 422


# ---- the completed-step check ------------------------------------------------------------------

def note(text, kind="certification"):
    return {"kind": kind, "text": text, "skill": "", "created_at": "2026-10-01T00:00:00Z"}


def test_a_finished_step_is_matched_strongly():
    step = {"title": SAA}
    assert completed_by(step, [note(f"Earned the {SAA} certification")])
    assert completed_by(step, [note("Passed the AWS Solutions Architect Associate exam")])
    assert completed_by({"title": "Deploy the review classifier"},
                        [note("Deployed the review classifier on AWS", kind="project")])
    assert completed_by({"title": "CKA certification"}, [note("Passed the CKA certification")])


def test_near_misses_are_not_treated_as_done():
    assert not completed_by({"title": "AWS Certified Solutions Architect - Professional"},
                            [note(f"Earned the {SAA} certification")])
    assert not completed_by({"title": SAA}, [note(f"Started studying for the {SAA}")])
    assert not completed_by({"title": SAA}, [note(f"Failed the {SAA} exam", kind="setback")])
    assert not completed_by({"title": "Advanced Python course"}, [note("Learned Python decorators", kind="learning")])


def test_drop_completed_keeps_everything_else():
    steps = [Opportunity(title=SAA, action="Book it", timeframe="this quarter", related_skills=["AWS"]),
             Opportunity(title="Mock interviews", action="Weekly", timeframe="this week", related_skills=["Interviewing"])]
    kept, dropped = drop_completed(steps, [note(f"Earned the {SAA}")])
    assert [o.title for o in kept] == ["Mock interviews"] and dropped == [SAA]


def test_the_log_the_model_sees_is_bounded():
    log = [note(f"Finished course {i} " + "x" * 400, kind="learning") for i in range(100)]
    shown, left_out = bounded_notes(log)
    assert 0 < len(shown) <= REFRESH_MAX_NOTES and left_out == 100 - len(shown)
    assert shown[-1]["text"].startswith("Finished course 99")  # the newest are kept
    assert all(len(n["text"]) <= 300 for n in shown)
    assert len(json.dumps(shown)) < 20_000



# ---- AgentCore Memory backend ------------------------------------------------------------------

class PagedMemoryClient(FakeMemoryClient):
    """Honors max_results like the SDK, which stops paging once it has that many events."""

    def list_events(self, memory_id, actor_id, session_id, max_results=100, **kwargs):
        return super().list_events(memory_id, actor_id, session_id)[:max_results]


def test_a_refresh_round_trips_through_agentcore_memory(settings, models, monkeypatch):
    monkeypatch.setattr(api_module, "model_status", lambda s: {"reachable": True, "model_ready": True, "detail": "ok"})
    client_ = PagedMemoryClient()
    store = AgentCoreMemoryStore("CareerCoachMemory-abc123defg", "us-east-1", client=client_)
    # chat turns use a local session file: this test must never reach the real AgentCore service
    monkeypatch.setattr(store, "session_manager", LocalMemoryStore(settings.data_dir).session_manager)
    client_.events[(USER_ID, NOTES_SESSION)] = [{"payload": [{"blob": json.dumps(
        {"kind": "win", "text": "Won the fall hackathon", "skill": "", "created_at": "2026-09-10T12:00:00Z"})}]}]
    client = TestClient(app_for(settings, store, models))
    assert create_profile(client).status_code == 201
    models["extract"].result = EARNED

    _, events = chat(client, CERT_MESSAGE, request_id="req-agentcore1")

    assert of_type(events, "profile_updated")[0]["profile"]["version"] == 2
    assert [p["version"] for p in store.profile_history(USER_ID)] == [1, 2]
    assert [n["text"] for n in store.list_notes(USER_ID)] == ["Won the fall hackathon", f"Earned the {SAA} certification"]


def test_agentcore_reads_past_the_first_hundred_versions():
    client_ = PagedMemoryClient()
    store = AgentCoreMemoryStore("CareerCoachMemory-abc123defg", "us-east-1", client=client_)
    for v in range(1, 151):
        store.save_profile(USER_ID, {"version": v, "created_at": f"2026-{1 + v // 28:02d}-{1 + v % 28:02d}T00:00:00Z"})
    history = store.profile_history(USER_ID)
    assert len(history) == 150 and next_version(history) == 151


def test_agentcore_breaks_same_second_ties_by_version():
    store = AgentCoreMemoryStore("CareerCoachMemory-abc123defg", "us-east-1", client=PagedMemoryClient())
    for v in (1, 2, 3):
        store.save_profile(USER_ID, {"version": v, "created_at": "2026-10-26T17:00:00Z"})
    assert [p["version"] for p in store.profile_history(USER_ID)] == [1, 2, 3]
    assert store.latest_profile(USER_ID)["version"] == 3
