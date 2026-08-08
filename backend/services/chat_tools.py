"""Tools exposed to the news hub chat providers."""

from __future__ import annotations

import asyncio
import ipaddress
import os
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

from backend.config import DEFAULT_DB
from backend.db import connect


ToolResult = dict[str, Any]
ToolContext = dict[str, Any]

SYSTEM_PROMPT = """You are the assistant for a personal AI-news hub.
Help the user discover, understand, and compare AI-lab news stored in this hub.
Use news_search for questions about stored articles, news_get_item when an item
id is available, and news_list_feeds to explain available sources. Use live web
tools only for current information not present in the local hub. Be explicit
when information is from the local news database versus the live web. Cite
article links when available, and never invent article contents."""


def _success(data: Any) -> ToolResult:
    return {"success": True, "data": data}


def _failure(error: str) -> ToolResult:
    return {"success": False, "error": error}


def _db_path(context: ToolContext | None) -> Path | None:
    value = (context or {}).get("db_path")
    return Path(value) if value else None


def _connect(context: ToolContext | None):
    return connect(_db_path(context) or DEFAULT_DB, seed=False)


def news_search(args: dict[str, Any], context: ToolContext | None = None) -> ToolResult:
    query = str(args.get("query") or "").strip()
    if not query:
        return _failure("query is required")
    if len(query) > 500:
        return _failure("query must be 500 characters or fewer")
    try:
        limit = max(1, min(int(args.get("limit", 8)), 20))
    except (TypeError, ValueError):
        limit = 8
    terms = [term for term in query.split() if term][:12]
    clauses = []
    values: list[str] = []
    for term in terms:
        pattern = f"%{term}%"
        clauses.append(
            "(i.title LIKE ? OR i.summary LIKE ? OR i.body_markdown LIKE ?)"
        )
        values.extend([pattern, pattern, pattern])
    where = " AND ".join(clauses)
    conn = _connect(context)
    try:
        rows = conn.execute(
            f"""SELECT i.id, i.feed_id, f.name AS feed_name, i.title, i.link,
                       i.summary, i.published_at, i.body_status
                FROM items i JOIN feeds f ON f.id = i.feed_id
                WHERE {where}
                ORDER BY COALESCE(i.published_at, i.fetched_at) DESC
                LIMIT ?""",
            [*values, limit],
        ).fetchall()
        return _success(
            {
                "query": query,
                "items": [
                    {
                        "id": row["id"],
                        "feed_id": row["feed_id"],
                        "feed_name": row["feed_name"],
                        "title": row["title"],
                        "link": row["link"],
                        "summary": row["summary"],
                        "published_at": row["published_at"],
                        "body_status": row["body_status"],
                    }
                    for row in rows
                ],
            }
        )
    except Exception as exc:  # noqa: BLE001
        return _failure(f"News search failed: {exc}")
    finally:
        conn.close()


def news_get_item(args: dict[str, Any], context: ToolContext | None = None) -> ToolResult:
    try:
        item_id = int(args.get("id"))
    except (TypeError, ValueError):
        return _failure("id must be an integer")
    conn = _connect(context)
    try:
        row = conn.execute(
            """SELECT i.id, i.feed_id, f.name AS feed_name, i.guid, i.title, i.link,
                      i.summary, i.published_at, i.fetched_at, i.body_markdown,
                      i.body_status, i.body_fetched_at, i.body_error
               FROM items i JOIN feeds f ON f.id = i.feed_id WHERE i.id = ?""",
            (item_id,),
        ).fetchone()
        if not row:
            return _failure("News item not found")
        return _success(dict(row))
    finally:
        conn.close()


def news_list_feeds(
    _args: dict[str, Any], context: ToolContext | None = None
) -> ToolResult:
    conn = _connect(context)
    try:
        rows = conn.execute(
            """SELECT f.id, f.name, f.url, f.kind, f.username, COUNT(i.id) AS item_count
               FROM feeds f LEFT JOIN items i ON i.feed_id = f.id
               WHERE f.enabled = 1 GROUP BY f.id ORDER BY f.name COLLATE NOCASE"""
        ).fetchall()
        return _success({"feeds": [dict(row) for row in rows]})
    finally:
        conn.close()


