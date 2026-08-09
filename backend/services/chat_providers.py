"""Provider adapters for the news chat SSE protocol.

The public functions yield bytes containing:
``event: delta|tool_call|tool_result|done|error`` SSE frames.
"""

from __future__ import annotations

import base64
import inspect
import json
import os
from dataclasses import dataclass, field
from typing import Any, AsyncIterator

from backend.services.chat_tools import SYSTEM_PROMPT, available_tools, tool_executors


@dataclass
class ChatAttachment:
    name: str
    mime_type: str
    size: int
    data: bytes = b""


@dataclass
class ChatRequest:
    message: str
    context: Any = None
    messages: list[dict[str, Any]] = field(default_factory=list)
    model: str | None = None
    reasoning_effort: str | None = None
    client_tz: str = ""
    client_utc_offset: str = ""
    client_now_iso: str = ""
    client_path: str = ""
    web_search_enabled: bool = True
    attachments: list[ChatAttachment] = field(default_factory=list)
    db_path: str | None = None


def sse(event: str, data: Any) -> bytes:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n".encode()


def _system_prompt(request: ChatRequest) -> str:
    prompt = SYSTEM_PROMPT
    if not request.web_search_enabled:
        prompt += "\n\nLive web access is disabled for this request."
    if request.client_tz or request.client_utc_offset or request.client_now_iso:
        prompt += (
            "\n\nUser locale context:"
            f"\n- Timezone: {request.client_tz or 'unknown'}"
            f"\n- UTC offset: {request.client_utc_offset or 'unknown'}"
            f"\n- Local time: {request.client_now_iso or 'unknown'}"
        )
    if request.client_path:
        prompt += f"\n\nCurrent app path: {request.client_path}"
    if request.context:
        prompt += f"\n\nCurrent news view context:\n{json.dumps(request.context, default=str)[:12000]}"
    return prompt


def _attachment_text(attachments: list[ChatAttachment]) -> str:
    if not attachments:
        return ""
    return "\n\n".join(
        f"File attachment: {a.name} ({a.mime_type}, {a.size} bytes)"
        for a in attachments
        if not a.mime_type.startswith("image/")
    )


def _history(request: ChatRequest) -> list[dict[str, Any]]:
    messages = []
    for item in request.messages[-20:]:
        role = item.get("role")
        content = item.get("content", "")
        if role in {"user", "assistant"} and isinstance(content, str):
            messages.append({"role": role, "content": content})
    user_text = request.message
    extra = _attachment_text(request.attachments)
    if extra:
        user_text = f"{user_text}\n\n{extra}" if user_text else extra
    messages.append({"role": "user", "content": user_text})
    return messages


def _anthropic_user_content(request: ChatRequest) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = [{"type": "text", "text": request.message}]
    for attachment in request.attachments:
        if attachment.mime_type in {"image/jpeg", "image/png", "image/gif", "image/webp"}:
            blocks.append(
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": attachment.mime_type,
                        "data": base64.b64encode(attachment.data).decode(),
                    },
                }
            )
        else:
            blocks.append(
                {
                    "type": "text",
                    "text": f"File attachment: {attachment.name} ({attachment.mime_type}, {attachment.size} bytes)",
                }
            )
    return blocks


def _openai_messages(request: ChatRequest) -> list[dict[str, Any]]:
    messages = [{"role": "system", "content": _system_prompt(request)}]
    messages.extend(_history(request)[:-1])
    content: Any = request.message
    if request.attachments:
        parts: list[dict[str, Any]] = [{"type": "text", "text": request.message}]
        for attachment in request.attachments:
            if attachment.mime_type.startswith("image/"):
                parts.append(
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{attachment.mime_type};base64,{base64.b64encode(attachment.data).decode()}",
                        },
                    }
                )
            else:
                parts.append(
                    {
                        "type": "text",
                        "text": f"File attachment: {attachment.name} ({attachment.mime_type}, {attachment.size} bytes)",
                    }
                )
        content = parts
    messages.append({"role": "user", "content": content})
    return messages


def _enabled_tools(request: ChatRequest) -> list[dict[str, Any]]:
    if request.web_search_enabled:
        return available_tools
    return [
        tool
        for tool in available_tools
        if tool["name"] not in {"web_search", "web_scrape"}
    ]


