import { useEffect, useState } from "react"
import ReactMarkdown from "react-markdown"
import { ExternalLinkIcon } from "lucide-react"

import { fetchFeeds, fetchItem, fetchItems, type Feed, type Item } from "@/api"
import { ModeToggle } from "@/components/mode-toggle"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { buttonVariants } from "@/components/ui/button"
import {
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyTitle,
} from "@/components/ui/empty"
import { ScrollArea } from "@/components/ui/scroll-area"
import { Separator } from "@/components/ui/separator"
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group"
import { cn } from "@/lib/utils"

function formatWhen(iso: string | null): string {
  if (!iso) return ""
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  }).format(d)
}

function stripHtml(html: string): string {
  const tmp = document.createElement("div")
  tmp.innerHTML = html
  return tmp.textContent?.trim() ?? ""
}

export default function App() {
  const [feeds, setFeeds] = useState<Feed[]>([])
  const [items, setItems] = useState<Item[]>([])
  const [total, setTotal] = useState(0)
  const [feedId, setFeedId] = useState<string | null>(null)
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [detail, setDetail] = useState<Item | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    fetchFeeds()
      .then((data) => setFeeds(data.feeds))
      .catch((err: Error) => setError(err.message))
  }, [])

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)
    fetchItems({ limit: 80, feedId })
      .then((data) => {
        if (cancelled) return
        setItems(data.items)
        setTotal(data.total)
        setLoading(false)
      })
      .catch((err: Error) => {
        if (cancelled) return
        setError(err.message)
        setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [feedId])

  useEffect(() => {
    if (selectedId == null) {
      setDetail(null)
      return
    }
    let cancelled = false
    fetchItem(selectedId)
      .then((item) => {
        if (!cancelled) setDetail(item)
      })
      .catch((err: Error) => {
        if (!cancelled) setError(err.message)
      })
    return () => {
      cancelled = true
    }
  }, [selectedId])

  const body =
    detail?.body_status === "ok" && detail.body_markdown
      ? detail.body_markdown
      : detail?.summary
        ? stripHtml(detail.summary)
        : null

  return (
    <div className="mx-auto flex min-h-svh max-w-6xl flex-col gap-6 p-6 md:p-8">
      <header className="flex items-start justify-between gap-4">
        <div className="flex flex-col gap-1">
          <h1 className="text-3xl font-semibold tracking-tight">news</h1>
          <p className="text-muted-foreground text-sm">
            Curated AI-lab stream from your local DB
          </p>
        </div>
        <ModeToggle />
      </header>

      <ToggleGroup
        value={[feedId ?? "all"]}
        onValueChange={(value) => {
          const next = value[0]
          if (!next) return
          setFeedId(next === "all" ? null : next)
        }}
        variant="outline"
        size="sm"
        spacing={0}
        className="flex max-w-full flex-wrap"
        aria-label="Sources"
      >
        <ToggleGroupItem value="all">All</ToggleGroupItem>
        {feeds.map((feed) => (
          <ToggleGroupItem key={feed.id} value={feed.id}>
            {feed.name}
          </ToggleGroupItem>
        ))}
      </ToggleGroup>

      {error && (
        <Alert variant="destructive">
          <AlertTitle>API error</AlertTitle>
          <AlertDescription>
            {error}. Is <code className="font-mono text-xs">python api.py</code>{" "}
            running?
          </AlertDescription>
        </Alert>
      )}

      <div className="grid min-h-0 flex-1 gap-0 md:grid-cols-2 md:border md:border-border">
        <section className="flex min-h-[40vh] flex-col border-b border-border md:min-h-[70vh] md:border-r md:border-b-0">
          <div className="text-muted-foreground flex items-center justify-between px-3 py-2 text-xs tracking-wide uppercase">
            <span>{loading ? "Loading…" : `${total} items`}</span>
          </div>
          <Separator />
          <ScrollArea className="min-h-0 flex-1">
            <ul className="flex flex-col">
              {items.map((item) => {
                const active = item.id === selectedId
                return (
                  <li key={item.id} className="border-b border-border last:border-b-0">
                    <button
                      type="button"
                      onClick={() => setSelectedId(item.id)}
                      className={cn(
                        "hover:bg-muted/60 flex w-full cursor-pointer flex-col gap-1 px-3 py-3 text-left transition-colors",
                        active && "bg-muted"
                      )}
                    >
                      <div className="flex items-center justify-between gap-3">
                        <span className="text-muted-foreground text-[11px] tracking-wide uppercase">
                          {item.feed_name}
                        </span>
                        <time className="text-muted-foreground shrink-0 text-xs">
                          {formatWhen(item.published_at ?? item.fetched_at)}
                        </time>
                      </div>
                      <span className="text-sm leading-snug font-medium">
                        {item.title || "(no title)"}
                      </span>
                    </button>
                  </li>
                )
              })}
            </ul>
            {!loading && items.length === 0 && (
              <Empty className="border-0">
                <EmptyHeader>
                  <EmptyTitle>No items</EmptyTitle>
                  <EmptyDescription>
                    Run the fetch scripts first.
                  </EmptyDescription>
                </EmptyHeader>
              </Empty>
            )}
          </ScrollArea>
        </section>

        <aside className="flex min-h-[40vh] flex-col md:min-h-[70vh]">
          {!detail && (
            <Empty className="border-0">
              <EmptyHeader>
                <EmptyTitle>Select an item</EmptyTitle>
                <EmptyDescription>
                  Pick something from the timeline to read.
                </EmptyDescription>
              </EmptyHeader>
            </Empty>
          )}
          {detail && (
            <article className="flex flex-col gap-4 p-4 md:p-6">
              <div className="flex flex-col gap-2">
                <p className="text-muted-foreground text-[11px] tracking-wide uppercase">
                  {detail.feed_name}
                </p>
                <h2 className="text-xl font-semibold tracking-tight text-balance md:text-2xl">
                  {detail.title || "(no title)"}
                </h2>
                <div className="text-muted-foreground flex flex-wrap items-center gap-2 text-sm">
                  <time>{formatWhen(detail.published_at ?? detail.fetched_at)}</time>
                  {detail.link && (
                    <a
                      href={detail.link}
                      target="_blank"
                      rel="noreferrer"
                      className={cn(buttonVariants({ variant: "link", size: "sm" }), "h-auto p-0")}
                    >
                      Open original
                      <ExternalLinkIcon data-icon="inline-end" />
                    </a>
                  )}
                </div>
              </div>
              <Separator />
              {body ? (
                <div className="typeset typeset-notes max-w-[42em]">
                  {detail.body_status === "ok" && detail.body_markdown ? (
                    <ReactMarkdown>{detail.body_markdown}</ReactMarkdown>
                  ) : (
                    <p>{body}</p>
                  )}
                </div>
              ) : (
                <p className="text-muted-foreground text-sm">
                  No body stored. Run enrich.py or open the original link.
                </p>
              )}
            </article>
          )}
        </aside>
      </div>
    </div>
  )
}
