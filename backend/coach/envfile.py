"""Read and merge backend/.env without a BOM (Windows PowerShell 5.1 adds one; this never does)."""

from __future__ import annotations

from pathlib import Path

from .config import ENV_FILE


def read_env(path: Path = ENV_FILE) -> dict[str, str]:
    if not path.exists():
        return {}
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        if "=" in line and not line.strip().startswith("#"):
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip()
    return values


def write_env(updates: dict[str, str | None], path: Path = ENV_FILE) -> None:
    """Merge updates into the file. A value of None removes that key."""
    values = read_env(path)
    for key, value in updates.items():
        if value is None:
            values.pop(key, None)
        else:
            values[key] = value
    path.write_text("".join(f"{k}={v}\n" for k, v in values.items()), encoding="utf-8")
