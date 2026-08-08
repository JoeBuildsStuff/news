import type { ToolCall } from './chat-store'

/**
 * Creates a new tool call with the given parameters
 */
export function createToolCall(name: string, arguments_: Record<string, unknown>): ToolCall {
  return {
    id: crypto.randomUUID(),
    name,
    arguments: arguments_,
  }
}

/**
 * Updates a tool call with its result
 */
export function updateToolCallResult(
  toolCall: ToolCall,
  success: boolean,
  data?: unknown,
  error?: string
): ToolCall {
  return {
    ...toolCall,
    result: {
      success,
      data,
      error,
    },
  }
}

/**
 * Formats tool call arguments for display
 */
export function formatToolCallArguments(args: Record<string, unknown>): string {
  try {
    return JSON.stringify(args, null, 2)
  } catch {
    return 'Invalid arguments'
  }
}

/**
 * Formats tool call result for display
 */
export function formatToolCallResult(result: ToolCall['result']): string {
  if (!result) return 'No result'
  
  if (result.success) {
    try {
      const data = result.data
      if (typeof data === 'string') {
        // Check if the data contains HTML markup
        if (data.includes('<pre><code>') && data.includes('</code></pre>')) {
          // Extract content from HTML markup
          const match = data.match(/<pre><code>([\s\S]*?)<\/code><\/pre>/)
          if (match) {
            return match[1]
          }
        }
        return data
      }
      return JSON.stringify(data, null, 2)
    } catch {
      return 'Invalid result data'
    }
  } else {
    return result.error || 'Unknown error'
  }
} 