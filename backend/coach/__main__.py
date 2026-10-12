"""Start the API:  uv run python -m coach"""

from __future__ import annotations

import os

import uvicorn

from .config import Settings, get_settings
from .llm import model_label, model_status


def agentcore_status(settings: Settings) -> str:
    """One line for the startup banner. Catches every error: a bad memory must not stop the API."""
    try:
        from bedrock_agentcore.memory import MemoryClient

        from .memory.agentcore import friendly_aws_error

        try:
            status = MemoryClient(region_name=settings.aws_region).get_memory_status(settings.agentcore_memory_id)
        except Exception as exc:  # noqa: BLE001 - reported, not raised
            return f"WARNING: {friendly_aws_error(exc)}"
        return f"{settings.agentcore_memory_id} ({status}, {settings.aws_region})"
    except Exception as exc:  # noqa: BLE001
        return f"WARNING: could not check AgentCore Memory ({exc.__class__.__name__})"


def copy_local_work(settings: Settings) -> list[str]:
    """Bring profiles built on local memory along, so switching brains keeps your dashboard."""
    try:
        from .memory.agentcore import AgentCoreMemoryStore
        from .memory.local import LocalMemoryStore
        from .memory.migrate import copy_local_to_agentcore

        agentcore = AgentCoreMemoryStore(settings.agentcore_memory_id, settings.aws_region)
        return [f"copied from local files: {line}" for line in copy_local_to_agentcore(LocalMemoryStore(settings.data_dir), agentcore)]
    except Exception as exc:  # noqa: BLE001 - never block startup
        return [f"WARNING: could not copy local profiles into AgentCore Memory ({exc})"]


def main() -> None:
    settings = get_settings()
    port = int(os.environ.get("COACH_PORT", "8000"))
    status = model_status(settings)  # Bedrock: one tiny real call, the only proof the account can use it
    if settings.provider == "bedrock":
        where = f"{model_label(status['model'])} on Amazon Bedrock ({status['model']}, {settings.aws_region})"
    else:
        how = ", auto: best model you have pulled" if settings.model_id == "auto" else ""
        where = f"{status['model']} on this computer (Ollama{how})"
    print(f"Career Coach API  ->  http://127.0.0.1:{port}/api/health")
    print(f"  model:  {where}")
    if not status["model_ready"]:
        print(f"  WARNING: {status['detail']}")
    if settings.memory_backend == "agentcore" and settings.agentcore_memory_id:
        line = agentcore_status(settings)
        print(f"  memory: AgentCore Memory {line}")
        if "(ACTIVE," in line:
            for copied in copy_local_work(settings):
                print(f"          {copied}")
    else:
        print("  memory: local files in backend/data")
    if not settings.web_search:
        print("  web search: off (COACH_WEB_SEARCH=off)")
    else:
        provider = "Tavily" if settings.tavily_api_key else "ddgs, no key needed"
        print(f"  web search: {provider} (checks next steps and fact questions; COACH_WEB_SEARCH=off disables)")
    if settings.auth == "cognito":
        print(f"  sign-in: Cognito user pool {settings.cognito_pool_id}")
    if settings.static_dir:
        print(f"  website: {settings.static_dir}")
    # Loopback by default: without COACH_AUTH=cognito the API has no sign-in. The CloudFormation
    # stack binds to the instance's private address, behind CloudFront and a security group.
    uvicorn.run("coach.api:create_app", factory=True, host=settings.host, port=port, log_level="info")


if __name__ == "__main__":
    main()
