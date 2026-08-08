"use client";

import { Button, buttonVariants } from "@/components/ui/button";
import { Copy, Check } from "lucide-react";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { useCopyToClipboard } from "@/hooks/use-copy-to-clipboard";
import { cn } from "@/lib/utils";
import { type VariantProps } from "class-variance-authority";
import type { ComponentProps } from "react";
import { motion, AnimatePresence } from "motion/react";

type ButtonProps = ComponentProps<"button"> &
  VariantProps<typeof buttonVariants> & {
    asChild?: boolean;
  };

interface CopyButtonProps extends Omit<ButtonProps, "onClick"> {
  /** The text content to copy to clipboard */
  textToCopy: string;
  /** Custom success message for the toast */
  successMessage?: string;
  /** Custom error message for the toast */
  errorMessage?: string;
  /** Size of the copy/check icons */
  iconSize?: number;
  /** Tooltip text when not copied */
  tooltipText?: string;
  /** Tooltip text when copied */
  tooltipCopiedText?: string;
  /** Whether to show tooltip */
  showTooltip?: boolean;
  /** Custom callback when copy is successful */
  onCopySuccess?: () => void;
  /** Custom callback when copy fails */
  onCopyError?: (error: unknown) => void;
}

export function CopyButton({
  textToCopy,
  successMessage,
  errorMessage,
  iconSize = 16,
  tooltipText = "Copy",
  tooltipCopiedText = "Copied!",
  showTooltip = true,
  onCopySuccess,
  onCopyError,
  className,
  variant = "ghost",
  size = "icon",
  ...props
}: CopyButtonProps) {
  const { isCopied, copyToClipboard } = useCopyToClipboard({
    successMessage,
    errorMessage,
  });

  const handleCopy = async () => {
    try {
      await copyToClipboard(textToCopy, successMessage);
      onCopySuccess?.();
    } catch (error) {
      onCopyError?.(error);
    }
  };

  const ButtonComponent = (
    <motion.div
      whileHover={{ scale: 1.2 }}
      whileTap={{ scale: 0.8 }}
      style={{}}
    >
      <Button
        variant={variant}
        size={size}
        className={cn(
          "h-fit w-fit p-2 m-0 text-muted-foreground hover:text-primary",
          className
        )}
        onClick={handleCopy}
        disabled={!textToCopy}
        {...props}
      >
        {isCopied ? (
          <AnimatePresence mode="wait">
            <motion.div
              key="check-icon"
              exit={{ opacity: 0, scale: 0.5, rotate: 180 }}
              transition={{ duration: 0.3, ease: "easeIn" }}
            >
              <Check className="" size={iconSize} />
            </motion.div>
          </AnimatePresence>
        ) : (
          <AnimatePresence mode="wait">
            <motion.div
              key={`copy-icon-${isCopied}`}
              initial={{ opacity: 0, scale: 0.5, rotate: -180 }}
              animate={{ opacity: 1, scale: 1, rotate: 0 }}
              transition={{ duration: 0.4, ease: "easeOut" }}
            >
              <Copy className="" size={iconSize} />
            </motion.div>
          </AnimatePresence>
        )}
      </Button>
    </motion.div>
  );

  if (!showTooltip) {
    return ButtonComponent;
  }

  return (
    <TooltipProvider>
      <Tooltip>
        <TooltipTrigger asChild>{ButtonComponent}</TooltipTrigger>
        <TooltipContent
          side="bottom"
          align="center"
          sideOffset={4}
          className="text-secondary-foreground bg-secondary"
          arrowClassName="bg-secondary fill-secondary"
        >
          {isCopied ? tooltipCopiedText : tooltipText}
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}
