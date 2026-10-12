"""Model factory. Every model call in the app goes through Strands, on one of two providers:

- bedrock (default): Claude Haiku 5.5 on Amazon Bedrock, in your own AWS account. See bedrock.py.
- ollama: a free open-source model on this computer, for when there's no AWS account.

COACH_PROVIDER in backend/.env picks one; the rest of the app doesn't know which it got.
"""

from __future__ import annotations

import threading
from collections.abc import AsyncIterator
from contextlib import aclosing
from dataclasses import dataclass
from typing import Any

import ollama
from pydantic import BaseModel, ValidationError
from strands.models.bedrock import BedrockModel
from strands.models.ollama import OllamaModel

from . import bedrock
from .config import PREFERRED_MODELS, Settings

_THINKING_CACHE: dict[tuple[str, str], bool] = {}


@dataclass(frozen=True)
class Budget:
    temperature: float  # Ollama only: Claude Haiku 5.5 rejects temperature, so Bedrock calls send none
    ollama_tokens: int
    bedrock_tokens: int  # roomier: Haiku 5.5 spends output tokens on hidden reasoning first


BUDGETS = {
    "synthesis": Budget(0.2, 2500, 8192),
    "chat": Budget(0.6, 700, 4096),
    "extract": Budget(0.0, 200, 2048),
    "verify": Budget(0.0, 200, 2048),
}


def build_model(settings: Settings, purpose: str) -> Any:
    """A Strands model for one job: synthesis, chat, extract or verify."""
    budget = BUDGETS[purpose]
    if settings.provider == "bedrock":
        return bedrock.build(settings, budget.bedrock_tokens)
    model_id = resolve_model_id(settings)
    extra: dict[str, Any] | None = {"think": False} if supports_thinking(settings.ollama_host, model_id) else None
    return OllamaModel(
        settings.ollama_host,
        model_id=model_id,
        temperature=budget.temperature,
        max_tokens=budget.ollama_tokens,
        keep_alive="30m",
        options={"num_ctx": settings.num_ctx},
        additional_args=extra,
    )


async def stream_structured(
    model: Any, output_model: type[BaseModel], messages: list[dict[str, Any]], system_prompt: str
) -> AsyncIterator[dict[str, Any]]:
    """Structured JSON, streamed so the UI can watch the model write.

    Yields {"type": "partial", "text": <JSON so far>} as tokens arrive, then
    {"type": "output", "output": <validated model>}. Raises ValueError when the
    finished JSON doesn't fit the schema.

    - Bedrock: Strands asks Claude to call a tool whose input schema is the Pydantic model, and
      the tool input arrives as streamed JSON. Closing this generator (the user pressed Cancel)
      sets Strands' cancel signal, which closes the HTTP stream so Bedrock stops writing.
    - Ollama: the schema goes in as `format`, which constrains decoding to valid JSON. Strands'
      OllamaModel.structured_output sends stream=False, so this builds the same request with
      Strands' format_request and streams it.
    - Anything else (test doubles) answers in one piece.
    """
    if isinstance(model, OllamaModel):
        async for event in _stream_ollama(model, output_model, messages, system_prompt):
            yield event
        return
    cancel = threading.Event()
    extra = {"cancel_signal": cancel} if isinstance(model, BedrockModel) else {}
    text = ""
    try:
        async with aclosing(model.structured_output(output_model, messages, system_prompt=system_prompt, **extra)) as events:
            async for event in events:
                chunk = event.get("event") or {}
                piece = chunk.get("contentBlockDelta", {}).get("delta", {}).get("toolUse", {}).get("input")
                if piece:
                    text += piece
                    yield {"type": "partial", "text": text}
                if "output" in event:
                    yield {"type": "output", "output": event["output"]}
    finally:
        cancel.set()


