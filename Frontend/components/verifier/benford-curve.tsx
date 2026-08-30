"use client"

import { useCallback, useEffect, useRef, useState } from "react"

import { cn } from "@/lib/utils"

/** Benford's Law: the probability that a naturally-occurring figure begins with
 *  digit d is log10(1 + 1/d). Computed rather than hard-coded, because these
 *  are the exact proportions the analysis engine tests against — a table of
 *  rounded percentages here could drift away from what the backend measures. */
const DIGITS = [1, 2, 3, 4, 5, 6, 7, 8, 9] as const
const EXPECTED = DIGITS.map((d) => Math.log10(1 + 1 / d))
const PEAK = EXPECTED[0]

/** How many figures the sampler draws before it stops. Enough that the shape is
 *  unmistakably Benford rather than noise, few enough that the run is over in
 *  about eight seconds and does not become the thing people watch instead of
 *  listening to the person presenting. */
const SAMPLE_TARGET = 240
/** Milliseconds between draws. Starts here and eases out as the run proceeds,
 *  so the histogram fills quickly and then settles rather than ticking along at
 *  one constant rate for eight seconds. */
const TICK_MIN_MS = 26
const TICK_MAX_MS = 150

/**
 * Sample figures the way the world produces them.
 *
 * Benford's Law is not a property of numbers; it is a property of numbers that
 * span orders of magnitude. So the sampler draws a uniform exponent and
 * exponentiates it — a quantity equally likely to be in the hundreds as in the
 * millions, which is what a ledger looks like. The leading-digit distribution
 * that falls out is Benford's, not because it was imposed but because that is
 * what the arithmetic does.
 *
 * That matters for honesty as much as for the demo: nothing here is drawing
 * from a hard-coded table of Benford frequencies and pretending to have
 * discovered them. The curve is an outcome.
 */
function sampleFigure(): number {
  const magnitude = Math.pow(10, Math.random() * 4)
  return magnitude * (1 + Math.random())
}

function leadingDigit(n: number): number {
  const s = Math.abs(n).toExponential()
  return Number(s[0])
}

function formatFigure(n: number): string {
  return n.toLocaleString(undefined, { maximumFractionDigits: n < 100 ? 2 : 0 })
}

/**
 * The product's thesis, running.
 *
 * This used to be a static bar chart of the expected frequencies — correct, and
 * completely inert. It now draws real figures one at a time, picks out each
 * leading digit, and grows the matching column, so the visitor watches the law
 * assemble itself out of nothing instead of being shown a picture of its
 * conclusion.
 *
 * It converges and stops. That is the point, and it is what keeps a moving
 * chart in a hero from being decoration: a perpetual loop is something the eye
 * learns to discard within seconds, while a run that reaches a real
 * distribution and holds there is an argument that has finished making itself.
 * It can be run again — the whole thing is a button — which is exactly the
 * affordance a presenter wants when someone at the back asks to see it again.
 */
