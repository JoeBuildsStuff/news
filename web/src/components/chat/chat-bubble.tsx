"use client";

import { Button } from "@/components/ui/button";
import { useChatStore } from "@/lib/chat/chat-store";
import { cn } from "@/lib/utils";
import { XIcon, MessagesSquare } from "lucide-react";

export function ChatBubble() {
  const {
    isOpen,
    isMinimized,
    isMaximized,
    setOpen,
    setMinimized,
    setMaximized,
    layoutMode,
    setLayoutMode,
  } = useChatStore();

  const handleToggle = () => {
    if (!isOpen) {
      // Open in the previously saved layout mode
      if (layoutMode === "inset") {
        setLayoutMode("inset"); // This will set isMaximized=true, isMinimized=false, isOpen=true
      } else if (layoutMode === "fullpage") {
        // Don't open bubble if in full page mode
        return;
      } else {
        setOpen(true);
        setMinimized(false);
        setMaximized(false);
      }
    } else if (isMinimized) {
      // Restore to the current layout mode
      if (layoutMode === "inset") {
        setLayoutMode("inset");
      } else {
        setMinimized(false);
        setMaximized(false);
      }
    } else if (!isMaximized) {
      // Maximize (switch to inset mode)
      setLayoutMode("inset");
    } else {
      // Minimize when maximized
      setMinimized(true);
      setMaximized(false);
    }
  };

  const handleClose = (e: React.MouseEvent) => {
    e.stopPropagation();
    setOpen(false);
    setMinimized(false);
    setMaximized(false);
  };

  // Show bubble when chat is closed or minimized, but not in full page mode
  const showBubble = (!isOpen || isMinimized) && layoutMode !== "fullpage";

  if (!showBubble) {
    return null;
  }

  return (
    <div
      className={cn("fixed bottom-2 right-2 z-50 bg-background rounded-full")}
    >
      {/* Main bubble button */}
      <div
        className={cn(
          "relative group cursor-pointer",
          "transition-all duration-300 ease-in-out",
          "hover:scale-110",
          "bg-background rounded-full"
        )}
        onClick={handleToggle}
      >
        <Button
          variant="blue"
          className="rounded-full size-12 bg-background shadow-md [&_svg]:w-6! [&_svg]:h-6! ring-blue-600"
        >
          <MessagesSquare />
        </Button>

        {/* Close button when minimized */}
        {isMinimized && (
          <Button
            size="sm"
            variant="outline"
            className={cn(
              "absolute -top-2 -right-2",
              "h-6 w-6 rounded-full p-0",
              "bg-background border-border",
              "opacity-0 group-hover:opacity-100",
              "transition-opacity duration-200"
            )}
            onClick={handleClose}
          >
            <XIcon />
          </Button>
        )}
      </div>

      {/* Tooltip */}
      <div
        className={cn(
          "absolute bottom-full right-0 mb-2",
          "bg-popover text-popover-foreground",
          "px-3 py-2 rounded-md text-sm",
          "shadow-md border",
          "opacity-0 group-hover:opacity-100",
          "transition-opacity duration-200",
          "pointer-events-none",
          "whitespace-nowrap"
        )}
      >
        {isMinimized ? "Restore Chat" : "Start Conversation"}
      </div>
    </div>
  );
}
