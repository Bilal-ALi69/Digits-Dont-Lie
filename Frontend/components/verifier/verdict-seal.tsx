import type { Verdict } from "@/lib/verifier"

/* ─── The seal ────────────────────────────────────────────────────────────────
   Hand-drawn SVG rather than a Lucide icon, for one reason: the glyph has to
   draw itself, and drawing needs `pathLength` on the path so a single
   stroke-dasharray works for all three marks. Lucide renders its own internal
   paths and gives no way to set that, so a fading icon was the only option
   there — and a mark that fades in has not been *made*, it has just appeared.

   Everything is expressed in a 100×100 viewBox and scaled by the caller, so the
   stroke weights stay in proportion at any size.
   -------------------------------------------------------------------------- */

/** Stroke paths per verdict. `pathLength={100}` on each means the dash maths in
 *  `.seal-glyph` is identical regardless of the real geometry. */
const GLYPH: Record<Verdict, { d: string; dot?: boolean }> = {
  // A tick, drawn from the short arm through the long one — the direction a
  // hand would make it.
  valid: { d: "M33 51.5 L44.5 63 L68 39" },
  // Two strokes in one path, so they draw in sequence rather than together.
  fraud: { d: "M37 37 L63 63 M63 37 L37 63" },
  // Arc over into the stem; the dot is a separate node because a dot has no
  // length to draw and has to arrive some other way.
  insufficient: { d: "M38 42 a12 12 0 1 1 12 15 v5", dot: true },
}

export function VerdictSeal({ verdict }: { verdict: Verdict }) {
  const glyph = GLYPH[verdict]

  return (
    // Sized by class rather than by a prop, so the phone can have a smaller
    // stamp without the caller having to know the viewport. The 100-unit
    // viewBox below means the strokes scale in proportion either way.
    <div
      className="relative flex size-[104px] shrink-0 items-center justify-center max-sm:size-[86px]"
      aria-hidden="true"
    >
      {/* --seal is set by the caller from the verdict's colour, so the glow,
          the ring and the glyph are all one hue without it being named twice. */}
      <span className="seal-glow" />
      <svg viewBox="0 0 100 100" className="relative size-full" fill="none">
        {/* The face of the stamp */}
        <circle className="seal-disc" cx="50" cy="50" r="39" fill="var(--seal-fill)" />
        {/* The rim, sweeping round. -rotate-90 starts it at twelve o'clock
            rather than at three, so it opens the way a dial does. */}
        <circle
          className="seal-ring origin-center -rotate-90"
          cx="50"
          cy="50"
          r="45"
          pathLength={100}
          stroke="var(--seal-line)"
          strokeWidth="2.5"
          strokeLinecap="round"
        />
        <path
          className="seal-glyph"
          d={glyph.d}
          pathLength={100}
          stroke="var(--seal-ink)"
          strokeWidth="7"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
        {glyph.dot && (
          <circle className="seal-dot" cx="50" cy="72" r="3.8" fill="var(--seal-ink)" />
        )}
      </svg>
    </div>
  )
}