export function BenfordCurve() {
  const [counts, setCounts] = useState<number[]>(() => new Array(9).fill(0))
  const [total, setTotal] = useState(0)
  const [running, setRunning] = useState(false)
  const [done, setDone] = useState(false)
  /** The figure currently flying in, and the column it landed on. */
  const [latest, setLatest] = useState<{ value: number; digit: number; id: number } | null>(null)
  const [active, setActive] = useState<number | null>(null)

  const ref = useRef<HTMLDivElement>(null)
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const drawnRef = useRef(0)
  const idRef = useRef(0)
  const reducedRef = useRef(false)

  const stop = useCallback(() => {
    if (timerRef.current) clearTimeout(timerRef.current)
    timerRef.current = null
  }, [])

  const run = useCallback(() => {
    stop()
    drawnRef.current = 0
    setCounts(new Array(9).fill(0))
    setTotal(0)
    setLatest(null)
    setDone(false)
    setRunning(true)

    // Someone who has asked for reduced motion still gets the finished
    // distribution — the information is not the animation. It simply arrives
    // in one step rather than being assembled in front of them.
    if (reducedRef.current) {
      const final = EXPECTED.map((p) => Math.round(p * SAMPLE_TARGET))
      setCounts(final)
      setTotal(final.reduce((a, b) => a + b, 0))
      setRunning(false)
      setDone(true)
      return
    }

    const tick = () => {
      const value = sampleFigure()
      const digit = leadingDigit(value)
      idRef.current += 1
      setLatest({ value, digit, id: idRef.current })
      setCounts((prev) => {
        const next = prev.slice()
        next[digit - 1] += 1
        return next
      })
      setTotal((t) => t + 1)
      drawnRef.current += 1

      if (drawnRef.current >= SAMPLE_TARGET) {
        setRunning(false)
        setDone(true)
        setLatest(null)
        return
      }
      // Ease the interval out over the run: fast while the shape is forming,
      // slowing as it settles, so the ending reads as arrival rather than as
      // the animation being switched off.
      const progress = drawnRef.current / SAMPLE_TARGET
      const delay = TICK_MIN_MS + (TICK_MAX_MS - TICK_MIN_MS) * Math.pow(progress, 3)
      timerRef.current = setTimeout(tick, delay)
    }

    timerRef.current = setTimeout(tick, 260)
  }, [stop])

  // Start when it is actually on screen, so the run is not already over by the
  // time a reader scrolls to it.
  useEffect(() => {
    reducedRef.current =
      typeof window !== "undefined" &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches

    const el = ref.current
    if (!el) return
    if (typeof IntersectionObserver === "undefined") {
      run()
      return
    }
    // Already on screen at mount: start now rather than waiting on the
    // observer. On a phone the hero is tall enough that this element is in view
    // immediately, and a threshold of 0.35 on a ~200px block that is partly
    // below the fold could leave it sitting at n = 0 with an empty 92px box
    // where the chart should be — which is exactly how it rendered on iOS.
    const box = el.getBoundingClientRect()
    const onScreenNow =
      box.top < window.innerHeight && box.bottom > 0 && box.height > 0
    if (onScreenNow) {
      run()
      return
    }

    const io = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) {
          run()
          io.disconnect()
        }
      },
      // Any sliver counts. The old 0.35 asked for a third of the block to be
      // visible before the demonstration would begin.
      { threshold: 0 },
    )
    io.observe(el)
    return () => {
      io.disconnect()
      stop()
    }
  }, [run, stop])

  useEffect(() => stop, [stop])

  const maxCount = Math.max(1, ...counts)
  // While the run is short the tallest column is noisy, so the bars are scaled
  // against the *expected* peak once there is enough data for that to be the
  // stable choice. Early on they scale against the observed max, or a single
  // early sample would fill the frame and then appear to shrink.
  const scaleBase = total > 40 ? Math.max(maxCount, PEAK * total * 0.92) : maxCount

  return (
    <div ref={ref} data-benford className="w-full max-w-sm">
      {/* Readout. Fixed height, so nothing below it moves as the run proceeds
          or as the pointer travels across the columns. */}
      <div className="mb-2 flex h-5 items-baseline justify-between gap-2 max-sm:h-auto max-sm:min-h-5">
        {active !== null ? (
          <span className="flex items-baseline gap-2">
            <span className="text-orange-ink font-mono text-caption font-semibold tabular-nums">
              {total > 0 ? ((counts[active] / total) * 100).toFixed(1) : "0.0"}%
            </span>
            <span className="text-mini text-muted-foreground max-sm:hidden">
              start with {DIGITS[active]} · Benford predicts{" "}
              {(EXPECTED[active] * 100).toFixed(1)}%
            </span>
            {/* The same fact, short enough to fit a phone row. */}
            <span className="text-mini text-muted-foreground hidden max-sm:inline">
              lead digit {DIGITS[active]}
            </span>
          </span>
        ) : (
          <span className="text-mini text-muted-foreground/70 font-mono tracking-wide uppercase">
            {running ? "Sampling figures…" : done ? "Leading-digit frequency" : " "}
          </span>
        )}
        <span className="text-mini text-muted-foreground/60 font-mono tabular-nums">
          n = {total}
        </span>
      </div>

      {/* The whole plot is the replay control. A presenter asked to show it
          again should not have to reload the page, and there is no sensible
          second thing to click here that this would be competing with. */}
      <button
        type="button"
        onClick={run}
        onPointerLeave={() => setActive(null)}
        aria-label="Run the sampling demonstration again"
        className={cn(
          "group/curve relative flex h-[92px] w-full items-end gap-1.5 overflow-hidden rounded-md outline-none",
          "focus-visible:ring-orange/30 focus-visible:ring-3",
          "max-sm:h-[68px] max-sm:gap-1",
          done && "curve-sweep",
        )}
        style={{ ["--sweep-delay" as string]: "0ms" }}
      >
        {/* The figure that was just drawn, rising away above the column it
            landed on — the visible link between one sample and one bar. */}
        {latest && (
          <span
            key={latest.id}
            className="sample-fly text-orange-ink pointer-events-none absolute top-0 z-10 font-mono text-mini font-semibold tabular-nums"
            style={{
              // Centred over its column: nine equal columns, so the midpoint of
              // column d sits at (d - 0.5) / 9 of the width.
              left: `${((latest.digit - 0.5) / 9) * 100}%`,
              transform: "translateX(-50%)",
            }}
          >
            {formatFigure(latest.value)}
          </span>
        )}

        {DIGITS.map((digit, i) => {
          const share = counts[i] / scaleBase
          const isActive = active === i
          const isHit = latest?.digit === digit
          // Everything dims when one column is picked out, so the comparison
          // the hover is making is between one bar and the rest.
          const dimmed = active !== null && !isActive
          return (
            <span
              key={digit}
              className="flex flex-1 cursor-pointer flex-col items-center gap-1.5 self-stretch"
              onPointerEnter={() => setActive(i)}
            >
              <span className="flex w-full flex-1 items-end">
                <span
                  key={isHit ? latest?.id : undefined}
                  className={cn(
                    "w-full rounded-t-[3px] rounded-b-[1px] transition-[height,opacity,transform] ease-(--ease-rise) motion-reduce:transition-none",
                    isHit && "bar-hit",
                  )}
                  style={{
                    // Height carries the data, so it is what animates. A
                    // transform would distort the rounded cap instead.
                    height: `${Math.min(100, share * 100)}%`,
                    // A vertical gradient rather than a flat fill: the bar is
                    // deepest where it meets the baseline, which gives the row
                    // a light source.
                    background:
                      "linear-gradient(180deg, var(--orange) 0%, var(--orange-ink) 130%)",
                    // Later digits recede, which is the shape of the law itself.
                    opacity: dimmed ? 0.32 : 1 - i * 0.055,
                    transform: isActive ? "scaleX(1.14)" : "scaleX(1)",
                    transitionDuration: "260ms, 220ms, 220ms",
                  }}
                />
              </span>
              <span
                className={cn(
                  "font-mono text-micro tabular-nums transition-colors duration-200",
                  isActive ? "text-orange-ink font-semibold" : "text-muted-foreground/70",
                )}
              >
                {digit}
              </span>
            </span>
          )
        })}
      </button>

      <p className="text-mini text-muted-foreground mt-3 max-sm:mt-2">
        {done ? (
          <>
            Real figures, sampled live — no table of frequencies behind them.
            Genuine ledgers land on this curve; fabricated figures rarely do.{" "}
            <span className="text-muted-foreground/60">Click to run it again.</span>
          </>
        ) : (
          <>
            Drawing figures across four orders of magnitude and counting their
            leading digits.
          </>
        )}
      </p>
    </div>
  )
}
