export type ItemMedia = {
  kind: "photo" | "video" | "website"
  url: string
  preview_url?: string | null
  image_url?: string | null
  title?: string | null
  description?: string | null
  site_name?: string | null
  alt?: string | null
  tco?: string | null
  embed?: boolean
  /** X animated GIF stored as a silent mp4. */
  gif?: boolean
}

export function isTwimgVideoUrl(url: string): boolean {
  try {
    const parsed = new URL(url)
    return parsed.protocol === "https:" && parsed.hostname === "video.twimg.com"
  } catch {
    return false
  }
}

/** Same-origin stream. Browser <video> sends a Referer that video.twimg.com 403s. */
export function playableVideoUrl(url: string): string {
  if (!isTwimgVideoUrl(url)) return url
  return `/api/media/video?url=${encodeURIComponent(url)}`
}

/** Animated GIFs from X live at video.twimg.com/tweet_video/*.mp4. */
export function isAnimatedGif(item: Pick<ItemMedia, "url" | "gif">): boolean {
  if (item.gif) return true
  try {
    return new URL(item.url).pathname.includes("/tweet_video/")
  } catch {
    return false
  }
}

const URL_RE = /https?:\/\/[^\s<>"')]+/gi

export function extractUrls(text: string | null | undefined): string[] {
  if (!text) return []
  const seen = new Set<string>()
  const out: string[] = []
  for (const match of text.match(URL_RE) ?? []) {
    const url = match.replace(/[).,;:!?]+$/, "")
    if (url && !seen.has(url)) {
      seen.add(url)
      out.push(url)
    }
  }
  return out
}

export function coveredPreviewUrls(media: ItemMedia[]): Set<string> {
  const covered = new Set<string>()
  for (const item of media) {
    if (item.tco) covered.add(item.tco)
    if (item.url) covered.add(item.url)
  }
  return covered
}

export function leftoverUrls(text: string | null | undefined, media: ItemMedia[]): string[] {
  const covered = coveredPreviewUrls(media)
  return extractUrls(text).filter((url) => !covered.has(url))
}

export function stripPreviewUrls(text: string, urls: string[]): string {
  if (!urls.length) return text
  let out = text
  for (const url of urls) {
    out = out.split(url).join("")
  }
  return out
    .replace(/[ \t]+\n/g, "\n")
    .replace(/\n{3,}/g, "\n\n")
    .replace(/[ \t]{2,}/g, " ")
    .trim()
}

export function siteHost(url: string): string {
  try {
    return new URL(url).host.replace(/^www\./, "")
  } catch {
    return url
  }
}

export function isYoutubeEmbed(url: string): boolean {
  try {
    const host = new URL(url).host
    return host === "www.youtube-nocookie.com" || host === "www.youtube.com" || host === "youtube.com"
  } catch {
    return false
  }
}

export function isVimeoEmbed(url: string): boolean {
  try {
    return new URL(url).host === "player.vimeo.com"
  } catch {
    return false
  }
}
