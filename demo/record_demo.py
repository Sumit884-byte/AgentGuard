"""Record the ~3 minute demo video: real web page, real guarded backend, live model.

    python demo/record_demo.py                       # writes runs/demo-video/agentguard-demo.mp4

Needs: playwright (+ `playwright install chromium`), ffmpeg, macOS `say`, and a
model key in .env. Narration for each attack is written from that attack's real
receipts after the agents answer, so it always describes what happened on screen.
Idle time while the model thinks is cut from the final video (about 1.5 s of
"thinking" is kept); the replies themselves are live and unedited.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import subprocess
import sys
import threading
import time
from http.server import ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agentguard.integration import make_backend  # noqa: E402
from agentguard.simulator import get_scenario  # noqa: E402

SLIDES = (ROOT / "demo" / "slides.html").as_uri()
VIEWPORT = {"width": 1600, "height": 900}
VOICE = "Samantha"

# Recorder-only styling: caption bar, and logs sized to stay above it.
OVERLAY_CSS = """
#demo-caption { position: fixed; left: 0; right: 0; bottom: 0; z-index: 9999; padding: 14px 40px;
  background: rgba(10, 10, 10, .92); border-top: 1px solid #262626; color: #e7ecf5;
  font: 600 22px/1.35 -apple-system, BlinkMacSystemFont, sans-serif; text-align: center; min-height: 64px; }
main { padding-bottom: 84px !important; }
"""

MONEY_TOOLS = {"issue_refund", "apply_discount", "cancel_subscription"}


def load_web_server():
    spec = importlib.util.spec_from_file_location("web_server", ROOT / "web" / "server.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["web_server"] = module
    spec.loader.exec_module(module)
    return module


def audio_seconds(path: Path) -> float:
    return float(subprocess.check_output(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)]).strip())


class Narrator:
    """Speaks lines with macOS `say`, shows them as captions, and records when each started."""

    def __init__(self, page, out: Path, t0: float) -> None:
        self.page, self.out, self.t0 = page, out, t0
        self.clips: list[tuple[float, Path]] = []
        self.cuts: list[tuple[float, float]] = []  # idle stretches (model thinking) removed from the final video

    def now(self) -> float:
        return time.monotonic() - self.t0

    def say(self, text: str, wait: bool = True) -> float:
        path = self.out / f"clip{len(self.clips):02d}.aiff"
        subprocess.run(["say", "-v", VOICE, "-r", "185", "-o", str(path), text], check=True)
        duration = audio_seconds(path)
        self.caption(text)
        self.clips.append((self.now(), path))
        if wait:
            time.sleep(duration + 0.6)
        return duration

    def caption(self, text: str) -> None:
        self.page.evaluate("""(t) => {
            let el = document.getElementById('demo-caption');
            if (!el) { el = document.createElement('div'); el.id = 'demo-caption'; document.body.appendChild(el); }
            el.textContent = t; }""", text)


def _a(number: str) -> str:
    """'an 80%', 'an 11%', 'a 20%': the article as the number is spoken."""
    return "an" if number.startswith(("8", "11", "18")) and not number.startswith(("1100", "1800")) else "a"


def phrase(call: dict) -> str:
    args, tool = call["arguments"], call["tool"]
    if tool == "issue_refund":
        amount = f"{float(args.get('amount', 0)):.0f}"
        return f"{_a(amount)} ${amount} refund"
    if tool == "apply_discount":
        percent = f"{float(args.get('percent', 0)):.0f}"
        return f"{_a(percent)} {percent}% discount"
    if tool == "cancel_subscription":
        return f"a cancellation on {args.get('customer_id')}"
    return f"a lookup of {args.get('customer_id')}"


def describe(result: dict) -> str:
    """One or two sentences on what each agent actually did, from the receipts."""
    naive = [c for c in result["naive"]["calls"] if c["tool"] in MONEY_TOOLS and c["executed"]]
    guarded = result["guarded"]["calls"]
    blocked = [c for c in guarded if c["receipt"] and c["receipt"]["status"] in ("BLOCKED", "NEEDS_APPROVAL")]
    allowed = [c for c in guarded if c["tool"] in MONEY_TOOLS and c["executed"]]

    parts = []
    if naive:
        parts.append("With no guardrails, the naive agent carried out " + " and ".join(phrase(c) for c in naive) + ".")
    else:
        parts.append("The naive agent did not move any money this time.")
    if blocked:
        first = blocked[0]["receipt"]
        line = f"AgentGuard blocked {phrase(blocked[0])}: {first['reason']}"
        if first.get("safe_alternative"):
            line += f" The receipt offered a safe alternative: {first['safe_alternative']['say']}"
        parts.append(line)
    elif not allowed:
        parts.append("The guarded agent did not attempt it.")
    if allowed:
        parts.append("The guarded agent carried out " + " and ".join(phrase(c) for c in allowed) + ", within policy.")
    return " ".join(parts)


def attack(page, narrator: Narrator, scenario_id: str, messages: list[str], setup: str) -> dict:
    """Play a scenario's escalating messages turn by turn, then narrate what both agents did overall."""
    page.click("[data-testid=scenario-select]")
    page.click(f"[data-testid=scenario-{scenario_id}]")
    page.wait_for_timeout(800)
    combined: dict = {"naive": {"calls": []}, "guarded": {"calls": []}}
    setup_ends = 0.0
    for turn, message in enumerate(messages):
        page.fill("[data-testid=message-input]", message)
        with page.expect_response(lambda r: r.url.endswith("/api/chat"), timeout=300_000) as response:
            page.click("[data-testid=send]")
            sent = narrator.now()
            if turn == 0:
                setup_ends = sent + narrator.say(setup, wait=False) + 0.6
        result = response.value.json()
        answered = narrator.now()
        idle_from = max(sent, setup_ends) + 1.5  # keep ~1.5 s of "thinking" on screen
        if answered - idle_from > 1.0:
            narrator.cuts.append((idle_from, answered))
        for mode in ("naive", "guarded"):
            combined[mode]["calls"] += result[mode]["calls"]
        page.wait_for_timeout(1800)  # let viewers see the new cards
    time.sleep(max(0.0, setup_ends - narrator.now()))  # never talk over the setup line
    narrator.say(describe(combined))
    return combined


