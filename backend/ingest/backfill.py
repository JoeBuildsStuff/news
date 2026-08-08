#!/usr/bin/env python3
"""Backfill recent Anthropic posts via sitemap + page scrape.

OpenAI's RSS already includes full history, so this focuses on Anthropic,
which has no official feed and whose community mirrors are incomplete.
"""

from __future__ import annotations

import argparse
import re
import sqlite3
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from html import unescape
from pathlib import Path
from urllib.parse import urlparse

import httpx

from backend.config import DEFAULT_DB, USER_AGENT
from backend.db import connect as feed_connect

SITEMAP_URL = "https://www.anthropic.com/sitemap.xml"

SECTION_FEEDS = {
    "news": {"id": "anthropic-news", "name": "Anthropic News"},
    "engineering": {"id": "anthropic-engineering", "name": "Anthropic Engineering"},
    "research": {"id": "anthropic-research", "name": "Anthropic Research"},
}

MONTHS = {
    "jan": 1,
    "january": 1,
    "feb": 2,
    "february": 2,
    "mar": 3,
    "march": 3,
    "apr": 4,
    "april": 4,
    "may": 5,
    "jun": 6,
    "june": 6,
    "jul": 7,
    "july": 7,
    "aug": 8,
    "august": 8,
    "sep": 9,
    "sept": 9,
    "september": 9,
    "oct": 10,
    "october": 10,
    "nov": 11,
    "november": 11,
    "dec": 12,
    "december": 12,
}


def connect(db_path: Path) -> sqlite3.Connection:
    return feed_connect(db_path)


def parse_human_date(text: str) -> datetime | None:
    m = re.search(
        r"\b(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
        r"Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|"
        r"Dec(?:ember)?)\s+(\d{1,2}),?\s+(20\d{2})\b",
        text,
        re.I,
    )
    if not m:
        return None
    month = MONTHS[m.group(1).lower()]
    day = int(m.group(2))
    year = int(m.group(3))
    return datetime(year, month, day, tzinfo=timezone.utc)


def parse_iso(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


def section_for(url: str) -> str | None:
    path = urlparse(url).path.strip("/")
    parts = path.split("/")
    if len(parts) < 2:
        return None
    section = parts[0]
    if section not in SECTION_FEEDS:
        return None
    # Skip section index pages like /news or /engineering
    if len(parts) == 1:
        return None
    return section


def load_sitemap(client: httpx.Client) -> list[tuple[str, datetime | None]]:
    response = client.get(SITEMAP_URL)
    response.raise_for_status()
    root = ET.fromstring(response.content)
    ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    out: list[tuple[str, datetime | None]] = []
    for node in root.findall("sm:url", ns):
        loc = (node.findtext("sm:loc", default="", namespaces=ns) or "").strip()
        if not section_for(loc):
            continue
        lastmod_raw = (node.findtext("sm:lastmod", default="", namespaces=ns) or "").strip()
        lastmod = parse_iso(lastmod_raw) if lastmod_raw else None
        out.append((loc, lastmod))
    return out


def scrape_article(client: httpx.Client, url: str) -> dict | None:
    response = client.get(url)
    response.raise_for_status()
    html = response.text

    title_match = re.search(
        r'<meta[^>]*property="og:title"[^>]*content="([^"]+)"',
        html,
        re.I,
    ) or re.search(
        r'<meta[^>]*content="([^"]+)"[^>]*property="og:title"',
        html,
        re.I,
    )
    if not title_match:
        return None
    title = unescape(title_match.group(1)).replace(" | Anthropic", "").strip()

    published = parse_human_date(html)
    if not published:
        # Fall back to first publishedOn timestamp in page payload.
        pubs = re.findall(r'publishedOn\\":\\"([^\\]+)', html)
        pubs += re.findall(r'"publishedOn"\s*:\s*"([^"]+)"', html)
        for raw in pubs:
            published = parse_iso(raw) if "T" in raw or raw.endswith("Z") else None
            if published is None and re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw):
                published = datetime.fromisoformat(raw).replace(tzinfo=timezone.utc)
            if published:
                break
    if not published:
        return None

    desc_match = re.search(
        r'<meta[^>]*property="og:description"[^>]*content="([^"]+)"',
        html,
        re.I,
    ) or re.search(
        r'<meta[^>]*content="([^"]+)"[^>]*property="og:description"',
        html,
        re.I,
    )
    summary = unescape(desc_match.group(1)).strip() if desc_match else None

    return {
        "title": title,
        "link": url.split("?")[0],
        "summary": summary,
        "published_at": published,
    }


