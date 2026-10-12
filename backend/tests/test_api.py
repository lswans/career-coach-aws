import json

import pytest
from botocore.exceptions import ClientError
from fastapi.testclient import TestClient

import coach.api as api_module
from coach.api import create_app
from coach.coach_agent import ProgressExtraction
from coach.search import SearchResult
from tests.conftest import (GOALS, SAMPLE_DIR, FakeChecker, FakeExtractor, FakeSearch, FakeStructuredModel,
                            ScriptedChatModel)

RESUME = (SAMPLE_DIR / "jordan-resume.md").read_bytes()
ENTRIES = json.dumps([{"label": "Achievements", "text": "2nd place at the Fall Hackathon; Dean's List."}])
PASSED = ProgressExtraction(is_progress=True, kind="certification",
                            text="Passed the AWS Cloud Practitioner exam", skill="AWS")
CERT_RESULTS = [SearchResult("AWS Certified Machine Learning Engineer - Associate", "https://aws.amazon.com/certification/x/",
                             "Validate skills in building ML solutions on AWS.")]


@pytest.fixture
def chat_model():
    return ScriptedChatModel()


@pytest.fixture
def extractor():
    return FakeExtractor()


@pytest.fixture
def search():
    return FakeSearch({"certification": CERT_RESULTS})


@pytest.fixture
def client(settings, store, chat_model, extractor, search, monkeypatch):
    monkeypatch.setattr(api_module, "model_status",
                        lambda s: {"reachable": True, "model_ready": True, "detail": "ok"})
    models = {"synthesis": FakeStructuredModel(), "verify": FakeChecker(), "extract": extractor, "chat": chat_model}
    return TestClient(create_app(settings=settings, store=store, model_factory=models.__getitem__, search=search))


def create_profile(client, user="jordan-rivera", headers=None):
    return client.post(f"/api/users/{user}/profile",
                       data={"goals": GOALS, "entries": ENTRIES},
                       files=[("files", ("jordan-resume.md", RESUME, "text/markdown"))],
                       headers=headers)


def events_of(response):
    return [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]


def chat(client, message, session_id="s1"):
    response = client.post("/api/users/jordan-rivera/chat", json={"message": message, "session_id": session_id})
    return response, events_of(response)


def test_health_publishes_the_intake_rules(client):
    body = client.get("/api/health").json()
    assert body["memory_backend"] == "local" and body["provider"] == "bedrock"
    assert (body["model"], body["model_id"]) == ("test-model", "test-model")
    assert body["web_search"] == "fake"
    assert body["rules"]["min_goal_chars"] == 200
    assert body["model_status"] == {"reachable": True, "model_ready": True, "detail": "ok"}


def test_health_names_the_claude_model_readably(settings, store, search, monkeypatch):
    monkeypatch.setattr(api_module, "model_status", lambda s: {
        "model": "us.anthropic.claude-haiku-5-5", "reachable": True, "model_ready": False,
        "detail": "Anthropic asks for a one-time use-case form"})
    body = TestClient(create_app(settings=settings, store=store, search=search)).get("/api/health").json()
    assert (body["model"], body["model_id"]) == ("Claude Haiku 5.5", "us.anthropic.claude-haiku-5-5")
    assert body["model_status"]["model_ready"] is False and "use-case form" in body["model_status"]["detail"]


def test_synthesis_is_blocked_without_documents_and_real_goals(client):
    response = client.post("/api/users/jordan-rivera/profile", data={"goals": "I want a job."})
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "VALIDATION_ERROR"
    assert set(error["fields"]) == {"documents", "goals"}


def test_unreadable_upload_is_reported_per_file(client):
    response = client.post("/api/users/jordan-rivera/profile", data={"goals": GOALS},
                           files=[("files", ("selfie.png", b"\x89PNG", "image/png"))])
    assert response.status_code == 422
    assert "selfie.png" in response.json()["error"]["fields"]["files"]


def test_profile_is_created_and_readable(client):
    assert client.get("/api/users/jordan-rivera/profile").status_code == 404
    response = create_profile(client)
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["profile"]["version"] == 1
    assert [s["name"] for s in body["profile"]["sources"]] == ["jordan-resume.md", "Achievements"]
    assert body["insights"]["stats"]["skills_total"] == 3
    again = client.get("/api/users/jordan-rivera/profile").json()
    assert again["profile"]["headline"] == body["profile"]["headline"]
    assert client.get("/api/users/jordan-rivera/insights").json()["graph"]["nodes"][0]["id"] == "you"


