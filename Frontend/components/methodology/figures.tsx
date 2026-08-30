"use client"

import { useEffect, useRef, useState } from "react"

import { cn } from "@/lib/utils"

/* ─── Figures ─────────────────────────────────────────────────────────────────
   The three ideas on this page that are genuinely visual. Each replaces a
   paragraph that was describing a picture instead of drawing one.
   -------------------------------------------------------------------------- */

/** A worked Luhn pass, computed rather than typed out.
 *
 *  The old page listed the four steps of the algorithm in prose and left the
 *  reader to run it in their head. Running it on an actual number — and showing
 *  which digits doubled, what they became, and the total landing on a multiple
 *  of ten — is the difference between being told the rule and seeing it close.
 *
 *  Nothing here is hard-coded: the doubling, the digit sum and the verdict are
 *  all derived below, so the figure cannot drift out of agreement with the
 *  algorithm it is illustrating. */
const LUHN_SAMPLE = "4111111111111111"

function luhnBreakdown(pan: string) {
  const digits = pan.split("").map(Number)
  // Walk from the right. The check digit is position 1 and is never doubled;
  // every second digit after it is.
  return digits.map((d, i) => {
    const fromRight = digits.length - i
    const doubled = fromRight % 2 === 0
    const raw = doubled ? d * 2 : d
    const value = raw > 9 ? raw - 9 : raw
    return { d, doubled, value, reduced: raw > 9 }
  })
}

export function LuhnFigure() {
  const rows = luhnBreakdown(LUHN_SAMPLE)
  const total = rows.reduce((a, r) => a + r.value, 0)
  const passes = total % 10 === 0

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap gap-1.5">
        {rows.map((r, i) => (
          <span key={i} className="flex flex-col items-center gap-1">
            <span
              className={cn(
                "flex size-8 items-center justify-center rounded-lg font-mono text-footnote font-semibold tabular-nums",
                r.doubled
                  ? "bg-orange/15 text-orange-ink ring-1 ring-orange/25 ring-inset"
                  : "bg-secondary text-muted-foreground",
              )}
            >
              {r.d}
            </span>
            <span
              className={cn(
                "font-mono text-micro tabular-nums",
                r.doubled ? "text-orange-ink font-semibold" : "text-muted-foreground/50",
              )}
            >
              {r.value}
            </span>
          </span>
        ))}
      </div>

      <div className="border-hairline/60 flex flex-wrap items-center gap-x-5 gap-y-2 border-t pt-3">
        <span className="text-mini text-muted-foreground">
          <span className="bg-orange/15 ring-orange/25 mr-1.5 inline-block size-2 rounded-sm ring-1 ring-inset" />
          doubled (every second digit from the right)
        </span>
        <span className="text-mini text-muted-foreground ml-auto font-mono tabular-nums">
          sum = <span className="text-foreground font-semibold">{total}</span> · {total} mod 10 ={" "}
          <span className="text-foreground font-semibold">{total % 10}</span>
        </span>
        <span
          className={cn(
            "text-mini rounded-full px-2.5 py-1 font-semibold",
            passes ? "bg-success/12 text-success" : "bg-danger/12 text-danger",
          )}
        >
          {passes ? "Checksum passes" : "Checksum fails"}
        </span>
      </div>
    </div>
  )
}

/** The Benford distribution, drawn against the formula that produces it.
 *
 *  The prose stated P(d) = log10(1 + 1/d) and then separately mentioned that 1
 *  occurs 30.1% of the time and 9 about 4.6%. Those are the same fact, and
 *  putting the equation next to the shape it generates says so. */
const DIGITS = [1, 2, 3, 4, 5, 6, 7, 8, 9] as const
const EXPECTED = DIGITS.map((d) => Math.log10(1 + 1 / d))

