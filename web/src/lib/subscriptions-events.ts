/** Dispatched after chat tools mutate Sources so the hub can refresh chips/panel. */

export const SUBSCRIPTIONS_CHANGED_EVENT = "news:subscriptions-changed"

export function notifySubscriptionsChanged(): void {
  if (typeof window === "undefined") return
  window.dispatchEvent(new Event(SUBSCRIPTIONS_CHANGED_EVENT))
}
