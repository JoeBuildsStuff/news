"use client";

import { useChatStore } from "@/lib/chat/chat-store";
import { useChat } from "@/hooks/use-chat";
import { ChatMessagesList } from "@/components/chat/chat-messages-list";
import { ChatInput } from "@/components/chat/chat-input";
import {
  MessageScroller,
  MessageScrollerButton,
  MessageScrollerContent,
  MessageScrollerProvider,
  MessageScrollerViewport,
} from "@/components/ui/message-scroller";
import { toast } from "sonner";
import { PictureInPicture2, PanelRight, LaptopMinimal } from "lucide-react";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";

export function ChatFullPage() {
  const { setLayoutMode } = useChatStore();

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

  return (
    <div className="h-full flex flex-col relative">
      <div className="absolute top-0 left-0 z-10 flex items-center justify-center">
        <ToggleGroup
          value={["fullpage"]}
          size="sm"
          className="bg-background/95 backdrop-blur border rounded-lg"
        >
          <ToggleGroupItem
            value="floating"
            onClick={() => setLayoutMode("floating")}
            aria-label="Floating mode"
          >
            <PictureInPicture2 className="size-4" />
          </ToggleGroupItem>
          <ToggleGroupItem
            value="inset"
            onClick={() => setLayoutMode("inset")}
            aria-label="Inset mode"
          >
            <PanelRight className="size-4" />
          </ToggleGroupItem>
          <ToggleGroupItem
            value="fullpage"
            aria-label="Full page mode"
          >
            <LaptopMinimal className="size-4" />
          </ToggleGroupItem>
        </ToggleGroup>
      </div>

      <div className="flex-1 flex flex-col min-h-0 max-w-3xl mx-auto w-full">
        <div className="flex-1 flex flex-col min-h-0">
          <MessageScrollerProvider autoScroll defaultScrollPosition="end">
            <MessageScroller>
              <MessageScrollerViewport>
                <MessageScrollerContent>
                  <ChatMessagesList onActionClick={handleActionClick} />
                </MessageScrollerContent>
              </MessageScrollerViewport>
              <MessageScrollerButton />
            </MessageScroller>
          </MessageScrollerProvider>
        </div>
        <div className="">
          <ChatInput />
        </div>
      </div>
    </div>
  );
}
