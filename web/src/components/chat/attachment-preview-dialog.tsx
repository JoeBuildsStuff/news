"use client";

import { useEffect, useMemo } from "react";

import { Dialog, DialogContent } from "@/components/ui/dialog";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  formatAttachmentSize,
  getAttachmentImageSrc,
  isPreviewableImageAttachment,
  type ChatAttachmentLike,
} from "@/lib/chat/attachments";
import { ChatAttachmentIcon } from "./chat-attachment-icon";

interface AttachmentPreviewDialogProps {
  attachment: ChatAttachmentLike | null;
  onOpenChange: (open: boolean) => void;
}

export function AttachmentPreviewDialog({
  attachment,
  onOpenChange,
}: AttachmentPreviewDialogProps) {
  const objectUrl = useMemo(
    () => (attachment?.file ? URL.createObjectURL(attachment.file) : null),
    [attachment]
  );
  const imageSrc = attachment
    ? getAttachmentImageSrc(attachment) || objectUrl
    : null;
  const canPreviewImage =
    attachment && isPreviewableImageAttachment(attachment) && imageSrc;

  useEffect(() => {
    return () => {
      if (objectUrl) {
        URL.revokeObjectURL(objectUrl);
      }
    };
  }, [objectUrl]);

  return (
    <Dialog open={!!attachment} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[90vh] max-w-4xl p-0">
        <div className="relative">
          {attachment && (
            <div className="flex flex-col">
              <div className="flex items-center gap-3 border-b p-4">
                <div className="min-w-0 flex-1">
                  <h3 className="truncate text-lg font-medium">
                    {attachment.name}
                  </h3>
                  <p className="text-sm text-muted-foreground">
                    {attachment.type} • {formatAttachmentSize(attachment.size)}
                  </p>
                </div>
              </div>

              <ScrollArea className="max-h-[75vh] flex-1">
                {canPreviewImage ? (
                  <div className="flex items-center justify-center p-4">
                    {/* eslint-disable-next-line @next/next/no-img-element */}
                    <img
                      src={imageSrc}
                      alt={attachment.name}
                      className="max-h-[70vh] max-w-full rounded-lg object-contain"
                    />
                  </div>
                ) : (
                  <div className="flex items-center justify-center p-8">
                    <div className="text-center">
                      <ChatAttachmentIcon
                        attachment={attachment}
                        className="mx-auto size-5"
                      />
                      <p className="mt-2 text-sm text-muted-foreground">
                        Preview not available for this file type
                      </p>
                      <p className="mt-1 text-xs text-muted-foreground">
                        {attachment.name}
                      </p>
                    </div>
                  </div>
                )}
              </ScrollArea>
            </div>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}
