import json
from datetime import datetime

import pytest
from strands.session.file_session_manager import FileSessionManager

from coach.memory.agentcore import NOTES_SESSION, PROFILE_SESSION, AgentCoreMemoryStore
from coach.memory.local import LocalMemoryStore

NOTE_A = {"kind": "win", "text": "Deployed my Flask API to AWS", "skill": "AWS", "created_at": "2026-10-01T09:00:00Z"}
NOTE_B = {"kind": "learning", "text": "Finished a pandas tutorial", "skill": "pandas", "created_at": "2026-10-02T09:00:00Z"}


def test_local_profiles_come_back_oldest_first(store):
    store.save_profile("jordan", {"version": 1})
    store.save_profile("jordan", {"version": 2})
    assert [p["version"] for p in store.profile_history("jordan")] == [1, 2]
    assert store.latest_profile("jordan") == {"version": 2}
    assert store.latest_profile("someone-else") is None


def test_local_recall_prefers_keyword_matches_then_recent(store):
    store.add_note("jordan", NOTE_A)
    store.add_note("jordan", NOTE_B)
    assert store.recall("jordan", "How should I use AWS next?", top_k=1) == [
        "2026-10-01 Win: Deployed my Flask API to AWS (skill: AWS)"
    ]
    assert len(store.recall("jordan", "zzz unrelated", top_k=5)) == 2


def test_local_session_manager_is_file_based(store, settings):
    manager = store.session_manager("jordan", "chat-1")
    assert isinstance(manager, FileSessionManager)
    assert (settings.data_dir / "jordan" / "sessions").exists()


class FakeDataPlane:
    def __init__(self):
        self.batches = []

    def batch_create_memory_records(self, **kwargs):
        self.batches.append(kwargs)
        return {"successfulRecords": [{"requestIdentifier": kwargs["records"][0]["requestIdentifier"]}]}


def java_style(value):
    """How the real service hands back a blob that was sent as a dict: not JSON."""
    if isinstance(value, dict):
        return "{" + ", ".join(f"{k}={java_style(v)}" for k, v in value.items()) + "}"
    if isinstance(value, list):
        return "[" + ", ".join(java_style(v) for v in value) + "]"
    return str(value)


class FakeMemoryClient:
    """Mimics the bedrock_agentcore MemoryClient methods the store uses, quirks included."""

    def __init__(self):
        self.events = {}
        self.gmdp_client = FakeDataPlane()
        self.retrievals = []

    def create_blob_event(self, memory_id, actor_id, session_id, blob_data, **kwargs):
        stored = blob_data if isinstance(blob_data, str) else java_style(blob_data)
        self.events.setdefault((actor_id, session_id), []).append({"payload": [{"blob": stored}]})
        return {"eventId": str(len(self.events))}

    def list_events(self, memory_id, actor_id, session_id, max_results=100, **kwargs):
        return list(reversed(self.events.get((actor_id, session_id), [])))  # newest first, like the service

    def retrieve_memories(self, memory_id, namespace=None, query=None, namespace_path=None, top_k=3, **kwargs):
        self.retrievals.append({"namespace_path": namespace_path, "query": query, "top_k": top_k})
        return [{"content": {"text": "2026-10-01 Win: Deployed my Flask API to AWS (skill: AWS)"}, "score": 0.81},
                {"content": {"text": "  "}, "score": 0.5}]


def make_agentcore():
    client = FakeMemoryClient()
    return AgentCoreMemoryStore("CareerCoachMemory-abc123defg", "us-east-1", client=client), client


def test_agentcore_profiles_are_blob_events_sorted_by_time():
    store, client = make_agentcore()
    store.save_profile("jordan", {"version": 2, "created_at": "2026-10-02T00:00:00Z"})
    store.save_profile("jordan", {"version": 1, "created_at": "2026-10-01T00:00:00Z", "skills": [{"name": "Python"}]})
    sent = client.events[("jordan", PROFILE_SESSION)][0]["payload"][0]["blob"]
    assert isinstance(sent, str) and json.loads(sent)["version"] == 2  # sent as JSON text, not a dict
    # a blob written as a dict by an older build comes back unparseable and is skipped
    client.events[("jordan", PROFILE_SESSION)].append({"payload": [{"blob": "{version=3, created_at=2026-10-03}"}]})
    history = store.profile_history("jordan")
    assert [p["version"] for p in history] == [1, 2]
    assert history[0]["skills"] == [{"name": "Python"}]
    assert store.latest_profile("jordan")["version"] == 2


