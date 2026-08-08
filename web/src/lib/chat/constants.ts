// Chat configuration constants
export const CHAT_CONFIG = {
  // Maximum number of messages to keep in storage
  MAX_STORED_MESSAGES: 50,

  // Maximum number of messages to display in UI
  MAX_DISPLAY_MESSAGES: 100,

  // Auto-scroll threshold (messages from bottom)
  AUTO_SCROLL_THRESHOLD: 5,

  // Typing indicator timeout (ms)
  TYPING_TIMEOUT: 3000,

  // Message retry attempts
  MAX_RETRY_ATTEMPTS: 3,

  // API timeout (ms)
  API_TIMEOUT: 30000,
} as const;

// Chat UI dimensions and styling
export const CHAT_UI = {
  // Panel dimensions
  PANEL_WIDTH: 384, // w-96 = 24rem = 384px
  PANEL_HEIGHT: 600,
  PANEL_MIN_HEIGHT: 300,

  // Bubble dimensions
  BUBBLE_SIZE: 60,
  BUBBLE_OFFSET: 20,

  // Animation durations (ms)
  SLIDE_DURATION: 300,
  FADE_DURATION: 200,

  // Z-index layers
  BUBBLE_Z_INDEX: 1000,
  PANEL_Z_INDEX: 1001,
  OVERLAY_Z_INDEX: 999,

  // Chat states
  STATES: {
    CLOSED: "closed",
    MINIMIZED: "minimized",
    NORMAL: "normal",
    MAXIMIZED: "maximized",
  },
} as const;

// Message role types
export const MESSAGE_ROLES = {
  USER: "user",
  ASSISTANT: "assistant",
  SYSTEM: "system",
} as const;

// Storage keys
export const STORAGE_KEYS = {
  CHAT_MESSAGES: "chat-storage",
  CHAT_PREFERENCES: "chat-preferences",
} as const;
