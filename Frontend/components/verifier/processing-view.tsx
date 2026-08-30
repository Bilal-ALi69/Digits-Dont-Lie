"use client"

import { useEffect, useRef, useState } from "react"

import { cn } from "@/lib/utils"
import type { ImageGuess } from "@/lib/api"
import { ScanStage } from "@/components/verifier/scan-stage"

interface ProcessingViewProps {
  steps: string[]
  /** Vision's read on an uploaded image. Arrives mid-flight; absent means the
   *  screen stays generic rather than inventing a document type. */
  guess?: ImageGuess | null
  /** True while real work is still outstanding. The narration never finishes
   *  ahead of it — it holds on the last line instead of jumping to results. */
  waiting?: boolean
  /** Whether a vision verdict is expected at all. When it is, its row is held
   *  open from the start so the panel does not grow when the chip lands. */
  expectsGuess?: boolean
  /** The document under analysis, shown in the scan frame. */
  file?: File
  /** The typed value under analysis, when there is no file. */
  value?: string
  onComplete: () => void
}

const LINE_MS = 1000
const TAIL_MS = 420

const DOC_TYPE_LABELS: Record<string, string> = {
  credit_card: "a credit card",
  debit_card: "a debit card",
  national_id: "a national ID",
  passport: "a passport",
  driver_license: "a driver's licence",
  invoice: "an invoice",
  bank_statement: "a bank statement",
  receipt: "a receipt",
  transaction_document: "a transaction document",
  other: "a document",
}

export function ProcessingView({ steps, guess, waiting = false, expectsGuess = false, file, value, onComplete }: ProcessingViewProps) {
  const [index, setIndex] = useState(0)
  const [linesDone, setLinesDone] = useState(false)
  const onCompleteRef = useRef(onComplete)
  onCompleteRef.current = onComplete

  // `steps` is stable for a run — the vision verdict renders as its own element
  // rather than joining this list, so a guess arriving mid-flight cannot resize
  // the array and restart the narration from the first line.
  useEffect(() => {
    const timers = steps.map((_, i) => setTimeout(() => setIndex(i), LINE_MS * i))
    const last = setTimeout(() => setLinesDone(true), LINE_MS * steps.length)
    return () => {
      timers.forEach(clearTimeout)
      clearTimeout(last)
    }
  }, [steps])

  // Finish only once the narration has played *and* the real work has landed.
  useEffect(() => {
    if (!linesDone || waiting) return
    const t = setTimeout(() => onCompleteRef.current(), TAIL_MS)
    return () => clearTimeout(t)
  }, [linesDone, waiting])

  const progress = steps.length > 1 ? index / (steps.length - 1) : 1
  const label = guess ? DOC_TYPE_LABELS[guess.document_type] ?? "a document" : null

  return (
    <div className="mx-auto w-full max-w-md">
      {/* m3x-container/card-mobile on a phone, matching every other surface in
          the app at that width — this panel was still an 12px-cornered
          rectangle while the input card beside it in the same flow had already
          become a 28px touch container. */}
      <div className="rise panel-raised rounded-2xl border border-hairline/60 bg-surface-card px-8 py-10 overflow-hidden m3x-container card-mobile max-sm:px-4 max-sm:py-7">
        {/* The document under the lens. This replaced a row of pulsing bars —
            a fine stand-in when there was nothing concrete to show, but the
            user has just handed over a document and watching it be read is
            strictly more interesting than watching a loader that stands for it.
            The Benford glyph still exists where it has something to say: the
            hero's live sampler on the landing screen. */}
        <ScanStage file={file} value={value} />

        <p className="mt-6 text-center font-mono text-micro font-semibold tracking-[0.18em] text-muted-foreground/50 uppercase max-sm:mt-5">
          Analyzing
        </p>

        {/* Every line is rendered, stacked in one grid cell, and only its
            opacity changes. Two consequences, both wanted: the block is always
            as tall as the longest line, so the panel never resizes as the
            narration advances; and the outgoing line fades out while the
            incoming one fades in, rather than the old text being removed and
            the new one appearing in an empty space. */}
        <div className="mt-3 grid">
          {steps.map((step, i) => (
            <p
              key={step}
              aria-hidden={i !== index}
              className={cn(
                "col-start-1 row-start-1 max-w-[30ch] justify-self-center text-center text-body leading-[1.5] text-muted-foreground max-sm:text-callout",
                "transition-opacity motion-reduce:transition-none",
                i === index
                  ? "opacity-100 duration-[280ms] ease-(--ease-rise) delay-[80ms]"
                  : "opacity-0 duration-[160ms] ease-(--ease-exit)",
              )}
            >
              {step}
            </p>
          ))}
        </div>

        {/* The stacked lines above are all present in the DOM, so they cannot
            carry the announcement — a screen reader would read the whole list.
            This is the single line that is actually current. */}
        <span className="sr-only" aria-live="polite">
          {steps[index]}
        </span>

        {/* The vision verdict persists once it lands, rather than scrolling past
            as one more line — it is the single most informative thing on screen.
            Its row is reserved from the start whenever a verdict is expected, so
            the chip arriving mid-run fades in rather than growing the panel. */}
        {(expectsGuess || (guess && label)) && (
          <div className="mt-1 flex h-9 items-center justify-center">
            {guess && label && (
              <div className="processing-verdict flex items-center gap-2 rounded-full border border-orange/25 bg-orange/10 px-3.5 py-1.5">
                <span className="size-1.5 shrink-0 rounded-full bg-orange" />
                <span className="text-caption font-medium text-foreground">
                  Looks like {label}
                </span>
                <span className="font-mono text-mini text-orange-ink">
                  {Math.round(guess.confidence * 100)}%
                </span>
              </div>
            )}
          </div>
        )}

        {/* 3px rather than the previous hairline: a travelling highlight is the
            point of this bar, and at 1px there was nothing for it to travel
            across. The panel behind is panel-raised, not glass-panel, so a
            continuous animation here costs nothing elsewhere on the page. */}
        <div className="mt-7 h-[3px] w-full overflow-hidden rounded-full bg-hairline">
          <div
            className={cn(
              "relative h-full overflow-hidden rounded-full bg-orange",
              // The width eases between narration steps rather than jumping,
              // and the curve settles instead of stopping dead.
              "transition-[width] duration-700 ease-(--ease-rise)",
              // A highlight sweeps along the filled portion the whole time, so
              // the bar reads as working rather than as a static measurement.
              "bar-sweep",
              // Waiting past the scripted narration: breathe as well, so a slow
              // backend still looks alive instead of parked at a dead 100%.
              linesDone && waiting && "progress-indeterminate",
            )}
            style={{ width: `${Math.max(6, progress * 100)}%` }}
          />
        </div>
      </div>
    </div>
  )
}
