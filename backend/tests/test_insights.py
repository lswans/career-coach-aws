from datetime import date

from coach.insights import build_graph, build_trends, compute_insights, compute_stats
from tests.conftest import make_draft


def profile(version: int, **overrides):
    data = make_draft(**overrides).model_dump()
    data.update(version=version, created_at=f"2026-10-0{version}T12:00:00Z")
    return data


def test_stats_summarize_the_latest_profile():
    stats = compute_stats(profile(1))
    assert stats == {
        "goal_alignment": 42,
        "readiness_pct": 100,  # the one high-relevance skill (Python) is at level 4
        "skills_total": 3,
        "avg_level": 3.3,
        "focus_area": "Model deployment on AWS",
    }


def test_graph_links_opportunities_to_known_and_missing_skills():
    graph = build_graph(profile(1))
    ids = {n["id"]: n for n in graph["nodes"]}
    assert ids["you"]["type"] == "you"
    assert ids["skill:python"]["level"] == 4
    assert ids["target:aws"]["type"] == "target"  # AWS is wanted but not yet a skill
    builds = {(e["source"], e["target"]) for e in graph["edges"] if e["type"] == "builds"}
    assert ("opp:0", "skill:python") in builds and ("opp:0", "target:aws") in builds
    assert all(e["source"] in ids and e["target"] in ids for e in graph["edges"])


def test_trends_compare_snapshots_and_bucket_notes_by_week():
    before = profile(1)
    after = profile(2, goal_alignment=55)
    after["skills"][1]["level"] = 4  # SQL 3 -> 4
    after["skills"].append({"name": "Docker", "category": "tool", "level": 2, "relevance": "high", "evidence": ["x"]})
    notes = [
        {"kind": "certification", "text": "Passed CCP", "skill": "AWS", "created_at": "2026-10-05T10:00:00Z"},
        {"kind": "win", "text": "Deployed API", "skill": "AWS", "created_at": "2026-09-29T10:00:00Z"},
        {"kind": "learning", "text": "Old note", "skill": "", "created_at": "2025-01-01T10:00:00Z"},
    ]
    trends = build_trends([before, after], notes, today=date(2026, 10, 6))
    assert trends["alignment_delta"] == 13
    assert trends["skill_changes"] == [{"skill": "SQL", "from": 3, "to": 4, "delta": 1}]
    assert trends["new_skills"] == ["Docker"]
    assert len(trends["notes_by_week"]) == 8
    assert trends["notes_by_week"][-1] == {"week_start": "2026-10-05", "total": 1, "win": 0, "learning": 0,
                                           "certification": 1, "project": 0, "setback": 0}
    assert trends["notes_by_week"][-2]["win"] == 1
    assert trends["momentum_14d"] == 2
    assert trends["themes"] == [{"skill": "AWS", "count": 2}]
    assert trends["recent_notes"][0]["text"] == "Passed CCP"


def test_no_history_means_no_insights():
    assert compute_insights([], []) is None
