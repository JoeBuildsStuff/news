"use client";

import { useChatStore } from "@/lib/chat/chat-store";
import { useChat } from "@/hooks/use-chat";
import { cn } from "@/lib/utils";
import { ChatHeader } from "@/components/chat/chat-header";
import { ChatMessagesList } from "@/components/chat/chat-messages-list";
import { ChatInput } from "@/components/chat/chat-input";
import { ChatHistory } from "@/components/chat/chat-history";
import {
  MessageScroller,
  MessageScrollerButton,
  MessageScrollerContent,
  MessageScrollerProvider,
  MessageScrollerViewport,
} from "@/components/ui/message-scroller";
import { toast } from "sonner";

export function ChatPanel() {
  const { isOpen, isMinimized, isMaximized, showHistory } = useChatStore();

  const { handleActionClick } = useChat({
    onActionClick: (action) => {
      switch (action.type) {
        case "filter": {
          const filterParams = new URLSearchParams(window.location.search);
          filterParams.set(
            `${action.payload.columnId}`,
            String(action.payload.value)
          );
          window.location.assign(
            `${window.location.pathname}?${filterParams.toString()}`
          );
          break;
        }
        case "sort": {
          const sortParams = new URLSearchParams(window.location.search);
          sortParams.set("sortBy", String(action.payload.columnId));
          sortParams.set("sortOrder", String(action.payload.direction));
          window.location.assign(
            `${window.location.pathname}?${sortParams.toString()}`
          );
          break;
        }
        case "navigate": {
          const targetPath = action.payload.clearFilters
            ? String(action.payload.pathname)
            : `${action.payload.pathname}?${window.location.search}`;
          window.location.assign(targetPath);
          break;
        }
        case "create":
          toast.success(`Action: ${action.label}`);
          break;
        case "function_call":
          toast.success(`Executed: ${action.label}`);
          window.location.reload();
          break;
        default:
          console.log("Unknown action type:", action);
      }
    },
  });

  // Don't render if not open or minimized
  if (!isOpen || isMinimized) {
    return null;
  }

  return (
    <div
      className={cn(
        "z-40 bg-background border border-border flex flex-col transition-all duration-300 ease-in-out",
        // Maximized (inset): full-screen overlay on mobile; in-flow right
        // column on md+ so ChatShell's flex row pushes main content left.
        isMaximized && [
          "fixed inset-0 z-50",
          "md:relative md:inset-auto md:z-auto md:h-full md:w-96 md:shrink-0",
          "border-l border-t-0 border-r-0 border-b-0 rounded-none",
        ],
        // Normal state - floating panel (fixed, out of document flow)
        !isMaximized && [
          "fixed inset-x-0 top-0 bottom-9 sm:inset-auto sm:bottom-9 sm:right-1",
          "w-full h-auto sm:w-96 sm:h-[600px]",
          "rounded-none sm:rounded-3xl sm:shadow-2xl",
        ]
      )}
    >
      {showHistory ? (
        // Chat History View
        <ChatHistory />
      ) : (
        // Regular Chat View
        <>
          {/* Chat Header */}
          <ChatHeader />

          {/* Messages Area */}
          <div className="flex-1 flex flex-col min-h-0">
            <MessageScrollerProvider autoScroll defaultScrollPosition="end">
              <MessageScroller>
                <MessageScrollerViewport>
                  <MessageScrollerContent className="p-3">
                    <ChatMessagesList onActionClick={handleActionClick} />
                  </MessageScrollerContent>
                </MessageScrollerViewport>
                <MessageScrollerButton />
              </MessageScroller>
            </MessageScrollerProvider>
          </div>

          {/* Input Area */}
          <div className="bg-transparent">
            <ChatInput />
          </div>
        </>
      )}
    </div>
  );
}
