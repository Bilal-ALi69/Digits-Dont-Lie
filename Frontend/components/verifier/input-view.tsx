"use client"

import { useEffect, useRef, useState } from "react"
import {
  ArrowRightIcon,
  BarChart3Icon,
  BrainCircuitIcon,
  CameraIcon,
  FileTextIcon,
  KeyboardIcon,
  ScanSearchIcon,
  ShieldCheckIcon,
  UploadCloudIcon,
  XIcon,
  SmartphoneIcon,
} from "lucide-react"

import { cn } from "@/lib/utils"
import { debugLog } from "@/lib/debug-log"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Segmented, type SegmentOption } from "@/components/ui/segmented"
import { BenfordCurve } from "@/components/verifier/benford-curve"
import { pressProps, sheenProps } from "@/components/verifier/sheen"

export interface AnalyzePayload {
  value: string
  source: "text" | "file"
  file?: { name: string; size: number; file: File }
}

interface InputViewProps {
  onAnalyze: (payload: AnalyzePayload) => void
}

const ACCEPTED = ["application/pdf", "image/jpeg", "image/png"]
// Matches the backend's _MAX_UPLOAD_BYTES (Backend/app/api/server.py) so
// oversized files are rejected instantly client-side instead of uploading
// megabytes only to be rejected by the server.
const MAX_FILE_SIZE = 10 * 1024 * 1024

// Shortest typed value that can produce any verification at all.
//
// Mirrors Backend/app/engines/card.py's format_check, which rejects anything
// under 13 digits as "Too short: N digits (minimum 13)". A card number is the
// only single value the backend can actually verify — a lone amount returns
// "no fraud determination can be made from a single amount", and an identifier
// returns "no specific validation rules available" — so below this length there
// is nothing to analyse and submitting only costs the user a round trip to be
// told so.
const MIN_VALUE_DIGITS = 13

function countDigits(value: string): number {
  return value.replace(/\D/g, "").length
}


/** The four capabilities, as rows rather than as a sentence.
 *
 *  Mobile only. The desktop hero states these twice — once inside a 40-word
 *  paragraph and again as a dot-separated run of labels — which works in a
 *  448px column beside a card. Stacked under the card on a phone the same
 *  content is a wall of grey text whose list wraps mid-item, and nothing in it
 *  can be scanned. The information is identical; only its shape changes.
 */
const CAPABILITIES = [
  {
    icon: ShieldCheckIcon,
    title: "Structural checks",
    desc: "Format, length, and checksum validation",
  },
  {
    icon: BarChart3Icon,
    title: "Statistical analysis",
    desc: "Benford's Law, chi-square, per-digit z-scores",
  },
  {
    icon: ScanSearchIcon,
    title: "OCR extraction",
    desc: "Reads figures straight off a document or photo",
  },
  {
    icon: BrainCircuitIcon,
    title: "AI classification",
    desc: "Identifies what a value actually represents",
  },
]

/** What to call the thing the user just attached, so the card can say "1 image
 *  added" rather than the vaguer "1 file added" when it knows better. */
function fileKindLabel(file: File): string {
  if (file.type.startsWith("image/")) return "1 image"
  if (file.type === "application/pdf") return "1 PDF"
  return "1 file"
}

/** The three ways in, as one row instead of a 320px stack.
 *
 *  Scan is always offered on a phone-width viewport rather than appearing once
 *  `canScan` resolves after mount — a tab materialising a frame late is a
 *  layout shift in the first thing the user looks at, and a narrow desktop
 *  window gets a straight explanation in the panel instead. */
type InputMode = "type" | "upload" | "scan"

const MODES: SegmentOption<InputMode>[] = [
  { value: "type", label: "Type", icon: KeyboardIcon },
  { value: "upload", label: "Upload", icon: UploadCloudIcon },
  { value: "scan", label: "Scan", icon: CameraIcon },
]

