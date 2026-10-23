import json

import pytest

from agentguard.simulator import get_scenario, load_run, load_run_dir, new_run_dir, run_scenario, save_run
from agentguard.simulator import __main__ as cli

from .fakes import ScriptedLLM, backend_factory, text, tool


def _guarded_s5_run():
    llm = ScriptedLLM([tool("apply_discount", customer_id="C-1005", percent=20, reason="loyal"), text("no"),
                       text("ok"), text("ok")])
    return run_scenario(get_scenario("S5"), "guarded", backend_factory, llm)


def test_save_and_load_round_trip(tmp_path):
    run = _guarded_s5_run()
    path = save_run(run, tmp_path)

    assert path.name == "S5.guarded.json"
    raw = json.loads(path.read_text())
    assert raw["targeted_policies"] == ["no_discount_stacking", "max_discount"]
    assert raw["tool_calls"][0]["receipt"]["violated_policy"] == "one_discount_per_customer"

    loaded = load_run(path)
    assert loaded == run
    assert loaded.blocked_calls[0].receipt["status"] == "BLOCKED"


def test_new_run_dir_refuses_to_overwrite(tmp_path):
    first = new_run_dir(tmp_path, "r1")
    assert first == tmp_path / "r1" and first.is_dir()
    with pytest.raises(FileExistsError):
        new_run_dir(tmp_path, "r1")


def test_load_run_dir_keys_by_scenario_and_mode_and_skips_traces(tmp_path):
    save_run(_guarded_s5_run(), tmp_path)
    (tmp_path / "S5.trace.json").write_text("{}")
    runs = load_run_dir(tmp_path)
    assert list(runs) == [("S5", "guarded")]


def test_cli_runs_and_saves_every_scenario_mode(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "default_llm", lambda: ScriptedLLM([text("Hello")] * 100))
    code = cli.main(["--backend", "tests.fakes:backend_factory", "--scenarios", "S1", "S3",
                     "--out", str(tmp_path), "--run-id", "demo"])
    assert code == 0
    names = sorted(p.name for p in (tmp_path / "demo").iterdir())
    assert names == ["S1.guarded.json", "S1.naive.json", "S3.guarded.json", "S3.naive.json"]
    assert "4 runs, 0 not completed" in capsys.readouterr().out


def test_cli_rejects_missing_backend(tmp_path):
    with pytest.raises(SystemExit):
        cli.main(["--backend", "no.such.module:make", "--out", str(tmp_path)])
