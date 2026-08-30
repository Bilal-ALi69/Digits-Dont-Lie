"use client"

import Link from "next/link"
import { useState } from "react"
import {
  ArrowLeftIcon,
  ArrowRightIcon,
  BrainCircuitIcon,
  ListIcon,
  ScaleIcon,
  SettingsIcon,
  ShieldCheckIcon,
  UploadCloudIcon,
} from "lucide-react"

import { MobileSheet } from "@/components/ui/mobile-sheet"
import { pressProps } from "@/components/verifier/sheen"
import { AmbientBackground } from "@/components/verifier/ambient-background"
import { Rail, ReadingProgress, type RailItem } from "@/components/methodology/rail"
import {
  BenfordFigure,
  LuhnFigure,
  RiskScaleFigure,
} from "@/components/methodology/figures"
import {
  Act,
  Code,
  Figure,
  MEASURE,
  Note,
  P,
  Reveal,
  Section,
  Steps,
  Terms,
} from "@/components/methodology/primitives"
import { cn } from "@/lib/utils"

/* ─── Methodology ─────────────────────────────────────────────────────────────
   A rewrite, not a restyle. The previous version put all fourteen sections
   behind accordions inside a single flat list, prefaced by a ten-node pipeline
   diagram that scrolled sideways. Three things were wrong with that, and they
   are the three the brief named:

   Cluttered — every section was a peer of every other, so a reader met fourteen
   equally-weighted rows with no sense of which were the argument and which were
   reference. They are now grouped into four acts that follow the pipeline, plus
   a reference appendix, so the shape of the process is the shape of the page.

   Hard to read — content was hidden by default and, once opened, ran the full
   container width in dense bullet lists. It is now open, set at a 68-character
   measure, and the bullet lists that were really key-value data have become
   definition lists that scan in a fraction of the time.

   Not stunning — the only figure was that sideways diagram. The three ideas on
   this page that are genuinely visual now get drawn: Luhn as a worked example
   on a real number, Benford as its formula beside the distribution it
   generates, and the risk bands as an actual scale.
   -------------------------------------------------------------------------- */

const RAIL: RailItem[] = [
  { id: "intake", label: "Overview", act: "I · Intake" },
  { id: "input-sources", label: "Input sources" },
  { id: "ocr", label: "OCR processing" },
  { id: "classification", label: "Classification", act: "II · Identification" },
  { id: "groq", label: "AI classification" },
  { id: "confidence", label: "Confidence scoring" },
  { id: "confirmation", label: "Auto vs. confirmation" },
  { id: "luhn", label: "Luhn algorithm", act: "III · Verification" },
  { id: "benford", label: "Benford's Law" },
  { id: "risk", label: "Risk assessment" },
  { id: "evidence", label: "Evidence", act: "IV · Verdict" },
  { id: "verdict", label: "Verdict logic" },
  { id: "modes", label: "Backend & fallback", act: "Reference" },
  { id: "api", label: "API endpoints" },
  { id: "limitations", label: "Limitations" },
]

/** The pipeline, as a spine rather than a sideways scroller.
 *
 *  The old diagram had ten nodes in a horizontally-scrolling strip, which meant
 *  the overview of the system could not be seen all at once — the reader had to
 *  drag to find out what came after step four. Four stages stacked vertically
 *  fit on any screen and match the four acts below, so the diagram and the
 *  document are finally the same structure. */
const STAGES = [
  {
    n: "I",
    title: "Intake",
    body: "A typed value, an uploaded document, or a camera capture. Files are rendered and read by OCR; text skips straight ahead.",
  },
  {
    n: "II",
    title: "Identification",
    body: "Deterministic pattern rules and an LLM pass both propose a type. Their agreement sets the confidence, and low confidence asks the user.",
  },
  {
    n: "III",
    title: "Verification",
    body: "Structural checks for what has them — Luhn for cards — and statistical ones for what does not: Benford, chi-square, per-digit z-scores.",
  },
  {
    n: "IV",
    title: "Verdict",
    body: "Every check contributes evidence and a weighted risk score. The verdict is the synthesis, with the workings kept visible.",
  },
]

