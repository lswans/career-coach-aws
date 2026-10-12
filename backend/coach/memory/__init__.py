"""Pick the brain from settings: COACH_MEMORY=local (default) or COACH_MEMORY=agentcore."""

from __future__ import annotations

from ..config import Settings
from .base import MemoryStore


def make_store(settings: Settings) -> MemoryStore:
    if settings.memory_backend == "agentcore":
        if not settings.agentcore_memory_id:
            raise ValueError(
                "COACH_MEMORY=agentcore needs COACH_AGENTCORE_MEMORY_ID. "
                "Run: uv run python scripts/create_agentcore_memory.py"
            )
        from .agentcore import AgentCoreMemoryStore

        return AgentCoreMemoryStore(settings.agentcore_memory_id, settings.aws_region)
    from .local import LocalMemoryStore

    return LocalMemoryStore(settings.data_dir)


__all__ = ["MemoryStore", "make_store"]
