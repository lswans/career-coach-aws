"""Data shapes shared by the model, the memory layer and the HTTP API."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

SkillCategory = Literal["technical", "tool", "domain", "soft"]
Rating = Literal["high", "medium", "low"]
Timeframe = Literal["this week", "this month", "this quarter", "this year"]
NoteKind = Literal["win", "learning", "certification", "project", "setback"]


class SkillAssessment(BaseModel):
    name: str
    category: SkillCategory
    level: int = Field(description="1 = beginner, 3 = working proficiency, 5 = expert; judged from evidence")
    relevance: Rating = Field(description="How much this skill matters for the stated career goals")
    evidence: list[str] = Field(description="Short phrases from the documents that prove the skill")


class Weakness(BaseModel):
    area: str
    why_it_matters: str
    severity: Rating


class Opportunity(BaseModel):
    title: str
    action: str = Field(description="A concrete next step the person can start soon")
    timeframe: Timeframe
    related_skills: list[str]


Verification = Literal["verified", "corrected", "unverified", "general", "unchecked"]


class CheckedOpportunity(Opportunity):
    """An opportunity after the web check (coach/verify.py). Stored, but never part of the model's schema,
    so the grammar can't make the model invent URLs."""

    verification: Verification = "unchecked"
    source_title: str = ""
    source_url: str = ""
    original_title: str = ""  # what the model wrote, when the check corrected it


# Bounds the model sees during constrained decoding. Python validation stays lenient
# (synthesis.clean_draft clamps instead) so a small model never fails on an off-by-one.
_ARRAY_BOUNDS = {
    "skills": (2, 10),
    "weaknesses": (1, 5),
    "opportunities": (2, 5),
    "evidence": (1, 3),
    "related_skills": (1, 4),
}
_INT_BOUNDS = {"level": (1, 5), "goal_alignment": (0, 100)}


def _bound_schema(node: Any) -> None:
    if isinstance(node, dict):
        for key, prop in (node.get("properties") or {}).items():
            if key in _ARRAY_BOUNDS and prop.get("type") == "array":
                prop["minItems"], prop["maxItems"] = _ARRAY_BOUNDS[key]
            if key in _INT_BOUNDS and prop.get("type") == "integer":
                prop["minimum"], prop["maximum"] = _INT_BOUNDS[key]
        for child in node.values():
            _bound_schema(child)
    elif isinstance(node, list):
        for child in node:
            _bound_schema(child)


class ProfileDraft(BaseModel):
    """Exactly what the model must return: small and flat so a 2-4B model can fill it."""

    headline: str
    summary: str
    target_role: str
    goal_alignment: int = Field(description="0-100: how ready the person is for the goal today")
    skills: list[SkillAssessment]
    weaknesses: list[Weakness]
    opportunities: list[Opportunity]

    @classmethod
    def model_json_schema(cls, *args: Any, **kwargs: Any) -> dict[str, Any]:  # type: ignore[override]
        schema = super().model_json_schema(*args, **kwargs)
        _bound_schema(schema)
        return schema


class SourceDoc(BaseModel):
    name: str
    kind: Literal["file", "text"]
    chars: int
    truncated: bool = False


class CareerProfile(ProfileDraft):
    opportunities: list[CheckedOpportunity]
    user_id: str
    version: int
    created_at: str  # ISO 8601, UTC
    goals: str
    sources: list[SourceDoc]
    model: str


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    session_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,99}$")


class ProgressNote(BaseModel):
    kind: NoteKind
    text: str
    skill: str = ""
    created_at: str
