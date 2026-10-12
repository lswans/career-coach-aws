"""HTTP API for the Career Coach. Run with: uv run python -m coach  (binds 127.0.0.1:8000).

Security note: by default there is no authentication. The server binds to 127.0.0.1 only and CORS
allows only the origins in COACH_ALLOWED_ORIGINS, so it is a single-user local app. Do not expose
it on a public interface in that mode. The CloudFormation stack sets COACH_AUTH=cognito, which
requires a Cognito access token on every user route and takes the user id from the token.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from collections.abc import AsyncIterator, Callable
from contextlib import aclosing
from typing import Any

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from . import __version__
from .auth import AuthError, KeySource, bearer, jwks_client, verify
from .coach_agent import build_coach, extract_progress, web_block, web_query
from .config import Settings, get_settings
from .ingest import ALLOWED_EXTENSIONS, Document, IngestError, extract_text, normalize
from .insights import compute_insights
from .limits import DailyLimits
from .llm import build_model, explain_model_error, model_label, model_status
from .memory import MemoryStore, make_store
from .memory.base import MemoryUnavailable
from .schemas import ChatRequest
from .search import SearchResult, WebSearch, make_search
from .synthesis import SynthesisError, synthesize_events, synthesize_profile
from .validation import IntakeError, validate_intake
from .verify import unbacked_names

logger = logging.getLogger(__name__)
USER_ID = re.compile(r"^[a-z0-9][a-z0-9-]{1,62}$")
SSE_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
ModelFactory = Callable[[str], Any]


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str, fields: dict[str, str] | None = None):
        super().__init__(message)
        self.status, self.code, self.message, self.fields = status, code, message, fields


def error_body(code: str, message: str, fields: dict[str, str] | None = None) -> dict[str, Any]:
    body: dict[str, Any] = {"code": code, "message": message}
    if fields:
        body["fields"] = fields
    return {"error": body}


def sse(payload: dict[str, Any]) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def friendly_model_error(exc: BaseException, settings: Settings) -> str:
    if isinstance(exc, MemoryUnavailable):
        return str(exc)
    if exc.__class__.__name__ == "SessionException":  # the memory session manager failed mid-chat
        return f"Your coach's memory failed: {str(exc)[:200]}. Check your AWS credentials, then try again."
    return explain_model_error(exc, settings)


def build_error(exc: Exception, settings: Settings) -> ApiError:
    """One mapping for build failures, used by the JSON response and the event stream."""
    if isinstance(exc, ApiError):
        return exc
    if isinstance(exc, SynthesisError):
        return ApiError(502, "SYNTHESIS_FAILED", str(exc))
    if isinstance(exc, MemoryUnavailable):
        return ApiError(503, "MEMORY_UNAVAILABLE", str(exc))
    return ApiError(503, "MODEL_UNAVAILABLE", friendly_model_error(exc, settings))  # no access, offline, throttled


def own_words(profile: dict[str, Any]) -> str:
    """What the person wrote or proved themselves: goals, skills and their evidence (not the model's
    suggested next steps). The reply check treats names found here as theirs."""
    skills = profile.get("skills", [])
    return " ".join([str(profile.get("goals", "")), *(str(s.get("name", "")) for s in skills),
                     *(str(e) for s in skills for e in s.get("evidence", []))])


def parse_entries(raw: str) -> list[Document]:
    """`entries` is a JSON list of {"label": str, "text": str} from the paste boxes."""
    try:
        items = json.loads(raw or "[]")
    except json.JSONDecodeError as exc:
        raise ApiError(422, "VALIDATION_ERROR", "entries must be a JSON list", {"entries": str(exc)}) from exc
    if not isinstance(items, list):
        raise ApiError(422, "VALIDATION_ERROR", "entries must be a JSON list", {"entries": "Expected a list."})
    docs = []
    for item in items:
        if isinstance(item, dict):
            text = normalize(str(item.get("text", "")))
            if text:
                docs.append(Document(name=str(item.get("label") or "Notes")[:80], kind="text", text=text))
    return docs


def create_app(
    settings: Settings | None = None,
    store: MemoryStore | None = None,
    model_factory: ModelFactory | None = None,
    search: WebSearch | None = None,
    keys: KeySource | None = None,
) -> FastAPI:
    settings = settings or get_settings()
    store = store or make_store(settings)
    search = search or make_search(settings)
    hosted = settings.auth == "cognito"
    signing_keys = (keys or jwks_client(settings)) if hosted else None
    limits = DailyLimits({"build": settings.daily_builds, "chat": settings.daily_chats})

    def default_factory(purpose: str) -> Any:
        return build_model(settings, purpose)

    make_model = model_factory or default_factory

    app = FastAPI(title="Career Coach API", version=__version__)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.allowed_origins),
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type", "Authorization", "X-Coach-Auth"],
        # Lets an Amplify-hosted page call a localhost API. The hosted stack serves the site
        # from the same origin, so it needs no cross-origin access at all.
        allow_private_network=not hosted,
    )

    @app.exception_handler(ApiError)
    async def _api_error(_: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(error_body(exc.code, exc.message, exc.fields), status_code=exc.status)

    @app.exception_handler(AuthError)
    async def _auth_error(_: Request, exc: AuthError) -> JSONResponse:
        return JSONResponse(error_body("UNAUTHORIZED", str(exc)), status_code=401)

    @app.exception_handler(MemoryUnavailable)
    async def _memory_error(_: Request, exc: MemoryUnavailable) -> JSONResponse:
        return JSONResponse(error_body("MEMORY_UNAVAILABLE", str(exc)), status_code=503)

    @app.exception_handler(IntakeError)
    async def _intake_error(_: Request, exc: IntakeError) -> JSONResponse:
        return JSONResponse(
            error_body("VALIDATION_ERROR", "Your intake is not ready for synthesis yet.", exc.fields), status_code=422
        )

    @app.exception_handler(RequestValidationError)
    async def _request_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        fields = {".".join(str(p) for p in e["loc"] if p != "body"): e["msg"] for e in exc.errors()}
        return JSONResponse(error_body("VALIDATION_ERROR", "Invalid request.", fields), status_code=422)

    def check_user(request: Request, user_id: str) -> None:
        """Local mode: any well-formed id. Hosted mode: only the signed-in person's own id."""
        if not USER_ID.match(user_id):
            raise ApiError(400, "BAD_USER_ID", "user_id must be 2-63 lowercase letters, digits or hyphens.")
        if hosted and verify(bearer(request.headers), settings, signing_keys).user_id != user_id:
            raise ApiError(403, "FORBIDDEN", "You can only open your own coach.")

    def spend(kind: str, user_id: str) -> None:
        if hosted and not limits.take(kind, user_id):
            what = "profile builds" if kind == "build" else "chat messages"
            raise ApiError(429, "DAILY_LIMIT", f"You've used today's {what}. Try again tomorrow.")

    def insights_for(user_id: str) -> dict[str, Any] | None:
        return compute_insights(store.profile_history(user_id), store.list_notes(user_id))

    @app.get("/api/me")
    async def me(request: Request) -> dict[str, Any]:
        """Hosted mode: who the token belongs to, so the website learns its user id after sign-in."""
        if not hosted:
            raise ApiError(404, "NO_SIGN_IN", "This coach has no sign-in. Pick a name instead.")
        caller = verify(bearer(request.headers), settings, signing_keys)
        return {"user_id": caller.user_id}

    @app.get("/api/health")
    async def health() -> dict[str, Any]:
        status = await asyncio.to_thread(model_status, settings)
        model_id = status.pop("model", settings.active_model_id)
        sign_in: dict[str, Any] = {"mode": settings.auth}
        if hosted:  # public values the website needs to talk to Cognito
            sign_in.update(region=(settings.cognito_pool_id or "").split("_", 1)[0],
                           client_id=settings.cognito_client_id)
        return {
            "status": "ok",
            "version": __version__,
            "provider": settings.provider,
            "model": model_label(model_id),
            "model_id": model_id,
            "model_status": status,
            "memory_backend": store.backend,
            "web_search": search.name,
            "auth": sign_in,
            "rules": {
                "min_goal_chars": settings.min_goal_chars,
                "min_doc_chars": settings.min_doc_chars,
                "max_files": settings.max_files,
                "max_file_mb": settings.max_file_bytes // (1024 * 1024),
                "allowed_extensions": list(ALLOWED_EXTENSIONS),
            },
        }

    @app.post("/api/users/{user_id}/profile", status_code=201)
    async def create_profile(
        request: Request,
        user_id: str,
        goals: str = Form(""),
        entries: str = Form("[]"),
        files: list[UploadFile] = File(default=[]),
    ) -> Any:
        """Build a profile. With `Accept: text/event-stream` it streams progress (the setup screen
        uses this); otherwise it answers once with JSON. Intake errors are 422 JSON either way."""
        check_user(request, user_id)
        docs: list[Document] = []
        file_errors: list[str] = []
        if len(files) > settings.max_files:
            file_errors.append(f"Upload at most {settings.max_files} files.")
        for upload in files[: settings.max_files]:
            name = upload.filename or "upload"
            data = await upload.read(settings.max_file_bytes + 1)
            if len(data) > settings.max_file_bytes:
                file_errors.append(f"{name}: larger than {settings.max_file_bytes // (1024 * 1024)} MB.")
                continue
            try:
                docs.append(Document(name=name, kind="file", text=extract_text(name, data)))
            except IngestError as exc:
                file_errors.append(str(exc))
        docs.extend(parse_entries(entries))
        goals = validate_intake(goals, docs, settings, file_errors)
        spend("build", user_id)  # only intakes that pass validation count toward the cap
        build = dict(
            user_id=user_id,
            goals=goals,
            docs=docs,
            settings=settings,
            store=store,
            model=make_model("synthesis"),
            checker=make_model("verify"),
            search=search,
            notes=await asyncio.to_thread(store.list_notes, user_id),
        )
        if "text/event-stream" in request.headers.get("accept", ""):
            return StreamingResponse(build_stream(synthesize_events(**build), insights_for, settings),
                                     media_type="text/event-stream", headers=SSE_HEADERS)
        try:
            profile = await synthesize_profile(**build)
        except Exception as exc:
            raise build_error(exc, settings) from exc
        return {"profile": profile.model_dump(mode="json"), "insights": insights_for(user_id)}

    @app.get("/api/users/{user_id}/profile")
    async def get_profile(request: Request, user_id: str) -> dict[str, Any]:
        check_user(request, user_id)
        profile = store.latest_profile(user_id)
        if profile is None:
            raise ApiError(404, "PROFILE_NOT_FOUND", "No profile yet. Complete setup first.")
        return {"profile": profile, "insights": insights_for(user_id)}

    @app.get("/api/users/{user_id}/insights")
    async def get_insights(request: Request, user_id: str) -> dict[str, Any]:
        check_user(request, user_id)
        insights = insights_for(user_id)
        if insights is None:
            raise ApiError(404, "PROFILE_NOT_FOUND", "No profile yet. Complete setup first.")
        return insights

    @app.post("/api/users/{user_id}/chat")
    async def chat(request: Request, user_id: str, body: ChatRequest) -> StreamingResponse:
        check_user(request, user_id)
        profile = store.latest_profile(user_id)
        if profile is None:
            raise ApiError(409, "PROFILE_REQUIRED", "Create your profile before chatting with your coach.")
        spend("chat", user_id)
        # A question about certifications, courses, jobs or events is searched while progress is extracted.
        query = web_query(body.message, profile) if search.enabled else None
        lookup = asyncio.create_task(search.asearch(query, 4)) if query else None
        try:
            try:
                note = await extract_progress(make_model("extract"), body.message)
            except Exception as exc:
                raise ApiError(503, "MODEL_UNAVAILABLE", friendly_model_error(exc, settings)) from exc
            if note:
                await asyncio.to_thread(store.add_note, user_id, note.model_dump())
        except BaseException:
            if lookup:
                lookup.cancel()
            raise
        results: list[SearchResult] = []
        if lookup:
            try:
                results = await lookup
            except Exception:  # noqa: BLE001 - no search results never stops the coach from answering
                logger.info("web search skipped for this chat turn", exc_info=True)
        agent = await asyncio.to_thread(
            lambda: build_coach(
                store=store,
                model=make_model("chat"),
                user_id=user_id,
                session_id=body.session_id,
                profile=profile,
                user_message=body.message,
                recorded=note,
                web=web_block(query or "", results),
            )
        )
        return StreamingResponse(
            stream_chat(agent, body.message, settings, note.model_dump() if note else None, results, search,
                        own_words(profile)),
            media_type="text/event-stream",
            headers=SSE_HEADERS,
        )

    if settings.static_dir:  # mounted last, so /api/* routes always win
        app.mount("/", StaticFiles(directory=settings.static_dir, html=True), name="site")

    return app


