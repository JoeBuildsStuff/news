'use client';

import { useState, useCallback } from 'react';
import { toast } from 'sonner';

interface UseCopyToClipboardOptions {
  successMessage?: string;
  errorMessage?: string;
  feedbackDuration?: number;
}

interface UseCopyToClipboardReturn {
  isCopied: boolean;
  copyToClipboard: (text: string, customMessage?: string) => Promise<void>;
}

export function useCopyToClipboard(options: UseCopyToClipboardOptions = {}): UseCopyToClipboardReturn {
  const {
    successMessage = 'Copied to clipboard',
    errorMessage = 'Failed to copy to clipboard',
    feedbackDuration = 2000,
  } = options;

  const [isCopied, setIsCopied] = useState(false);

  const copyToClipboard = useCallback(
    async (text: string, customMessage?: string) => {
      if (!text) {
        toast.error('Nothing to copy');
        return;
      }

      try {
        await navigator.clipboard.writeText(text);
        toast.success(customMessage || successMessage);
        setIsCopied(true);

        // Reset the copied state after the specified duration
        setTimeout(() => {
          setIsCopied(false);
        }, feedbackDuration);
      } catch (error) {
        console.error('Failed to copy to clipboard:', error);
        toast.error(errorMessage);
      }
    },
    [successMessage, errorMessage, feedbackDuration]
  );

  return {
    isCopied,
    copyToClipboard,
  };
}
