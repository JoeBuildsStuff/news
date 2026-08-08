"use client";

import { createContext, useContext } from "react";
import { useChatStore } from "@/lib/chat/chat-store";
import type { ChatContextValue, ChatProviderProps } from "@/types/chat";

const ChatContext = createContext<ChatContextValue | null>(null);

export function ChatProvider({ children }: ChatProviderProps) {
  const store = useChatStore();

  // Initialize context value that maps store to the expected interface
  const contextValue: ChatContextValue = {
    // Session management
    sessions: store.sessions,
    currentSessionId: store.currentSessionId,
    currentSession: store.currentSession,

    // Legacy support - maps to current session
    messages: store.messages,
    isOpen: store.isOpen,
    isMinimized: store.isMinimized,
    isMaximized: store.isMaximized,
    currentContext: store.currentContext,

    // Session actions
    createSession: store.createSession,
    switchToSession: store.switchToSession,
    deleteSession: store.deleteSession,
    updateSessionTitle: store.updateSessionTitle,
    getSessions: store.getSessions,

    // Message actions
    addMessage: store.addMessage,
    updateMessage: store.updateMessage,
    deleteMessage: store.deleteMessage,
    clearMessages: store.clearMessages,

    // UI state
    setOpen: store.setOpen,
    setMinimized: store.setMinimized,
    setMaximized: store.setMaximized,
    toggleChat: store.toggleChat,
    showHistory: store.showHistory,
    setShowHistory: store.setShowHistory,

    // Context
    updatePageContext: store.updatePageContext,

    // Utility
    getUnreadCount: store.getUnreadCount,
  };

  return (
    <ChatContext.Provider value={contextValue}>{children}</ChatContext.Provider>
  );
}

export function useChatContext() {
  const context = useContext(ChatContext);
  if (!context) {
    throw new Error("useChatContext must be used within a ChatProvider");
  }
  return context;
}

// Convenience hook that provides additional computed values
export function useChat() {
  const context = useChatContext();

  const hasMessages = context.messages.length > 0;
  const lastMessage = hasMessages
    ? context.messages[context.messages.length - 1]
    : null;

  return {
    ...context,
    hasMessages,
    lastMessage,
  };
}
