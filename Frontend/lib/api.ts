// API client for the Digits Dont Lie backend.
// Calls this app's own /api/* route handlers (see app/api/**/route.ts), which
// hold the real backend URL and X-API-Key server-side and proxy the request
// through. The browser never sees the backend's shared secret.

function headers(): Record<string, string> {
  return { "Content-Type": "application/json" }
}

// ---- Backend response types (mirrors Backend/app/models.py) ----

export interface BackendEvidence {
  check: string
  category: string
  status: "passed" | "failed" | "warning" | "not_applicable" | "unknown" | "unavailable" | "requires_review"
  confidence: number
  severity: string
  message: string
  details: Record<string, unknown>
}

export interface BackendClassificationCandidate {
  type: string
  label: string
  confidence: number
  reason: string
  layer: string
}

export interface BackendRiskAssessment {
  risk_score: number
  confidence: number
  level: string
  /** Checks that actually returned a verdict, vs. checks attempted. Drives the
   *  "n of m checks could not run" caveat rather than a second dial. */
  checks_determinate?: number
  checks_total?: number
}

export interface BackendAnalysisResponse {
  request_id: string
  timestamp: string
  input_classification: {
    type: string
    confidence: number
    evidence: string[]
    candidates: BackendClassificationCandidate[]
  } | null
  classification_source: string
  extracted_data: Record<string, unknown>
  checks: BackendEvidence[]
  statistical_analysis: Record<string, unknown>
  consistency_analysis: Record<string, unknown>
  risk_assessment: BackendRiskAssessment | null
  overall_status: string
  limitations: string[]
  recommendation: string
  explanation: string
  document_candidates: BackendClassificationCandidate[]
  value_candidates: BackendClassificationCandidate[]
  top_document_type: string
  top_value_type: string
  display_status: string
}

export interface BackendClassificationResponse {
  request_id: string
  classification_id: string
  input_value: string
  candidates: BackendClassificationCandidate[]
  recommended_type: string
  recommended_label: string
  document_candidates: BackendClassificationCandidate[]
  value_candidates: BackendClassificationCandidate[]
  top_document_type: string
  top_value_type: string
}

// ---- Frontend-mapped types ----

// "document" covers whole financial documents (an invoice, a statement),
// as distinct from "invoice" which names a *value* — an invoice number.
export type DocType = "card" | "id" | "invoice" | "amount" | "document"
// Four states, because three lost the distinction that matters most to a
// reader: the backend's `requires_review` means "the reading was not reliable
// enough to judge this", and collapsing it into `fail` displayed an explicit
// refusal to accuse as an accusation. `na` likewise means "this test does not
// apply to this input", which is not a failure of anything.
export type CheckStatus = "pass" | "fail" | "review" | "na"
export type Verdict = "valid" | "fraud" | "insufficient"

export type Severity = "none" | "low" | "medium" | "high" | "critical"

export interface Check {
  id: string
  name: string
  status: CheckStatus
  summary: string
  detail: string
  /** What it means for this check to fail. Drives scoring; defaults to
   *  "medium" when a check does not declare one. */
  severity?: Severity
  /** How sure this check is of its own result, 0-1. Defaults to 0.9. */
  confidence?: number
}

export interface Candidate {
  type: DocType
  label: string
  confidence: number
}

/** One figure read off a document, with how well the OCR passes agreed on it. */
export interface DocumentFigure {
  name: string
  value: number
  agreement: number
}

export interface AnalysisResult {
  input: string
  rawText: string
  type: DocType
  typeLabel: string
  /** A whole document was analysed rather than a single value. The results view
   *  drops "Analyzed value" for these: there is no one value: the document was
   *  judged on the figures below. */
  isDocument: boolean
  /** The figures the verdict actually rests on, for documents. */
  documentFigures: DocumentFigure[]
  verdict: Verdict
  verdictSentence: string
  /** Risk, always: 0 = nothing suspicious, 100 = certainly invalid. Never
   *  confidence — that is reported separately so the two cannot be confused. */
  score: number
  /** How much the analysis trusts its own answer, from evidence coverage. */
  confidence: number
  /** Checks that returned a verdict, and checks attempted. */
  checksRun: number
  checksTotal: number
  checks: Check[]
  candidates: Candidate[]
  imageFile?: File
}