def _tool_defs_anthropic(request: ChatRequest) -> list[dict[str, Any]]:
    return [
        {
            "name": tool["name"],
            "description": tool["description"],
            "input_schema": tool["input_schema"],
        }
        for tool in _enabled_tools(request)
    ]


def _tool_defs_openai(request: ChatRequest) -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "function": {
                "name": tool["name"],
                "description": tool["description"],
                "parameters": tool["input_schema"],
            },
        }
        for tool in _enabled_tools(request)
    ]


def _tool_defs_openai_responses(request: ChatRequest) -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "name": tool["name"],
            "description": tool["description"],
            "parameters": tool["input_schema"],
        }
        for tool in _enabled_tools(request)
    ]


def _responses_input_from_request(request: ChatRequest) -> list[dict[str, Any]]:
    """Build Responses API input items from chat history + current turn."""
    items: list[dict[str, Any]] = []
    for item in _history(request)[:-1]:
        items.append({"role": item["role"], "content": item["content"]})
    if request.attachments:
        parts: list[dict[str, Any]] = [{"type": "input_text", "text": request.message}]
        for attachment in request.attachments:
            if attachment.mime_type.startswith("image/"):
                parts.append(
                    {
                        "type": "input_image",
                        "image_url": (
                            f"data:{attachment.mime_type};base64,"
                            f"{base64.b64encode(attachment.data).decode()}"
                        ),
                    }
                )
            else:
                parts.append(
                    {
                        "type": "input_text",
                        "text": (
                            f"File attachment: {attachment.name} "
                            f"({attachment.mime_type}, {attachment.size} bytes)"
                        ),
                    }
                )
        items.append({"role": "user", "content": parts})
    else:
        items.append({"role": "user", "content": request.message})
    return items


async def _execute_tool(
    name: str, arguments: dict[str, Any], request: ChatRequest
) -> dict[str, Any]:
    executor = tool_executors.get(name)
    if not executor:
        return {"success": False, "error": f"Unknown tool: {name}"}
    augmented = {
        **arguments,
        "client_tz": request.client_tz,
        "client_utc_offset": request.client_utc_offset,
        "client_now_iso": request.client_now_iso,
    }
    try:
        result = executor(augmented, {"db_path": request.db_path})
        if inspect.isawaitable(result):
            result = await result
        return result
    except Exception as exc:  # noqa: BLE001
        return {"success": False, "error": str(exc)}


def _citations(tool_calls: list[dict[str, Any]]) -> list[dict[str, str]]:
    citations: list[dict[str, str]] = []
    seen: set[str] = set()
    for call in tool_calls:
        result = call.get("result") or {}
        data = result.get("data") if isinstance(result, dict) else None
        candidates = []
        if isinstance(data, dict):
            candidates.extend(data.get("results") or [])
            candidates.extend(data.get("items") or [])
            if data.get("url"):
                candidates.append(data)
        for item in candidates:
            if not isinstance(item, dict) or not item.get("url"):
                continue
            url = str(item["url"])
            if url in seen:
                continue
            seen.add(url)
            citations.append(
                {
                    "url": url,
                    "title": str(item.get("title") or item.get("feed_name") or url),
                    "cited_text": str(item.get("description") or item.get("summary") or ""),
                }
            )
    return citations


def _max_tool_iterations() -> int:
    try:
        return max(1, min(int(os.environ.get("WEB_SEARCH_MAX_USES", "5")), 10))
    except ValueError:
        return 5


