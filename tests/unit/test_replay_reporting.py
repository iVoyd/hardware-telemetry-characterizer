from __future__ import annotations

import json
from pathlib import Path

from htc.replay import load_scenario, replay_scenario
from htc.reporting import report_run

SCENARIOS = [
    "normal_single_nvme",
    "normal_three_nvme",
    "missing_ipmitool",
    "missing_smartctl",
    "ipmi_timeout",
    "malformed_ipmi_output",
    "sensor_missing_mid_run",
    "stale_sensor",
    "nvme_controller_identity_collision_regression",
    "thermal_guard_trigger",
    "workload_process_failure",
    "collector_command_timeout",
]


def test_all_committed_scenarios_are_explicitly_synthetic() -> None:
    for scenario in SCENARIOS:
        assert load_scenario(scenario)["synthetic"] is True


def test_replay_writes_required_artifacts_and_report(tmp_path: Path) -> None:
    run_dir = replay_scenario("normal_three_nvme", tmp_path)
    assert {path.name for path in run_dir.iterdir()} == {
        "metadata.json",
        "samples.csv",
        "summary.json",
        "report.txt",
    }
    summary = json.loads((run_dir / "summary.json").read_text())
    devices = {row["device_id"] for row in summary["channels"]}
    assert devices == {"nvme0", "nvme1", "nvme2"}
    assert summary["sample_frame_count"] == 2
    assert summary["numeric_observation_count"] == 6
    report = report_run(run_dir)
    assert "Hardware Telemetry Characterizer" in report
    assert "Samples: 2" in report
    assert "Numeric observations: 6" in report


def test_replay_keeps_fault_quality_explicit(tmp_path: Path) -> None:
    run_dir = replay_scenario("ipmi_timeout", tmp_path)
    samples = (run_dir / "samples.csv").read_text()
    assert "TIMEOUT" in samples
    assert "command timed out" in samples
