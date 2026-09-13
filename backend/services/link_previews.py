"""Unfurl URLs found in stored items into image / video / website previews."""

from __future__ import annotations

import ipaddress
import json
import re
import socket
import sqlite3
from datetime import datetime, timezone
from html import unescape
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx

from backend.db import normalize_http_url, parse_share_image

_URL_RE = re.compile(r"https?://[^\s<>\"')]+", re.I)
_META_TAG_RE = re.compile(r"<meta\b([^>]+)>", re.I)
_ATTR_RE = re.compile(r'([^\s=]+)\s*=\s*["\']([^"\']+)["\']', re.I)
_IMAGE_TYPES = {"image/jpeg", "image/jpg", "image/png", "image/gif", "image/webp", "image/avif"}
_VIDEO_TYPES = {"video/mp4", "video/webm", "video/quicktime"}
_IMAGE_EXT = (".jpg", ".jpeg", ".png", ".gif", ".webp", ".avif")
_VIDEO_EXT = (".mp4", ".webm", ".mov")
_X_HOSTS = {"x.com", "www.x.com", "twitter.com", "www.twitter.com", "pic.x.com", "pic.twitter.com"}
_UNFURL_UA = (
    "Mozilla/5.0 (compatible; news-local-fetcher/1.0; +local) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
)
_YOUTUBE_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be", "www.youtu.be"}
_VIMEO_HOSTS = {"vimeo.com", "www.vimeo.com", "player.vimeo.com"}
_MAX_HTML_BYTES = 1_000_000
_ERROR_RETRY_SECONDS = 3600


def extract_urls(text: str | None) -> list[str]:
    if not text:
        return []
    out: list[str] = []
    seen: set[str] = set()
    for raw in _URL_RE.findall(text):
        url = raw.rstrip(").,;:!?]}")
        if url and url not in seen:
            seen.add(url)
            out.append(url)
    return out


def parse_media_json(raw: object) -> list[dict[str, Any]]:
    if not raw:
        return []
    if isinstance(raw, list):
        return [item for item in raw if isinstance(item, dict)]
    try:
        data = json.loads(str(raw))
    except (TypeError, json.JSONDecodeError, ValueError):
        return []
    if not isinstance(data, list):
        return []
    return [item for item in data if isinstance(item, dict)]


def _meta_map(html: str) -> dict[str, str]:
    found: dict[str, str] = {}
    for attrs_raw in _META_TAG_RE.findall(html):
        attrs = {key.lower(): val for key, val in _ATTR_RE.findall(attrs_raw)}
        key = (attrs.get("property") or attrs.get("name") or "").lower()
        content = attrs.get("content")
        if key and content and key not in found:
            found[key] = unescape(content)
    return found


def _host(url: str) -> str:
    return urlparse(url).netloc.lower().split("@")[-1]


def is_x_status_url(url: str) -> bool:
    host = _host(url)
    if host in {"pic.x.com", "pic.twitter.com"}:
        return True
    if host not in _X_HOSTS:
        return False
    path = urlparse(url).path.lower()
    return "/status/" in path


def youtube_embed_url(url: str) -> str | None:
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    if host not in _YOUTUBE_HOSTS:
        return None
    video_id = None
    if host.endswith("youtu.be"):
        video_id = parsed.path.strip("/").split("/", 1)[0]
    else:
        if parsed.path.startswith("/embed/"):
            video_id = parsed.path.split("/embed/", 1)[-1].split("/", 1)[0]
        else:
            video_id = parse_qs(parsed.query).get("v", [None])[0]
    if not video_id or len(video_id) < 11:
        return None
    return f"https://www.youtube-nocookie.com/embed/{video_id[:11]}"


def vimeo_embed_url(url: str) -> str | None:
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    if host not in _VIMEO_HOSTS:
        return None
    parts = [p for p in parsed.path.split("/") if p]
    if host == "player.vimeo.com" and parts and parts[0] == "video" and len(parts) > 1:
        video_id = parts[1]
    elif parts and parts[0].isdigit():
        video_id = parts[0]
    else:
        return None
    if not video_id.isdigit():
        return None
    return f"https://player.vimeo.com/video/{video_id}"