async def stream_anthropic(request: ChatRequest) -> AsyncIterator[bytes]:
    """Stream Anthropic text and run custom tools until a final response."""
    try:
        from anthropic import AsyncAnthropic

        client = AsyncAnthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
        messages: list[dict[str, Any]] = [
            {"role": item["role"], "content": item["content"]}
            for item in _history(request)[:-1]
        ]
        messages.append({"role": "user", "content": _anthropic_user_content(request)})
        tool_calls: list[dict[str, Any]] = []
        final_text = ""
        for _ in range(_max_tool_iterations()):
            content_blocks: list[Any] = []
            async with client.messages.stream(
                model=request.model or "claude-sonnet-4-20250514",
                max_tokens=4096,
                system=_system_prompt(request),
                messages=messages,
                tools=_tool_defs_anthropic(request) or None,
            ) as stream:
                async for text in stream.text_stream:
                    final_text += text
                    yield sse("delta", {"delta": text})
                response = await stream.get_final_message()
            content_blocks = response.content
            tool_blocks = [
                block for block in content_blocks if getattr(block, "type", None) == "tool_use"
            ]
            if not tool_blocks:
                break
            results = []
            for block in tool_blocks:
                tool_id = getattr(block, "id", "")
                name = getattr(block, "name", "")
                arguments = getattr(block, "input", {}) or {}
                yield sse("tool_call", {"id": tool_id, "name": name, "arguments": arguments})
                result = await _execute_tool(name, arguments, request)
                summary = {"id": tool_id, "name": name, "arguments": arguments, "result": result}
                tool_calls.append(summary)
                yield sse("tool_result", {"id": tool_id, "result": result})
                results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": tool_id,
                        "content": json.dumps(result, default=str),
                    }
                )
            messages.append(
                {
                    "role": "assistant",
                    "content": [
                        block.model_dump() if hasattr(block, "model_dump") else {
                            "type": getattr(block, "type", "tool_use"),
                            "id": getattr(block, "id", ""),
                            "name": getattr(block, "name", ""),
                            "input": getattr(block, "input", {}),
                        }
                        for block in content_blocks
                    ],
                }
            )
            messages.append({"role": "user", "content": results})
        yield sse(
            "done",
            {
                "message": final_text.strip() or "No response generated",
                "model": request.model or "claude-sonnet-4-20250514",
                "toolCalls": tool_calls or None,
                "citations": _citations(tool_calls) or None,
                "actions": [],
            },
        )
    except Exception as exc:  # noqa: BLE001
        yield sse("error", {"message": str(exc)})


async def _stream_openai_responses(request: ChatRequest) -> AsyncIterator[bytes]:
    """OpenAI gpt-5.* path: Responses API supports tools + reasoning_effort together."""
    try:
        from openai import AsyncOpenAI

        client = AsyncOpenAI(api_key=os.environ["OPENAI_API_KEY"])
        model = request.model or "gpt-5"
        tools = _tool_defs_openai_responses(request)
        all_tool_calls: list[dict[str, Any]] = []
        final_text = ""
        reasoning_text = ""
        previous_response_id: str | None = None
        current_input: list[dict[str, Any]] = _responses_input_from_request(request)

        for _ in range(_max_tool_iterations()):
            params: dict[str, Any] = {
                "model": model,
                "instructions": _system_prompt(request),
                "input": current_input,
                "stream": True,
            }
            if tools:
                params["tools"] = tools
            if previous_response_id:
                params["previous_response_id"] = previous_response_id
            effort = (request.reasoning_effort or "").strip() or None
            if effort:
                params["reasoning"] = {"effort": effort}

            stream = await client.responses.create(**params)
            response_id: str | None = None
            calls: dict[str, dict[str, str]] = {}
            content = ""

            async for event in stream:
                etype = getattr(event, "type", None)
                if etype == "response.created":
                    response = getattr(event, "response", None)
                    response_id = getattr(response, "id", None) or response_id
                elif etype == "response.output_text.delta":
                    delta = getattr(event, "delta", None) or ""
                    if delta:
                        content += delta
                        final_text += delta
                        yield sse("delta", {"delta": delta})
                elif etype == "response.reasoning_summary_text.delta":
                    delta = getattr(event, "delta", None) or ""
                    if delta:
                        reasoning_text += delta
                elif etype == "response.output_item.done":
                    item = getattr(event, "item", None)
                    if getattr(item, "type", None) == "function_call":
                        call_id = getattr(item, "call_id", "") or ""
                        calls[call_id] = {
                            "id": call_id,
                            "name": getattr(item, "name", "") or "",
                            "arguments": getattr(item, "arguments", "") or "{}",
                        }
                elif etype == "response.completed":
                    response = getattr(event, "response", None)
                    response_id = getattr(response, "id", None) or response_id
                    for item in getattr(response, "output", None) or []:
                        if getattr(item, "type", None) != "function_call":
                            continue
                        call_id = getattr(item, "call_id", "") or ""
                        if call_id and call_id not in calls:
                            calls[call_id] = {
                                "id": call_id,
                                "name": getattr(item, "name", "") or "",
                                "arguments": getattr(item, "arguments", "") or "{}",
                            }

            if not calls:
                break

            tool_outputs: list[dict[str, Any]] = []
            for call_id, entry in calls.items():
                try:
                    arguments = json.loads(entry["arguments"] or "{}")
                except ValueError:
                    arguments = {}
                yield sse(
                    "tool_call",
                    {"id": call_id, "name": entry["name"], "arguments": arguments},
                )
                result = await _execute_tool(entry["name"], arguments, request)
                summary = {
                    "id": call_id,
                    "name": entry["name"],
                    "arguments": arguments,
                    "result": result,
                }
                all_tool_calls.append(summary)
                yield sse("tool_result", {"id": call_id, "result": result})
                tool_outputs.append(
                    {
                        "type": "function_call_output",
                        "call_id": call_id,
                        "output": json.dumps(result, default=str),
                    }
                )

            if not response_id:
                break
            previous_response_id = response_id
            current_input = tool_outputs

        yield sse(
            "done",
            {
                "message": final_text.strip() or "No response generated",
                "reasoning": reasoning_text or None,
                "model": model,
                "toolCalls": all_tool_calls or None,
                "citations": _citations(all_tool_calls) or None,
                "actions": [],
            },
        )
    except Exception as exc:  # noqa: BLE001
        yield sse("error", {"message": str(exc)})


