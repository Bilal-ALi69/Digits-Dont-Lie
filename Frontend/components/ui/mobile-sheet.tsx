"use client"

import { useCallback, useEffect, useRef, useState } from "react"
import { createPortal } from "react-dom"

import { cn } from "@/lib/utils"

/* ─── Bottom sheet ────────────────────────────────────────────────────────────
   A dropdown is a cursor pattern. It hangs off a trigger, it is dismissed by
   moving the pointer somewhere else, and it assumes the trigger is near where
   the user is already looking. None of that holds on a phone: the trigger is in
   the top bar, the hand is at the bottom, and there is no "somewhere else" to
   move to without tapping something.

   So on a phone the same content arrives as a sheet from the bottom edge, and
   the interesting part is that it can be *thrown away* — the surface tracks the
   finger one-to-one, resists at the top, and on release continues at the speed
   it was already moving rather than restarting from rest.

   Only the grip drags. The body scrolls. Separating them is what stops the two
   gestures from having to be disambiguated, which is a delay nobody notices
   being removed and everybody notices being present (§10).
   -------------------------------------------------------------------------- */

/** Apple's momentum projection, from the *Designing Fluid Interfaces* sample.
 *  Where the sheet would come to rest if it kept decelerating from here — which
 *  is what decides dismiss-or-return, rather than where the finger happened to
 *  stop. A short fast flick and a long slow drag should not mean the same
 *  thing, and comparing raw distances says they do. */
function project(velocity: number, decelerationRate = 0.998): number {
  return ((velocity / 1000) * decelerationRate) / (1 - decelerationRate)
}

/** Progressive resistance past the top edge. A hard stop reads as frozen; the
 *  surface slowing the further it is pulled reads as responsive with nothing
 *  more to give (§9). */
function rubberband(overshoot: number, dimension: number, constant = 0.55): number {
  return (overshoot * dimension * constant) / (dimension + constant * Math.abs(overshoot))
}

function clamp(v: number, lo: number, hi: number): number {
  return Math.min(hi, Math.max(lo, v))
}

/** Past this share of its own height — as *projected*, not as dragged — the
 *  sheet is going away. */
const DISMISS_FRACTION = 0.38
/** …or past this speed downward, however short the drag was. A flick is an
 *  intention, and waiting for it to also cover distance ignores that. */
const DISMISS_VELOCITY = 520

interface MobileSheetProps {
  open: boolean
  onClose: () => void
  /** Names the dialog for assistive technology. */
  label: string
  children: React.ReactNode
  className?: string
}

