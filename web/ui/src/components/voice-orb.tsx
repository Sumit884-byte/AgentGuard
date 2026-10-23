import { Loader2, Mic } from "lucide-react"

import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"
import { cn } from "@/lib/utils"

/** The Alexa-style ring: tap to talk. Pulses while listening, spins while the agents think. */
export function VoiceOrb({ listening, busy, onClick }: { listening: boolean; busy: boolean; onClick: () => void }) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <button
          type="button"
          aria-label="Talk"
          data-testid="voice-orb"
          disabled={busy}
          onClick={onClick}
          className={cn(
            "relative grid size-20 place-items-center rounded-full p-[3px] transition-shadow disabled:cursor-default",
            "bg-[conic-gradient(from_180deg,#22d3ee,#3b82f6,#22d3ee)]",
            listening && "shadow-[0_0_0_10px_rgba(34,211,238,0.15),0_0_40px_rgba(34,211,238,0.5)]",
            busy && "animate-spin [animation-duration:2.4s]",
          )}
        >
          <span className="grid size-full place-items-center rounded-full bg-background">
            {busy ? <Loader2 className="size-7 animate-spin text-cyan-400 [animation-direction:reverse]" />
                  : <Mic className={cn("size-7 text-cyan-400", listening && "animate-pulse")} />}
          </span>
        </button>
      </TooltipTrigger>
      <TooltipContent>{busy ? "Both agents are thinking" : listening ? "Listening…" : "Tap and speak"}</TooltipContent>
    </Tooltip>
  )
}
