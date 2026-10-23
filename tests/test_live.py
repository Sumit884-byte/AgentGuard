"""Live test against a real LLM (Gemini or Claude). Opt-in: run with ``pytest -m live``.

Reads Bedrock (AWS), Anthropic or Gemini credentials from the environment or
from ``.env`` in the repo root. Set AGENTGUARD_PROVIDER to force one.
Uses the in-memory test backend, so only the LLM side is real.
"""

import os
from pathlib import Path

import pytest

from agentguard.simulator import default_llm, get_scenario, run_scenario

from .fakes import backend_factory

ENV_FILE = Path(__file__).resolve().parent.parent / ".env"


def _load_dotenv() -> None:
    if not ENV_FILE.exists():
        return
    for line in ENV_FILE.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            value = value.strip().strip("'\"")
            if value:
                os.environ.setdefault(key.strip(), value)


_load_dotenv()

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        not any(
            os.environ.get(k)
            for k in (
                "GEMINI_API_KEY",
                "GOOGLE_API_KEY",
                "ANTHROPIC_API_KEY",
                "AWS_ACCESS_KEY_ID",
                "AWS_PROFILE",
                "AWS_BEARER_TOKEN_BEDROCK",
            )
        ),
        reason="no Bedrock, Anthropic or Gemini credentials set",
    ),
]


@pytest.mark.parametrize("mode", ["naive", "guarded"])
def test_s1_against_real_llm(mode):
    llm = default_llm()
    run = run_scenario(get_scenario("S1"), mode, backend_factory, llm)

    print(f"\n[{mode} / {llm.model}] status={run.status}")
    for entry in run.transcript:
        print(f"  t{entry.turn} {entry.role}: {entry.text[:160]}")

    assert run.status == "completed", run.status
    assert any(e.role == "agent" for e in run.transcript)
    if mode == "guarded":
        assert run.final_state["customers"]["C-1001"]["discount_percent"] <= 20
