import { create } from "zustand";
import { persist, createJSONStorage } from "zustand/middleware";

export interface ToolCall {
  id: string;
  name: string;
  arguments: Record<string, unknown>;
  result?: {
    success: boolean;
    data?: unknown;
    error?: string;
  };
  reasoning?: string; // Reasoning associated with this specific tool call
}

export interface ChatMessage {
  id: string;
  role: "user" | "assistant" | "system";
  content: string;
  timestamp: Date;
  reasoning?: string; // Reasoning steps from Cerebras API
  attachments?: Array<{
    id: string;
    name: string;
    size: number;
    type: string;
    url?: string;
    data?: string; // base64 data for images
  }>;
  context?: {
    filters?: Record<string, unknown>;
    data?: Record<string, unknown>;
  };
  suggestedActions?: ChatAction[];
  functionResult?: {
    success: boolean;
    data?: unknown;
    error?: string;
  };
  toolCalls?: ToolCall[];
  citations?: Array<{
    url: string;
    title: string;
    cited_text: string;
  }>;
}

export interface ChatAction {
  type: "filter" | "sort" | "navigate" | "create" | "function_call";
  label: string;
  payload: Record<string, unknown>;
}

export interface PageContext {
  currentFilters: Record<string, unknown>;
  currentSort: Record<string, unknown>;
  visibleData: Record<string, unknown>[];
  totalCount: number;
}

export interface ChatSession {
  id: string;
  title: string;
  messages: ChatMessage[];
  createdAt: Date;
  updatedAt: Date;
  context?: PageContext;
}

export interface ChatSessionSummary {
  id: string;
  title: string;
  lastMessage: string;
  messageCount: number;
  createdAt: Date;
  updatedAt: Date;
}

interface ChatStore {
  // Session management
  sessions: ChatSession[];
  currentSessionId: string | null;

  // UI State
  isOpen: boolean;
  isMinimized: boolean;
  isMaximized: boolean;
  isLoading: boolean;
  showHistory: boolean;
  currentContext: PageContext | null;
  layoutMode: "floating" | "inset" | "fullpage";
  lastNonFullpageLayout: "floating" | "inset";
  openSessionIds: string[];

  // Computed properties (will be updated whenever state changes)
  currentSession: ChatSession | null;
  messages: ChatMessage[];
  // Per-message branch history: map user message id -> branches and active selection
  messageBranches: Record<
    string,
    { branches: ChatMessage[][]; signatures: string[]; activeIndex: number }
  >;
  currentBranchRootId: string | null;

  // Session CRUD operations
  createSession: (title?: string) => string;
  switchToSession: (sessionId: string) => void;
  deleteSession: (sessionId: string) => void;
  updateSessionTitle: (sessionId: string, title: string) => void;
  getSessions: () => ChatSessionSummary[];

  // Message CRUD operations (operate on current session)
  addMessage: (message: Omit<ChatMessage, "id" | "timestamp">) => void;
  updateMessage: (id: string, updates: Partial<ChatMessage>) => void;
  deleteMessage: (id: string) => void;
  clearMessages: () => void;

  // Server-backed helpers
  upsertSessionFromServer: (
    session: Omit<ChatSession, "messages"> & { messages?: ChatMessage[] }
  ) => void;
  setCurrentSessionIdFromServer: (sessionId: string) => void;
  setMessagesForSession: (sessionId: string, messages: ChatMessage[]) => void;

  // Message actions
  copyMessage: (messageId: string) => void;
  editMessage: (messageId: string, newContent: string) => void;
  retryMessage: (messageId: string, onRetry: (content: string) => void) => void;

  // Branch navigation
  getBranchStatus: (messageId: string) => { current: number; total: number };
  goToPreviousMessageList: (messageId: string) => void;
  goToNextMessageList: (messageId: string) => void;

  // Assistant-level variant navigation (within current prompt content)
  getAssistantVariantStatus: (messageId: string) => {
    current: number;
    total: number;
  };
  goToPreviousVariant: (messageId: string) => void;
  goToNextVariant: (messageId: string) => void;

  // Tool call operations
  addToolCalls: (messageId: string, toolCalls: ToolCall[]) => void;
  updateToolCallResult: (
    messageId: string,
    toolCallId: string,
    result: { success: boolean; data?: unknown; error?: string }
  ) => void;

  // UI State
  setOpen: (open: boolean) => void;
  setMinimized: (minimized: boolean) => void;
  setMaximized: (maximized: boolean) => void;
  setLoading: (loading: boolean) => void;
  toggleChat: () => void;
  setShowHistory: (show: boolean) => void;
  setLayoutMode: (mode: "floating" | "inset" | "fullpage") => void;
  openSessionTab: (sessionId: string) => void;
  closeSessionTab: (sessionId: string) => void;

