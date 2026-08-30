import { BACKEND_URL } from "@/lib/backend"

export async function GET() {
  try {
    const res = await fetch(`${BACKEND_URL}/api/health`, { cache: "no-store" })
    const body = await res.text()
    return new Response(body, {
      status: res.status,
      headers: { "Content-Type": res.headers.get("Content-Type") || "application/json" },
    })
  } catch {
    return new Response(JSON.stringify(null), { status: 502 })
  }
}
