"use client"

import type { LucideIcon } from "lucide-react"

import { cn } from "@/lib/utils"
import { pressProps } from "@/components/verifier/sheen"

/* ─── Segmented control ───────────────────────────────────────────────────────
   Mobile only — every rule it depends on lives inside `@media (width < 40rem)`
   in globals.css, and the shells that render it are hidden above that width.

   Tabs rather than a radio group in the markup, because that is what this is:
   one visible panel at a time, and the arrow keys should move between the
   options the way they do in every other tab strip a user has met (§16,
   familiarity).
   -------------------------------------------------------------------------- */

export interface SegmentOption<T extends string> {
  value: T
  label: string
  icon: LucideIcon
}

interface SegmentedProps<T extends string> {
  options: SegmentOption<T>[]
  value: T
  onChange: (value: T) => void
  /** Ties each tab to the panel it reveals. */
  idPrefix: string
  "aria-label": string
  className?: string
}

export function Segmented<T extends string>({
  options,
  value,
  onChange,
  idPrefix,
  className,
  ...rest
}: SegmentedProps<T>) {
  const index = Math.max(
    0,
    options.findIndex((o) => o.value === value),
  )

  function onKeyDown(e: React.KeyboardEvent<HTMLDivElement>) {
    const delta = e.key === "ArrowRight" ? 1 : e.key === "ArrowLeft" ? -1 : 0
    if (delta === 0) return
    e.preventDefault()
    // Wraps, so the strip has no dead ends.
    const next = (index + delta + options.length) % options.length
    onChange(options[next].value)
  }

  return (
    <div
      role="tablist"
      aria-label={rest["aria-label"]}
      onKeyDown={onKeyDown}
      className={cn("seg", className)}
      style={{
        // The thumb sizes and travels from these two numbers alone, so adding
        // or removing an option needs no change to the CSS.
        ["--seg-n" as string]: options.length,
        ["--seg-i" as string]: index,
      }}
    >
      {/* One element that slides, rather than three backgrounds taking turns.
          That is what makes the change read as a single object travelling — and
          it is what lets the motion carry a spring. */}
      <span className="seg-thumb" aria-hidden="true" />
      {options.map((option) => {
        const selected = option.value === value
        return (
          <button
            key={option.value}
            type="button"
            role="tab"
            id={`${idPrefix}-tab-${option.value}`}
            aria-selected={selected}
            aria-controls={`${idPrefix}-panel-${option.value}`}
            // Only the selected tab is in the tab order; the arrow keys move
            // within the strip. Standard tablist behaviour, and it stops a
            // three-option control costing three tab stops.
            tabIndex={selected ? 0 : -1}
            onClick={() => onChange(option.value)}
            {...pressProps}
            className="seg-item text-footnote font-semibold outline-none focus-visible:ring-2 focus-visible:ring-orange/40"
          >
            <option.icon className={cn("size-4", selected ? "text-orange-ink" : "opacity-70")} />
            <span>{option.label}</span>
          </button>
        )
      })}
    </div>
  )
}