// ---- Mapping helpers ----

const VALUE_TYPE_MAP: Record<string, DocType> = {
  card_number: "card",
  credit_card_candidate: "card",
  financial_amount: "amount",
  invoice_number: "invoice",
  id_number: "id",
  generic_identifier: "id",
  transaction_id: "id",
  passport_number: "id",
  license_number: "id",
  date: "id",
  phone_number: "id",
  email: "id",
  url: "id",
  unknown: "id",
}

const STATUS_MAP: Record<string, Verdict> = {
  likely_valid: "valid",
  valid_with_warnings: "insufficient",
  anomalous: "insufficient",
  requires_review: "insufficient",
  insufficient_evidence: "insufficient",
  invalid: "fraud",
}

const CHECK_STATUS_MAP: Record<string, CheckStatus> = {
  passed: "pass",
  failed: "fail",
  warning: "review",
  requires_review: "review",
  not_applicable: "na",
  unknown: "na",
  unavailable: "na",
}

function mapDocType(backendType: string): DocType {
  return VALUE_TYPE_MAP[backendType] || "id"
}

function mapVerdict(status: string): Verdict {
  return STATUS_MAP[status] || "insufficient"
}

function mapCheckStatus(status: string): CheckStatus {
  return CHECK_STATUS_MAP[status] || "na"
}

// The previous implementation clamped a fraud verdict into [70, 95]. Backend
// risk was effectively always 100 (severity weights cancelled in the old ratio),
// so every fraudulent result rendered as exactly 95 — a constant, not a
// measurement. Risk now passes through untouched.
function computeScore(risk: BackendRiskAssessment | null): number {
  if (!risk) return 0
  return Math.min(100, Math.max(0, Math.round(risk.risk_score)))
}

// Backend check ids are snake_case identifiers (`luhn_checksum`). The offline
// fallback engine in lib/verifier.ts already presents human titles, so the
// backend path matches it rather than leaking raw ids into the UI.
const CHECK_LABELS: Record<string, string> = {
  bank_balance: "Bank Balance",
  benford_applicability: "Benford Applicability",
  benford_chi_square: "Benford's Law Analysis",
  benford_chi_square_secondary_column: "Benford's Law (Secondary Column)",
  benford_two_digit_chi_square: "Benford's Law (Two-Digit)",
  cv_date_extraction: "CV Date Extraction",
  cv_date_overlap_analysis: "CV Date Overlap",
  cv_structure: "CV Structure",
  date_format: "Date Format",
  degenerate_sequence: "Degenerate Sequence",
  duplicate_detection: "Duplicate Detection",
  format_length: "Format Length",
  format_numeric: "Numeric Format",
  format_separators: "Format Separators",
  identifier_format: "Identifier Format",
  invoice_line_item_parsing: "Invoice Line Item Parsing",
  invoice_line_items: "Invoice Line Items",
  invoice_subtotal: "Invoice Subtotal",
  invoice_total: "Invoice Total",
  invoice_totals_consistency: "Invoice Totals",
  luhn_checksum: "Luhn Checksum",
  network_detection: "Network Detection",
  round_amount_check: "Round-Number Heuristic",
  sample_size: "Sample Size",
}

// Words that read wrong in Title Case when a check id is not in the map above.
const CHECK_ACRONYMS = new Set(["cv", "ocr", "id", "pdf", "csv", "xlsx", "vat", "gst", "api"])

function humanizeCheckName(id: string): string {
  const known = CHECK_LABELS[id]
  if (known) return known
  // Unknown ids still reach the UI readable: a new backend check shows as
  // "Some New Check" rather than blocking on this map being updated.
  return id
    .split("_")
    .filter(Boolean)
    .map((word) =>
      CHECK_ACRONYMS.has(word) ? word.toUpperCase() : word.charAt(0).toUpperCase() + word.slice(1)
    )
    .join(" ")
}

