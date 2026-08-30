// Fraud detection engine for the Digits Dont Lie app.
// Pure, dependency-free logic so results are deterministic and testable.

// The result shape is a contract with the results view, not with either engine,
// so it is declared once in lib/api.ts and re-exported here. It used to be
// declared in both files, and every change to one had to be mirrored by hand in
// the other — which is how "review" and "document" each broke the build.
//
// `import type` is erased at compile time, so this adds no runtime dependency
// and keeps this module the dependency-free logic it claims to be above.
export type {
  AnalysisResult,
  Candidate,
  Check,
  CheckStatus,
  DocType,
  DocumentFigure,
  Verdict,
} from "@/lib/api"

import type {
  AnalysisResult,
  Candidate,
  Check,
  CheckStatus,
  DocType,
  Severity,
  Verdict,
} from "@/lib/api"

export const TYPE_LABELS: Record<DocType, string> = {
  card: "Card Number",
  id: "ID Number",
  invoice: "Invoice Number",
  amount: "Financial Amount",
  // Unreachable from this engine, which only classifies single typed values.
  document: "Document",
}

// ---------- primitives ----------

export function luhnValid(value: string): boolean {
  const digits = value.replace(/\D/g, "")
  if (digits.length < 2) return false
  let sum = 0
  let alt = false
  for (let i = digits.length - 1; i >= 0; i--) {
    let n = Number.parseInt(digits[i], 10)
    if (alt) {
      n *= 2
      if (n > 9) n -= 9
    }
    sum += n
    alt = !alt
  }
  return sum % 10 === 0
}

interface Network {
  name: string
  lengths: number[]
}

// Prefix rules mirror Backend/app/engines/card.py's _NETWORK_RULES exactly,
// so the offline fallback recognizes the same networks the backend does.
// (Previously this list used tighter/looser prefix ranges than the backend —
// e.g. it recognized Discover's 644-649 range that the backend doesn't, and
// was missing UnionPay and Maestro entirely — which meant the fallback could
// reach a different verdict than the real backend for the same input.)
export function detectNetwork(value: string): Network | null {
  const d = value.replace(/\D/g, "")
  if (/^4/.test(d)) return { name: "Visa", lengths: [13, 16, 19] }
  if (/^5[1-5]/.test(d) || /^2[2-7]/.test(d)) return { name: "Mastercard", lengths: [16] }
  if (/^3[47]/.test(d)) return { name: "American Express", lengths: [15] }
  if (/^(6011|65)/.test(d)) return { name: "Discover", lengths: [16] }
  if (/^3(0[0-5]|[68])/.test(d)) return { name: "Diners Club", lengths: [14, 16] }
  if (/^(2131|1800|35)/.test(d)) return { name: "JCB", lengths: [15, 16, 17, 18, 19] }
  if (/^62/.test(d)) return { name: "UnionPay", lengths: [16, 17, 18, 19] }
  if (/^(5018|5020|5038|5893|6304|6759|676[1-3])/.test(d))
    return { name: "Maestro", lengths: [12, 13, 14, 15, 16, 17, 18, 19] }
  return null
}

// Chi-square-ish conformity of leading digits to Benford's distribution.
const BENFORD = [0.301, 0.176, 0.125, 0.097, 0.079, 0.067, 0.058, 0.051, 0.046]

export function benfordConformity(numbers: number[]): number {
  const leads = numbers
    .map((n) => Math.abs(n))
    .filter((n) => n >= 1)
    .map((n) => Number(String(n).replace(/[^1-9]/, "").charAt(0)) || Number(String(Math.trunc(n)).charAt(0)))
    .filter((d) => d >= 1 && d <= 9)
  if (leads.length === 0) return 0
  const counts = new Array(9).fill(0)
  leads.forEach((d) => (counts[d - 1] += 1))
  let dist = 0
  for (let i = 0; i < 9; i++) {
    const observed = counts[i] / leads.length
    dist += Math.abs(observed - BENFORD[i])
  }
  // dist ranges ~0 (perfect) to ~1.4 (worst). Normalize to a 0-1 conformity score.
  return Math.max(0, 1 - dist / 1.2)
}