  // Context management
  updatePageContext: (context: PageContext) => void;

  // Quota management
  getStorageUsage: () => {
    totalSize: number;
    sessionsCount: number;
    messagesCount: number;
    attachmentsCount: number;
    attachmentsSize: number;
    usagePercentage: number;
  };
  clearOldSessions: (keepCount?: number) => void;
  isStorageQuotaExceeded: () => boolean;

  // Utility
  getUnreadCount: () => number;
}

// Helper function to compute current session and messages
const computeCurrentSessionAndMessages = (
  sessions: ChatSession[],
  currentSessionId: string | null
) => {
  const currentSession =
    sessions.find((s) => s.id === currentSessionId) || null;
  const messages = currentSession?.messages || [];
  return { currentSession, messages };
};

// Helper function to generate session title
const generateSessionTitle = (messages: ChatMessage[]): string => {
  if (messages.length === 0) return "New Chat";

  const firstUserMessage = messages.find((m) => m.role === "user");
  if (firstUserMessage) {
    // Truncate to 30 characters
    const title = firstUserMessage.content.slice(0, 30);
    return title.length < firstUserMessage.content.length
      ? `${title}...`
      : title;
  }

  return "New Chat";
};

export const useChatStore = create<ChatStore>()(
  persist(
    (set, get) => ({
      // Initial state
      sessions: [],
      currentSessionId: null,
      isOpen: false,
      isMinimized: false,
      isMaximized: false,
      isLoading: false,
      showHistory: false,
      currentContext: null,
      currentSession: null,
      messages: [],
      layoutMode: "floating",
      lastNonFullpageLayout: "floating",
      openSessionIds: [],
      messageBranches: {},
      currentBranchRootId: null,

      // Session CRUD operations
      createSession: (title?: string) => {
        const sessionId = crypto.randomUUID();
        const now = new Date();

        const newSession: ChatSession = {
          id: sessionId,
          title: title || "New Chat",
          messages: [],
          createdAt: now,
          updatedAt: now,
        };

        set((state) => {
          const newSessions = [newSession, ...state.sessions];
          const { currentSession, messages } = computeCurrentSessionAndMessages(
            newSessions,
            sessionId
          );

          return {
            sessions: newSessions,
            currentSessionId: sessionId,
            currentSession,
            messages,
            showHistory: false,
          };
        });

        return sessionId;
      },

      switchToSession: (sessionId) => {
        set((state) => {
          const { currentSession, messages } = computeCurrentSessionAndMessages(
            state.sessions,
            sessionId
          );

          return {
            currentSessionId: sessionId,
            currentSession,
            messages,
            showHistory: false,
          };
        });
      },

      deleteSession: (sessionId) => {
        set((state) => {
          const newSessions = state.sessions.filter((s) => s.id !== sessionId);
          const newCurrentId =
            state.currentSessionId === sessionId
              ? newSessions[0]?.id || null
              : state.currentSessionId;

          const { currentSession, messages } = computeCurrentSessionAndMessages(
            newSessions,
            newCurrentId
          );

          return {
            sessions: newSessions,
            currentSessionId: newCurrentId,
            currentSession,
            messages,
            openSessionIds: state.openSessionIds.filter((id) => id !== sessionId),
          };
        });
      },

      updateSessionTitle: (sessionId, title) => {
        set((state) => {
          const updatedSessions = state.sessions.map((s) =>
            s.id === sessionId ? { ...s, title, updatedAt: new Date() } : s
          );

          const { currentSession, messages } = computeCurrentSessionAndMessages(
            updatedSessions,
            state.currentSessionId
          );

          const oldSession = state.sessions.find((s) => s.id === sessionId);
          const titleGenerated =
            oldSession?.title === "New Chat" && title !== "New Chat";
          const openSessionIds =
            titleGenerated && !state.openSessionIds.includes(sessionId)
              ? [...state.openSessionIds, sessionId]
              : state.openSessionIds;

          return {
            sessions: updatedSessions,
            currentSession,
            messages,
            openSessionIds,
          };
        });
      },

      getSessions: () => {
        const { sessions } = get();
        return sessions.map((session) => ({
          id: session.id,
          title: session.title,
          lastMessage:
            session.messages[session.messages.length - 1]?.content || "",
          messageCount: session.messages.length,
          createdAt: session.createdAt,
          updatedAt: session.updatedAt,
        }));
      },

      // Message CRUD operations
      addMessage: (messageData) => {
        const message: ChatMessage = {
          ...messageData,
          id: crypto.randomUUID(),
          timestamp: new Date(),
        };

        set((state) => {
          // Create a session if none exists
          let currentSessionId = state.currentSessionId;
          let sessions = state.sessions;

          if (
            !currentSessionId ||
            !sessions.find((s) => s.id === currentSessionId)
          ) {
            const sessionId = crypto.randomUUID();
            const now = new Date();

            const newSession: ChatSession = {
              id: sessionId,
              title: "New Chat",
              messages: [],
              createdAt: now,
              updatedAt: now,
            };

            sessions = [newSession, ...sessions];
            currentSessionId = sessionId;
          }

          // Check if adding this message would exceed quota
          const currentUsage = get().getStorageUsage();
          const messageSize = new Blob([JSON.stringify(message)]).size;
          const estimatedNewSize = currentUsage.totalSize + messageSize;
          const maxSize = 10 * 1024 * 1024; // 10MB

          if (estimatedNewSize > maxSize) {
            // Try to clear old sessions to make room
            const sortedSessions = sessions.sort((a, b) => {
              if (a.id === currentSessionId) return -1;
              if (b.id === currentSessionId) return 1;
              return (
                new Date(b.updatedAt).getTime() -
                new Date(a.updatedAt).getTime()
              );
            });

            // Keep only the 2 most recent sessions
            const sessionsToKeep = sortedSessions.slice(0, 2);
            const sessionsToDelete = sortedSessions.slice(2);

            // Delete old sessions
            sessionsToDelete.forEach((session) => {
              get().deleteSession(session.id);
            });

            // Update sessions to only include kept ones
            sessions = sessionsToKeep;
          }

          // Update the current session with the new message
          const updatedSessions = sessions.map((session) => {
            if (session.id === currentSessionId) {
              const updatedMessages = [...session.messages, message];
              return {
                ...session,
                messages: updatedMessages,
                title:
                  session.title === "New Chat"
                    ? generateSessionTitle(updatedMessages)
                    : session.title,
                updatedAt: new Date(),
              };
            }
            return session;
          });

          const { currentSession, messages } = computeCurrentSessionAndMessages(
            updatedSessions,
            currentSessionId
          );

          // If branching is active, update the active branch tail with new messages after the root
          let messageBranches = state.messageBranches;
          const rootId = state.currentBranchRootId;
          if (rootId && currentSession) {
            const rootIndex = currentSession.messages.findIndex(
              (m) => m.id === rootId
            );
            if (rootIndex !== -1) {
              const tail = currentSession.messages.slice(rootIndex + 1);
              const entry = messageBranches[rootId];
              if (entry) {
                const branches = entry.branches.slice();
                branches[entry.activeIndex] = tail;
                messageBranches = {
                  ...messageBranches,
                  [rootId]: {
                    branches,
                    signatures: entry.signatures,
                    activeIndex: entry.activeIndex,
                  },
                };
              }
            }
          }

          return {
            sessions: updatedSessions,
            currentSessionId,
            currentSession,
            messages,
            messageBranches,
          };
        });
      },

      updateMessage: (id, updates) => {
        set((state) => {
          const updatedSessions = state.sessions.map((session) =>
            session.id === state.currentSessionId
              ? {
                  ...session,
                  messages: session.messages.map((msg) =>
                    msg.id === id ? { ...msg, ...updates } : msg
                  ),
                  updatedAt: new Date(),
                }
              : session
          );

          const { currentSession, messages } = computeCurrentSessionAndMessages(
            updatedSessions,
            state.currentSessionId
          );

          return {
            sessions: updatedSessions,
            currentSession,
            messages,
          };
        });
      },

      deleteMessage: (id) => {
        set((state) => {
          const updatedSessions = state.sessions.map((session) =>
            session.id === state.currentSessionId
              ? {
                  ...session,
                  messages: session.messages.filter((msg) => msg.id !== id),
                  updatedAt: new Date(),
                }
              : session
          );

          const { currentSession, messages } = computeCurrentSessionAndMessages(
            updatedSessions,
            state.currentSessionId
          );

          return {
            sessions: updatedSessions,
            currentSession,
            messages,
          };
        });
      },

      clearMessages: () => {
        set((state) => {
          const updatedSessions = state.sessions.map((session) =>
            session.id === state.currentSessionId
              ? {
                  ...session,
                  messages: [],
                  updatedAt: new Date(),
                }
              : session
          );

          const { currentSession, messages } = computeCurrentSessionAndMessages(
            updatedSessions,
            state.currentSessionId
          );

          return {
            sessions: updatedSessions,
            currentSession,
            messages,
          };
        });
      },

      // Server-backed helpers
      upsertSessionFromServer: (session) => {
        set((state) => {
          const exists = state.sessions.find((s) => s.id === session.id);
          const toInsert: ChatSession = {
            id: session.id,
            title: session.title,
            messages: session.messages || [],
            createdAt: session.createdAt,
            updatedAt: session.updatedAt,
            context: session.context,
          };

          const sessions = exists
            ? state.sessions.map((s) =>
                s.id === session.id ? { ...s, ...toInsert } : s
              )
            : [toInsert, ...state.sessions];

          const { currentSession, messages } = computeCurrentSessionAndMessages(
            sessions,
            state.currentSessionId ?? session.id
          );

          const oldSession = state.sessions.find((s) => s.id === session.id);
          const titleGenerated =
            oldSession?.title === "New Chat" && session.title !== "New Chat";
          const openSessionIds =
            titleGenerated && !state.openSessionIds.includes(session.id)
              ? [...state.openSessionIds, session.id]
              : state.openSessionIds;

          return {
            sessions,
            currentSession,
            messages,
            openSessionIds,
          };
        });
      },

      setCurrentSessionIdFromServer: (sessionId) => {
        set((state) => {
          const { currentSession, messages } = computeCurrentSessionAndMessages(
            state.sessions,
            sessionId
          );
          return {
            currentSessionId: sessionId,
            currentSession,
            messages,
            showHistory: false,
          };
        });
      },

      setMessagesForSession: (sessionId, newMessages) => {
        set((state) => {
          const updatedSessions = state.sessions.map((s) =>
            s.id === sessionId
              ? { ...s, messages: newMessages, updatedAt: new Date() }
              : s
          );
          const { currentSession, messages } = computeCurrentSessionAndMessages(
            updatedSessions,
            state.currentSessionId
          );
          return { sessions: updatedSessions, currentSession, messages };
        });
      },

      copyMessage: (messageId: string) => {
        const state = get();
        const message = state.messages.find((msg) => msg.id === messageId);
        if (message) {
          navigator.clipboard.writeText(message.content).catch(console.error);
        }
      },

      editMessage: (messageId: string, newContent: string) => {
        set((state) => {
          const updatedSessions = state.sessions.map((session) =>
            session.id === state.currentSessionId
              ? {
                  ...session,
                  messages: session.messages.map((msg) =>
                    msg.id === messageId ? { ...msg, content: newContent } : msg
                  ),
                  updatedAt: new Date(),
                }
              : session
          );

          const { currentSession, messages } = computeCurrentSessionAndMessages(
            updatedSessions,
            state.currentSessionId
          );

          return {
            sessions: updatedSessions,
            currentSession,
            messages,
          };
        });
      },

      retryMessage: (messageId: string, onRetry: (content: string) => void) => {
        const state = get();
        const message = state.messages.find((msg) => msg.id === messageId);
        if (!message || message.role !== "user") return;

        const currentSession = state.currentSession;
        if (!currentSession) return;

        const messageIndex = currentSession.messages.findIndex(
          (m) => m.id === messageId
        );
        if (messageIndex === -1) return;

        const existingTail = currentSession.messages.slice(messageIndex + 1);

        set((state) => {
          const updatedSessions = state.sessions.map((session) =>
            session.id === state.currentSessionId
              ? {
                  ...session,
                  messages: session.messages.slice(0, messageIndex + 1), // keep the edited user message
                  updatedAt: new Date(),
                }
              : session
          );

          const existing = state.messageBranches[messageId];
          const signature = (
            state.messages.find((m) => m.id === messageId)?.content || ""
          ).trim();
          let branches: ChatMessage[][];
          let signatures: string[];
          let activeIndex: number;
          if (!existing) {
            branches = [existingTail, []];
            signatures = [signature, signature];
            activeIndex = 1;
          } else {
            branches = existing.branches.map((b) => b.slice());
            branches.push([]);
            signatures = existing.signatures.slice();
            signatures.push(signature);
            activeIndex = branches.length - 1;
          }

          const newBranches = {
            ...state.messageBranches,
            [messageId]: { branches, signatures, activeIndex },
          };

          const { currentSession, messages } = computeCurrentSessionAndMessages(
            updatedSessions,
            state.currentSessionId
          );

          return {
            sessions: updatedSessions,
            currentSession,
            messages,
            messageBranches: newBranches,
            currentBranchRootId: messageId,
          };
        });

        if (onRetry) {
          onRetry(message.content);
        } else {
          setTimeout(() => {
            const { addMessage } = useChatStore.getState();
            addMessage({
              role: "user",
              content: message.content,
              context: message.context,
            });
          }, 100);
        }
      },

      getBranchStatus: (messageId: string) => {
        // User-level status: count distinct signatures and current position among them
        const entry = get().messageBranches[messageId];
        if (!entry) return { current: 0, total: 0 };
        const order: string[] = [];
        entry.signatures.forEach((sig) => {
          if (!order.includes(sig)) order.push(sig);
        });
        if (order.length === 0) return { current: 0, total: 0 };
        const currentSig = entry.signatures[entry.activeIndex];
        const pos = Math.max(0, order.indexOf(currentSig));
        return { current: pos + 1, total: order.length };
      },

      getAssistantVariantStatus: (messageId: string) => {
        // messageId here refers to the USER message id (root)
        const entry = get().messageBranches[messageId];
        if (!entry) return { current: 0, total: 0 };
        const activeSig = entry.signatures[entry.activeIndex];
        const filtered = entry.signatures
          .map((sig, idx) => ({ sig, idx }))
          .filter((x) => x.sig === activeSig)
          .map((x) => x.idx);
        const position = filtered.indexOf(entry.activeIndex);
        return { current: position + 1, total: filtered.length };
      },

      goToPreviousMessageList: (messageId: string) => {
        const { currentSession, messageBranches, currentSessionId } = get();
        const entry = messageBranches[messageId];
        if (!currentSession || !entry) return;
        if (entry.branches.length === 0) return;

        const rootIndex = currentSession.messages.findIndex(
          (m) => m.id === messageId
        );
        if (rootIndex === -1) return;

        // Move to previous distinct signature group
        const sigOrder: string[] = [];
        entry.signatures.forEach((sig) => {
          if (!sigOrder.includes(sig)) sigOrder.push(sig);
        });
        if (sigOrder.length <= 1) return;
        const currentSig = entry.signatures[entry.activeIndex];
        const sigPos = sigOrder.indexOf(currentSig);
        const newSig = sigOrder[Math.max(0, sigPos - 1)];
        const candidateIndices = entry.signatures
          .map((sig, idx) => ({ sig, idx }))
          .filter((x) => x.sig === newSig)
          .map((x) => x.idx);
        const newIndex = candidateIndices.length
          ? Math.max(...candidateIndices)
          : entry.activeIndex;
        const newTail = entry.branches[newIndex] || [];

        set((state) => {
          const updatedSessions = state.sessions.map((session) =>
            session.id === currentSessionId
              ? {
                  ...session,
                  messages: session.messages
                    .slice(0, rootIndex + 1)
                    .concat(newTail),
                  updatedAt: new Date(),
                }
              : session
          );

          const { currentSession, messages } = computeCurrentSessionAndMessages(
            updatedSessions,
            currentSessionId
          );

          return {
            sessions: updatedSessions,
            currentSession,
            messages,
            messageBranches: {
              ...state.messageBranches,
              [messageId]: {
                branches: entry.branches,
                signatures: entry.signatures,
                activeIndex: newIndex,
              },
            },
            currentBranchRootId: messageId,
          };
        });
      },

      goToNextMessageList: (messageId: string) => {
        const { currentSession, messageBranches, currentSessionId } = get();
        const entry = messageBranches[messageId];
        if (!currentSession || !entry) return;
        if (entry.branches.length === 0) return;

        const rootIndex = currentSession.messages.findIndex(
          (m) => m.id === messageId
        );
        if (rootIndex === -1) return;

        // Move to next distinct signature group
        const sigOrder: string[] = [];
        entry.signatures.forEach((sig) => {
          if (!sigOrder.includes(sig)) sigOrder.push(sig);
        });
        if (sigOrder.length <= 1) return;
        const currentSig = entry.signatures[entry.activeIndex];
        const sigPos = sigOrder.indexOf(currentSig);
        const newSig = sigOrder[Math.min(sigOrder.length - 1, sigPos + 1)];
        const candidateIndices = entry.signatures
          .map((sig, idx) => ({ sig, idx }))
          .filter((x) => x.sig === newSig)
          .map((x) => x.idx);
        const newIndex = candidateIndices.length
          ? Math.max(...candidateIndices)
          : entry.activeIndex;
        const newTail = entry.branches[newIndex] || [];

        set((state) => {
          const updatedSessions = state.sessions.map((session) =>
            session.id === currentSessionId
              ? {
                  ...session,
                  messages: session.messages
                    .slice(0, rootIndex + 1)
                    .concat(newTail),
                  updatedAt: new Date(),
                }
              : session
          );

          const { currentSession, messages } = computeCurrentSessionAndMessages(
            updatedSessions,
            currentSessionId
          );

          return {
            sessions: updatedSessions,
            currentSession,
            messages,
            messageBranches: {
              ...state.messageBranches,
              [messageId]: {
                branches: entry.branches,
                signatures: entry.signatures,
                activeIndex: newIndex,
              },
            },
            currentBranchRootId: messageId,
          };
        });
      },

      goToPreviousVariant: (messageId: string) => {
        const { currentSession, messageBranches, currentSessionId } = get();
        const entry = messageBranches[messageId];
        if (!currentSession || !entry) return;
        if (entry.branches.length === 0) return;

        const rootIndex = currentSession.messages.findIndex(
          (m) => m.id === messageId
        );
        if (rootIndex === -1) return;

        const activeSig = entry.signatures[entry.activeIndex];
        const filtered = entry.signatures
          .map((sig, idx) => ({ sig, idx }))
          .filter((x) => x.sig === activeSig)
          .map((x) => x.idx);
        const pos = filtered.indexOf(entry.activeIndex);
        if (pos <= 0) return;
        const newIndex = filtered[pos - 1];
        const newTail = entry.branches[newIndex] || [];

        set((state) => {
          const updatedSessions = state.sessions.map((session) =>
            session.id === currentSessionId
              ? {
                  ...session,
                  messages: session.messages
                    .slice(0, rootIndex + 1)
                    .concat(newTail),
                  updatedAt: new Date(),
                }
              : session
          );
          const { currentSession, messages } = computeCurrentSessionAndMessages(
            updatedSessions,
            currentSessionId
          );
          return {
            sessions: updatedSessions,
            currentSession,
            messages,
            messageBranches: {
              ...state.messageBranches,
              [messageId]: {
                branches: entry.branches,
                signatures: entry.signatures,
                activeIndex: newIndex,
              },
            },
            currentBranchRootId: messageId,
          };
        });
      },

      goToNextVariant: (messageId: string) => {
        const { currentSession, messageBranches, currentSessionId } = get();
        const entry = messageBranches[messageId];
        if (!currentSession || !entry) return;
        if (entry.branches.length === 0) return;

        const rootIndex = currentSession.messages.findIndex(
          (m) => m.id === messageId
        );
        if (rootIndex === -1) return;

        const activeSig = entry.signatures[entry.activeIndex];
        const filtered = entry.signatures
          .map((sig, idx) => ({ sig, idx }))
          .filter((x) => x.sig === activeSig)
          .map((x) => x.idx);
        const pos = filtered.indexOf(entry.activeIndex);
        if (pos === -1 || pos >= filtered.length - 1) return;
        const newIndex = filtered[pos + 1];
        const newTail = entry.branches[newIndex] || [];

        set((state) => {
          const updatedSessions = state.sessions.map((session) =>
            session.id === currentSessionId
              ? {
                  ...session,
                  messages: session.messages
                    .slice(0, rootIndex + 1)
                    .concat(newTail),
                  updatedAt: new Date(),
                }
              : session
          );
          const { currentSession, messages } = computeCurrentSessionAndMessages(
            updatedSessions,
            currentSessionId
          );
          return {
            sessions: updatedSessions,
            currentSession,
            messages,
            messageBranches: {
              ...state.messageBranches,
              [messageId]: {
                branches: entry.branches,
                signatures: entry.signatures,
                activeIndex: newIndex,
              },
            },
            currentBranchRootId: messageId,
          };
        });
      },

      addToolCalls: (messageId: string, toolCalls: ToolCall[]) => {
        set((state) => {
          const updatedSessions = state.sessions.map((session) =>
            session.id === state.currentSessionId
              ? {
                  ...session,
                  messages: session.messages.map((msg) =>
                    msg.id === messageId
                      ? {
                          ...msg,
                          toolCalls: [...(msg.toolCalls || []), ...toolCalls],
                          updatedAt: new Date(),
                        }
                      : msg
                  ),
                }
              : session
          );

          const { currentSession, messages } = computeCurrentSessionAndMessages(
            updatedSessions,
            state.currentSessionId
          );

          return {
            sessions: updatedSessions,
            currentSession,
            messages,
          };
        });
      },

      updateToolCallResult: (
        messageId: string,
        toolCallId: string,
        result: { success: boolean; data?: unknown; error?: string }
      ) => {
        set((state) => {
          const updatedSessions = state.sessions.map((session) =>
            session.id === state.currentSessionId
              ? {
                  ...session,
                  messages: session.messages.map((msg) =>
                    msg.id === messageId
                      ? {
                          ...msg,
                          toolCalls: msg.toolCalls?.map((tc) =>
                            tc.id === toolCallId ? { ...tc, result } : tc
                          ),
                          updatedAt: new Date(),
                        }
                      : msg
                  ),
                }
              : session
          );

          const { currentSession, messages } = computeCurrentSessionAndMessages(
            updatedSessions,
            state.currentSessionId
          );

          return {
            sessions: updatedSessions,
            currentSession,
            messages,
          };
        });
      },

      // UI State
      setOpen: (open) => {
        set({
          isOpen: open,
          isMinimized: open ? false : get().isMinimized,
          isMaximized: open ? get().isMaximized : false,
        });
      },

      setMinimized: (minimized) => {
        set({
          isMinimized: minimized,
          isOpen: minimized ? false : get().isOpen,
          isMaximized: minimized ? false : get().isMaximized,
        });
      },

      setMaximized: (maximized) => {
        set({
          isMaximized: maximized,
          isOpen: maximized ? true : get().isOpen,
          isMinimized: maximized ? false : get().isMinimized,
        });
      },

      setLoading: (loading) => {
        set({ isLoading: loading });
      },

      toggleChat: () => {
        const { isOpen, isMaximized } = get();
        if (!isOpen) {
          // Open in normal mode
          set({ isOpen: true, isMinimized: false, isMaximized: false });
        } else if (!isMaximized) {
          // Maximize
          set({ isMaximized: true, isMinimized: false });
        } else {
          // Close
          set({ isOpen: false, isMinimized: false, isMaximized: false });
        }
      },

      setShowHistory: (show) => {
        set({ showHistory: show });
      },

      setLayoutMode: (mode) => {
        set({
          layoutMode: mode,
          lastNonFullpageLayout:
            mode === "fullpage" ? get().lastNonFullpageLayout : mode,
          isMaximized: mode === "inset",
          isMinimized: false,
          isOpen: mode !== "fullpage",
        });
      },

      openSessionTab: (sessionId) => {
        set((state) => {
          if (state.openSessionIds.includes(sessionId)) return state;
          return { openSessionIds: [...state.openSessionIds, sessionId] };
        });
      },

      closeSessionTab: (sessionId) => {
        set((state) => ({
          openSessionIds: state.openSessionIds.filter((id) => id !== sessionId),
        }));
      },

      // Context management
      updatePageContext: (context) => {
        set({ currentContext: context });
      },

      // Quota management
      getStorageUsage: () => {
        const { sessions } = get();

        const totalMessages = sessions.reduce(
          (count, session) => count + session.messages.length,
          0
        );
        const totalAttachments = sessions.reduce(
          (count, session) =>
            count +
            session.messages.reduce(
              (msgCount, msg) => msgCount + (msg.attachments?.length || 0),
              0
            ),
          0
        );
        const totalAttachmentsSize = sessions.reduce(
          (size, session) =>
            size +
            session.messages.reduce(
              (msgSize, msg) =>
                msgSize +
                (msg.attachments?.reduce(
                  (attSize, att) =>
                    attSize + (att.data ? new Blob([att.data]).size : 0),
                  0
                ) || 0),
              0
            ),
          0
        );

        // Calculate total storage size
        const totalSize = new Blob([
          JSON.stringify({
            sessions: sessions,
            currentSessionId: get().currentSessionId,
            layoutMode: get().layoutMode,
          }),
        ]).size;

        const maxStorageSize = 10 * 1024 * 1024; // 10MB
        const usagePercentage = (totalSize / maxStorageSize) * 100;

        return {
          totalSize,
          sessionsCount: sessions.length,
          messagesCount: totalMessages,
          attachmentsCount: totalAttachments,
          attachmentsSize: totalAttachmentsSize,
          usagePercentage,
        };
      },

      clearOldSessions: (keepCount = 3) => {
        const { sessions, currentSessionId } = get();

        // Sort sessions by updatedAt, keeping current session first
        const sortedSessions = sessions.sort((a, b) => {
          if (a.id === currentSessionId) return -1;
          if (b.id === currentSessionId) return 1;
          return (
            new Date(b.updatedAt).getTime() - new Date(a.updatedAt).getTime()
          );
        });

        // Get sessions to delete (keep the specified number of sessions)
        const sessionsToDelete = sortedSessions.slice(keepCount);

        // Delete old sessions
        sessionsToDelete.forEach((session) => {
          get().deleteSession(session.id);
        });
      },

      isStorageQuotaExceeded: () => {
        const usage = get().getStorageUsage();
        return usage.usagePercentage >= 95; // 95% threshold
      },

      // Utility
      getUnreadCount: () => {
        // For now, return 0. This can be enhanced with read/unread tracking
        return 0;
      },
    }),
    {
      name: "chat-storage",
      storage: createJSONStorage(() => ({
        getItem: (name: string) => {
          return localStorage.getItem(name);
        },
        setItem: (name: string, value: string) => {
          const size = new Blob([value]).size;
          const maxSize = 10 * 1024 * 1024; // 10MB

          if (size > maxSize) {
            console.warn("Storage quota exceeded, clearing old data");
            // Try to clear old sessions to make room
            const currentData = JSON.parse(
              localStorage.getItem("chat-storage") || "{}"
            );
            if (currentData.sessions?.length > 2) {
              // Keep only the 2 most recent sessions
              const sortedSessions = currentData.sessions.sort(
                (a: { updatedAt: string }, b: { updatedAt: string }) =>
                  new Date(b.updatedAt).getTime() -
                  new Date(a.updatedAt).getTime()
              );
              currentData.sessions = sortedSessions.slice(0, 2);

              // Try to save with reduced data
              const reducedSize = new Blob([JSON.stringify(currentData)]).size;
              if (reducedSize <= maxSize) {
                localStorage.setItem(
                  "chat-storage",
                  JSON.stringify(currentData)
                );
                return;
              }
            }

            // If still too large, log error but don't throw to prevent app crash
            console.error(
              "Storage quota exceeded. Please clear some chat history."
            );
            // Try to save with minimal data
            const minimalData = {
              sessions: currentData.sessions.slice(0, 1),
              currentSessionId: currentData.currentSessionId,
              layoutMode: currentData.layoutMode,
              lastNonFullpageLayout: currentData.lastNonFullpageLayout,
            };
            const minimalSize = new Blob([JSON.stringify(minimalData)]).size;
            if (minimalSize <= maxSize) {
              localStorage.setItem("chat-storage", JSON.stringify(minimalData));
            }
          }

          localStorage.setItem(name, value);
        },
        removeItem: (name: string) => {
          localStorage.removeItem(name);
        },
      })),
      // Persist sessions with serialized dates
      partialize: (state) => ({
        sessions: state.sessions.slice(0, 10).map((session) => ({
          ...session,
          messages: session.messages.slice(-50).map((msg) => ({
            ...msg,
            timestamp: msg.timestamp.toISOString(),
          })),
          createdAt: session.createdAt.toISOString(),
          updatedAt: session.updatedAt.toISOString(),
        })), // Keep last 10 sessions
        currentSessionId: state.currentSessionId,
        layoutMode: state.layoutMode,
        lastNonFullpageLayout: state.lastNonFullpageLayout,
        openSessionIds: state.openSessionIds,
        messageBranches: state.messageBranches,
        currentBranchRootId: state.currentBranchRootId,
      }),
      // Transform dates back when loading from storage
      onRehydrateStorage: () => (state) => {
        if (state?.sessions) {
          state.sessions = state.sessions.map((session) => ({
            ...session,
            messages: session.messages.map((msg) => ({
              ...msg,
              timestamp: new Date(msg.timestamp as unknown as string),
            })),
            createdAt: new Date(session.createdAt as unknown as string),
            updatedAt: new Date(session.updatedAt as unknown as string),
          }));

          // Recompute current session and messages after rehydration
          if (state.currentSessionId) {
            const { currentSession, messages } =
              computeCurrentSessionAndMessages(
                state.sessions,
                state.currentSessionId
              );
            state.currentSession = currentSession;
            state.messages = messages;
          }

          // Ensure branch maps exist
          if (!("messageBranches" in state) || !state.messageBranches) {
            (state as unknown as ChatStore).messageBranches = {};
          }
          if (!("currentBranchRootId" in state)) {
            (state as unknown as ChatStore).currentBranchRootId = null;
          }
          if (!("lastNonFullpageLayout" in state)) {
            (state as unknown as ChatStore).lastNonFullpageLayout = "floating";
          }
          if (!("openSessionIds" in state) || !state.openSessionIds) {
            (state as unknown as ChatStore).openSessionIds = [];
          }

          // Ensure signatures exist for each entry if an older state is loaded
          const store = state as unknown as ChatStore;
          if (store.messageBranches) {
            Object.keys(store.messageBranches).forEach((key) => {
              const entry = store.messageBranches[key] as unknown as {
                branches: ChatMessage[][];
                signatures?: string[];
                activeIndex: number;
              };
              if (
                !entry.signatures ||
                entry.signatures.length !== entry.branches.length
              ) {
                entry.signatures = entry.branches.map(() => "");
              }
              // write back
              (
                store.messageBranches as Record<
                  string,
                  {
                    branches: ChatMessage[][];
                    signatures: string[];
                    activeIndex: number;
                  }
                >
              )[key] = {
                branches: entry.branches,
                signatures: entry.signatures,
                activeIndex: entry.activeIndex,
              };
            });
          }
        }
      },
    }
  )
);
