"use client"

import { useEffect, useLayoutEffect, useState, useCallback, useRef } from "react"

import {
  analyze as clientAnalyze,
  classify as clientClassify,
  isAmbiguous,
  simulateExtraction,
  type AnalysisResult,
  type Candidate,
  type DocType,
} from "@/lib/verifier"
import {
  checkHealth,
  analyzeValue,
  analyzeUpload,
  mapAnalysisResult,
  classifyValue,
  dedupeByType,
  classifyImage,
  type BackendAnalysisResponse,
  type ImageGuess,
} from "@/lib/api"
import { cn } from "@/lib/utils"
import { debugLog } from "@/lib/debug-log"
import { AppHeader } from "@/components/verifier/app-header"
import { AmbientBackground } from "@/components/verifier/ambient-background"
import { InputView, type AnalyzePayload } from "@/components/verifier/input-view"
import { ProcessingView } from "@/components/verifier/processing-view"
import { ConfirmView } from "@/components/verifier/confirm-view"
import { ResultsView } from "@/components/verifier/results-view"

/** useLayoutEffect on the client, useEffect on the server.
 *
 *  React warns when useLayoutEffect runs during server rendering, and this is a
 *  client component that Next still renders on the server. The distinction only
 *  matters on the client anyway: there is no paint to beat on the server, and
 *  the first render is always the input stage with no transition in flight. */
const useIsomorphicLayoutEffect =
  typeof window !== "undefined" ? useLayoutEffect : useEffect

type Stage = "input" | "processing" | "confirm" | "results"

interface Pending {
  value: string
  rawText: string
  candidates: Candidate[]
  steps: string[]
  classificationId?: string
  file?: File
  source: "text" | "file"
  /** Vision's read on an uploaded image, used to narrate the processing screen. */
  guess?: ImageGuess | null
  /** Whether a vision verdict is coming, so its row can be held open up front. */
  expectsGuess?: boolean
}

/** Longest the processing screen will wait on a vision verdict before moving on.
 *  Sits just past the upload narration (5 lines × 1s) so a prompt answer is
 *  always shown, while a slow one costs the user roughly a second, not thirty. */
const GUESS_HOLD_MS = 6000

/** How long the outgoing view is held on screen to animate away before the
 *  incoming one mounts. Drives the animation duration directly (inline style on
 *  <main>) so the CSS and the timer here cannot drift apart. */
const STAGE_EXIT_MS = 200

/** Below this, the app asks the user which type it is rather than assuming.
 *  Above it, the identification is treated as settled and analysis proceeds. */
const CONFIRM_CONFIDENCE_THRESHOLD = 0.9

/** How long the identification chip is shown before the results replace it, so
 *  a verdict that lands at the very end of the run is actually readable. */
const VERDICT_CHIP_MS = 1400

/** Backend document types, mapped for the processing screen's chip. Analysis
 *  identifies a document deterministically — a page stating a subtotal and a
 *  total that reconcile is an invoice — so the chip no longer depends on the
 *  vision service being reachable, which it frequently is not (a daily token
 *  cap or a decommissioned model both silently produce no guess at all). */
const RESULT_TYPE_TO_GUESS: Record<string, string> = {
  document: "invoice",
  card: "credit_card",
  invoice: "invoice",
  amount: "transaction_document",
  id: "national_id",
}

/** Collapse the backend's value-type vocabulary onto the four types this UI
 *  offers. Anything identity-like (passport, licence, national ID…) lands on
 *  "id", which is the bucket that carries those checks. */
function backendTypeToDocType(valueType: string): DocType {
  if (valueType === "card_number") return "card"
  if (valueType === "financial_amount") return "amount"
  if (valueType === "invoice_number") return "invoice"
  return "id"
}

const DOC_TYPE_LABELS: Record<DocType, string> = {
  card: "Card Number",
  amount: "Financial Amount",
  invoice: "Invoice Number",
  id: "ID Number",
  document: "Document",
}

/** Turn a vision verdict into ranked candidates.
 *
 * An uploaded file has no client-side value to classify — the digits only exist
 * after server-side OCR — so classify("") scored every type at 0% and the
 * confirm screen offered four indistinguishable options. Vision has already
 * identified the document, so use that instead of nothing.
 */
