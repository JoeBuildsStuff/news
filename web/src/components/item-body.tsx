import { useEffect, useState } from "react"
import ReactMarkdown from "react-markdown"

import { unfurlUrls, type Item } from "@/api"
import { ItemImage } from "@/components/item-image"
import { ItemMediaList } from "@/components/item-media"
import { Skeleton } from "@/components/ui/skeleton"
import {
  leftoverUrls,
  stripPreviewUrls,
  type ItemMedia,
} from "@/lib/links"

function stripHtml(html: string): string {
  const tmp = document.createElement("div")
  tmp.innerHTML = html
  return tmp.textContent?.trim() ?? ""
}

export function ItemBody({ item }: { item: Item }) {
  const stored = item.media ?? []
  const markdown =
    item.body_status === "ok" && item.body_markdown ? item.body_markdown : null
  const summary = !markdown && item.summary ? stripHtml(item.summary) : null
  const pending = leftoverUrls(summary, stored)
  const pendingKey = pending.join("\n")

  const [extra, setExtra] = useState<ItemMedia[]>([])
  const [hiddenUrls, setHiddenUrls] = useState<string[]>([])
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    const urls = pendingKey ? pendingKey.split("\n") : []
    if (urls.length === 0) return
    let cancelled = false
    void (async () => {
      await Promise.resolve()
      if (cancelled) return
      setLoading(true)
      try {
        const data = await unfurlUrls(urls)
        if (cancelled) return
        const next: ItemMedia[] = []
        const hidden: string[] = []
        for (const preview of data.previews) {
          if (preview.media) next.push(preview.media)
          if (preview.media || preview.kind === "skip") hidden.push(preview.url)
        }
        setExtra(next)
        setHiddenUrls(hidden)
        setLoading(false)
      } catch {
        /* previews are optional; keep the post text */
        if (!cancelled) setLoading(false)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [pendingKey])

  if (markdown) {
    return (
      <div className="flex flex-col gap-3">
        {item.image_url && (
          <ItemImage
            src={item.image_url}
            alt=""
            className="bg-muted aspect-video w-full rounded-lg object-cover"
          />
        )}
        <div className="typeset typeset-notes max-w-[42em]">
          <ReactMarkdown>{markdown}</ReactMarkdown>
        </div>
      </div>
    )
  }

  const media = [...stored, ...extra]
  const stripped = summary
    ? stripPreviewUrls(
        summary,
        [
          ...media.flatMap((entry) => [entry.tco, entry.url].filter(Boolean) as string[]),
          ...hiddenUrls,
        ]
      )
    : null
  const showFallbackImage = Boolean(item.image_url) && media.length === 0

  return (
    <div className="flex flex-col gap-3">
      {stripped ? (
        <p className="text-sm leading-relaxed whitespace-pre-wrap">{stripped}</p>
      ) : null}
      {showFallbackImage && item.image_url && (
        <ItemImage
          src={item.image_url}
          alt=""
          className="bg-muted aspect-video w-full rounded-lg object-cover"
        />
      )}
      <ItemMediaList media={media} />
      {loading && <Skeleton className="aspect-video w-full rounded-lg" />}
      {!stripped && !showFallbackImage && media.length === 0 && !loading && (
        <p className="text-muted-foreground text-sm">
          No body stored. Run enrich.py or open the original link.
        </p>
      )}
    </div>
  )
}
