"""SQLite persistence and local file storage for the news hub chat."""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from uuid import uuid4


LOCAL_CHAT_USER_ID = os.environ.get("LOCAL_CHAT_USER_ID", "local").strip() or "local"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json(value: Any) -> str | None:
    return None if value is None else json.dumps(value, ensure_ascii=False)


def _decode(value: str | None, default: Any = None) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default


def resolve_chat_storage_dir(db_path: str | Path | None = None) -> Path:
    configured = os.environ.get("CHAT_STORAGE_DIR", "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    base = Path(db_path).expanduser().resolve().parent if db_path else Path("data").resolve()
    return base / "chat"


def ensure_chat_storage_dir(db_path: str | Path | None = None) -> Path:
    directory = resolve_chat_storage_dir(db_path)
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def resolve_safe_chat_file_path(
    storage_path: str, db_path: str | Path | None = None
) -> Path | None:
    if not storage_path or "\x00" in storage_path:
        return None
    candidate = Path(storage_path)
    if candidate.is_absolute():
        return None
    root = ensure_chat_storage_dir(db_path).resolve()
    resolved = (root / candidate).resolve()
    try:
        resolved.relative_to(root)
    except ValueError:
        return None
    return resolved


def ensure_chat_schema(conn: sqlite3.Connection) -> None:
    """Create the chat tables in the same database as feeds and items."""
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS chat_sessions (
          id TEXT PRIMARY KEY,
          user_id TEXT NOT NULL DEFAULT 'local',
          title TEXT NOT NULL DEFAULT 'New Chat',
          context TEXT,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_chat_sessions_user_updated
          ON chat_sessions(user_id, updated_at DESC);

        CREATE TABLE IF NOT EXISTS chat_messages (
          seq INTEGER PRIMARY KEY AUTOINCREMENT,
          id TEXT NOT NULL UNIQUE,
          session_id TEXT NOT NULL REFERENCES chat_sessions(id) ON DELETE CASCADE,
          parent_id TEXT REFERENCES chat_messages(id) ON DELETE SET NULL,
          role TEXT NOT NULL CHECK (role IN ('user', 'assistant', 'system')),
          content TEXT NOT NULL DEFAULT '',
          reasoning TEXT,
          context TEXT,
          function_result TEXT,
          citations TEXT,
          root_user_message_id TEXT REFERENCES chat_messages(id) ON DELETE SET NULL,
          variant_group_id TEXT,
          variant_index INTEGER NOT NULL DEFAULT 0,
          created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_chat_messages_session_seq
          ON chat_messages(session_id, seq);
        CREATE INDEX IF NOT EXISTS idx_chat_messages_parent
          ON chat_messages(parent_id);
        CREATE INDEX IF NOT EXISTS idx_chat_messages_root_user
          ON chat_messages(root_user_message_id);

        CREATE TABLE IF NOT EXISTS chat_attachments (
          id TEXT PRIMARY KEY,
          message_id TEXT NOT NULL REFERENCES chat_messages(id) ON DELETE CASCADE,
          name TEXT NOT NULL,
          mime_type TEXT NOT NULL,
          size INTEGER NOT NULL,
          storage_path TEXT NOT NULL,
          width INTEGER,
          height INTEGER,
          created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_chat_attachments_message
          ON chat_attachments(message_id);

        CREATE TABLE IF NOT EXISTS chat_tool_calls (
          id TEXT PRIMARY KEY,
          message_id TEXT NOT NULL REFERENCES chat_messages(id) ON DELETE CASCADE,
          name TEXT NOT NULL,
          arguments TEXT NOT NULL,
          result TEXT,
          reasoning TEXT,
          created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_chat_tool_calls_message
          ON chat_tool_calls(message_id);

        CREATE TABLE IF NOT EXISTS chat_suggested_actions (
          id TEXT PRIMARY KEY,
          message_id TEXT NOT NULL REFERENCES chat_messages(id) ON DELETE CASCADE,
          type TEXT NOT NULL CHECK (
            type IN ('filter', 'sort', 'navigate', 'create', 'function_call')
          ),
          label TEXT NOT NULL,
          payload TEXT NOT NULL,
          created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_chat_suggested_actions_message
          ON chat_suggested_actions(message_id);

        CREATE TABLE IF NOT EXISTS chat_branch_state (
          id TEXT PRIMARY KEY,
          session_id TEXT NOT NULL REFERENCES chat_sessions(id) ON DELETE CASCADE,
          user_message_id TEXT NOT NULL REFERENCES chat_messages(id) ON DELETE CASCADE,
          active_index INTEGER NOT NULL DEFAULT 0,
          signature TEXT,
          signatures TEXT,
          updated_at TEXT NOT NULL,
          UNIQUE (session_id, user_message_id)
        );
        CREATE INDEX IF NOT EXISTS idx_chat_branch_state_session
          ON chat_branch_state(session_id);
        """
    )
    conn.commit()


def _owned_session(conn: sqlite3.Connection, session_id: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM chat_sessions WHERE id = ? AND user_id = ?",
        (session_id, LOCAL_CHAT_USER_ID),
    ).fetchone()


def create_session(
    conn: sqlite3.Connection, title: str | None = None, context: Any = None
) -> dict[str, Any]:
    session_id, now = str(uuid4()), _now()
    title = title or "New Chat"
    conn.execute(
        """INSERT INTO chat_sessions
           (id, user_id, title, context, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (session_id, LOCAL_CHAT_USER_ID, title, _json(context), now, now),
    )
    conn.commit()
    return {
        "id": session_id,
        "title": title,
        "created_at": now,
        "updated_at": now,
        "context": context,
    }


def update_session_title(
    conn: sqlite3.Connection, session_id: str, title: str
) -> dict[str, Any] | None:
    if not _owned_session(conn, session_id):
        return None
    updated = _now()
    conn.execute(
        "UPDATE chat_sessions SET title = ?, updated_at = ? WHERE id = ? AND user_id = ?",
        (title, updated, session_id, LOCAL_CHAT_USER_ID),
    )
    conn.commit()
    return {"id": session_id, "title": title, "updated_at": updated}


def update_session_title_if_default(
    conn: sqlite3.Connection,
    session_id: str,
    title: str,
    default_title: str = "New Chat",
) -> str | None:
    session = _owned_session(conn, session_id)
    if not session:
        return None
    if session["title"] != default_title:
        return session["title"]
    updated = _now()
    result = conn.execute(
        """UPDATE chat_sessions SET title = ?, updated_at = ?
           WHERE id = ? AND user_id = ? AND title = ?""",
        (title, updated, session_id, LOCAL_CHAT_USER_ID, default_title),
    )
    conn.commit()
    if result.rowcount == 0:
        current = _owned_session(conn, session_id)
        return current["title"] if current else None
    return title


def list_sessions(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        """SELECT s.id, s.title, s.created_at, s.updated_at,
                  (SELECT COUNT(*) FROM chat_messages m WHERE m.session_id = s.id)
                  AS message_count
           FROM chat_sessions s WHERE s.user_id = ?
           ORDER BY s.updated_at DESC""",
        (LOCAL_CHAT_USER_ID,),
    ).fetchall()
    return [dict(row) for row in rows]


def get_session_summaries_by_ids(
    conn: sqlite3.Connection, session_ids: Iterable[str]
) -> list[dict[str, Any]]:
    ids = list(dict.fromkeys(item for item in session_ids if item))[:20]
    if not ids:
        return []
    placeholders = ",".join("?" for _ in ids)
    rows = conn.execute(
        f"""SELECT id, title, created_at, updated_at FROM chat_sessions
            WHERE user_id = ? AND id IN ({placeholders})""",
        [LOCAL_CHAT_USER_ID, *ids],
    ).fetchall()
    return [dict(row) for row in rows]


def delete_session(
    conn: sqlite3.Connection, session_id: str, db_path: str | Path | None = None
) -> bool:
    if not _owned_session(conn, session_id):
        return False
    paths = conn.execute(
        """SELECT a.storage_path FROM chat_attachments a
           JOIN chat_messages m ON m.id = a.message_id
           WHERE m.session_id = ?""",
        (session_id,),
    ).fetchall()
    conn.execute(
        "DELETE FROM chat_sessions WHERE id = ? AND user_id = ?",
        (session_id, LOCAL_CHAT_USER_ID),
    )
    conn.commit()
    for row in paths:
        path = resolve_safe_chat_file_path(row["storage_path"], db_path)
        if path:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
    return True


def add_message(conn: sqlite3.Connection, params: dict[str, Any]) -> dict[str, Any] | None:
    session_id = params["sessionId"]
    if not _owned_session(conn, session_id):
        return None
    message_id, created = str(uuid4()), _now()
    conn.execute(
        """INSERT INTO chat_messages
           (id, session_id, parent_id, role, content, reasoning, context,
            function_result, citations, root_user_message_id, variant_group_id,
            variant_index, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            message_id,
            session_id,
            params.get("parentId"),
            params["role"],
            params.get("content", ""),
            params.get("reasoning"),
            _json(params.get("context")),
            _json(params.get("functionResult")),
            _json(params.get("citations")),
            params.get("rootUserMessageId"),
            params.get("variantGroupId"),
            params.get("variantIndex", 0) or 0,
            created,
        ),
    )
    conn.execute(
        "UPDATE chat_sessions SET updated_at = ? WHERE id = ?", (created, session_id)
    )
    conn.commit()
    return {"id": message_id, "created_at": created}


def add_attachments(
    conn: sqlite3.Connection, message_id: str, attachments: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    created = _now()
    rows = []
    with conn:
        for attachment in attachments:
            attachment_id = str(uuid4())
            conn.execute(
                """INSERT INTO chat_attachments
                   (id, message_id, name, mime_type, size, storage_path, width,
                    height, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    attachment_id,
                    message_id,
                    attachment["name"],
                    attachment["mime_type"],
                    int(attachment["size"]),
                    attachment["storage_path"],
                    attachment.get("width"),
                    attachment.get("height"),
                    created,
                ),
            )
            rows.append(
                {
                    "id": attachment_id,
                    "name": attachment["name"],
                    "storage_path": attachment["storage_path"],
                }
            )
    return rows


def add_tool_calls(
    conn: sqlite3.Connection, message_id: str, calls: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    created, rows = _now(), []
    with conn:
        for call in calls:
            call_id = str(uuid4())
            conn.execute(
                """INSERT INTO chat_tool_calls
                   (id, message_id, name, arguments, result, reasoning, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    call_id,
                    message_id,
                    call["name"],
                    _json(call.get("arguments")) or "{}",
                    _json(call.get("result")),
                    call.get("reasoning"),
                    created,
                ),
            )
            rows.append({"id": call_id, "name": call["name"]})
    return rows


def add_suggested_actions(
    conn: sqlite3.Connection, message_id: str, actions: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    created, rows = _now(), []
    with conn:
        for action in actions:
            action_id = str(uuid4())
            conn.execute(
                """INSERT INTO chat_suggested_actions
                   (id, message_id, type, label, payload, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    action_id,
                    message_id,
                    action["type"],
                    action["label"],
                    _json(action.get("payload")) or "{}",
                    created,
                ),
            )
            rows.append(
                {"id": action_id, "type": action["type"], "label": action["label"]}
            )
    return rows


def get_messages(conn: sqlite3.Connection, session_id: str) -> list[dict[str, Any]] | None:
    if not _owned_session(conn, session_id):
        return None
    messages = conn.execute(
        "SELECT * FROM chat_messages WHERE session_id = ? ORDER BY seq ASC",
        (session_id,),
    ).fetchall()
    if not messages:
        return []
    ids = [row["id"] for row in messages]
    placeholders = ",".join("?" for _ in ids)
    attachments = conn.execute(
        f"SELECT * FROM chat_attachments WHERE message_id IN ({placeholders})", ids
    ).fetchall()
    tools = conn.execute(
        f"SELECT * FROM chat_tool_calls WHERE message_id IN ({placeholders})", ids
    ).fetchall()
    actions = conn.execute(
        f"SELECT * FROM chat_suggested_actions WHERE message_id IN ({placeholders})", ids
    ).fetchall()
    by_attachment: dict[str, list[dict[str, Any]]] = {}
    by_tool: dict[str, list[dict[str, Any]]] = {}
    by_action: dict[str, list[dict[str, Any]]] = {}
    for row in attachments:
        by_attachment.setdefault(row["message_id"], []).append(dict(row))
    for row in tools:
        item = dict(row)
        item["arguments"] = _decode(item["arguments"], {})
        item["result"] = _decode(item["result"])
        by_tool.setdefault(row["message_id"], []).append(item)
    for row in actions:
        item = dict(row)
        item["payload"] = _decode(item["payload"], {})
        by_action.setdefault(row["message_id"], []).append(item)
    result = []
    for row in messages:
        item = dict(row)
        item.update(
            {
                "context": _decode(row["context"]),
                "function_result": _decode(row["function_result"]),
                "citations": _decode(row["citations"]),
                "chat_attachments": by_attachment.get(row["id"], []),
                "chat_tool_calls": by_tool.get(row["id"], []),
                "chat_suggested_actions": by_action.get(row["id"], []),
            }
        )
        result.append(item)
    return result


def set_active_variant(
    conn: sqlite3.Connection, params: dict[str, Any]
) -> dict[str, Any] | None:
    session_id, user_message_id = params["sessionId"], params["userMessageId"]
    if not _owned_session(conn, session_id):
        return None
    updated = _now()
    existing = conn.execute(
        "SELECT id FROM chat_branch_state WHERE session_id = ? AND user_message_id = ?",
        (session_id, user_message_id),
    ).fetchone()
    if existing:
        branch_id = existing["id"]
        conn.execute(
            """UPDATE chat_branch_state SET active_index = ?, signature = ?,
               signatures = ?, updated_at = ? WHERE id = ?""",
            (
                params["activeIndex"],
                params.get("signature"),
                _json(params.get("signatures")),
                updated,
                branch_id,
            ),
        )
    else:
        branch_id = str(uuid4())
        conn.execute(
            """INSERT INTO chat_branch_state
               (id, session_id, user_message_id, active_index, signature,
                signatures, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                branch_id,
                session_id,
                user_message_id,
                params["activeIndex"],
                params.get("signature"),
                _json(params.get("signatures")),
                updated,
            ),
        )
    conn.execute("UPDATE chat_sessions SET updated_at = ? WHERE id = ?", (updated, session_id))
    conn.commit()
    return {"id": branch_id, "active_index": params["activeIndex"]}


def get_branch_state(
    conn: sqlite3.Connection, session_id: str
) -> list[dict[str, Any]] | None:
    if not _owned_session(conn, session_id):
        return None
    rows = conn.execute(
        """SELECT user_message_id, active_index, signature, signatures
           FROM chat_branch_state WHERE session_id = ?""",
        (session_id,),
    ).fetchall()
    return [
        {
            "user_message_id": row["user_message_id"],
            "active_index": row["active_index"],
            "signature": row["signature"],
            "signatures": _decode(row["signatures"]),
        }
        for row in rows
    ]


def get_session_title(
    conn: sqlite3.Connection, session_id: str
) -> dict[str, str] | None:
    session = _owned_session(conn, session_id)
    return {"id": session["id"], "title": session["title"]} if session else None
