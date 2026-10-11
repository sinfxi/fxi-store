"""Grounded educational web search for DarsYar.

Searches Wikimedia's public API and a web search engine, returns short excerpts
with source URLs, and never treats retrieved pages as instructions.
"""
from __future__ import annotations

import asyncio
from html import unescape
from urllib.parse import parse_qs, urlparse

import aiohttp
from bs4 import BeautifulSoup

TIMEOUT = aiohttp.ClientTimeout(total=10, connect=4)
USER_AGENT = "DarsYarStudyBot/2.0 (+educational search)"
TRUSTED_DOMAINS = (
    "roshd.ir", "chap.sch.ir", "gama.ir", "hamyarbook.ir", "asan-dars.ir",
    "openstax.org", "khanacademy.org", "britannica.com", "nasa.gov",
    "phet.colorado.edu", "mit.edu", "wikipedia.org",
)

def _clean(value: str, limit: int = 600) -> str:
    return " ".join(BeautifulSoup(unescape(value or ""), "html.parser").get_text(" ", strip=True).split())[:limit]

def _unwrap_url(raw: str) -> str:
    parsed = urlparse(raw)
    if parsed.hostname and parsed.hostname.endswith("duckduckgo.com"):
        target = parse_qs(parsed.query).get("uddg", [""])[0]
        if target:
            raw = target
    parsed = urlparse(raw)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return ""
    return raw

def _trusted(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return any(host == domain or host.endswith("." + domain) for domain in TRUSTED_DOMAINS)

async def _wikipedia(session: aiohttp.ClientSession, language: str, query: str) -> list[dict]:
    endpoint = f"https://{language}.wikipedia.org/w/api.php"
    params = {"action": "query", "list": "search", "srsearch": query[:180],
              "srlimit": "3", "format": "json", "utf8": "1"}
    try:
        async with session.get(endpoint, params=params) as response:
            response.raise_for_status()
            payload = await response.json(content_type=None)
        results = []
        for item in payload.get("query", {}).get("search", []):
            title = _clean(item.get("title", ""), 180)
            snippet = _clean(item.get("snippet", ""), 520)
            page_id = item.get("pageid")
            if title and page_id:
                results.append({"title": title, "snippet": snippet,
                                "url": f"https://{language}.wikipedia.org/?curid={page_id}",
                                "source": f"{language}.wikipedia.org"})
        return results
    except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, TypeError):
        return []

async def _web_search(session: aiohttp.ClientSession, query: str) -> list[dict]:
    site_filter = " OR ".join(f"site:{domain}" for domain in TRUSTED_DOMAINS if domain != "wikipedia.org")
    search_query = f"{query[:180]} ({site_filter} OR site:fa.wikipedia.org OR site:en.wikipedia.org)"
    try:
        async with session.get("https://html.duckduckgo.com/html/",
                               params={"q": search_query},
                               headers={"User-Agent": USER_AGENT}) as response:
            response.raise_for_status()
            html = await response.text()
        soup = BeautifulSoup(html, "html.parser")
        results = []
        for item in soup.select(".result"):
            anchor = item.select_one(".result__a")
            snippet_el = item.select_one(".result__snippet")
            if not anchor:
                continue
            title = _clean(anchor.get_text(" ", strip=True), 180)
            url = _unwrap_url(anchor.get("href", ""))
            snippet = _clean(snippet_el.get_text(" ", strip=True) if snippet_el else "", 520)
            if title and url and _trusted(url):
                results.append({"title": title, "snippet": snippet, "url": url,
                                "source": urlparse(url).hostname or ""})
            if len(results) >= 5:
                break
        return results
    except (aiohttp.ClientError, asyncio.TimeoutError, ValueError):
        return []

async def search_study_sources(query: str, limit: int = 5) -> list[dict]:
    """Return deduplicated, domain-checked educational search results."""
    query = " ".join((query or "").split())[:350]
    if len(query) < 2:
        return []
    headers = {"User-Agent": USER_AGENT}
    async with aiohttp.ClientSession(timeout=TIMEOUT, headers=headers) as session:
        batches = await asyncio.gather(
            _web_search(session, query),
            _wikipedia(session, "fa", query),
            _wikipedia(session, "en", query),
            return_exceptions=True,
        )
    merged = []
    seen = set()
    for batch in batches:
        if isinstance(batch, Exception):
            continue
        for item in batch:
            url = item.get("url", "")
            if not url or url in seen:
                continue
            seen.add(url)
            merged.append(item)
    return merged[:max(1, min(int(limit), 8))]