def test_agentcore_note_is_listed_and_written_to_long_term_memory():
    store, client = make_agentcore()
    store.add_note("jordan", NOTE_A)
    assert store.list_notes("jordan") == [NOTE_A]
    assert ("jordan", NOTES_SESSION) in client.events
    batch = client.gmdp_client.batches[0]
    assert batch["memoryId"] == "CareerCoachMemory-abc123defg"
    record = batch["records"][0]
    assert record["namespaces"] == ["/career/jordan/progress/"]
    assert record["content"]["text"] == "2026-10-01 Win: Deployed my Flask API to AWS (skill: AWS)"
    assert isinstance(record["timestamp"], datetime) and record["timestamp"].tzinfo is not None
    assert len(record["requestIdentifier"]) == 32


def test_agentcore_recall_searches_the_progress_namespace():
    store, client = make_agentcore()
    assert store.recall("jordan", "AWS plans", top_k=4) == ["2026-10-01 Win: Deployed my Flask API to AWS (skill: AWS)"]
    assert client.retrievals == [{"namespace_path": "/career/jordan/progress/", "query": "AWS plans", "top_k": 4}]



def test_expired_credentials_become_a_fix_it_message():
    from botocore.exceptions import ClientError

    from coach.memory.base import MemoryUnavailable

    store, client = make_agentcore()

    def expired(**kwargs):
        raise ClientError({"Error": {"Code": "ExpiredTokenException", "Message": "token expired"}}, "ListEvents")

    client.list_events = expired
    with pytest.raises(MemoryUnavailable, match="aws login"):
        store.profile_history("jordan")


def test_a_failed_long_term_record_does_not_break_the_note(caplog):
    store, client = make_agentcore()
    client.gmdp_client.batch_create_memory_records = lambda **kw: {
        "successfulRecords": [], "failedRecords": [{"requestIdentifier": "x", "errorMessage": "bad namespace"}]
    }
    store.add_note("jordan", NOTE_A)
    assert store.list_notes("jordan") == [NOTE_A]
    assert "bad namespace" in caplog.text


def test_api_turns_memory_outages_into_503(settings):
    from fastapi.testclient import TestClient

    import coach.api as api_module
    from coach.memory.base import MemoryUnavailable

    class DownStore(LocalMemoryStore):
        def profile_history(self, user_id):
            raise MemoryUnavailable("AgentCore Memory needs working AWS credentials. Run 'aws login', then restart the backend.")

    api_module_status = api_module.model_status
    try:
        api_module.model_status = lambda s: {"reachable": True, "model_ready": True, "model": "x", "detail": "ok"}
        client = TestClient(api_module.create_app(settings=settings, store=DownStore(settings.data_dir)))
        response = client.get("/api/users/jordan-rivera/profile")
    finally:
        api_module.model_status = api_module_status
    assert response.status_code == 503
    assert response.json()["error"] == {
        "code": "MEMORY_UNAVAILABLE",
        "message": "AgentCore Memory needs working AWS credentials. Run 'aws login', then restart the backend.",
    }


def test_switching_to_agentcore_copies_local_work_once(store):
    from coach.memory.migrate import copy_local_to_agentcore

    store.save_profile("jordan-ab12", {"version": 1, "created_at": "2026-10-01T00:00:00Z"})
    store.save_profile("jordan-ab12", {"version": 2, "created_at": "2026-10-02T00:00:00Z"})
    store.add_note("jordan-ab12", NOTE_A)
    store.session_manager("no-profile-yet", "s1")  # a user dir with no profile is skipped
    agentcore, client = make_agentcore()

    assert copy_local_to_agentcore(store, agentcore) == ["jordan-ab12: 2 profile version(s), 1 progress note(s)"]
    assert [p["version"] for p in agentcore.profile_history("jordan-ab12")] == [1, 2]
    assert agentcore.list_notes("jordan-ab12") == [NOTE_A]
    assert len(client.gmdp_client.batches) == 1  # the note is searchable by meaning too

    assert copy_local_to_agentcore(store, agentcore) == []  # restarting never duplicates
    assert len(agentcore.profile_history("jordan-ab12")) == 2