function generateVerdictSentence(verdict: Verdict, checks: Check[], limitations: string[]): string {
  // Deliberately does not use the backend's raw `explanation` field — that's
  // a technical log-style summary ("Input classified as card_number
  // (confidence: 100%). Checks: 1 passed, 0 warnings, 1 failed out of 3.
  // Risk: 100/100 (high).") meant for logs/debugging, not a banner headline;
  // the counts it repeats are already shown by the score ring and the
  // checks list below, so surfacing it again here just reads as clutter.
  //
  // For insufficient-evidence verdicts, prefer the backend's specific reason
  // (e.g. "No text detected in image.") over a generic sentence — otherwise
  // every OCR miss looks like an identical, canned placeholder result.
  if (verdict === "insufficient" && limitations.length > 0) return limitations.join(" ")
  const failed = checks.filter((c) => c.status === "fail").length
  const passed = checks.filter((c) => c.status === "pass").length
  if (verdict === "valid") {
    // "All 0 checks passed" was reachable, and it was the worst sentence this
    // app could produce: an assurance whose own numbers say nothing was
    // examined. The verdict is now guarded upstream (see mapAnalysisResult), so
    // this branch should be unreachable — it stays as a sentence that is at
    // least true if it ever is reached.
    if (passed === 0) return "No checks were able to run on this value."
    if (passed === 1)
      return "The one applicable check passed. This value appears structurally valid."
    return `All ${passed} checks passed. This value appears structurally valid.`
  }
  if (verdict === "fraud") return `${failed} check(s) failed. The analysis detected anomalies consistent with fraud.`
  return "The analysis produced mixed results. Additional context may be needed for a definitive verdict."
}

// ---- API functions ----

export async function checkHealth(): Promise<{ status: string; version: string } | null> {
  try {
    const res = await fetch("/api/health")
    if (!res.ok) {
      console.warn(`checkHealth: /api/health returned ${res.status}`)
      return null
    }
    return await res.json()
  } catch (err) {
    // Logged (not silently swallowed) so a failed health check — the thing
    // that routes every analyze request to the offline client-side fallback
    // instead of the real backend — is visible in the console rather than
    // just showing up downstream as unexplained fake-looking results.
    console.warn("checkHealth: /api/health request failed", err)
    return null
  }
}

export async function classifyValue(value: string): Promise<BackendClassificationResponse> {
  const res = await fetch("/api/classify", {
    method: "POST",
    headers: headers(),
    body: JSON.stringify({ value }),
  })
  if (!res.ok) throw new Error(`Classification failed: ${res.status}`)
  return res.json()
}

export async function analyzeValue(
  value: string,
  confirmedValueType?: string,
  confirmedDocumentType?: string,
  classificationId?: string,
): Promise<BackendAnalysisResponse> {
  const body: Record<string, unknown> = {
    input_type: "auto",
    value,
  }
  if (confirmedValueType) body.confirmed_value_type = confirmedValueType
  if (confirmedDocumentType) body.confirmed_document_type = confirmedDocumentType
  if (classificationId) body.classification_id = classificationId

  const res = await fetch("/api/analyze", {
    method: "POST",
    headers: headers(),
    body: JSON.stringify(body),
  })
  if (!res.ok) throw new Error(`Analysis failed: ${res.status}`)
  return res.json()
}

export async function analyzeDataset(values: number[]): Promise<BackendAnalysisResponse> {
  const res = await fetch("/api/analyze", {
    method: "POST",
    headers: headers(),
    body: JSON.stringify({ input_type: "manual_dataset", values }),
  })
  if (!res.ok) throw new Error(`Dataset analysis failed: ${res.status}`)
  return res.json()
}

export async function analyzeUpload(
  file: File,
  visionGuess?: ImageGuess | null,
): Promise<BackendAnalysisResponse> {
  const form = new FormData()
  form.append("file", file)
  // Hand back the verdict classifyImage already produced. Without it the backend
  // re-runs the identical vision classification during analysis — a second call
  // per upload, for an answer we are holding. The server re-validates it.
  if (visionGuess) form.append("vision_guess", JSON.stringify(visionGuess))

  // Content-Type is intentionally left unset so fetch can generate the
  // correct multipart boundary itself. No API key here — this hits our own
  // /api/analyze/upload route handler, which attaches it server-side.
  const res = await fetch("/api/analyze/upload?input_type=auto", { method: "POST", body: form })
  if (!res.ok) {
    const body = await res.text().catch(() => "")
    throw new Error(`Upload failed (${res.status}): ${body}`)
  }
  return res.json()
}

