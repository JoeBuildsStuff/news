"use client";

import * as React from "react";
import { ChevronDown, CopyIcon } from "lucide-react";
import { toast } from "sonner";

import { cn } from "@/lib/utils";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import { Button } from "@/components/ui/button";

function ToolCall({
  className,
  ...props
}: React.ComponentProps<typeof Collapsible>) {
  return (
    <Collapsible
      data-slot="tool-call"
      className={cn("text-sm font-light wrap-break-word", className)}
      {...props}
    />
  );
}

function ToolCallTrigger({
  className,
  children,
  ...props
}: React.ComponentProps<"button">) {
  return (
    <CollapsibleTrigger asChild>
      <button
        data-slot="tool-call-trigger"
        className={cn(
          "group/tool-call-trigger flex w-full cursor-pointer items-center justify-between text-muted-foreground transition-colors hover:text-foreground",
          className
        )}
        {...props}
      >
        {children}
        <ChevronDown
          className="size-4 shrink-0 transition-transform group-data-[state=open]/tool-call-trigger:rotate-180"
          strokeWidth={1.5}
        />
      </button>
    </CollapsibleTrigger>
  );
}

function ToolCallContent({
  className,
  ...props
}: React.ComponentProps<typeof CollapsibleContent>) {
  return (
    <CollapsibleContent
      data-slot="tool-call-content"
      className={cn("mt-2 space-y-2", className)}
      {...props}
    />
  );
}

function ToolCallPanel({
  className,
  defaultOpen = true,
  ...props
}: React.ComponentProps<typeof Collapsible>) {
  return (
    <Collapsible
      data-slot="tool-call-panel"
      defaultOpen={defaultOpen}
      className={cn("rounded-md border border-border bg-background/30", className)}
      {...props}
    />
  );
}

function ToolCallPanelTrigger({
  className,
  children,
  ...props
}: React.ComponentProps<"button">) {
  return (
    <CollapsibleTrigger asChild>
      <button
        data-slot="tool-call-panel-trigger"
        className={cn(
          "group/tool-call-panel-trigger flex w-full cursor-pointer items-center justify-between p-2 text-muted-foreground transition-colors hover:text-foreground",
          className
        )}
        {...props}
      >
        <span className="text-xs font-medium">{children}</span>
        <ChevronDown
          className="size-3.5 shrink-0 transition-transform group-data-[state=open]/tool-call-panel-trigger:rotate-180"
          strokeWidth={1.5}
        />
      </button>
    </CollapsibleTrigger>
  );
}

function ToolCallPanelContent({
  className,
  ...props
}: React.ComponentProps<typeof CollapsibleContent>) {
  return (
    <CollapsibleContent
      data-slot="tool-call-panel-content"
      className={cn(className)}
      {...props}
    />
  );
}

function ToolCallCode({
  value,
  copyLabel = "Copied to clipboard",
  className,
  ...props
}: React.ComponentProps<"div"> & {
  value: string;
  copyLabel?: string;
}) {
  return (
    <div
      data-slot="tool-call-code"
      className={cn("relative px-2 pb-2", className)}
      {...props}
    >
      <pre className="max-w-full overflow-x-auto p-2 text-xs break-words whitespace-pre-wrap">
        {value}
      </pre>
      <Button
        variant="ghost"
        size="sm"
        className="absolute top-1 right-1 h-6 w-6 p-0"
        onClick={() => {
          navigator.clipboard.writeText(value);
          toast.success(copyLabel);
        }}
      >
        <CopyIcon className="size-3" strokeWidth={1.5} />
      </Button>
    </div>
  );
}

export {
  ToolCall,
  ToolCallTrigger,
  ToolCallContent,
  ToolCallPanel,
  ToolCallPanelTrigger,
  ToolCallPanelContent,
  ToolCallCode,
};
