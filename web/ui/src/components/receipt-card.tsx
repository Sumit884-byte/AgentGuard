import { useState } from "react"
import { CheckCircle2, ChevronRight, CircleAlert, Hourglass, ShieldCheck, ShieldX, Sparkles, XCircle } from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible"
import { cn } from "@/lib/utils"
import { formatArgs, receiptStatus, type ToolCall } from "@/lib/api"

const STATUS = {
  ALLOWED: { label: "Allowed", icon: ShieldCheck, rail: "border-l-emerald-500", badge: "bg-emerald-500/15 text-emerald-400" },
  BLOCKED: { label: "Blocked", icon: ShieldX, rail: "border-l-red-500", badge: "bg-red-500/15 text-red-400" },
  NEEDS_APPROVAL: { label: "Needs approval", icon: Hourglass, rail: "border-l-amber-500", badge: "bg-amber-500/15 text-amber-400" },
  ERROR: { label: "Error", icon: CircleAlert, rail: "border-l-zinc-500", badge: "bg-zinc-500/20 text-zinc-300" },
} as const

const LAYER_LABEL = { handler: "Identity", yaml: "YAML policy", backend: "Backend" } as const

export function ReceiptCard({ call }: { call: ToolCall }) {
  const [open, setOpen] = useState(false)
  const r = call.receipt
  const status = receiptStatus(call)
  const s = STATUS[status]
  const Icon = s.icon
  const checks = r?.checks ?? []
  const failed = checks.filter((c) => !c.passed).length

  return (
    <div
      data-testid="receipt"
      data-status={status}
      className={cn("rounded-lg border border-l-4 bg-card/60 px-3 py-2.5 text-sm shadow-sm", s.rail)}
    >
      <div className="flex flex-wrap items-center gap-2">
        <Badge className={cn("gap-1 font-semibold", s.badge)}>
          <Icon className="size-3.5" />
          {s.label}
        </Badge>
        <code className="min-w-0 break-all font-mono text-xs text-foreground/90">
          {call.tool}({formatArgs(r?.args ?? call.arguments)})
        </code>
      </div>

      {status !== "ALLOWED" && (
        <p className="mt-1.5 text-muted-foreground">
          {r?.violated_policy && <span className="mr-1 font-mono text-xs font-semibold text-foreground">{r.violated_policy}</span>}
          {r?.reason || call.error}
        </p>
      )}

      {r?.safe_alternative && (
        <div className="mt-2 flex gap-2 rounded-md border border-emerald-500/30 bg-emerald-500/10 px-2.5 py-2 text-emerald-300">
          <Sparkles className="mt-0.5 size-4 shrink-0" />
          <div className="min-w-0">
            <p className="font-medium">Safe alternative: {r.safe_alternative.say}</p>
            <code className="break-all font-mono text-xs text-emerald-300/80">
              {r.safe_alternative.tool}({formatArgs(r.safe_alternative.args)})
            </code>
          </div>
        </div>
      )}

      {r?.approval_id && (
        <p className="mt-1.5 text-amber-400">Waiting for supervisor approval · {r.approval_id}</p>
      )}

      {checks.length > 0 && (
        <Collapsible open={open} onOpenChange={setOpen} className="mt-2">
          <CollapsibleTrigger
            data-testid="checks-toggle"
            className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"
          >
            <ChevronRight className={cn("size-3.5 transition-transform", open && "rotate-90")} />
            {checks.length} {checks.length === 1 ? "rule" : "rules"} checked{failed ? `, ${failed} failed` : ", all passed"}
          </CollapsibleTrigger>
          <CollapsibleContent>
            <ul className="mt-2 space-y-1 rounded-md bg-muted/40 p-2">
              {checks.map((c, i) => (
                <li key={`${c.layer}-${c.rule}-${i}`} className="flex items-start gap-2 text-xs">
                  {c.passed
                    ? <CheckCircle2 className="mt-0.5 size-3.5 shrink-0 text-emerald-400" />
                    : <XCircle className="mt-0.5 size-3.5 shrink-0 text-red-400" />}
                  <span className="w-20 shrink-0 text-muted-foreground">{LAYER_LABEL[c.layer]}</span>
                  <span className="font-mono">{c.rule}</span>
                  <span className="ml-auto truncate pl-2 font-mono text-muted-foreground">
                    {Object.entries(c.values).map(([k, v]) => `${k}=${v}`).join(" ")}
                  </span>
                </li>
              ))}
            </ul>
          </CollapsibleContent>
        </Collapsible>
      )}
    </div>
  )
}
