/**
 * The field the whole app sits on: slow warm and cool auroras, a mesh of dots,
 * a scatter of drifting Benford digits, and a film of grain over the top.
 *
 * Not a client component. Nothing here reacts to state, and every value below
 * is a literal — so it renders once on the server and ships no JavaScript at
 * all. Which also settles the hydration question the obvious implementation
 * raises: positions come from the table below rather than Math.random(), so the
 * server and the client cannot disagree about where a digit is.
 *
 * All of the visual tuning lives in globals.css under `.ambient`, including why
 * the alphas are as low as they are and why nothing here loops faster than
 * roughly 0.02Hz.
 */

/**
 * Benford's Law applied to its own wallpaper.
 *
 * The digits are not evenly distributed: 1 appears four times, 2 three times,
 * and the tail thins out exactly as log10(1 + 1/d) says it should. Someone who
 * counts them finds the thesis of the project written into the background — and
 * someone who does not still reads a field that happens to feel right, because
 * the low digits are the ones carrying the visual weight.
 *
 * `delay` is negative on purpose: the animation starts mid-cycle, so the field
 * is already populated on first paint instead of filling in over the first
 * minute while the user watches an empty page.
 */
const DIGITS: {
  d: number
  left: string
  top: string
  size: number
  dur: number
  delay: number
}[] = [
  { d: 1, left: '6%', top: '68%', size: 64, dur: 78, delay: -4 },
  { d: 1, left: '82%', top: '74%', size: 46, dur: 66, delay: -31 },
  { d: 1, left: '38%', top: '88%', size: 34, dur: 92, delay: -58 },
  { d: 1, left: '68%', top: '52%', size: 28, dur: 71, delay: -12 },
  { d: 2, left: '19%', top: '80%', size: 40, dur: 84, delay: -47 },
  { d: 2, left: '91%', top: '44%', size: 30, dur: 63, delay: -22 },
  { d: 2, left: '52%', top: '70%', size: 52, dur: 96, delay: -70 },
  { d: 3, left: '29%', top: '58%', size: 26, dur: 74, delay: -39 },
  { d: 3, left: '74%', top: '86%', size: 38, dur: 88, delay: -8 },
  { d: 4, left: '12%', top: '40%', size: 30, dur: 69, delay: -55 },
  { d: 4, left: '60%', top: '92%', size: 24, dur: 81, delay: -27 },
  { d: 5, left: '45%', top: '36%', size: 22, dur: 76, delay: -63 },
  { d: 7, left: '86%', top: '62%', size: 26, dur: 90, delay: -17 },
  { d: 9, left: '24%', top: '94%', size: 20, dur: 72, delay: -44 },
]

export function AmbientBackground() {
  return (
    <div className="ambient" aria-hidden="true">
      <div className="ambient-blob ambient-blob-a" />
      <div className="ambient-blob ambient-blob-b" />
      <div className="ambient-blob ambient-blob-c" />
      <div className="ambient-mesh" />
      {DIGITS.map((g, i) => (
        <span
          key={i}
          className="ambient-digit"
          style={{
            left: g.left,
            top: g.top,
            fontSize: g.size,
            // Consumed by the .ambient-digit rule, so the timing of a single
            // glyph is data here and the motion itself stays in CSS.
            ['--amb-dur' as string]: `${g.dur}s`,
            ['--amb-delay' as string]: `${g.delay}s`,
          }}
        >
          {g.d}
        </span>
      ))}
      <div className="ambient-grain" />
    </div>
  )
}
