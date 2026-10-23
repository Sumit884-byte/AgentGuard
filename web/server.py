"""Simulated Alexa+ demo: one customer, the naive and guarded agents side by side.

Run from the repo root:

    python web/server.py                      # Person A's make_backend (real policies)
    python web/server.py --backend tests.fakes:backend_factory   # dev stand-in only

Then open http://localhost:8000. Uses the same agent loop, prompt and model as
the simulator (default_llm(); see .env.example).
"""

from __future__ import annotations

import argparse
import importlib
import json
import sys
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agentguard.simulator import (  # noqa: E402
    SCENARIOS,
    SupportAgent,
    ToolExecutor,
    default_llm,
    get_scenario,
)
from agentguard.simulator.runner import BackendFactory  # noqa: E402

WEB = Path(__file__).resolve().parent
DIST = WEB / "ui" / "dist"  # shadcn/React build (web/ui); falls back to the plain page if missing
INDEX = DIST / "index.html" if (DIST / "index.html").exists() else WEB / "index.html"
STATIC_TYPES = {".js": "text/javascript", ".css": "text/css", ".woff2": "font/woff2", ".svg": "image/svg+xml",
                ".png": "image/png", ".ico": "image/x-icon"}
MODES = ("naive", "guarded")
MAX_SESSIONS = 50
MAX_BODY_BYTES = 16_384
MAX_MESSAGE_CHARS = 2_000


def load_dotenv() -> None:
    import os

    env = ROOT / ".env"
    if not env.exists():
        return
    for line in env.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            value = value.strip().strip("'\"")
            if value:
                os.environ.setdefault(key.strip(), value)


def load_factory(spec: str) -> BackendFactory:
    module_name, _, attr = spec.partition(":")
    return getattr(importlib.import_module(module_name), attr)


@dataclass
class Side:
    agent: SupportAgent
    executor: ToolExecutor
    backend: Any
    initial_state: Any = None


@dataclass
class Session:
    scenario_id: str
    sides: dict[str, Side]
    turn: int = 0
    lock: threading.Lock = field(default_factory=threading.Lock)


class Demo:
    def __init__(self, factory: BackendFactory, backend_label: str, llm: Any = None) -> None:
        self.factory = factory
        self.backend_label = backend_label
        self.llm = llm or default_llm()
        self.sessions: dict[str, Session] = {}
        self.pool = ThreadPoolExecutor(max_workers=8)

    def start(self, scenario_id: str) -> dict[str, Any]:
        scenario = get_scenario(scenario_id)
        sides = {}
        for mode in MODES:
            backend = self.factory(scenario, mode)
            executor = ToolExecutor(backend)
            agent = SupportAgent(llm=self.llm, executor=executor, customer_id=scenario.authenticated_customer_id)
            sides[mode] = Side(agent, executor, backend, backend.snapshot())
        if len(self.sessions) >= MAX_SESSIONS:
            self.sessions.pop(next(iter(self.sessions)))
        session_id = uuid.uuid4().hex
        self.sessions[session_id] = Session(scenario_id, sides)
        return {"session_id": session_id, "scenario": _scenario_json(scenario)}

    def chat(self, session_id: str, message: str) -> dict[str, Any]:
        session = self.sessions.get(session_id)
        if session is None:
            raise KeyError("unknown or expired session; start a new one")
        with session.lock:
            session.turn += 1
            futures = {mode: self.pool.submit(self._run_side, session.sides[mode], session.turn, message) for mode in MODES}
            return {"turn": session.turn, **{mode: f.result() for mode, f in futures.items()}}

    @staticmethod
    def _run_side(side: Side, turn: int, message: str) -> dict[str, Any]:
        start = len(side.executor.calls)
        try:
            outcome = side.agent.respond(turn, message)
            text, status = outcome.text, outcome.status
        except Exception as exc:  # show provider errors on the card instead of a 500
            text, status = "", f"error: {type(exc).__name__}: {exc}"
        calls = [
            {
                "tool": c.tool_name,
                "arguments": c.arguments,
                "allowed": c.allowed,
                "executed": c.executed,
                "error": c.error,
                "receipt": c.receipt,
            }
            for c in side.executor.calls[start:]
        ]
        state = side.backend.snapshot()
        return {"text": text, "status": status, "calls": calls, "state": state,
                "loss": session_loss(side.initial_state, state)}


