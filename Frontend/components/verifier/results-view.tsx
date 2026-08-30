"use client"

import { useEffect, useRef, useState } from "react"
import {
  CheckCircle2Icon,
  EyeIcon,
  EyeOffIcon,
  ImageIcon,
  RotateCcwIcon,
  XCircleIcon,
  AlertCircleIcon,
  MinusCircleIcon,
  type LucideIcon,
} from "lucide-react"

import { cn } from "@/lib/utils"
import type { AnalysisResult, CheckStatus, Verdict } from "@/lib/verifier"
import { Button } from "@/components/ui/button"
import { HorizontalScrollArea } from "@/components/ui/horizontal-scroll-area"
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from "@/components/ui/accordion"
import { ConfidenceRing } from "@/components/verifier/confidence-ring"
import { VerdictSeal } from "@/components/verifier/verdict-seal"
import { pressProps, sheenProps } from "@/components/verifier/sheen"

/** Confidence is evidence coverage, not a second risk figure: it says how much
 *  of the analysis actually ran. Stated in words because a bare percentage next
 *  to the risk percentage invites the two being read on the same scale. */
function describeConfidence(confidence: number, run: number, total: number): string {
  const missing = Math.max(0, total - run)
  const band = confidence >= 75 ? "High" : confidence >= 45 ? "Moderate" : "Low"
  if (missing === 0) return `${band} confidence · all ${total} checks ran`
  return `${band} confidence · ${missing} of ${total} checks could not run`
}

interface ResultsViewProps {
  result: AnalysisResult
  onReset: () => void
}

/** One base colour per verdict, spun out into the roles the panel needs.
 *
 *  Every value derives from a single token via color-mix, so the seal's rim,
 *  its fill, its glow, the panel's wash and the bloom cannot drift apart — and
 *  a theme change moves all of them at once. The previous version hard-coded
 *  an rgba() for the amber case, which is exactly the drift this prevents. */
function verdictPalette(base: string) {
  return {
    seal: `color-mix(in oklch, ${base}, transparent 72%)`,
    sealFill: `color-mix(in oklch, ${base}, transparent 86%)`,
    sealLine: `color-mix(in oklch, ${base}, transparent 55%)`,
    sealInk: base,
    bloom: `color-mix(in oklch, ${base}, transparent 74%)`,
    wash: `color-mix(in oklch, ${base}, transparent 92%)`,
    edge: `color-mix(in oklch, ${base}, transparent 78%)`,
  }
}

const VERDICT_CONFIG: Record<
  Verdict,
  { label: string; lede: string; text: string; base: string }
> = {
  valid: {
    label: "Likely Valid",
    lede: "No structural or statistical problems found",
    text: "text-success",
    base: "var(--success)",
  },
  fraud: {
    label: "Fraud Detected",
    lede: "Critical indicators present in this value",
    text: "text-danger",
    base: "var(--danger)",
  },
  insufficient: {
    label: "Insufficient Evidence",
    lede: "Not enough signal to call this either way",
    text: "text-warning",
    base: "var(--warning)",
  },
}

const STATUS_CONFIG: Record<
  CheckStatus,
  { icon: LucideIcon; text: string; label: string }
> = {
  pass: { icon: CheckCircle2Icon, text: "text-success", label: "Pass" },
  fail: { icon: XCircleIcon, text: "text-danger", label: "Fail" },
  // Amber, not red: the check ran and found something worth a human's attention,
  // which is a different statement from "this document is fraudulent".
  review: { icon: AlertCircleIcon, text: "text-warning", label: "Review" },
  // Grey and neutral: the test did not apply to this input. Showing it in red,
  // as this did, told the reader a test had failed when none had run.
  na: { icon: MinusCircleIcon, text: "text-muted-foreground", label: "N/A" },
}

function maskValue(input: string): string {
  const digits = input.replace(/\D/g, "")
  if (digits.length >= 8) {
    return "*".repeat(digits.length - 4) + digits.slice(-4)
  }
  return "*".repeat(digits.length)
}

function formatMaskedDisplay(input: string): string {
  const raw = input.replace(/\s/g, "")
  const masked = maskValue(raw)
  return masked.replace(/(.{4})/g, "$1 ").trim()
}