def _public_url(value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    parsed = urlparse(value.strip())
    if parsed.scheme not in {"http", "https"} or parsed.username or parsed.password:
        return None
    hostname = (parsed.hostname or "").lower().strip("[]")
    if not hostname or hostname in {"localhost", "0.0.0.0", "::1"}:
        return None
    try:
        address = ipaddress.ip_address(hostname)
        if address.is_private or address.is_loopback or address.is_link_local:
            return None
    except ValueError:
        if hostname.endswith(".local") or hostname.endswith(".localhost"):
            return None
    return parsed.geturl()


# Get your Jina AI API key for free: https://jina.ai/?sui=apikey
JINA_READER = "https://r.jina.ai/"
JINA_SEARCH = "https://s.jina.ai/"
JINA_REMOVE_SELECTOR = "nav,header,footer"


def _jina_api_key() -> str:
    return os.environ.get("JINA_API_KEY", "").strip()


def _firecrawl_api_key() -> str:
    return os.environ.get("FIRECRAWL_API_KEY", "").strip()


def _web_tools_backend() -> str | None:
    """Prefer Jina (already used by enrich.py); fall back to Firecrawl."""
    if _jina_api_key():
        return "jina"
    if _firecrawl_api_key():
        return "firecrawl"
    return None


async def _jina_request(
    endpoint: str,
    payload: dict[str, Any],
    *,
    extra_headers: dict[str, str] | None = None,
    retries: int = 3,
) -> Any:
    api_key = _jina_api_key()
    if not api_key:
        raise RuntimeError("JINA_API_KEY is not configured")
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    if extra_headers:
        headers.update(extra_headers)
    last_exc: BaseException | None = None
    async with httpx.AsyncClient(timeout=60.0) as client:
        for attempt in range(1, retries + 1):
            try:
                response = await client.post(endpoint, headers=headers, json=payload)
                data = response.json()
                if response.status_code >= 400:
                    message = (
                        (data.get("error") if isinstance(data, dict) else None)
                        or f"Jina request failed ({response.status_code})"
                    )
                    if response.status_code not in {408, 425, 429, 500, 502, 503, 504}:
                        raise RuntimeError(message)
                    raise httpx.HTTPStatusError(
                        message,
                        request=response.request,
                        response=response,
                    )
                return data
            except (httpx.TransportError, httpx.TimeoutException, httpx.HTTPStatusError) as exc:
                last_exc = exc
                if attempt < retries:
                    await asyncio.sleep(min(2**attempt, 8))
    assert last_exc is not None
    raise last_exc


async def _firecrawl_request(path: str, payload: dict[str, Any]) -> Any:
    api_key = _firecrawl_api_key()
    if not api_key:
        raise RuntimeError("FIRECRAWL_API_KEY is not configured")
    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(
            f"https://api.firecrawl.dev/v2{path}",
            headers={"Authorization": f"Bearer {api_key}"},
            json=payload,
        )
    data = response.json()
    if response.status_code >= 400 or data.get("success") is False:
        raise RuntimeError(data.get("error") or f"Firecrawl failed ({response.status_code})")
    if "data" not in data:
        raise RuntimeError("Firecrawl returned no data")
    return data["data"]


def _parse_jina_reader(payload: Any, fallback_url: str) -> dict[str, str]:
    if isinstance(payload, dict) and isinstance(payload.get("data"), dict):
        data = payload["data"]
    elif isinstance(payload, dict):
        data = payload
    else:
        raise RuntimeError(f"Unexpected Jina Reader response type: {type(payload)!r}")
    content = data.get("content") or data.get("text") or data.get("markdown") or ""
    if not str(content).strip():
        raise RuntimeError("Jina Reader returned no content")
    return {
        "title": str(data.get("title") or fallback_url),
        "url": str(data.get("url") or data.get("sourceURL") or fallback_url),
        "description": str(data.get("description") or ""),
        "markdown": str(content).strip(),
    }


def _parse_jina_search(payload: Any, *, limit: int) -> list[dict[str, str]]:
    if isinstance(payload, dict) and isinstance(payload.get("data"), list):
        rows = payload["data"]
    elif isinstance(payload, list):
        rows = payload
    elif isinstance(payload, dict) and isinstance(payload.get("data"), dict):
        rows = payload["data"].get("results") or payload["data"].get("web") or []
    else:
        raise RuntimeError("Jina Search returned no results")
    results: list[dict[str, str]] = []
    for item in rows[:limit]:
        if not isinstance(item, dict):
            continue
        url = str(item.get("url") or item.get("link") or "")
        title = str(item.get("title") or url or "Untitled result")
        description = str(
            item.get("description")
            or item.get("content")
            or item.get("snippet")
            or ""
        )
        if url or title:
            results.append({"title": title, "url": url, "description": description})
    return results


async def _web_search_jina(query: str, limit: int, include_domains: list[str] | None) -> list[dict[str, str]]:
    headers: dict[str, str] = {
        # SERP metadata only — full page bodies come from web_scrape / r.jina.ai
        "X-Respond-With": "no-content",
    }
    if include_domains:
        headers["X-Site"] = include_domains[0]
    payload: dict[str, Any] = {"q": query, "num": limit}
    data = await _jina_request(JINA_SEARCH, payload, extra_headers=headers)
    return _parse_jina_search(data, limit=limit)


async def _web_search_firecrawl(
    query: str,
    limit: int,
    *,
    recency: str | None,
    include: list[str] | None,
    exclude: list[str] | None,
) -> list[dict[str, str]]:
    recency_map = {"hour": "qdr:h", "day": "qdr:d", "week": "qdr:w", "month": "qdr:m", "year": "qdr:y"}
    payload: dict[str, Any] = {"query": query, "limit": limit, "sources": ["web"]}
    if recency in recency_map:
        payload["tbs"] = recency_map[recency]
    if include:
        payload["includeDomains"] = include[:10]
    if exclude:
        payload["excludeDomains"] = exclude[:10]
    data = await _firecrawl_request("/search", payload)
    return [
        {
            "title": item.get("title") or item.get("url") or "Untitled result",
            "url": item.get("url", ""),
            "description": item.get("description", ""),
        }
        for item in (data.get("web") or [])[:limit]
    ]


async def _web_scrape_jina(url: str) -> dict[str, str]:
    data = await _jina_request(
        JINA_READER,
        {"url": url},
        extra_headers={
            "X-Return-Format": "markdown",
            "X-Retain-Images": "none",
            "X-Remove-Selector": JINA_REMOVE_SELECTOR,
        },
    )
    return _parse_jina_reader(data, url)


async def _web_scrape_firecrawl(url: str) -> dict[str, str]:
    data = await _firecrawl_request(
        "/scrape",
        {
            "url": url,
            "formats": ["markdown"],
            "onlyMainContent": True,
            "timeout": 60000,
        },
    )
    metadata = data.get("metadata") or {}
    return {
        "title": metadata.get("title") or url,
        "url": metadata.get("sourceURL") or url,
        "description": metadata.get("description") or "",
        "markdown": data.get("markdown") or "",
    }


async def web_search(args: dict[str, Any], _context: ToolContext | None = None) -> ToolResult:
    query = str(args.get("query") or "").strip()
    if not query:
        return _failure("query is required")
    if len(query) > 500:
        return _failure("query must be 500 characters or fewer")
    try:
        limit = max(1, min(int(args.get("limit", 5)), 8))
    except (TypeError, ValueError):
        limit = 5
    include = args.get("includeDomains")
    exclude = args.get("excludeDomains")
    if include and exclude:
        return _failure("includeDomains and excludeDomains cannot be combined")
    include_list = [str(item) for item in include[:10]] if isinstance(include, list) else None
    exclude_list = [str(item) for item in exclude[:10]] if isinstance(exclude, list) else None
    backend = _web_tools_backend()
    try:
        if backend == "jina":
            if exclude_list:
                return _failure("excludeDomains is only supported with FIRECRAWL_API_KEY")
            results = await _web_search_jina(query, limit, include_list)
        elif backend == "firecrawl":
            results = await _web_search_firecrawl(
                query,
                limit,
                recency=args.get("recency") if isinstance(args.get("recency"), str) else None,
                include=include_list,
                exclude=exclude_list,
            )
        else:
            return _failure("Live web tools require JINA_API_KEY or FIRECRAWL_API_KEY")
        return _success({"query": query, "results": results, "provider": backend})
    except Exception as exc:  # noqa: BLE001
        return _failure(str(exc))


async def web_scrape(args: dict[str, Any], _context: ToolContext | None = None) -> ToolResult:
    url = _public_url(args.get("url"))
    if not url:
        return _failure("A valid public HTTP or HTTPS URL is required")
    try:
        max_chars = max(1, min(int(args.get("maxChars", 12000)), 30000))
    except (TypeError, ValueError):
        max_chars = 12000
    backend = _web_tools_backend()
    try:
        if backend == "jina":
            scraped = await _web_scrape_jina(url)
        elif backend == "firecrawl":
            scraped = await _web_scrape_firecrawl(url)
        else:
            return _failure("Live web tools require JINA_API_KEY or FIRECRAWL_API_KEY")
        markdown = scraped.get("markdown") or ""
        return _success(
            {
                "title": scraped.get("title") or url,
                "url": scraped.get("url") or url,
                "description": scraped.get("description") or "",
                "markdown": markdown[:max_chars],
                "truncated": len(markdown) > max_chars,
                "provider": backend,
            }
        )
    except Exception as exc:  # noqa: BLE001
        return _failure(str(exc))


def _tool(name: str, description: str, properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {
        "name": name,
        "description": description,
        "input_schema": {
            "type": "object",
            "properties": properties,
            "required": required,
        },
    }


available_tools: list[dict[str, Any]] = [
    _tool(
        "news_search",
        "Search stored news article titles, summaries, and enriched bodies.",
        {
            "query": {"type": "string", "description": "Search terms."},
            "limit": {"type": "integer", "description": "Maximum results, 1-20."},
        },
        ["query"],
    ),
    _tool(
        "news_get_item",
        "Get one stored news item, including its full article body when available.",
        {"id": {"type": "integer", "description": "The news item id."}},
        ["id"],
    ),
    _tool(
        "news_list_feeds",
        "List enabled local news feeds and item counts.",
        {},
        [],
    ),
]

tool_executors: dict[str, Any] = {
    "news_search": news_search,
    "news_get_item": news_get_item,
    "news_list_feeds": news_list_feeds,
}

if _web_tools_backend():
    available_tools.extend(
        [
            _tool(
                "web_search",
                "Search the live web for current or externally verifiable information.",
                {
                    "query": {"type": "string"},
                    "limit": {"type": "integer"},
                    "recency": {
                        "type": "string",
                        "enum": ["hour", "day", "week", "month", "year"],
                        "description": "Firecrawl only; ignored when using Jina.",
                    },
                    "includeDomains": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "With Jina, only the first domain is applied via site filter.",
                    },
                    "excludeDomains": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Firecrawl only.",
                    },
                },
                ["query"],
            ),
            _tool(
                "web_scrape",
                "Read the main Markdown content from a public web page.",
                {
                    "url": {"type": "string"},
                    "maxChars": {"type": "integer"},
                },
                ["url"],
            ),
        ]
    )
    tool_executors.update({"web_search": web_search, "web_scrape": web_scrape})