def upsert_item(conn: sqlite3.Connection, feed_id: str, item: dict) -> str:
    now = datetime.now(timezone.utc).isoformat()
    published = item["published_at"].isoformat()
    guid = item["link"]
    existing = conn.execute(
        "SELECT 1 FROM items WHERE feed_id = ? AND guid = ?",
        (feed_id, guid),
    ).fetchone()
    conn.execute(
        """
        INSERT INTO items (feed_id, guid, title, link, summary, published_at, fetched_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(feed_id, guid) DO UPDATE SET
            title = excluded.title,
            link = excluded.link,
            summary = COALESCE(excluded.summary, items.summary),
            published_at = excluded.published_at
        """,
        (feed_id, guid, item["title"], item["link"], item["summary"], published, now),
    )
    return "updated" if existing else "inserted"


def ensure_feed(conn: sqlite3.Connection, feed: dict, url: str) -> None:
    conn.execute(
        """
        INSERT INTO feeds (id, name, url, kind, enabled)
        VALUES (?, ?, ?, 'rss', 1)
        ON CONFLICT(id) DO UPDATE SET
            name = excluded.name,
            url = excluded.url,
            kind = 'rss'
        """,
        (feed["id"], feed["name"], url),
    )


def backfill(days: int, db_path: Path, sections: list[str], delay: float) -> None:
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    # Sitemap lastmod can lag or be edited later; widen candidate window a bit.
    candidate_cutoff = cutoff - timedelta(days=14)

    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }
    conn = connect(db_path)
    inserted = updated = skipped = errors = 0

    try:
        with httpx.Client(follow_redirects=True, timeout=30.0, headers=headers) as client:
            print(f"Loading sitemap… (keeping posts since {cutoff.date()})")
            urls = load_sitemap(client)
            candidates = []
            for loc, lastmod in urls:
                section = section_for(loc)
                if section not in sections:
                    continue
                if lastmod and lastmod < candidate_cutoff:
                    continue
                candidates.append((loc, section, lastmod))

            # Always include candidates with missing lastmod in selected sections
            # only when within widened window — already handled above when lastmod is None.
            print(f"Candidates to scrape: {len(candidates)}")

            for i, (loc, section, lastmod) in enumerate(candidates, 1):
                feed = SECTION_FEEDS[section]
                ensure_feed(conn, feed, f"https://www.anthropic.com/{section}")
                try:
                    item = scrape_article(client, loc)
                    if not item:
                        skipped += 1
                        print(f"[{i}/{len(candidates)}] skip (no metadata) {loc}")
                    elif item["published_at"] < cutoff:
                        skipped += 1
                        print(
                            f"[{i}/{len(candidates)}] skip (older than window) "
                            f"{item['published_at'].date()} {loc}"
                        )
                    else:
                        result = upsert_item(conn, feed["id"], item)
                        if result == "inserted":
                            inserted += 1
                        else:
                            updated += 1
                        print(
                            f"[{i}/{len(candidates)}] {result} "
                            f"{item['published_at'].date()} {feed['id']}: {item['title']}"
                        )
                    conn.commit()
                except Exception as exc:  # noqa: BLE001
                    errors += 1
                    conn.rollback()
                    print(f"[{i}/{len(candidates)}] error {loc}: {exc}")
                if delay:
                    time.sleep(delay)

            # Mark feeds as freshly backfilled
            now = datetime.now(timezone.utc).isoformat()
            for section in sections:
                feed = SECTION_FEEDS[section]
                conn.execute(
                    """
                    UPDATE feeds
                    SET last_fetched_at = ?, last_status = ?, last_error = NULL
                    WHERE id = ?
                    """,
                    (now, "backfill-ok", feed["id"]),
                )
            conn.commit()
    finally:
        conn.close()

    print(
        f"\nDone. inserted={inserted} updated={updated} skipped={skipped} errors={errors}"
    )
    print("OpenAI past-week items already come from RSS (`python fetch_feeds.py`).")


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill recent Anthropic posts")
    parser.add_argument("--days", type=int, default=7, help="How many days back to keep")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument(
        "--sections",
        default="news,engineering,research",
        help="Comma-separated: news,engineering,research",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=0.4,
        help="Seconds between page fetches",
    )
    args = parser.parse_args()
    sections = [s.strip() for s in args.sections.split(",") if s.strip()]
    unknown = [s for s in sections if s not in SECTION_FEEDS]
    if unknown:
        raise SystemExit(f"Unknown sections: {unknown}. Use {list(SECTION_FEEDS)}")
    backfill(args.days, args.db, sections, args.delay)


if __name__ == "__main__":
    main()
