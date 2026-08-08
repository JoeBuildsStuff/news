import React from 'react'
import type { ChatMessage, ChatAction, PageContext } from '@/lib/chat/chat-store'

// Re-export core types from the store for convenience
export type { ChatMessage, ChatAction, PageContext }

/** JSON-compatible values used by chat persistence / tool payloads. */
export type Json =
  | string
  | number
  | boolean
  | null
  | { [key: string]: Json | undefined }
  | Json[]

export type ChatRole = "user" | "assistant" | "system"

export interface ChatAttachmentRow {
  id: string
  message_id: string
  name: string
  mime_type: string
  size: number
  storage_path: string
  width: number | null
  height: number | null
  created_at: string
}

export interface ChatToolCallRow {
  id: string
  message_id: string
  name: string
  arguments: unknown
  result: unknown | null
  reasoning: string | null
  created_at: string
}

export interface ChatSuggestedActionRow {
  id: string
  message_id: string
  type: "filter" | "sort" | "navigate" | "create" | "function_call"
  label: string
  payload: unknown
  created_at: string
}

export interface ChatMessageRow {
  id: string
  session_id: string
  parent_id: string | null
  role: ChatRole
  content: string
  reasoning: string | null
  context: unknown | null
  function_result: unknown | null
  citations: unknown | null
  root_user_message_id: string | null
  variant_group_id: string | null
  variant_index: number
  created_at: string
  seq: number
  chat_attachments: ChatAttachmentRow[]
  chat_tool_calls: ChatToolCallRow[]
  chat_suggested_actions: ChatSuggestedActionRow[]
}

// Chat Session types
export interface ChatSession {
  id: string
  title: string
  messages: ChatMessage[]
  createdAt: Date
  updatedAt: Date
  context?: PageContext
}

export interface ChatSessionSummary {
  id: string
  title: string
  lastMessage: string
  messageCount: number
  createdAt: Date
  updatedAt: Date
}

// Additional types for the chat system
export interface ChatContextValue {
  // Session management
  sessions: ChatSession[]
  currentSessionId: string | null
  currentSession: ChatSession | null
  
  // Legacy support - these map to current session
  messages: ChatMessage[]
  isOpen: boolean
  isMinimized: boolean
  isMaximized: boolean
  currentContext: PageContext | null
  
  // Session actions
  createSession: (title?: string) => string
  switchToSession: (sessionId: string) => void
  deleteSession: (sessionId: string) => void
  updateSessionTitle: (sessionId: string, title: string) => void
  getSessions: () => ChatSessionSummary[]
  
  // Actions (operate on current session)
  addMessage: (message: Omit<ChatMessage, 'id' | 'timestamp'>) => void
  updateMessage: (id: string, updates: Partial<ChatMessage>) => void
  deleteMessage: (id: string) => void
  clearMessages: () => void
  
  // UI State
  setOpen: (open: boolean) => void
  setMinimized: (minimized: boolean) => void
  setMaximized: (maximized: boolean) => void
  toggleChat: () => void
  showHistory: boolean
  setShowHistory: (show: boolean) => void
  
  // Context
  updatePageContext: (context: PageContext) => void
  
  // Utility
  getUnreadCount: () => number
}

export interface ChatProviderProps {
  children: React.ReactNode
}

export interface ChatBubbleProps {
  className?: string
  style?: React.CSSProperties
}

export interface ChatPanelProps {
  className?: string
  style?: React.CSSProperties
}

export interface ChatMessageProps {
  message: ChatMessage
  className?: string
  onActionClick?: (action: ChatAction) => void
}

export interface ChatInputProps {
  onSend: (message: string) => void
  disabled?: boolean
  placeholder?: string
  className?: string
}

export interface ChatHeaderProps {
  onClose?: () => void
  onMinimize?: () => void
  title?: string
  className?: string
}

export interface ChatMessagesListProps {
  messages: ChatMessage[]
  onActionClick?: (action: ChatAction) => void
  className?: string
}

export interface ChatFilterSuggestionsProps {
  actions: ChatAction[]
  onActionClick: (action: ChatAction) => void
  className?: string
}

// API types
export interface ChatAPIRequest {
  messages: ChatMessage[]
  context: PageContext
}

export interface ChatAPIResponse {
  message: string
  reasoning?: string // Reasoning associated with the final response this supports cerebras 
  actions?: ChatAction[]
  functionResult?: {
    success: boolean
    data?: unknown
    error?: string
  }
  toolCalls?: Array<{
    id: string
    name: string
    arguments: Record<string, unknown>
    result?: {
      success: boolean
      data?: unknown
      error?: string
    }
    reasoning?: string // Reasoning associated with this specific tool call this supports anthropic 
  }>
  citations?: Array<{
    url: string
    title: string
    cited_text: string
  }>
  error?: string
}

// Hook return types
export interface UseChatReturn extends ChatContextValue {
  // Additional computed values
  hasMessages: boolean
  lastMessage: ChatMessage | null
  isLoading: boolean
  error: string | null
  
  // Enhanced actions
  sendMessage: (content: string) => Promise<void>
  executeAction: (action: ChatAction) => void
  retryLastMessage: () => Promise<void>
}

export interface UsePageContextReturn {
  context: PageContext | null
  updateContext: (context: PageContext) => void
  isContextReady: boolean
}

export interface UseChatPersistenceReturn {
  isLoaded: boolean
  save: () => void
  clear: () => void
  exportData: () => string
  importData: (data: string) => boolean
} 