async def build_stream(
    events: AsyncIterator[dict[str, Any]], insights_for: Callable[[str], Any], settings: Settings
) -> AsyncIterator[str]:
    """Server-sent events for a profile build: stage and progress events, then done (or error)."""
    try:
        async with aclosing(events):
            async for event in events:
                if event["type"] != "profile":
                    yield sse(event)
                    continue
                profile = event["profile"].model_dump(mode="json")
                insights = await asyncio.to_thread(insights_for, profile["user_id"])
                yield sse({"type": "done", "profile": profile, "insights": insights})
    except Exception as exc:  # noqa: BLE001 - the stream has started, so the error goes in-band
        error = build_error(exc, settings)
        yield sse({"type": "error", "code": error.code, "message": error.message})


async def stream_chat(
    agent: Any,
    message: str,
    settings: Settings,
    recorded: dict[str, Any] | None = None,
    sources: list[SearchResult] | None = None,
    search: WebSearch | None = None,
    known: str = "",
) -> AsyncIterator[str]:
    """Server-sent events: memory (a note was saved), sources (web results), delta (text), tool,
    check (offering names in the reply that no web result backs up), done, error."""
    if recorded:
        yield sse({"type": "memory", "note": recorded})
    if sources:
        yield sse({"type": "sources", "items": [{"title": r.title, "url": r.url} for r in sources]})
    tools_used: list[str] = []
    seen: set[str] = set()
    final = ""
    try:
        async for event in agent.stream_async(message):
            text = event.get("data")
            if isinstance(text, str) and text:
                yield sse({"type": "delta", "text": text})
            tool = event.get("current_tool_use")
            if isinstance(tool, dict) and tool.get("name"):
                key = str(tool.get("toolUseId") or tool["name"])
                if key not in seen:
                    seen.add(key)
                    tools_used.append(tool["name"])
                    yield sse({"type": "tool", "name": tool["name"]})
            if "result" in event:
                final = str(event["result"]).strip()
    except Exception as exc:
        yield sse({"type": "error", "message": friendly_model_error(exc, settings)})
        return
    if search and final:
        try:
            unbacked = await unbacked_names(final, message, sources or [], search, known)
        except Exception:  # noqa: BLE001 - the check is advice; the reply is already out
            logger.info("reply check skipped", exc_info=True)
            unbacked = []
        if unbacked:
            yield sse({"type": "check", "unverified": unbacked})
    yield sse({"type": "done", "text": final, "tools": tools_used, "recorded": recorded})
