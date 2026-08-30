"use client"

import { useEffect, useState } from "react"
import { MoonIcon, SunIcon } from "lucide-react"

import { cn } from "@/lib/utils"
import { Button } from "@/components/ui/button"
import { pressProps } from "@/components/verifier/sheen"

const STORAGE_KEY = "ddl-theme"

function apply(dark: boolean) {
  const root = document.documentElement
  root.classList.toggle("dark", dark)
  root.classList.toggle("light", !dark)
}

export function ThemeToggle() {
  // null until mounted: the server cannot know the stored preference, so
  // rendering either icon during SSR would be a hydration mismatch and, half
  // the time, the wrong icon flashing before the effect corrects it.
  const [isDark, setIsDark] = useState<boolean | null>(null)

  // The inline script in app/layout.tsx has already resolved and applied the
  // theme before first paint. Read the result rather than re-deriving it from
  // localStorage — two independent copies of that logic would be free to
  // disagree, and this one runs late enough that its answer would win.
  useEffect(() => {
    setIsDark(document.documentElement.classList.contains("dark"))
  }, [])

  function toggle() {
    const next = !isDark
    apply(next)
    try {
      localStorage.setItem(STORAGE_KEY, next ? "dark" : "light")
    } catch {
      // Private browsing can refuse storage. The theme still applies for this
      // page; it simply will not be remembered.
    }
    setIsDark(next)
  }

  return (
    <Button
      variant="ghost"
      size="icon-sm"
      onClick={toggle}
      aria-label={isDark ? "Switch to light theme" : "Switch to dark theme"}
      {...pressProps}
      // 28px (size-7) is well under Apple's 44pt minimum, and a bare ghost
      // icon in muted grey on warm paper is easy to miss entirely — which is
      // what happened. On a phone it becomes a 44px bordered chip so it reads
      // as a control and can actually be hit.
      className={cn(
        "rounded-full text-muted-foreground hover:text-foreground",
        // The state layer is the whole feedback on a control whose only other
        // response is an icon that cross-rotates over 280ms — far too slow to
        // read as an acknowledgement of the tap itself (§1).
        "max-sm:text-foreground max-sm:border-hairline max-sm:bg-surface-card max-sm:size-11 max-sm:border max-sm:shadow-sm m3-press",
      )}
    >
      {/* Before mount both icons sit at opacity 0, so the button holds its
          space, the header never reflows, and no wrong icon appears for a
          frame. After mount they cross-rotate rather than swapping instantly —
          the icon change is the only feedback this control gives. */}
      <span className="grid size-4 place-items-center" aria-hidden="true">
        <MoonIcon
          className={cn(
            "col-start-1 row-start-1 size-4 transition-[opacity,transform] duration-[280ms] ease-(--ease-rise) motion-reduce:transition-none",
            isDark === true
              ? "scale-100 rotate-0 opacity-100"
              : "scale-75 -rotate-90 opacity-0",
          )}
        />
        <SunIcon
          className={cn(
            "col-start-1 row-start-1 size-4 transition-[opacity,transform] duration-[280ms] ease-(--ease-rise) motion-reduce:transition-none",
            isDark === false
              ? "scale-100 rotate-0 opacity-100"
              : "scale-75 rotate-90 opacity-0",
          )}
        />
      </span>
    </Button>
  )
}
