"use client"

import { useEffect, useRef, useState } from "react"

interface ConfidenceRingProps {
  value: number // 0-100
  label: string
}

type Stop = { at: number; rgb: [number, number, number] }

/* ─── Colour ramps ───────────────────────────────────────────────────────────
   Two of them, because a single ramp cannot serve both themes.

   The dark ramp is iOS's system colours, which are tuned to glow on near-black.
   Read as a 12px stroke on a *white* card they collapse: systemGreen (#32D74B)
   measures 1.6:1 against white and systemYellow (#FFD60A) 1.2:1 — under a
   projector, which lifts blacks and blooms highlights, the arc simply is not
   there for the first half of its travel. The green-to-red journey, which is
   the entire point of the control, was invisible in the room it was going to
   be shown in.

   The light ramp keeps the same green -> yellow -> orange -> red story and the
   same stop positions, so the reading does not change between themes; only the
   luminance does. Every stop clears 3:1 against #FFFFFF — the threshold for a
   graphical object rather than the 4.5:1 needed for text, which is the right
   bar for a stroke this heavy.
   -------------------------------------------------------------------------- */
const DARK_STOPS: Stop[] = [
  { at: 0, rgb: [50, 215, 75] }, // #32D74B green
  { at: 20, rgb: [50, 215, 75] },
  { at: 40, rgb: [255, 214, 10] }, // #FFD60A yellow
  { at: 60, rgb: [255, 159, 10] }, // #FF9F0A orange
  { at: 80, rgb: [255, 69, 58] }, // #FF453A red
  { at: 100, rgb: [220, 20, 20] },
]

const LIGHT_STOPS: Stop[] = [
  { at: 0, rgb: [15, 122, 56] }, // #0F7A38 — the light theme's --success
  { at: 20, rgb: [15, 122, 56] },
  { at: 40, rgb: [168, 116, 0] }, // #A87400 dark gold, standing in for yellow
  { at: 60, rgb: [194, 94, 0] }, // #C25E00 orange
  { at: 80, rgb: [192, 36, 26] }, // #C0241A — the light theme's --danger
  { at: 100, rgb: [150, 23, 15] },
]

function lerp(a: number, b: number, t: number): number {
  return a + (b - a) * t
}

function dangerValueToRgb(dangerValue: number, stops: Stop[]): [number, number, number] {
  const v = Math.max(0, Math.min(100, dangerValue))
  for (let i = 0; i < stops.length - 1; i++) {
    const from = stops[i]
    const to = stops[i + 1]
    if (v >= from.at && v <= to.at) {
      const t = to.at === from.at ? 0 : (v - from.at) / (to.at - from.at)
      return [
        lerp(from.rgb[0], to.rgb[0], t),
        lerp(from.rgb[1], to.rgb[1], t),
        lerp(from.rgb[2], to.rgb[2], t),
      ]
    }
  }
  return stops[stops.length - 1].rgb
}

function rgbToHex([r, g, b]: [number, number, number]): string {
  const h = (n: number) => Math.round(n).toString(16).padStart(2, "0")
  return `#${h(r)}${h(g)}${h(b)}`
}

/** Which ramp to draw with. Starts undecided rather than guessing: the server
 *  cannot know the theme, and rendering the wrong ramp for a frame would show
 *  the arc changing colour for no reason the user did anything to cause. */
function useIsDark(): boolean {
  const [isDark, setIsDark] = useState(true)

  useEffect(() => {
    const root = document.documentElement
    const read = () => setIsDark(root.classList.contains("dark"))
    read()
    // The theme toggle mutates the class on <html> directly, outside React, so
    // there is no state change here to react to — observe the attribute instead.
    // Without this the ring keeps its old ramp until the next analysis, which
    // during a live demo means toggling the theme leaves it unreadable.
    const mo = new MutationObserver(read)
    mo.observe(root, { attributes: true, attributeFilter: ["class"] })
    return () => mo.disconnect()
  }, [])

  return isDark
}