function candidatesFromGuess(guess: ImageGuess): Candidate[] {
  const top = backendTypeToDocType(guess.value_type)
  // Spread the remaining probability evenly over the alternatives rather than
  // asserting a ranking vision never expressed.
  const rest = (1 - guess.confidence) / 3
  return [
    { type: top, label: DOC_TYPE_LABELS[top], confidence: guess.confidence },
    ...(["card", "amount", "invoice", "id"] as DocType[])
      .filter((t) => t !== top)
      .map((t) => ({ type: t, label: DOC_TYPE_LABELS[t], confidence: rest })),
  ]
}

const DOC_TYPE_TO_BACKEND: Record<DocType, string> = {
  card: "card_number",
  amount: "financial_amount",
  invoice: "invoice_number",
  id: "generic_identifier",
  // Not a *value* type, so it has no counterpart in the confirm flow; present
  // only because this map must cover every DocType.
  document: "",
}

export function VerifierApp() {
  const [stage, setStage] = useState<Stage>("input")
  const [pending, setPending] = useState<Pending | null>(null)
  const [result, setResult] = useState<AnalysisResult | null>(null)
  const [backendAvailable, setBackendAvailable] = useState<boolean | null>(null)
  const [apiError, setApiError] = useState<string | null>(null)
  // True while the vision request is in flight, so the processing screen holds
  // instead of advancing to results before the verdict has been shown.
  const [guessPending, setGuessPending] = useState(false)
  const pendingRef = useRef(pending)
  pendingRef.current = pending
  const healthCheckRef = useRef<Promise<boolean> | null>(null)

  /* ─── Stage transitions ────────────────────────────────────────────────────
     A stage change used to be a bare conditional swap: the outgoing view was
     gone on the same frame the incoming one mounted, which read as a hard cut
     followed by a slow cascade.

     It cannot be fixed by holding `stage` back alone, because `pending` and
     `result` are cleared in the same tick — a view held open on live state
     would render empty. So the outgoing view is rendered from a frozen
     snapshot of the state as it was when it was last on screen, and only the
     incoming view reads live state.
     --------------------------------------------------------------------- */
  type StageSnapshot = {
    stage: Stage
    pending: Pending | null
    result: AnalysisResult | null
    guessPending: boolean
  }
  const [leavingStage, setLeavingStage] = useState<Stage | null>(null)
  // What is on screen right now. Deliberately updated in an effect, so the
  // detector below sees the previous commit's values rather than the new ones.
  const shownRef = useRef<StageSnapshot>({ stage, pending, result, guessPending })
  const frozenRef = useRef<StageSnapshot | null>(null)
  // A ref rather than the `leavingStage` state because both effects below run
  // within a single commit, and under StrictMode twice: a state value read from
  // a render closure is stale by the time the second effect sees it, which let
  // the snapshot be overwritten between the two invocations and stranded the
  // view at opacity 0 with no timer left to clear it.
  const leavingRef = useRef(false)

  /* A layout effect, not a passive one, and that is the whole fix for the
     transition flicker.

     Passive effects run *after* the browser paints. So on the commit where
     `stage` changes, `leavingStage` was still null, the incoming view was
     painted for one frame, and only then did this effect swap the outgoing view
     back in to animate away — the next screen flashing up, the current one
     returning, then the transition.

     A layout effect runs after React has mutated the DOM but before the browser
     paints, and the setState below forces a synchronous re-render within the
     same frame. The incoming view therefore reaches the DOM but is never
     painted, and what the user sees is the outgoing view animating out.

     (The earlier attempt at this derived the outgoing snapshot during render
     instead. That painted correctly on the way in and then stranded the view:
     once the exit timer cleared `leavingRef`, the derivation still saw a stale
     `shownRef` and re-selected the *outgoing* stage, with only a ref mutation —
     which triggers no re-render — to correct it. The result was a stage stuck
     on screen until unrelated state moved: the first Analyze looking like a
     page reset, and the processing screen hanging forever after it.)

     Declared before the effect that refreshes shownRef, so on the commit where
     `stage` changes this still holds the outgoing view's data. */
  useIsomorphicLayoutEffect(() => {
    // While a view is leaving this must still re-arm the timer even when the
    // stage matches what is painted: this effect's cleanup has just cancelled
    // the previous one, and returning here would leave the view stranded at
    // opacity 0 with nothing left to clear it. Reachable by changing stage
    // twice inside one exit and landing back where the exit started.
    if (shownRef.current.stage === stage && !leavingRef.current) return
    // Already animating something out (a second stage change inside one exit,
    // or StrictMode's re-invocation): keep the view that is actually painted.
    if (!leavingRef.current) {
      leavingRef.current = true
      frozenRef.current = shownRef.current
      setLeavingStage(shownRef.current.stage)
    }
    const t = setTimeout(() => {
      leavingRef.current = false
      frozenRef.current = null
      setLeavingStage(null)
    }, STAGE_EXIT_MS)
    return () => clearTimeout(t)
  }, [stage])

  useEffect(() => {
    // Frozen while a view is leaving: shownRef must keep describing what is
    // actually painted, not what the state has already moved on to.
    if (leavingRef.current) return
    shownRef.current = { stage, pending, result, guessPending }
  })

  useEffect(() => {
    debugLog("verifier-app.healthCheck:starting")
    healthCheckRef.current = checkHealth().then((h) => {
      const ok = h !== null
      debugLog("verifier-app.healthCheck:result", { ok, response: h })
      setBackendAvailable(ok)
      return ok
    })
  }, [])

  useEffect(() => {
    debugLog("verifier-app.render:stage-changed", { stage })
  }, [stage])

  const runAnalysis = useCallback(async (
    value: string,
    rawText: string,
    backend: boolean,
    file?: File,
    confirmedValueType?: string,
    classificationId?: string,
    visionGuess?: ImageGuess | null,
  ): Promise<AnalysisResult> => {
    if (backend) {
      let apiResult: BackendAnalysisResponse
      if (file) {
        apiResult = await analyzeUpload(file, visionGuess)
      } else {
        apiResult = await analyzeValue(value, confirmedValueType, undefined, classificationId)
      }
      return mapAnalysisResult(apiResult, value, rawText, file)
    }
    // Client-side fallback
    const candidates = clientClassify(value)
    const type = candidates[0].type
    const res = clientAnalyze(value, type, rawText)
    if (file) res.imageFile = file
    return res
  }, [])

  async function handleAnalyze(payload: AnalyzePayload) {
    debugLog("verifier-app.handleAnalyze:called", {
      source: payload.source,
      backendAvailable,
      fileName: payload.file?.name,
    })
    setApiError(null)
    let value = payload.value
    let rawText = payload.value
    let steps: string[]
    let file: File | undefined
    let source: "text" | "file" = payload.source === "file" ? "file" : "text"

    // backendAvailable may still be null while the initial health check is
    // in flight (e.g. user submits immediately on page load). Awaiting the
    // in-flight promise here avoids racing straight into the weaker
    // client-side fallback just because the check hadn't resolved yet.
    const useApi =
      backendAvailable === null
        ? await (healthCheckRef.current ?? Promise.resolve(false))
        : backendAvailable

    debugLog("verifier-app.handleAnalyze:useApi-decision", { useApi, backendAvailableAtCallTime: backendAvailable })

    // Surface this immediately, not just on a mid-flight upload failure —
    // otherwise the offline fallback fires silently and the fabricated
    // result (see lib/verifier.ts simulateExtraction) looks like a real
    // backend response with no indication anything went wrong.
    if (!useApi) {
      debugLog("verifier-app.handleAnalyze:OFFLINE-FALLBACK will be used (demo/simulated result)")
      setApiError("/api/health check failed — see browser console for details")
    }

    if (payload.source === "file" && payload.file) {
      file = payload.file.file ?? undefined
      if (!useApi) {
        value = simulateExtraction(payload.file.name, payload.file.size)
        rawText = `Source: ${payload.file.name}\nExtracted candidate: ${value}`
      } else {
        rawText = `Source: ${payload.file.name}`
      }
      // Narration names the stage actually running, so the wait explains itself.
      steps = useApi
        ? [
            "Uploading your document\u2026",
            "Reading the document layout\u2026",
            "Extracting text with OCR\u2026",
            "Running structural and statistical checks\u2026",
            "Scoring risk and writing the verdict\u2026",
          ]
        : ["Extracting text\u2026", "Classifying the value\u2026", "Running checks\u2026"]
    } else {
      steps = useApi
        ? [
            "Classifying what this value represents\u2026",
            "Running structural and format checks\u2026",
            "Testing digit distribution against Benford\u2019s Law\u2026",
            "Scoring risk and writing the verdict\u2026",
          ]
        : ["Parsing input\u2026", "Classifying the value\u2026", "Running checks\u2026"]
    }

    let candidates: Candidate[]
    let classificationId: string | undefined

    if (useApi && payload.source === "text") {
      try {
        const cls = await classifyValue(value)
        // backendTypeToDocType is many-to-one: transaction_id and
        // generic_identifier both become "id". Two candidates sharing a type
        // are one choice on the confirm screen — rendered as two buttons they
        // collided on React's key, and because selection is tracked by type,
        // clicking either highlighted both and neither could be picked alone.
        candidates = dedupeByType(
          cls.value_candidates.map((vc) => ({
            type: backendTypeToDocType(vc.type),
            label: vc.label,
            confidence: vc.confidence,
          })),
        )
        classificationId = cls.classification_id
        if (candidates.length === 0) candidates = clientClassify(value)
      } catch {
        candidates = clientClassify(value)
      }
    } else {
      candidates = clientClassify(value)
    }

    // Open the processing screen before asking vision anything. The call takes
    // seconds, and awaiting it here left the user on the input form with no
    // feedback at all — the wait now happens with the animation already running.
    const expectsGuess = Boolean(useApi && payload.source === "file" && file)
    setPending({ value, rawText, candidates, steps, classificationId, file, source, guess: null, expectsGuess })
    setGuessPending(expectsGuess)
    setStage("processing")

    if (expectsGuess && file) {
      // Measured Groq latency for this call swings between ~3s and ~28s, so the
      // screen must not be held hostage to it. Stop waiting after the deadline
      // and let analysis proceed; a verdict arriving later still populates the
      // chip if the run is somehow still here, and is simply dropped otherwise.
      // Nothing is lost by giving up: the backend runs its own vision pass
      // during analysis, so the verdict still reaches the final report.
      const releaseHold = setTimeout(() => setGuessPending(false), GUESS_HOLD_MS)

      classifyImage(file)
        .then((g) => {
          debugLog("verifier-app.handleAnalyze:image-guess", { guess: g })
          // Merge rather than replace: handleConfirm and friends read this same
          // object, and the run may have advanced while the request was in flight.
          // Candidates are rebuilt from the verdict because the ones computed at
          // submit time came from an empty string and scored every type at 0%.
          setPending((prev) =>
            prev
              ? { ...prev, guess: g, candidates: g ? candidatesFromGuess(g) : prev.candidates }
              : prev,
          )
        })
        .finally(() => {
          clearTimeout(releaseHold)
          setGuessPending(false)
        })
    }
  }

  function handleProcessingComplete() {
    const p = pendingRef.current
    debugLog("verifier-app.handleProcessingComplete:called", { backendAvailable, source: p?.source })
    if (!p) return

    // Manually typed values always route through confirmation: the classifier
    // works from format alone, so "16 digits" cannot distinguish a card from any
    // other long number, and the user needs to see the confidence and correct it.
    // Uploads stay automatic — their type is inferred from document content.
    // This runs before the backend branch because that branch used to auto-apply
    // candidates[0] without ever consulting isAmbiguous, so confirmation never
    // appeared whenever the backend was reachable.
    // An upload has no client-side value to classify — the digits only exist
    // after server-side OCR — so its candidates are meaningless unless vision
    // supplied them. Asking to choose between four options all scored 0% is
    // worse than not asking: the backend classifies the document itself during
    // analysis, so defer to it rather than presenting an empty choice.
    const hasUsableCandidates = (p.candidates[0]?.confidence ?? 0) > 0
    // An upload is confirmed when the identification is not confident enough to
    // act on alone. `isAmbiguous` additionally catches a top choice that is
    // confident but barely ahead of the runner-up.
    const belowThreshold =
      (p.candidates[0]?.confidence ?? 0) < CONFIRM_CONFIDENCE_THRESHOLD
    const needsConfirm =
      p.source === "text" ||
      (hasUsableCandidates && (belowThreshold || isAmbiguous(p.candidates)))

    if (needsConfirm) {
      debugLog("verifier-app.handleProcessingComplete:routing to confirm", {
        source: p.source,
        ambiguous: isAmbiguous(p.candidates),
        topConfidence: p.candidates[0]?.confidence,
      })
      setStage("confirm")
      return
    }

    debugLog("verifier-app.handleProcessingComplete:skipping confirm", {
      source: p.source,
      hasUsableCandidates,
      topConfidence: p.candidates[0]?.confidence,
    })

    if (backendAvailable === true) {
      // Only assert a type when something actually determined one. Forwarding
      // the first of four zero-confidence candidates would pin the backend to an
      // arbitrary type; leaving it undefined lets it classify from the document.
      const topCandidate = hasUsableCandidates ? p.candidates[0] : undefined
      const confirmedType = topCandidate ? DOC_TYPE_TO_BACKEND[topCandidate.type] : undefined

      runAnalysis(p.value, p.rawText, true, p.file, confirmedType, p.classificationId, p.guess)
        .then((r) => {
          debugLog("verifier-app.handleProcessingComplete:REAL backend result -> results screen", {
            verdict: r.verdict,
            type: r.type,
            score: r.score,
          })

          // Analysis has now identified the document. Show that on the
          // processing screen before the results replace it: the user watched a
          // progress animation for several seconds and the identification is
          // the first thing it has actually been able to tell them.
          const identified = r.candidates[0]
          if (p.file && identified && !p.guess) {
            setPending((prev) =>
              prev
                ? {
                    ...prev,
                    guess: {
                      document_type: RESULT_TYPE_TO_GUESS[r.type] ?? "other",
                      value_type: r.type,
                      confidence: identified.confidence,
                      reason: "Identified from the document's own structure",
                    },
                  }
                : prev,
            )
            setTimeout(() => {
              setResult(r)
              setStage("results")
            }, VERDICT_CHIP_MS)
            return
          }

          setResult(r)
          setStage("results")
        })
        .catch((err) => {
          console.error("Backend upload failed:", err)
          debugLog("verifier-app.handleProcessingComplete:backend call FAILED -> falling back to client-side demo result", {
            error: err instanceof Error ? err.message : String(err),
          })
          setApiError(err instanceof Error ? err.message : "Backend analysis failed")
          const type = p.candidates[0].type
          setResult(clientAnalyze(p.value, type, p.rawText))
          setStage("results")
        })
      return
    }

    // Client-side path. Ambiguous and text-sourced inputs already returned above,
    // so anything reaching here is a confidently classified upload.
    debugLog("verifier-app.handleProcessingComplete:backendAvailable is not true -> using client-side/demo path", {
      backendAvailable,
    })
    const type = p.candidates[0].type
    setResult(clientAnalyze(p.value, type, p.rawText))
    setStage("results")
  }

  function handleConfirm(type: DocType) {
    const p = pendingRef.current
    if (!p) return

    if (backendAvailable === true) {
      const confirmedType = DOC_TYPE_TO_BACKEND[type]
      runAnalysis(p.value, p.rawText, true, p.file, confirmedType, p.classificationId, p.guess)
        .then((r) => {
          setResult(r)
          setStage("results")
        })
        .catch((err) => {
          // Must report, not just recover. This is the path every manually
          // typed value takes (typed input always routes through confirm), so
          // a backend that dies here is the most likely failure a viewer will
          // ever see — and without setApiError it fell through to the offline
          // engine in complete silence. The fabricated client-side result then
          // renders identically to a real one, which is the exact failure the
          // health-check branch in handleAnalyze already refuses to allow.
          console.error("Backend analysis failed after confirm:", err)
          setApiError(err instanceof Error ? err.message : "Backend analysis failed")
          setResult(clientAnalyze(p.value, type, p.rawText))
          setStage("results")
        })
      return
    }

    setResult(clientAnalyze(p.value, type, p.rawText))
    setStage("results")
  }

  function handleReset() {
    setResult(null)
    setPending(null)
    setStage("input")
    setApiError(null)
    // Clear the in-flight flag too: a stale true would make the next run's
    // processing screen hold forever waiting on a request that already settled.
    setGuessPending(false)
  }

  // While a view is leaving it renders from the frozen snapshot; otherwise from
  // live state, so a mounted view still receives updates (the processing screen
  // needs `guessPending` and a vision verdict arriving mid-run).
  //
  // No render-time fallback to shownRef here: the exit is registered in a
  // layout effect above, so `leavingStage` is already set by the time anything
  // is painted, and falling back to a ref during render is what stranded the
  // view previously.
  const shown: StageSnapshot =
    leavingStage !== null && frozenRef.current
      ? frozenRef.current
      : { stage, pending, result, guessPending }

  return (
    <div className="bg-surface-page min-h-screen text-foreground pt-16 flex flex-col max-sm:w-full max-sm:max-w-full max-sm:overflow-hidden max-sm:pt-[calc(3.5rem+env(safe-area-inset-top))]">
      {/* First child, so it paints above this wrapper's own background and below
          every sibling that follows — all of which now carry an explicit z-index
          for exactly that reason. */}
      <AmbientBackground />
      <AppHeader />
      {/* Fades content into the header's bottom edge. It washes with --nav
          rather than --surface-page: the page colour is opaque, and painting an
          opaque strip over the drifting ambient field punched a visible
          rectangle out of it. --nav is the same colour the bar itself uses, at
          the same alpha, so the strip reads as the bar's own falloff. */}
      <div className="pointer-events-none fixed top-16 right-0 left-0 z-30 h-10 bg-gradient-to-b from-[var(--nav)] to-transparent max-sm:top-[calc(3.5rem+env(safe-area-inset-top))]" />
      {/* Outside <main> on purpose: the exit animation puts a transform on it,
          which would make this fixed banner position against <main> instead of
          the viewport for the length of the animation. */}
      {apiError && (
        <div className="rise fixed top-20 left-1/2 -translate-x-1/2 z-50 max-w-[90vw] rounded-xl border border-warning/30 bg-warning-muted px-4 py-2 text-footnote text-warning shadow-sm backdrop-blur-md max-sm:top-[calc(4.25rem+env(safe-area-inset-top))]">
          Backend request failed — showing client-side analysis instead. ({apiError})
        </div>
      )}
      <main
        className={cn(
          "relative z-10 max-w-6xl mx-auto px-6 py-14 flex flex-col lg:flex-row items-center justify-center gap-16 lg:gap-24 flex-1",
          // Mobile: px comes from .safe-x (≥1rem + notches). The pb clears the
          // pinned action bar (~5rem + inset) with room to spare, so the
          // bottom-most text scrolls fully above it; w-full/overflow-hidden
          // keep every 1.75rem corner inside the viewport.
          "safe-x max-sm:pt-6 max-sm:pb-[calc(9rem+env(safe-area-inset-bottom))] max-sm:w-full max-sm:max-w-full max-sm:overflow-hidden max-sm:gap-8",
          leavingStage !== null && "stage-leaving",
        )}
        style={leavingStage !== null ? { animationDuration: `${STAGE_EXIT_MS}ms` } : undefined}
      >
        {shown.stage === "input" && <InputView onAnalyze={handleAnalyze} />}
        {shown.stage === "processing" && shown.pending && (
          <ProcessingView
            steps={shown.pending.steps}
            guess={shown.pending.guess}
            waiting={shown.guessPending}
            expectsGuess={shown.pending.expectsGuess}
            file={shown.pending.file}
            value={shown.pending.source === "text" ? shown.pending.value : undefined}
            onComplete={handleProcessingComplete}
          />
        )}
        {shown.stage === "confirm" && shown.pending && (
          <ConfirmView
            value={shown.pending.value}
            candidates={shown.pending.candidates}
            onConfirm={handleConfirm}
          />
        )}
        {shown.stage === "results" && shown.result && (
          <ResultsView result={shown.result} onReset={handleReset} />
        )}
      </main>
      {/* pb clears the pinned action bar (56px control + bar padding) plus the
          home indicator, so the footer is never hidden beneath it. */}
      <footer className="relative z-10 border-t border-hairline/60 py-6 text-center safe-x max-sm:pt-5 max-sm:pb-[calc(6.5rem+env(safe-area-inset-bottom))]">
        <p className="text-mini text-muted-foreground">
          <span className="font-display font-bold">Digits Don&apos;t Lie</span> &mdash; Researchathon Project &middot; Benford&apos;s Law &middot; Luhn Algorithm &middot; Statistical Fraud Detection
        </p>
        <p className="text-micro text-muted-foreground/60 mt-1">
          Project by <span className="text-muted-foreground/80 font-medium">Bilal Ali</span> &middot; Class <span className="text-muted-foreground/80 font-medium">E4</span>
        </p>
        {backendAvailable !== null && (
          <p className="text-micro text-muted-foreground/50 mt-1">
            Backend: {backendAvailable ? "Connected" : "Offline (client-side mode)"}
          </p>
        )}
      </footer>
    </div>
  )
}
