"use client";

import { formatDistanceToNow } from "date-fns";
import { Lightbulb } from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import rehypeHighlight from "rehype-highlight";
import type { ChatMessage as ChatMessageType, ChatAction } from "@/types/chat";
import { cn } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import ChatMessageActions from "./chat-message-actions";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { AttachmentGroup } from "@/components/ui/attachment";
import {
  Message,
  MessageContent,
  MessageHeader,
  MessageFooter,
} from "@/components/ui/message";
import { Bubble, BubbleContent } from "@/components/ui/bubble";
import { Marker, MarkerIcon, MarkerContent } from "@/components/ui/marker";
import {
  ToolCall,
  ToolCallTrigger,
  ToolCallContent,
  ToolCallPanel,
  ToolCallPanelTrigger,
  ToolCallPanelContent,
  ToolCallCode,
} from "@/components/ui/tool-call";
import { toast } from "sonner";
import {
  formatToolCallArguments,
  formatToolCallResult,
} from "@/lib/chat/utils";
import { useState } from "react";
import { useChatStore } from "@/lib/chat/chat-store";
import { useChat } from "@/hooks/use-chat";
import Spinner from "@/components/ui/spinner";
import { ChatAttachmentCard } from "@/components/chat/chat-attachment-card";
import { AttachmentPreviewDialog } from "@/components/chat/attachment-preview-dialog";
import type { ChatAttachmentLike } from "@/lib/chat/attachments";

// Import highlight.js styles
import "highlight.js/styles/github-dark.css";

interface ChatMessageProps {
  message: ChatMessageType;
  onActionClick?: (action: ChatAction) => void;
}

// Citation component with popover
const CitationPopover = ({
  citationNumber,
  citation,
}: {
  citationNumber: number;
  citation: { url: string; title: string; cited_text: string };
}) => {
  return (
    <Popover>
      <PopoverTrigger>
        <Badge className="" variant="blue">
          {citationNumber}
        </Badge>
      </PopoverTrigger>
      <PopoverContent className="p-3" align="start">
        <div className="space-y-2">
          <a
            href={citation.url}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-block"
          >
            <Badge
              variant="blue"
              className="font-medium text-sm break-words whitespace-normal"
            >
              {citation.title}
            </Badge>
          </a>
          {citation.cited_text && (
            <div className="text-xs text-muted-foreground italic border-l-2 border-muted pl-2">
              &ldquo;
              {citation.cited_text.length > 150
                ? citation.cited_text.substring(0, 150) + "..."
                : citation.cited_text}
              &rdquo;
            </div>
          )}
        </div>
      </PopoverContent>
    </Popover>
  );
};

// Reasoning component
const ReasoningDisplay = ({ reasoning }: { reasoning: string }) => {
  return (
    <Bubble className="mb-2 w-72 overflow-hidden rounded-lg bg-muted/40">
      <Marker className="gap-2 px-3 pt-2 pb-1 text-muted-foreground">
        <MarkerIcon>
          <Lightbulb className="size-3.5 shrink-0" strokeWidth={1.5} />
        </MarkerIcon>
        <MarkerContent className="text-xs font-medium">Reasoning</MarkerContent>
      </Marker>
      <BubbleContent className="px-3 pb-2 text-sm break-words">
        <div className="typeset typeset-docs">
          <ReactMarkdown
            remarkPlugins={[remarkGfm]}
            rehypePlugins={[rehypeHighlight]}
          >
            {reasoning}
          </ReactMarkdown>
        </div>
      </BubbleContent>
    </Bubble>
  );
};

// Function to render text with inline citations
const renderTextWithCitations = (
  text: string,
  citations: Array<{ url: string; title: string; cited_text: string }>
) => {
  // Find all citation patterns like [1], [2], etc.
  const citationRegex = /\[(\d+)\]/g;
  const parts = [];
  let lastIndex = 0;
  let match;

  while ((match = citationRegex.exec(text)) !== null) {
    // Add text before the citation
    if (match.index > lastIndex) {
      parts.push(text.slice(lastIndex, match.index));
    }

    // Add the citation popover
    const citationNumber = parseInt(match[1]);
    const citation = citations[citationNumber - 1]; // Citations are 1-indexed

    if (citation) {
      parts.push(
        <CitationPopover
          key={`citation-${citationNumber}-${match.index}`}
          citationNumber={citationNumber}
          citation={citation}
        />
      );
    } else {
      // If citation not found, just show the number
      parts.push(match[0]);
    }

    lastIndex = match.index + match[0].length;
  }

  // Add remaining text
  if (lastIndex < text.length) {
    parts.push(text.slice(lastIndex));
  }

  return parts.length > 1 ? <>{parts}</> : text;
};

