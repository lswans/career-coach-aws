"""AgentCore brain: Amazon Bedrock AgentCore Memory.

AgentCore Memory is model-agnostic: it stores events and runs its own extraction, whatever
model wrote them, so the coach uses it the same way with Claude on Bedrock or the local model.

How the coach uses it:
- Profile snapshots and progress notes are blob events in fixed sessions, so they can be
  listed exactly (that is what powers the trend charts).
- Each progress note is also written as a long-term memory record under
  /career/{actorId}/progress/ so the coach can find it later by meaning, not keywords.
- Chat turns go through AgentCoreMemorySessionManager (short-term memory). The memory's
  built-in strategies extract facts and preferences from them, and the session manager
  pulls relevant ones back into context on every user turn.
"""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any

from .base import MemoryStore, MemoryUnavailable, note_sentence

logger = logging.getLogger(__name__)

PROFILE_SESSION = "profile-snapshots"
NOTES_SESSION = "progress-notes"
# namespace template -> (top_k, minimum relevance score)
RETRIEVAL = {
    "/facts/{actorId}/": (5, 0.3),
    "/preferences/{actorId}/": (5, 0.3),
}


def progress_namespace(user_id: str) -> str:
    return f"/career/{user_id}/progress/"


def as_blob(data: dict[str, Any]) -> str:
    """Blob payloads must be sent as a JSON string.

    Sent as a dict, the service hands it back as Java-style text like
    "{summary=..., skills=[{name=Python}]}", which can't be parsed. The SDK's own
    session manager json.dumps its blobs for the same reason.
    """
    return json.dumps(data, ensure_ascii=False)


def friendly_aws_error(exc: BaseException) -> str:
    """Say what went wrong in words a workshop attendee can act on."""
    text = str(exc)
    code = ""
    response = getattr(exc, "response", None)
    if isinstance(response, dict):
        code = str(response.get("Error", {}).get("Code", ""))
    if "credential" in text.lower() or code in {"ExpiredTokenException", "UnrecognizedClientException", "InvalidSignatureException"}:
        return "AgentCore Memory needs working AWS credentials. Run 'aws login', then restart the backend."
    if code == "ResourceNotFoundException":
        return ("AgentCore Memory not found. Run 'uv run python scripts/create_agentcore_memory.py' in backend, "
                "or switch back with COACH_MEMORY=local in backend/.env.")
    if code == "AccessDeniedException":
        return "Your AWS user is not allowed to use AgentCore Memory. Check its IAM permissions."
    if code == "ThrottlingException":
        return "AgentCore Memory is busy (throttled). Wait a few seconds and try again."
    return f"AgentCore Memory request failed ({code or exc.__class__.__name__}): {text[:200]}"


@contextmanager
def aws_errors() -> Iterator[None]:
    """Re-raise AWS SDK errors as MemoryUnavailable with a fix-it message."""
    from botocore.exceptions import BotoCoreError, ClientError

    try:
        yield
    except (BotoCoreError, ClientError) as exc:
        raise MemoryUnavailable(friendly_aws_error(exc)) from exc


class AgentCoreMemoryStore(MemoryStore):
    backend = "agentcore"

    def __init__(self, memory_id: str, region: str, client: Any | None = None) -> None:
        self.memory_id = memory_id
        self.region = region
        if client is None:
            from bedrock_agentcore.memory import MemoryClient

            client = MemoryClient(region_name=region)
        self.client = client

    def _blobs(self, user_id: str, session_id: str) -> list[dict[str, Any]]:
        with aws_errors():
            events = self.client.list_events(
                memory_id=self.memory_id, actor_id=user_id, session_id=session_id, max_results=100
            )
        items: list[dict[str, Any]] = []
        for event in events:
            for part in event.get("payload", []):
                blob = part.get("blob")
                if isinstance(blob, str):
                    try:
                        blob = json.loads(blob)
                    except json.JSONDecodeError:
                        continue
                if isinstance(blob, dict):
                    items.append(blob)
        return sorted(items, key=lambda item: str(item.get("created_at", "")))

    def save_profile(self, user_id: str, profile: dict[str, Any]) -> None:
        with aws_errors():
            self.client.create_blob_event(
                memory_id=self.memory_id, actor_id=user_id, session_id=PROFILE_SESSION, blob_data=as_blob(profile)
            )

    def profile_history(self, user_id: str) -> list[dict[str, Any]]:
        return self._blobs(user_id, PROFILE_SESSION)

    def add_note(self, user_id: str, note: dict[str, Any]) -> None:
        with aws_errors():
            self.client.create_blob_event(
                memory_id=self.memory_id, actor_id=user_id, session_id=NOTES_SESSION, blob_data=as_blob(note)
            )
            response = self.client.gmdp_client.batch_create_memory_records(
                memoryId=self.memory_id,
                records=[
                    {
                        "requestIdentifier": uuid.uuid4().hex,
                        "namespaces": [progress_namespace(user_id)],
                        "content": {"text": note_sentence(note)},
                        "timestamp": datetime.now(timezone.utc),
                    }
                ],
            )
        # The note is already saved for the charts. A failed long-term record only means the
        # coach can't find it by meaning later, so log it instead of failing the chat.
        for failed in (response or {}).get("failedRecords", []):
            logger.warning("AgentCore did not store the progress note as a long-term record: %s", failed)

    def list_notes(self, user_id: str) -> list[dict[str, Any]]:
        return self._blobs(user_id, NOTES_SESSION)

    def recall(self, user_id: str, query: str, top_k: int = 5) -> list[str]:
        # The SDK returns [] when the search fails, so recall degrades instead of breaking chat.
        records = self.client.retrieve_memories(
            memory_id=self.memory_id, namespace_path=progress_namespace(user_id), query=query, top_k=top_k
        )
        texts = []
        for record in records:
            text = (record.get("content") or {}).get("text", "").strip()
            if text:
                texts.append(text)
        return texts

    def session_manager(self, user_id: str, session_id: str) -> Any:
        from bedrock_agentcore.memory.integrations.strands.config import AgentCoreMemoryConfig, RetrievalConfig
        from bedrock_agentcore.memory.integrations.strands.session_manager import AgentCoreMemorySessionManager
        from strands.types.exceptions import SessionException

        config = AgentCoreMemoryConfig(
            memory_id=self.memory_id,
            session_id=session_id,
            actor_id=user_id,
            retrieval_config={
                namespace: RetrievalConfig(top_k=top_k, relevance_score=score)
                for namespace, (top_k, score) in RETRIEVAL.items()
            },
        )
        try:
            with aws_errors():
                return AgentCoreMemorySessionManager(agentcore_memory_config=config, region_name=self.region)
        except SessionException as exc:  # wraps the AWS error while restoring the chat
            raise MemoryUnavailable(friendly_aws_error(exc.__cause__ or exc)) from exc