export function BenfordFigure() {
  const [shown, setShown] = useState(false)
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const el = ref.current
    if (!el || typeof IntersectionObserver === "undefined") {
      setShown(true)
      return
    }
    const io = new IntersectionObserver(
      ([e]) => {
        if (e.isIntersecting) {
          setShown(true)
          io.disconnect()
        }
      },
      { threshold: 0.3 },
    )
    io.observe(el)
    return () => io.disconnect()
  }, [])

  const peak = EXPECTED[0]

  return (
    <div ref={ref} className="flex flex-col gap-5">
      <p className="text-foreground text-center font-mono text-lead tracking-tight max-sm:text-callout">
        P(d) = log<sub className="text-caption">10</sub>(1 + 1/d)
      </p>
      <div className="flex items-end gap-2 max-sm:gap-1" style={{ height: 120 }}>
        {DIGITS.map((digit, i) => (
          <div key={digit} className="flex flex-1 flex-col items-center gap-1.5">
            <span
              className={cn(
                "text-muted-foreground font-mono text-micro tabular-nums transition-opacity duration-500",
                shown ? "opacity-100" : "opacity-0",
              )}
              style={{ transitionDelay: `${420 + i * 55}ms` }}
            >
              {(EXPECTED[i] * 100).toFixed(1)}
            </span>
            <div className="flex w-full flex-1 items-end">
              <div
                className="w-full rounded-t-[3px] transition-[height] ease-(--ease-rise) motion-reduce:transition-none"
                style={{
                  height: shown ? `${(EXPECTED[i] / peak) * 100}%` : "0%",
                  background: "linear-gradient(180deg, var(--orange) 0%, var(--orange-ink) 130%)",
                  opacity: 1 - i * 0.055,
                  transitionDuration: "700ms",
                  transitionDelay: `${i * 55}ms`,
                }}
              />
            </div>
            <span className="text-muted-foreground/70 font-mono text-micro tabular-nums">
              {digit}
            </span>
          </div>
        ))}
      </div>
      <p className="text-muted-foreground text-mini text-center">
        Percentage of genuine figures beginning with each digit
      </p>
    </div>
  )
}

/** The risk scale, as a scale.
 *
 *  This was four coloured words in a sentence — and the colours were Tailwind's
 *  400 ramp, which is tuned for dark surfaces and washed out on paper. Drawing
 *  it as a continuous band with the boundaries marked shows what the sentence
 *  could only assert: that these are ranges on one axis, not four categories. */
const BANDS = [
  { label: "Low", range: "0–30", span: 30, cls: "bg-success" },
  { label: "Medium", range: "31–60", span: 30, cls: "bg-warning" },
  { label: "High", range: "61–80", span: 20, cls: "bg-orange" },
  { label: "Critical", range: "81–100", span: 20, cls: "bg-danger" },
]

export function RiskScaleFigure() {
  return (
    <div className="flex flex-col gap-3">
      <div className="flex h-3 w-full overflow-hidden rounded-full">
        {BANDS.map((b) => (
          <div key={b.label} className={cn(b.cls)} style={{ width: `${b.span}%` }} />
        ))}
      </div>
      {/* Wide: each label sits under the segment it names, so the figure reads
          as one axis. */}
      <div className="flex w-full max-sm:hidden">
        {BANDS.map((b) => (
          <div key={b.label} className="flex flex-col gap-0.5" style={{ width: `${b.span}%` }}>
            <span className="text-footnote text-foreground font-semibold">{b.label}</span>
            <span className="text-muted-foreground/70 font-mono text-micro tabular-nums">
              {b.range}
            </span>
          </div>
        ))}
      </div>
      {/* Narrow: the same four bands as a legend. A 20% column is 65px on a
          phone, which "Critical" does not fit into and which pushed the range
          under it onto a second line, so the labels stopped lining up with the
          band above them and the figure read as broken rather than tight. The
          colour swatch is what keeps each row tied to its segment. */}
      <div className="hidden grid-cols-2 gap-x-4 gap-y-2.5 max-sm:grid">
        {BANDS.map((b) => (
          <div key={b.label} className="flex items-center gap-2">
            <span className={cn("size-2.5 shrink-0 rounded-full", b.cls)} />
            <span className="text-footnote text-foreground font-semibold">{b.label}</span>
            <span className="text-muted-foreground/70 ml-auto font-mono text-micro tabular-nums">
              {b.range}
            </span>
          </div>
        ))}
      </div>
    </div>
  )
}