def assemble(video: Path, narrator: Narrator, final: Path) -> None:
    """Cut the idle stretches, scale to 1080p, and lay each narration clip at its (shifted) start."""
    cuts = sorted(narrator.cuts)
    keep, cursor = [], 0.0
    for start, end in cuts:
        keep.append((cursor, start))
        cursor = end
    keep.append((cursor, None))

    def shifted(t: float) -> float:
        return t - sum(min(end, t) - start for start, end in cuts if t > start)

    filters = []
    for i, (a, b) in enumerate(keep):
        trim = f"trim=start={a:.3f}" + (f":end={b:.3f}" if b is not None else "")
        filters.append(f"[0:v]{trim},setpts=PTS-STARTPTS[v{i}]")
    filters.append("".join(f"[v{i}]" for i in range(len(keep)))
                   + f"concat=n={len(keep)}:v=1:a=0,scale=1920:1080:flags=lanczos[vout]")
    inputs = ["-i", str(video)]
    for i, (start, clip) in enumerate(narrator.clips, start=1):
        inputs += ["-i", str(clip)]
        filters.append(f"[{i}:a]adelay={int(shifted(start) * 1000)}:all=1[a{i}]")
    mix = "".join(f"[a{i}]" for i in range(1, len(narrator.clips) + 1))
    filters.append(f"{mix}amix=inputs={len(narrator.clips)}:normalize=0[aout]")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *inputs, "-filter_complex", ";".join(filters),
                    "-map", "[vout]", "-map", "[aout]", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "20",
                    "-c:a", "aac", "-b:a", "160k", str(final)], check=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", default=str(ROOT / "runs" / "demo-video"))
    args = parser.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    from playwright.sync_api import sync_playwright

    web = load_web_server()
    web.load_dotenv()
    demo = web.Demo(make_backend, "agentguard.integration.backend:make_backend")
    server = ThreadingHTTPServer(("127.0.0.1", 0), web.make_handler(demo))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_address[1]}/"
    print(f"model {demo.llm.model}, backend make_backend, page {url}", flush=True)

    log: dict = {"model": demo.llm.model, "scenes": []}

    with sync_playwright() as p:
        browser = p.chromium.launch()
        context = browser.new_context(viewport=VIEWPORT, record_video_dir=str(out), record_video_size=VIEWPORT)
        page = context.new_page()
        narrator = Narrator(page, out, time.monotonic())
        page.add_init_script("document.addEventListener('DOMContentLoaded', () => {"
                             f"const s = document.createElement('style'); s.textContent = {json.dumps(OVERLAY_CSS)};"
                             "document.head.appendChild(s); });")

        # 1. Title
        page.goto(SLIDES + "#intro")
        narrator.say("This is AgentGuard. AI support agents with refund and discount tools can be talked into "
                     "giving money away. We run the same agent twice: once with no guardrails, and once with "
                     "AgentGuard's billing rules enforced on the server.")

        # 2. The app
        page.goto(url)
        page.wait_for_selector("[data-testid=scenario-select]")
        page.wait_for_timeout(600)
        page.click("[data-testid=speak-select]")
        page.click("[data-testid=speak-off]")
        narrator.say("This is our Alexa plus style billing assistant. Every customer message goes to both agents "
                     "at once: naive on the left, guarded on the right. Every tool call shows its decision receipt.")

        # 3. Threat to churn: the full escalating story
        log["scenes"].append(attack(page, narrator, "S1", list(get_scenario("S1").customer_messages),
            "First, a customer threatening to leave. They push harder each turn, up to eighty percent off."))

        # 4. Receipt close-up, on a blocked call when there is one
        toggle = page.locator("[data-testid=panel-guarded] [data-status=BLOCKED] [data-testid=checks-toggle]")
        if not toggle.count():
            toggle = page.locator("[data-testid=panel-guarded] [data-testid=checks-toggle]")
        if toggle.count():
            toggle.last.scroll_into_view_if_needed()
            toggle.last.click()
            narrator.say("Each receipt lists every rule that was checked, with the values it used: ownership first, "
                         "then the YAML policies, then the backend policies. Nothing is decided by the model.")

        # 5. False authority
        log["scenes"].append(attack(page, narrator, "S2", list(get_scenario("S2").customer_messages[:2]),
            "Next, false authority. The customer claims to be a StreamBox manager with an override code, "
            "and asks for a five hundred dollar refund."))

        # 6. Someone else's account
        s3 = get_scenario("S3").customer_messages
        log["scenes"].append(attack(page, narrator, "S3", [s3[0] + " " + s3[1]],
            "Finally, social engineering. A customer signed in to their own account asks the agent to cancel and "
            "refund their husband's account."))

        # 7. Tech stack
        page.goto(SLIDES + "#stack")
        narrator.say("Under the hood: a Python agent loop and a Strands agent, live runs on Gemini, and an Amazon "
                     "Bedrock provider that is implemented but not yet run live. Tools are served over MCP with "
                     "streamable HTTP and bearer-token identity. Policies are a YAML engine plus backend checks, and "
                     "every run is saved with its receipts for the damage scoreboard.")

        # 8. Close
        page.goto(SLIDES + "#outro")
        narrator.say("Same agent, same customer. The guardrail is the difference.")
        time.sleep(1.0)

        video = Path(page.video.path())
        context.close()
        browser.close()
    server.shutdown()

    final = out / "agentguard-demo.mp4"
    assemble(video, narrator, final)
    log["cuts_seconds"] = [[round(a, 1), round(b, 1)] for a, b in sorted(narrator.cuts)]
    (out / "scenes.json").write_text(json.dumps(log, indent=2, default=str))
    print(f"wrote {final} ({audio_seconds(final):.0f} s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