def test_bad_user_id_is_rejected(client):
    assert client.get("/api/users/Bad_User!/profile").status_code == 400


def test_build_streams_each_stage_then_the_profile(client):
    response = create_profile(client, headers={"Accept": "text/event-stream"})
    assert response.status_code == 200 and response.headers["content-type"].startswith("text/event-stream")
    events = events_of(response)
    stages = [(e["stage"], e["state"]) for e in events if e["type"] == "stage"]
    assert stages == [("read", "done"), ("model", "active"), ("model", "done"), ("verify", "skipped"),
                      ("save", "active"), ("save", "done")]
    assert events[0]["detail"].startswith("2 documents")
    done = events[-1]
    assert done["type"] == "done" and done["profile"]["version"] == 1
    assert [o["verification"] for o in done["profile"]["opportunities"]] == ["general", "general"]
    assert done["insights"]["stats"]["skills_total"] == 3


def test_streamed_intake_errors_are_still_plain_422s(client):
    response = client.post("/api/users/jordan-rivera/profile", data={"goals": "short"},
                           headers={"Accept": "text/event-stream"})
    assert response.status_code == 422 and response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_a_failure_mid_stream_arrives_as_an_error_event(settings, store, search, monkeypatch):
    monkeypatch.setattr(api_module, "model_status", lambda s: {"reachable": True, "model_ready": True, "detail": "ok"})

    class NoClaudeYet:
        async def structured_output(self, *args, **kwargs):
            raise ClientError({"Error": {"Code": "ResourceNotFoundException", "Message":
                               "Model use case details have not been submitted for this account."}}, "ConverseStream")
            yield  # pragma: no cover

    app = create_app(settings=settings, store=store, search=search,
                     model_factory=lambda purpose: NoClaudeYet())
    events = events_of(create_profile(TestClient(app), headers={"Accept": "text/event-stream"}))
    assert events[-1]["type"] == "error" and events[-1]["code"] == "MODEL_UNAVAILABLE"
    assert "one-time use-case form" in events[-1]["message"]
    assert store.profile_history("jordan-rivera") == []


def test_fact_questions_are_searched_and_cited(client, chat_model, search):
    create_profile(client)
    chat_model.turns = [{"text": "Go for the AWS Certified Machine Learning Engineer - Associate [1]."}]
    _, events = chat(client, "Which AWS certification should I take next?")
    assert {"type": "sources", "items": [{"title": CERT_RESULTS[0].title, "url": CERT_RESULTS[0].url}]} in events
    assert search.queries[-1] == "Which AWS certification should I take next? Machine Learning Engineer"
    prompt = chat_model.calls[0]["system_prompt"]
    assert "WEB SEARCH RESULTS" in prompt and "[1] AWS Certified Machine Learning Engineer - Associate" in prompt
    assert not any(e["type"] == "check" for e in events)  # the named cert is in the sources
    assert events[-1]["type"] == "done"


def test_a_reply_naming_an_unknown_certification_is_flagged(client, chat_model, search):
    create_profile(client)
    search.results["Quantum"] = CERT_RESULTS  # a real search returns related certs, none with this name
    chat_model.turns = [{"text": "Take the AWS Certified Quantum Cloud Wizard exam next."}]
    _, events = chat(client, "What should I do after the Cloud Practitioner exam?")
    assert events[-2] == {"type": "check", "unverified": ["AWS Certified Quantum Cloud Wizard exam"]}
    assert events[-1]["type"] == "done"


def test_chat_still_answers_when_search_is_down(client, chat_model, search):
    create_profile(client)
    search.down = True
    chat_model.turns = [{"text": "I'm not sure which one; check aws.amazon.com/certification."}]
    _, events = chat(client, "Which AWS certification should I take next?")
    assert not any(e["type"] == "sources" for e in events)
    assert "WEB SEARCH RESULTS" not in chat_model.calls[0]["system_prompt"]
    assert events[-1]["type"] == "done"


