import { NextRequest } from "next/server"
import { BACKEND_URL, backendHeaders, relayResponse, backendUnreachable } from "@/lib/backend"

export async function POST(request: NextRequest) {
  const body = await request.text()
  let res: Response
  try {
    res = await fetch(`${BACKEND_URL}/api/analyze`, {
      method: "POST",
      headers: backendHeaders({ "Content-Type": "application/json" }),
      body,
    })
  } catch (err) {
    return backendUnreachable(err)
  }
  return relayResponse(res)
}
