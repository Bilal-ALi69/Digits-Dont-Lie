"use client"

import { useCallback, useEffect, useRef, useState } from "react"

import { cn } from "@/lib/utils"

const TRACK_WIDTH = 40 // px

interface HorizontalScrollAreaProps {
  children: React.ReactNode
  /** Classes for the scrolling inner element (layout of the content itself). */
  className?: string
  /** Classes for the non-scrolling outer wrapper — put background/border/padding/rounding here. */
  wrapperClassName?: string
  /** CSS color the edge fade blends into — should match this area's own background. */
  fadeColor: string
  thumbColor?: string
  /** Positioning classes for the pill indicator (default: "top-2 right-3"). */
  thumbPositionClassName?: string
}

// Shared "custom scrollbar" treatment: hides the native scrollbar, fades the
// edge into the surrounding background instead of hard-clipping content, and
// shows a small pill indicator (top-right) tracking scroll position — used
// anywhere content scrolls horizontally, so every instance looks the same.
export function HorizontalScrollArea({
  children,
  className,
  wrapperClassName,
  fadeColor,
  thumbColor = "var(--orange)",
  thumbPositionClassName = "top-2 right-3",
}: HorizontalScrollAreaProps) {
  const scrollRef = useRef<HTMLDivElement>(null)
  const [state, setState] = useState({
    ratio: 0,
    thumbRatio: 1,
    canScrollLeft: false,
    canScrollRight: false,
  })

  const frameRef = useRef<number | null>(null)

  const update = useCallback(() => {
    const el = scrollRef.current
    if (!el) return
    const maxScroll = el.scrollWidth - el.clientWidth
    const thumbRatio = el.scrollWidth > 0 ? el.clientWidth / el.scrollWidth : 1
    const ratio = maxScroll > 0 ? el.scrollLeft / maxScroll : 0
    setState({
      ratio,
      thumbRatio,
      canScrollLeft: el.scrollLeft > 1,
      canScrollRight: el.scrollLeft < maxScroll - 1,
    })
  }, [])

  // Scroll fires far more often than the display refreshes; without this the
  // thumb re-rendered several times per painted frame for no visible gain.
  const scheduleUpdate = useCallback(() => {
    if (frameRef.current !== null) return
    frameRef.current = requestAnimationFrame(() => {
      frameRef.current = null
      update()
    })
  }, [update])

  useEffect(() => {
    update()
    window.addEventListener("resize", scheduleUpdate)
    return () => {
      window.removeEventListener("resize", scheduleUpdate)
      if (frameRef.current !== null) cancelAnimationFrame(frameRef.current)
    }
  }, [update, scheduleUpdate])

  const thumbWidth = Math.max(10, TRACK_WIDTH * state.thumbRatio)
  const thumbLeft = (TRACK_WIDTH - thumbWidth) * state.ratio

  return (
    <div className={cn("relative", wrapperClassName)}>
      <div
        className={cn(
          "pointer-events-none absolute inset-y-0 left-0 z-10 w-10 transition-opacity duration-200 ease-(--ease-standard)",
          state.canScrollLeft ? "opacity-100" : "opacity-0",
        )}
        style={{ background: `linear-gradient(to right, ${fadeColor}, transparent)` }}
      />
      <div
        className={cn(
          "pointer-events-none absolute inset-y-0 right-0 z-10 w-10 transition-opacity duration-200 ease-(--ease-standard)",
          state.canScrollRight ? "opacity-100" : "opacity-0",
        )}
        style={{ background: `linear-gradient(to left, ${fadeColor}, transparent)` }}
      />
      {state.thumbRatio < 1 && (
        <div
          className={cn(
            "pointer-events-none absolute z-20 h-1 overflow-hidden rounded-full bg-foreground/15",
            thumbPositionClassName
          )}
          style={{ width: TRACK_WIDTH }}
        >
          <div
            className="h-full rounded-full"
            style={{ width: thumbWidth, transform: `translateX(${thumbLeft}px)`, background: thumbColor }}
          />
        </div>
      )}
      <div ref={scrollRef} onScroll={scheduleUpdate} className={cn("no-scrollbar overflow-x-auto", className)}>
        {children}
      </div>
    </div>
  )
}
