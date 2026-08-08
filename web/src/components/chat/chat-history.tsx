"use client";

import { formatDistanceToNow } from "date-fns";
import { ChevronRight, MessagesSquare, SquarePen, Trash } from "lucide-react";
import { Button } from "@/components/ui/button";
import { ScrollFadeArea } from "@/components/scroll-fade-area";

import { useChatStore } from "@/lib/chat/chat-store";
import { cn } from "@/lib/utils";

import { useEffect, useState } from "react";
import {
  createChatSession,
  deleteChatSession,
  listChatSessions,
  getChatMessages,
} from "@/actions/chat";
import type {
  ChatMessageRow,
  ChatSuggestedActionRow,
  ChatToolCallRow,
} from "@/types/chat";
import { Skeleton } from "../ui/skeleton";

// Type for the mapped session data returned by listChatSessions
type ChatSessionSummaryRow = {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
  message_count: number;
};

export function ChatHistory() {
  const {
    currentSessionId,
    setShowHistory,
    deleteSession: deleteLocalSession,
    upsertSessionFromServer,
    setCurrentSessionIdFromServer,
    setMessagesForSession,
    openSessionTab,
  } = useChatStore();

  const [sessions, setSessions] = useState<
    Array<{
      id: string;
      title: string;
      updatedAt: Date;
      createdAt: Date;
      messageCount: number;
    }>
  >([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    const load = async () => {
      setLoading(true);
      const res = await listChatSessions();
      if ("error" in res && res.error) {
        setLoading(false);
        return;
      }
      const mapped = (res.data || []).map((row: ChatSessionSummaryRow) => ({
        id: row.id,
        title: row.title,
        createdAt: new Date(row.created_at),
        updatedAt: new Date(row.updated_at),
        messageCount: row.message_count ?? 0,
      }));
      // prime store sessions list
      mapped.forEach((s) =>
        upsertSessionFromServer({
          id: s.id,
          title: s.title,
          createdAt: s.createdAt,
          updatedAt: s.updatedAt,
          messages: [],
        })
      );
      setSessions(mapped);
      setLoading(false);
    };
    load();
  }, [upsertSessionFromServer]);

  const handleSessionClick = async (sessionId: string) => {
    setCurrentSessionIdFromServer(sessionId);
    openSessionTab(sessionId);
    // fetch messages for the session and populate
    const res = await getChatMessages(sessionId);
    if (!("error" in res) && res.data) {
      // map to UI messages; we only include minimal fields here; use-chat’s refresh has fuller mapping.
      const rows = res.data;
      const msgs = await Promise.all(
        rows.map(async (m: ChatMessageRow) => {
          const attachments = Array.isArray(m.chat_attachments)
            ? m.chat_attachments.map((att) => {
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
          return {
            id: m.id,
            role: m.role,
            content: m.content,
            timestamp: new Date(m.created_at),
            reasoning: m.reasoning || undefined,
            attachments,
            context: m.context
              ? typeof m.context === "object" && m.context !== null
                ? (m.context as {
                    filters?: Record<string, unknown>;
                    data?: Record<string, unknown>;
                  })
                : undefined
              : undefined,
            suggestedActions: Array.isArray(m.chat_suggested_actions)
              ? m.chat_suggested_actions.map((a: ChatSuggestedActionRow) => ({
                  type: a.type,
                  label: a.label,
                  payload:
                    a.payload &&
                    typeof a.payload === "object" &&
                    a.payload !== null
                      ? (a.payload as Record<string, unknown>)
                      : {},
                }))
              : undefined,
            functionResult: m.function_result
              ? typeof m.function_result === "object" &&
                m.function_result !== null
                ? (m.function_result as {
                    success: boolean;
                    data?: unknown;
                    error?: string;
                  })
                : undefined
              : undefined,
            toolCalls: Array.isArray(m.chat_tool_calls)
              ? m.chat_tool_calls.map((t: ChatToolCallRow) => ({
                  id: t.id,
                  name: t.name,
                  arguments: t.arguments as Record<string, unknown>,
                  result: t.result
                    ? typeof t.result === "object" && t.result !== null
                      ? (t.result as {
                          success: boolean;
                          data?: unknown;
                          error?: string;
                        })
                      : undefined
                    : undefined,
                  reasoning: t.reasoning || undefined,
                }))
              : undefined,
            citations: m.citations
              ? Array.isArray(m.citations)
                ? (m.citations as Array<{
                    url: string;
                    title: string;
                    cited_text: string;
                  }>)
                : undefined
              : undefined,
          };
        })
      );
      setMessagesForSession(sessionId, msgs);
    }
  };

  const handleDeleteSession = async (sessionId: string) => {
    await deleteChatSession(sessionId);
    // update local store and list
    deleteLocalSession(sessionId);
    setSessions((prev) => prev.filter((s) => s.id !== sessionId));
  };

  const handleNewChat = async () => {
    const res = await createChatSession();
    if ("error" in res && res.error) return;
    const row = res.data!;
    const s = {
      id: row.id,
      title: row.title,
      createdAt: new Date(row.created_at),
      updatedAt: new Date(row.updated_at),
      messageCount: 0,
    };
    upsertSessionFromServer({
      id: s.id,
      title: s.title,
      createdAt: s.createdAt,
      updatedAt: s.updatedAt,
      messages: [],
    });
    setCurrentSessionIdFromServer(s.id);
    openSessionTab(s.id);
    setSessions((prev) => [s, ...prev]);
    setShowHistory(false);
  };

  const handleBackToChat = () => {
    setShowHistory(false);
  };

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="flex items-center justify-between p-2 border-b">
        <div className="flex items-center gap-1">
          <Button
            variant="ghost"
            size="icon-sm"
            className="rounded-tl-xl"
            onClick={handleNewChat}
            title="New chat"
          >
            <SquarePen className="size-4" strokeWidth={1} />
          </Button>
        </div>
        <div className="flex items-center gap-1">
          <Button
            variant="ghost"
            size="icon-sm"
            className="rounded-tr-xl"
            onClick={handleBackToChat}
            title="Back to current chat"
          >
            <ChevronRight className="size-4" />
          </Button>
        </div>
      </div>

      {/* Sessions List */}
      <ScrollFadeArea
        className="min-h-0 flex-1"
        contentClassName="p-1"
        watch={sessions.length}
      >
        {loading ? (
          <div className="flex flex-col items-center justify-center text-center gap-2">
            <Skeleton className="h-[4.5rem] w-full" />
            <Skeleton className="h-[4.5rem] w-full" />
            <Skeleton className="h-[4.5rem] w-full" />
          </div>
        ) : sessions.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-8 text-center">
            <MessagesSquare
              className="size-8 text-muted-foreground mb-2"
              strokeWidth={1}
            />
            <p className="text-sm text-muted-foreground mb-4 font-light">
              No chat history yet
            </p>
            <Button
              className="flex items-center "
              variant="outline"
              size="sm"
              onClick={handleNewChat}
            >
              <span className="font-light">Start chat</span>
              <ChevronRight className="size-4" strokeWidth={1} />
            </Button>
          </div>
        ) : (
          <div className="flex flex-col gap-1">
            {sessions.map((session) => (
              <div
                key={session.id}
                className={cn(
                  "group flex flex-col p-2 rounded-lg cursor-pointer overflow-hidden",
                  "hover:bg-accent/50 transition-colors",
                  "border border-transparent",
                  session.id === currentSessionId && "bg-accent border-border",
                )}
                onClick={() => handleSessionClick(session.id)}
              >
                {/* Session Title */}
                <div className="flex items-center gap-2 min-w-0 overflow-hidden justify-between">
                  <h3
                    className={cn(
                      "flex font-medium text-sm overflow-hidden text-ellipsis whitespace-nowrap",
                      session.id === currentSessionId &&
                        "text-accent-foreground",
                    )}
                  >
                    {session.title.slice(0, 20)}
                  </h3>
                  {/* Delete Button */}
                  <div
                    className="opacity-0 group-hover:opacity-100 transition-opacity"
                    onClick={(e) => e.stopPropagation()}
                  >
                    <Button
                      variant="ghost"
                      size="icon-sm"
                      onClick={() => handleDeleteSession(session.id)}
                    >
                      <Trash className="size-4" />
                    </Button>
                  </div>
                </div>

                {/* Session Meta */}
                <div className="flex items-center justify-between text-xs text-muted-foreground pt-2">
                  <span>
                    {session.messageCount} message
                    {session.messageCount !== 1 ? "s" : ""}
                  </span>
                  <span>
                    {formatDistanceToNow(session.updatedAt, {
                      addSuffix: true,
                    })}
                  </span>
                </div>
              </div>
            ))}
          </div>
        )}
      </ScrollFadeArea>
    </div>
  );
}