function Pipeline() {
  return (
    <div className="flex flex-col">
      {STAGES.map((s, i) => (
        <Reveal key={s.n} delay={i * 70}>
          <div className="flex gap-5">
            <div className="flex shrink-0 flex-col items-center">
              <span className="border-orange/30 bg-orange/10 text-orange-ink flex size-9 items-center justify-center rounded-full border font-mono text-caption font-bold">
                {s.n}
              </span>
              {i < STAGES.length - 1 && (
                <span className="from-orange/30 to-hairline my-1 w-px flex-1 bg-gradient-to-b" />
              )}
            </div>
            <div className={cn("pb-8", i === STAGES.length - 1 && "pb-0")}>
              <h3 className="font-display text-foreground text-lead font-bold">{s.title}</h3>
              <p className="text-muted-foreground text-footnote mt-1.5 max-w-[52ch] leading-[1.7]">
                {s.body}
              </p>
            </div>
          </div>
        </Reveal>
      ))}
    </div>
  )
}

export default function HowItWorksPage() {
  // The rail is `lg:block`, so on a phone this fifteen-section document had no
  // table of contents at all — the 2px progress line said how far in the reader
  // was and nothing said what was ahead or let them skip to it. Same items, same
  // grouping, reached from the header instead of a second column.
  const [contentsOpen, setContentsOpen] = useState(false)

  return (
    <div className="bg-surface-page text-foreground min-h-screen">
      <AmbientBackground />
      <ReadingProgress />

      <header className="chrome-bar sticky top-0 z-40">
        <div className="mx-auto flex h-14 max-w-6xl items-center justify-between px-6 max-sm:px-4">
          <Link
            href="/"
            {...pressProps}
            className="group text-muted-foreground hover:text-foreground text-footnote flex items-center gap-2 font-medium transition-colors row-press max-sm:-mx-2 max-sm:min-h-11 max-sm:rounded-xl max-sm:px-2"
          >
            <ArrowLeftIcon className="size-4 transition-transform group-hover:-translate-x-0.5 motion-reduce:transition-none" />
            <span>Back to Analyzer</span>
          </Link>
          {/* Desktop keeps the label — the rail beside the article is already
              answering "what's here", so a second control would be noise. */}
          <span className="text-muted-foreground/50 text-mini tracking-wide uppercase max-sm:hidden">
            Methodology
          </span>
          <button
            type="button"
            onClick={() => setContentsOpen(true)}
            aria-expanded={contentsOpen}
            aria-haspopup="dialog"
            {...pressProps}
            className="row-press border-hairline bg-surface-card text-footnote text-foreground hidden min-h-11 items-center gap-2 rounded-full border px-4 font-medium shadow-sm outline-none focus-visible:ring-3 focus-visible:ring-orange/25 max-sm:flex"
          >
            <ListIcon className="text-orange-ink size-4" />
            <span>Contents</span>
          </button>
        </div>
      </header>

      {/* Washes with --nav rather than --surface-page: the page colour is
          opaque, and painting a strip of it over the drifting ambient field
          punched a visible rectangle out of the field. */}
      <div className="pointer-events-none fixed top-14 right-0 left-0 z-30 h-10 bg-gradient-to-b from-[var(--nav)] to-transparent" />

      <main className="relative z-10 mx-auto max-w-[56rem] px-6 pt-20 pb-24 max-sm:px-4 max-sm:pt-12 max-sm:pb-16">
      <div className="flex gap-10 lg:gap-12">
        <Rail items={RAIL} />

        <article className="min-w-0 flex-1">
        {/* ── Hero ──────────────────────────────────────────────────────────
            Inside the article column, sharing its left edge. Set outside it the
            hero began 200px to the left of every heading beneath it, and that
            misalignment was the first thing the eye caught on the page. */}
        <Reveal>
          <p className="text-orange-ink/80 mb-5 font-mono text-mini font-semibold tracking-[0.2em] uppercase">
            Technical Methodology
          </p>
          <h1 className="font-display text-heading text-display-sm sm:text-display max-w-[15ch] font-extrabold text-balance">
            How <span className="text-orange-ink">Digits Don&apos;t Lie</span> works
          </h1>
          <p className={cn("text-muted-foreground text-lead mt-6 leading-[1.6] text-pretty", MEASURE)}>
            A complete walkthrough of the analysis pipeline — from raw input to
            final verdict. Every number tells a story. This is how we check
            whether it is telling the truth.
          </p>
          <div className="text-muted-foreground/60 mt-7 flex flex-wrap items-center gap-x-3 gap-y-1 font-mono text-mini tracking-wide uppercase">
            <span>Four stages</span>
            <span className="bg-muted-foreground/25 size-[3px] rounded-full" />
            <span>Fifteen sections</span>
            <span className="bg-muted-foreground/25 size-[3px] rounded-full" />
            <span>Deterministic &amp; statistical</span>
          </div>
        </Reveal>

            {/* ── I · Intake ───────────────────────────────────────────── */}
            <div id="intake" className="scroll-mt-24">
              <Act
                numeral="ACT I"
                icon={UploadCloudIcon}
                title="Intake"
                blurb="Getting a number out of whatever the user actually has — a typed value, a photograph, a PDF."
              />
              <Reveal>
                <div className="mb-4">
                  <Pipeline />
                </div>
              </Reveal>
            </div>

            <Section id="input-sources" n="01" title="Input sources">
              <P>The system accepts three kinds of input.</P>
              <Terms
                items={[
                  {
                    term: "Text input",
                    desc: "A numeric value pasted or typed directly — a card number, an invoice amount, a reference ID.",
                  },
                  {
                    term: "File upload",
                    desc: "PDF documents, JPEG images, or PNG screenshots, all routed through OCR extraction.",
                  },
                  {
                    term: "Camera capture",
                    desc: "A live photo from the device camera, processed as an image file.",
                  },
                ]}
              />
              <P>
                When a file is provided the backend runs OCR first. Typed text skips
                extraction entirely and goes straight to classification.
              </P>
            </Section>

            <Section id="ocr" n="02" title="OCR processing">
              <P>
                File inputs are processed through a Tesseract-based OCR pipeline on the
                backend, which converts image content into machine-readable text.
              </P>
              <Terms
                items={[
                  { term: "PDFs", desc: "Each page is rendered to an image before OCR runs." },
                  { term: "Images", desc: "Text is extracted directly by the OCR engine." },
                ]}
              />
              <P>
                Extracted text is passed downstream for classification and analysis.
              </P>
              <Note>
                In client-side mode, when the backend is unreachable, extraction is
                simulated from a deterministic filename heuristic. That path exists so
                the interface stays demonstrable offline — it is not analysis, and the
                app says so on screen when it is in use.
              </Note>
            </Section>

            {/* ── II · Identification ──────────────────────────────────── */}
            <Act
              numeral="ACT II"
                icon={BrainCircuitIcon}
              title="Identification"
              blurb="Deciding what the value actually is, and being honest about how sure that decision is."
            />

            <Section id="classification" n="03" title="Document classification">
              <P>
                Once a raw value exists — typed or extracted — it is classified into one
                of four types.
              </P>
              <Terms
                items={[
                  { term: "Card number", desc: "13–19 digit sequences, with or without spaces and dashes." },
                  { term: "Financial amount", desc: "Monetary values with currency symbols or decimal formatting." },
                  { term: "Invoice number", desc: "Alphanumeric identifiers of the kind invoices carry." },
                  { term: "Generic identifier", desc: "Any other numeric or alphanumeric string." },
                ]}
              />
              <P>
                Classification combines regex patterns, length heuristics and format
                detection. Each candidate receives a confidence score between 0 and 1.
              </P>
            </Section>

            <Section id="groq" n="04" title="AI classification">
              <P>
                When the backend is available, classification is augmented by a fast LLM
                pass through the Groq API. The raw text is sent for zero-shot
                classification, which returns the most likely type, a confidence score
                per type, and an extracted label.
              </P>
              <P>
                That result is merged with the deterministic classifier rather than
                replacing it. If the API yields no candidates, the regex classifier
                stands alone — so the system degrades to rules rather than to nothing.
              </P>
            </Section>

            <Section id="confidence" n="05" title="Confidence scoring">
              <P>Every candidate is scored on four inputs.</P>
              <Terms
                items={[
                  { term: "Pattern match", desc: "How closely the input fits a known format." },
                  { term: "Length validation", desc: "Whether the digit count falls in the expected range." },
                  { term: "Character composition", desc: "The ratio of digits to other characters." },
                  { term: "API agreement", desc: "Confidence is boosted when the LLM independently agrees with the rules." },
                ]}
              />
              <P>
                Above the threshold the top candidate is taken as settled. Below it — or
                when two candidates sit too close together — the user is asked.
              </P>
            </Section>

            <Section id="confirmation" n="06" title="Auto vs. user confirmation">
              <Terms
                items={[
                  {
                    term: "Auto-proceed",
                    desc: "One candidate holds dominant confidence, and analysis runs immediately.",
                  },
                  {
                    term: "Ask the user",
                    desc: "Several types are plausible, so the candidates are shown with their scores and the user picks.",
                  },
                ]}
              />
              <P>
                This exists to stop a misclassification becoming a wrong verdict.
                A sixteen-digit number could be a card or an account reference, and the
                checks that apply to each are different — guessing silently would produce
                a confident answer to the wrong question.
              </P>
            </Section>

            {/* ── III · Verification ───────────────────────────────────── */}
            <Act
              numeral="ACT III"
                icon={ShieldCheckIcon}
              title="Verification"
              blurb="Two independent kinds of evidence: what the structure of a number proves, and what its statistics suggest."
            />

            <Section id="luhn" n="07" title="Luhn algorithm">
              <P>
                Card numbers carry a mod-10 checksum. It is computed by doubling every
                second digit from the right, subtracting 9 from any result above 9,
                and summing everything.
              </P>
              <Steps
                items={[
                  "Starting from the rightmost digit — the check digit — double every second digit.",
                  "Where doubling gives a value above 9, subtract 9.",
                  "Sum all the resulting values.",
                  "If the total is divisible by 10, the number passes.",
                ]}
              />
              <Figure label="Worked example · 4111 1111 1111 1111">
                <LuhnFigure />
              </Figure>
              <P>The issuer is identified separately, from the leading digits.</P>
              <Terms
                items={[
                  { term: "Visa", desc: <>Starts with <Code>4</Code></> },
                  { term: "Mastercard", desc: <>Starts with <Code>51–55</Code> or <Code>2221–2720</Code></> },
                  { term: "American Express", desc: <>Starts with <Code>34</Code> or <Code>37</Code></> },
                  { term: "Discover", desc: <>Starts with <Code>6011</Code> or <Code>65</Code></> },
                ]}
              />
            </Section>

            <Section id="benford" n="08" title="Benford's Law">
              <P>
                In datasets that span orders of magnitude, leading digits are not evenly
                distributed. A 1 leads about 30% of the time; a 9 leads under 5%. This is
                not a quirk of the data — it is what the arithmetic of scale produces.
              </P>
              <Figure label="Expected leading-digit distribution">
                <BenfordFigure />
              </Figure>
              <P>
                The system extracts leading digits from the input and compares the
                observed distribution against that expectation three ways.
              </P>
              <Terms
                items={[
                  { term: "Chi-square test", desc: "Measures overall deviation between observed and expected frequencies." },
                  { term: "Mean absolute deviation", desc: "An intuitive average distance from the expected values." },
                  { term: "Per-digit z-scores", desc: "Flags individual digits that deviate significantly on their own." },
                ]}
              />
              <P>
                Conforming data is treated as natural. Significant deviation suggests
                fabrication, rounding, or manipulation — because invented figures tend to
                be spread evenly, which is exactly what real ones are not.
              </P>
            </Section>

            <Section id="risk" n="09" title="Statistical risk assessment">
              <P>
                Findings are combined into a single score between 0 and 100, weighted by
                how much each one actually proves.
              </P>
              <Terms
                items={[
                  { term: "Luhn failure", desc: "A failed checksum is arithmetic, not inference, and carries heavy weight." },
                  { term: "Benford deviation", desc: "Higher chi-square or MAD values raise the score." },
                  { term: "Digit anomalies", desc: "Individual z-scores past their threshold each contribute." },
                  { term: "Format irregularities", desc: "Unexpected spacing, characters, or length patterns." },
                  { term: "Issuer mismatch", desc: "A card prefix matching no known issuer range." },
                ]}
              />
              <Figure label="Risk bands">
                <RiskScaleFigure />
              </Figure>
            </Section>

            {/* ── IV · Verdict ─────────────────────────────────────────── */}
            <Act
              numeral="ACT IV"
                icon={ScaleIcon}
              title="Verdict"
              blurb="Turning a pile of findings into one sentence — without hiding what produced it."
            />

            <Section id="evidence" n="10" title="Evidence generation">
              <P>
                Every analysis emits structured evidence, which is what the results screen
                renders rather than a bare score.
              </P>
              <Terms
                items={[
                  { term: "Luhn result", desc: "Pass or fail, with the checksum details." },
                  { term: "Benford metrics", desc: "Chi-square statistic, MAD value, per-digit z-scores." },
                  { term: "Digit distribution", desc: "Observed against expected frequencies, drawn." },
                  { term: "Classification", desc: "Detected type, confidence, and issuer identification." },
                  { term: "Risk breakdown", desc: "What each individual factor contributed." },
                ]}
              />
              <P>
                The point is that the verdict is inspectable. A tool that says
                &ldquo;fraud&rdquo; without showing its working is asking for trust it has
                not earned.
              </P>
            </Section>

            <Section id="verdict" n="11" title="Verdict logic">
              <Terms
                items={[
                  { term: "Likely valid", desc: "Structural checks pass, the distribution looks natural, risk is low." },
                  { term: "Insufficient evidence", desc: "Anomalies were found, but not enough to call it either way." },
                  { term: "Fraud detected", desc: "Critical indicators: a failed checksum, severe Benford deviation, or a high composite score." },
                ]}
              />
              <P>
                The verdict sits at the intersection of structural validity, statistical
                conformity, and composite risk. A single critical failure can override an
                otherwise clean result — a card that fails Luhn is invalid regardless of
                how natural its digits look.
              </P>
            </Section>

            {/* ── Reference ────────────────────────────────────────────── */}
            <Act
              numeral="REFERENCE"
                icon={SettingsIcon}
              title="Implementation"
              blurb="How the system is put together, what it exposes, and — importantly — what it cannot do."
            />

            <Section id="modes" n="12" title="Backend and client-side fallback">
              <Terms
                items={[
                  {
                    term: "Backend mode",
                    desc: "The full pipeline: Tesseract OCR, Groq-assisted classification, server-side Benford analysis and risk scoring. Active whenever the FastAPI service is reachable.",
                  },
                  {
                    term: "Client-side mode",
                    desc: "A deterministic fallback: regex classification, client-side Luhn, basic Benford, and simulated extraction for files.",
                  },
                ]}
              />
              <P>
                The frontend checks backend health on mount and degrades gracefully. Which
                mode produced a given result is always shown, because a fallback result
                presented as a real one would be worse than no result at all.
              </P>
            </Section>

            <Section id="api" n="13" title="API endpoints">
              <Terms
                items={[
                  { key: "health", term: <>GET <Code>/api/health</Code></>, desc: "Health check. Returns service status." },
                  { key: "classify", term: <>POST <Code>/api/classify</Code></>, desc: "Classifies a text value into candidate types with confidence scores." },
                  { key: "analyze", term: <>POST <Code>/api/analyze</Code></>, desc: "Full pipeline for a text value: classification, Benford, Luhn, risk scoring." },
                  { key: "upload", term: <>POST <Code>/api/analyze/upload</Code></>, desc: "Full pipeline for a file upload: OCR, then classification and analysis." },
                ]}
              />
              <P>
                Every endpoint requires an API key in the <Code>X-API-Key</Code> header,
                and CORS is scoped to the frontend origin.
              </P>
            </Section>

            <Section id="limitations" n="14" title="Limitations">
              <P>
                This is a research and teaching tool. The honest boundaries matter as much
                as the capabilities.
              </P>
              <Terms
                items={[
                  {
                    term: "Not production fraud detection",
                    desc: "Real systems draw on transaction history, behavioural signals and domain rules this has no access to.",
                  },
                  {
                    term: "Benford has preconditions",
                    desc: "It applies to naturally occurring figures spanning orders of magnitude — accounting data, census figures, addresses. It does not apply to assigned or constrained numbers like phone numbers and postcodes.",
                  },
                  {
                    term: "Luhn proves format, not authenticity",
                    desc: "A number can pass the checksum and still be stolen, expired, or entirely fabricated.",
                  },
                  {
                    term: "OCR inherits input quality",
                    desc: "A poorly lit photograph or a low-resolution scan produces bad text, and bad text produces bad analysis.",
                  },
                  {
                    term: "Single values are weak evidence",
                    desc: "Benford wants 50+ figures to say anything meaningful. One number rests almost entirely on structural checks.",
                  },
                ]}
              />
            </Section>

            <Reveal>
              <div className="border-hairline/60 mt-16 flex flex-col items-start gap-5 border-t pt-10">
                <p className={cn("text-muted-foreground text-body leading-[1.7]", MEASURE)}>
                  That is the whole pipeline. The best way to see it is to run something
                  through it.
                </p>
                <Link
                  href="/"
                  className="btn-gradient text-footnote inline-flex items-center gap-2 rounded-2xl px-6 py-3 font-semibold text-white transition-transform duration-(--dur-press) ease-(--spring-press) hover:-translate-y-px active:translate-y-0 active:scale-[0.98] motion-reduce:transition-none motion-reduce:hover:translate-y-0"
                >
                  <span>Analyze something</span>
                  <ArrowRightIcon className="size-4" />
                </Link>
              </div>
            </Reveal>
        </article>
      </div>
      </main>

      <MobileSheet
        open={contentsOpen}
        onClose={() => setContentsOpen(false)}
        label="Contents"
      >
        <nav aria-label="Sections" className="px-4 pb-2">
          <h2 className="text-micro text-muted-foreground/60 mb-1 px-2 font-mono font-semibold tracking-[0.18em] uppercase">
            Contents
          </h2>
          <ul className="flex flex-col">
            {RAIL.map((item) => (
              <li key={item.id}>
                {/* The act headings are what turn fifteen peers into four
                    groups plus an appendix. They are the same divisions the
                    document itself uses, so the menu and the page have one
                    shape between them rather than two. */}
                {item.act && (
                  <span className="text-orange-ink/70 mt-4 mb-1 block px-2 font-mono text-micro font-bold tracking-[0.18em] uppercase first:mt-1">
                    {item.act}
                  </span>
                )}
                <a
                  href={`#${item.id}`}
                  // The jump is done by hand, one frame later, because the
                  // sheet's scroll lock is released in an effect cleanup that
                  // has not run yet on this click — letting the browser handle
                  // the hash here would target a page that still cannot scroll.
                  onClick={(e) => {
                    e.preventDefault()
                    setContentsOpen(false)
                    requestAnimationFrame(() => {
                      const target = document.getElementById(item.id)
                      if (!target) return
                      // scroll-margin-top on the section is what clears the
                      // sticky header, so this needs no offset of its own.
                      target.scrollIntoView({
                        behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches
                          ? "auto"
                          : "smooth",
                        block: "start",
                      })
                      history.replaceState(null, "", `#${item.id}`)
                    })
                  }}
                  {...pressProps}
                  className="row-press text-footnote text-foreground flex min-h-12 items-center rounded-xl px-2 font-medium"
                >
                  {item.label}
                </a>
              </li>
            ))}
          </ul>
        </nav>
      </MobileSheet>
    </div>
  )
}