export function MobileSheet({ open, onClose, label, children, className }: MobileSheetProps) {
  const sheetRef = useRef<HTMLDivElement>(null)
  const scrimRef = useRef<HTMLDivElement>(null)
  // Portalled to <body>, so the sheet is not trapped in the stacking context of
  // whatever opened it. The trigger for this one lives inside a z-40 header, and
  // both the pinned action bar (z-45) and the offline banner (z-50) would have
  // painted straight over the top of it.
  const [mounted, setMounted] = useState(false)
  useEffect(() => setMounted(true), [])
  // Live gesture state. Refs rather than state throughout: a pointermove that
  // re-rendered would put React between the finger and the surface, and the
  // whole point of the gesture is that there is nothing in between.
  const dragRef = useRef<{
    active: boolean
    startY: number
    height: number
    // The last few samples, for velocity at release. One sample is the
    // instantaneous jitter of a single frame, not the speed of the gesture.
    history: { y: number; t: number }[]
  } | null>(null)

  /** Writes the surface's position and the scrim's dim from one number, so the
   *  background lightening and the sheet descending cannot drift apart. */
  const paint = useCallback((y: number, height: number) => {
    sheetRef.current?.style.setProperty("--sheet-y", `${y}px`)
    scrimRef.current?.style.setProperty(
      "--scrim-o",
      `${clamp(1 - y / Math.max(1, height), 0, 1)}`,
    )
  }, [])

  const reset = useCallback(() => {
    const el = sheetRef.current
    if (!el) return
    el.style.transition = ""
    el.dataset.dragging = "false"
    el.style.setProperty("--sheet-y", "0px")
    scrimRef.current?.style.setProperty("--scrim-o", "1")
  }, [])

  // Whatever position a previous dismissal left behind must be cleared before
  // the next open, or the sheet animates in to wherever it was thrown.
  useEffect(() => {
    if (open) reset()
  }, [open, reset])

  // Escape closes, and while the sheet is up the page behind it does not
  // scroll. Both are gated on the viewport actually being a phone: the sheet is
  // display:none above 640px, and locking a scroll for an invisible surface
  // would strand a desktop user on a page that no longer moves.
  useEffect(() => {
    if (!open) return
    if (!window.matchMedia("(width < 40rem)").matches) return

    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose()
    }
    document.addEventListener("keydown", onKey)

    // overflow alone. `touch-action: none` on <body> was the first attempt and
    // is wrong: touch-action is resolved by walking up from the touch target and
    // intersecting what it finds, and this sheet is portalled *into* body — so
    // the lock meant to hold the page still would also have stopped the sheet's
    // own content from scrolling. The grip carries its own `touch-action: none`,
    // and .sheet-body carries `overscroll-behavior: contain`, which is what
    // actually stops a flick inside the sheet reaching the page.
    const { overflow } = document.body.style
    document.body.style.overflow = "hidden"
    return () => {
      document.removeEventListener("keydown", onKey)
      document.body.style.overflow = overflow
    }
  }, [open, onClose])

  function onPointerDown(e: React.PointerEvent<HTMLDivElement>) {
    const el = sheetRef.current
    if (!el) return
    // Capture, so the drag survives the finger leaving the grip — which it
    // does immediately, because the grip is 30px tall and the gesture is not.
    e.currentTarget.setPointerCapture(e.pointerId)
    el.dataset.dragging = "true"
    el.style.transition = ""
    dragRef.current = {
      active: true,
      startY: e.clientY,
      height: el.offsetHeight,
      history: [{ y: e.clientY, t: e.timeStamp }],
    }
  }

  function onPointerMove(e: React.PointerEvent<HTMLDivElement>) {
    const d = dragRef.current
    if (!d?.active) return
    const raw = e.clientY - d.startY
    // Down follows the finger exactly. Up resists, and increasingly.
    const y = raw >= 0 ? raw : -rubberband(-raw, d.height)
    paint(y, d.height)
    d.history.push({ y: e.clientY, t: e.timeStamp })
    if (d.history.length > 6) d.history.shift()
  }

  function onPointerUp(e: React.PointerEvent<HTMLDivElement>) {
    const el = sheetRef.current
    const d = dragRef.current
    if (!el || !d?.active) return
    d.active = false

    const dy = Math.max(0, e.clientY - d.startY)
    // Velocity over the sampled window rather than the last frame.
    const first = d.history[0]
    const last = d.history[d.history.length - 1]
    const dt = Math.max(1, last.t - first.t)
    const velocity = ((last.y - first.y) / dt) * 1000 // px/s, positive = downward

    el.dataset.dragging = "false"

    const projected = dy + project(velocity)
    if (projected > d.height * DISMISS_FRACTION || velocity > DISMISS_VELOCITY) {
      // Continue at the speed the finger was already moving, so there is no
      // seam between the drag and the animation (§5). A spring library would
      // take the velocity directly; with a CSS transition the equivalent is to
      // derive the duration from it — same arrival speed, one property.
      const remaining = Math.max(1, d.height - dy)
      const ms =
        velocity > 40 ? clamp((remaining / velocity) * 1000, 130, 320) : 260
      el.style.transition = `transform ${ms}ms var(--ease-exit)`
      paint(d.height, d.height)
      window.setTimeout(() => {
        onClose()
        reset()
      }, ms)
    } else {
      // Returning home is a spring, not a retreat: --spring-pop is what
      // .sheet already carries, so clearing the inline override restores it.
      el.style.transition = ""
      paint(0, d.height)
    }
  }

  if (!mounted) return null

  return createPortal(
    <>
      <div
        ref={scrimRef}
        className="sheet-scrim"
        data-open={open}
        aria-hidden="true"
        onClick={onClose}
      />
      <div
        ref={sheetRef}
        role="dialog"
        aria-modal="true"
        aria-label={label}
        aria-hidden={!open}
        inert={!open}
        data-open={open}
        className={cn("sheet", className)}
      >
        <div
          className="sheet-grip"
          onPointerDown={onPointerDown}
          onPointerMove={onPointerMove}
          onPointerUp={onPointerUp}
          onPointerCancel={onPointerUp}
          aria-hidden="true"
        />
        <div className="sheet-body">{children}</div>
      </div>
    </>,
    document.body,
  )
}