// Loading placeholder component
export function ChatMessageLoading() {
  return (
    <Message align="start" className="px-0 py-2">
      <MessageContent>
        {/* Loading message bubble */}
        <Bubble>
          <BubbleContent className="rounded-lg px-3 py-2 text-sm bg-muted flex items-center gap-2">
            <Spinner className="stroke-5 size-4 stroke-muted-foreground" />
            {/* <span className="text-muted-foreground">Thinking...</span> */}
          </BubbleContent>
        </Bubble>
      </MessageContent>
    </Message>
  );
}

export function ChatMessage({ message, onActionClick }: ChatMessageProps) {
  const isUser = message.role === "user";
  const isSystem = message.role === "system";
  const [isEditing, setIsEditing] = useState(false);
  const [editContent, setEditContent] = useState(message.content);
  const [selectedAttachment, setSelectedAttachment] =
    useState<ChatAttachmentLike | null>(null);
  const { editMessage, retryMessage } = useChatStore();
  const { sendMessage } = useChat();

  // Whether the message has any visible body yet. An assistant message starts
  // out empty while streaming, so its header/body should stay hidden until real
  // content (or tool calls/reasoning/attachments) has arrived.
  const hasRenderableBody =
    message.content.trim().length > 0 ||
    (message.toolCalls?.length ?? 0) > 0 ||
    (message.attachments?.length ?? 0) > 0 ||
    Boolean(message.reasoning);

  // The footer actions (copy/retry/edit/thumbs) act on the final text response,
  // so they should only appear once there's actual content — not while a tool
  // call is still running and the text hasn't streamed in yet.
  const hasActionableContent =
    message.content.trim().length > 0 || Boolean(message.functionResult);

  const handleEdit = () => {
    setIsEditing(true);
  };

  const handleEditSave = () => {
    if (editContent.trim() !== message.content) {
      editMessage(message.id, editContent.trim());
      toast.success("Message updated");
      // After updating the message content, trim chat history to this point
      // and resend the edited message to get a fresh assistant reply.
      retryMessage(message.id, (content) => {
        // Resend using the existing user message (no new user bubble)
        sendMessage(content, undefined, undefined, undefined, {
          skipUserAdd: true,
        });
      });
    }
    setIsEditing(false);
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleEditSave();
    } else if (e.key === "Escape") {
      handleEditCancel();
    }
  };

  const handleEditCancel = () => {
    setEditContent(message.content);
    setIsEditing(false);
  };

  const openAttachmentModal = (attachment: ChatAttachmentLike) => {
    setSelectedAttachment(attachment);
  };

  const closeAttachmentModal = () => {
    setSelectedAttachment(null);
  };

  // System messages get a centered pill treatment outside the Message layout
  if (isSystem) {
    return (
      <div className="flex justify-center py-2">
        <span className="bg-muted/50 text-muted-foreground text-xs italic px-4 py-1 rounded-full">
          {message.content}
        </span>
      </div>
    );
  }

  return (
    <>
      <Message align={isUser ? "end" : "start"} className="px-0 py-2">
        <MessageContent className={cn("gap-1", isUser && "items-end")}>
          {/* Timestamp */}
          {hasRenderableBody && (
            <MessageHeader className={cn("px-1", isUser && "justify-end")}>
              <span className="text-xs text-muted-foreground">
                {formatDistanceToNow(message.timestamp, { addSuffix: true })}
              </span>
            </MessageHeader>
          )}

          {/* Attachments - shown for user messages */}
          {isUser && message.attachments && message.attachments.length > 0 && (
            <AttachmentGroup className="max-w-72 gap-1.5 pb-1">
              {message.attachments.map((attachment) => (
                <ChatAttachmentCard
                  key={attachment.id}
                  attachment={attachment}
                  variant="message"
                  onPreview={openAttachmentModal}
                />
              ))}
            </AttachmentGroup>
          )}

          {/* Reasoning - shown before tool calls and content for non-system messages */}
          {message.reasoning && (
            <ReasoningDisplay reasoning={message.reasoning} />
          )}

          {/* Tool calls with individual reasoning - shown before the response for non-system messages */}
          {message.toolCalls && message.toolCalls.length > 0 && (
            <div className="space-y-2 mb-2 w-72">
              {message.toolCalls.map((toolCall) => (
                <div key={toolCall.id} className="space-y-2">
                  {/* Reasoning for this specific tool call */}
                  {toolCall.reasoning && (
                    <ReasoningDisplay reasoning={toolCall.reasoning} />
                  )}

                  {/* Tool call */}
                  <ToolCall>
                    <ToolCallTrigger>
                      <Marker className="gap-2">
                        <MarkerIcon>
                          {toolCall.result ? (
                            <Lightbulb
                              className="size-4 shrink-0"
                              strokeWidth={1.5}
                            />
                          ) : (
                            <Spinner className="size-4 shrink-0 stroke-current" />
                          )}
                        </MarkerIcon>
                        <MarkerContent className="text-sm">
                          {toolCall.result
                            ? toolCall.name
                            : `Running ${toolCall.name}…`}
                        </MarkerContent>
                      </Marker>
                    </ToolCallTrigger>
                    <ToolCallContent>
                      {/* Tool Arguments - independently collapsible */}
                      <ToolCallPanel>
                        <ToolCallPanelTrigger>Request</ToolCallPanelTrigger>
                        <ToolCallPanelContent>
                          <ToolCallCode
                            value={formatToolCallArguments(toolCall.arguments)}
                            copyLabel="Arguments copied to clipboard"
                          />
                        </ToolCallPanelContent>
                      </ToolCallPanel>
                      {/* Tool Result - independently collapsible */}
                      {toolCall.result && (
                        <ToolCallPanel>
                          <ToolCallPanelTrigger>
                            Result:{" "}
                            {toolCall.result.success ? "Success" : "Error"}
                          </ToolCallPanelTrigger>
                          <ToolCallPanelContent>
                            <ToolCallCode
                              value={formatToolCallResult(toolCall.result)}
                              copyLabel="Result copied to clipboard"
                            />
                          </ToolCallPanelContent>
                        </ToolCallPanel>
                      )}
                    </ToolCallContent>
                  </ToolCall>
                </div>
              ))}
            </div>
          )}

          {/* Message bubble or editing textarea */}
          {isEditing && isUser ? (
            <Bubble align="end">
              <BubbleContent className="rounded-lg px-3 py-2 text-sm bg-muted">
                <Textarea
                  value={editContent}
                  onChange={(e) => setEditContent(e.target.value)}
                  onKeyDown={handleKeyDown}
                  className="bg-transparent dark:bg-transparent shadow-none border-none focus-visible:ring-0 focus-visible:ring-offset-0 focus-visible:border-none p-0 resize-none"
                  placeholder="Edit your message..."
                  autoFocus
                />
                <div className="flex gap-2 items-center justify-end">
                  <Button
                    size="sm"
                    onClick={handleEditCancel}
                    variant="outline"
                  >
                    Cancel
                  </Button>
                  <Button size="sm" onClick={handleEditSave} variant="outline">
                    Send
                  </Button>
                </div>
              </BubbleContent>
            </Bubble>
          ) : // Only render message bubble if there's content
          message.content.trim() ? (
            <Bubble align={isUser ? "end" : "start"}>
              <BubbleContent
                className={cn(
                  "rounded-lg px-3 py-2 text-sm break-words",
                  isUser ? "bg-muted" : "text-foreground"
                )}
              >
                <div className="typeset typeset-docs">
                  <ReactMarkdown
                    remarkPlugins={[remarkGfm]}
                    rehypePlugins={[rehypeHighlight]}
                    components={{
                      // Citation wiring only — typography comes from typeset
                      p: ({ children }) => {
                        if (typeof children === "string") {
                          return (
                            <p>
                              {renderTextWithCitations(
                                children,
                                message.citations || []
                              )}
                            </p>
                          );
                        }
                        return <p>{children}</p>;
                      },
                      li: ({ children }) => {
                        if (typeof children === "string") {
                          return (
                            <li>
                              {renderTextWithCitations(
                                children,
                                message.citations || []
                              )}
                            </li>
                          );
                        }
                        return <li>{children}</li>;
                      },
                      text: ({ children }) => {
                        if (typeof children === "string") {
                          return renderTextWithCitations(
                            children,
                            message.citations || []
                          );
                        }
                        return children;
                      },
                    }}
                  >
                    {message.content}
                  </ReactMarkdown>
                </div>
              </BubbleContent>
            </Bubble>
          ) : null}

          {/* Only show actions when not editing and there's content to act on */}
          {hasActionableContent && (
            <MessageFooter className={cn(isUser && "justify-end")}>
              {!isEditing && (
                <ChatMessageActions message={message} onEdit={handleEdit} />
              )}

              {/* Function result indicator */}
              {message.functionResult && (
                <Badge
                  variant={message.functionResult.success ? "green" : "red"}
                  className="mt-1"
                >
                  {message.functionResult.success
                    ? "✓ Action completed"
                    : "✗ Action failed"}
                </Badge>
              )}
            </MessageFooter>
          )}

          {/* Suggested actions */}
          {message.suggestedActions && message.suggestedActions.length > 0 && (
            <div
              className={cn(
                "flex flex-wrap gap-2 mt-2",
                isUser && "justify-end"
              )}
            >
              {message.suggestedActions.map((action, index) => (
                <button
                  key={index}
                  className={cn(
                    "text-xs px-2 py-1 rounded-md",
                    "bg-secondary text-secondary-foreground",
                    "hover:bg-secondary/80 transition-colors",
                    "border border-border"
                  )}
                  onClick={() => onActionClick?.(action)}
                >
                  {action.label}
                </button>
              ))}
            </div>
          )}
        </MessageContent>
      </Message>

      <AttachmentPreviewDialog
        attachment={selectedAttachment}
        onOpenChange={closeAttachmentModal}
      />
    </>
  );
}
