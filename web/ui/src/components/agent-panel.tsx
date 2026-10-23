import { useEffect, useRef } from "react"
import { Bot, ShieldCheck, ShieldOff, User } from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { Card, CardAction, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { ReceiptCard } from "@/components/receipt-card"
import { cn } from "@/lib/utils"
import type { Mode, ToolCall } from "@/lib/api"

export type Entry =
  | { kind: "customer"; text: string }
  | { kind: "agent"; text: string }
  | { kind: "call"; call: ToolCall }
  | { kind: "status"; text: string }

const META = {
  naive: { title: "Naive agent", subtitle: "No guardrails", icon: ShieldOff, accent: "text-red-400", dot: "bg-red-500" },
  guarded: { title: "Guarded agent", subtitle: "AgentGuard policies", icon: ShieldCheck, accent: "text-emerald-400", dot: "bg-emerald-500" },
} as const

function Stats({ given, blocked, accent }: { given: number; blocked: number; accent: string }) {
  return (
    <>
      <Badge variant="outline" className="gap-1 font-mono" data-testid="given">
        given away <span className={cn("font-semibold", given > 0 ? accent : "text-foreground")}>${given.toFixed(2)}</span>
      </Badge>
      <Badge variant="outline" className="gap-1 font-mono" data-testid="blocked">
        blocked <span className="font-semibold text-foreground">{blocked}</span>
      </Badge>
    </>
  )
}

// Models sometimes answer with light markdown: render **bold**, drop stray asterisks.
function Rich({ text }: { text: string }) {
  const parts = text.replace(/(^|\n)\s*[-*]\s+/g, "$1• ").split(/\*\*(.+?)\*\*/g)
  return <>{parts.map((p, i) => (i % 2 ? <strong key={i}>{p}</strong> : p.replace(/[*`]/g, "")))}</>
}

export function AgentPanel({ mode, entries, given, blocked, thinking, customerId }: {
  mode: Mode
  entries: Entry[]
  given: number
  blocked: number
  thinking: boolean
  customerId?: string
}) {
  const meta = META[mode]
  const Icon = meta.icon
  const end = useRef<HTMLDivElement>(null)
  useEffect(() => end.current?.scrollIntoView({ block: "end" }), [entries.length, thinking])

  return (
    <Card className="flex h-[70dvh] min-h-0 flex-col gap-0 py-0 md:h-auto" data-testid={`panel-${mode}`}>
      <CardHeader className="border-b py-4">
        <CardTitle className="flex items-center gap-2 text-base">
          <Icon className={cn("size-4", meta.accent)} />
          {meta.title}
        </CardTitle>
        <CardDescription className="flex flex-wrap items-center gap-x-3 gap-y-2">
          {meta.subtitle}
          <span className="flex gap-2 lg:hidden"><Stats given={given} blocked={blocked} accent={meta.accent} /></span>
        </CardDescription>
        <CardAction className="hidden items-center gap-2 lg:flex">
          <Stats given={given} blocked={blocked} accent={meta.accent} />
        </CardAction>
      </CardHeader>
      <CardContent className="min-h-0 flex-1 overflow-y-auto px-4 py-4" data-testid={`log-${mode}`}>
        <div className="flex flex-col gap-3">
          {entries.length === 0 && (
            <p className="py-10 text-center text-sm text-muted-foreground">
              {customerId ? `Signed in as ${customerId}. ` : ""}Replies and decision receipts appear here.
            </p>
          )}
          {entries.map((e, i) => {
            if (e.kind === "customer") return (
              <div key={i} className="flex justify-end gap-2">
                <div className="max-w-[85%] rounded-2xl rounded-tr-sm bg-cyan-600 px-3.5 py-2 text-sm text-white">{e.text}</div>
                <User className="mt-1 size-4 shrink-0 text-muted-foreground" />
              </div>
            )
            if (e.kind === "agent") return (
              <div key={i} className="flex gap-2">
                <Bot className={cn("mt-1 size-4 shrink-0", meta.accent)} />
                <div className="max-w-[85%] whitespace-pre-wrap rounded-2xl rounded-tl-sm bg-muted px-3.5 py-2 text-sm"><Rich text={e.text} /></div>
              </div>
            )
            if (e.kind === "call") return <ReceiptCard key={i} call={e.call} />
            return <p key={i} className="text-center text-xs text-amber-400">{e.text}</p>
          })}
          {thinking && (
            <div className="flex gap-2" data-testid={`thinking-${mode}`}>
              <Bot className={cn("mt-1 size-4 shrink-0 animate-pulse", meta.accent)} />
              <div className="flex w-2/3 flex-col gap-1.5"><Skeleton className="h-3.5 w-full" /><Skeleton className="h-3.5 w-3/4" /></div>
            </div>
          )}
          <div ref={end} />
        </div>
      </CardContent>
    </Card>
  )
}