def _host_is_public(host: str) -> bool:
    hostname = host.split(":")[0]
    if not hostname or hostname in {"localhost", "localhost."}:
        return False
    try:
        infos = socket.getaddrinfo(hostname, None)
    except socket.gaierror:
        return False
    for info in infos:
        addr = info[4][0]
        try:
            ip = ipaddress.ip_address(addr)
        except ValueError:
            continue
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
            or ip.is_unspecified
        ):
            return False
    return True


def url_in_corpus(conn: sqlite3.Connection, url: str) -> bool:
    like = f"%{url}%"
    row = conn.execute(
        """
        SELECT 1 FROM items
        WHERE summary LIKE ?
           OR link = ?
           OR IFNULL(body_markdown, '') LIKE ?
           OR IFNULL(media_json, '') LIKE ?
        LIMIT 1
        """,
        (like, url, like, like),
    ).fetchone()
    return row is not None


def preview_to_media(preview: dict[str, Any], *, tco: str | None = None) -> dict[str, Any] | None:
    kind = preview.get("kind")
    if kind == "image":
        url = preview.get("resolved_url") or preview.get("image_url")
        if not url:
            return None
        return {
            "kind": "photo",
            "url": url,
            "preview_url": None,
            "alt": preview.get("title"),
            "tco": tco,
        }
    if kind == "video":
        url = preview.get("video_url") or preview.get("resolved_url")
        if not url:
            return None
        return {
            "kind": "video",
            "url": url,
            "preview_url": preview.get("image_url"),
            "embed": bool(preview.get("embed")),
            "alt": preview.get("title"),
            "tco": tco,
        }
    if kind == "website":
        url = preview.get("resolved_url")
        if not url:
            return None
        return {
            "kind": "website",
            "url": url,
            "title": preview.get("title"),
            "description": preview.get("description"),
            "image_url": preview.get("image_url"),
            "site_name": preview.get("site_name"),
            "tco": tco,
        }
    return None


def _row_to_preview(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "url": row["url"],
        "resolved_url": row["resolved_url"],
        "kind": row["kind"],
        "title": row["title"],
        "description": row["description"],
        "image_url": row["image_url"],
        "video_url": row["video_url"],
        "site_name": row["site_name"],
        "status": row["status"],
        "embed": bool(row["kind"] == "video" and (row["video_url"] or "").find("embed") >= 0),
    }


def _store_preview(conn: sqlite3.Connection, url: str, payload: dict[str, Any]) -> dict[str, Any]:
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """
        INSERT INTO link_previews (
            url, resolved_url, kind, title, description, image_url, video_url,
            site_name, fetched_at, status, error
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(url) DO UPDATE SET
            resolved_url = excluded.resolved_url,
            kind = excluded.kind,
            title = excluded.title,
            description = excluded.description,
            image_url = excluded.image_url,
            video_url = excluded.video_url,
            site_name = excluded.site_name,
            fetched_at = excluded.fetched_at,
            status = excluded.status,
            error = excluded.error
        """,
        (
            url,
            payload.get("resolved_url"),
            payload.get("kind") or "skip",
            payload.get("title"),
            payload.get("description"),
            payload.get("image_url"),
            payload.get("video_url"),
            payload.get("site_name"),
            now,
            payload.get("status") or "ok",
            payload.get("error"),
        ),
    )
    conn.commit()
    payload = {**payload, "url": url}
    return payload


def _fresh_error(row: sqlite3.Row) -> bool:
    if row["status"] != "error":
        return True
    fetched = row["fetched_at"]
    try:
        ts = datetime.fromisoformat(fetched.replace("Z", "+00:00"))
    except (TypeError, ValueError, AttributeError):
        return False
    age = (datetime.now(timezone.utc) - ts).total_seconds()
    return age < _ERROR_RETRY_SECONDS