def session_loss(initial: Any, current: Any) -> float | None:
    """Money given away so far, by the same rule as the scoreboard (contracts-v2 section 6).

    None when the backend's snapshots do not have the billing-store shape (test stand-ins).
    """
    from agentguard.analytics.export import calculate_state_loss

    try:
        return calculate_state_loss(initial, current)
    except Exception:
        return None


def _scenario_json(s) -> dict[str, Any]:
    return {
        "id": s.id,
        "title": s.title,
        "attack_type": s.attack_type,
        "customer_id": s.authenticated_customer_id,
        "messages": list(s.customer_messages),
    }


def make_handler(demo: Demo) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def _send(self, code: int, body: bytes, content_type: str) -> None:
            self.send_response(code)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _json(self, code: int, payload: Any) -> None:
            self._send(code, json.dumps(payload, default=str).encode(), "application/json")

        def do_GET(self) -> None:
            path = self.path.split("?", 1)[0]
            if path in ("/", "/index.html"):
                self._send(200, INDEX.read_bytes(), "text/html; charset=utf-8")
            elif path.startswith("/assets/") and DIST.is_dir():
                asset = (DIST / path.lstrip("/")).resolve()
                if asset.is_relative_to(DIST.resolve()) and asset.is_file() and asset.suffix in STATIC_TYPES:
                    self._send(200, asset.read_bytes(), STATIC_TYPES[asset.suffix])
                else:
                    self._json(404, {"error": "not found"})
            elif self.path == "/api/scenarios":
                self._json(200, {
                    "scenarios": [_scenario_json(s) for s in SCENARIOS],
                    "model": demo.llm.model,
                    "backend": demo.backend_label,
                })
            else:
                self._json(404, {"error": "not found"})

        def do_POST(self) -> None:
            try:
                length = int(self.headers.get("Content-Length") or 0)
                if length > MAX_BODY_BYTES:
                    self._json(413, {"error": "request too large"})
                    return
                body = json.loads(self.rfile.read(length) or b"{}")
                if self.path == "/api/session":
                    self._json(200, demo.start(body["scenario_id"]))
                elif self.path == "/api/chat":
                    message = str(body.get("message", "")).strip()
                    if not message:
                        raise ValueError("message is empty")
                    if len(message) > MAX_MESSAGE_CHARS:
                        raise ValueError(f"message is longer than {MAX_MESSAGE_CHARS} characters")
                    self._json(200, demo.chat(body["session_id"], message))
                else:
                    self._json(404, {"error": "not found"})
            except (KeyError, ValueError, json.JSONDecodeError) as exc:
                self._json(400, {"error": str(exc)})

        def log_message(self, fmt: str, *args: Any) -> None:
            sys.stderr.write("web: " + fmt % args + "\n")

    return Handler


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument(
        "--backend",
        default="agentguard.integration.backend:make_backend",
        help="module:function returning a backend for (scenario, mode)",
    )
    args = parser.parse_args()

    load_dotenv()
    try:
        factory = load_factory(args.backend)
    except (ImportError, AttributeError) as exc:
        sys.exit(f"Cannot load backend {args.backend!r}: {exc}")

    demo = Demo(factory, args.backend)
    print(f"Alexa+ demo on http://localhost:{args.port}  (model {demo.llm.model}, backend {args.backend})")
    ThreadingHTTPServer(("127.0.0.1", args.port), make_handler(demo)).serve_forever()


if __name__ == "__main__":
    main()
