export type Feed = {
  id: string
  name: string
  url: string
  last_fetched_at: string | null
  last_status: string | null
  item_count: number
}

export type Subscription = {
  id: string
  name: string
  url: string
  kind: "rss" | "x"
  enabled: boolean
  exclude_retweets: boolean
  exclude_replies: boolean
  username: string | null
  last_fetched_at: string | null
  last_status: string | null
  last_error: string | null
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

const ADMIN_TOKEN_KEY = "news_admin_token"

export function getAdminToken(): string {
  return sessionStorage.getItem(ADMIN_TOKEN_KEY) ?? ""
}

export function setAdminToken(token: string) {
  if (token) {
    sessionStorage.setItem(ADMIN_TOKEN_KEY, token)
  } else {
    sessionStorage.removeItem(ADMIN_TOKEN_KEY)
  }
}

async function parseError(res: Response): Promise<string> {
  try {
    const data = (await res.json()) as { detail?: string | { msg: string }[] }
    if (typeof data.detail === "string") return data.detail
    if (Array.isArray(data.detail) && data.detail[0]?.msg) {
      return data.detail.map((d) => d.msg).join("; ")
    }
  } catch {
    /* ignore */
  }
  return `${res.status} ${res.statusText}`
}

async function getJson<T>(path: string): Promise<T> {
  const res = await fetch(path)
  if (!res.ok) {
    throw new Error(await parseError(res))
  }
  return res.json() as Promise<T>
}

async function mutateJson<T>(
  path: string,
  method: "POST" | "PATCH" | "DELETE",
  body?: unknown
): Promise<T> {
  const headers: Record<string, string> = {}
  const token = getAdminToken()
  if (token) headers.Authorization = `Bearer ${token}`
  if (body !== undefined) headers["Content-Type"] = "application/json"

  const res = await fetch(path, {
    method,
    headers,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  })
  if (!res.ok) {
    throw new Error(await parseError(res))
  }
  return res.json() as Promise<T>
}

export function fetchFeeds() {
  return getJson<{ feeds: Feed[] }>("/api/feeds")
}

export function fetchSubscriptions() {
  return getJson<{
    auth_required: boolean
    subscriptions: Subscription[]
  }>("/api/subscriptions")
}

export function createSubscription(payload: {
  kind: "rss" | "x"
  name: string
  url?: string
  username?: string
  exclude_retweets?: boolean
  exclude_replies?: boolean
}) {
  return mutateJson<{
    subscription: Subscription
    fetch_error?: string
  }>("/api/subscriptions", "POST", payload)
}

export function patchSubscription(
  id: string,
  payload: {
    name?: string
    url?: string
    enabled?: boolean
    exclude_retweets?: boolean
    exclude_replies?: boolean
  }
) {
  return mutateJson<{ subscription: Subscription }>(
    `/api/subscriptions/${encodeURIComponent(id)}`,
    "PATCH",
    payload
  )
}

export function deleteSubscription(id: string) {
  return mutateJson<{ subscription: Subscription }>(
    `/api/subscriptions/${encodeURIComponent(id)}`,
    "DELETE"
  )
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
