"""Runtime settings, read from environment variables and an optional backend/.env file."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
ENV_FILE = BACKEND_DIR / ".env"
DEFAULT_ORIGINS = "http://localhost:5173,http://127.0.0.1:5173"
# COACH_PROVIDER picks where the model runs:
#   bedrock (default)  Claude Haiku 5.5 on Amazon Bedrock, in your own AWS account (pay per use)
#   ollama             a free open-source model on this computer (no AWS account needed)
PROVIDERS = ("bedrock", "ollama")
DEFAULT_BEDROCK_MODEL = "us.anthropic.claude-haiku-5-5"  # the US cross-region inference profile
# With COACH_PROVIDER=ollama, COACH_MODEL=auto (the default) uses the first of these that is pulled.
PREFERRED_MODELS = ("qwen3:4b-instruct", "qwen3:1.7b")
OLLAMA_MAX_DOC_CHARS = 12_000  # a laptop model's context is small; Claude takes far more


def load_env_file(path: Path = ENV_FILE) -> None:
    """Copy KEY=VALUE lines from a .env file into os.environ.

    Real environment variables win over the file. A UTF-8 BOM is tolerated
    because Windows PowerShell 5.1 adds one when it writes "utf8" files.
    """
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


@dataclass(frozen=True)
class Settings:
    provider: str = "bedrock"  # "bedrock" or "ollama"
    bedrock_model_id: str = DEFAULT_BEDROCK_MODEL
    model_id: str = "auto"  # Ollama only: "auto" or an exact tag such as "qwen3:1.7b"
    ollama_host: str = "http://127.0.0.1:11434"
    num_ctx: int = 8192
    max_doc_chars: int = 40_000  # about 10k tokens of documents per profile build
    memory_backend: str = "local"  # "local" or "agentcore"
    agentcore_memory_id: str | None = None
    aws_region: str = "us-east-1"
    data_dir: Path = BACKEND_DIR / "data"
    allowed_origins: tuple[str, ...] = tuple(DEFAULT_ORIGINS.split(","))
    web_search: bool = True  # COACH_WEB_SEARCH=off keeps every query on this laptop
    tavily_api_key: str | None = None  # optional: use Tavily instead of the keyless default
    min_goal_chars: int = 200
    min_doc_chars: int = 50
    max_files: int = 10
    max_file_bytes: int = 5 * 1024 * 1024
    # Hosted mode (the CloudFormation stack). Unset, the API stays a single-user local app.
    auth: str = "none"  # "none" or "cognito"
    cognito_pool_id: str | None = None
    cognito_client_id: str | None = None
    host: str = "127.0.0.1"
    static_dir: Path | None = None  # serve the built website from here (same origin as the API)
    daily_builds: int = 10  # per user, hosted mode only
    daily_chats: int = 100

    @property
    def active_model_id(self) -> str:
        """The model this backend calls: a Bedrock model id, or an Ollama tag ("auto" until resolved)."""
        return self.bedrock_model_id if self.provider == "bedrock" else self.model_id


def get_settings() -> Settings:
    load_env_file()
    env = os.environ.get
    provider = env("COACH_PROVIDER", "bedrock").strip().lower() or "bedrock"
    if provider not in PROVIDERS:
        raise ValueError(f"COACH_PROVIDER must be 'bedrock' or 'ollama', got {provider!r}")
    backend = env("COACH_MEMORY", "local").strip().lower()
    if backend not in {"local", "agentcore"}:
        raise ValueError(f"COACH_MEMORY must be 'local' or 'agentcore', got {backend!r}")
    origins = tuple(
        origin.strip().rstrip("/")
        for origin in env("COACH_ALLOWED_ORIGINS", DEFAULT_ORIGINS).split(",")
        if origin.strip()
    )
    web_search = env("COACH_WEB_SEARCH", "on").strip().lower()
    if web_search not in {"on", "off"}:
        raise ValueError(f"COACH_WEB_SEARCH must be 'on' or 'off', got {web_search!r}")
    doc_chars = Settings.max_doc_chars if provider == "bedrock" else OLLAMA_MAX_DOC_CHARS
    auth = env("COACH_AUTH", "none").strip().lower() or "none"
    if auth not in {"none", "cognito"}:
        raise ValueError(f"COACH_AUTH must be 'none' or 'cognito', got {auth!r}")
    pool = (env("COACH_COGNITO_POOL_ID") or "").strip() or None
    client = (env("COACH_COGNITO_CLIENT_ID") or "").strip() or None
    if auth == "cognito" and not (pool and client):
        raise ValueError("COACH_AUTH=cognito needs COACH_COGNITO_POOL_ID and COACH_COGNITO_CLIENT_ID")
    static = (env("COACH_STATIC_DIR") or "").strip()
    return Settings(
        auth=auth,
        cognito_pool_id=pool,
        cognito_client_id=client,
        host=env("COACH_HOST", Settings.host).strip() or Settings.host,
        static_dir=Path(static) if static else None,
        daily_builds=int(env("COACH_DAILY_BUILDS", str(Settings.daily_builds))),
        daily_chats=int(env("COACH_DAILY_CHATS", str(Settings.daily_chats))),
        provider=provider,
        bedrock_model_id=env("COACH_BEDROCK_MODEL", "").strip() or DEFAULT_BEDROCK_MODEL,
        model_id=env("COACH_MODEL", "").strip() or Settings.model_id,
        ollama_host=env("COACH_OLLAMA_HOST", Settings.ollama_host).strip(),
        num_ctx=int(env("COACH_NUM_CTX", str(Settings.num_ctx))),
        max_doc_chars=int(env("COACH_MAX_DOC_CHARS", str(doc_chars))),
        memory_backend=backend,
        agentcore_memory_id=(env("COACH_AGENTCORE_MEMORY_ID") or "").strip() or None,
        aws_region=env("AWS_REGION", env("AWS_DEFAULT_REGION", Settings.aws_region)).strip(),
        data_dir=Path(env("COACH_DATA_DIR", str(BACKEND_DIR / "data"))),
        allowed_origins=origins,
        web_search=web_search == "on",
        tavily_api_key=(env("TAVILY_API_KEY") or "").strip() or None,
    )
