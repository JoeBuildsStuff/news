"use client";

import { useChatStore } from "@/lib/chat/chat-store";
import { ChatMessage, ChatMessageLoading } from "./chat-message";
import { MessagesSquare } from "lucide-react";
import { MessageScrollerItem } from "@/components/ui/message-scroller";
import { MessageGroup } from "@/components/ui/message";
import type { ChatAction, ChatMessage as ChatMessageType } from "@/types/chat";

interface ChatMessagesListProps {
  onActionClick?: (action: ChatAction) => void;
}

export function ChatMessagesList({
  onActionClick,
}: ChatMessagesListProps = {}) {
  const { messages, isLoading } = useChatStore();
  const lastMessage = messages[messages.length - 1];
  const shouldShowLoading =
    isLoading &&
    !(lastMessage?.role === "assistant" && lastMessage.content.trim());

  if (messages.length === 0 && !isLoading) {
    return (
      <div className="flex-1 flex items-center justify-center p-6">
        <div className="flex flex-col items-center gap-2">
          <MessagesSquare
            className="size-8 text-muted-foreground mb-2"
            strokeWidth={1}
          />
          <p className="text-sm text-muted-foreground mb-4 font-light">
            Start a conversation
          </p>
        </div>
      </div>
    );
  }

  // Collapse runs of consecutive same-role messages into a single MessageGroup
  // so same-sender bubbles read as one visual unit.
  const messageGroups = messages.reduce<ChatMessageType[][]>((groups, message) => {
    const lastGroup = groups[groups.length - 1];
    if (lastGroup && lastGroup[0].role === message.role) {
      lastGroup.push(message);
    } else {
      groups.push([message]);
    }
    return groups;
  }, []);

  return (
    <>
      {messageGroups.map((group) => (
        <MessageGroup key={group[0].id}>
          {group.map((message) => (
            <MessageScrollerItem key={message.id} messageId={message.id}>
              <ChatMessage message={message} onActionClick={onActionClick} />
            </MessageScrollerItem>
          ))}
        </MessageGroup>
      ))}

      {/* Show loading placeholder while waiting for API response */}
      {shouldShowLoading && (
        <MessageScrollerItem>
          <ChatMessageLoading />
        </MessageScrollerItem>
      )}

      {/* Invisible element marking the bottom of the message list */}
      <MessageScrollerItem scrollAnchor className="h-1" />
    </>
  );
}
