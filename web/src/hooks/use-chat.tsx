"use client";

import { useCallback, useMemo } from "react";
import { useChatStore } from "@/lib/chat/chat-store";
import { toast } from "sonner";
import type { ChatMessage, ChatAction, PageContext } from "@/types/chat";
import type { Attachment } from "@/components/chat/chat-input";
import type { Json } from "@/types/chat";
import {
  createChatSession,
  addChatMessage,
  addChatAttachments,
  addChatSuggestedActions,
  addChatToolCalls,
  getChatMessages,
} from "@/actions/chat";

// Define proper types for database responses
interface ChatAttachmentRow {
  id: string;
  name: string;
  size: number;
  mime_type: string;
  storage_path: string;
}

interface ChatSuggestedActionRow {
  type: "filter" | "sort" | "navigate" | "create" | "function_call";
  label: string;
  payload: Json;
}

interface ChatToolCallRow {
  id: string;
  name: string;
  arguments: Json;
  result?: Json;
  reasoning?: string;
}

interface ChatMessageRow {
  id: string;
  role: "user" | "assistant" | "system";
  content: string;
  created_at: string;
  reasoning?: string;
  context?: Json;
  function_result?: Json;
  citations?: Json;
  chat_attachments?: ChatAttachmentRow[];
  chat_suggested_actions?: ChatSuggestedActionRow[];
  chat_tool_calls?: ChatToolCallRow[];
}

interface ToolCallResponse {
  id: string;
  name: string;
  arguments: Record<string, unknown>;
  result?: {
    success: boolean;
    data?: unknown;
    error?: string;
  };
  reasoning?: string;
}

interface ActionResponse {
  type: "filter" | "sort" | "navigate" | "create" | "function_call";
  label: string;
  payload: Record<string, unknown>;
}

interface ChatStreamResult {
  message?: string;
  reasoning?: string;
  actions?: ActionResponse[];
  toolCalls?: ToolCallResponse[];
  citations?: Array<{
    url: string;
    title: string;
    cited_text: string;
  }>;
}

interface UseChatProps {
  onSendMessage?: (
    message: string,
    attachments?: Attachment[],
    signal?: AbortSignal
  ) => Promise<void>;
  onActionClick?: (action: ChatAction) => void;
}

let activeChatAbortController: AbortController | null = null;

function isAbortError(error: unknown): boolean {
  return error instanceof DOMException
    ? error.name === "AbortError"
    : error instanceof Error && error.name === "AbortError";
}

interface StreamToolCall {
  id: string;
  name: string;
  arguments: Record<string, unknown>;
  result?: { success: boolean; data?: unknown; error?: string };
}

interface ChatStreamHandlers {
  onToolCall?: (toolCall: StreamToolCall) => void;
  onToolResult?: (toolResult: {
    id: string;
    result: { success: boolean; data?: unknown; error?: string };
  }) => void;
}

async function readChatStream(
  response: Response,
  onDelta: (delta: string) => void,
  signal: AbortSignal,
  handlers?: ChatStreamHandlers
): Promise<ChatStreamResult> {
  const contentType = response.headers.get("content-type") || "";
  if (!contentType.includes("text/event-stream") || !response.body) {
    return (await response.json()) as ChatStreamResult;
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let finalResult: ChatStreamResult | null = null;

  const handleFrame = (frame: string) => {
    let event = "message";
    const dataLines: string[] = [];

    for (const line of frame.split(/\r?\n/)) {
      if (line.startsWith("event:")) {
        event = line.slice("event:".length).trim();
      } else if (line.startsWith("data:")) {
        dataLines.push(line.slice("data:".length).trimStart());
      }
    }

    if (dataLines.length === 0) return;
    const payload = JSON.parse(dataLines.join("\n")) as Record<string, unknown>;

    if (event === "delta" && typeof payload.delta === "string") {
      onDelta(payload.delta);
    } else if (event === "tool_call" && handlers?.onToolCall) {
      handlers.onToolCall(payload as unknown as StreamToolCall);
    } else if (event === "tool_result" && handlers?.onToolResult) {
      handlers.onToolResult(
        payload as unknown as {
          id: string;
          result: { success: boolean; data?: unknown; error?: string };
        }
      );
    } else if (event === "done") {
      finalResult = payload as ChatStreamResult;
    } else if (event === "error") {
      throw new Error(
        typeof payload.message === "string"
          ? payload.message
          : "Chat stream failed"
      );
    }
  };

  while (true) {
    signal.throwIfAborted();
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });
    const frames = buffer.split(/\r?\n\r?\n/);
    buffer = frames.pop() || "";
    for (const frame of frames) {
      if (frame.trim()) handleFrame(frame);
    }
  }

  buffer += decoder.decode();
  if (buffer.trim()) handleFrame(buffer);

  return finalResult || {};
}

