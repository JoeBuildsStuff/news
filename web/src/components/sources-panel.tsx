import { useEffect, useState, type FormEvent } from "react"
import { SettingsIcon, XIcon } from "lucide-react"

import {
  createSubscription,
  deleteSubscription,
  fetchSubscriptions,
  getAdminToken,
  patchSubscription,
  setAdminToken,
  type Subscription,
} from "@/api"
import { Badge } from "@/components/ui/badge"
import { Button, buttonVariants } from "@/components/ui/button"
import { Separator } from "@/components/ui/separator"
import { Toggle } from "@/components/ui/toggle"
import { cn } from "@/lib/utils"

const inputClass =
  "border-input bg-background placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-ring/40 h-8 w-full rounded-md border px-2.5 text-sm outline-none focus-visible:ring-2"

type SourcesPanelProps = {
  onClose: () => void
  onChanged: () => void
}

export function SourcesPanel({ onClose, onChanged }: SourcesPanelProps) {
  const [subs, setSubs] = useState<Subscription[]>([])
  const [authRequired, setAuthRequired] = useState(false)
  const [token, setToken] = useState(getAdminToken)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [kind, setKind] = useState<"rss" | "x">("rss")
  const [name, setName] = useState("")
  const [url, setUrl] = useState("")
  const [username, setUsername] = useState("")
  const [busyId, setBusyId] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    fetchSubscriptions()
      .then((data) => {
        if (cancelled) return
        setSubs(data.subscriptions)
        setAuthRequired(data.auth_required)
        setError(null)
      })
      .catch((err: Error) => {
        if (!cancelled) setError(err.message)
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [])

  function reload() {
    setError(null)
    fetchSubscriptions()
      .then((data) => {
        setSubs(data.subscriptions)
        setAuthRequired(data.auth_required)
      })
      .catch((err: Error) => setError(err.message))
  }

  async function handleCreate(e: FormEvent) {
    e.preventDefault()
    setError(null)
    setBusyId("__create__")
    try {
      const result = await createSubscription(
        kind === "rss"
          ? { kind: "rss", name: name.trim(), url: url.trim() }
          : {
              kind: "x",
              name: name.trim(),
              username: username.trim(),
            }
      )
      if (result.fetch_error) {
        setError(`Saved, but initial fetch failed: ${result.fetch_error}`)
      }
      setName("")
      setUrl("")
      setUsername("")
      reload()
      onChanged()
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusyId(null)
    }
  }

  async function toggleEnabled(sub: Subscription) {
    setBusyId(sub.id)
    setError(null)
    try {
      if (sub.enabled) {
        await deleteSubscription(sub.id)
      } else {
        await patchSubscription(sub.id, { enabled: true })
      }
      reload()
      onChanged()
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusyId(null)
    }
  }

  async function toggleRetweets(sub: Subscription) {
    setBusyId(sub.id)
    setError(null)
    try {
      await patchSubscription(sub.id, {
        exclude_retweets: !sub.exclude_retweets,
      })
      reload()
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusyId(null)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-black/40">
      <button
        type="button"
        className="absolute inset-0 cursor-default"
        aria-label="Close sources"
        onClick={onClose}
      />
      <aside className="bg-background border-border relative flex h-full w-full max-w-md flex-col border-l shadow-lg">
        <div className="flex items-center justify-between gap-3 px-4 py-3">
          <div className="flex items-center gap-2">
            <SettingsIcon className="text-muted-foreground size-4" />
            <h2 className="text-sm font-semibold tracking-tight">Sources</h2>
          </div>
          <Button
            type="button"
            variant="ghost"
            size="icon-sm"
            onClick={onClose}
            aria-label="Close"
          >
            <XIcon />
          </Button>
        </div>
        <Separator />

        <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto p-4">
          {authRequired && (
            <div className="flex flex-col gap-1.5">
              <label htmlFor="admin-token" className="text-xs font-medium">
                Admin token
              </label>
              <input
                id="admin-token"
                type="password"
                className={inputClass}
                value={token}
                autoComplete="off"
                placeholder="NEWS_ADMIN_TOKEN"
                onChange={(e) => {
                  const next = e.target.value
                  setToken(next)
                  setAdminToken(next)
                }}
              />
              <p className="text-muted-foreground text-[11px]">
                Stored in sessionStorage for this tab only.
              </p>
            </div>
          )}

          <form className="flex flex-col gap-3" onSubmit={handleCreate}>
            <p className="text-xs font-medium tracking-wide uppercase">
              Add source
            </p>
            <div className="flex gap-1">
              <Toggle
                pressed={kind === "rss"}
                onPressedChange={(on) => on && setKind("rss")}
                variant="outline"
                size="sm"
              >
                RSS
              </Toggle>
              <Toggle
                pressed={kind === "x"}
                onPressedChange={(on) => on && setKind("x")}
                variant="outline"
                size="sm"
              >
                X
              </Toggle>
            </div>
            <input
              className={inputClass}
              placeholder="Display name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              required
            />
            {kind === "rss" ? (
              <input
                className={inputClass}
                placeholder="https://example.com/rss.xml"
                value={url}
                onChange={(e) => setUrl(e.target.value)}
                required
              />
            ) : (
              <input
                className={inputClass}
                placeholder="username (without @)"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                required
              />
            )}
            <Button
              type="submit"
              size="sm"
              disabled={busyId === "__create__"}
            >
              {busyId === "__create__" ? "Adding…" : "Subscribe"}
            </Button>
          </form>

          <Separator />

          <div className="flex flex-col gap-2">
            <p className="text-muted-foreground text-xs">
              {loading ? "Loading…" : `${subs.length} subscriptions`}
            </p>
            {error && (
              <p className="text-destructive text-xs" role="alert">
                {error}
              </p>
            )}
            <ul className="flex flex-col gap-2">
              {subs.map((sub) => (
                <li
                  key={sub.id}
                  className="border-border flex flex-col gap-2 rounded-md border p-3"
                >
                  <div className="flex items-start justify-between gap-2">
                    <div className="flex min-w-0 flex-col gap-1">
                      <div className="flex flex-wrap items-center gap-1.5">
                        <span className="truncate text-sm font-medium">
                          {sub.name}
                        </span>
                        <Badge variant="outline">
                          {sub.kind === "x" ? "X" : "RSS"}
                        </Badge>
                        {!sub.enabled && (
                          <Badge variant="secondary">paused</Badge>
                        )}
                      </div>
                      <p className="text-muted-foreground truncate font-mono text-[11px]">
                        {sub.kind === "x"
                          ? `@${sub.username}`
                          : sub.url}
                      </p>
                      {sub.last_status && (
                        <p className="text-muted-foreground text-[11px]">
                          {sub.last_status}
                          {sub.item_count
                            ? ` · ${sub.item_count} items`
                            : ""}
                        </p>
                      )}
                    </div>
                  </div>
                  <div className="flex flex-wrap items-center gap-2">
                    <button
                      type="button"
                      className={cn(
                        buttonVariants({ variant: "outline", size: "sm" })
                      )}
                      disabled={busyId === sub.id}
                      onClick={() => toggleEnabled(sub)}
                    >
                      {sub.enabled ? "Unsubscribe" : "Resubscribe"}
                    </button>
                    {sub.kind === "x" && sub.enabled && (
                      <Toggle
                        pressed={!sub.exclude_retweets}
                        onPressedChange={() => toggleRetweets(sub)}
                        disabled={busyId === sub.id}
                        variant="outline"
                        size="sm"
                        aria-label="Include retweets"
                      >
                        Include retweets
                      </Toggle>
                    )}
                  </div>
                </li>
              ))}
            </ul>
          </div>
        </div>
      </aside>
    </div>
  )
}
