import { NextRequest, NextResponse } from "next/server"
import { BACKEND_URL, MAX_UPLOAD_BYTES, backendHeaders, relayResponse } from "@/lib/backend"

export async function POST(request: NextRequest) {
  // Same guard as app/api/analyze/upload/route.ts, and for the same reason:
  // request.formData() reads the whole body into this process's memory, so the
  // backend's own limit is applied too late to protect this server. Refusing on
  // the declared length avoids paying for the body at all; the check after the
  // parse covers chunked requests, which carry no Content-Length to refuse on.
  const declared = Number(request.headers.get("content-length") ?? "0")
  if (declared > MAX_UPLOAD_BYTES) {
    return NextResponse.json({ detail: "File too large (max 10 MB)." }, { status: 413 })
  }

  const form = await request.formData()

  const file = form.get("file")
  if (file instanceof File && file.size > MAX_UPLOAD_BYTES) {
    return NextResponse.json({ detail: "File too large (max 10 MB)." }, { status: 413 })
  }

  // Content-Type is intentionally left unset so fetch generates the correct
  // multipart boundary itself for the forwarded FormData body.
  const res = await fetch(`${BACKEND_URL}/api/classify/image`, {
    method: "POST",
    headers: backendHeaders(),
    body: form,
  })
  return relayResponse(res)
}
