import { NextRequest } from "next/server"
import { BACKEND_URL, backendHeaders, relayResponse } from "@/lib/backend"

export async function POST(request: NextRequest) {
  const body = await request.text()
  const res = await fetch(`${BACKEND_URL}/api/analyze`, {
    method: "POST",
    headers: backendHeaders({ "Content-Type": "application/json" }),
    body,
  })
  return relayResponse(res)
}
