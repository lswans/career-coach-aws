from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from strands.models import Model

from coach.config import Settings
from coach.memory.local import LocalMemoryStore
from coach.schemas import Opportunity, ProfileDraft, SkillAssessment, Weakness
from coach.search import SearchResult, WebSearch
from coach.verify import OfferingCheck

SAMPLE_DIR = Path(__file__).resolve().parents[2] / "sample-data"
GOALS = (SAMPLE_DIR / "jordan-goals.txt").read_text(encoding="utf-8").strip()


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(bedrock_model_id="test-model", data_dir=tmp_path / "data", web_search=False)


@pytest.fixture
def store(settings: Settings) -> LocalMemoryStore:
    return LocalMemoryStore(settings.data_dir)


class FakeSearch(WebSearch):
    """WebSearch with canned results per query word, and a switch to simulate an outage."""

    def __init__(self, results: dict[str, list[SearchResult]] | None = None, down: bool = False) -> None:
        super().__init__("fake", self._lookup)
        self.results = results or {}
        self.down = down
        self.queries: list[str] = []

    def _lookup(self, query: str, max_results: int) -> list[SearchResult]:
        self.queries.append(query)
        if self.down:
            raise OSError("network is unreachable")
        return next((r for key, r in self.results.items() if key.lower() in query.lower()), [])


class FakeChecker:
    """Stands in for the next-step check call: returns a canned OfferingCheck per step title word."""

    def __init__(self, answers: dict[str, OfferingCheck] | None = None) -> None:
        self.answers = answers or {}
        self.prompts: list[str] = []

    async def structured_output(self, output_model, prompt, system_prompt=None, **kwargs):
        text = prompt[0]["content"][0]["text"]
        self.prompts.append(text)
        step = text.splitlines()[0]
        yield {"output": next((a for key, a in self.answers.items() if key in step), OfferingCheck(named="", real_match=""))}


def make_draft(**overrides: Any) -> ProfileDraft:
    base = dict(
        headline="CS student who ships data pipelines",
        summary="You build Python data tools and want to move into ML engineering.",
        target_role="Machine Learning Engineer",
        goal_alignment=42,
        skills=[
            SkillAssessment(name="Python", category="technical", level=4, relevance="high",
                            evidence=["Built a Python ETL job"]),
            SkillAssessment(name="SQL", category="technical", level=3, relevance="medium",
                            evidence=["PostgreSQL"]),
            SkillAssessment(name="Mentoring", category="soft", level=3, relevance="low",
                            evidence=["Mentored 3 first-year students"]),
        ],
        weaknesses=[Weakness(area="Model deployment on AWS", why_it_matters="Core to ML engineering",
                             severity="high")],
        opportunities=[
            Opportunity(title="Deploy the review classifier", action="Serve it behind an API on AWS",
                        timeframe="this month", related_skills=["Python", "AWS"]),
            Opportunity(title="Mock interviews", action="Two live-coding mocks per week",
                        timeframe="this week", related_skills=["Interviewing"]),
        ],
    )
    base.update(overrides)
    return ProfileDraft(**base)


class FakeStructuredModel:
    """Stands in for OllamaModel.structured_output during synthesis."""

    def __init__(self, draft: ProfileDraft | None = None) -> None:
        self.draft = draft or make_draft()
        self.prompts: list[str] = []
        self.system_prompt: str | None = None

    async def structured_output(self, output_model, prompt, system_prompt=None, **kwargs):
        self.prompts.append(prompt[0]["content"][0]["text"])
        self.system_prompt = system_prompt
        yield {"output": self.draft}


class FakeExtractor:
    """Stands in for the progress-extraction model call."""

    def __init__(self, result: Any = None) -> None:
        self.result = result
        self.calls: list[str] = []

    async def structured_output(self, output_model, prompt, system_prompt=None, **kwargs):
        self.calls.append(prompt[0]["content"][0]["text"])
        yield {"output": self.result}


class ScriptedChatModel(Model):
    """A real Strands Model that replays scripted turns: plain text, or one tool call."""

    def __init__(self, turns: list[dict[str, Any]] | None = None) -> None:
        self.turns = list(turns or [])
        self.calls: list[dict[str, Any]] = []

    def update_config(self, **model_config: Any) -> None:
        pass

    def get_config(self) -> dict[str, Any]:
        return {}

    async def structured_output(self, output_model, prompt, system_prompt=None, **kwargs):
        raise NotImplementedError
        yield  # pragma: no cover

    async def stream(self, messages, tool_specs=None, system_prompt=None, **kwargs):
        self.calls.append({"messages": json.loads(json.dumps(messages, default=str)),
                           "system_prompt": system_prompt,
                           "tools": [t["name"] for t in tool_specs or []]})
        turn = self.turns.pop(0) if self.turns else {"text": "Keep going!"}
        yield {"messageStart": {"role": "assistant"}}
        if "tool" in turn:
            yield {"contentBlockStart": {"start": {"toolUse": {"toolUseId": f"tool-{len(self.calls)}",
                                                               "name": turn["tool"]}}}}
            yield {"contentBlockDelta": {"delta": {"toolUse": {"input": json.dumps(turn["input"])}}}}
            yield {"contentBlockStop": {}}
            stop = "tool_use"
        else:
            yield {"contentBlockStart": {"start": {}}}
            words = turn["text"].split(" ")
            for i, word in enumerate(words):
                yield {"contentBlockDelta": {"delta": {"text": word + (" " if i < len(words) - 1 else "")}}}
            yield {"contentBlockStop": {}}
            stop = "end_turn"
        yield {"messageStop": {"stopReason": stop}}
        yield {"metadata": {"usage": {"inputTokens": 1, "outputTokens": 1, "totalTokens": 2},
                            "metrics": {"latencyMs": 1}}}
