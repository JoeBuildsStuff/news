"""FastAPI routes for chat persistence, files, and provider streaming."""

from __future__ import annotations

import json
import mimetypes
import os
import re
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Body, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from backend.config import DEFAULT_DB
from backend.db import connect
from backend.services import chat_db
from backend.services.chat_providers import (
    ChatAttachment,
    ChatRequest,
    generate_title,
    stream_anthropic,
    stream_cerebras,
    stream_openai,
    stream_xai,
)


router = APIRouter()
_db_path: Path = DEFAULT_DB
MAX_FILE_SIZE = 25 * 1024 * 1024
MAX_IMAGE_SIZE = 10 * 1024 * 1024
ALLOWED_IMAGES = {"image/jpeg", "image/png", "image/gif", "image/webp"}


def configure(db_path: Path | None = None) -> None:
    global _db_path
    if db_path is not None:
        _db_path = db_path
    elif os.environ.get("DB_PATH"):
        _db_path = Path(os.environ["DB_PATH"])


@contextmanager
def _conn():
    conn = connect(_db_path)
    try:
        yield conn
    finally:
        conn.close()


class SessionCreate(BaseModel):
    title: str | None = Field(default=None, max_length=200)
    context: Any = None


class SessionTitle(BaseModel):
    title: str = Field(min_length=1, max_length=200)


class MessageCreate(BaseModel):
    role: str
    content: str = ""
    parentId: str | None = None
    reasoning: str | None = None
    context: Any = None
    functionResult: Any = None
    citations: Any = None
    rootUserMessageId: str | None = None
    variantGroupId: str | None = None
    variantIndex: int | None = 0


class BranchUpdate(BaseModel):
    userMessageId: str
    activeIndex: int
    signature: str | None = None
    signatures: list[str] | None = None
    signatures: list[str] | None = None


@router.post("/api/chat/sessions")
def create_chat_session(body: SessionCreate | None = None) -> dict[str, Any]:
    with _conn() as conn:
        return {"data": chat_db.create_session(conn, body.title if body else None, body.context if body else None)}


@router.get("/api/chat/sessions")
def list_chat_sessions() -> dict[str, Any]:
    with _conn() as conn:
        return {"data": chat_db.list_sessions(conn)}


@router.get("/api/chat/sessions/summaries")
def get_chat_summaries(ids: str = Query("")) -> dict[str, Any]:
    with _conn() as conn:
        return {"data": chat_db.get_session_summaries_by_ids(conn, ids.split(","))}


@router.patch("/api/chat/sessions/{session_id}")
def patch_chat_session(session_id: str, body: SessionTitle) -> dict[str, Any]:
    with _conn() as conn:
        result = chat_db.update_session_title(conn, session_id, body.title.strip())
    if not result:
        raise HTTPException(status_code=404, detail="Chat not found")
    return {"data": result}


@router.delete("/api/chat/sessions/{session_id}")
def remove_chat_session(session_id: str) -> dict[str, Any]:
    with _conn() as conn:
        removed = chat_db.delete_session(conn, session_id, _db_path)
    if not removed:
        raise HTTPException(status_code=404, detail="Chat not found")
    return {"data": {"success": True}}


@router.get("/api/chat/sessions/{session_id}/messages")
def list_chat_messages(session_id: str) -> dict[str, Any]:
    with _conn() as conn:
        result = chat_db.get_messages(conn, session_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Chat not found")
    return {"data": result}


@router.post("/api/chat/sessions/{session_id}/messages")
def create_chat_message(session_id: str, body: MessageCreate) -> dict[str, Any]:
    if body.role not in {"user", "assistant", "system"}:
        raise HTTPException(status_code=400, detail="Invalid message role")
    params = body.model_dump()
    params["sessionId"] = session_id
    with _conn() as conn:
        result = chat_db.add_message(conn, params)
    if not result:
        raise HTTPException(status_code=404, detail="Chat not found")
    return {"data": result}


def _json_body(body: Any, key: str) -> list[dict[str, Any]]:
    if isinstance(body, list):
        return body
    if isinstance(body, dict) and isinstance(body.get(key), list):
        return body[key]
    return []


@router.post("/api/chat/messages/{message_id}/attachments")
def create_chat_attachments(message_id: str, body: Any = Body(...)) -> dict[str, Any]:
    attachments = _json_body(body, "attachments")
    with _conn() as conn:
        try:
            result = chat_db.add_attachments(conn, message_id, attachments)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"data": result}


@router.post("/api/chat/messages/{message_id}/tool-calls")
def create_chat_tool_calls(message_id: str, body: Any = Body(...)) -> dict[str, Any]:
    calls = _json_body(body, "calls")
    with _conn() as conn:
        try:
            result = chat_db.add_tool_calls(conn, message_id, calls)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"data": result}