async def _stream_openai_compatible(
    request: ChatRequest, provider: str
) -> AsyncIterator[bytes]:
    try:
        from openai import AsyncOpenAI

        kwargs: dict[str, Any] = {"api_key": os.environ[f"{provider.upper()}_API_KEY"]}
        if provider == "xai":
            kwargs["base_url"] = "https://api.x.ai/v1"
        elif provider == "cerebras":
            kwargs["base_url"] = "https://api.cerebras.ai/v1"
        client = AsyncOpenAI(**kwargs)
        messages = _openai_messages(request)
        tools = _tool_defs_openai(request)
        all_tool_calls: list[dict[str, Any]] = []
        final_text = ""
        reasoning_text = ""
        model = request.model or {
            "openai": "gpt-5",
            "xai": "grok-4",
            "cerebras": "gpt-oss-120b",
        }[provider]

        for _ in range(_max_tool_iterations()):
            params: dict[str, Any] = {
                "model": model,
                "messages": messages,
                "stream": True,
                "tools": tools or None,
            }
            # chat.completions rejects tools + non-none reasoning for OpenAI gpt-5.*;
            # OpenAI uses the Responses path instead. xAI/Cerebras still accept this.
            if request.reasoning_effort and request.reasoning_effort != "none":
                params["reasoning_effort"] = request.reasoning_effort
            stream = await client.chat.completions.create(**params)
            content = ""
            calls: dict[int, dict[str, str]] = {}
            async for chunk in stream:
                choice = chunk.choices[0] if chunk.choices else None
                if not choice:
                    continue
                delta = choice.delta
                text = getattr(delta, "content", None)
                if text:
                    content += text
                    final_text += text
                    yield sse("delta", {"delta": text})
                reasoning = getattr(delta, "reasoning", None)
                if reasoning:
                    reasoning_text += reasoning
                for tool_delta in getattr(delta, "tool_calls", None) or []:
                    index = getattr(tool_delta, "index", 0)
                    entry = calls.setdefault(index, {"id": "", "name": "", "arguments": ""})
                    if getattr(tool_delta, "id", None):
                        entry["id"] = tool_delta.id
                    function = getattr(tool_delta, "function", None)
                    if function:
                        if getattr(function, "name", None):
                            entry["name"] = function.name
                        if getattr(function, "arguments", None):
                            entry["arguments"] += function.arguments
            if not calls:
                break
            assistant_call_payload = []
            tool_messages = []
            for entry in calls.values():
                try:
                    arguments = json.loads(entry["arguments"] or "{}")
                except ValueError:
                    arguments = {}
                call_id = entry["id"] or f"call_{len(all_tool_calls)}"
                yield sse(
                    "tool_call",
                    {"id": call_id, "name": entry["name"], "arguments": arguments},
                )
                result = await _execute_tool(entry["name"], arguments, request)
                summary = {
                    "id": call_id,
                    "name": entry["name"],
                    "arguments": arguments,
                    "result": result,
                }
                all_tool_calls.append(summary)
                yield sse("tool_result", {"id": call_id, "result": result})
                assistant_call_payload.append(
                    {
                        "id": call_id,
                        "type": "function",
                        "function": {
                            "name": entry["name"],
                            "arguments": entry["arguments"] or "{}",
                        },
                    }
                )
                tool_messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call_id,
                        "content": json.dumps(result, default=str),
                    }
                )
            messages.append(
                {
                    "role": "assistant",
                    "content": content,
                    "tool_calls": assistant_call_payload,
                }
            )
            messages.extend(tool_messages)
        yield sse(
            "done",
            {
                "message": final_text.strip() or "No response generated",
                "reasoning": reasoning_text or None,
                "model": model,
                "toolCalls": all_tool_calls or None,
                "citations": _citations(all_tool_calls) or None,
                "actions": [],
            },
        )
    except Exception as exc:  # noqa: BLE001
        yield sse("error", {"message": str(exc)})


