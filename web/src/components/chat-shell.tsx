import { ChatProvider } from "@/components/chat/chat-provider"
import { ChatPanel } from "@/components/chat/chat-panel"
import { ChatFooterBar } from "@/components/chat/chat-footer-bar"
import { Toaster } from "@/components/ui/sonner"

/**
 * Chat chrome matches tech-stack-010226 dashboard layout:
 * content scrolls in a flex column; ChatFooterBar is pinned at the bottom
 * (open tabs + Ask Chat + history). Inset mode puts ChatPanel in the row so
 * main content shrinks; floating mode keeps the panel fixed above.
 */
export function ChatShell({ children }: { children: React.ReactNode }) {
  return (
    <ChatProvider>
      <div className="flex h-dvh min-h-0 w-full overflow-hidden">
        <div className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden">
          <div className="min-h-0 flex-1 overflow-auto">{children}</div>
          <ChatFooterBar />
        </div>
        <ChatPanel />
      </div>
      <Toaster />
    </ChatProvider>
  )
}
