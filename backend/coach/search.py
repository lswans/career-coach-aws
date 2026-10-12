"""Web search, so the coach can check facts instead of trusting a small model's memory.

- Default: ddgs, a free metasearch library that needs no account. It reads public search
  engines, so treat it as a workshop tool, not a production service.
- Set TAVILY_API_KEY to use Tavily's search API instead (free tier, no card needed).
- Set COACH_WEB_SEARCH=off to keep every query on this laptop.

What leaves the laptop: the search text only (a suggested next step, or a chat question
plus your target role). Never your documents.

A failed search never breaks a build or a chat. It raises SearchUnavailable, the caller
carries on without results, and the coach stops trying for a minute, so a dead network
costs one timeout instead of one per query.
"""

from __future__ import annotations

import asyncio
import json
import threading
import time
import urllib.request
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass

from .config import Settings

TIMEOUT_SECS = 8
COOLDOWN_SECS = 60
CACHE_SIZE = 128
CACHE_TTL_SECS = 3600


@dataclass(frozen=True)
class SearchResult:
    title: str
    url: str
    snippet: str


class SearchUnavailable(RuntimeError):
    """The web search could not run: switched off, offline, rate-limited or cooling down."""


Fetcher = Callable[[str, int], list[SearchResult]]


def ddgs_fetch(query: str, max_results: int) -> list[SearchResult]:
    from ddgs import DDGS
    from ddgs.exceptions import DDGSException

    try:
        rows = DDGS(timeout=TIMEOUT_SECS).text(query, region="us-en", safesearch="moderate", max_results=max_results)
    except DDGSException as exc:
        if str(exc) == "No results found.":  # ddgs raises this when every engine answered with nothing
            return []
        raise
    return [SearchResult(r.get("title", ""), r.get("href", ""), r.get("body", "")) for r in rows]


def tavily_fetcher(api_key: str) -> Fetcher:
    def fetch(query: str, max_results: int) -> list[SearchResult]:
        request = urllib.request.Request(
            "https://api.tavily.com/search",
            data=json.dumps({"query": query, "max_results": max_results}).encode("utf-8"),
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECS) as response:
            body = json.load(response)
        return [SearchResult(r.get("title", ""), r.get("url", ""), r.get("content", "")) for r in body.get("results", [])]

    return fetch


def clean(results: list[SearchResult], limit: int) -> list[SearchResult]:
    """Keep http(s) results that have a title, drop duplicate URLs, trim long snippets."""
    seen: set[str] = set()
    kept: list[SearchResult] = []
    for r in results:
        url, title = r.url.strip(), " ".join(r.title.split())
        if not title or not url.startswith(("https://", "http://")) or url in seen:
            continue
        seen.add(url)
        kept.append(SearchResult(title[:200], url, " ".join(r.snippet.split())[:300]))
    return kept[:limit]


class WebSearch:
    def __init__(self, name: str, fetch: Fetcher | None, clock: Callable[[], float] = time.monotonic) -> None:
        self.name = name  # "ddgs", "tavily" or "off": shown in /api/health
        self._fetch = fetch
        self._clock = clock
        self._cache: OrderedDict[tuple[str, int], tuple[float, list[SearchResult]]] = OrderedDict()
        self._down_until = 0.0
        self._lock = threading.Lock()

    @property
    def enabled(self) -> bool:
        return self._fetch is not None

    def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        if self._fetch is None:
            raise SearchUnavailable("Web search is off (COACH_WEB_SEARCH=off).")
        query = " ".join(query.split())[:300]
        key = (query.lower(), max_results)
        with self._lock:
            now = self._clock()
            hit = self._cache.get(key)
            if hit and now - hit[0] < CACHE_TTL_SECS:
                self._cache.move_to_end(key)
                return hit[1]
            if now < self._down_until:
                raise SearchUnavailable("Web search failed a moment ago, so it is paused for a minute.")
        try:
            results = clean(self._fetch(query, max_results), max_results)
        except Exception as exc:  # offline, rate limit, bad JSON: all mean "no search right now"
            with self._lock:
                self._down_until = self._clock() + COOLDOWN_SECS
            raise SearchUnavailable(f"Web search failed ({exc.__class__.__name__}).") from exc
        with self._lock:
            self._cache[key] = (self._clock(), results)
            while len(self._cache) > CACHE_SIZE:
                self._cache.popitem(last=False)
        return results

    async def asearch(self, query: str, max_results: int = 5) -> list[SearchResult]:
        """Run a search off the event loop, with a hard time limit."""
        try:
            return await asyncio.wait_for(asyncio.to_thread(self.search, query, max_results), TIMEOUT_SECS * 2)
        except TimeoutError as exc:
            with self._lock:
                self._down_until = self._clock() + COOLDOWN_SECS
            raise SearchUnavailable("Web search timed out.") from exc


def make_search(settings: Settings) -> WebSearch:
    if not settings.web_search:
        return WebSearch("off", None)
    if settings.tavily_api_key:
        return WebSearch("tavily", tavily_fetcher(settings.tavily_api_key))
    return WebSearch("ddgs", ddgs_fetch)