async def stream_openai(request: ChatRequest) -> AsyncIterator[bytes]:
    async for event in _stream_openai_responses(request):
        yield event


async def stream_xai(request: ChatRequest) -> AsyncIterator[bytes]:
    async for event in _stream_openai_compatible(request, "xai"):
        yield event


async def stream_cerebras(request: ChatRequest) -> AsyncIterator[bytes]:
    async for event in _stream_openai_compatible(request, "cerebras"):
        yield event


async def generate_title(message: str, provider: str = "cerebras") -> str:
    """Generate a short title, falling back across providers when one fails."""
    prompt = (
        "Write a concise title for a personal AI-news chat. Return only 3-7 "
        "words, plain text, without quotes or ending punctuation.\n\n"
        + message[:4000]
    )
    errors: list[str] = []

    async def _via_cerebras() -> str | None:
        if not os.environ.get("CEREBRAS_API_KEY", "").strip():
            return None
        from openai import AsyncOpenAI

        client = AsyncOpenAI(
            api_key=os.environ["CEREBRAS_API_KEY"],
            base_url="https://api.cerebras.ai/v1",
        )
        response = await client.chat.completions.create(
            model="gpt-oss-120b",
            messages=[
                {"role": "system", "content": "Return only a short chat title."},
                {"role": "user", "content": prompt},
            ],
            max_completion_tokens=200,
            temperature=0.2,
            reasoning_effort="low",
        )
        if not response.choices:
            return None
        message_obj = response.choices[0].message
        return _clean_title(getattr(message_obj, "content", None) or "")

    async def _via_anthropic() -> str | None:
        if not os.environ.get("ANTHROPIC_API_KEY", "").strip():
            return None
        from anthropic import AsyncAnthropic

        client = AsyncAnthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
        response = await client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=40,
            system="Return only a short chat title.",
            messages=[{"role": "user", "content": prompt}],
        )
        text = next(
            (
                getattr(block, "text", "")
                for block in response.content
                if getattr(block, "type", "") == "text"
            ),
            "",
        )
        return _clean_title(text)

    order = (
        (_via_cerebras, _via_anthropic)
        if provider == "cerebras"
        else (_via_anthropic, _via_cerebras)
    )
    for factory in order:
        try:
            title = await factory()
            if title:
                return title
            errors.append(f"{factory.__name__}: empty title")
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{factory.__name__}: {exc}")
    detail = "; ".join(errors) if errors else "no title providers configured"
    raise RuntimeError(f"Failed to generate chat title: {detail}")


def _clean_title(value: str | None) -> str:
    value = (value or "").replace("<think>", "").replace("</think>", "")
    lines = [line.strip() for line in value.splitlines() if line.strip()]
    if not lines:
        return ""
    cleaned = lines[0].strip("\"'`")
    cleaned = " ".join(cleaned.split()).rstrip(".!?")
    return cleaned[:60].strip()