// Groups digits into 4s for the "revealed" view — typed input already reads
// nicely because the user spaces it themselves, but OCR-extracted numbers
// arrive as one unbroken digit string and need the same grouping applied.
function formatRevealedDisplay(input: string): string {
  const digits = input.replace(/\D/g, "")
  return digits.replace(/(.{4})/g, "$1 ").trim()
}

export function ResultsView({ result, onReset }: ResultsViewProps) {
  const verdict = VERDICT_CONFIG[result.verdict]
  const palette = verdictPalette(verdict.base)
  const [revealed, setRevealed] = useState(false)
  const isCard = result.type === "card"
  const [imageUrl, setImageUrl] = useState<string | null>(null)
  const barRef = useRef<HTMLDivElement>(null)
  const detailsRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const bar = barRef.current
    const details = detailsRef.current
    if (!bar || !details) return

    // The bar is tethered to the page on the opposite end: it leaves the moment
    // the technical-details card reaches it, and travels down one pixel for
    // every pixel the card has scrolled past the bar's top edge. Same amount,
    // same speed as the scroll — just inverted, so the pinning never fights the
    // last section it is about to cover. No easing while the finger drives it:
    // any easing here is latency, exactly like the sheet's drag (§2).
    const update = () => {
      const barHeight = bar.getBoundingClientRect().height
      const barTop = window.innerHeight - barHeight
      const over = barTop - details.getBoundingClientRect().top
      const travel = Math.min(barHeight, Math.max(0, over))
      const gone = travel >= barHeight
      bar.style.transform = `translate3d(0, ${travel}px, 0)`
      bar.style.opacity = String(1 - travel / barHeight)
      bar.style.pointerEvents = gone ? "none" : ""
      bar.toggleAttribute("inert", gone)
    }
    update()
    window.addEventListener("scroll", update, { passive: true })
    window.addEventListener("resize", update)
    return () => {
      window.removeEventListener("scroll", update)
      window.removeEventListener("resize", update)
    }
  }, [])

  useEffect(() => {
    if (result.imageFile) {
      const url = URL.createObjectURL(result.imageFile)
      setImageUrl(url)
      return () => URL.revokeObjectURL(url)
    }
  }, [result.imageFile])

  return (
    <div className="mx-auto flex w-full max-w-lg flex-col gap-5 max-sm:gap-3.5">
      {/* ── The verdict ────────────────────────────────────────────────────
          The answer, and now the largest thing in the column. It was a thin
          strip above a 180px risk ring, which meant the most prominent object
          on the results screen was the score rather than the conclusion — the
          eye found the number first and had to work out which was which.

          --seal-* are read by VerdictSeal and by the wash below, all derived
          from one base colour, so the mark and the surface it sits on are the
          same hue by construction. */}
      <div
        className="verdict-rise relative overflow-hidden rounded-[1.75rem] border px-7 py-9 text-center sm:px-10 sm:py-11 max-sm:rounded-2xl max-sm:px-5 max-sm:py-7"
        style={{
          ["--seal" as string]: palette.seal,
          ["--seal-fill" as string]: palette.sealFill,
          ["--seal-line" as string]: palette.sealLine,
          ["--seal-ink" as string]: palette.sealInk,
          borderColor: palette.edge,
          // A wash rather than a flat tint: strongest behind the seal at the
          // top, clearing by the time it reaches the sentence, so the panel has
          // a light source and the text sits on the card rather than in colour.
          background: `radial-gradient(120% 90% at 50% 0%, ${palette.wash}, transparent 72%), var(--surface-card)`,
        }}
      >
        {/* Expands out from behind the seal once and does not repeat — the
            payoff of the whole flow, and the one moment that earns a flourish. */}
        <span
          className="verdict-bloom"
          style={{ ["--bloom" as string]: palette.bloom }}
          aria-hidden="true"
        />

        <div className="relative z-10 flex flex-col items-center">
          <VerdictSeal verdict={result.verdict} />

          <h1
            className={cn(
              "font-display text-display-sm mt-6 font-extrabold tracking-tight text-balance",
              "max-sm:mt-4 max-sm:text-headline",
              verdict.text,
            )}
          >
            {verdict.label}
          </h1>

          {/* A fixed one-line summary of what the verdict means, above the
              generated sentence. The generated one explains *this* result; this
              one explains the verdict itself, and having both means the heading
              never has to carry the explanation on its own. */}
          <p className="text-muted-foreground text-caption mt-2 font-medium tracking-wide uppercase">
            {verdict.lede}
          </p>

          {/* Set at reading size, not footnote size. It is the sentence the
              whole analysis exists to produce. */}
          <p className="text-foreground/75 text-lead mt-5 max-w-[42ch] leading-[1.5] text-pretty max-sm:mt-3.5 max-sm:text-callout">
            {result.verdictSentence}
          </p>
        </div>
      </div>

      {/* Score + summary — clean card */}
      <div
        {...sheenProps}
        className="rise rise-2 glass-panel sheen-surface rounded-3xl p-7 max-sm:rounded-2xl max-sm:p-5"
      >
        <div className="relative z-10 flex flex-col items-center gap-8 sm:flex-row sm:gap-10 max-sm:gap-5">
          {/* The ring always means risk: 0 is clean, 100 is certainly invalid.
              It used to switch to confidence for non-fraud verdicts, so the same
              figure meant opposite things depending on the verdict — and the
              colour ramp had to invert to compensate. How much the analysis
              trusts itself is a separate statement, made underneath. */}
          <div className="flex shrink-0 flex-col items-center gap-2">
            <ConfidenceRing value={result.score} label="Risk" />
            <p className="max-w-[11rem] text-center text-micro tracking-wide text-muted-foreground uppercase">
              {describeConfidence(result.confidence, result.checksRun, result.checksTotal)}
            </p>
          </div>
          {/* Two-column data layout */}
          <div className="border-hairline/70 flex flex-1 flex-col gap-5 text-center sm:text-left max-sm:w-full max-sm:border-t max-sm:pt-5">
            {/* A document has no single "analyzed value" to show — it was judged
                on the figures it states, which are listed below. So the type
                carries the row on its own and is set at heading size. */}
            {result.isDocument ? (
              <div className="flex flex-col items-center gap-1 sm:items-start">
                <span className="text-caption font-medium tracking-wide text-muted-foreground uppercase">
                  Document type
                </span>
                <span className="text-headline leading-tight font-semibold text-foreground">
                  {result.typeLabel}
                </span>
                {result.documentFigures.length > 0 && (
                  <span className="mt-1 text-caption text-muted-foreground">
                    Verified against {result.documentFigures.length} figures stated on the document
                  </span>
                )}
              </div>
            ) : (
              <>
            <div className="flex items-baseline justify-center gap-3 sm:justify-start">
              <span className="text-caption font-medium tracking-wide text-muted-foreground uppercase">
                Classified as
              </span>
              <span className="text-callout font-semibold text-foreground">
                {result.typeLabel}
              </span>
            </div>
            <span className="hidden h-px w-full bg-border sm:block" />
            <div className="flex flex-col items-center gap-1.5 sm:items-start">
              <span className="text-caption font-medium tracking-wide text-muted-foreground uppercase">
                Analyzed value
              </span>
              {isCard ? (
                <button
                  type="button"
                  onClick={() => setRevealed((v) => !v)}
                  // .tap gives it a 44pt hit region without making the row 44pt
                  // tall — the control is a line of text and should stay one.
                  className="group tap flex w-full items-center gap-2 font-mono text-body font-medium text-foreground transition-[color,opacity] duration-(--dur-press) ease-(--ease-standard) active:opacity-70 max-sm:justify-center max-sm:text-callout"
                  title={revealed ? formatRevealedDisplay(result.input) : "Click to reveal"}
                >
                  <span className="truncate">
                    {revealed ? formatRevealedDisplay(result.input) : formatMaskedDisplay(result.input)}
                  </span>
                  <span className="shrink-0 text-muted-foreground/50 group-hover:text-muted-foreground transition-colors">
                    {revealed ? (
                      <EyeOffIcon className="size-3.5" />
                    ) : (
                      <EyeIcon className="size-3.5" />
                    )}
                  </span>
                </button>
              ) : (
                <span className="w-full truncate font-mono text-body font-medium text-foreground" title={result.input}>
                  {result.input}
                </span>
              )}
            </div>
              </>
            )}
          </div>
        </div>
      </div>

      {/* Checks performed */}
      <div className="rise rise-3 glass-panel rounded-3xl max-sm:rounded-2xl">
        <div className="px-6 pt-5 pb-1 max-sm:px-4">
          <h2 className="text-caption font-medium tracking-wide text-muted-foreground uppercase">
            Checks performed
          </h2>
          <p className="mt-1 text-caption text-muted-foreground">
            {result.checks.filter((c) => c.status === "pass").length} passed ·{" "}
            {result.checks.filter((c) => c.status === "fail").length} failed ·{" "}
            {result.checks.filter((c) => c.status === "review").length} to review ·{" "}
            {result.checks.filter((c) => c.status === "na").length} n/a
          </p>
        </div>
        <Accordion className="px-2 pb-2">
          {result.checks.map((check, i) => {
            const status = STATUS_CONFIG[check.status]
            const StatusIcon = status.icon
            return (
              <AccordionItem
                key={check.id}
                value={check.id}
                // Each row arrives on the shared rise, one step behind the last,
                // so the list reads as evidence being laid out rather than a
                // block of results appearing at once. Capped at eight steps:
                // past roughly a quarter-second the cascade stops reading as a
                // cascade and starts reading as the page being slow.
                className="rise border-b border-border/50 last:border-b-0"
                style={{ ["--rise-delay" as string]: `${140 + Math.min(i, 8) * 45}ms` }}
              >
                <AccordionTrigger
                  {...pressProps}
                  className="items-center gap-3.5 py-3.5 pr-4 pl-4 row-press max-sm:min-h-14 max-sm:rounded-xl max-sm:active:opacity-100"
                >
                  <span className={cn("shrink-0", status.text)}>
                    <StatusIcon className="size-4.5" />
                  </span>
                  <span className="flex flex-1 flex-col gap-0.5 pr-2 text-left">
                    <span className="text-footnote font-medium text-foreground">{check.name}</span>
                    <span className="text-caption font-normal text-muted-foreground">
                      {check.summary}
                    </span>
                  </span>
                </AccordionTrigger>
                <AccordionContent className="pb-2 pl-[2.9rem] text-footnote text-muted-foreground">
                  {check.detail}
                </AccordionContent>
              </AccordionItem>
            )
          })}
        </Accordion>
      </div>

      {/* Technical details */}
      <div ref={detailsRef} className="rise rise-4 glass-panel rounded-3xl max-sm:rounded-2xl">
        <Accordion>
          <AccordionItem value="technical" className="border-none">
            <AccordionTrigger
              {...pressProps}
              className="px-6 py-4 row-press max-sm:min-h-14 max-sm:rounded-xl max-sm:px-4 max-sm:active:opacity-100"
            >
              <span className="text-footnote font-medium text-foreground">Technical details</span>
            </AccordionTrigger>
            <AccordionContent className="px-6 pb-5 max-sm:px-4">
              <div className="flex flex-col gap-5">
                {/* Scanned image preview */}
                {imageUrl && (
                  <div>
                    <p className="mb-2 text-mini font-medium tracking-wide text-muted-foreground uppercase">
                      Scanned image
                    </p>
                    <div className="relative overflow-hidden rounded-xl border border-border bg-secondary">
                      <img
                        src={imageUrl}
                        alt="Scanned document"
                        className="max-h-64 w-full object-contain"
                      />
                      <div className="absolute top-2 right-2 flex items-center gap-1.5 rounded-lg bg-black/60 px-2 py-1 text-micro text-white/80">
                        <ImageIcon className="size-3" />
                        <span>{result.imageFile?.name}</span>
                      </div>
                    </div>
                  </div>
                )}

                {/* For a document, the figures it stated are the evidence the
                    verdict rests on, and the OCR agreement is how far each one
                    can be trusted. That is what a reader needs to see; the raw
                    text panel below said only "Source: images.png", because the
                    client has no OCR text of its own to show. */}
                {result.isDocument && result.documentFigures.length > 0 ? (
                  <div>
                    <p className="mb-2 text-mini font-medium tracking-wide text-muted-foreground uppercase">
                      Figures read from the document
                    </p>
                    <div className="overflow-hidden rounded-xl bg-secondary">
                      {result.documentFigures.map((figure, i) => (
                        <div
                          key={figure.name}
                          className={cn(
                            "flex items-center justify-between gap-4 px-3.5 py-2.5",
                            i > 0 && "border-t border-border/50",
                          )}
                        >
                          <span className="text-caption text-muted-foreground">{figure.name}</span>
                          <span className="flex items-baseline gap-3">
                            <span className="font-mono text-footnote font-medium text-foreground">
                              {figure.value.toLocaleString(undefined, {
                                minimumFractionDigits: 2,
                                maximumFractionDigits: 2,
                              })}
                            </span>
                            <span
                              className="font-mono text-mini text-muted-foreground/70"
                              title="How many independent OCR passes read this figure the same way"
                            >
                              {Math.round(figure.agreement * 100)}% agreement
                            </span>
                          </span>
                        </div>
                      ))}
                    </div>
                  </div>
                ) : (
                  <div>
                    <p className="mb-2 text-mini font-medium tracking-wide text-muted-foreground uppercase">
                      Raw extracted text
                    </p>
                    <HorizontalScrollArea
                      fadeColor="var(--secondary)"
                      wrapperClassName="rounded-xl bg-secondary"
                      className="p-3.5 font-mono text-caption whitespace-pre text-foreground"
                    >
                      {result.rawText || "\u2014"}
                    </HorizontalScrollArea>
                  </div>
                )}
                <div>
                  <p className="mb-2.5 text-mini font-medium tracking-wide text-muted-foreground uppercase">
                    Classification confidence
                  </p>
                  <div className="flex flex-col gap-2.5">
                    {result.candidates.map((c) => {
                      const pct = Math.round(c.confidence * 100)
                      return (
                        <div key={c.type} className="flex items-center gap-3">
                          <span className="w-28 shrink-0 text-caption text-muted-foreground">
                            {c.label}
                          </span>
                          <span className="relative h-1.5 flex-1 overflow-hidden rounded-full bg-secondary">
                            <span
                              className={cn(
                                "absolute inset-y-0 left-0 rounded-full",
                                c.type === result.type ? "bg-orange" : "bg-muted-foreground/30",
                              )}
                              style={{ width: `${pct}%` }}
                            />
                          </span>
                          <span className="w-9 shrink-0 text-right font-mono text-caption tabular-nums text-muted-foreground">
                            {pct}%
                          </span>
                        </div>
                      )
                    })}
                  </div>
                </div>
              </div>
            </AccordionContent>
          </AccordionItem>
        </Accordion>
      </div>

      <Button
        size="lg"
        onClick={onReset}
        className="btn-gradient mt-2 h-12 w-full rounded-2xl text-body font-semibold text-white disabled:opacity-40 max-sm:hidden"
      >
        <RotateCcwIcon data-icon="inline-start" className="size-4" />
        Analyze another
      </Button>

      {/* The results screen is the longest scroll in the app — a verdict panel,
          a score card, up to a dozen checks and a technical appendix. Leaving
          the only way out at the bottom of that meant scrolling back through all
          of it to start again.

          Pinned, but not forever: the moment the technical-details section
          reaches it, the bar is pushed off the opposite edge and out of the
          way — retreating down in step with the scroll rather than sitting over
          the last section of the page or the credits beneath. */}
      <div ref={barRef} className="action-bar hidden max-sm:block">
        <Button
          size="lg"
          onClick={onReset}
          {...pressProps}
          className="btn-gradient m3-press btn-liquid m3x-morph h-14 w-full text-callout font-semibold text-white"
        >
          <RotateCcwIcon data-icon="inline-start" className="size-4" />
          Analyze another
        </Button>
      </div>
    </div>
  )
}
