"use client";

// Purpose: This component renders the chat footer bar, which includes session tabs, new chat button, and chat history button.

import { useState } from "react";
import { MessagesSquare, GalleryVerticalEnd, X } from "lucide-react";
import { createChatSession } from "@/actions/chat";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { useHydrateOpenChatTabs } from "@/components/chat/use-hydrate-open-chat-tabs";
import { useChatStore } from "@/lib/chat/chat-store";
import { cn } from "@/lib/utils";

// Main footer bar for chat sessions
export function ChatFooterBar() {
  // Chat state from the global store
  const {
    isOpen,
    isMinimized,
    isMaximized,
    setOpen,
    setMinimized,
    setMaximized,
    layoutMode,
    setLayoutMode,
    sessions,
    switchToSession,
    setShowHistory,
    currentSessionId,
    openSessionIds,
    openSessionTab,
    closeSessionTab,
    upsertSessionFromServer,
    setCurrentSessionIdFromServer,
  } = useChatStore();
  // Tracks whether a chat session is being created
  const [isCreating, setIsCreating] = useState(false);
  useHydrateOpenChatTabs();

  // Handler for creating a new chat session ("Ask Chat" button)
  const handleAskChat = async () => {
    if (isCreating) return;
    setIsCreating(true);
    try {
      const res = await createChatSession();
      if ("error" in res && res.error) return;
      const row = res.data!;
      // Add new session to the store from server response
      upsertSessionFromServer({
        id: row.id,
        title: row.title,
        createdAt: new Date(row.created_at),
        updatedAt: new Date(row.updated_at),
        messages: [],
      });
      setCurrentSessionIdFromServer(row.id);
      if (layoutMode === "inset") {
        setLayoutMode("inset");
      } else {
        setOpen(true);
        setMinimized(false);
        setMaximized(false);
      }
      setShowHistory(false);
    } finally {
      setIsCreating(false);
    }
  };

  // Switch to an existing session tab or open it if minimized/closed
  const handleOpenSession = (sessionId: string) => {
    switchToSession(sessionId);
    openSessionTab(sessionId);
    setShowHistory(false);
    if (!isOpen || isMinimized) {
      if (layoutMode === "inset") {
        setLayoutMode("inset");
      } else {
        setOpen(true);
        setMinimized(false);
        setMaximized(false);
      }
    }
  };

  // Toggle, and open if necessary, the chat history sidebar
  const handleToggleHistory = () => {
    if (!isOpen || isMinimized) {
      setOpen(true);
      setMinimized(false);
      setMaximized(false);
      setShowHistory(true);
    } else {
      setShowHistory(true);
    }
  };

  // Don't render the footer bar if chat is in fullpage layout
  if (layoutMode === "fullpage") {
    return null;
  }

  // Prepare open sessions for tab rendering
  const openSessions = openSessionIds
    .map((id) => sessions.find((s) => s.id === id))
    .filter((s): s is NonNullable<typeof s> => s != null);

  return (
    // Main footer container.
    // While the inset panel is full screen on mobile it provides its own
    // input, so hide the footer there to avoid overlapping the chat input.
    <div
      className={cn(
        "-mx-2 shrink-0 z-50 flex min-h-9 items-center bg-background px-2",
        isMaximized && "max-md:hidden"
      )}
    >
      {/* Right-aligned cluster: session tabs + actions */}
      <div className="ml-auto flex min-w-0 flex-1 items-center justify-end gap-1 py-1">
        {/* Session tabs area */}
        <ScrollArea className="min-w-0 max-w-full flex-1">
          <div className="flex w-max items-center gap-0.5">
            {openSessions.map((session) => {
              // Mark tab as active if relevant session & window state
              const isActive =
                session.id === currentSessionId && isOpen && !isMinimized;
              return (
                // Session tab wrapper
                <div
                  key={session.id}
                  className={cn(
                    "group flex max-w-[240px] shrink-0 items-center justify-between rounded-md px-2 py-1 transition-colors hover:bg-secondary",
                    isActive &&
                      "bg-secondary text-secondary-foreground hover:bg-secondary"
                  )}
                >
                  {/* Clickable tab label for switching to session */}
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => handleOpenSession(session.id)}
                    className="relative h-auto min-w-0 flex-1 justify-start overflow-hidden px-0 text-left hover:bg-transparent"
                  >
                    {/* Session title */}
                    <span
                      className={cn(
                        "block truncate whitespace-nowrap text-xs",
                        isActive
                          ? "text-secondary-foreground"
                          : "text-muted-foreground"
                      )}
                    >
                      {session.title}
                    </span>
                    {/* Gradient fade on tab edge */}
                    <div
                      className={cn(
                        "pointer-events-none absolute inset-y-0 right-0 w-8 bg-linear-to-r from-transparent transition-all group-hover:w-10",
                        isActive
                          ? "to-accent group-hover:to-accent"
                          : "to-background group-hover:to-secondary"
                      )}
                    />
                  </Button>
                  {/* Close tab "X" button */}
                  <Button
                    variant="ghost"
                    size="icon"
                    aria-label="Close tab"
                    onClick={() => closeSessionTab(session.id)}
                    className="ml-1 size-0 shrink-0 overflow-hidden p-0 opacity-0 transition-all group-hover:size-4 group-hover:opacity-100 hover:bg-transparent"
                  >
                    <X
                      className={cn(
                        "h-3.5 w-3.5 shrink-0 text-muted-foreground hover:text-foreground",
                        isActive &&
                          "text-accent-foreground/70 hover:text-accent-foreground"
                      )}
                    />
                  </Button>
                </div>
              );
            })}
          </div>
        </ScrollArea>

        {/* Action buttons on the right */}
        <div className="flex shrink-0 items-center gap-0.5">
          {/* "Ask Chat" button: creates new chat session */}
          <Button
            variant="blue"
            size="sm"
            className="gap-1.5 px-3 text-xs"
            onClick={handleAskChat}
            disabled={isCreating}
          >
            <MessagesSquare className="size-3.5" />
            Ask Chat
          </Button>

          {/* History button: opens chat history side panel */}
          <Button
            variant="ghost"
            size="icon-sm"
            className="text-muted-foreground hover:text-foreground"
            onClick={handleToggleHistory}
            title="Chat history"
          >
            <GalleryVerticalEnd className="size-3.5" />
          </Button>
        </div>
      </div>
    </div>
  );
}
