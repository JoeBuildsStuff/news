export interface ChatAttachmentLike {
  id: string;
  name: string;
  size: number;
  type: string;
  file?: File;
  url?: string;
  data?: string;
}

export type ChatAttachmentKind =
  | "document"
  | "archive"
  | "spreadsheet"
  | "video"
  | "audio"
  | "image"
  | "file";

export function formatAttachmentSize(bytes: number) {
  if (bytes === 0) return "0 Bytes";

  const unit = 1024;
  const sizes = ["Bytes", "KB", "MB", "GB"];
  const unitIndex = Math.floor(Math.log(bytes) / Math.log(unit));

  return `${parseFloat((bytes / Math.pow(unit, unitIndex)).toFixed(2))} ${
    sizes[unitIndex]
  }`;
}

export function getAttachmentKind(
  attachment: ChatAttachmentLike
): ChatAttachmentKind {
  const fileType = attachment.type;
  const fileName = attachment.name.toLowerCase();

  if (
    fileType.includes("pdf") ||
    fileName.endsWith(".pdf") ||
    fileType.includes("word") ||
    fileName.endsWith(".doc") ||
    fileName.endsWith(".docx")
  ) {
    return "document";
  }

  if (
    fileType.includes("zip") ||
    fileType.includes("archive") ||
    fileName.endsWith(".zip") ||
    fileName.endsWith(".rar")
  ) {
    return "archive";
  }

  if (
    fileType.includes("excel") ||
    fileName.endsWith(".xls") ||
    fileName.endsWith(".xlsx")
  ) {
    return "spreadsheet";
  }

  if (fileType.includes("video/")) return "video";
  if (fileType.includes("audio/")) return "audio";
  if (fileType.startsWith("image/")) return "image";

  return "file";
}

export function isPreviewableImageAttachment(attachment: ChatAttachmentLike) {
  return getAttachmentKind(attachment) === "image";
}

export function getAttachmentImageSrc(attachment: ChatAttachmentLike) {
  return attachment.data || attachment.url || null;
}
