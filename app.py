#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""
Flask MCP server fetch any URL, Wikipedia summary or Latvian news.
"""

from flask import Flask, request, jsonify, Response
import requests
import xml.etree.ElementTree as ET
import time
import json
from bs4 import BeautifulSoup
from bs4.element import Tag
from bs4 import NavigableString
import re
from urllib.parse import urljoin, urlparse, quote_plus
from typing import cast  # added
import os
import threading
from collections import deque, OrderedDict

app = Flask(__name__)

# System prompt loader (reads from sysprompt.md)
_SYSPROMPT_PATH = os.path.join(os.path.dirname(__file__), 'sysprompt.md')

def _load_sysprompt_file() -> str:
    try:
        with open(_SYSPROMPT_PATH, 'r', encoding='utf-8') as f:
            text = f.read()
        import re as _re
        m = _re.search(r"```\n(.*?)```", text, flags=_re.DOTALL)
        if m:
            return m.group(1).strip()
        return text.strip()
    except Exception:
        return "You are an autonomous browsing and data assistant integrated with the MCP tool server webtool-mcp. (fallback minimal prompt)"

def get_system_prompt() -> dict:
    prompt = _load_sysprompt_file()
    return {"prompt": prompt, "version": "1.1"}

# ------------------------------------------------------------------
# Helper functions
# ------------------------------------------------------------------

def fetch_url(url: str) -> dict:
    """Return raw HTML of the requested URL."""
    try:
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        return {"content": resp.text}
    except requests.RequestException as exc:
        return {"error": f"Could not fetch {url}: {exc}"}


def search_wikipedia(query: str) -> dict:
    """Get a short summary from Wikipedia REST API."""
    api_url = (
        f"https://en.wikipedia.org/api/rest_v1/page/summary/{query.replace(' ', '_')}"
    )
    try:
        resp = requests.get(api_url, timeout=5)
        resp.raise_for_status()
        data = resp.json()
        return {
            "title": data.get("title"),
            "description": data.get("description"),
            "extract": data.get("extract"),
            "url": data.get("content_urls", {}).get("desktop", {}).get("page"),
        }
    except requests.RequestException as exc:
        return {"error": f"Wikipedia fetch failed: {exc}"}


def search_duckduckgo(query: str, max_results: int = 5) -> dict:
    """Improved DuckDuckGo search.
    1) Try duckduckgo_search library for organic results.
    2) Fallback to lightweight HTML scrape.
    3) Finally fallback to Instant Answer API (may be sparse for long-tail queries).
    """
    if not query:
        return {"error": "Empty query"}
    results = []
    # Attempt library (organic results)
    try:
        from duckduckgo_search import DDGS  # type: ignore
        with DDGS() as ddgs:  # context manager handles cookies
            for r in ddgs.text(query, max_results=max_results):
                if not isinstance(r, dict):
                    continue
                title = r.get("title") or r.get("heading")
                url = r.get("href") or r.get("url")
                snippet = r.get("body") or r.get("abstract")
                if title and url:
                    results.append({"title": title, "url": url, "snippet": snippet})
        if results:
            return {
                "query": query,
                "engine": "duckduckgo",
                "results": results,
                "source": "duckduckgo_search library",
            }
    except ImportError:
        pass  # fallback below
    except Exception as exc:
        # Non-fatal; include note and fallback
        fallback_note = f"organic_error: {exc}"[:180]
    # If library failed or empty, attempt lightweight HTML scraping (best-effort; may break)
    if not results:
        try:
            r = requests.get("https://duckduckgo.com/html/", params={"q": query}, timeout=10, headers={"User-Agent": "Mozilla/5.0 webtool-mcp"})
            r.raise_for_status()
            s = BeautifulSoup(r.text, 'html.parser')
            for a in s.select('a.result__a'):
                title = _collapse(a.get_text(' '))[:240]
                href = a.get('href')
                snippet_tag = a.find_parent('div', class_='result__body')
                snippet = ''
                if snippet_tag:
                    sn = snippet_tag.select_one('.result__snippet')
                    if sn:
                        snippet = _collapse(sn.get_text(' '))[:400]
                if title and href:
                    results.append({"title": title, "url": href, "snippet": snippet})
                if len(results) >= max_results:
                    break
            if results:
                return {"query": query, "engine": "duckduckgo_html", "results": results, "source": "duckduckgo html scrape"}
        except Exception:
            pass
    # Fallback to Instant Answer
    url = "https://api.duckduckgo.com/"
    params = {"q": query, "format": "json", "no_html": 1, "skip_disambig": 1, "t": "webtool-mcp"}
    try:
        resp = requests.get(url, params=params, timeout=7)
        resp.raise_for_status()
        data = resp.json()
        abstract = data.get("Abstract") or data.get("AbstractText")
        heading = data.get("Heading")
        related = []
        for topic in data.get("RelatedTopics", [])[: max_results]:
            if isinstance(topic, dict):
                txt = topic.get("Text")
                first_url = topic.get("FirstURL")
                if txt and first_url:
                    related.append({"title": txt, "url": first_url})
        payload = {"query": query, "engine": "duckduckgo_instant", "heading": heading, "abstract": abstract, "related": related, "source": "DuckDuckGo Instant Answer"}
        if not abstract and not related:
            payload["note"] = "Instant Answer returned minimal data; consider alternate engine via web_search tool."
        return payload
    except requests.RequestException as exc:
        return {"error": f"DuckDuckGo request failed: {exc}"}


def web_search(query: str, engine: str = "duckduckgo", max_results: int = 5, engines: list[str] | None = None) -> dict:
    """Unified multi-engine web search.

    Supported engines:
      - duckduckgo (library for organic results)
      - bing (HTML scrape lightweight; may be brittle)
      - google_cse (requires env GOOGLE_API_KEY + GOOGLE_CSE_ID)
      - multi (provide list via engines=[...])
    """
    if not query:
        return {"error": "Empty query"}
    engine = (engine or "duckduckgo").lower()

    def _bing(q: str) -> list[dict]:
        search_url = "https://www.bing.com/search"
        try:
            r = requests.get(search_url, params={"q": q}, timeout=10, headers={"User-Agent": "Mozilla/5.0 webtool-mcp"})
            r.raise_for_status()
            s = BeautifulSoup(r.text, "html.parser")
            out = []
            for li in s.select("li.b_algo"):
                a = li.select_one("h2 a")
                if not a or not a.get("href"):
                    continue
                title = _collapse(a.get_text(" "))[:240]
                url2 = a.get("href")
                snippet_tag = li.select_one("p") or li.select_one("div.b_caption p")
                snippet = _collapse(snippet_tag.get_text(" "))[:400] if snippet_tag else ""
                if title and url2:
                    out.append({"title": title, "url": url2, "snippet": snippet})
                if len(out) >= max_results:
                    break
            return out
        except Exception as e:
            return [{"error": f"bing_fetch_failed: {e}"}]

    def _google_cse(q: str) -> list[dict]:
        key = os.environ.get("GOOGLE_API_KEY")
        cx = os.environ.get("GOOGLE_CSE_ID")
        if not key or not cx:
            return [{"error": "Missing GOOGLE_API_KEY or GOOGLE_CSE_ID env vars"}]
        try:
            resp = requests.get("https://www.googleapis.com/customsearch/v1", params={"key": key, "cx": cx, "q": q, "num": min(max_results, 10)}, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            items = data.get("items") or []
            out = []
            for it in items[:max_results]:
                title = it.get("title")
                link = it.get("link")
                snippet = it.get("snippet")
                if title and link:
                    out.append({"title": title, "url": link, "snippet": snippet})
            return out
        except Exception as e:
            return [{"error": f"google_cse_failed: {e}"}]

    def _duck(q: str) -> list[dict]:
        r = search_duckduckgo(q, max_results=max_results)
        if r.get("results"):
            return r["results"]  # type: ignore
        # Fallback transform of instant answer "related"
        rel = r.get("related") or []
        out = []
        for it in rel:
            title = it.get("title") or it.get("text")
            url2 = it.get("url")
            if title and url2:
                out.append({"title": title, "url": url2, "snippet": r.get("abstract") or ""})
        return out

    if engine == "multi":
        selected = engines or ["duckduckgo", "bing"]
        aggregate = {}
        for eng in selected:
            if eng == "duckduckgo":
                aggregate[eng] = _duck(query)
            elif eng == "bing":
                aggregate[eng] = _bing(query)
            elif eng == "google_cse":
                aggregate[eng] = _google_cse(query)
            else:
                aggregate[eng] = [{"error": "unsupported_engine"}]
        return {"query": query, "engine": "multi", "results": aggregate, "source": "web_search"}

    if engine == "duckduckgo":
        return {"query": query, "engine": engine, "results": _duck(query), "source": "web_search"}
    if engine == "bing":
        return {"query": query, "engine": engine, "results": _bing(query), "source": "web_search"}
    if engine == "google_cse":
        return {"query": query, "engine": engine, "results": _google_cse(query), "source": "web_search"}
    return {"error": f"Unsupported engine '{engine}'", "supported": ["duckduckgo", "bing", "google_cse", "multi"]}


def quick_search(query: str) -> dict:
    """Fast lightweight search (duckduckgo first, fallback to bing) limited to 3 results.
    Intended for initial scoping before deeper multi-engine exploration.
    """
    if not query:
        return {"error": "Empty query"}
    r = web_search(query, engine="duckduckgo", max_results=3)
    results = r.get("results") or []
    if isinstance(results, list) and results:
        return {"query": query, "engine": "duckduckgo", "results": results, "source": "quick_search"}
    # fallback single bing
    r2 = web_search(query, engine="bing", max_results=3)
    return {"query": query, "engine": "bing", "results": r2.get("results"), "source": "quick_search"}


def stock_quotes(symbols: list[str] | str) -> dict:
    """Fetch simple stock quote data via Yahoo Finance unofficial endpoint."""
    if isinstance(symbols, str):
        # split by comma/whitespace
        raw = re.split(r"[\s,]+", symbols.strip()) if symbols.strip() else []
        symbols_list = [s.upper() for s in raw if s]
    else:
        symbols_list = [s.upper() for s in symbols if s]
    if not symbols_list:
        return {"error": "No symbols provided"}
    api_url = "https://query1.finance.yahoo.com/v7/finance/quote"
    try:
        resp = requests.get(api_url, params={"symbols": ",".join(symbols_list)}, timeout=8)
        resp.raise_for_status()
        data = resp.json()
        result = []
        for quote in data.get("quoteResponse", {}).get("result", []):
            result.append({
                "symbol": quote.get("symbol"),
                "name": quote.get("shortName") or quote.get("longName"),
                "price": quote.get("regularMarketPrice"),
                "change_percent": quote.get("regularMarketChangePercent"),
                "currency": quote.get("currency"),
                "previous_close": quote.get("regularMarketPreviousClose"),
                "day_range": quote.get("regularMarketDayRange"),
                "market_state": quote.get("marketState"),
            })
        return {"quotes": result, "requested": symbols_list, "source": "Yahoo Finance (unofficial)"}
    except requests.RequestException as exc:
        return {"error": f"Stock quote fetch failed: {exc}"}


def latvian_news(query: str | None = None, limit: int = 10) -> dict:
    """Return the latest Latvian news items or topic-specific items from Google News RSS.
    If query provided, perform a topic search.
    """
    if query:
        # Google News search (lv locale)
        q = quote_plus(query)
        rss_url = f"https://news.google.com/rss/search?q={q}&hl=lv&gl=LV&ceid=LV:lv"
    else:
        rss_url = "https://news.google.com/rss?hl=lv&gl=LV&ceid=LV:lv"
    try:
        resp = requests.get(rss_url, timeout=10)
        resp.raise_for_status()
        root = ET.fromstring(resp.content)
        items = []
        for item in root.findall('.//item'):
            title = (item.findtext('title') or '').strip()
            link = (item.findtext('link') or '').strip()
            pub_date = (item.findtext('pubDate') or '').strip()
            if title and link:
                items.append({"title": title, "url": link, "published": pub_date})
            if len(items) >= limit:
                break
        return {"items": items, "query": query, "source": "Google News RSS"}
    except requests.RequestException as exc:
        return {"error": f"News fetch failed: {exc}"}


def available_functions_info() -> dict:
    """Return info about available functions and usage (legacy endpoint)."""
    info = {
        "status": "ok",
        "functions": {
            "fetch_url": {"args": {"url": "string", "chunk_id": "string?", "mode": "string? (outline)", "link_id": "string? (e.g. L7)"}},
            "search_wikipedia": {"args": {"query": "string"}},
            "latvian_news": {"args": {"query": "string?"}},
            "search_duckduckgo": {"args": {"query": "string"}},
            "stock_quotes": {"args": {"symbols": "string|list"}},
            "get_system_prompt": {"args": {}},
        },
        "usage": [
            {"name": "fetch_url", "arguments": {"url": "https://example.com"}},
            {"name": "fetch_url", "arguments": {"url": "https://example.com", "chunk_id": "sec-2"}},
            {"name": "fetch_url", "arguments": {"url": "https://example.com", "mode": "outline"}},
            {"name": "fetch_url", "arguments": {"url": "https://example.com", "link_id": "L3"}},
            {"name": "search_wikipedia", "arguments": {"query": "Python"}},
            {"name": "latvian_news", "arguments": {}},
            {"name": "latvian_news", "arguments": {"query": "tehnoloģijas"}},
            {"name": "search_duckduckgo", "arguments": {"query": "open source vector database"}},
            {"name": "quick_search", "arguments": {"query": "quick test query"}},
            {"name": "stock_quotes", "arguments": {"symbols": "AAPL, MSFT"}},
            {"name": "get_system_prompt", "arguments": {}},
        ],
    }
    return info

# JSON-RPC helpers (defined unconditionally)

def _jsonrpc_result(_id, result):
    return {"jsonrpc": "2.0", "id": _id, "result": result}


def _jsonrpc_error(_id, code, message, data=None):
    err = {"code": code, "message": message}
    if data is not None:
        err["data"] = data
    return {"jsonrpc": "2.0", "id": _id, "error": err}


def _sse_stream():
    yield "event: ready\ndata: {}\n\n"
    while True:
        yield ": keep-alive\n\n"
        time.sleep(15)

# ------------------------------------------------------------------
# Caching & Rate Limiting (new)
# ------------------------------------------------------------------

_HTML_CACHE_TTL = int(os.getenv("WEBTOOL_CACHE_TTL", "300"))  # seconds
_HTML_CACHE_MAX = int(os.getenv("WEBTOOL_HTML_CACHE_SIZE", "64"))
_OUTLINE_CACHE_TTL = int(os.getenv("WEBTOOL_OUTLINE_CACHE_TTL", "300"))
_FETCH_RATE_PER_MIN = int(os.getenv("WEBTOOL_FETCH_URL_RATE_PER_MIN", "60"))

_html_cache_lock = threading.Lock()
_outline_cache_lock = threading.Lock()

class _LRUCache:
    def __init__(self, capacity: int):
        self.capacity = capacity
        self.data: OrderedDict[str, tuple[float, str]] = OrderedDict()

    def get(self, key: str, ttl: int) -> str | None:
        now = time.time()
        with _html_cache_lock:
            item = self.data.get(key)
            if not item:
                return None
            ts, val = item
            if now - ts > ttl:
                del self.data[key]
                return None
            # move to end
            self.data.move_to_end(key)
            return val

    def put(self, key: str, value: str):
        with _html_cache_lock:
            if key in self.data:
                self.data.move_to_end(key)
            self.data[key] = (time.time(), value)
            while len(self.data) > self.capacity:
                self.data.popitem(last=False)

_html_cache = _LRUCache(_HTML_CACHE_MAX)
_outline_cache = _LRUCache(_HTML_CACHE_MAX)

_rate_lock = threading.Lock()
_fetch_timestamps = deque()  # timestamps of fetch_url network fetches

def _rate_limited_fetch_allowed() -> bool:
    """Return True if another network fetch_url is allowed under rate limit."""
    if _FETCH_RATE_PER_MIN <= 0:
        return True
    now = time.time()
    window_start = now - 60
    with _rate_lock:
        # drop old
        while _fetch_timestamps and _fetch_timestamps[0] < window_start:
            _fetch_timestamps.popleft()
        if len(_fetch_timestamps) >= _FETCH_RATE_PER_MIN:
            return False
        _fetch_timestamps.append(now)
        return True

def _cached_fetch_html(url: str) -> tuple[str | None, bool, str | None]:
    """Return (html, cache_hit, error)."""
    key = url.strip()
    html = _html_cache.get(key, _HTML_CACHE_TTL)
    if html is not None:
        return html, True, None
    # rate limiting only for real network fetches
    if not _rate_limited_fetch_allowed():
        return None, False, f"Rate limit exceeded: max {_FETCH_RATE_PER_MIN} fetch_url network requests per minute. Try later or rely on cached outline/chunks."
    res = fetch_url(url)
    if isinstance(res, dict) and res.get("error"):
        return None, False, res["error"]
    html = res.get("content", "")
    if html:
        _html_cache.put(key, html)
    return html, False, None

def _outline_cache_key(url: str) -> str:
    return f"outline::{url.strip()}"

def _get_cached_outline(url: str) -> str | None:
    return _outline_cache.get(_outline_cache_key(url), _OUTLINE_CACHE_TTL)

def _store_cached_outline(url: str, text: str):
    _outline_cache.put(_outline_cache_key(url), text)
    app.logger.debug(f"Stored outline cache for {url}")

# ------------------------------------------------------------------
# Structured page extraction (replaces earlier simple fallback)
# ------------------------------------------------------------------

_TOKEN_EST_CHARS_PER = 4  # heuristic

_HEADING_TAGS = ["h1", "h2", "h3"]

_WS_RE = re.compile(r"\s+")
_CAP_ENTITY_RE = re.compile(r"\b(?:[A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,3})\b")
_DATE_RE = re.compile(r"\b(20\d{2}|19\d{2})\b")
_NUMBER_RE = re.compile(r"\b\d{2,}\b")


def _now_iso():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _collapse(text: str) -> str:
    return _WS_RE.sub(" ", text).strip()


def _token_estimate(text: str) -> int:
    return max(1, len(text) // _TOKEN_EST_CHARS_PER)


def _select_main(soup: BeautifulSoup) -> Tag:  # revised to guarantee Tag return
    for sel in ["main", "article"]:
        tag = soup.find(sel)
        if isinstance(tag, Tag):
            return tag
    body = soup.body
    if isinstance(body, Tag):
        return body
    # BeautifulSoup itself subclasses Tag enough for our usage; cast for type checker
    return cast(Tag, soup)


def _extract_nav_links(soup: BeautifulSoup, base_url: str) -> list[dict]:
    navs = []
    for nav in soup.find_all(["nav"]):
        for a in nav.find_all("a", href=True):
            txt = _collapse(a.get_text(" "))
            if not txt:
                continue
            href = urljoin(base_url, a["href"]) if a["href"] else None
            if href:
                navs.append({"text": txt, "url": href})
    # Deduplicate by (text,url)
    seen = set()
    dedup = []
    for item in navs:
        key = (item["text"], item["url"])
        if key in seen:
            continue
        seen.add(key)
        dedup.append(item)
    return dedup[:50]


def _iter_text_nodes(node: Tag):
    for el in node.descendants:
        if isinstance(el, NavigableString):
            txt = _collapse(str(el))
            if txt:
                yield txt


def _gather_links(main: Tag, base_url: str) -> list[dict]:
    links = []
    for a in main.find_all("a", href=True):
        text = _collapse(a.get_text(" "))[:160]
        href = urljoin(base_url, a["href"]) if a["href"] else None
        if not href or not text:
            continue
        links.append({"text": text, "url": href})
    # Dedupe while preserving order
    seen = set()
    out = []
    for l in links:
        key = (l["text"], l["url"])
        if key in seen:
            continue
        seen.add(key)
        out.append(l)
    return out[:200]


def _extract_headings(main: Tag) -> list[dict]:
    headings = []
    for tag in main.find_all(_HEADING_TAGS):
        level = int(tag.name[1])
        title = _collapse(tag.get_text(" "))
        if not title:
            continue
        headings.append({"level": level, "title": title, "tag": tag})
    return headings


def _build_chunks(headings: list[dict], main: Tag) -> list[dict]:
    if not headings:
        # single chunk of all text
        text = _collapse(main.get_text(" "))
        return [{"id": "sec-1", "heading": "Document", "level": 1, "text": text}]
    chunks = []
    for idx, h in enumerate(headings):
        start_tag = h["tag"]
        # Determine stop boundary
        stop_tags = []
        for nxt in headings[idx + 1:]:
            if nxt["level"] <= h["level"]:
                stop_tags.append(nxt["tag"])
                break
        texts = []
        cur = start_tag.next_sibling
        while cur and (not stop_tags or cur != stop_tags[0]):
            if isinstance(cur, Tag):
                # Skip further headings entirely
                if cur.name in _HEADING_TAGS:
                    break
                txt = _collapse(cur.get_text(" "))
                if txt:
                    texts.append(txt)
            elif isinstance(cur, NavigableString):
                txt = _collapse(str(cur))
                if txt:
                    texts.append(txt)
            cur = cur.next_sibling
        body_text = " \n".join(texts).strip()
        chunk_id = f"sec-{idx+1}"
        chunks.append({
            "id": chunk_id,
            "heading": h["title"],
            "level": h["level"],
            "text": body_text,
            "tokens": _token_estimate(body_text),
        })
    return chunks


def _derive_outline(chunks: list[dict]) -> list[str]:
    lines = []
    for c in chunks:
        indent = "  " * (c["level"] - 1)
        lines.append(f"{indent}{c['id']} {c['heading']}")
    return lines


def _keypoints(chunks: list[dict]) -> list[str]:
    points = []
    for c in chunks[:8]:  # limit initial extraction
        if not c["text"]:
            continue
        # Take first sentence-like fragment
        frag = c["text"].split(".")[0][:180]
        if frag:
            points.append(f"{c['heading']}: {frag.strip()}.")
    return points[:12]


def _entities(full_text: str) -> dict:
    people_orgs = list(dict.fromkeys(_CAP_ENTITY_RE.findall(full_text)))[:25]
    years = list(dict.fromkeys(_DATE_RE.findall(full_text)))[:10]
    numbers = list(dict.fromkeys(_NUMBER_RE.findall(full_text)))[:15]
    return {"names": people_orgs, "years": years, "numbers": numbers}


def _snippets(chunks: list[dict]) -> list[str]:
    out = []
    for c in chunks[:10]:
        if not c["text"]:
            continue
        snippet = c["text"][:260].strip()
        out.append(f"[{c['id']}] {snippet}...")
    return out


# Link / URL cleanup helpers
_GOOGLE_NEWS_ARTICLE_RE = re.compile(r"https://news\.google\.com/rss/articles/")

def _cleanup_link(url: str) -> str:
    # For Google News redirect-style article URLs keep as-is (cannot easily unwrap w/out fetch), but remove trailing query params except required 'oc=5'
    if _GOOGLE_NEWS_ARTICLE_RE.match(url):
        # Preserve only base + optional ?oc=5
        base, _, query = url.partition('?')
        if 'oc=5' in query:
            return base + '?oc=5'
        return base
    return url


def format_structured_page(html: str, url: str, chunk_id: str | None = None, mode: str | None = None) -> str:
    """Return structured multi-section text for LLM consumption.
    Sections: META, OUTLINE, KEYPOINTS, ENTITIES, LINKS, NAV, SNIPPETS, CHUNKS, NEXT
    If chunk_id provided, return focused chunk view plus minimal META/OUTLINE context.
    """
    # (We re-use existing implementation but add early outline-only branch)
    # NOTE: This edit only appends outline mode handling at the start.
    if not html:
        return f"META\nsource: {url}\nstatus: empty\n\n"
    soup = BeautifulSoup(html, "html.parser")
    title = _collapse(soup.title.get_text()) if soup.title else ""
    meta_desc = ""
    md = soup.find("meta", attrs={"name": "description"})
    if isinstance(md, Tag):
        content = md.get("content")
        if isinstance(content, str):
            meta_desc = _collapse(content)
    main = _select_main(soup)
    headings = _extract_headings(main)
    chunks = _build_chunks(headings, main)
    full_text = " \n".join(c["text"] for c in chunks if c.get("text"))
    links = _gather_links(main, url)
    nav_links = _extract_nav_links(soup, url)
    outline_lines = _derive_outline(chunks)

    if mode == 'outline':
        link_lines = []
        for i, l in enumerate(links[:40], 1):
            link_lines.append(f"[L{i}] {l['text']} — {l['url']}")
        chunk_index_lines = [f"{c['id']} lvl={c['level']} tokens~{c['tokens']} {c['heading'][:120]}" for c in chunks[:60]]
        parts = [
            'META', f'source: {url}', f'fetched_at: {_now_iso()}', f'title: {title}', f'description: {meta_desc}' if meta_desc else '', '',
            'OUTLINE', *outline_lines[:80], '', 'LINKS', *(link_lines or ['(none)']), '', 'CHUNKS', *chunk_index_lines, '', 'NEXT', 'Request a section id (e.g. sec-2) or follow a link (e.g. L5).']
        return "\n".join([p for p in parts if p])

    # Focus mode if chunk_id requested
    focus_chunk = None
    if chunk_id:
        focus_chunk = next((c for c in chunks if c["id"].lower() == chunk_id.lower()), None)

    outline_lines = _derive_outline(chunks)

    if focus_chunk:
        neighbor_ids = [c["id"] for c in chunks]
        idx = neighbor_ids.index(focus_chunk["id"]) if focus_chunk["id"] in neighbor_ids else -1
        prev_id = neighbor_ids[idx-1] if idx > 0 else None
        next_id = neighbor_ids[idx+1] if idx >= 0 and idx < len(neighbor_ids)-1 else None
        parts = [
            "META",
            f"source: {url}",
            f"fetched_at: {_now_iso()}",
            f"title: {title}",
            f"description: {meta_desc}" if meta_desc else "",
            "",
            "OUTLINE",
            *outline_lines[:40],
            "",
            "CHUNK",
            f"id: {focus_chunk['id']}",
            f"heading: {focus_chunk['heading']}",
            f"level: {focus_chunk['level']}",
            f"tokens_est: {focus_chunk['tokens']}",
            "",
            focus_chunk["text"][:5000],
            "",
            "NEIGHBORS",
            f"previous: {prev_id or '-'}",
            f"next: {next_id or '-'}",
            "",
            "LINKS (local excerpt)",
        ]
        # limited links inside focus text
        local_links = []
        if links:
            for i, l in enumerate(links, 1):
                if len(local_links) >= 40:
                    break
                # naive filter: if link text appears in chunk text
                if l["text"] and l["text"] in focus_chunk["text"]:
                    local_links.append(f"[L{i}] {l['text']} — {l['url']}")
        parts.extend(local_links or ["(none)"])
        parts.extend([
            "",
            "NEXT",
            "You can request another section by id (e.g. sec-2) or follow a link (e.g. L5).",
        ])
        return "\n".join([p for p in parts if p is not None])

    # Global view
    kp = _keypoints(chunks)
    ents = _entities(full_text)
    snips = _snippets(chunks)

    link_lines = []
    for i, l in enumerate(links[:120], 1):
        link_lines.append(f"[L{i}] {l['text']} — {l['url']}")

    nav_lines = [f"• {n['text']} — {n['url']}" for n in nav_links[:40]]

    chunk_index_lines = [
        f"{c['id']} lvl={c['level']} tokens~{c['tokens']} {c['heading'][:120]}" for c in chunks[:80]
    ]

    parts = [
        "META",
        f"source: {url}",
        f"fetched_at: {_now_iso()}",
        f"title: {title}",
        f"description: {meta_desc}" if meta_desc else "",
        "",
        "OUTLINE",
        *outline_lines[:80],
        "",
        "KEYPOINTS",
        *(kp or ["(none extracted)"]),
        "",
        "ENTITIES",
        f"names: {', '.join(ents['names'])}" if ents.get("names") else "names: (none)",
        f"years: {', '.join(ents['years'])}" if ents.get("years") else "years: (none)",
        f"numbers: {', '.join(ents['numbers'])}" if ents.get("numbers") else "numbers: (none)",
        "",
        "LINKS",
        *(link_lines or ["(none)"]),
        "",
        "NAV",
        *(nav_lines or ["(none)"]),
        "",
        "SNIPPETS",
        *(snips or ["(none)"]),
        "",
        "CHUNKS",
        *chunk_index_lines,
        "",
        "NEXT",
        "Request a section via its id (e.g. sec-2) or ask to follow a specific link (e.g. L7).",
    ]
    return "\n".join([p for p in parts if p is not None])

# ------------------------------------------------------------------
# MCP endpoint modifications (tools list & call)
# ------------------------------------------------------------------

@app.route('/mcp', methods=['POST', 'GET'])
def mcp_endpoint():
    # Always provide SSE stream on GET (LM Studio probes this path for SSE fallback)
    if request.method == 'GET':
        headers = {
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
        return Response(_sse_stream(), headers=headers, mimetype='text/event-stream')

    # Parse JSON payload (don't fail on empty/invalid JSON)
    app.logger.debug(f"Received MCP payload: {request.data}")
    data = request.get_json(silent=True) or {}

    # If this looks like a JSON-RPC 2.0 request, handle MCP JSON-RPC methods
    if isinstance(data, dict) and data.get("jsonrpc") == "2.0" and ("method" in data or "id" in data):
        _id = data.get("id")
        method = data.get("method")
        params = data.get("params") or {}

        # initialize handshake
        if method == "initialize":
            result = {
                "protocolVersion": "2024-11-05",
                "serverInfo": {"name": "webtool-mcp", "version": "1.0.0"},
                "capabilities": {"tools": {}},
            }
            return jsonify(_jsonrpc_result(_id, result))

        # list tools
        if method in ("tools/list", "tools.list"):
            tools = [
                {
                    "name": "fetch_url",
                    "description": "Fetch and summarize a webpage with outline, links, navigation, snippets, and chunk index. Optional: fetch a specific chunk, outline-only mode, or follow a link id (L#) from the page.",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "url": {"type": "string", "description": "HTTP or HTTPS URL (base page or target if not following)"},
                            "chunk_id": {"type": "string", "description": "Optional section id to return only that chunk (e.g., sec-3)"},
                            "section": {"type": "string", "description": "Alias for chunk_id"},
                            "mode": {"type": "string", "enum": ["outline"], "description": "outline = only META/OUTLINE/LINKS/CHUNKS/NEXT"},
                            "link_id": {"type": "string", "description": "Follow a link from the base page by id (e.g. L7)"}
                        },
                        "required": ["url"],
                    },
                },
                {
                    "name": "search_wikipedia",
                    "description": "Get a short summary from Wikipedia",
                    "inputSchema": {
                        "type": "object",
                        "properties": {"query": {"type": "string", "description": "Search query"}},
                        "required": ["query"],
                    },
                },
                {
                    "name": "latvian_news",
                    "description": "Latest Latvian news headlines or topic search (optional query).",
                    "inputSchema": {
                        "type": "object",
                        "properties": {"query": {"type": "string", "description": "Optional topic term"}},
                    },
                },
                {
                    "name": "search_duckduckgo",
                    "description": "DuckDuckGo Instant Answer: abstract + related links for a query.",
                    "inputSchema": {
                        "type": "object",
                        "properties": {"query": {"type": "string", "description": "Search phrase"}},
                        "required": ["query"],
                    },
                },
                {
                    "name": "web_search",
                    "description": "Multi-engine web search (duckduckgo, bing, google_cse, multi). Returns structured result list.",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "query": {"type": "string"},
                            "engine": {"type": "string", "enum": ["duckduckgo", "bing", "google_cse", "multi"], "description": "Search engine (default duckduckgo)"},
                            "max_results": {"type": "number", "description": "Max results per engine (default 5)"},
                            "engines": {"type": "array", "items": {"type": "string"}, "description": "When engine=multi specify engines subset"}
                        },
                        "required": ["query"],
                    },
                },
                {
                    "name": "quick_search",
                    "description": "Fast small-result search (duckduckgo→bing fallback) max 3 results for scoping.",
                    "inputSchema": {
                        "type": "object",
                        "properties": {"query": {"type": "string", "description": "Search phrase"}},
                        "required": ["query"],
                    },
                },
                {
                    "name": "stock_quotes",
                    "description": "Fetch basic stock quotes for one or multiple symbols.",
                    "inputSchema": {
                        "type": "object",
                        "properties": {"symbols": {"type": "string", "description": "Comma or space separated symbols, e.g. AAPL MSFT"}},
                        "required": ["symbols"],
                    },
                },
                {
                    "name": "get_system_prompt",
                    "description": "Return the internal system prompt / guidance for tool usage.",
                    "inputSchema": {"type": "object", "properties": {}},
                },
            ]
            return jsonify(_jsonrpc_result(_id, {"tools": tools}))

        # call tool
        if method in ("tools/call", "tools.call"):
            name = None
            arguments = {}
            if isinstance(params, dict):
                name = (
                    params.get("name")
                    or params.get("toolName")
                    or params.get("function")
                    or params.get("method")
                )
                arguments = params.get("arguments") or params.get("args") or {}

            if name == "fetch_url":
                url = (arguments or {}).get("url", "")
                chunk_id = (arguments or {}).get("chunk_id") or (arguments or {}).get("section")
                mode = (arguments or {}).get("mode")
                link_id = (arguments or {}).get("link_id")
                cache_status = []
                # Use caches
                html, html_cache_hit, html_error = _cached_fetch_html(url)
                if html_error:
                    return jsonify(_jsonrpc_result(_id, {"content": [{"type": "text", "text": f"Error fetching URL: {html_error}"}]}))
                if html_cache_hit:
                    cache_status.append("html_hit")
                # Outline cache applies only when outline mode and no chunk/link follow
                if mode == 'outline' and not chunk_id and not link_id:
                    cached_outline = _get_cached_outline(url)
                    if cached_outline is not None:
                        cache_status.append("outline_hit")
                        text = cached_outline
                        # annotate (reuse injection logic later)
                        marker = "META\n"
                        insertion = f"META\ncache_status: {','.join(cache_status)}\n"
                        if marker in text:
                            text2 = text.replace(marker, insertion, 1)
                            text = text2
                        else:
                            text = insertion + text
                        return jsonify(_jsonrpc_result(_id, {"content": [{"type": "text", "text": text}]}))
                if html is None:
                    text = "Error: no HTML returned."  # should have been handled above
                else:
                    # If link_id provided, perform single-hop follow
                    if link_id and not chunk_id:
                        try:
                            base_soup = BeautifulSoup(html, 'html.parser')
                            main = _select_main(base_soup)
                            base_links = _gather_links(main, url)
                            # normalize link_id like 'L7' or '7'
                            m = re.match(r'[Ll]?(\d+)', str(link_id).strip())
                            target_structured = None
                            if not m:
                                raise ValueError(f"Invalid link_id format: {link_id}")
                            idx = int(m.group(1))
                            if idx < 1 or idx > len(base_links):
                                raise IndexError(f"link_id {link_id} out of range (1..{len(base_links)})")
                            chosen = base_links[idx-1]
                            target_url = chosen['url']
                            # fetch target
                            target_res = fetch_url(target_url)
                            if isinstance(target_res, dict) and target_res.get('error'):
                                text = f"Error following {link_id} → {target_url}: {target_res['error']}"
                            else:
                                target_html = target_res.get('content', '')
                                try:
                                    target_structured = format_structured_page(target_html, target_url, mode=mode)
                                except Exception as e:
                                    app.logger.exception("format_structured_page (follow) failed")
                                    trunc2 = target_html[:1000].replace('\n',' ')
                                    target_structured = f"Parser error on followed page: {e}\nSource: {target_url}\nSnippet: {trunc2}"
                                text = (
                                    "HISTORY\n"
                                    f"from_page: {url}\n"
                                    f"followed: {link_id} -> {target_url}\n"
                                    f"link_text: {chosen['text']}\n"
                                    "\n" + target_structured
                                )
                        except Exception as e:
                            app.logger.exception("link follow failed")
                            trunc = html[:800].replace('\n',' ')
                            text = f"Link follow error: {e}\nBase page snippet: {trunc}\nYou can retry with a different link_id or fetch without link_id."
                    else:
                        try:
                            text = format_structured_page(html, url, chunk_id=chunk_id, mode=mode)
                            # Always attempt to store if outline mode (no chunk/link)
                            if mode == 'outline' and not chunk_id and not link_id:
                                _store_cached_outline(url, text)
                        except Exception as e:
                            app.logger.exception("format_structured_page failed")
                            trunc = html[:1200].replace('\n', ' ')
                            text = f"Parser error, fallback raw snippet. Error: {e}\nSource: {url}\nSnippet: {trunc}"
                if cache_status:
                    marker = "META\n"
                    insertion = f"META\ncache_status: {','.join(cache_status)}\n"
                    if marker in text:
                        text2 = text.replace(marker, insertion, 1)
                        if text2 == text:
                            # fallback append after first line
                            lines = text.splitlines()
                            if lines and lines[0] == 'META':
                                lines.insert(1, f"cache_status: {','.join(cache_status)}")
                                text = "\n".join(lines)
                            else:
                                text = insertion + text
                        else:
                            text = text2
                    else:
                        text = insertion + text
                return jsonify(_jsonrpc_result(_id, {"content": [{"type": "text", "text": text}]}))
            if name == "search_wikipedia":
                query = (arguments or {}).get("query", "")
                res = search_wikipedia(query)
                # Keep JSON-encoded result as text, it's small
                return jsonify(_jsonrpc_result(_id, {"content": [{"type": "text", "text": json.dumps(res, ensure_ascii=False)}]}))
            if name == "latvian_news":
                q = (arguments or {}).get("query")
                res = latvian_news(q)
                items = res.get("items") if isinstance(res, dict) else None
                if items:
                    lines = [f"Latvian News{' — ' + q if q else ''}:"]
                    for it in items:
                        title = it.get("title", "").strip()
                        url2 = it.get("url", "").strip()
                        pub = it.get("published", "").strip()
                        line = f"• {title} — {url2}"
                        if pub:
                            line += f" (Published: {pub})"
                        lines.append(line)
                    text = "\n".join(lines)
                else:
                    text = json.dumps(res, ensure_ascii=False)
                return jsonify(_jsonrpc_result(_id, {"content": [{"type": "text", "text": text}]}))
            if name == "search_duckduckgo":
                query = (arguments or {}).get("query", "")
                res = search_duckduckgo(query)
                return jsonify(_jsonrpc_result(_id, {"content": [{"type": "text", "text": json.dumps(res, ensure_ascii=False)}]}))
            if name == "web_search":
                query = (arguments or {}).get("query", "")
                engine = (arguments or {}).get("engine", "duckduckgo")
                max_results = (arguments or {}).get("max_results", 5)
                engines = (arguments or {}).get("engines")
                res = web_search(query, engine=engine, max_results=max_results, engines=engines)
                return jsonify(_jsonrpc_result(_id, {"content": [{"type": "text", "text": json.dumps(res, ensure_ascii=False)}]}))
            if name == "quick_search":
                query = (arguments or {}).get("query", "")
                res = quick_search(query)
                return jsonify(_jsonrpc_result(_id, {"content": [{"type": "text", "text": json.dumps(res, ensure_ascii=False)}]}))
            if name == "stock_quotes":
                symbols = (arguments or {}).get("symbols", "")
                res = stock_quotes(symbols)
                return jsonify(_jsonrpc_result(_id, {"content": [{"type": "text", "text": json.dumps(res, ensure_ascii=False)}]}))
            if name == "get_system_prompt":
                prm = get_system_prompt()
                return jsonify(_jsonrpc_result(_id, {"content": [{"type": "text", "text": prm["prompt"]}]}))

            return jsonify(_jsonrpc_error(_id, -32601, f"Unknown tool '{name}'"))

        # Unknown JSON-RPC method
        return jsonify(_jsonrpc_error(_id, -32601, f"Unknown method '{method}'"))

    # ------------- Legacy simple payloads for manual testing -------------
    # Determine function name and arguments from either 'function'/'args' or 'name'/'arguments'
    function_name = None
    args = {}

    if isinstance(data, dict):
        if 'function' in data:
            function_name = data.get('function')
            args = data.get('args', {}) or {}
        elif 'name' in data:
            function_name = data.get('name')
            args = data.get('arguments', {}) or {}

    # If still not known, try to infer from payload keys
    payload = args if isinstance(args, dict) and args else data
    if not function_name:
        # For POSTs without JSON-RPC and no function specified, return a JSON-RPC error envelope
        # so MCP clients parsing strict JSON-RPC won't fail.
        hint = "Send JSON-RPC 2.0 or include 'function'/'name'. (If using curl, ensure -d JSON is in the same command; newline breaks will drop the body.)"
        return jsonify(_jsonrpc_error(None, -32600, "Invalid Request", {"hint": hint}))

    # Handle generic info/handshake-like names gracefully
    if function_name in ('initialize', 'list_tools', 'health', 'info'):
        result = available_functions_info()
        # Attach system prompt in legacy info for convenience
        try:
            result["system_prompt_head"] = get_system_prompt()["prompt"].splitlines()[:6]
        except Exception:
            result["system_prompt_head"] = ["(failed to load system prompt)"]
        return jsonify({"response": result})

    # Dispatch to helper functions
    if function_name == 'fetch_url':
        url = ''
        if isinstance(payload, dict):
            url = payload.get('url', '')
        result = fetch_url(url)
    elif function_name == 'search_wikipedia':
        query = ''
        if isinstance(payload, dict):
            query = payload.get('query', '')
        result = search_wikipedia(query)
    elif function_name == 'latvian_news':
        query = ''
        if isinstance(payload, dict):
            query = payload.get('query', '')
        result = latvian_news(query)
    elif function_name == 'get_system_prompt':
        result = get_system_prompt()
    else:
        # Instead of hard error, respond with info so clients don't fail to connect
        app.logger.error(f"Unknown function '{function_name}'")
        return jsonify({"response": available_functions_info(), "warning": f"Unknown function '{function_name}'"})

    # Return format expected by LM Studio's legacy manual testing: {"response": ...}
    return jsonify({"response": result})

if __name__ == "__main__":
    # Simple health check endpoint for quick diagnostics
    @app.route('/health', methods=['GET'])
    def health():
        return jsonify({"status": "ok"})

    app.run(host="0.0.0.0", port=5000)