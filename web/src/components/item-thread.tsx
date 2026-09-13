import { ExternalLinkIcon } from "lucide-react"

import type { Item } from "@/api"
import { ItemBody } from "@/components/item-body"
import { buttonVariants } from "@/components/ui/button"
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

export function ItemThread({ posts }: { posts: Item[] }) {
  return (
    <ol className="flex flex-col">
      {posts.map((post, index) => {
        const last = index === posts.length - 1
        return (
          <li key={post.id} className="flex gap-3">
            <div className="flex w-4 shrink-0 flex-col items-center">
              <span className="bg-foreground mt-1.5 size-2 rounded-full" />
              {!last && <span className="bg-border w-px flex-1" />}
            </div>
            <div className={cn("flex min-w-0 flex-1 flex-col gap-2", !last && "pb-5")}>
              <div className="text-muted-foreground flex flex-wrap items-center gap-2 text-xs">
                <time>{formatWhen(post.published_at ?? post.fetched_at)}</time>
                {post.link && (
                  <a
                    href={post.link}
                    target="_blank"
                    rel="noreferrer"
                    className={cn(
                      buttonVariants({ variant: "link", size: "sm" }),
                      "h-auto p-0 text-xs"
                    )}
                  >
                    Open original
                    <ExternalLinkIcon data-icon="inline-end" />
                  </a>
                )}
              </div>
              <ItemBody key={post.id} item={post} />
            </div>
          </li>
        )
      })}
    </ol>
  )
}
