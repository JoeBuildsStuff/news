/** Chat persistence client — FastAPI over `/api/chat/*` (ported from Next server actions). */

import type { Json, ChatMessageRow } from "@/types/chat";

export type ChatRole = "user" | "assistant" | "system";

type ApiResult<T> = { data: T; error?: undefined } | { data?: undefined; error: string };

async function chatFetch<T>(
  input: string,
  init?: RequestInit,
): Promise<ApiResult<T>> {
  try {
    const res = await fetch(input, {
      ...init,
      headers: {
        ...(init?.body && !(init.body instanceof FormData)
          ? { "Content-Type": "application/json" }
          : {}),
        ...init?.headers,
      },
    });
    const payload = (await res.json().catch(() => ({}))) as {
      data?: T;
      error?: string;
      detail?: string | { msg?: string }[];
      message?: string;
    };
    if (!res.ok) {
      const detail = payload.detail;
      const detailText = Array.isArray(detail)
        ? detail.map((d) => d.msg || JSON.stringify(d)).join("; ")
        : typeof detail === "string"
          ? detail
          : undefined;
      return {
        error:
          payload.error ||
          detailText ||
          payload.message ||
          `Request failed (${res.status})`,
      };
    }
    if ("data" in payload) {
      return { data: payload.data as T };
    }
    return { data: payload as T };
  } catch (error) {
    return {
      error: error instanceof Error ? error.message : "Network error",
    };
  }
}

export interface CreateSessionParams {
  title?: string;
  context?: Json | null;
}

export async function createChatSession(params: CreateSessionParams = {}) {
  return chatFetch<{
    id: string;
    title: string;
    created_at: string;
    updated_at: string;
    context: Json | null;
  }>("/api/chat/sessions", {
    method: "POST",
    body: JSON.stringify(params),
  });
}

export async function updateChatSessionTitle(sessionId: string, title: string) {
  return chatFetch<{ id: string; title: string; updated_at: string }>(
    `/api/chat/sessions/${encodeURIComponent(sessionId)}`,
    {
      method: "PATCH",
      body: JSON.stringify({ title }),
    },
  );
}

export async function deleteChatSession(sessionId: string) {
  return chatFetch<{ success: boolean }>(
    `/api/chat/sessions/${encodeURIComponent(sessionId)}`,
    { method: "DELETE" },
  );
}

export async function listChatSessions() {
  return chatFetch<
    Array<{
      id: string;
      title: string;
      created_at: string;
      updated_at: string;
      message_count: number;
    }>
  >("/api/chat/sessions");
}

export async function getChatSessionSummariesByIds(sessionIds: string[]) {
  const ids = sessionIds.filter(Boolean).join(",");
  return chatFetch<
    Array<{
      id: string;
      title: string;
      created_at: string;
      updated_at: string;
    }>
  >(`/api/chat/sessions/summaries?ids=${encodeURIComponent(ids)}`);
}

export interface AddMessageParams {
  sessionId: string;
  role: ChatRole;
  content: string;
  parentId?: string | null;
  reasoning?: string | null;
  context?: Json | null;
  functionResult?: Json | null;
  citations?: Json | null;
  rootUserMessageId?: string | null;
  variantGroupId?: string | null;
  variantIndex?: number | null;
}

export async function addChatMessage(params: AddMessageParams) {
  const { sessionId, ...body } = params;
  return chatFetch<{ id: string; created_at: string }>(
    `/api/chat/sessions/${encodeURIComponent(sessionId)}/messages`,
    {
      method: "POST",
      body: JSON.stringify(body),
    },
  );
}

export interface AttachmentInput {
  name: string;
  mime_type: string;
  size: number;
  storage_path: string;
  width?: number | null;
  height?: number | null;
}

export async function addChatAttachments(
  messageId: string,
  attachments: AttachmentInput[],
) {
  if (!attachments || attachments.length === 0) return { data: [] };
  return chatFetch<Array<{ id: string; name: string; storage_path: string }>>(
    `/api/chat/messages/${encodeURIComponent(messageId)}/attachments`,
    {
      method: "POST",
      body: JSON.stringify({ attachments }),
    },
  );
}

export interface ToolCallInput {
  name: string;
  arguments: Json;
  result?: Json | null;
  reasoning?: string | null;
}

export async function addChatToolCalls(
  messageId: string,
  calls: ToolCallInput[],
) {
  if (!calls || calls.length === 0) return { data: [] };
  return chatFetch<Array<{ id: string; name: string }>>(
    `/api/chat/messages/${encodeURIComponent(messageId)}/tool-calls`,
    {
      method: "POST",
      body: JSON.stringify({ calls }),
    },
  );
}

export interface SuggestedActionInput {
  type: "filter" | "sort" | "navigate" | "create" | "function_call";
  label: string;
  payload: Json;
}

export async function addChatSuggestedActions(
  messageId: string,
  actions: SuggestedActionInput[],
) {
  if (!actions || actions.length === 0) return { data: [] };
  return chatFetch<Array<{ id: string; type: string; label: string }>>(
    `/api/chat/messages/${encodeURIComponent(messageId)}/suggested-actions`,
    {
      method: "POST",
      body: JSON.stringify({ actions }),
    },
  );
}

export async function getChatMessages(sessionId: string) {
  return chatFetch<ChatMessageRow[]>(
    `/api/chat/sessions/${encodeURIComponent(sessionId)}/messages`,
  );
}

export interface SetActiveVariantParams {
  sessionId: string;
  userMessageId: string;
  activeIndex: number;
  signature?: string | null;
  signatures?: string[] | null;
}

export async function setActiveVariant(params: SetActiveVariantParams) {
  const { sessionId, ...body } = params;
  return chatFetch<{ id: string; active_index: number }>(
    `/api/chat/sessions/${encodeURIComponent(sessionId)}/branch`,
    {
      method: "POST",
      body: JSON.stringify(body),
    },
  );
}

export async function getBranchState(sessionId: string) {
  return chatFetch<
    Array<{
      user_message_id: string;
      active_index: number;
      signature: string | null;
      signatures: string[] | null;
    }>
  >(`/api/chat/sessions/${encodeURIComponent(sessionId)}/branch`);
}
