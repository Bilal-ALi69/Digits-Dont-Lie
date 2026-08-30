// Flow logger for tracing "action -> code path -> what's on screen" while
// diagnosing behaviour. Open DevTools, filter on "FLOW", reproduce, copy.
//
// Silent in production builds. It was unconditional, so a deployed page logged
// every file name, size and typed digit count to the console of whoever opened
// it — debug instrumentation is for the person debugging, not for every visitor.
// The check is against a literal Next inlines at build time, so the calls are
// eliminated by dead-code removal rather than merely skipped at runtime.
const ENABLED = process.env.NODE_ENV !== "production"

export function debugLog(step: string, data?: Record<string, unknown>) {
  if (!ENABLED) return
  const ts = new Date().toISOString().slice(11, 23)
  console.log(`%c[FLOW ${ts}] ${step}`, "color:#E87040;font-weight:bold", data ?? "")
}