@router.post("/api/chat/messages/{message_id}/suggested-actions")
def create_chat_actions(message_id: str, body: Any = Body(...)) -> dict[str, Any]:
    actions = _json_body(body, "actions")
    with _conn() as conn:
        try:
            result = chat_db.add_suggested_actions(conn, message_id, actions)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"data": result}


@router.post("/api/chat/sessions/{session_id}/branch")
def update_chat_branch(session_id: str, body: BranchUpdate) -> dict[str, Any]:
    params = body.model_dump()
    params["sessionId"] = session_id
    with _conn() as conn:
        result = chat_db.set_active_variant(conn, params)
    if not result:
        raise HTTPException(status_code=404, detail="Chat not found")
    return {"data": result}


@router.get("/api/chat/sessions/{session_id}/branch")
def get_chat_branch(session_id: str) -> dict[str, Any]:
    with _conn() as conn:
        result = chat_db.get_branch_state(conn, session_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Chat not found")
    return {"data": result}


def _safe_name(name: str, fallback: str) -> str:
    return re.sub(r"[^a-zA-Z0-9._-]", "_", name)[:120] or fallback


def _storage_path(name: str, prefix: str = "chat") -> tuple[str, Path]:
    clean_prefix = prefix.strip().strip("/").replace("\\", "/")
    if not clean_prefix or ".." in Path(clean_prefix).parts or Path(clean_prefix).is_absolute():
        raise HTTPException(status_code=400, detail="Invalid storage path")
    relative = Path(clean_prefix) / chat_db.LOCAL_CHAT_USER_ID / f"{uuid4()}-{_safe_name(name, 'file')}"
    absolute = chat_db.resolve_safe_chat_file_path(relative.as_posix(), _db_path)
    if not absolute:
        raise HTTPException(status_code=400, detail="Invalid storage path")
    return relative.as_posix(), absolute


async def _save_upload(
    upload: UploadFile,
    *,
    image: bool,
    path_prefix: str,
) -> tuple[str, int]:
    if not upload.filename:
        raise HTTPException(status_code=400, detail="Missing file name")
    mime_type = upload.content_type or "application/octet-stream"
    if image and mime_type not in ALLOWED_IMAGES:
        raise HTTPException(status_code=400, detail=f"Unsupported image type: {mime_type}")
    limit = MAX_IMAGE_SIZE if image else MAX_FILE_SIZE
    data = await upload.read(limit + 1)
    if len(data) > limit:
        raise HTTPException(
            status_code=400,
            detail=f"{'Image' if image else 'File'} is larger than {limit // (1024 * 1024)}MB",
        )
    relative, absolute = _storage_path(upload.filename, path_prefix)
    absolute.parent.mkdir(parents=True, exist_ok=True)
    absolute.write_bytes(data)
    return relative, len(data)


@router.post("/api/files/upload")
async def upload_file(
    file: UploadFile = File(...), pathPrefix: str = Form("chat")
) -> dict[str, Any]:
    path, size = await _save_upload(file, image=False, path_prefix=pathPrefix)
    return {"success": True, "filePath": path, "url": path, "size": size}


@router.post("/api/images/upload")
async def upload_image(
    file: UploadFile = File(...), pathPrefix: str = Form("chat")
) -> dict[str, Any]:
    path, size = await _save_upload(file, image=True, path_prefix=pathPrefix)
    return {"success": True, "filePath": path, "url": path, "size": size}


@router.get("/api/files/serve")
def serve_file(path: str) -> FileResponse:
    absolute = chat_db.resolve_safe_chat_file_path(path, _db_path)
    if not absolute or not absolute.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(absolute, media_type=mimetypes.guess_type(absolute.name)[0])


@router.get("/api/images/serve")
def serve_image(path: str) -> FileResponse:
    absolute = chat_db.resolve_safe_chat_file_path(path, _db_path)
    if not absolute or not absolute.is_file():
        raise HTTPException(status_code=404, detail="Image not found")
    if mimetypes.guess_type(absolute.name)[0] not in ALLOWED_IMAGES:
        raise HTTPException(status_code=400, detail="Not an image")
    return FileResponse(absolute, media_type=mimetypes.guess_type(absolute.name)[0])


async def _parse_chat_request(request: Request) -> ChatRequest:
    content_type = request.headers.get("content-type", "")
    attachments: list[ChatAttachment] = []
    if "multipart/form-data" in content_type or "application/x-www-form-urlencoded" in content_type:
        form = await request.form()
        get = lambda name, default="": str(form.get(name, default) or default)
        try:
            context = json.loads(get("context")) if get("context") not in {"", "null"} else None
        except ValueError:
            context = None
        try:
            messages = json.loads(get("messages")) if get("messages") else []
        except ValueError:
            messages = []
        count = max(0, min(int(get("attachmentCount", "0") or 0), 20))
        for index in range(count):
            item = form.get(f"attachment-{index}")
            if not isinstance(item, UploadFile):
                continue
            data = await item.read(MAX_FILE_SIZE + 1)
            if len(data) > MAX_FILE_SIZE:
                raise HTTPException(status_code=400, detail="Attachment is larger than 25MB")
            mime_type = get(f"attachment-{index}-type", item.content_type or "application/octet-stream")
            attachments.append(
                ChatAttachment(
                    name=get(f"attachment-{index}-name", item.filename or f"attachment-{index}"),
                    mime_type=mime_type,
                    size=int(get(f"attachment-{index}-size", str(len(data))) or len(data)),
                    data=data,
                )
            )
        return ChatRequest(
            message=get("message"),
            context=context,
            messages=messages if isinstance(messages, list) else [],
            model=get("model") or None,
            reasoning_effort=get("reasoning_effort") or None,
            client_tz=get("client_tz"),
            client_utc_offset=get("client_utc_offset"),
            client_now_iso=get("client_now_iso"),
            client_path=get("client_path"),
            web_search_enabled=get("web_search_enabled", "true") != "false",
            attachments=attachments,
            db_path=str(_db_path),
        )
    payload = await request.json()
    return ChatRequest(
        message=str(payload.get("message") or ""),
        context=payload.get("context"),
        messages=payload.get("messages") or [],
        model=payload.get("model"),
        reasoning_effort=payload.get("reasoning_effort"),
        client_tz=str(payload.get("client_tz") or ""),
        client_utc_offset=str(payload.get("client_utc_offset") or ""),
        client_now_iso=str(payload.get("client_now_iso") or ""),
        client_path=str(payload.get("client_path") or ""),
        web_search_enabled=payload.get("web_search_enabled", True) is not False,
        db_path=str(_db_path),
    )


def _provider_key(provider: str) -> str:
    return {
        "anthropic": "ANTHROPIC_API_KEY",
        "openai": "OPENAI_API_KEY",
        "xai": "XAI_API_KEY",
        "cerebras": "CEREBRAS_API_KEY",
    }[provider]


async def _stream_provider(request: Request, provider: str) -> Any:
    parsed = await _parse_chat_request(request)
    if not parsed.message.strip():
        return JSONResponse({"message": "Invalid message content"}, status_code=400)
    key = _provider_key(provider)
    if not os.environ.get(key, "").strip():
        return JSONResponse(
            {"message": f"{provider.title()} service is not configured. Set {key}."},
            status_code=503,
        )
    stream = {
        "anthropic": stream_anthropic,
        "openai": stream_openai,
        "xai": stream_xai,
        "cerebras": stream_cerebras,
    }[provider](parsed)
    return StreamingResponse(
        stream,
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/api/chat/anthropic")
async def chat_anthropic(request: Request) -> Any:
    return await _stream_provider(request, "anthropic")


@router.post("/api/chat/openai")
async def chat_openai(request: Request) -> Any:
    return await _stream_provider(request, "openai")


@router.post("/api/chat/xai")
async def chat_xai(request: Request) -> Any:
    return await _stream_provider(request, "xai")


@router.post("/api/chat/cerebras")
async def chat_cerebras(request: Request) -> Any:
    return await _stream_provider(request, "cerebras")


@router.post("/api/chat/title")
async def chat_title(request: Request) -> dict[str, Any]:
    content_type = request.headers.get("content-type", "")
    if "multipart/form-data" in content_type:
        form = await request.form()
        session_id = str(form.get("sessionId") or "").strip()
        message = str(form.get("message") or "").strip()
    else:
        payload = await request.json()
        session_id = str(payload.get("sessionId") or "").strip()
        message = str(payload.get("message") or "").strip()
    if not session_id or not message:
        raise HTTPException(status_code=400, detail="sessionId and message are required")
    with _conn() as conn:
        session = chat_db.get_session_title(conn, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Chat not found")
    if session["title"] != "New Chat":
        return {"title": session["title"], "skipped": True}
    if not os.environ.get("CEREBRAS_API_KEY", "").strip() and not os.environ.get(
        "ANTHROPIC_API_KEY", ""
    ).strip():
        return JSONResponse(
            {"error": "CEREBRAS_API_KEY or ANTHROPIC_API_KEY is required"},
            status_code=503,
        )
    provider = "cerebras" if os.environ.get("CEREBRAS_API_KEY") else "anthropic"
    try:
        title = await generate_title(message, provider)
    except RuntimeError as exc:
        return JSONResponse({"error": str(exc)}, status_code=502)
    with _conn() as conn:
        updated = chat_db.update_session_title_if_default(conn, session_id, title)
    return {"title": updated or session["title"]}
