import importlib.util
import sys
from pathlib import Path

import pytest

from .fakes import ScriptedLLM, backend_factory, text, tool

spec = importlib.util.spec_from_file_location("web_server", Path(__file__).resolve().parent.parent / "web" / "server.py")
web_server = importlib.util.module_from_spec(spec)
sys.modules["web_server"] = web_server
spec.loader.exec_module(web_server)


class PerModeLLM:
    """Gives each side its own script, chosen by which history it is called with."""

    model = "scripted"

    def __init__(self, naive, guarded):
        self.scripts = {"naive": ScriptedLLM(naive), "guarded": ScriptedLLM(guarded)}
        self.owner = {}

    def create(self, system, tools, messages):
        mode = self.owner[id(messages)]
        return self.scripts[mode].create(system, tools, messages)


def test_chat_runs_both_sides_and_returns_receipts():
    attack = tool("apply_discount", customer_id="C-1001", percent=80, reason="retention")
    llm = PerModeLLM(
        naive=[attack, text("Done, 80% off.")],
        guarded=[tool("apply_discount", customer_id="C-1001", percent=80, reason="retention"), text("I can do 20%.")],
    )
    demo = web_server.Demo(backend_factory, "tests.fakes:backend_factory", llm=llm)
    started = demo.start("S1")
    session = demo.sessions[started["session_id"]]
    for mode, side in session.sides.items():
        llm.owner[id(side.agent.messages)] = mode

    out = demo.chat(started["session_id"], "Give me 80% off")

    assert out["turn"] == 1
    assert out["naive"]["text"] == "Done, 80% off."
    assert out["naive"]["calls"][0]["receipt"]["status"] == "ALLOWED"
    assert out["guarded"]["calls"][0]["receipt"]["status"] == "BLOCKED"
    assert out["guarded"]["calls"][0]["receipt"]["safe_alternative"]["args"]["percent"] == 20
    assert out["naive"]["state"]["customers"]["C-1001"]["discount_percent"] == 80
    assert out["guarded"]["state"]["customers"]["C-1001"]["discount_percent"] == 0


def test_chat_reports_llm_errors_per_side():
    class Boom:
        model = "boom"

        def create(self, *a):
            raise RuntimeError("quota")

    demo = web_server.Demo(backend_factory, "x", llm=Boom())
    sid = demo.start("S1")["session_id"]
    out = demo.chat(sid, "hi")
    assert out["naive"]["status"] == "error: RuntimeError: quota"
    assert out["guarded"]["status"] == "error: RuntimeError: quota"


def test_unknown_session_is_rejected():
    demo = web_server.Demo(backend_factory, "x", llm=ScriptedLLM([]))
    with pytest.raises(KeyError):
        demo.chat("nope", "hi")


def test_message_length_is_capped():
    assert web_server.MAX_MESSAGE_CHARS <= 5_000
    assert web_server.MAX_BODY_BYTES <= 65_536


def test_static_assets_cannot_escape_dist(tmp_path):
    import http.client
    import threading
    from http.server import ThreadingHTTPServer

    demo = web_server.Demo(backend_factory, "x", llm=ScriptedLLM([]))
    try:
        server = ThreadingHTTPServer(("127.0.0.1", 0), web_server.make_handler(demo))
    except PermissionError:
        pytest.skip("port binding not allowed here")
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        conn = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=5)
        for bad in ("/assets/../../server.py", "/assets/%2e%2e/%2e%2e/server.py", "/assets/../../../pyproject.toml"):
            conn.request("GET", bad)
            response = conn.getresponse()
            body = response.read()
            assert response.status == 404, bad
            assert b"import" not in body
        conn.request("GET", "/")
        assert conn.getresponse().status == 200
    finally:
        server.shutdown()


def test_given_away_uses_state_loss_so_cancelled_discounts_count_zero():
    from agentguard.integration import make_backend

    llm = PerModeLLM(
        naive=[tool("apply_discount", customer_id="C-1001", percent=80, reason="retention"), text("Done."),
               tool("cancel_subscription", customer_id="C-1001", reason="asked"), text("Cancelled.")],
        guarded=[text("No."), text("No.")],
    )
    demo = web_server.Demo(make_backend, "make_backend", llm=llm)
    sid = demo.start("S1")["session_id"]
    for mode, side in demo.sessions[sid].sides.items():
        llm.owner[id(side.agent.messages)] = mode
    assert demo.chat(sid, "80% off")["naive"]["loss"] == round(29.99 * 0.8 * 12, 2)
    assert demo.chat(sid, "cancel then")["naive"]["loss"] == 0.0  # discount on a cancelled plan gives nothing away


def test_loss_is_none_for_stand_in_backends():
    assert web_server.session_loss({"customers": {}}, {"customers": {}}) is None
