# Hand-made serialization fixture (not a simulator result)

The paired `S1.naive.json` and `S1.guarded.json` files in this folder are manually authored test inputs. They exercise the v2 `ScenarioRun.to_dict()` serialization shape, including snapshots and the full guarded decision receipt. They were not produced by an LLM or an executed simulator run. Their amounts are test values only and must not be reported as project results.

Tests load these files with `agentguard.simulator.load_run_dir()` and write generated traces only under pytest's temporary output directory.