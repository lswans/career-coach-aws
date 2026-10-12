import asyncio
import threading

import pytest
from botocore.exceptions import ClientError, EndpointConnectionError, NoCredentialsError
from strands.models.bedrock import BedrockModel
from strands.types.exceptions import ModelThrottledException

import coach.bedrock as bedrock
from coach.config import Settings
from coach.llm import stream_structured
from tests.conftest import make_draft

SETTINGS = Settings()


def client_error(code: str, message: str, operation: str = "ConverseStream") -> ClientError:
    return ClientError({"Error": {"Code": code, "Message": message}}, operation)


def test_labels_are_readable():
    assert bedrock.model_label("us.anthropic.claude-haiku-5-5") == "Claude Haiku 5.5"
    assert bedrock.model_label("global.anthropic.claude-haiku-4-5-20251001-v1:0") == "Claude Haiku 4.5"
    assert bedrock.model_label("us.amazon.nova-lite-v1:0") == "amazon.nova-lite-v1:0"
    assert bedrock.model_label("qwen3:1.7b") == "qwen3:1.7b"


@pytest.mark.parametrize(
    "error, fix",
    [
        # The exact messages Bedrock returns, as seen live or reported for new accounts.
        (client_error("ResourceNotFoundException", "Model use case details have not been submitted for this account. "
                      "Fill out the Anthropic use case details form before using the model."), "use-case form"),
        (client_error("AccessDeniedException", "Model access is denied due to INVALID_PAYMENT_INSTRUMENT:"
                      "A valid payment instrument must be provided."), "payment method"),
        (client_error("AccessDeniedException", "Model access is denied due to IAM user or service role is not "
                      "authorized to perform the required AWS Marketplace actions (aws-marketplace:Subscribe)."),
         "Marketplace permissions"),
        (client_error("ValidationException", "Invocation of model ID anthropic.claude-haiku-5-5 with on-demand "
                      "throughput isn’t supported. Retry your request with the ID or ARN of an inference profile "
                      "that contains this model."), "inference profile"),
        (client_error("ValidationException", "The provided model identifier is invalid."), "AWS_REGION=us-east-1"),
        (client_error("ValidationException", "Operation not allowed"), "verifying this new AWS account"),
        (client_error("ValidationException", "Access to this model is not available for channel program accounts. "
                      "Reach out to your AWS Solution Provider or AWS Distributor for more information."),
         "AWS partner"),
        (client_error("AccessDeniedException", "You don't have access to the model with the specified model ID."),
         "COACH_PROVIDER=ollama"),
        (client_error("ExpiredTokenException", "The security token included in the request is expired"), "aws login"),
        (NoCredentialsError(), "aws login"),
        (ModelThrottledException("ThrottlingException: Too many requests"), "throttled"),
        (EndpointConnectionError(endpoint_url="https://bedrock-runtime.us-east-1.amazonaws.com"), "internet"),
        (client_error("ServiceUnavailableException", "Service unavailable"), "temporary problem"),
    ],
)
def test_every_bedrock_failure_says_how_to_fix_it(error, fix):
    assert fix in bedrock.explain(error, SETTINGS)


class FakeRuntime:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.calls: list[dict] = []

    def converse(self, **request):
        self.calls.append(request)
        if self.error:
            raise self.error
        return {"output": {"message": {"role": "assistant", "content": [{"text": "OK"}]}}, "stopReason": "end_turn"}


def test_the_access_check_is_one_tiny_call():
    runtime = FakeRuntime()
    assert bedrock.check(SETTINGS, runtime) == {"reachable": True, "model_ready": True, "detail": "ok"}
    (request,) = runtime.calls
    assert request["modelId"] == "us.anthropic.claude-haiku-5-5"
    assert request["inferenceConfig"] == {"maxTokens": 16}  # and no temperature, which Haiku 5.5 rejects
    denied = bedrock.check(SETTINGS, FakeRuntime(client_error("AccessDeniedException", "INVALID_PAYMENT_INSTRUMENT")))
    assert denied["model_ready"] is False and "payment method" in denied["detail"]


def test_status_is_cached_longer_when_the_model_works(monkeypatch):
    clock = [1000.0]
    results = [{"reachable": True, "model_ready": False, "detail": "no"}] + [
        {"reachable": True, "model_ready": True, "detail": "ok"}] * 2
    calls = []
    monkeypatch.setattr(bedrock.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(bedrock, "check", lambda settings, client=None: calls.append(1) or results[len(calls) - 1])
    monkeypatch.setattr(bedrock, "_status", {})
    assert bedrock.status(SETTINGS)["model_ready"] is False
    clock[0] += 5
    bedrock.status(SETTINGS)
    assert len(calls) == 1  # a failed check is reused for 20 s, so the 20 s health polls don't hammer Bedrock
    clock[0] += 20
    assert bedrock.status(SETTINGS)["model_ready"] is True and len(calls) == 2
    clock[0] += 300
    bedrock.status(SETTINGS)
    assert len(calls) == 2  # a working model is re-checked every 10 minutes
    bedrock.status(SETTINGS, fresh=True)
    assert len(calls) == 3


def test_bedrock_tool_input_streams_and_cancel_reaches_strands():
    """The live checklist reads Claude's tool-input JSON as it streams; Cancel must stop Bedrock writing."""
    answer = make_draft().model_dump_json()
    pieces = [answer[i : i + 50] for i in range(0, len(answer), 50)]
    model = BedrockModel(model_id="us.anthropic.claude-haiku-5-5", region_name="us-east-1")
    seen: dict = {}

    async def fake_stream(messages, tool_specs=None, system_prompt=None, *, tool_choice=None, cancel_signal=None, **kw):
        seen.update(tool=tool_specs[0]["name"], choice=tool_choice, cancel=cancel_signal)
        yield {"messageStart": {"role": "assistant"}}
        yield {"contentBlockStart": {"start": {"toolUse": {"toolUseId": "t1", "name": "ProfileDraft"}}}}
        for piece in pieces:
            yield {"contentBlockDelta": {"delta": {"toolUse": {"input": piece}}}}
        yield {"contentBlockStop": {}}
        yield {"messageStop": {"stopReason": "tool_use"}}

    model.stream = fake_stream
    from coach.schemas import ProfileDraft

    async def collect():
        return [e async for e in stream_structured(model, ProfileDraft, [{"role": "user", "content": [{"text": "x"}]}], "s")]

    events = asyncio.run(collect())
    partials = [e["text"] for e in events if e["type"] == "partial"]
    assert len(partials) == len(pieces) and partials[-1] == answer
    assert events[-1]["output"] == make_draft()
    assert seen["tool"] == "ProfileDraft" and seen["choice"] == {"any": {}}
    assert isinstance(seen["cancel"], threading.Event) and seen["cancel"].is_set()  # set once the stream closes

    async def cancel_early():
        stream = stream_structured(model, ProfileDraft, [{"role": "user", "content": [{"text": "x"}]}], "s")
        await anext(stream)  # first partial, then the user presses Cancel
        assert not seen["cancel"].is_set()
        await stream.aclose()
        return seen["cancel"].is_set()

    assert asyncio.run(cancel_early()) is True
