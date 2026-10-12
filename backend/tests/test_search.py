import io
import json
import sys
import types

import pytest

import coach.search as search_module
from coach.config import Settings
from coach.search import SearchResult, SearchUnavailable, WebSearch, ddgs_fetch, make_search, tavily_fetcher


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def test_results_are_cleaned_and_deduplicated():
    raw = [
        SearchResult("  AWS   Certified AI Practitioner ", "https://aws.amazon.com/a", "x" * 900),
        SearchResult("Same page again", "https://aws.amazon.com/a", ""),
        SearchResult("No title", "", ""),
        SearchResult("Script", "javascript:alert(1)", ""),
        SearchResult("", "https://example.com/untitled", ""),
    ]
    results = WebSearch("t", lambda q, n: raw).search("ai practitioner")
    assert [(r.title, r.url) for r in results] == [("AWS Certified AI Practitioner", "https://aws.amazon.com/a")]
    assert len(results[0].snippet) == 300


def test_repeat_queries_come_from_the_cache():
    calls = []
    search = WebSearch("t", lambda q, n: calls.append(q) or [SearchResult("A", "https://a.example", "")])
    search.search("AWS  certification")
    search.search("aws certification")
    assert calls == ["AWS certification"]


def test_a_failure_pauses_search_for_a_minute():
    clock, calls = Clock(), []

    def flaky(query, n):
        calls.append(query)
        raise OSError("network is unreachable")

    search = WebSearch("t", flaky, clock=clock)
    with pytest.raises(SearchUnavailable):
        search.search("first")
    with pytest.raises(SearchUnavailable, match="paused"):
        search.search("second")
    assert calls == ["first"]  # the second query never reached the network
    clock.now += 61
    with pytest.raises(SearchUnavailable):
        search.search("third")
    assert calls == ["first", "third"]


def test_off_means_no_search_at_all():
    search = make_search(Settings(web_search=False))
    assert search.name == "off" and not search.enabled
    with pytest.raises(SearchUnavailable, match="off"):
        search.search("anything")
    assert make_search(Settings(tavily_api_key="tvly-x")).name == "tavily"
    assert make_search(Settings()).name == "ddgs"


def test_ddgs_no_results_is_an_empty_list_not_an_outage(monkeypatch):
    from ddgs.exceptions import DDGSException

    class FakeDDGS:
        def __init__(self, timeout):
            pass

        def text(self, query, **kwargs):
            if query == "nothing":
                raise DDGSException("No results found.")
            if query == "broken":
                raise DDGSException("engine error")
            return [{"title": "T", "href": "https://t.example", "body": "B"}]

    monkeypatch.setitem(sys.modules, "ddgs", types.SimpleNamespace(DDGS=FakeDDGS))
    assert ddgs_fetch("nothing", 5) == []
    assert ddgs_fetch("ok", 5) == [SearchResult("T", "https://t.example", "B")]
    with pytest.raises(DDGSException):
        ddgs_fetch("broken", 5)


def test_tavily_request_and_response(monkeypatch):
    sent = {}

    def fake_urlopen(request, timeout):
        sent.update(url=request.full_url, auth=request.get_header("Authorization"), body=json.loads(request.data))
        return io.BytesIO(json.dumps({"results": [{"title": "T", "url": "https://t.example", "content": "C"}]}).encode())

    monkeypatch.setattr(search_module.urllib.request, "urlopen", fake_urlopen)
    assert tavily_fetcher("tvly-key")("aws certs", 3) == [SearchResult("T", "https://t.example", "C")]
    assert sent == {"url": "https://api.tavily.com/search", "auth": "Bearer tvly-key",
                    "body": {"query": "aws certs", "max_results": 3}}