export interface ImageGuess {
  document_type: string
  value_type: string
  confidence: number
  reason: string
}

/** Ask the backend what an uploaded image appears to be, before analysing it.
 *
 * Used to narrate the processing screen with the real classification rather than
 * a scripted guess. Resolves to null whenever vision is unavailable or unsure —
 * callers fall back to generic progress copy instead of inventing a document type.
 */
export async function classifyImage(file: File): Promise<ImageGuess | null> {
  const form = new FormData()
  form.append("file", file)

  try {
    const res = await fetch("/api/classify/image", { method: "POST", body: form })
    if (!res.ok) return null
    const body = (await res.json()) as { guess?: ImageGuess | null }
    return body.guess ?? null
  } catch {
    return null
  }
}

// ---- High-level: backend response → frontend AnalysisResult ----

// Whole-document types the backend reports in `top_document_type`. When one of
// these is set the document identified itself — by stating figures that verify
// against each other — and there is nothing to infer.
const DOCUMENT_TYPE_LABELS: Record<string, string> = {
  invoice: "Invoice",
  bank_statement: "Bank Statement",
  receipt: "Receipt",
}

const FIGURE_LABELS: Record<string, string> = {
  subtotal: "Subtotal",
  tax: "Tax",
  discount: "Discount",
  total: "Total",
  opening: "Opening balance",
  closing: "Closing balance",
  credits: "Credits",
  debits: "Debits",
}

function readDocumentFigures(consistency: Record<string, unknown>): DocumentFigure[] {
  const fields = consistency?.extracted_fields
  if (!fields || typeof fields !== "object") return []
  const order = Object.keys(FIGURE_LABELS)
  return Object.entries(fields as Record<string, { value: number; agreement: number }>)
    .map(([name, f]) => ({
      name: FIGURE_LABELS[name] ?? name,
      value: f.value,
      agreement: f.agreement,
    }))
    .sort(
      (a, b) =>
        order.indexOf(Object.keys(FIGURE_LABELS).find((k) => FIGURE_LABELS[k] === a.name) ?? "") -
        order.indexOf(Object.keys(FIGURE_LABELS).find((k) => FIGURE_LABELS[k] === b.name) ?? ""),
    )
}

/** Collapse candidates that map onto the same DocType.
 *
 *  VALUE_TYPE_MAP is many-to-one — ten backend value types become "id" on their
 *  own — so a backend reply offering, say, id_number and generic_identifier
 *  produced two candidates with identical `type`. React saw duplicate keys, and
 *  the confirm screen offered two buttons with the same label that set the same
 *  value when clicked. They are one choice, so present them as one, keeping the
 *  most confident of the group and its label.
 */
export function dedupeByType(candidates: Candidate[]): Candidate[] {
  const best = new Map<DocType, Candidate>()
  for (const candidate of candidates) {
    const existing = best.get(candidate.type)
    if (!existing || candidate.confidence > existing.confidence) {
      best.set(candidate.type, candidate)
    }
  }
  return [...best.values()].sort((a, b) => b.confidence - a.confidence)
}

