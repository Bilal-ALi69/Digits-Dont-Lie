import { NextRequest, NextResponse } from "next/server"
import { BACKEND_URL, MAX_UPLOAD_BYTES, backendHeaders, relayResponse } from "@/lib/backend"

export async function POST(request: NextRequest) {
  const inputType = request.nextUrl.searchParams.get("input_type") || "auto"

  // Refuse before reading. `request.formData()` buffers the entire body into
  // this process's memory, so checking afterwards would mean the cost was
  // already paid — the backend's own 10 MB limit cannot defend this server.
  const declared = Number(request.headers.get("content-length") ?? "0")
  if (declared > MAX_UPLOAD_BYTES) {
    return NextResponse.json({ detail: "File too large (max 10 MB)." }, { status: 413 })
  }

  const form = await request.formData()

  // Content-Length is absent on a chunked request, so the declared size above
  // can be missing entirely. Check what actually arrived as well.
  const file = form.get("file")
  if (file instanceof File && file.size > MAX_UPLOAD_BYTES) {
    return NextResponse.json({ detail: "File too large (max 10 MB)." }, { status: 413 })
  }

  // Content-Type is intentionally left unset so fetch generates the correct
  // multipart boundary itself for the forwarded FormData body.
  const res = await fetch(
    `${BACKEND_URL}/api/analyze/upload?input_type=${encodeURIComponent(inputType)}`,
    { method: "POST", headers: backendHeaders(), body: form },
  )
  return relayResponse(res)
}