export function InputView({ onAnalyze }: InputViewProps) {
  const [text, setText] = useState("")
  const [file, setFile] = useState<File | null>(null)
  const [fileError, setFileError] = useState<string | null>(null)
  const [dragging, setDragging] = useState(false)
  const [mode, setMode] = useState<InputMode>("type")
  // Whether this device can actually open a camera. Starts false and is set
  // after mount: it depends on browser APIs the server cannot see, and
  // rendering a different answer on each side would be a hydration mismatch.
  const [canScan, setCanScan] = useState(false)
  const [scanNotice, setScanNotice] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)
  const cameraRef = useRef<HTMLInputElement>(null)

  const typedDigits = countDigits(text)
  // Only gate the typed path: an uploaded document is analysed as a whole and
  // has no digit count to satisfy.
  const typedTooShort = file === null && text.trim().length > 0 && typedDigits < MIN_VALUE_DIGITS
  const hasInput = text.trim().length > 0 || file !== null
  const canSubmit = hasInput && !typedTooShort

  // `capture` comes from the HTML Media Capture spec, which desktop browsers
  // parse and then ignore — the input silently falls back to a file picker. No
  // feature test distinguishes that, so ask the device what it is instead:
  // Chromium reports it directly, and elsewhere a coarse-only pointer means a
  // touch device rather than a mouse-driven one.
  useEffect(() => {
    const uaData = (navigator as { userAgentData?: { mobile?: boolean } }).userAgentData
    if (typeof uaData?.mobile === "boolean") {
      setCanScan(uaData.mobile)
      return
    }
    setCanScan(
      window.matchMedia("(pointer: coarse)").matches &&
        !window.matchMedia("(pointer: fine)").matches,
    )
  }, [])

  function pickFile(f: File | null) {
    debugLog("input-view.pickFile:called", { name: f?.name, type: f?.type, size: f?.size })
    if (!f) return
    if (!ACCEPTED.includes(f.type)) {
      debugLog("input-view.pickFile:rejected-type", { type: f.type })
      setFileError("Unsupported file type. Please upload a PDF, JPG, or PNG.")
      return
    }
    if (f.size > MAX_FILE_SIZE) {
      debugLog("input-view.pickFile:rejected-size", { size: f.size })
      setFileError(`File is too large (${(f.size / (1024 * 1024)).toFixed(1)} MB). Max size is 10 MB.`)
      return
    }
    debugLog("input-view.pickFile:accepted", { name: f.name })
    setFileError(null)
    setScanNotice(false)
    setFile(f)
    setText("")
  }

  function clearFile() {
    setFile(null)
    setFileError(null)
  }

  function openCamera() {
    debugLog("input-view.camera-button:clicked", { canScan })
    if (!canScan) {
      setScanNotice(true)
      return
    }
    cameraRef.current?.click()
  }

  function submit() {
    debugLog("input-view.submit:called", {
      hasInput,
      canSubmit,
      hasFile: !!file,
      textLength: text.trim().length,
      typedDigits,
    })
    if (!canSubmit) return
    if (file) {
      onAnalyze({ value: "", source: "file", file: { name: file.name, size: file.size, file } })
    } else {
      onAnalyze({ value: text.trim(), source: "text" })
    }
  }

  return (
    <>
      {/* Left column — hero */}
      {/* Pinned on lg in both axes, so nothing here reacts to the card's size.
          Fixed width with shrink disabled stops the two columns negotiating
          horizontal space; self-start stops the parent's items-center
          re-centring this column every time the card grows a row, which pushed
          the whole hero down by half the added height.

          lg:mt-10 replaces the -mt-10 that paired with centring: anchored to the
          top of the row, the column needs a positive offset to sit where
          centring used to put it. It is a fixed value, but now a stable one —
          the position no longer depends on how tall the card happens to be. */}
      {/* `max-sm:contents` is what makes the mobile reordering possible. It
          dissolves this column below 640px so its two groups become direct flex
          children of <main> alongside the card, and `order` can then interleave
          all three. Above 640px the div is an ordinary flex column and nothing
          about the desktop layout changes.

          The split into two groups is spacing-neutral on desktop: the outer gap
          of 20px now falls between the groups, and each group repeats it
          internally, so every gap in the column is still 20px. */}
      <div className="rise rise-1 flex flex-col items-start gap-5 text-left pl-4 lg:pl-0 lg:-ml-48 lg:mt-10 max-w-md lg:w-[28rem] lg:shrink-0 lg:self-start max-sm:contents">
        {/* ── Group 1: identity. Stays above the card on mobile — enough to say
            what this is, and nothing more. */}
        <div className="flex w-full flex-col items-start gap-5 max-sm:order-1 max-sm:mx-auto max-sm:max-w-md max-sm:gap-3">
        {/* The eyebrow the header's "Researchathon" pill used to carry before it
            was dropped at this width. Restated here, where there is room for it
            and where it is doing hierarchy work rather than fighting for space
            in a 56px bar. Mobile only. */}
        <span className="text-micro text-orange-ink bg-orange/12 ring-orange/20 hidden rounded-full px-2.5 py-1 font-mono font-semibold tracking-[0.14em] uppercase ring-1 ring-inset max-sm:inline-block">
          Researchathon Project
        </span>
        {/* Title */}
        {/* Tracking tightens as the type grows (§15): -0.028em at 32px against
            the -0.03em the display step carries at 48px. */}
        <h1 className="font-display text-display font-extrabold text-heading mb-4 max-sm:mb-0 max-sm:text-[2rem] max-sm:leading-[1.12] max-sm:tracking-[-0.028em]">
          Verify numbers &amp; documents.
          {/* .headline-sheen paints the glyphs with a gradient and moves it
              across once, so the accent line lights up as the hero settles.
              text-orange-ink stays as the fallback the class overrides — under
              reduced motion it is the colour that actually renders. */}
          <span className="headline-sheen text-orange-ink block">
            Digits never lie.
          </span>
        </h1>

        {/* Primary statement */}
        <p className="text-lead leading-relaxed text-foreground/80 font-medium max-sm:text-callout max-sm:leading-[1.5]">
          Fraud detection through mathematical certainty.
        </p>
        </div>

        {/* ── Group 2: the detail. Drops below the card on mobile, because on a
            phone this screen is a tool before it is a pitch — someone who
            opened it to check a number should not have to scroll past the
            argument to reach the input. */}
        <div className="flex w-full flex-col items-start gap-5 max-sm:order-3 max-sm:mx-auto max-sm:mt-3 max-sm:max-w-md">
        {/* Supporting paragraph — desktop only. Below 640px the rows further
            down carry the same four capabilities in a scannable shape. */}
        <p className="text-footnote leading-[1.65] text-muted-foreground max-w-sm max-sm:hidden">
          Analyzes numbers, documents, and datasets using deterministic
          validation, statistical analysis, OCR extraction, and
          AI-assisted classification to surface anomalies and verify integrity.
        </p>

        {/* Tech capability line — desktop only, same reason. It is a run of
            four labels separated by dots, which wraps mid-list at 390px. */}
        <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 font-mono text-mini font-medium tracking-wide text-muted-foreground/75 uppercase [&>span]:whitespace-nowrap max-sm:hidden">
          <span>Structural checks</span>
          <span className="size-[3px] rounded-full bg-muted-foreground/25" />
          <span>Statistical analysis</span>
          <span className="size-[3px] rounded-full bg-muted-foreground/25" />
          <span>OCR</span>
          <span className="size-[3px] rounded-full bg-muted-foreground/25" />
          <span>AI classification</span>
        </div>

        {/* Mobile equivalent. `hidden` by default so it can never reach the
            desktop layout, revealed only under the same 640px guard as
            everything else in this pass.

            A card of its own rather than four rows on the page background: on a
            phone this sits directly beneath the input card, and two adjacent
            blocks of content with only one of them on a surface read as the
            second having been forgotten. */}
        <div className="bg-surface-card m3x-container ring-hairline/60 hidden w-full max-w-full overflow-hidden p-4 shadow-sm ring-1 max-sm:block">
          <p className="text-micro text-muted-foreground/60 mb-2 font-mono font-semibold tracking-[0.16em] uppercase">
            What it checks
          </p>
          <ul className="divide-hairline/50 divide-y">
            {CAPABILITIES.map((c) => (
              <li key={c.title} className="flex items-start gap-3 py-3 last:pb-0">
                <span className="bg-orange/10 ring-orange/15 mt-px flex size-8 shrink-0 items-center justify-center rounded-xl ring-1 ring-inset">
                  <c.icon className="text-orange-ink size-4" />
                </span>
                <span className="min-w-0 flex-1">
                  <span className="text-footnote text-foreground block font-semibold">
                    {c.title}
                  </span>
                  <span className="text-caption text-muted-foreground mt-0.5 block leading-[1.5]">
                    {c.desc}
                  </span>
                </span>
              </li>
            ))}
          </ul>
        </div>

        {/* Was a bare 12px rule. The curve says the same thing the rule was
            gesturing at, and says it with the actual data. */}
        <div className="mt-3 w-full m3x-container max-sm:bg-surface-card max-sm:mt-0 max-sm:p-4 max-sm:shadow-sm max-sm:ring-1 max-sm:ring-hairline/60">
          <BenfordCurve />
        </div>
        </div>
      </div>

      {/* Right column — input card */}
      {/* lg:self-start anchors the card's top edge. The parent <main> centres
          its columns, so without this the card grows in both directions when
          the camera notice appears — half the new height pushes the whole panel
          upward, and it reads as the box jumping rather than expanding. Anchored
          at the top, it only ever grows downward. Applied here rather than on
          <main>, which also lays out the processing and results screens and
          should keep centring those. */}
      <div className="rise rise-3 mx-auto w-full max-w-md lg:mt-2 lg:w-[28rem] lg:shrink-0 lg:translate-x-[40%] lg:self-start relative max-sm:order-2">
        {/* ── Desktop card ───────────────────────────────────────────────────
            Unchanged. The mobile shell below is a separate tree rather than a
            pile of `max-sm:` overrides on this one, because what changed is the
            structure — three stacked options became one segmented row — and
            structure is not something a variant can express. Two trees sharing
            one set of state is the honest way to say that, and it means nothing
            written for the phone can reach this markup. */}
        <div className="max-sm:hidden">
        <div
          {...sheenProps}
          className="sheen-surface panel-raised bg-surface-card border-hairline/80 rounded-2xl border p-6"
        >
          <div className="relative z-10 flex flex-col gap-4">
            {/* Text input */}
            <div className="flex flex-col gap-2">
              <label htmlFor="value" className="text-footnote font-medium text-muted-foreground">
                Enter a value
              </label>
              <Input
                id="value"
                value={text}
                disabled={file !== null}
                onChange={(e) => setText(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.nativeEvent.isComposing && e.keyCode !== 229) {
                    submit()
                  }
                }}
                placeholder="e.g. 4111 1111 1111 1111"
                // Matches the backend's max_length on ManualInputRequest.value,
                // so a long paste is stopped here instead of making a round trip
                // to come back as a 422.
                maxLength={1000}
                className={cn(
                  "input-recessed h-11 rounded-xl font-mono text-foreground placeholder:text-muted-foreground",
                  typedTooShort && "border-warning/40",
                )}
                aria-invalid={typedTooShort || undefined}
                aria-describedby={typedTooShort ? "value-length-hint" : undefined}
                autoComplete="off"
                spellCheck={false}
              />
              {/* Says what is missing and how much, rather than leaving a
                  disabled button with no explanation. */}
              {typedTooShort && (
                <p
                  id="value-length-hint"
                  role="status"
                  className="text-mini leading-[1.5] text-warning"
                >
                  {typedDigits === 0
                    ? `Enter at least ${MIN_VALUE_DIGITS} digits — nothing shorter can be verified.`
                    : `${typedDigits} of ${MIN_VALUE_DIGITS} digits. Card numbers are 13–19 digits; shorter values cannot be verified.`}
                </p>
              )}
            </div>

            {/* Divider */}
            <div className="flex items-center gap-3">
              <span className="h-px flex-1 bg-border" />
              <span className="text-mini font-medium tracking-wider text-muted-foreground uppercase">
                or
              </span>
              <span className="h-px flex-1 bg-border" />
            </div>

            {/* File selected state and upload/camera options share one grid
                cell, so selecting a file swaps the contents without the card
                resizing under the cursor. The upload area stays mounted while
                a file is held — invisible and inert — purely to keep setting
                that height, which means no hard-coded pixel value can drift
                out of sync with what the upload area actually renders. */}
            <div className="grid">
              {file && (
                // min-w-0 on the grid cell as well as the text: a grid item's
                // default `min-width: auto` refuses to shrink below its content,
                // so a long file name pushed the whole card wider and `truncate`
                // never got the chance to do anything.
                <div className="unfold col-start-1 row-start-1 flex min-w-0 flex-col justify-center">
                  <p className="mb-1.5 text-mini font-medium tracking-wide text-muted-foreground uppercase">
                    {fileKindLabel(file)} added
                  </p>
                  <div className="flex w-full min-w-0 items-center gap-3 rounded-md border border-border bg-surface-inset p-3.5">
                    <span className="flex size-10 shrink-0 items-center justify-center rounded-xl bg-surface-raised text-muted-foreground">
                      <FileTextIcon className="size-5" />
                    </span>
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-sm font-medium text-foreground" title={file.name}>
                        {file.name}
                      </p>
                      <p className="text-xs text-muted-foreground">
                        {(file.size / 1024).toFixed(0)} KB
                      </p>
                    </div>
                    <Button
                      variant="ghost"
                      size="icon-sm"
                      aria-label="Remove file"
                      onClick={clearFile}
                      className="rounded-full text-muted-foreground hover:text-foreground"
                    >
                      <XIcon className="size-4" />
                    </Button>
                  </div>
                </div>
              )}

              <div
                className={cn(
                  "col-start-1 row-start-1 flex min-w-0 flex-col gap-2.5",
                  file && "invisible",
                )}
                inert={file !== null}
              >
                {/* Single upload target — one obvious action instead of two
                    competing halves, and the whole area accepts a drop. */}
                <button
                  type="button"
                  {...pressProps}
                  onClick={() => {
                    debugLog("input-view.upload-button:clicked", { refPresent: !!inputRef.current })
                    inputRef.current?.click()
                  }}
                  onDragOver={(e) => {
                    e.preventDefault()
                    setDragging(true)
                  }}
                  onDragLeave={() => setDragging(false)}
                  onDrop={(e) => {
                    e.preventDefault()
                    setDragging(false)
                    pickFile(e.dataTransfer.files?.[0] ?? null)
                  }}
                  className={cn(
                    "tactile-card group/upload flex w-full flex-col items-center gap-3 rounded-md border border-dashed border-border bg-surface-inset px-4 py-9 text-center outline-none active:scale-[0.99] focus-visible:border-orange focus-visible:ring-3 focus-visible:ring-orange/20",
                    dragging && "border-solid border-orange/50 bg-orange/5",
                  )}
                >
                  <span className="flex size-12 items-center justify-center rounded-full bg-surface-raised text-muted-foreground transition-colors group-hover/upload:text-orange-ink">
                    <UploadCloudIcon className="size-6" />
                  </span>
                  <div>
                    <span className="block text-body font-semibold text-foreground">
                      {dragging ? "Drop to upload" : "Upload a document"}
                    </span>
                    <span className="mt-0.5 block text-caption text-muted-foreground">
                      Drag it here, or click to browse · PDF, JPG, PNG
                    </span>
                  </div>
                </button>

                {/* Secondary path. Kept visible on desktop rather than hidden:
                    the feature exists, it simply needs a phone, and saying so is
                    more useful than pretending the option was never there. */}
                <button
                  type="button"
                  onClick={openCamera}
                  aria-describedby={scanNotice ? "scan-notice" : undefined}
                  {...pressProps}
                  className="group/camera flex items-center justify-center gap-2 rounded-md px-3 py-2 text-caption font-medium text-muted-foreground transition-colors duration-(--dur-press) ease-(--ease-standard) outline-none hover:bg-foreground/[0.04] hover:text-foreground focus-visible:ring-2 focus-visible:ring-orange/30"
                >
                  <CameraIcon className="size-3.5 opacity-70 transition-colors group-hover/camera:text-orange-ink" />
                  <span>Scan with camera</span>
                </button>

                {scanNotice && !canScan && (
                  <div
                    id="scan-notice"
                    role="status"
                    className="scan-notice flex items-start gap-2.5 rounded-md border border-orange/20 bg-orange/[0.06] px-3.5 py-3"
                  >
                    <SmartphoneIcon className="mt-px size-4 shrink-0 text-orange-ink" />
                    <div className="flex-1">
                      <p className="text-caption font-medium text-foreground">
                        Scanning needs a phone or tablet
                      </p>
                      <p className="mt-1 text-mini leading-[1.55] text-muted-foreground">
                        Desktop browsers can&apos;t open a camera from this control.
                        Open this page on your phone to scan, or upload a photo above.
                      </p>
                    </div>
                    <button
                      type="button"
                      onClick={() => setScanNotice(false)}
                      aria-label="Dismiss"
                      className="shrink-0 rounded-full p-0.5 text-muted-foreground transition-colors hover:text-foreground"
                    >
                      <XIcon className="size-3.5" />
                    </button>
                  </div>
                )}
              </div>
            </div>

            {fileError && (
              <p className="text-caption text-danger" role="alert">
                {fileError}
              </p>
            )}

            <Button
              size="lg"
              disabled={!canSubmit}
              onClick={submit}
              className="btn-gradient mt-1 h-12 rounded-md text-body font-semibold text-white disabled:opacity-40"
            >
              Analyze
              <ArrowRightIcon data-icon="inline-end" className="size-4" />
            </Button>
          </div>
        </div>
        </div>

        {/* ── Mobile card ────────────────────────────────────────────────────
            One surface, one row of choices, one panel. The desktop card shows
            all three input paths at once and separates the first two with an
            "OR" rule — about 320px of card spent making someone read every
            option before picking one, which is affordable in a column beside a
            hero and is most of the screen on a phone.

            Attaching a file replaces the whole control rather than sitting
            beneath it: at that point the choice has been made, and leaving the
            other two paths on screen invites the question of what tapping them
            would do to the file already held. */}
        <div className="hidden max-sm:block">
          <div className="bg-surface-card m3x-container card-mobile w-full max-w-full overflow-hidden border-hairline/70 border p-4">
            {file ? (
              <div className="unfold flex min-w-0 flex-col gap-3">
                <p className="text-micro text-muted-foreground/70 font-mono font-semibold tracking-[0.16em] uppercase">
                  {fileKindLabel(file)} ready to analyze
                </p>
                <div className="surface-tonal flex w-full min-w-0 items-center gap-3 rounded-[1.25rem] border p-3">
                  <span className="bg-surface-card text-orange-ink flex size-11 shrink-0 items-center justify-center rounded-2xl">
                    <FileTextIcon className="size-5" />
                  </span>
                  <div className="min-w-0 flex-1">
                    <p className="text-footnote text-foreground truncate font-semibold" title={file.name}>
                      {file.name}
                    </p>
                    <p className="text-caption text-muted-foreground">
                      {(file.size / 1024).toFixed(0)} KB
                    </p>
                  </div>
                </div>
                {/* A full-width row rather than a 28px X in the corner. Removing
                    the file is the only other thing that can be done from this
                    state, so it gets a real control instead of a hit target
                    that has to be aimed at. */}
                <button
                  type="button"
                  onClick={clearFile}
                  {...pressProps}
                  className="m3-press text-footnote text-muted-foreground flex min-h-11 items-center justify-center gap-2 rounded-full font-medium outline-none focus-visible:ring-2 focus-visible:ring-orange/30"
                >
                  <XIcon className="size-4" />
                  <span>Choose something else</span>
                </button>
              </div>
            ) : (
              <>
                <Segmented
                  options={MODES}
                  value={mode}
                  onChange={(next) => {
                    setMode(next)
                    setScanNotice(false)
                  }}
                  idPrefix="input"
                  aria-label="How to provide the value"
                />

                {/* Each panel is its own subtree keyed by mode, so switching
                    tabs re-runs .unfold and the new content eases in from the
                    control rather than replacing it on the same frame. */}
                <div className="mt-4">
                  {mode === "type" && (
                    <div
                      key="type"
                      role="tabpanel"
                      id="input-panel-type"
                      aria-labelledby="input-tab-type"
                      className="unfold flex flex-col gap-2"
                    >
                      <label
                        htmlFor="value-mobile"
                        className="text-footnote text-muted-foreground font-medium"
                      >
                        Enter a value
                      </label>
                      <Input
                        id="value-mobile"
                        value={text}
                        onChange={(e) => setText(e.target.value)}
                        onKeyDown={(e) => {
                          if (e.key === "Enter" && !e.nativeEvent.isComposing && e.keyCode !== 229) {
                            submit()
                          }
                        }}
                        placeholder="4111 1111 1111 1111"
                        maxLength={1000}
                        // inputMode numeric brings up the digit pad rather than
                        // the full keyboard. Not type="number": that would strip
                        // the spaces people naturally type into a card number.
                        inputMode="numeric"
                        className={cn(
                          "input-recessed h-14 rounded-2xl font-mono text-[1.0625rem] tracking-[0.01em] text-foreground placeholder:text-muted-foreground/60",
                          typedTooShort && "border-warning/40",
                        )}
                        aria-invalid={typedTooShort || undefined}
                        aria-describedby={typedTooShort ? "value-length-hint-mobile" : undefined}
                        autoComplete="off"
                        spellCheck={false}
                      />
                      {typedTooShort ? (
                        <p
                          id="value-length-hint-mobile"
                          role="status"
                          className="bg-warning-muted text-warning text-footnote rounded-xl px-3 py-2 leading-[1.5]"
                        >
                          {typedDigits === 0
                            ? `Enter at least ${MIN_VALUE_DIGITS} digits — nothing shorter can be verified.`
                            : `${typedDigits} of ${MIN_VALUE_DIGITS} digits. Card numbers are 13–19 digits; shorter values cannot be verified.`}
                        </p>
                      ) : (
                        <p className="text-caption text-muted-foreground/70 px-1">
                          A card number, an invoice figure, or any identifier of
                          13 digits or more.
                        </p>
                      )}
                    </div>
                  )}

                  {mode === "upload" && (
                    <div
                      key="upload"
                      role="tabpanel"
                      id="input-panel-upload"
                      aria-labelledby="input-tab-upload"
                      className="unfold"
                    >
                      <button
                        type="button"
                        {...pressProps}
                        onClick={() => {
                          debugLog("input-view.upload-button:clicked", {
                            refPresent: !!inputRef.current,
                          })
                          inputRef.current?.click()
                        }}
                        className="m3-press surface-tonal flex w-full flex-col items-center gap-2.5 rounded-[1.5rem] border px-4 py-8 text-center outline-none focus-visible:ring-3 focus-visible:ring-orange/25"
                      >
                        <span className="bg-surface-card text-orange-ink flex size-14 items-center justify-center rounded-full">
                          <UploadCloudIcon className="size-6" />
                        </span>
                        <span className="text-callout text-foreground block font-semibold">
                          Choose a document
                        </span>
                        <span className="text-caption text-muted-foreground block">
                          PDF, JPG or PNG · up to 10 MB
                        </span>
                      </button>
                    </div>
                  )}

                  {mode === "scan" && (
                    <div
                      key="scan"
                      role="tabpanel"
                      id="input-panel-scan"
                      aria-labelledby="input-tab-scan"
                      className="unfold"
                    >
                      <button
                        type="button"
                        {...pressProps}
                        onClick={openCamera}
                        aria-describedby={scanNotice ? "scan-notice-mobile" : undefined}
                        className="m3-press surface-tonal flex w-full flex-col items-center gap-2.5 rounded-[1.5rem] border px-4 py-8 text-center outline-none focus-visible:ring-3 focus-visible:ring-orange/25"
                      >
                        <span className="bg-surface-card text-orange-ink flex size-14 items-center justify-center rounded-full">
                          <CameraIcon className="size-6" />
                        </span>
                        <span className="text-callout text-foreground block font-semibold">
                          Open the camera
                        </span>
                        <span className="text-caption text-muted-foreground block">
                          Point it at the number and take one photo
                        </span>
                      </button>

                      {/* Only reachable when this shell is being rendered in a
                          narrow desktop window, since `capture` is honoured on
                          every real phone. Saying so beats a control that
                          silently opens a file picker instead. */}
                      {scanNotice && !canScan && (
                        <div
                          id="scan-notice-mobile"
                          role="status"
                          className="scan-notice border-orange/20 bg-orange/[0.06] mt-3 flex items-start gap-2.5 rounded-xl border px-3.5 py-3"
                        >
                          <SmartphoneIcon className="text-orange-ink mt-px size-4 shrink-0" />
                          <p className="text-caption text-muted-foreground flex-1 leading-[1.55]">
                            <span className="text-foreground font-medium">
                              Scanning needs a phone or tablet.
                            </span>{" "}
                            This browser can&apos;t open a camera from the page — use
                            Upload instead.
                          </p>
                        </div>
                      )}
                    </div>
                  )}
                </div>
              </>
            )}

            {/* The primary action lives on the card, the same way the desktop
                shell keeps it — labelled for what will actually run, so
                "Analyze document" names the file already attached. */}
            <Button
              size="lg"
              disabled={!canSubmit}
              onClick={submit}
              {...pressProps}
              className="btn-gradient m3-press btn-liquid m3x-morph mt-4 h-14 w-full text-callout font-semibold text-white disabled:opacity-55"
            >
              {file ? "Analyze document" : "Analyze"}
              <ArrowRightIcon data-icon="inline-end" className="size-4" />
            </Button>

            {fileError && (
              <p className="text-footnote text-danger mt-3" role="alert">
                {fileError}
              </p>
            )}
          </div>
        </div>

        {/* One pair of file inputs for both shells. They sit outside either so
            neither tree can end up owning a ref the other one needs. */}
        <input
          ref={inputRef}
          type="file"
          accept=".pdf,.jpg,.jpeg,.png"
          // NOT `hidden`. iOS Safari ignores a programmatic .click() on a
          // display:none file input, which is why Upload and Scan did
          // nothing on a phone while working on desktop. sr-only keeps the
          // element in the layout tree, where the click is honoured.
          className="sr-only"
          onChange={(e) => pickFile(e.target.files?.[0] ?? null)}
        />
        <input
          ref={cameraRef}
          type="file"
          accept="image/*"
          capture="environment"
          className="sr-only"
          onChange={(e) => pickFile(e.target.files?.[0] ?? null)}
        />

        </div>

      </>
  )
}
