"use client"

import Link from "next/link"
import { useCallback, useEffect, useRef, useState } from "react"
import {
  ArrowUpRightIcon,
  BarChart3Icon,
  FileCheck2Icon,
  ScanSearchIcon,
  SearchIcon,
  ShieldCheckIcon,
} from "lucide-react"

import { cn } from "@/lib/utils"
import { MobileSheet } from "@/components/ui/mobile-sheet"
import { pressProps } from "@/components/verifier/sheen"

const STEPS = [
  {
    num: "01",
    title: "Detect",
    desc: "Input is classified by type — card number, amount, invoice, or identifier.",
    icon: SearchIcon,
  },
  {
    num: "02",
    title: "Verify",
    desc: "Structural, mathematical, and format checks are applied.",
    icon: ShieldCheckIcon,
  },
  {
    num: "03",
    title: "Analyze",
    desc: "Statistical tests (Benford, chi-square) and risk scoring are run.",
    icon: BarChart3Icon,
  },
  {
    num: "04",
    title: "Report",
    desc: "A clear verdict with supporting evidence and confidence scores.",
    icon: FileCheck2Icon,
  },
]

/** Hover intent. A pointer crossing the brand on its way somewhere else should
 *  not summon a panel, so the open waits for the pointer to settle. */
const OPEN_DELAY_MS = 110
/** Grace on the way out. The panel sits below the trigger with a gap between
 *  them, and a pointer travelling into it necessarily leaves the trigger first —
 *  closing on that frame makes the panel impossible to reach. */
const CLOSE_DELAY_MS = 260

/**
 * The pipeline summary, hung off the brand mark.
 *
 * This used to be a "How it works" button under the input card, which spent a
 * permanent slot in the primary flow on something nobody needs while they are
 * mid-task. Hanging it on the wordmark costs no layout at all and puts it where
 * curiosity actually starts.
 *
 * Hover is the primary gesture but never the only one: the trigger is a real
 * button, so it opens on keyboard focus and toggles on tap, which is what makes
 * the content reachable on a phone and to a screen reader. A hover-only
 * disclosure would simply not exist for either.
 */
