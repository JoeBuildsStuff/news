import { useEffect, useState } from "react"
import { MoonIcon, SunIcon } from "lucide-react"

import { useTheme } from "@/components/theme-provider"
import { Button } from "@/components/ui/button"

export function ModeToggle() {
  const { setTheme } = useTheme()
  const [isDark, setIsDark] = useState(false)

  useEffect(() => {
    const root = document.documentElement
    const sync = () => setIsDark(root.classList.contains("dark"))
    sync()
    const observer = new MutationObserver(sync)
    observer.observe(root, { attributes: true, attributeFilter: ["class"] })
    return () => observer.disconnect()
  }, [])

  const next = isDark ? "light" : "dark"

  return (
    <Button
      type="button"
      variant="outline"
      size="icon-sm"
      aria-label={`Switch to ${next} mode`}
      title={`Switch to ${next} mode (or press d)`}
      onClick={() => setTheme(next)}
    >
      {isDark ? <SunIcon /> : <MoonIcon />}
    </Button>
  )
}
