import { useChatStore } from "@/lib/chat/chat-store"
import { ChatProvider } from "@/components/chat/chat-provider"
import { ChatPanel } from "@/components/chat/chat-panel"
import { ChatFooterBar } from "@/components/chat/chat-footer-bar"
import { ChatBubble } from "@/components/chat/chat-bubble"
import { Toaster } from "@/components/ui/sonner"
import { cn } from "@/lib/utils"

export function ChatShell({ children }: { children: React.ReactNode }) {
  const isMaximized = useChatStore((s) => s.isMaximized)

  return (
    <ChatProvider>
      <div
        className={cn(
          "min-h-svh w-full transition-all duration-300 ease-in-out",
          isMaximized && "md:mr-96"
        )}
      >
        {children}
      </div>
      <ChatBubble />
      <ChatFooterBar />
      <ChatPanel />
      <Toaster />
    </ChatProvider>
  )
}