export function mapAnalysisResult(
  backend: BackendAnalysisResponse,
  inputValue: string,
  rawText: string,
  imageFile?: File,
): AnalysisResult {
  // For file/camera uploads, inputValue arrives empty (there's no typed value)
  // — the actual value only exists once OCR extracts it server-side. Without
  // this, "Analyzed value" has nothing to mask/display for scanned cards even
  // though a real number was found.
  const ocrExtractedValue = backend.extracted_data.ocr_card_candidate
  const effectiveInput =
    inputValue || (typeof ocrExtractedValue === "string" ? ocrExtractedValue : "")

  let topType = backend.top_value_type || "unknown"

  // Infer a type from the input's shape only when nobody has stated one.
  //
  // The backend reports classification_source: "confirmed" when the user picked
  // the type on the confirm screen. Choosing "ID Number" there sends
  // generic_identifier, which this branch then treated as "the backend had no
  // idea" and rewrote to card_number for anything 13-19 digits long — so every
  // choice came back labelled Card Number regardless of what was selected.
  const userChoseTheType = backend.classification_source === "confirmed"

  if (!userChoseTheType && (topType === "unknown" || topType === "generic_identifier")) {
    const digits = effectiveInput.replace(/\D/g, "")
    if (digits.length >= 13 && digits.length <= 19) {
      topType = "card_number"
    } else if (/[$€£¥]/.test(effectiveInput) || /\d[.,]\d{2}\b/.test(effectiveInput)) {
      topType = "financial_amount"
    } else if (/(inv|invoice|no|#)/i.test(effectiveInput)) {
      topType = "invoice_number"
    }
  }

  // A document that identified itself wins over any inference from the value:
  // top_value_type is empty for documents, and letting it fall through to the
  // `unknown -> "id"` default is what labelled a scanned invoice "ID Number".
  const documentLabel = DOCUMENT_TYPE_LABELS[backend.top_document_type]
  const isDocument = Boolean(documentLabel)
  const type: DocType = isDocument ? "document" : mapDocType(topType)
  const documentFigures = isDocument ? readDocumentFigures(backend.consistency_analysis) : []
  const verdict = mapVerdict(backend.overall_status)

  const checks: Check[] = backend.checks.map((c, i) => ({
    id: `check-${i}`,
    name: humanizeCheckName(c.check),
    status: mapCheckStatus(c.status),
    summary: c.message || `${humanizeCheckName(c.check)}: ${c.status}`,
    detail: c.message || `Category: ${c.category}. Confidence: ${Math.round(c.confidence * 100)}%`,
  }))

  const candidates: Candidate[] = dedupeByType(
    backend.value_candidates.map((vc) => ({
      type: mapDocType(vc.type),
      label: vc.label,
      confidence: vc.confidence,
    })),
  )

  const score = computeScore(backend.risk_assessment)
  const risk = backend.risk_assessment
  const checksTotal = risk?.checks_total ?? checks.length
  const checksRun =
    risk?.checks_determinate ?? checks.filter((c) => c.status !== "na").length
  const confidence = risk ? Math.min(100, Math.max(0, risk.confidence)) : 0

  /* ─── Zero-evidence guard ──────────────────────────────────────────────────
     A "valid" verdict requires at least one check to have actually determined
     something. Without that there is no finding to report, only an absence, and
     "Likely Valid" is an assurance the analysis never earned.

     The root cause is fixed in the backend (engines/risk.py: NOT_APPLICABLE
     checks were counted as evidence of validity). This is a second line of
     defence, not the fix — it is the frontend's own responsibility not to
     render an assurance it has no support for, and it holds against an older
     backend, a cached response, or a future regression upstream.
     ---------------------------------------------------------------------- */
  const effectiveVerdict: Verdict =
    verdict === "valid" && checksRun === 0 ? "insufficient" : verdict

  const verdictSentence =
    effectiveVerdict !== verdict
      ? "No checks could be applied to this value, so no determination can be made."
      : generateVerdictSentence(verdict, checks, backend.limitations)

  const typeLabels: Record<DocType, string> = {
    card: "Card Number",
    id: "ID Number",
    invoice: "Invoice Number",
    amount: "Financial Amount",
    document: "Document",
  }

  return {
    input: effectiveInput,
    rawText,
    type,
    typeLabel: documentLabel ?? typeLabels[type],
    isDocument,
    documentFigures,
    verdict: effectiveVerdict,
    verdictSentence,
    score,
    confidence,
    checksRun,
    checksTotal,
    checks,
    candidates:
      isDocument
        ? dedupeByType(
            // Every entry here is given the same `type`, so without the dedupe
            // two document candidates would collide with each other outright.
            backend.document_candidates.map((dc) => ({
              type,
              label: DOCUMENT_TYPE_LABELS[dc.type] ?? dc.label,
              confidence: dc.confidence,
            })),
          )
        : candidates.length > 0
          ? candidates
          : [{ type, label: typeLabels[type], confidence: 0.8 }],
    imageFile,
  }
}

export const TYPE_LABELS: Record<DocType, string> = {
  card: "Card Number",
  id: "ID Number",
  invoice: "Invoice Number",
  amount: "Financial Amount",
  document: "Document",
}
