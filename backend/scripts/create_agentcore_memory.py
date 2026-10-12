"""Create (or reuse) the coach's AgentCore Memory, then switch the backend to it.

    uv run python scripts/create_agentcore_memory.py             # create, then update backend/.env
    uv run python scripts/create_agentcore_memory.py --delete    # clean up when you're done

Needs AWS credentials in your terminal (aws configure, or aws login). Pay-per-use: a
workshop's worth of events and records costs well under $1. The memory lives in your own
AWS account, next to the Claude model the coach calls on Amazon Bedrock.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from coach.envfile import ENV_FILE, read_env, write_env  # noqa: E402

MEMORY_NAME = "CareerCoachMemory"
STRATEGIES = [
    {"semanticMemoryStrategy": {"name": "CareerFacts", "namespaceTemplates": ["/facts/{actorId}/"]}},
    {"userPreferenceMemoryStrategy": {"name": "CoachingPreferences", "namespaceTemplates": ["/preferences/{actorId}/"]}},
    {"summaryMemoryStrategy": {"name": "SessionSummaries", "namespaceTemplates": ["/summaries/{actorId}/{sessionId}/"]}},
]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--region", default=os.environ.get("AWS_REGION") or read_env().get("AWS_REGION") or "us-east-1")
    parser.add_argument("--delete", action="store_true", help="Delete the memory and switch back to local memory")
    args = parser.parse_args()

    import boto3
    from bedrock_agentcore.memory import MemoryClient

    try:
        account = boto3.client("sts", region_name=args.region).get_caller_identity()["Account"]
    except Exception as exc:
        print(f"No working AWS credentials ({exc.__class__.__name__}). Run 'aws configure' or 'aws login' first.")
        return 1
    client = MemoryClient(region_name=args.region)

    if args.delete:
        memory_id = read_env().get("COACH_AGENTCORE_MEMORY_ID")
        if not memory_id:
            print("No COACH_AGENTCORE_MEMORY_ID in backend/.env; nothing to delete.")
            return 0
        print(f"Deleting {memory_id} from account {account} ({args.region}) ...")
        client.delete_memory_and_wait(memory_id)
        write_env({"COACH_MEMORY": "local", "COACH_AGENTCORE_MEMORY_ID": None})
        print("Deleted. The backend is back on local memory.")
        return 0

    print(f"Creating or reusing '{MEMORY_NAME}' in account {account} ({args.region}). This can take 2-3 minutes ...")
    memory = client.create_or_get_memory(
        name=MEMORY_NAME,
        strategies=STRATEGIES,
        description="Career Coach workshop: chat history, extracted facts and preferences, progress notes",
        event_expiry_days=365,  # the maximum: profiles and progress notes are events, so they last this long
    )
    memory_id = memory.get("id") or memory.get("memoryId")
    if not memory_id:
        print(f"Unexpected response: {memory}")
        return 1
    write_env({"COACH_MEMORY": "agentcore", "COACH_AGENTCORE_MEMORY_ID": memory_id, "AWS_REGION": args.region})
    print(f"Memory ready: {memory_id} (status {memory.get('status', 'ACTIVE')})")
    print(f"Wrote {ENV_FILE}. Restart the backend to use it.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
