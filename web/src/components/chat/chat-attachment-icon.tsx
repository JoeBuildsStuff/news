import {
  File,
  FileArchive,
  FileSpreadsheet,
  FileText,
  FileVideo,
  Headphones,
  ImageIcon,
} from "lucide-react";

import {
  type ChatAttachmentLike,
  getAttachmentKind,
} from "@/lib/chat/attachments";
import { cn } from "@/lib/utils";

interface ChatAttachmentIconProps {
  attachment: ChatAttachmentLike;
  className?: string;
}

export function ChatAttachmentIcon({
  attachment,
  className,
}: ChatAttachmentIconProps) {
  const iconClassName = cn("opacity-60", className);

  switch (getAttachmentKind(attachment)) {
    case "document":
      return <FileText className={iconClassName} />;
    case "archive":
      return <FileArchive className={iconClassName} />;
    case "spreadsheet":
      return <FileSpreadsheet className={iconClassName} />;
    case "video":
      return <FileVideo className={iconClassName} />;
    case "audio":
      return <Headphones className={iconClassName} />;
    case "image":
      return <ImageIcon className={iconClassName} />;
    default:
      return <File className={iconClassName} />;
  }
}
