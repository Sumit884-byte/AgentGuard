import { useCallback, useEffect, useRef, useState } from "react"
import { ArrowRight, RotateCcw, Send, ShieldHalf, Volume2 } from "lucide-react"
import { toast } from "sonner"

import { AgentPanel, type Entry } from "@/components/agent-panel"
import { VoiceOrb } from "@/components/voice-orb"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Separator } from "@/components/ui/separator"
import { api, moneyGiven, receiptStatus, type Mode, type Scenario } from "@/lib/api"
import { cn } from "@/lib/utils"

const MODES: Mode[] = ["naive", "guarded"]
type PerMode<T> = Record<Mode, T>
type SpeakMode = "both" | "guarded" | "naive" | "off"

// Browser speech recognition is prefixed in Chrome and Edge, and missing elsewhere.
type Recognizer = { lang: string; interimResults: boolean; start(): void; onresult: ((e: any) => void) | null;
  onend: (() => void) | null; onerror: ((e: any) => void) | null }
const Recognition: (new () => Recognizer) | undefined =
  (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition

const plain = (t: string) => t.replace(/\*\*(.+?)\*\*/g, "$1").replace(/[*`]/g, "")
const empty = <T,>(v: T): PerMode<T> => ({ naive: v, guarded: v })

export default function App() {
  const [scenarios, setScenarios] = useState<Scenario[]>([])
  const [meta, setMeta] = useState({ model: "", backend: "" })
  const [scenarioId, setScenarioId] = useState("")
  const [session, setSession] = useState<{ id: string; scenario: Scenario } | null>(null)
  const [entries, setEntries] = useState<PerMode<Entry[]>>(empty([]))
  const [given, setGiven] = useState<PerMode<number>>(empty(0))
  const [blocked, setBlocked] = useState<PerMode<number>>(empty(0))
  const [nextLine, setNextLine] = useState(0)
  const [text, setText] = useState("")
  const [busy, setBusy] = useState(false)
  const [listening, setListening] = useState(false)
  const [speak, setSpeak] = useState<SpeakMode>("both")
  const recognizer = useRef<Recognizer | null>(null)

  const start = useCallback(async (id: string) => {
    try {
      const data = await api.start(id)
      setSession({ id: data.session_id, scenario: data.scenario })
      setEntries(empty([])); setGiven(empty(0)); setBlocked(empty(0)); setNextLine(0)
    } catch (e) {
      toast.error(`Could not start: ${(e as Error).message}`)
    }
  }, [])

  useEffect(() => {
    api.scenarios().then((d) => {
      setScenarios(d.scenarios)
      setMeta({ model: d.model, backend: d.backend })
      const first = d.scenarios[0]?.id
      if (first) { setScenarioId(first); start(first) }
    }).catch((e) => toast.error(`Server unreachable: ${e.message}`))
  }, [start])

  const pickScenario = (id: string) => { setScenarioId(id); start(id) }

  const say = useCallback((replies: PerMode<string>) => {
    if (!("speechSynthesis" in window) || speak === "off") return
    speechSynthesis.cancel()
    for (const m of MODES) {
      if ((speak !== "both" && speak !== m) || !replies[m]) continue
      const prefix = speak === "both" ? (m === "naive" ? "Naive agent: " : "Guarded agent: ") : ""
      const u = new SpeechSynthesisUtterance(prefix + plain(replies[m]))
      u.rate = 1.05
      speechSynthesis.speak(u)
    }
  }, [speak])

  const send = useCallback(async (raw: string) => {
    const message = raw.trim()
    if (!message || busy || !session) return
    setText("")
    setBusy(true)
    setEntries((prev) => ({
      naive: [...prev.naive, { kind: "customer", text: message }],
      guarded: [...prev.guarded, { kind: "customer", text: message }],
    }))
    try {
      const data = await api.chat(session.id, message)
      const add: PerMode<Entry[]> = empty([])
      const addGiven = empty(0), addBlocked = empty(0)
      for (const m of MODES) {
        const side = data[m]
        add[m] = [
          ...side.calls.map((call): Entry => ({ kind: "call", call })),
          ...(side.text ? [{ kind: "agent", text: side.text } as Entry] : []),
          ...(side.status !== "completed" ? [{ kind: "status", text: side.status } as Entry] : []),
        ]
        addGiven[m] = side.calls.reduce((sum, c) => sum + moneyGiven(c), 0)
        addBlocked[m] = side.calls.filter((c) => ["BLOCKED", "NEEDS_APPROVAL"].includes(receiptStatus(c))).length
      }
      setEntries((prev) => ({ naive: [...prev.naive, ...add.naive], guarded: [...prev.guarded, ...add.guarded] }))
      setGiven((p) => ({ naive: p.naive + addGiven.naive, guarded: p.guarded + addGiven.guarded }))
      setBlocked((p) => ({ naive: p.naive + addBlocked.naive, guarded: p.guarded + addBlocked.guarded }))
      say({ naive: data.naive.text, guarded: data.guarded.text })
    } catch (e) {
      toast.error((e as Error).message)
    } finally {
      setBusy(false)
    }
  }, [busy, session, say])

  const listen = () => {
    if (!Recognition) { toast("Voice input needs Chrome or Edge. You can type instead."); return }
    if (busy) return
    speechSynthesis?.cancel()
    const r = new Recognition()
    r.lang = "en-US"
    r.interimResults = true
    r.onresult = (e: any) => {
      const t = Array.from(e.results as ArrayLike<any>).map((x: any) => x[0].transcript).join("")
      setText(t)
      if (e.results[e.results.length - 1].isFinal) send(t)
    }
    r.onend = () => setListening(false)
    r.onerror = (e: any) => toast.error(`Voice error: ${e.error}. You can type instead.`)
    recognizer.current = r
    setListening(true)
    r.start()
  }

  const story = session?.scenario.messages ?? []
  const playNext = () => {
    if (nextLine >= story.length) { toast("That's the end of this story. Start over or pick another."); return }
    send(story[nextLine])
    setNextLine((n) => n + 1)
  }

  return (
    <div className="flex min-h-dvh flex-col bg-background bg-[radial-gradient(ellipse_at_top,rgba(34,211,238,0.08),transparent_60%)] text-foreground md:h-dvh">
      <header className="flex flex-wrap items-center gap-x-6 gap-y-3 border-b px-6 py-3">
        <div className="flex items-center gap-2.5">
          <span className="grid size-8 place-items-center rounded-lg bg-gradient-to-br from-cyan-400 to-blue-600">
            <ShieldHalf className="size-4.5 text-white" />
          </span>
          <div className="leading-tight">
            <p className="font-semibold">AgentGuard</p>
            <p className="text-xs text-muted-foreground">Alexa+ billing assistant</p>
          </div>
        </div>
        <Select value={scenarioId} onValueChange={pickScenario}>
          <SelectTrigger className="w-full sm:w-80" data-testid="scenario-select" aria-label="Customer story">
            <SelectValue placeholder="Customer story" />
          </SelectTrigger>
          <SelectContent>
            {scenarios.map((s) => (
              <SelectItem key={s.id} value={s.id} data-testid={`scenario-${s.id}`}>{s.id} · {s.title}</SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Select value={speak} onValueChange={(v) => setSpeak(v as SpeakMode)}>
          <SelectTrigger className="w-44" data-testid="speak-select" aria-label="Speak replies">
            <Volume2 className="size-4 text-muted-foreground" /><SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="both">Speak both</SelectItem>
            <SelectItem value="guarded">Guarded only</SelectItem>
            <SelectItem value="naive">Naive only</SelectItem>
            <SelectItem value="off" data-testid="speak-off">Muted</SelectItem>
          </SelectContent>
        </Select>
        <div className="ml-auto flex items-center gap-2">
          {meta.model && <Badge variant="secondary" className="font-mono">{meta.model}</Badge>}
          {meta.backend && <Badge variant="outline" className="font-mono">{meta.backend.split(":").pop()}</Badge>}
        </div>
      </header>

      <section className="flex flex-col items-center gap-3 px-6 pt-5 pb-4">
        <VoiceOrb listening={listening} busy={busy} onClick={listen} />
        <p className="min-h-5 text-center text-sm text-muted-foreground" data-testid="hint">
          {busy ? "Both agents are thinking…" : listening ? "Listening…"
            : session ? `${session.scenario.title} · signed in as ${session.scenario.customer_id}` : "Loading…"}
        </p>
        <form className="flex w-full max-w-3xl gap-2" onSubmit={(e) => { e.preventDefault(); send(text) }}>
          <Input
            data-testid="message-input"
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder="Say something to the billing assistant…"
            className="h-10"
          />
          <Button type="submit" size="lg" disabled={busy || !text.trim()} data-testid="send">
            <Send /> Send
          </Button>
        </form>
        <div className="flex flex-wrap items-center justify-center gap-2">
          <Button variant="secondary" size="sm" onClick={playNext} disabled={busy || !session} data-testid="next-line">
            Next line from this story <ArrowRight />
          </Button>
          <Button variant="ghost" size="sm" onClick={() => start(scenarioId)} disabled={busy} data-testid="reset">
            <RotateCcw /> Start over
          </Button>
          {story.length > 0 && (
            <>
              <Separator orientation="vertical" className="mx-1 h-5" />
              <div className="flex gap-1" aria-label="Story progress">
                {story.map((_, i) => (
                  <span key={i} className={cn("h-1.5 w-6 rounded-full", i < nextLine ? "bg-cyan-400" : "bg-muted")} />
                ))}
              </div>
            </>
          )}
        </div>
      </section>

      <main className="grid min-h-0 flex-1 grid-cols-1 gap-4 px-4 pb-6 sm:px-6 md:grid-cols-2">
        {MODES.map((m) => (
          <AgentPanel key={m} mode={m} entries={entries[m]} given={given[m]} blocked={blocked[m]}
                      thinking={busy} customerId={session?.scenario.customer_id} />
        ))}
      </main>
    </div>
  )
}