export function ConfidenceRing({ value, label }: ConfidenceRingProps) {
  const [display, setDisplay] = useState(0)
  const rafRef = useRef<number | null>(null)
  const isDark = useIsDark()

  useEffect(() => {
    const start = performance.now()
    // Linear, and slow enough that the green -> yellow -> orange -> red
    // ramp is actually visible as it fills, instead of an ease-out curve
    // that covers most of the distance in the first ~150ms and leaves the
    // ring sitting near its final color for the rest of the animation.
    const duration = 1600
    const from = 0
    const to = value

    const tick = (now: number) => {
      const t = Math.min(1, (now - start) / duration)
      setDisplay(Math.round(from + (to - from) * t))
      if (t < 1) rafRef.current = requestAnimationFrame(tick)
    }
    rafRef.current = requestAnimationFrame(tick)
    return () => {
      if (rafRef.current) cancelAnimationFrame(rafRef.current)
    }
  }, [value])

  const size = 180
  const stroke = 12
  const radius = (size - stroke) / 2
  const circumference = 2 * Math.PI * radius
  const offset = circumference - (display / 100) * circumference

  // `value` is always risk now, so the ring reads directly: higher is worse.
  // It previously also accepted a confidence figure and inverted internally,
  // which meant the same number could render green or red depending on a label.
  const dangerValue = display
  const rgb = dangerValueToRgb(dangerValue, isDark ? DARK_STOPS : LIGHT_STOPS)
  const color = rgbToHex(rgb)
  // The halo is the arc's own colour at low alpha, so the two cannot drift
  // apart as the figure counts up — one interpolation drives both.
  const halo = `rgba(${rgb.map((c) => Math.round(c)).join(", ")}, ${isDark ? 0.3 : 0.22})`

  return (
    <div className="relative flex size-[180px] items-center justify-center max-sm:size-[148px]">
      {/* Sits behind the svg, so the arc is never drawn through its blur. */}
      <div className="ring-halo" style={{ ["--halo" as string]: halo }} aria-hidden="true" />

      {/* viewBox rather than width/height attributes: the drawing keeps its
          180-unit coordinate space and the box scales it, so nothing about the
          geometry below has to know the rendered size. */}
      <svg viewBox={`0 0 ${size} ${size}`} className="relative size-full -rotate-90" aria-hidden="true">
        {/* Track. --secondary rather than a hard-coded grey: it was #FFFFFF in
            the light theme and this circle sits on a white card, so the track
            was invisible and the arc floated with nothing to measure against. */}
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          strokeWidth={stroke}
          strokeLinecap="round"
          className="stroke-secondary"
        />
        {/* Ticks at every tenth. They give the arc a scale to be read against —
            without them a 62 and a 71 look the same — and they are what makes
            the control read as an instrument rather than a progress bar. */}
        <g className="stroke-hairline-strong" strokeWidth={1.5} strokeLinecap="round">
          {Array.from({ length: 10 }, (_, i) => {
            const angle = (i / 10) * 2 * Math.PI
            const inner = radius - stroke / 2 - 5
            const outer = radius - stroke / 2 - 1.5
            const cx = size / 2
            const cy = size / 2
            return (
              <line
                key={i}
                x1={cx + Math.cos(angle) * inner}
                y1={cy + Math.sin(angle) * inner}
                x2={cx + Math.cos(angle) * outer}
                y2={cy + Math.sin(angle) * outer}
              />
            )
          })}
        </g>
        {/* Filled arc */}
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          strokeWidth={stroke}
          strokeLinecap="round"
          strokeDasharray={circumference}
          strokeDashoffset={offset}
          stroke={color}
        />
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center gap-0.5">
        {/* The figure takes the arc's colour once it has settled. While it is
            counting it stays foreground-coloured, so the number is legible at
            every frame rather than passing through the pale middle of the ramp. */}
        <span
          className="font-mono text-numeral text-foreground font-bold tabular-nums max-sm:text-[2.125rem]"
          style={display >= value ? { color } : undefined}
        >
          {display}
        </span>
        <span className="text-micro text-muted-foreground font-medium tracking-widest uppercase">
          {label}
        </span>
      </div>
    </div>
  )
}