// ---------- classification ----------

export function classify(input: string): Candidate[] {
  const raw = input.trim()
  const digitsOnly = raw.replace(/\D/g, "")
  const hasLetters = /[a-z]/i.test(raw)
  const hasCurrency = /[$€£¥]/.test(raw) || /\d[.,]\d{2}\b/.test(raw)
  const hasSeparators = /[\/\-]/.test(raw)
  const len = digitsOnly.length

  let card = 0
  let id = 0
  let invoice = 0
  let amount = 0

  // Card: 12-19 digits, no letters, spacing patterns common.
  if (!hasLetters) {
    if (len >= 12 && len <= 19) card += 0.5
    if (detectNetwork(raw)) card += 0.25
    if (luhnValid(raw)) card += 0.25
    if (/\d{4}[\s-]\d{4}/.test(raw)) card += 0.1
  }

  // Amount: currency symbols or decimal formatting.
  if (hasCurrency) amount += 0.7
  if (/^[$€£¥]?\s?[\d,]+(\.\d{1,2})?$/.test(raw) && !hasLetters) amount += 0.3
  if (/,/.test(raw) && /\.\d{2}$/.test(raw)) amount += 0.2

  // Invoice: prefix letters + digits, or explicit invoice-like tokens.
  if (hasLetters && /\d/.test(raw)) invoice += 0.5
  if (/(inv|invoice|no|#)/i.test(raw)) invoice += 0.35
  if (hasSeparators && hasLetters) invoice += 0.15

  // ID: mixed alnum without currency, medium length, or SSN-like patterns.
  if (hasLetters && /\d/.test(raw)) id += 0.35
  if (/^\d{3}-\d{2}-\d{4}$/.test(raw)) id += 0.6 // SSN pattern
  if (!hasCurrency && len >= 6 && len <= 12 && !detectNetwork(raw)) id += 0.2
  if (/^[A-Z0-9]{6,12}$/i.test(raw.replace(/\s/g, "")) && hasLetters) id += 0.2

  // Highest score each type can actually reach from the checks above, e.g. a
  // spaced Visa hits all four card checks (0.5+0.25+0.25+0.1). ID tops out at
  // 0.8 rather than 1.35 because its SSN and alphanumeric branches are mutually
  // exclusive — an SSN has no letters, so it can never also earn the letter
  // bonuses.
  const MAX_SCORE = { card: 1.1, amount: 1.2, invoice: 1.0, id: 0.8 } as const

  // Score each type against its own evidence ceiling rather than against the
  // other candidates. Dividing by the sum of all scores (the previous approach)
  // inflated weak matches whenever the alternatives matched even worse — a
  // random 16-digit string that failed both Luhn and network detection still
  // read as 0.63 "card" and skipped confirmation.
  const candidates: Candidate[] = [
    { type: "card", label: TYPE_LABELS.card, confidence: card / MAX_SCORE.card },
    { type: "amount", label: TYPE_LABELS.amount, confidence: amount / MAX_SCORE.amount },
    { type: "invoice", label: TYPE_LABELS.invoice, confidence: invoice / MAX_SCORE.invoice },
    { type: "id", label: TYPE_LABELS.id, confidence: id / MAX_SCORE.id },
  ]

  return candidates
    .map((c) => ({ ...c, confidence: Math.min(0.99, c.confidence) }))
    .sort((a, b) => b.confidence - a.confidence)
}

export function isAmbiguous(candidates: Candidate[]): boolean {
  if (candidates.length === 0) return true
  const [first, second] = candidates
  if (first.confidence < 0.55) return true
  if (second && first.confidence - second.confidence < 0.18) return true
  return false
}

// ---------- per-type checks + verdict ----------

function analyzeCard(input: string): { checks: Check[]; verdict: Verdict; score: number; sentence: string } {
  const digits = input.replace(/\D/g, "")
  const network = detectNetwork(input)
  const luhn = luhnValid(input)
  const lengthOk = network ? network.lengths.includes(digits.length) : digits.length >= 12 && digits.length <= 19

  const checks: Check[] = [
    {
      id: "format",
      name: "Format Validation",
      // Outside 12-19 digits it cannot be a PAN at all, under ISO/IEC 7812.
      severity: "critical",
      status: digits.length >= 12 && digits.length <= 19 ? "pass" : "fail",
      summary:
        digits.length >= 12 && digits.length <= 19
          ? `${digits.length} digits — within the valid PAN range`
          : `${digits.length} digits — outside the 12–19 range for card numbers`,
      detail:
        "Payment card numbers (PANs) are 12–19 digits. Values outside this range cannot be valid card numbers under ISO/IEC 7812.",
    },
    {
      id: "luhn",
      name: "Luhn Checksum",
      // Arithmetically impossible, not merely suspicious.
      severity: "critical",
      status: luhn ? "pass" : "fail",
      summary: luhn ? "Checksum is valid" : "Checksum failed — the number is mathematically invalid",
      detail:
        "The Luhn algorithm is a checksum applied to the final digit of a card number. A failing checksum means the number was mistyped or fabricated.",
    },
    {
      id: "network",
      name: "Network Detection",
      // A strong anomaly, but unrecognised IINs do get issued.
      severity: "high",
      status: network ? "pass" : "fail",
      summary: network ? `Identified as ${network.name}` : "No known card network prefix matched",
      detail:
        "The leading digits (the IIN/BIN) map to a card network such as Visa, Mastercard, or American Express. An unrecognized prefix is a strong anomaly signal.",
    },
    {
      id: "length",
      name: "Length Consistency",
      severity: "high",
      status: network ? (lengthOk ? "pass" : "fail") : "na",
      summary: network
        ? lengthOk
          ? `Length matches ${network.name} specification`
          : `Length does not match ${network.name} (expected ${network.lengths.join("/")} digits)`
        : "No network identified — length spec not applicable",
      detail:
        "Each network defines exact permitted lengths. A number whose length disagrees with its own prefix is inconsistent.",
    },
    {
      id: "benford",
      name: "Benford's Law Analysis",
      status: "na",
      summary: "Not applicable to a single card number",
      detail:
        "Benford's Law describes leading-digit frequencies across large datasets. It is meaningful for populations of numbers (e.g. transaction ledgers), not a single identifier.",
    },
  ]

  const critical = [checks[0], checks[1], checks[2]]
  const passing = critical.filter((c) => c.status === "pass").length
  let verdict: Verdict
  let sentence: string

  if (!luhn && digits.length >= 12) {
    verdict = "fraud"
    sentence = "The Luhn checksum fails, so this cannot be a genuine card number."
  } else if (passing === 3 && lengthOk) {
    verdict = "valid"
    sentence = `This is a structurally valid ${network?.name ?? "card"} number that passes all format checks.`
  } else if (passing >= 2) {
    verdict = "insufficient"
    sentence = "The number passes some checks but has anomalies that prevent a confident verdict."
  } else {
    verdict = "insufficient"
    sentence = "There isn't enough consistent structure to confirm this as a card number."
  }

  return { checks, verdict, score: scoreChecks(checks).score, sentence }
}

function analyzeAmount(input: string): { checks: Check[]; verdict: Verdict; score: number; sentence: string } {
  const numeric = Number.parseFloat(input.replace(/[^0-9.]/g, ""))
  const valid = Number.isFinite(numeric)
  const hasTwoDecimals = /\.\d{2}\b/.test(input)
  const conformity = benfordConformity([numeric].filter((n) => Number.isFinite(n)))
  const leadDigit = valid ? Number(String(Math.trunc(Math.abs(numeric))).charAt(0)) : 0
  const roundSuspicious = valid && numeric >= 1000 && numeric % 1000 === 0

  const checks: Check[] = [
    {
      id: "format",
      name: "Format Validation",
      // Unparseable means there is nothing to judge, not that it is fraudulent.
      severity: "medium",
      status: valid ? "pass" : "fail",
      summary: valid ? `Parsed as ${numeric.toLocaleString()}` : "Could not parse a numeric amount",
      detail: "The value is checked for a well-formed monetary representation with optional grouping and decimals.",
    },
    {
      id: "precision",
      name: "Decimal Precision",
      status: valid ? (hasTwoDecimals ? "pass" : "na") : "na",
      summary: hasTwoDecimals ? "Two-decimal currency precision present" : "No explicit cents — treated as a whole amount",
      detail: "Most currencies use two-decimal minor units. Missing precision isn't an error but is noted.",
    },
    {
      id: "benford",
      name: "Benford's Law Analysis",
      // One value is weak evidence: the detail text says so, and the score
      // should agree rather than treating a rare lead digit as near-proof.
      severity: "low",
      confidence: 0.35,
      status: valid ? (leadDigit <= 3 ? "pass" : leadDigit >= 7 ? "fail" : "na") : "na",
      summary: valid
        ? leadDigit <= 3
          ? `Leading digit ${leadDigit} is high-probability under Benford`
          : leadDigit >= 7
            ? `Leading digit ${leadDigit} is statistically rare as a leading digit`
            : `Leading digit ${leadDigit} is moderately common`
        : "No amount to analyze",
      detail:
        "Benford's Law predicts that natural amounts begin with 1 about 30% of the time and with 9 under 5%. A single value is only weakly informative — for real assurance, run it across a dataset.",
    },
    {
      id: "round",
      name: "Round-Number Heuristic",
      // "A soft signal, not proof" — per this check's own detail text.
      severity: "low",
      confidence: 0.4,
      status: valid ? (roundSuspicious ? "fail" : "pass") : "na",
      summary: roundSuspicious ? "Suspiciously round figure" : "No round-number anomaly",
      detail: "Fabricated amounts skew toward round thousands. This is a soft signal, not proof.",
    },
  ]

  let verdict: Verdict = "insufficient"
  let sentence = "A single amount can be format-checked but not confidently verified in isolation."
  if (!valid) {
    verdict = "insufficient"
    sentence = "The input couldn't be parsed as a monetary amount."
  } else if (roundSuspicious && leadDigit >= 7) {
    verdict = "fraud"
    sentence = "The amount combines a rare leading digit with a suspiciously round figure."
  } else if (conformity > 0.6 && !roundSuspicious) {
    verdict = "insufficient"
    sentence = "The amount is well-formed, but distribution tests need a dataset for a firm verdict."
  }

  return { checks, verdict, score: scoreChecks(checks).score, sentence }
}

function analyzeInvoice(input: string): { checks: Check[]; verdict: Verdict; score: number; sentence: string } {
  const raw = input.trim()
  const hasPrefix = /^[a-z]{2,5}[\s\-]?\d/i.test(raw) || /(inv|invoice)/i.test(raw)
  const digits = raw.replace(/\D/g, "")
  const structured = /^[a-z0-9]+([\-\/][a-z0-9]+)+$/i.test(raw)

  const checks: Check[] = [
    {
      id: "format",
      name: "Format Validation",
      severity: "medium",
      status: raw.length >= 3 ? "pass" : "fail",
      summary: raw.length >= 3 ? "Well-formed invoice-style token" : "Too short to be an invoice reference",
      detail: "Invoice references are typically alphanumeric with a prefix and a sequential component.",
    },
    {
      id: "prefix",
      name: "Prefix Detection",
      status: hasPrefix ? "pass" : "na",
      summary: hasPrefix ? "Recognized an issuer/document prefix" : "No standard prefix detected",
      detail: "Many systems prepend a fixed prefix (e.g. INV-) to invoice sequences. Its presence increases confidence.",
    },
    {
      id: "structure",
      name: "Segment Structure",
      status: structured ? "pass" : "na",
      summary: structured ? "Delimited segments detected" : "No multi-segment structure",
      detail: "Segmented references (e.g. 2024-0001) encode a period and a sequence, a common legitimate pattern.",
    },
    {
      id: "benford",
      name: "Benford's Law Analysis",
      status: digits.length ? "na" : "na",
      summary: "Requires the full invoice sequence to evaluate",
      detail:
        "Benford's Law can flag manufactured invoice runs, but needs the population of invoice numbers rather than one reference.",
    },
  ]

  const verdict: Verdict = "insufficient"
  const sentence = "The reference is well-formed, but a single invoice number can't be verified without its ledger."
  return { checks, verdict, score: scoreChecks(checks).score, sentence }
}

function analyzeId(input: string): { checks: Check[]; verdict: Verdict; score: number; sentence: string } {
  const raw = input.trim().replace(/\s/g, "")
  const ssn = /^\d{3}-?\d{2}-?\d{4}$/.test(raw)
  const entropy = new Set(raw.replace(/[^a-z0-9]/gi, "").toLowerCase().split("")).size
  const formatOk = raw.length >= 5 && /^[a-z0-9\-]+$/i.test(raw)

  const checks: Check[] = [
    {
      id: "format",
      name: "Format Validation",
      severity: "medium",
      status: formatOk ? "pass" : "fail",
      summary: formatOk ? `Valid identifier format (${raw.length} chars)` : "Contains characters not typical of identifiers",
      detail: "Identifiers are usually alphanumeric with optional dashes and a minimum length.",
    },
    {
      id: "pattern",
      name: "Known Pattern Match",
      status: ssn ? "pass" : "na",
      summary: ssn ? "Matches a US SSN pattern (###-##-####)" : "No known national-ID pattern matched",
      detail: "Some identifiers follow published national formats. A match narrows the identifier's origin.",
    },
    {
      id: "entropy",
      name: "Character Entropy",
      // A placeholder like 1111111 is a strong tell, but not arithmetic proof.
      severity: "high",
      status: entropy >= 4 ? "pass" : "fail",
      summary: entropy >= 4 ? `${entropy} distinct characters — healthy variety` : "Low character variety — possible placeholder",
      detail: "Repetitive identifiers (e.g. 1111111) are common test/placeholder values rather than real records.",
    },
    {
      id: "checksum",
      name: "Checksum Verification",
      status: "na",
      summary: "No checksum scheme is defined for this identifier type",
      detail: "Unlike card numbers, most ID formats don't embed a check digit that can be independently verified.",
    },
  ]

  let verdict: Verdict = "insufficient"
  let sentence = "The identifier is well-formed, but without an issuing authority it can't be confirmed."
  if (entropy < 4) {
    verdict = "fraud"
    sentence = "The identifier has suspiciously low character variety, typical of placeholder or fabricated values."
  } else if (ssn && entropy >= 4) {
    verdict = "insufficient"
    sentence = "The value matches a recognized ID pattern but cannot be validated against an authority here."
  }

  return { checks, verdict, score: scoreChecks(checks).score, sentence }
}

export function analyze(input: string, type: DocType, rawText?: string): AnalysisResult {
  const candidates = classify(input)
  let result: { checks: Check[]; verdict: Verdict; score: number; sentence: string }
  switch (type) {
    case "card":
      result = analyzeCard(input)
      break
    case "amount":
      result = analyzeAmount(input)
      break
    case "invoice":
      result = analyzeInvoice(input)
      break
    case "id":
    default:
      result = analyzeId(input)
      break
  }

  return {
    input,
    rawText: rawText ?? input,
    type,
    typeLabel: TYPE_LABELS[type],
    verdict: result.verdict,
    verdictSentence: result.sentence,
    score: result.score,
    confidence: scoreChecks(result.checks).confidence,
    checksRun: scoreChecks(result.checks).checksRun,
    checksTotal: result.checks.length,
    checks: result.checks,
    candidates,
    // This offline engine only ever analyses a single typed value; whole-document
    // analysis needs OCR and the backend. So it never produces document figures.
    isDocument: false,
    documentFigures: [],
  }
}

// Deterministic pseudo-extraction for uploaded files (no OCR in the browser).
// Produces a stable candidate value seeded by the file name + size.
export function simulateExtraction(fileName: string, fileSize: number): string {
  let seed = fileSize
  for (let i = 0; i < fileName.length; i++) seed = (seed * 31 + fileName.charCodeAt(i)) >>> 0
  const rng = () => {
    seed = (seed * 1664525 + 1013904223) >>> 0
    return seed / 0xffffffff
  }
  // Build a Visa-like number then fix the Luhn check digit for realism.
  const body = "4"
  let digits = body
  for (let i = 0; i < 14; i++) digits += Math.floor(rng() * 10)
  // compute check digit
  let sum = 0
  let alt = true
  for (let i = digits.length - 1; i >= 0; i--) {
    let n = Number.parseInt(digits[i], 10)
    if (alt) {
      n *= 2
      if (n > 9) n -= 9
    }
    sum += n
    alt = !alt
  }
  const check = (10 - (sum % 10)) % 10
  digits += check
  return digits.replace(/(.{4})/g, "$1 ").trim()
}

/* ─── Offline scoring ────────────────────────────────────────────────────────
   A port of Backend/app/engines/risk.py's aggregate_evidence, so the offline
   fallback and the backend produce the same number from the same checks. These
   analysers previously returned hand-picked constants (88 for fraud, 92 for
   valid — four points apart on one scale, meaning opposite things), so the same
   card scored differently depending on whether the backend happened to be up.

   Keep the constants below in step with _SEVERITY_POINTS, _STATUS_MULTIPLIER
   and _CRITICAL_FAILURE_FLOOR in risk.py.
   ------------------------------------------------------------------------- */

const SEVERITY_POINTS: Record<Severity, number> = {
  none: 0,
  low: 8,
  medium: 20,
  high: 45,
  critical: 100,
}

/** How much of a check's severity each outcome realises. "na" is absent on
 *  purpose: a check that could not run says nothing about risk. */
const STATUS_MULTIPLIER: Partial<Record<CheckStatus, number>> = {
  fail: 1.0,
  review: 0.25,
}

const CRITICAL_FAILURE_FLOOR = 90

export interface OfflineScore {
  score: number
  confidence: number
  checksRun: number
  checksTotal: number
}

export function scoreChecks(checks: Check[]): OfflineScore {
  if (checks.length === 0) {
    return { score: 0, confidence: 0, checksRun: 0, checksTotal: 0 }
  }

  let accumulated = 0
  let hasCriticalFailure = false
  const determinate = checks.filter((c) => c.status !== "na")

  for (const check of checks) {
    const multiplier = STATUS_MULTIPLIER[check.status]
    if (multiplier === undefined) continue
    const severity = check.severity ?? "medium"
    accumulated += SEVERITY_POINTS[severity] * multiplier
    if (check.status === "fail" && severity === "critical") hasCriticalFailure = true
  }

  let score = Math.min(100, Math.round(accumulated))
  if (hasCriticalFailure) score = Math.max(score, CRITICAL_FAILURE_FLOOR)

  const meanConfidence =
    determinate.length > 0
      ? determinate.reduce((sum, c) => sum + (c.confidence ?? 0.9), 0) / determinate.length
      : 0
  const coverage = determinate.length / checks.length
  const confidence = Math.min(100, Math.max(0, Math.round(coverage * meanConfidence * 100)))

  return { score, confidence, checksRun: determinate.length, checksTotal: checks.length }
}
