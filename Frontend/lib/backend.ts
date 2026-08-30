// Server-only helpers shared by the app/api/* route handlers.
// This file must never be imported from client components: it reads the
// real backend URL and API key, which stay server-side so the browser
// bundle never contains the shared secret used to authenticate with the
// FastAPI backend.

// 127.0.0.1 rather than "localhost": Node resolves localhost to ::1 first, but
// uvicorn binds IPv4 only by default, so every proxied request was failing with
// ECONNREFUSED against a backend that was running fine on 127.0.0.1.
export const BACKEND_URL = process.env.BACKEND_URL || "http://127.0.0.1:8000"
const BACKEND_API_KEY = process.env.BACKEND_API_KEY || ""

export function backendHeaders(extra?: Record<string, string>): Record<string, string> {
  return { "X-API-Key": BACKEND_API_KEY, ...extra }
}

// Mirrors the backend response verbatim (status + body + content-type) so the
// browser sees the same thing it would from a direct call, without the key.
export async function relayResponse(res: Response): Promise<Response> {
  const body = await res.text()
  return new Response(body, {
    status: res.status,
    headers: { "Content-Type": res.headers.get("Content-Type") || "application/json" },
  })
}

/** Answer for a backend that could not be reached at all.
 *
 *  `fetch` *rejects* on a transport failure rather than resolving with an error
 *  status, so an unguarded proxy route threw straight out of the handler and
 *  Next answered with a bare 500: no body, no content-type, nothing the caller
 *  could read to learn what went wrong. That is the single most likely failure
 *  in a live demo — the backend is simply not running yet — and it was the one
 *  the proxy explained worst. /api/health already answered 502 for exactly this
 *  condition; the other routes now agree with it.
 *
 *  502 rather than 503: this server is fine, the upstream one it depends on is
 *  not, which is what Bad Gateway means. The client treats any non-ok status as
 *  a reason to fall back to the offline engine, so the status choice only
 *  affects what a human reads in the network tab — which is the point.
 */
export function backendUnreachable(err: unknown): Response {
  // Logged server-side: the browser is about to be told the backend is
  // unreachable, but only this process ever sees *why* (ECONNREFUSED, DNS,
  // TLS), and that is the line that ends the debugging session.
  console.error(`Backend unreachable at ${BACKEND_URL}:`, err)
  // The URL is deliberately in the log above and not in the body below. This
  // whole module exists to keep the backend's address and key on the server;
  // naming the upstream host in a browser-visible error would hand back part of
  // what the proxy is here to withhold. Whoever can fix this is reading the
  // server log anyway.
  return new Response(
    JSON.stringify({ detail: "Analysis backend is unreachable. Is the FastAPI server running?" }),
    { status: 502, headers: { "Content-Type": "application/json" } },
  )
}

/** Mirrors Backend/app/api/server.py's _MAX_UPLOAD_BYTES.
 *
 *  The route handlers need their own copy because they buffer the request body
 *  before the backend ever sees it: `request.formData()` reads the whole upload
 *  into this server's memory, so the backend's limit cannot protect this
 *  process. The check has to happen here to mean anything. */
export const MAX_UPLOAD_BYTES = 10 * 1024 * 1024