def fetch_preview(url: str) -> dict[str, Any]:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return {"kind": "skip", "status": "ok", "resolved_url": url}
    if not _host_is_public(parsed.netloc):
        return {
            "kind": "skip",
            "status": "error",
            "error": "blocked host",
            "resolved_url": url,
        }

    path = parsed.path.lower()
    if any(path.endswith(ext) for ext in _IMAGE_EXT):
        return {"kind": "image", "status": "ok", "resolved_url": url, "image_url": url}
    if any(path.endswith(ext) for ext in _VIDEO_EXT):
        return {"kind": "video", "status": "ok", "resolved_url": url, "video_url": url}

    yt = youtube_embed_url(url)
    if yt:
        return {
            "kind": "video",
            "status": "ok",
            "resolved_url": url,
            "video_url": yt,
            "embed": True,
            "site_name": "YouTube",
        }
    vimeo = vimeo_embed_url(url)
    if vimeo:
        return {
            "kind": "video",
            "status": "ok",
            "resolved_url": url,
            "video_url": vimeo,
            "embed": True,
            "site_name": "Vimeo",
        }

    headers = {
        "User-Agent": _UNFURL_UA,
        "Accept": "text/html,application/xhtml+xml,image/*,video/*,*/*;q=0.8",
    }
    try:
        with httpx.Client(follow_redirects=True, timeout=12.0, headers=headers) as client:
            response = client.get(url)
            final = str(response.url)
            if not _host_is_public(urlparse(final).netloc):
                return {
                    "kind": "skip",
                    "status": "error",
                    "error": "blocked redirect",
                    "resolved_url": final,
                }
            ctype = (response.headers.get("content-type") or "").split(";", 1)[0].strip().lower()
            if ctype in _IMAGE_TYPES or ctype.startswith("image/"):
                return {
                    "kind": "image",
                    "status": "ok",
                    "resolved_url": final,
                    "image_url": final,
                }
            if ctype in _VIDEO_TYPES or ctype.startswith("video/"):
                return {
                    "kind": "video",
                    "status": "ok",
                    "resolved_url": final,
                    "video_url": final,
                }
            if is_x_status_url(final):
                return {"kind": "skip", "status": "ok", "resolved_url": final}
            html = response.text[:_MAX_HTML_BYTES]
    except (httpx.HTTPError, OSError) as exc:
        return {
            "kind": "skip",
            "status": "error",
            "error": str(exc)[:300],
            "resolved_url": url,
        }

    yt = youtube_embed_url(final)
    if yt:
        return {
            "kind": "video",
            "status": "ok",
            "resolved_url": final,
            "video_url": yt,
            "embed": True,
            "site_name": "YouTube",
        }
    vimeo = vimeo_embed_url(final)
    if vimeo:
        return {
            "kind": "video",
            "status": "ok",
            "resolved_url": final,
            "video_url": vimeo,
            "embed": True,
            "site_name": "Vimeo",
        }

    meta = _meta_map(html)
    image = parse_share_image(html, base=final)
    video = normalize_http_url(
        meta.get("og:video:url") or meta.get("og:video") or meta.get("twitter:player:stream"),
        base=final,
    )
    title = (meta.get("og:title") or meta.get("twitter:title") or "").strip() or None
    description = (
        meta.get("og:description") or meta.get("twitter:description") or ""
    ).strip() or None
    site = (meta.get("og:site_name") or "").strip() or urlparse(final).netloc.removeprefix("www.")
    player = normalize_http_url(meta.get("twitter:player"), base=final)
    og_type = (meta.get("og:type") or "").lower()
    if video and (og_type.startswith("video") or "mp4" in (video or "")):
        return {
            "kind": "video",
            "status": "ok",
            "resolved_url": final,
            "video_url": video,
            "image_url": image,
            "title": title,
            "site_name": site,
        }
    if player and ("youtube" in player or "vimeo" in player):
        return {
            "kind": "video",
            "status": "ok",
            "resolved_url": final,
            "video_url": player,
            "image_url": image,
            "title": title,
            "embed": True,
            "site_name": site,
        }
    return {
        "kind": "website",
        "status": "ok",
        "resolved_url": final,
        "title": title,
        "description": description,
        "image_url": image,
        "site_name": site,
    }


def get_or_fetch_preview(conn: sqlite3.Connection, url: str) -> dict[str, Any]:
    row = conn.execute("SELECT * FROM link_previews WHERE url = ?", (url,)).fetchone()
    if row and _fresh_error(row):
        return _row_to_preview(row)
    payload = fetch_preview(url)
    stored = _store_preview(conn, url, payload)
    stored["embed"] = bool(payload.get("embed"))
    return stored


__all__ = [
    "extract_urls",
    "fetch_preview",
    "get_or_fetch_preview",
    "is_x_status_url",
    "parse_media_json",
    "preview_to_media",
    "url_in_corpus",
    "vimeo_embed_url",
    "youtube_embed_url",
]
