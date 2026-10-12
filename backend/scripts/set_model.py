"""Choose the coach's model, then check that it works. Writes backend/.env for you.

    uv run python scripts/set_model.py bedrock              # default: Claude Haiku 5.5 on Amazon Bedrock
    uv run python scripts/set_model.py bedrock <model-id>   # another Bedrock model, for example
                                                            #   us.anthropic.claude-haiku-4-5-20251001-v1:0
    uv run python scripts/set_model.py ollama               # free local model, no AWS account needed
    uv run python scripts/set_model.py ollama qwen3:1.7b    # a specific local model

The Bedrock check sends Claude one word (about a ten-thousandth of a cent). The first call is
also what switches the model on for a new AWS account. Restart the backend afterwards.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from coach import bedrock  # noqa: E402
from coach.config import get_settings  # noqa: E402
from coach.envfile import ENV_FILE, write_env  # noqa: E402
from coach.llm import ollama_status  # noqa: E402


def main(argv: list[str]) -> int:
    if len(argv) not in (2, 3) or argv[1] not in {"bedrock", "ollama"}:
        print(__doc__)
        return 1
    provider = argv[1]
    model = argv[2].strip() if len(argv) == 3 else ""
    if provider == "bedrock":
        write_env({"COACH_PROVIDER": "bedrock", "COACH_BEDROCK_MODEL": model or None})
    else:
        write_env({"COACH_PROVIDER": "ollama", "COACH_MODEL": None if model in ("", "auto") else model})
    settings = get_settings()
    print(f"Wrote COACH_PROVIDER={provider} to {ENV_FILE}.")
    if provider == "bedrock":
        label = bedrock.model_label(settings.bedrock_model_id)
        print(f"Checking {label} ({settings.bedrock_model_id}) in {settings.aws_region} ...")
        status = bedrock.status(settings, fresh=True)
        ok = f"OK: {label} answered."
    else:
        status = ollama_status(settings)
        ok = f"OK: Ollama is running and {status['model']} is pulled."
    if not status["model_ready"]:
        print(f"Not ready: {status['detail']}")
        return 1
    print(f"{ok} Restart the backend to use it.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