// Builds stream handlers that surface tool calls on the in-progress assistant
// message as they happen: each `tool_call` event appends a running tool call,
// and each `tool_result` event fills in its result. This lets the UI show the
// "actioning a tool" state before the model streams its text response.
function createToolStreamHandlers(
  getAssistantMessageId: () => string | null,
  updateMessage: (id: string, updates: Partial<ChatMessage>) => void
): ChatStreamHandlers {
  const toolCalls: StreamToolCall[] = [];
  const flush = () => {
    const id = getAssistantMessageId();
    if (id) updateMessage(id, { toolCalls: toolCalls.map((t) => ({ ...t })) });
  };
  return {
    onToolCall: (toolCall) => {
      toolCalls.push({ ...toolCall });
      flush();
    },
    onToolResult: ({ id, result }) => {
      const existing = toolCalls.find((t) => t.id === id);
      if (existing) existing.result = result;
      flush();
    },
  };
}

export function useChat({ onSendMessage, onActionClick }: UseChatProps = {}) {
  const {
    messages,
    isOpen,
    isMinimized,
    isLoading,
    currentContext,
    currentSessionId,
    addMessage,
    updateMessage,
    deleteMessage,
    clearMessages,
    setOpen,
    setMinimized,
    setLoading,
    toggleChat,
    updatePageContext,
    updateSessionTitle,
    // server-backed helpers
    upsertSessionFromServer,
    setCurrentSessionIdFromServer,
    setMessagesForSession,
  } = useChatStore();

  // Ensure a server-backed session exists
  const ensureSession = useCallback(async (): Promise<string> => {
    if (currentSessionId) return currentSessionId;
    const res = await createChatSession();
    if ("error" in res && res.error) {
      toast.error("Failed to create chat session");
      throw new Error(res.error);
    }
    const session = res.data!;
    upsertSessionFromServer({
      id: session.id,
      title: session.title,
      createdAt: new Date(session.created_at),
      updatedAt: new Date(session.updated_at),
      messages: [],
      context: session.context as unknown as PageContext | undefined,
    });
    setCurrentSessionIdFromServer(session.id);
    return session.id;
  }, [
    currentSessionId,
    upsertSessionFromServer,
    setCurrentSessionIdFromServer,
  ]);

  // Refresh messages from DB
  const refreshMessages = useCallback(
    async (sessionId: string) => {
      const res = await getChatMessages(sessionId);
      if ("error" in res && res.error) {
        console.error("Failed to fetch messages:", res.error);
        return;
      }
      const rows = res.data || [];

      const allMessages: ChatMessage[] = [];
      for (const m of rows as unknown as ChatMessageRow[]) {
        // Map attachments and sign URLs
        const attachments = Array.isArray(m.chat_attachments)
          ? m.chat_attachments.map((att: ChatAttachmentRow) => {
              const endpoint = (att.mime_type as string)?.startsWith("image/")
                ? "/api/images/serve"
                : "/api/files/serve";
              return {
                id: att.id,
                name: att.name,
                size: att.size,
                type: att.mime_type,
                url: `${endpoint}?path=${encodeURIComponent(att.storage_path)}`,
              };
            })
          : [];

        allMessages.push({
          id: m.id,
          role: m.role,
          content: m.content,
          timestamp: new Date(m.created_at),
          reasoning: m.reasoning || undefined,
          attachments,
          context: m.context
            ? {
                filters:
                  ((m.context as Record<string, unknown>)?.filters as Record<
                    string,
                    unknown
                  >) || {},
                data:
                  ((m.context as Record<string, unknown>)?.data as Record<
                    string,
                    unknown
                  >) || {},
              }
            : undefined,
          suggestedActions: Array.isArray(m.chat_suggested_actions)
            ? m.chat_suggested_actions.map((a: ChatSuggestedActionRow) => ({
                type: a.type,
                label: a.label,
                payload: a.payload as Record<string, unknown>,
              }))
            : undefined,
          functionResult: m.function_result as
            | { success: boolean; data?: unknown; error?: string }
            | undefined,
          toolCalls: Array.isArray(m.chat_tool_calls)
            ? m.chat_tool_calls.map((t: ChatToolCallRow) => ({
                id: t.id,
                name: t.name,
                arguments: t.arguments as Record<string, unknown>,
                result: t.result as
                  | { success: boolean; data?: unknown; error?: string }
                  | undefined,
                reasoning: t.reasoning || undefined,
              }))
            : undefined,
          citations: m.citations as
            | Array<{ url: string; title: string; cited_text: string }>
            | undefined,
        });
      }

      setMessagesForSession(sessionId, allMessages);
    },
    [setMessagesForSession]
  );

  // Default API handler
  const sendToAPI = useCallback(
    async (
      content: string,
      context: PageContext | null,
      attachments?: Attachment[],
      model?: string,
      reasoningEffort?: "none" | "low" | "medium" | "high" | "xhigh",
      webSearchEnabled = true,
      signal?: AbortSignal
    ) => {
      const formData = new FormData();
      formData.append("message", content);
      formData.append("context", JSON.stringify(context));
      // Always read latest messages from the store to avoid stale closures
      const { messages: latestMessages } = useChatStore.getState();
      formData.append("messages", JSON.stringify(latestMessages.slice(-10))); // Send last 10 messages for context
      if (model) {
        formData.append("model", model);
      }
      if (reasoningEffort) {
        formData.append("reasoning_effort", reasoningEffort);
      }
      formData.append("web_search_enabled", String(webSearchEnabled));
      formData.append("stream", "true");

      // Attach client timezone context
      try {
        const tz = Intl.DateTimeFormat().resolvedOptions().timeZone || "";
        const offsetMinutes = new Date().getTimezoneOffset();
        const sign = offsetMinutes <= 0 ? "+" : "-";
        const abs = Math.abs(offsetMinutes);
        const hh = String(Math.floor(abs / 60)).padStart(2, "0");
        const mm = String(abs % 60).padStart(2, "0");
        const offset = `${sign}${hh}:${mm}`;
        const d = new Date();
        const pad = (n: number) => String(n).padStart(2, "0");
        const localISO = `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}${offset}`;
        formData.append("client_tz", tz);
        formData.append("client_utc_offset", offset);
        formData.append("client_now_iso", localISO);
        formData.append("client_path", window.location.pathname || "");
      } catch {}

      // Add attachments if any
      if (attachments && attachments.length > 0) {
        attachments.forEach((attachment, index) => {
          formData.append(`attachment-${index}`, attachment.file);
          formData.append(`attachment-${index}-name`, attachment.name);
          formData.append(`attachment-${index}-type`, attachment.type);
          formData.append(
            `attachment-${index}-size`,
            attachment.size.toString()
          );
        });
        formData.append("attachmentCount", attachments.length.toString());
      }

      let assistantMessageId: string | null = null;
      let streamedContent = "";
      const prevLen = useChatStore.getState().messages.length;
      addMessage({
        role: "assistant",
        content: "",
      });
      const messagesAfterAssistantAdd = useChatStore.getState().messages;
      if (messagesAfterAssistantAdd.length > prevLen) {
        assistantMessageId =
          messagesAfterAssistantAdd[messagesAfterAssistantAdd.length - 1]?.id ||
          null;
      }

      const response = await fetch("/api/chat/anthropic", {
        method: "POST",
        body: formData,
        signal,
      });

      if (!response.ok) {
        throw new Error(`API error: ${response.status}`);
      }

      const result = await readChatStream(
        response,
        (delta) => {
          streamedContent += delta;
          if (assistantMessageId) {
            updateMessage(assistantMessageId, {
              content: streamedContent,
            });
          }
        },
        signal ?? new AbortController().signal,
        createToolStreamHandlers(() => assistantMessageId, updateMessage)
      );
      signal?.throwIfAborted();

      // Add the assistant message with tool calls, citations, and reasoning if available
      const assistantMessage: Omit<ChatMessage, "id" | "timestamp"> = {
        role: "assistant",
        content:
          result.message ||
          streamedContent ||
          "I apologize, but I couldn't generate a response.",
        reasoning: result.reasoning || undefined,
        suggestedActions: result.actions || [],
        toolCalls: result.toolCalls || undefined,
        citations: result.citations || undefined,
      };

      if (assistantMessageId) {
        updateMessage(assistantMessageId, assistantMessage);
      }

      // Persist assistant message to DB and refresh
      const sid = await ensureSession();
      const addRes = await addChatMessage({
        sessionId: sid,
        role: "assistant",
        content: assistantMessage.content,
        reasoning: assistantMessage.reasoning || null,
        context: null,
        functionResult: (assistantMessage.functionResult as Json) || null,
        citations: (assistantMessage.citations as Json) || null,
      });
      if (!("error" in addRes) && addRes.data) {
        if (result.toolCalls?.length) {
          await addChatToolCalls(
            addRes.data.id,
            result.toolCalls.map((t: ToolCallResponse) => ({
              name: t.name,
              arguments: t.arguments as Json,
              result: (t.result as Json) || null,
              reasoning: t.reasoning,
            }))
          );
        }
        if (result.actions?.length) {
          await addChatSuggestedActions(
            addRes.data.id,
            result.actions.map((a: ActionResponse) => ({
              type: a.type,
              label: a.label,
              payload: a.payload as Json,
            }))
          );
        }
      }
      await refreshMessages(sid);
    },
    [addMessage, ensureSession, refreshMessages, updateMessage]
  );

  // Handle sending a new message
  const sendMessage = useCallback(
    async (
      content: string,
      attachments?: Attachment[],
      model?: string,
      reasoningEffort?: "none" | "low" | "medium" | "high" | "xhigh",
      options?: { skipUserAdd?: boolean; webSearchEnabled?: boolean }
    ) => {
      if (
        (!content.trim() && (!attachments || attachments.length === 0)) ||
        isLoading
      )
        return;

      // Ensure we have a server-backed session first so optimistic add targets the right session
      const sid = await ensureSession();
      const abortController = new AbortController();
      activeChatAbortController = abortController;
      const { signal } = abortController;

      const stateBeforeSend = useChatStore.getState();
      const sessionBeforeSend = stateBeforeSend.sessions.find(
        (session) => session.id === sid
      );
      const shouldGenerateTitle =
        !options?.skipUserAdd &&
        Boolean(content.trim()) &&
        sessionBeforeSend?.title === "New Chat" &&
        !stateBeforeSend.messages.some((message) => message.role === "user");

      if (shouldGenerateTitle) {
        // This request intentionally runs independently of the main chat request.
        void fetch("/api/chat/title", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ sessionId: sid, message: content.trim() }),
        })
          .then(async (response) => {
            const result = (await response.json()) as {
              title?: string;
              error?: string;
            };
            if (!response.ok) {
              throw new Error(result.error || `Title API error: ${response.status}`);
            }
            if (result.title) updateSessionTitle(sid, result.title);
          })
          .catch((error) => {
            console.error("Failed to generate chat title:", error);
          });
      }

      // Optimistically add the user's message to the UI (before uploads/DB)
      let tempUserMessageId: string | null = null;
      if (!options?.skipUserAdd) {
        const trimmed = content.trim() || "Sent with attachments";
        const prevLen = useChatStore.getState().messages.length;
        const localAttachments = (attachments || []).map((a) => ({
          id: crypto.randomUUID(),
          name: a.name,
          size: a.size,
          type: a.type,
          // Show instant preview for images; use blob URL to avoid heavy base64
          data: a.type.startsWith("image/")
            ? URL.createObjectURL(a.file)
            : undefined,
        }));
        addMessage({
          role: "user",
          content: trimmed,
          attachments: localAttachments,
          context: currentContext
            ? {
                filters: currentContext.currentFilters,
                data: { totalCount: currentContext.totalCount },
              }
            : undefined,
        });
        const newMessages = useChatStore.getState().messages;
        if (newMessages.length > prevLen)
          tempUserMessageId = newMessages[newMessages.length - 1]?.id || null;
        // Immediately show assistant typing spinner while processing backend work
        setLoading(true);
      }

      // Upload attachments to Supabase Storage
      const uploaded: Array<{
        name: string;
        mime_type: string;
        size: number;
        storage_path: string;
      }> = [];
      if (attachments && attachments.length > 0) {
        for (const a of attachments) {
          try {
            const form = new FormData();
            form.append("file", a.file);
            form.append("pathPrefix", "chat");
            const endpoint = a.type.startsWith("image/")
              ? "/api/images/upload"
              : "/api/files/upload";
            const resp = await fetch(endpoint, {
              method: "POST",
              body: form,
              signal,
            });
            const j = await resp.json();
            if (!resp.ok || j.error)
              throw new Error(j.error || "Upload failed");
            const filePath = j.filePath || j.url;
            if (filePath)
              uploaded.push({
                name: a.name,
                mime_type: a.type,
                size: a.size,
                storage_path: filePath,
              });
          } catch (e) {
            if (signal.aborted) {
              break;
            }
            console.error("Attachment upload failed:", e);
            toast.error("Attachment upload failed");
          }
        }
      }

      // Persist user message to DB unless explicitly skipped (used when resending an edited message)
      if (!options?.skipUserAdd) {
        try {
          const res = await addChatMessage({
            sessionId: sid,
            role: "user",
            content: content.trim() || "Sent with attachments",
            context: currentContext
              ? ({
                  filters: currentContext.currentFilters,
                  data: { totalCount: currentContext.totalCount },
                } as Json)
              : null,
          });

          if (!("error" in res) && res.data && uploaded.length > 0) {
            await addChatAttachments(res.data.id, uploaded);
          }
          await refreshMessages(sid); // replaces the optimistic entry with canonical data
        } catch (err) {
          if (activeChatAbortController === abortController) {
            activeChatAbortController = null;
          }
          // Roll back optimistic message on failure
          if (tempUserMessageId) deleteMessage(tempUserMessageId);
          console.error("Failed to persist user message:", err);
          toast.error("Failed to send message");
          // Stop the typing indicator if we started it
          setLoading(false);
          return;
        }
      }

      // If we didn't set loading above (e.g., skipUserAdd path), enable it now
      if (options?.skipUserAdd) setLoading(true);

      try {
        signal.throwIfAborted();
        // Call custom send handler if provided, otherwise use default API call
        if (onSendMessage) {
          await onSendMessage(content, attachments, signal);
        } else {
          // Determine which API to use based on model selection
          const isCerebrasModel = model?.startsWith("gpt-oss-120b");
          const isOpenAIModel = model?.startsWith("gpt-5");
          const isXAIModel = model?.startsWith("grok-");

          if (isCerebrasModel) {
            // Use Cerebras API
            const cerebrasFormData = new FormData();
            cerebrasFormData.append("message", content);
            cerebrasFormData.append("context", JSON.stringify(currentContext));
            const { messages: latestMessages } = useChatStore.getState();
            cerebrasFormData.append(
              "messages",
              JSON.stringify(latestMessages.slice(-10))
            );
            if (model) {
              cerebrasFormData.append("model", model);
            }
            if (reasoningEffort) {
              cerebrasFormData.append("reasoning_effort", reasoningEffort);
            }
            cerebrasFormData.append(
              "web_search_enabled",
              String(options?.webSearchEnabled ?? true)
            );
            cerebrasFormData.append("stream", "true");

            // Attach client timezone context
            try {
              const tz = Intl.DateTimeFormat().resolvedOptions().timeZone || "";
              const offsetMinutes = new Date().getTimezoneOffset();
              const sign = offsetMinutes <= 0 ? "+" : "-";
              const abs = Math.abs(offsetMinutes);
              const hh = String(Math.floor(abs / 60)).padStart(2, "0");
              const mm = String(abs % 60).padStart(2, "0");
              const offset = `${sign}${hh}:${mm}`;
              const d = new Date();
              const pad = (n: number) => String(n).padStart(2, "0");
              const localISO = `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}${offset}`;
              cerebrasFormData.append("client_tz", tz);
              cerebrasFormData.append("client_utc_offset", offset);
              cerebrasFormData.append("client_now_iso", localISO);
              cerebrasFormData.append(
                "client_path",
                window.location.pathname || ""
              );
            } catch {}

            // Add attachments if any
            if (attachments && attachments.length > 0) {
              attachments.forEach((attachment, index) => {
                cerebrasFormData.append(`attachment-${index}`, attachment.file);
                cerebrasFormData.append(
                  `attachment-${index}-name`,
                  attachment.name
                );
                cerebrasFormData.append(
                  `attachment-${index}-type`,
                  attachment.type
                );
                cerebrasFormData.append(
                  `attachment-${index}-size`,
                  attachment.size.toString()
                );
              });
              cerebrasFormData.append(
                "attachmentCount",
                attachments.length.toString()
              );
            }

            let assistantMessageId: string | null = null;
            let streamedContent = "";
            const prevLen = useChatStore.getState().messages.length;
            addMessage({
              role: "assistant",
              content: "",
            });
            const messagesAfterAssistantAdd = useChatStore.getState().messages;
            if (messagesAfterAssistantAdd.length > prevLen) {
              assistantMessageId =
                messagesAfterAssistantAdd[messagesAfterAssistantAdd.length - 1]
                  ?.id || null;
            }

            const response = await fetch("/api/chat/cerebras", {
              method: "POST",
              body: cerebrasFormData,
              signal,
            });

            if (!response.ok) {
              throw new Error(`Cerebras API error: ${response.status}`);
            }

            const result = await readChatStream(
              response,
              (delta) => {
                streamedContent += delta;
                if (assistantMessageId) {
                  updateMessage(assistantMessageId, {
                    content: streamedContent,
                  });
                }
              },
              signal,
              createToolStreamHandlers(
                () => assistantMessageId,
                updateMessage
              )
            );
            signal.throwIfAborted();

            // Add the assistant message with tool calls, citations, and reasoning if available
            const assistantMessage: Omit<ChatMessage, "id" | "timestamp"> = {
              role: "assistant",
              content:
                result.message ||
                streamedContent ||
                "I apologize, but I couldn't generate a response.",
              reasoning: result.reasoning || undefined,
              suggestedActions: result.actions || [],
              toolCalls: result.toolCalls || undefined,
              citations: result.citations || undefined,
            };

            if (assistantMessageId) {
              updateMessage(assistantMessageId, assistantMessage);
            }

            const res2 = await addChatMessage({
              sessionId: sid,
              role: "assistant",
              content: assistantMessage.content,
              reasoning: assistantMessage.reasoning || null,
              citations: (assistantMessage.citations as Json) || null,
            });
            if (!("error" in res2) && res2.data) {
              if (result.toolCalls?.length) {
                await addChatToolCalls(
                  res2.data.id,
                  result.toolCalls.map((t: ToolCallResponse) => ({
                    name: t.name,
                    arguments: t.arguments as Json,
                    result: (t.result as Json) || null,
                    reasoning: t.reasoning,
                  }))
                );
              }
              if (result.actions?.length) {
                await addChatSuggestedActions(
                  res2.data.id,
                  result.actions.map((a: ActionResponse) => ({
                    type: a.type,
                    label: a.label,
                    payload: a.payload as Json,
                  }))
                );
              }
            }
            await refreshMessages(sid);
          } else if (isOpenAIModel || isXAIModel) {
            // Use OpenAI or xAI Responses API
            const providerLabel = isXAIModel ? "xAI" : "OpenAI";
            const providerEndpoint = isXAIModel
              ? "/api/chat/xai"
              : "/api/chat/openai";
            const openaiFormData = new FormData();
            openaiFormData.append("message", content);
            openaiFormData.append("context", JSON.stringify(currentContext));
            const { messages: latestMessages } = useChatStore.getState();
            openaiFormData.append(
              "messages",
              JSON.stringify(latestMessages.slice(-10))
            );
            if (model) {
              openaiFormData.append("model", model);
            }
            if (reasoningEffort) {
              openaiFormData.append("reasoning_effort", reasoningEffort);
            }
            openaiFormData.append(
              "web_search_enabled",
              String(options?.webSearchEnabled ?? true)
            );
            openaiFormData.append("stream", "true");

            // Attach client timezone context
            try {
              const tz = Intl.DateTimeFormat().resolvedOptions().timeZone || "";
              const offsetMinutes = new Date().getTimezoneOffset();
              const sign = offsetMinutes <= 0 ? "+" : "-";
              const abs = Math.abs(offsetMinutes);
              const hh = String(Math.floor(abs / 60)).padStart(2, "0");
              const mm = String(abs % 60).padStart(2, "0");
              const offset = `${sign}${hh}:${mm}`;
              const d = new Date();
              const pad = (n: number) => String(n).padStart(2, "0");
              const localISO = `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}${offset}`;
              openaiFormData.append("client_tz", tz);
              openaiFormData.append("client_utc_offset", offset);
              openaiFormData.append("client_now_iso", localISO);
              openaiFormData.append(
                "client_path",
                window.location.pathname || ""
              );
            } catch {}

            // Add attachments if any
            if (attachments && attachments.length > 0) {
              attachments.forEach((attachment, index) => {
                openaiFormData.append(`attachment-${index}`, attachment.file);
                openaiFormData.append(
                  `attachment-${index}-name`,
                  attachment.name
                );
                openaiFormData.append(
                  `attachment-${index}-type`,
                  attachment.type
                );
                openaiFormData.append(
                  `attachment-${index}-size`,
                  attachment.size.toString()
                );
              });
              openaiFormData.append(
                "attachmentCount",
                attachments.length.toString()
              );
            }

            let assistantMessageId: string | null = null;
            let streamedContent = "";
            const prevLen = useChatStore.getState().messages.length;
            addMessage({
              role: "assistant",
              content: "",
            });
            const messagesAfterAssistantAdd = useChatStore.getState().messages;
            if (messagesAfterAssistantAdd.length > prevLen) {
              assistantMessageId =
                messagesAfterAssistantAdd[messagesAfterAssistantAdd.length - 1]
                  ?.id || null;
            }

            const response = await fetch(providerEndpoint, {
              method: "POST",
              body: openaiFormData,
              signal,
            });

            if (!response.ok) {
              throw new Error(`${providerLabel} API error: ${response.status}`);
            }

            const result = await readChatStream(
              response,
              (delta) => {
                streamedContent += delta;
                if (assistantMessageId) {
                  updateMessage(assistantMessageId, {
                    content: streamedContent,
                  });
                }
              },
              signal,
              createToolStreamHandlers(
                () => assistantMessageId,
                updateMessage
              )
            );
            signal.throwIfAborted();

            // Add the assistant message with tool calls, citations, and reasoning if available
            const assistantMessage: Omit<ChatMessage, "id" | "timestamp"> = {
              role: "assistant",
              content:
                result.message ||
                streamedContent ||
                "I apologize, but I couldn't generate a response.",
              reasoning: result.reasoning || undefined,
              suggestedActions: result.actions || [],
              toolCalls: result.toolCalls || undefined,
              citations: result.citations || undefined,
            };

            if (assistantMessageId) {
              updateMessage(assistantMessageId, assistantMessage);
            }

            const res3 = await addChatMessage({
              sessionId: sid,
              role: "assistant",
              content: assistantMessage.content,
              reasoning: assistantMessage.reasoning || null,
              citations: (assistantMessage.citations as Json) || null,
            });
            if (!("error" in res3) && res3.data) {
              if (result.toolCalls?.length) {
                await addChatToolCalls(
                  res3.data.id,
                  result.toolCalls.map((t: ToolCallResponse) => ({
                    name: t.name,
                    arguments: t.arguments as Json,
                    result: (t.result as Json) || null,
                    reasoning: t.reasoning,
                  }))
                );
              }
              if (result.actions?.length) {
                await addChatSuggestedActions(
                  res3.data.id,
                  result.actions.map((a: ActionResponse) => ({
                    type: a.type,
                    label: a.label,
                    payload: a.payload as Json,
                  }))
                );
              }
            }
            await refreshMessages(sid);
          } else {
            // Default API call (Anthropic)
            await sendToAPI(
              content,
              currentContext,
              attachments,
              model,
              reasoningEffort,
              options?.webSearchEnabled ?? true,
              signal
            );
          }
        }
      } catch (error) {
        if (signal.aborted || isAbortError(error)) return;
        console.error("Failed to send message:", error);
        const description =
          error instanceof Error ? error.message : "Please try again.";
        toast.error("Unable to complete chat request", { description });
        await addChatMessage({
          sessionId: sid,
          role: "assistant",
          content:
            "Sorry, I encountered an error while processing your message. Please try again.",
        });
        await refreshMessages(sid);
      } finally {
        if (activeChatAbortController === abortController) {
          activeChatAbortController = null;
        }
        // Always clear loading state
        setLoading(false);
      }
    },
    [
      currentContext,
      ensureSession,
      onSendMessage,
      isLoading,
      setLoading,
      sendToAPI,
      refreshMessages,
      addMessage,
      updateMessage,
      deleteMessage,
      updateSessionTitle,
    ]
  );

  const stopMessage = useCallback(() => {
    activeChatAbortController?.abort();
    activeChatAbortController = null;
    setLoading(false);
  }, [setLoading]);

  // Handle action clicks
  const handleActionClick = useCallback(
    (action: ChatAction) => {
      if (onActionClick) {
        onActionClick(action);
      } else {
        // Default action handling
        console.log("Action clicked:", action);
        // Add confirmation message
        addMessage({
          role: "system",
          content: `Action executed: ${action.label}`,
        });
      }
    },
    [onActionClick, addMessage]
  );

  // Get unread message count
  const getUnreadCount = useCallback(() => {
    if (isOpen) return 0;
    // Count assistant messages since last opened
    // For now, just return 0 - this could be enhanced with proper read tracking
    return 0;
  }, [isOpen]);

  // Chat state utilities
  const chatState = useMemo(
    () => ({
      isEmpty: messages.length === 0,
      hasMessages: messages.length > 0,
      lastMessage: messages[messages.length - 1] || null,
      messageCount: messages.length,
      isTyping: isLoading, // Use loading state as typing indicator
    }),
    [messages, isLoading]
  );

  // Context utilities
  const contextInfo = useMemo(() => {
    if (!currentContext) {
      return {
        hasContext: false,
        pageDescription: "No page context available",
        summary: "Unable to determine current page context",
      };
    }

    const { totalCount, currentFilters, currentSort, visibleData } =
      currentContext;
    const hasFilters =
      ((currentFilters as Record<string, unknown>)
        ?.activeFiltersCount as number) > 0;
    const hasSorting =
      ((currentSort as Record<string, unknown>)?.activeSortsCount as number) >
      0;

    return {
      hasContext: true,
      pageDescription: "Current data view",
      summary: `Viewing ${totalCount} items${hasFilters ? " (filtered)" : ""}${hasSorting ? " (sorted)" : ""}`,
      hasFilters,
      hasSorting,
      dataCount: totalCount,
      visibleCount: visibleData.length,
    };
  }, [currentContext]);

  return {
    // State
    messages,
    isOpen,
    isMinimized,
    isLoading,
    currentContext,
    chatState,
    contextInfo,

    // Actions
    sendMessage,
    stopMessage,
    addMessage,
    updateMessage,
    deleteMessage,
    clearMessages,
    handleActionClick,

    // UI State
    setOpen,
    setMinimized,
    toggleChat,
    openChat: () => setOpen(true),
    closeChat: () => setOpen(false),
    minimizeChat: () => setMinimized(true),
    maximizeChat: () => setMinimized(false),

    // Context
    updatePageContext,

    // Utilities
    getUnreadCount,
    hasUnread: getUnreadCount() > 0,

    // Convenience methods
    clearAndClose: () => {
      clearMessages();
      setOpen(false);
    },

    canSendMessage: (content: string) => {
      return content.trim().length > 0 && !isLoading;
    },

    // Get context summary for display
    getContextSummary: () => {
      if (!currentContext) return null;

      const { totalCount, currentFilters, currentSort } = currentContext;
      const hasFilters =
        ((currentFilters as Record<string, unknown>)
          ?.activeFiltersCount as number) > 0;
      const hasSorting =
        ((currentSort as Record<string, unknown>)?.activeSortsCount as number) >
        0;

      let summary = `${totalCount} items`;
      if (hasFilters) summary += " (filtered)";
      if (hasSorting) summary += " (sorted)";

      return summary;
    },

    // Get suggested prompts based on context
    getSuggestedPrompts: () => {
      if (!currentContext) return [];

      const { totalCount } = currentContext;
      const hasData = totalCount > 0;

      if (!hasData) {
        return [
          `Why are there no items?`,
          `How can I add a new item?`,
          `Show me how to import items`,
        ];
      }

      return [
        `Filter items by status`,
        `Show me recent items`,
        `Sort items by priority`,
      ];
    },
  };
}
