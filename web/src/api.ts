export type Feed = {
  id: string
  name: string
  url: string
  last_fetched_at: string | null
  last_status: string | null
  item_count: number
}

export type Item = {
  id: number
  feed_id: string
  feed_name: string
  guid: string
  title: string | null
  link: string | null
  summary: string | null
  published_at: string | null
  fetched_at: string
  body_status: string | null
  has_body?: boolean
  body_markdown?: string | null
  body_fetched_at?: string | null
  body_error?: string | null
}

async function getJson<T>(path: string): Promise<T> {
  const res = await fetch(path)
  if (!res.ok) {
    throw new Error(`${res.status} ${res.statusText}`)
  }
  return res.json() as Promise<T>
}

export function fetchFeeds() {
  return getJson<{ feeds: Feed[] }>("/api/feeds")
}

export function fetchItems(opts: {
  limit?: number
  offset?: number
  feedId?: string | null
}) {
  const params = new URLSearchParams()
  params.set("limit", String(opts.limit ?? 50))
  if (opts.offset) params.set("offset", String(opts.offset))
  if (opts.feedId) params.set("feed_id", opts.feedId)
  return getJson<{ total: number; items: Item[] }>(`/api/items?${params}`)
}

export function fetchItem(id: number) {
  return getJson<Item>(`/api/items/${id}`)
}
