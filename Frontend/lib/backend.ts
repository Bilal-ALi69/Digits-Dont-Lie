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

/** Mirrors Backend/app/api/server.py's _MAX_UPLOAD_BYTES.
 *
 *  The route handlers need their own copy because they buffer the request body
 *  before the backend ever sees it: `request.formData()` reads the whole upload
 *  into this server's memory, so the backend's limit cannot protect this
 *  process. The check has to happen here to mean anything. */
export const MAX_UPLOAD_BYTES = 10 * 1024 * 1024
