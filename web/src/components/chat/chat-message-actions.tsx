import type { ChatMessage } from "@/types/chat";
import { Button } from "../ui/button";
import {
  ChevronLeft,
  ChevronRight,
  Pencil,
  RotateCcw,
  ThumbsUp,
  ThumbsDown,
} from "lucide-react";
import { useChatStore } from "@/lib/chat/chat-store";
import { useChat } from "@/hooks/use-chat";
import { toast } from "sonner";
import { CopyButton } from "@/components/ui/copy-button";

import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "../ui/tooltip";

interface ChatMessageActionsProps {
  message: ChatMessage;
  onEdit?: () => void;
}

export default function ChatMessageActions({
  message,
  onEdit,
}: ChatMessageActionsProps) {
  const {
    retryMessage,
    getBranchStatus,
    getAssistantVariantStatus,
    goToPreviousMessageList,
    goToNextMessageList,
    goToPreviousVariant,
    goToNextVariant,
  } = useChatStore();
  const { sendMessage } = useChat();

  const handleRetry = () => {
    // If retry is clicked on an assistant message, retry the preceding user message
    const { messages } = useChatStore.getState();
    let targetMessageId = message.id;

    if (message.role === "assistant") {
      const idx = messages.findIndex((m) => m.id === message.id);
      const prevUser = [...messages]
        .slice(0, idx)
        .reverse()
        .find((m) => m.role === "user");
      if (prevUser) targetMessageId = prevUser.id;
    }

    retryMessage(targetMessageId, (content) => {
      // Resend using the existing user message (keep place, no new bubble)
      sendMessage(content, undefined, undefined, undefined, {
        skipUserAdd: true,
      });
    });
    toast.success("Retrying message...");
  };

  const handleUpvote = () => {
    // TODO: Implement upvote functionality
    toast.success("Message upvoted");
  };

  const handleDownvote = () => {
    // TODO: Implement downvote functionality
    toast.success("Message downvoted");
  };

  return (
    <TooltipProvider>
      {/* Show copy button for all messages */}
      <div className="flex">
        <CopyButton
          textToCopy={message.content}
          successMessage="Message copied to clipboard"
          tooltipText="Copy"
          tooltipCopiedText="Copied!"
          iconSize={16}
          className="p-2 m-0 h-fit w-fit text-muted-foreground hover:text-primary"
        />

        {/* Show Retry, Upvote, Downvote, and Response navigation for assistant messages */}
        {message.role === "assistant" && (
          <>
            <Tooltip>
              <TooltipTrigger asChild>
                <Button
                  variant="ghost"
                  size="icon"
                  className="p-2 m-0 h-fit w-fit text-muted-foreground"
                  onClick={handleUpvote}
                >
                  <ThumbsUp size={16} />
                </Button>
              </TooltipTrigger>
              <TooltipContent
                side="bottom"
                align="center"
                sideOffset={4}
                className="text-secondary-foreground bg-secondary"
                arrowClassName="bg-secondary fill-secondary"
              >
                Upvote
              </TooltipContent>
            </Tooltip>
            <Tooltip>
              <TooltipTrigger asChild>
                <Button
                  variant="ghost"
                  size="icon"
                  className="p-2 m-0 h-fit w-fit text-muted-foreground"
                  onClick={handleDownvote}
                >
                  <ThumbsDown size={16} />
                </Button>
              </TooltipTrigger>
              <TooltipContent
                side="bottom"
                align="center"
                sideOffset={4}
                className="text-secondary-foreground bg-secondary"
                arrowClassName="bg-secondary fill-secondary"
              >
                Downvote
              </TooltipContent>
            </Tooltip>
            <Tooltip>
              <TooltipTrigger asChild>
                <Button
                  variant="ghost"
                  size="icon"
                  className="p-2 m-0 h-fit w-fit text-muted-foreground hover:text-primary"
                  onClick={handleRetry}
                >
                  <RotateCcw />
                </Button>
              </TooltipTrigger>
              <TooltipContent
                side="bottom"
                align="center"
                sideOffset={4}
                className="text-secondary-foreground bg-secondary"
                arrowClassName="bg-secondary fill-secondary"
              >
                Retry
              </TooltipContent>
            </Tooltip>
            {(() => {
              // Assistant-level navigation should cycle variants for the same prompt content only
              const { messages } = useChatStore.getState();
              const idx = messages.findIndex((m) => m.id === message.id);
              const prevUser = [...messages]
                .slice(0, idx)
                .reverse()
                .find((m) => m.role === "user");
              if (!prevUser) return null;
              const { current, total } = getAssistantVariantStatus(prevUser.id);
              if (total <= 1) return null;
              return (
                <div className="flex items-center gap-0.5">
                  <Button
                    variant="ghost"
                    size="icon"
                    className="p-1 m-0 h-fit w-fit text-muted-foreground hover:text-primary"
                    onClick={() => goToPreviousVariant(prevUser.id)}
                    disabled={current <= 1}
                  >
                    <ChevronLeft
                      className="size-5 shrink-0"
                      strokeWidth={1.5}
                    />
                  </Button>
                  <span className="text-muted-foreground text-sm">
                    {current} / {total}
                  </span>
                  <Button
                    variant="ghost"
                    size="icon"
                    className="p-1 m-0 h-fit w-fit text-muted-foreground hover:text-primary"
                    onClick={() => goToNextVariant(prevUser.id)}
                    disabled={current >= total}
                  >
                    <ChevronRight
                      className="size-5 shrink-0"
                      strokeWidth={1.5}
                    />
                  </Button>
                </div>
              );
            })()}
          </>
        )}

        {/* Show Edit for user messages */}
        {message.role === "user" && onEdit && (
          <>
            <Tooltip>
              <TooltipTrigger asChild>
                <Button
                  variant="ghost"
                  size="icon"
                  className="p-2 m-0 h-fit w-fit text-muted-foreground hover:text-primary"
                  onClick={onEdit}
                >
                  <Pencil className="size-4 shrink-0" strokeWidth={1.5} />
                </Button>
              </TooltipTrigger>
              <TooltipContent
                side="bottom"
                align="center"
                sideOffset={4}
                className="text-secondary-foreground bg-secondary"
                arrowClassName="bg-secondary fill-secondary"
              >
                Edit
              </TooltipContent>
            </Tooltip>
            {(() => {
              const { current, total } = getBranchStatus(message.id);
              if (total <= 1) return null;
              return (
                <div className="flex items-center gap-0.5">
                  <Button
                    variant="ghost"
                    size="icon"
                    className="p-1 m-0 h-fit w-fit text-muted-foreground hover:text-primary"
                    onClick={() => goToPreviousMessageList(message.id)}
                    disabled={current <= 1}
                  >
                    <ChevronLeft
                      className="size-5 shrink-0"
                      strokeWidth={1.5}
                    />
                  </Button>
                  <span className="text-muted-foreground text-sm">
                    {current} / {total}
                  </span>
                  <Button
                    variant="ghost"
                    size="icon"
                    className="p-1 m-0 h-fit w-fit text-muted-foreground hover:text-primary"
                    onClick={() => goToNextMessageList(message.id)}
                    disabled={current >= total}
                  >
                    <ChevronRight
                      className="size-5 shrink-0"
                      strokeWidth={1.5}
                    />
                  </Button>
                </div>
              );
            })()}
          </>
        )}
      </div>
    </TooltipProvider>
  );
}
