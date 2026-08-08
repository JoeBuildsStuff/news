"use client";

import { X } from "lucide-react";
import { useEffect, useMemo } from "react";

import {
  Attachment,
  AttachmentAction,
  AttachmentActions,
  AttachmentContent,
  AttachmentDescription,
  AttachmentMedia,
  AttachmentTitle,
  AttachmentTrigger,
} from "@/components/ui/attachment";
import {
  formatAttachmentSize,
  getAttachmentImageSrc,
  isPreviewableImageAttachment,
  type ChatAttachmentLike,
} from "@/lib/chat/attachments";
import { cn } from "@/lib/utils";
import { ChatAttachmentIcon } from "./chat-attachment-icon";

interface ChatAttachmentCardProps {
  attachment: ChatAttachmentLike;
  variant?: "input" | "message";
  disabled?: boolean;
  onPreview?: (attachment: ChatAttachmentLike) => void;
  onRemove?: (attachmentId: string) => void;
}

export function ChatAttachmentCard({
  attachment,
  variant = "input",
  disabled = false,
  onPreview,
  onRemove,
}: ChatAttachmentCardProps) {
  const objectUrl = useMemo(
    () => (attachment.file ? URL.createObjectURL(attachment.file) : null),
    [attachment.file]
  );
  const imageSrc = getAttachmentImageSrc(attachment) || objectUrl;
  const isImage = isPreviewableImageAttachment(attachment) && imageSrc;
  const isMessageVariant = variant === "message";

  useEffect(() => {
    return () => {
      if (objectUrl) {
        URL.revokeObjectURL(objectUrl);
      }
    };
  }, [objectUrl]);

  return (
    <Attachment
      orientation="vertical"
      size={isMessageVariant ? "xs" : "default"}
      className={cn(
        "cursor-pointer bg-background",
        isMessageVariant
          ? "w-[60px] min-w-[60px] rounded-md"
          : "w-[104px] max-w-[104px] rounded-lg bg-background/80 shadow-sm"
      )}
    >
      <AttachmentMedia
        variant={isImage ? "image" : "icon"}
        className="w-full rounded-t-[inherit] bg-accent"
      >
        {isImage ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={imageSrc}
            alt={attachment.name}
            className="size-full rounded-t-[inherit] object-cover"
          />
        ) : (
          <ChatAttachmentIcon
            attachment={attachment}
            className={isMessageVariant ? "size-4" : "size-5"}
          />
        )}
      </AttachmentMedia>

      <AttachmentContent
        className={cn(
          "flex flex-col border-t",
          isMessageVariant ? "gap-0 p-1" : "gap-0.5 p-2"
        )}
      >
        <AttachmentTitle
          className={cn(
            "font-medium leading-tight",
            isMessageVariant ? "text-[9px]" : "text-[11px]"
          )}
        >
          {attachment.name}
        </AttachmentTitle>
        <AttachmentDescription
          className={cn(
            "leading-tight",
            isMessageVariant ? "text-[8px]" : "text-[10px]"
          )}
        >
          {formatAttachmentSize(attachment.size)}
        </AttachmentDescription>
      </AttachmentContent>

      {onRemove && (
        <AttachmentActions className="absolute -top-1.5 -right-1.5 z-20 opacity-100">
          <AttachmentAction
            onClick={(event) => {
              event.stopPropagation();
              onRemove(attachment.id);
            }}
            size="icon"
            variant="secondary"
            className="size-6 rounded-full border border-border bg-background/95 shadow-sm"
            aria-label="Remove file"
            disabled={disabled}
          >
            <X className="size-4" />
          </AttachmentAction>
        </AttachmentActions>
      )}

      {onPreview && (
        <AttachmentTrigger
          aria-label={`Preview ${attachment.name}`}
          onClick={() => onPreview(attachment)}
        />
      )}
    </Attachment>
  );
}