def test_chat_requires_a_profile(client):
    response = client.post("/api/users/jordan-rivera/chat", json={"message": "hi", "session_id": "s1"})
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "PROFILE_REQUIRED"


def test_reported_progress_is_saved_before_the_coach_replies(client, chat_model, extractor, store):
    create_profile(client)
    extractor.result = PASSED
    chat_model.turns = [{"text": "Congratulations! Next, deploy your classifier on AWS this month."}]
    response, events = chat(client, "I passed my AWS Cloud Practitioner exam!")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert events[0] == {"type": "memory", "note": store.list_notes("jordan-rivera")[0]}
    assert events[0]["note"]["kind"] == "certification" and events[0]["note"]["skill"] == "AWS"
    assert "".join(e["text"] for e in events if e["type"] == "delta").startswith("Congratulations!")
    done = events[-1]
    assert done["type"] == "done" and "deploy your classifier" in done["text"]
    prompt = chat_model.calls[0]["system_prompt"]
    assert "Machine Learning Engineer" in prompt and "JUST SAVED" in prompt
    assert chat_model.calls[0]["tools"] == ["get_profile_section"]
    assert client.get("/api/users/jordan-rivera/insights").json()["trends"]["momentum_14d"] == 1


def test_questions_skip_extraction_entirely(client, chat_model, extractor, store):
    create_profile(client)
    chat_model.turns = [{"text": "Start with deployment."}]
    _, events = chat(client, "What should I focus on this month?")
    assert extractor.calls == []  # the regex gate saved a model call
    assert [e["type"] for e in events][-1] == "done" and not any(e["type"] == "memory" for e in events)
    assert store.list_notes("jordan-rivera") == []


def test_extractor_can_veto_a_false_alarm(client, chat_model, extractor, store):
    create_profile(client)
    extractor.result = ProgressExtraction(is_progress=False, kind="win", text="", skill="")
    chat_model.turns = [{"text": "Sure."}]
    chat(client, "Should I start a project or learn Docker first?")
    assert len(extractor.calls) == 1 and store.list_notes("jordan-rivera") == []


def test_coach_can_look_up_profile_detail_with_a_tool(client, chat_model):
    create_profile(client)
    chat_model.turns = [
        {"tool": "get_profile_section", "input": {"section": "weaknesses"}},
        {"text": "Your biggest gap is model deployment."},
    ]
    _, events = chat(client, "What is my biggest gap?")
    assert {"type": "tool", "name": "get_profile_section"} in events
    assert "Model deployment on AWS" in json.dumps(chat_model.calls[1]["messages"])  # the tool result
    assert events[-1]["tools"] == ["get_profile_section"]


def test_chat_history_persists_within_a_session(client, chat_model):
    create_profile(client)
    chat_model.turns = [{"text": "Noted."}, {"text": "You said interviews make you nervous."}]
    chat(client, "Interviews make me nervous", session_id="s9")
    chat(client, "What did I say?", session_id="s9")
    seen = json.dumps(chat_model.calls[-1]["messages"])
    assert "Interviews make me nervous" in seen and "What did I say?" in seen


def test_cors_preflight_allows_local_ui_and_private_network(client):
    response = client.options("/api/users/jordan-rivera/chat", headers={
        "Origin": "http://localhost:5173",
        "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "content-type",
        "Access-Control-Request-Private-Network": "true",
    })
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"
    assert response.headers.get("access-control-allow-private-network") == "true"
    blocked = client.options("/api/health", headers={"Origin": "https://evil.example",
                                                     "Access-Control-Request-Method": "GET"})
    assert blocked.status_code == 400



def test_questions_about_the_chat_itself_are_not_searched(client, chat_model, search):
    """Seen live: "Which exam did I just tell you I passed?" fetched unrelated results, and the reply
    then took back its earlier, correct citations."""
    create_profile(client)
    chat_model.turns = [{"text": "You passed the AWS Cloud Practitioner exam."}]
    _, events = chat(client, "Which exam did I just tell you I passed?")
    assert not any("tell you" in q for q in search.queries) and not any(e["type"] == "sources" for e in events)
    assert "WEB SEARCH RESULTS" not in chat_model.calls[0]["system_prompt"]
