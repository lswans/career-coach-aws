"""Carry an attendee's work over when they switch from local memory to AgentCore Memory.

Without this, switching brains in the middle of the workshop means a new, empty memory:
the app shows the setup wizard again and the attendee waits for another profile build.
"""

from __future__ import annotations

from .base import MemoryStore
from .local import LocalMemoryStore


def copy_local_to_agentcore(local: LocalMemoryStore, agentcore: MemoryStore) -> list[str]:
    """Copy each local user's profile versions and progress notes into AgentCore, once.

    A user is copied only while AgentCore has no profile for them, so restarting the
    backend never duplicates anything. Returns one line per copied user for the banner.
    """
    copied: list[str] = []
    if not local.root.exists():
        return copied
    for user_dir in sorted(p for p in local.root.iterdir() if p.is_dir()):
        user_id = user_dir.name
        profiles = local.profile_history(user_id)
        if not profiles or agentcore.profile_history(user_id):
            continue
        for profile in profiles:
            agentcore.save_profile(user_id, profile)
        notes = local.list_notes(user_id)
        for note in notes:
            agentcore.add_note(user_id, note)
        copied.append(f"{user_id}: {len(profiles)} profile version(s), {len(notes)} progress note(s)")
    return copied