export function BrandPopover({ children }: { children: React.ReactNode }) {
  const [open, setOpen] = useState(false)
  /** Set once a tap has opened it, so a subsequent pointerleave — which touch
   *  devices synthesise — does not immediately close what the user just asked
   *  for. Cleared on close. */
  const pinnedRef = useRef(false)
  const openTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const closeTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const rootRef = useRef<HTMLDivElement>(null)
  const triggerRef = useRef<HTMLButtonElement>(null)

  const clearTimers = useCallback(() => {
    if (openTimer.current) clearTimeout(openTimer.current)
    if (closeTimer.current) clearTimeout(closeTimer.current)
    openTimer.current = null
    closeTimer.current = null
  }, [])

  const scheduleOpen = useCallback(() => {
    clearTimers()
    openTimer.current = setTimeout(() => setOpen(true), OPEN_DELAY_MS)
  }, [clearTimers])

  const scheduleClose = useCallback(() => {
    if (pinnedRef.current) return
    clearTimers()
    closeTimer.current = setTimeout(() => setOpen(false), CLOSE_DELAY_MS)
  }, [clearTimers])

  const closeNow = useCallback(() => {
    clearTimers()
    pinnedRef.current = false
    setOpen(false)
  }, [clearTimers])

  useEffect(() => clearTimers, [clearTimers])

  // Escape closes and returns focus, and a click anywhere outside dismisses a
  // panel that was pinned open by tapping.
  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return
      closeNow()
      triggerRef.current?.focus()
    }
    const onDown = (e: MouseEvent) => {
      if (!rootRef.current?.contains(e.target as Node)) closeNow()
    }
    document.addEventListener("keydown", onKey)
    document.addEventListener("mousedown", onDown)
    return () => {
      document.removeEventListener("keydown", onKey)
      document.removeEventListener("mousedown", onDown)
    }
  }, [open, closeNow])

  return (
    <div
      ref={rootRef}
      className="relative"
      onPointerEnter={(e) => {
        // Touch synthesises a pointerenter immediately before the tap; letting
        // it schedule an open would race the toggle below.
        if (e.pointerType === "touch") return
        scheduleOpen()
      }}
      onPointerLeave={(e) => {
        if (e.pointerType === "touch") return
        scheduleClose()
      }}
    >
      <button
        ref={triggerRef}
        type="button"
        aria-expanded={open}
        aria-haspopup="dialog"
        onClick={() => {
          pinnedRef.current = !open
          clearTimers()
          setOpen((v) => !v)
        }}
        // Keyboard focus only. A tap on Android focuses the button on
        // pointerdown and clicks it on pointerup, so this used to open the
        // panel and the toggle below immediately closed it again — the one
        // menu in the app did nothing at all when tapped. :focus-visible is
        // exactly the "arrived here by keyboard" test this always wanted.
        onFocus={(e) => {
          if (e.currentTarget.matches(":focus-visible")) setOpen(true)
        }}
        onBlur={(e) => {
          // Focus moving into the panel itself is not focus leaving the group.
          if (rootRef.current?.contains(e.relatedTarget as Node)) return
          closeNow()
        }}
        {...pressProps}
        className={cn(
          "group/brand -mx-2 -my-1 flex cursor-pointer items-center gap-2.5 rounded-xl px-2 py-1",
          "outline-none transition-colors duration-(--dur-press) ease-(--ease-standard)",
          "hover:bg-foreground/[0.045] focus-visible:ring-orange/35 focus-visible:ring-3",
          // The wordmark is the only way into the one menu this app has, and at
          // 30px tall it was well under the 44pt floor — on a phone it read as
          // a logo rather than a control, which is exactly how it behaved.
          "row-press max-sm:min-h-11 max-sm:py-2",
          open && "bg-foreground/[0.045]",
        )}
      >
        {children}
        {/* A chevron would read as a menu. This is a hairline that grows under
            the wordmark on hover — the same "there is more here" signal, made
            out of the underline the wordmark already implies. */}
        <span
          aria-hidden="true"
          className={cn(
            "bg-orange-ink/60 absolute bottom-0 left-2 h-px origin-left rounded-full",
            "transition-[transform,opacity] duration-[420ms] ease-(--ease-rise) motion-reduce:transition-none",
            open ? "scale-x-100 opacity-100" : "scale-x-0 opacity-0",
          )}
          style={{ width: "calc(100% - 1rem)" }}
        />
      </button>

      {/* The panel. Everything about how it moves lives in `.brand-panel` in
          globals.css — it materialises, animating blur radius, scale and opacity
          together on a sampled spring, scaling out of the wordmark's top-left
          corner rather than its own centre.

          It is always mounted, never conditionally rendered. A panel that
          unmounts cannot animate out — and more importantly, CSS transitions
          interrupt from the current *computed* value, so sweeping the pointer
          back mid-open reverses it smoothly from wherever it had got to instead
          of snapping to the end and restarting (§3). */}
      <div
        role="dialog"
        aria-label="How it works"
        aria-hidden={!open}
        inert={!open}
        onPointerEnter={() => clearTimers()}
        onPointerLeave={(e) => {
          if (e.pointerType === "touch") return
          scheduleClose()
        }}
        data-open={open}
        className="brand-panel absolute top-full left-0 z-50 mt-2.5 w-[330px] rounded-2xl p-4 max-sm:hidden"
      >
        <div className="mb-3 flex items-center gap-2">
          <span className="bg-orange/12 flex size-5 items-center justify-center rounded">
            <ScanSearchIcon className="text-orange-ink size-3" />
          </span>
          <span className="text-caption text-foreground font-semibold">How it works</span>
        </div>

        <div className="flex flex-col gap-3">
          {STEPS.map((step, i) => (
            <div
              key={step.num}
              className={cn(
                "flex items-start gap-2.5",
                // Each row eases in behind the panel itself, so the content
                // settles a beat after the surface rather than arriving with it
                // fully formed. Driven by the panel's open state rather than an
                // animation, so reversing mid-flight reverses this too.
                "transition-[opacity,transform] motion-reduce:transition-none",
                open
                  ? "translate-y-0 opacity-100 ease-(--ease-rise) duration-[420ms]"
                  : "translate-y-1 opacity-0 duration-[120ms] ease-(--ease-exit)",
              )}
              style={{ transitionDelay: open ? `${110 + i * 42}ms` : "0ms" }}
            >
              <div className="flex shrink-0 flex-col items-center self-stretch">
                <span className="text-mini text-orange-ink/60 font-mono font-bold tracking-wider">
                  {step.num}
                </span>
                {i < STEPS.length - 1 && (
                  <span className="bg-hairline/70 mt-1 h-full min-h-[18px] w-px" />
                )}
              </div>
              <div className="-mt-0.5 flex-1">
                <div className="mb-0.5 flex items-center gap-1.5">
                  <step.icon className="text-muted-foreground/50 size-3" />
                  <span className="text-mini text-foreground font-semibold">{step.title}</span>
                </div>
                <p className="text-mini text-muted-foreground leading-[1.5]">{step.desc}</p>
              </div>
            </div>
          ))}
        </div>

        <div className="border-hairline/50 mt-3 border-t pt-3">
          <Link
            href="/how-it-works"
            onClick={() => {
              // Closing here would set inert on this subtree before the link's
              // default navigation runs — React flushes discrete events
              // synchronously, and a browser suppresses the default navigation
              // of a link that has just gone inert, so the click would do
              // nothing. Defer the close by a frame so the navigation goes first.
              requestAnimationFrame(closeNow)
            }}
            className="group/link text-orange-ink/85 hover:text-orange-ink text-mini inline-flex items-center gap-1 font-medium transition-colors"
          >
            <span>Read the full methodology</span>
            <ArrowUpRightIcon className="size-3 transition-transform group-hover/link:translate-x-px group-hover/link:-translate-y-px" />
          </Link>
        </div>
      </div>

      {/* The same content as a sheet, below 640px.

          A popover hanging off a fixed header is a cursor pattern: it is
          dismissed by moving the pointer somewhere else, and it assumes the
          trigger is near where the user is already looking. On a phone the
          trigger is in the top bar, the hand is at the bottom, and this
          particular panel ran past half the screen anyway.

          `open` is shared with the panel above rather than duplicated, so the
          trigger has one state and one meaning at every width; only the surface
          that state drives changes. Above 640px the sheet is display:none and
          never participates in anything. */}
      <MobileSheet open={open} onClose={closeNow} label="How it works">
        <div className="px-5 pb-2">
          <div className="mb-1 flex items-center gap-2.5">
            <span className="bg-orange/12 flex size-7 items-center justify-center rounded-lg">
              <ScanSearchIcon className="text-orange-ink size-4" />
            </span>
            <h2 className="text-callout text-foreground font-semibold">How it works</h2>
          </div>
          <p className="text-footnote text-muted-foreground mt-2 leading-[1.55]">
            Four stages, from whatever you hand it to a verdict you can check.
          </p>

          <ol className="mt-5 flex flex-col">
            {STEPS.map((step, i) => (
              <li key={step.num} className="flex items-start gap-3.5">
                <div className="flex shrink-0 flex-col items-center self-stretch">
                  <span className="bg-orange/10 ring-orange/20 text-orange-ink flex size-8 items-center justify-center rounded-full font-mono text-mini font-bold ring-1 ring-inset">
                    {step.num}
                  </span>
                  {/* The spine is what makes four rows read as one sequence
                      rather than four cards. It stops at the last step, so the
                      list has an end rather than trailing off. */}
                  {i < STEPS.length - 1 && (
                    <span className="bg-hairline/80 my-1 w-px flex-1" />
                  )}
                </div>
                <div className="flex-1 pb-5">
                  <div className="flex items-center gap-1.5">
                    <step.icon className="text-muted-foreground/60 size-3.5" />
                    <span className="text-footnote text-foreground font-semibold">
                      {step.title}
                    </span>
                  </div>
                  <p className="text-caption text-muted-foreground mt-1 leading-[1.6]">
                    {step.desc}
                  </p>
                </div>
              </li>
            ))}
          </ol>

          {/* A full-width row, not a text link. The methodology page is the one
              place this sheet can send someone, and a 12px inline link is not a
              destination on a touch screen. */}
          <Link
            href="/how-it-works"
            onClick={() => {
              // Same deferred close as the popover's own link: closing here
              // sets inert on the sheet before the browser runs the link's
              // default navigation, which suppresses it — the one way out of
              // this sheet would do nothing. Navigate first, close a frame later.
              requestAnimationFrame(closeNow)
            }}
            {...pressProps}
            className="row-press border-hairline/70 bg-surface-inset text-footnote text-foreground mt-1 flex min-h-13 items-center justify-between gap-3 rounded-2xl border px-4 font-medium"
          >
            <span>Read the full methodology</span>
            <ArrowUpRightIcon className="text-orange-ink size-4 shrink-0" />
          </Link>
        </div>
      </MobileSheet>
    </div>
  )
}
