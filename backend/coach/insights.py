"""Bonus insights: statistics, a skill knowledge graph and trends. Pure Python, no model calls."""

from __future__ import annotations

import re
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from typing import Any

CATEGORIES = ("technical", "tool", "domain", "soft")
RATINGS = ("high", "medium", "low")
NOTE_KINDS = ("win", "learning", "certification", "project", "setback")


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "item"


def _parse_day(value: str) -> date | None:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
    except (ValueError, AttributeError):
        return None


def _readiness(profile: dict[str, Any]) -> int:
    """Share of goal-critical (high relevance) skills already at working level (3+)."""
    critical = [s for s in profile.get("skills", []) if s.get("relevance") == "high"]
    if not critical:
        return 0
    return round(100 * sum(1 for s in critical if s.get("level", 0) >= 3) / len(critical))


def _avg_level(profile: dict[str, Any]) -> float:
    levels = [s.get("level", 0) for s in profile.get("skills", [])]
    return round(sum(levels) / len(levels), 1) if levels else 0.0


def compute_stats(profile: dict[str, Any]) -> dict[str, Any]:
    """The headline numbers on the Insights tab."""
    skills = profile.get("skills", [])
    severe = sorted(profile.get("weaknesses", []), key=lambda w: RATINGS.index(w.get("severity", "low")))
    return {
        "goal_alignment": profile.get("goal_alignment", 0),
        "readiness_pct": _readiness(profile),
        "skills_total": len(skills),
        "avg_level": _avg_level(profile),
        "focus_area": severe[0]["area"] if severe else None,
    }


def build_graph(profile: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    """Nodes: you, categories, skills you have, skills to build, gaps, opportunities."""
    nodes: list[dict[str, Any]] = [{"id": "you", "label": "You", "type": "you"}]
    edges: list[dict[str, str]] = []
    skill_ids: dict[str, str] = {}
    for category in CATEGORIES:
        members = [s for s in profile.get("skills", []) if s.get("category") == category]
        if not members:
            continue
        cat_id = f"cat:{category}"
        nodes.append({"id": cat_id, "label": category.title(), "type": "category"})
        edges.append({"source": "you", "target": cat_id, "type": "has"})
        for skill in members:
            node_id = f"skill:{slug(skill['name'])}"
            if node_id in skill_ids.values():
                continue
            skill_ids[skill["name"].lower()] = node_id
            nodes.append(
                {
                    "id": node_id,
                    "label": skill["name"],
                    "type": "skill",
                    "level": skill.get("level", 0),
                    "relevance": skill.get("relevance", "low"),
                }
            )
            edges.append({"source": cat_id, "target": node_id, "type": "includes"})
    for index, gap in enumerate(profile.get("weaknesses", [])):
        gap_id = f"gap:{index}"
        nodes.append({"id": gap_id, "label": gap["area"], "type": "gap", "severity": gap.get("severity", "low")})
        edges.append({"source": "you", "target": gap_id, "type": "gap"})
    for index, opp in enumerate(profile.get("opportunities", [])):
        opp_id = f"opp:{index}"
        nodes.append({"id": opp_id, "label": opp["title"], "type": "opportunity", "timeframe": opp.get("timeframe")})
        for name in opp.get("related_skills", []):
            target = skill_ids.get(name.lower())
            if target is None:  # a skill the person does not have yet
                target = f"target:{slug(name)}"
                if all(n["id"] != target for n in nodes):
                    nodes.append({"id": target, "label": name, "type": "target"})
            edges.append({"source": opp_id, "target": target, "type": "builds"})
    return {"nodes": nodes, "edges": edges}


def build_trends(history: list[dict[str, Any]], notes: list[dict[str, Any]], today: date | None = None) -> dict[str, Any]:
    today = today or datetime.now(timezone.utc).date()
    snapshots = [
        {
            "version": p.get("version", i + 1),
            "created_at": p.get("created_at"),
            "goal_alignment": p.get("goal_alignment", 0),
            "readiness_pct": _readiness(p),
            "skills_total": len(p.get("skills", [])),
            "avg_level": _avg_level(p),
        }
        for i, p in enumerate(history)
    ]
    skill_changes: list[dict[str, Any]] = []
    new_skills: list[str] = []
    if len(history) >= 2:
        before = {s["name"].lower(): s for s in history[-2].get("skills", [])}
        for skill in history[-1].get("skills", []):
            old = before.get(skill["name"].lower())
            if old is None:
                new_skills.append(skill["name"])
            elif old.get("level") != skill.get("level"):
                skill_changes.append(
                    {"skill": skill["name"], "from": old.get("level"), "to": skill.get("level"),
                     "delta": skill.get("level", 0) - old.get("level", 0)}
                )
        skill_changes.sort(key=lambda c: -c["delta"])

    this_monday = today - timedelta(days=today.weekday())
    weeks = [this_monday - timedelta(weeks=n) for n in range(7, -1, -1)]
    buckets = {w: Counter() for w in weeks}
    for note in notes:
        day = _parse_day(str(note.get("created_at", "")))
        if day is None:
            continue
        monday = day - timedelta(days=day.weekday())
        if monday in buckets:
            buckets[monday][note.get("kind", "win")] += 1
    notes_by_week = [
        {"week_start": w.isoformat(), "total": sum(buckets[w].values()), **{k: buckets[w][k] for k in NOTE_KINDS}}
        for w in weeks
    ]
    recent = [n for n in notes if (d := _parse_day(str(n.get("created_at", "")))) and (today - d).days < 14]
    themes = Counter(n["skill"].strip() for n in notes if str(n.get("skill", "")).strip())
    alignment_delta = (
        snapshots[-1]["goal_alignment"] - snapshots[-2]["goal_alignment"] if len(snapshots) >= 2 else None
    )
    return {
        "snapshots": snapshots,
        "alignment_delta": alignment_delta,
        "skill_changes": skill_changes,
        "new_skills": new_skills,
        "notes_by_week": notes_by_week,
        "momentum_14d": len(recent),
        "themes": [{"skill": s, "count": c} for s, c in themes.most_common(5)],
        "recent_notes": sorted(notes, key=lambda n: str(n.get("created_at", "")), reverse=True)[:10],
    }


def compute_insights(history: list[dict[str, Any]], notes: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not history:
        return None
    latest = history[-1]
    return {
        "stats": compute_stats(latest),
        "graph": build_graph(latest),
        "trends": build_trends(history, notes),
    }
