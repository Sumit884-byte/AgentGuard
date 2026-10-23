// Client for web/server.py. Shapes follow contracts-v2.md section 4 (receipts).

export type Mode = "naive" | "guarded"
export type ReceiptStatus = "ALLOWED" | "BLOCKED" | "NEEDS_APPROVAL" | "ERROR"

export interface Check {
  rule: string
  layer: "handler" | "yaml" | "backend"
  passed: boolean
  values: Record<string, unknown>
  detail: string
}

export interface SafeAlternative {
  tool: string
  args: Record<string, unknown>
  say: string
}

export interface Receipt {
  status: ReceiptStatus
  tool: string
  args: Record<string, unknown>
  checks: Check[]
  violated_policy: string | null
  reason: string
  safe_alternative: SafeAlternative | null
  approval_id: string | null
  executed: boolean
  money?: { refund_usd: number; discount_value_12m_usd: number }
}

export interface ToolCall {
  tool: string
  arguments: Record<string, unknown>
  allowed: boolean
  executed: boolean
  error: string | null
  receipt: Receipt | null
}

export interface SideResult {
  text: string
  status: string
  calls: ToolCall[]
}

export interface ChatResult {
  turn: number
  naive: SideResult
  guarded: SideResult
}

export interface Scenario {
  id: string
  title: string
  attack_type: string
  customer_id: string
  messages: string[]
}

async function call<T>(path: string, body?: unknown): Promise<T> {
  const res = await fetch(path, body === undefined ? {} : {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  })
  const data = await res.json()
  if (!res.ok) throw new Error(data.error || res.statusText)
  return data as T
}

export const api = {
  scenarios: () => call<{ scenarios: Scenario[]; model: string; backend: string }>("api/scenarios"),
  start: (scenarioId: string) =>
    call<{ session_id: string; scenario: Scenario }>("api/session", { scenario_id: scenarioId }),
  chat: (sessionId: string, message: string) =>
    call<ChatResult>("api/chat", { session_id: sessionId, message }),
}

export function receiptStatus(call: ToolCall): ReceiptStatus {
  if (call.receipt) return call.receipt.status
  return call.error ? "ERROR" : call.executed ? "ALLOWED" : "BLOCKED"
}

export function moneyGiven(call: ToolCall): number {
  const m = call.receipt?.money
  return m ? (m.refund_usd || 0) + (m.discount_value_12m_usd || 0) : 0
}

export function formatArgs(args: Record<string, unknown> | undefined): string {
  return Object.entries(args ?? {})
    .map(([k, v]) => `${k}=${typeof v === "string" ? JSON.stringify(v) : String(v)}`)
    .join(", ")
}
