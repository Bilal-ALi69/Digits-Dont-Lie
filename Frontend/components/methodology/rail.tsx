"use client"

import { useEffect, useState } from "react"

import { cn } from "@/lib/utils"

export interface RailItem {
  id: string
  label: string
  act?: string
}

/* ─── Wayfinding ──────────────────────────────────────────────────────────────
   "Where am I, where can I go, what's there, how do I get out" — the four
   questions §16 says every screen has to answer. On a document this long the
   old page answered none of them: fourteen collapsed rows gave no sense of
   position, extent, or what was still ahead.
   -------------------------------------------------------------------------- */

/** How far through the article the reader is. A hairline at the very top of the
 *  viewport — the one piece of chrome that earns its place on a long read,
 *  because it is the only thing that can say "how much of this is left". */
export function ReadingProgress() {
  const [pct, setPct] = useState(0)

  useEffect(() => {
    const onScroll = () => {
      const doc = document.documentElement
      const max = doc.scrollHeight - doc.clientHeight
      setPct(max > 0 ? Math.min(100, (doc.scrollTop / max) * 100) : 0)
    }
    onScroll()
    window.addEventListener("scroll", onScroll, { passive: true })
    window.addEventListener("resize", onScroll)
    return () => {
      window.removeEventListener("scroll", onScroll)
      window.removeEventListener("resize", onScroll)
    }
  }, [])

  return (
    <div className="pointer-events-none fixed top-0 right-0 left-0 z-50 h-0.5">
      <div
        className="h-full origin-left bg-orange"
        // Scaled rather than sized: width would lay out on every scroll frame,
        // and this updates on every scroll frame.
        style={{ transform: `scaleX(${pct / 100})` }}
      />
    </div>
  )
}

/** The section rail. Desktop only — on a narrow screen it would be a second
 *  column competing with the one that matters, and the progress bar above
 *  already answers "how far in am I". */
export function Rail({ items }: { items: RailItem[] }) {
  const [active, setActive] = useState(items[0]?.id ?? "")

  useEffect(() => {
    const nodes = items
      .map((i) => document.getElementById(i.id))
      .filter((n): n is HTMLElement => n !== null)
    if (nodes.length === 0) return

    // A band across the upper third of the viewport: whatever heading is inside
    // it is what the reader is reading. Keying off "topmost intersecting" alone
    // makes the marker jump backwards when a tall section scrolls past.
    const io = new IntersectionObserver(
      (entries) => {
        const visible = entries
          .filter((e) => e.isIntersecting)
          .sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top)
        if (visible[0]) setActive(visible[0].target.id)
      },
      { rootMargin: "-12% 0px -70% 0px", threshold: 0 },
    )
    nodes.forEach((n) => io.observe(n))
    return () => io.disconnect()
  }, [items])

  return (
    <nav aria-label="Sections" className="sticky top-24 hidden w-40 shrink-0 self-start lg:block">
      <ul className="flex flex-col gap-0.5">
        {items.map((item) => {
          const isActive = active === item.id
          return (
            <li key={item.id}>
              {item.act && (
                <span className="text-muted-foreground/45 mt-5 mb-1.5 block font-mono text-micro font-bold tracking-[0.18em] uppercase first:mt-0">
                  {item.act}
                </span>
              )}
              <a
                href={`#${item.id}`}
                className={cn(
                  "group/rail flex items-center gap-2.5 rounded-md py-1 pr-2 pl-0.5",
                  "text-mini transition-colors duration-(--dur-press) ease-(--ease-standard)",
                  isActive
                    ? "text-foreground font-semibold"
                    : "text-muted-foreground/70 hover:text-foreground",
                )}
              >
                {/* The marker grows rather than appearing — a 2px bar easing
                    from nothing to full height is the whole feedback here. */}
                <span
                  className={cn(
                    "w-0.5 shrink-0 rounded-full transition-[height,background-color] duration-[280ms] ease-(--ease-rise) motion-reduce:transition-none",
                    isActive ? "h-4 bg-orange" : "h-2 bg-hairline-strong/50",
                  )}
                />
                <span className="leading-[1.4]">{item.label}</span>
              </a>
            </li>
          )
        })}
      </ul>
    </nav>
  )
}
