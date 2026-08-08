import { StrictMode } from "react"
import { createRoot } from "react-dom/client"

import "./index.css"
import "highlight.js/styles/github-dark.css"
import App from "./App.tsx"
import { ThemeProvider } from "@/components/theme-provider.tsx"
import { ChatShell } from "@/components/chat-shell"

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <ThemeProvider>
      <ChatShell>
        <App />
      </ChatShell>
    </ThemeProvider>
  </StrictMode>
)