async def _stream_ollama(
    model: OllamaModel, output_model: type[BaseModel], messages: list[dict[str, Any]], system_prompt: str
) -> AsyncIterator[dict[str, Any]]:
    request = model.format_request(messages, system_prompt=system_prompt)
    request["format"] = output_model.model_json_schema()
    text = ""
    async for chunk in await ollama.AsyncClient(model.host, **model.client_args).chat(**request):
        if piece := chunk.message.content:
            text += piece
            yield {"type": "partial", "text": text}
    try:
        output = output_model.model_validate_json(text.strip())
    except ValidationError as exc:
        raise ValueError(f"The model's JSON did not match the schema: {exc}") from exc
    yield {"type": "output", "output": output}


def model_status(settings: Settings) -> dict[str, Any]:
    """{"model": id, "reachable", "model_ready", "detail"} for /api/health and the startup banner."""
    if settings.provider == "bedrock":
        return {"model": settings.bedrock_model_id, **bedrock.status(settings)}
    return ollama_status(settings)


def explain_model_error(exc: BaseException, settings: Settings) -> str:
    """A model call failed: say how to fix it, in the provider's terms."""
    if settings.provider == "bedrock":
        return bedrock.explain(exc, settings)
    text = str(exc)
    if isinstance(exc, ConnectionError) or "connect" in text.lower():
        return "Can't reach Ollama. Start it, then try again."
    if "not found" in text.lower():
        return f"Model not installed. {text}"
    return f"The model failed: {text[:300]}"


def model_name(model: Any, fallback: str) -> str:
    """The model id a model object was built with (recorded on each profile)."""
    try:
        return str(model.get_config().get("model_id") or fallback)
    except Exception:
        return fallback


model_label = bedrock.model_label  # display name: 'us.anthropic.claude-haiku-5-5' -> 'Claude Haiku 5.5'


# ---- Ollama ----------------------------------------------------------------------------------


def installed_models(host: str) -> set[str] | None:
    """Names of the models pulled in Ollama, or None if Ollama is not reachable."""
    try:
        return {m.model for m in ollama.Client(host=host, timeout=3).list().models}
    except Exception:
        return None


def full_name(model_id: str) -> str:
    return model_id if ":" in model_id else f"{model_id}:latest"


def pick_model(requested: str, installed: set[str] | None) -> str:
    """'auto' takes the first preferred model that is pulled; any other value is used as given.

    This lets an attendee pull only the small model and run the coach with no config edits.
    """
    if requested != "auto":
        return requested
    for name in PREFERRED_MODELS:
        if installed and name in installed:
            return name
    return PREFERRED_MODELS[0]


def resolve_model_id(settings: Settings) -> str:
    if settings.model_id != "auto":
        return settings.model_id
    return pick_model("auto", installed_models(settings.ollama_host))


def supports_thinking(host: str, model_id: str) -> bool:
    """Hybrid models such as qwen3:1.7b reason out loud by default; we switch that off for speed.

    Only successful lookups are cached, so starting Ollama after the API still works.
    """
    key = (host, model_id)
    if key not in _THINKING_CACHE:
        try:
            capabilities = ollama.Client(host=host, timeout=5).show(model_id).capabilities or []
        except Exception:
            return False
        _THINKING_CACHE[key] = "thinking" in capabilities
    return _THINKING_CACHE[key]


def ollama_status(settings: Settings) -> dict[str, Any]:
    installed = installed_models(settings.ollama_host)
    model = pick_model(settings.model_id, installed)
    if installed is None:
        return {
            "reachable": False,
            "model_ready": False,
            "model": model,
            "detail": f"Ollama is not reachable at {settings.ollama_host}. Open the Ollama app or run: ollama serve",
        }
    ready = full_name(model) in installed
    if ready:
        detail = "ok"
    elif settings.model_id == "auto":
        detail = (
            f"No model pulled yet. Run: ollama pull {PREFERRED_MODELS[0]}  "
            f"(or ollama pull {PREFERRED_MODELS[1]} on an 8 GB laptop)"
        )
    else:
        detail = f"Model missing. Run: ollama pull {model}"
    return {"reachable": True, "model_ready": ready, "model": model, "detail": detail}
