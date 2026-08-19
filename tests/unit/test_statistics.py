from __future__ import annotations

import csv
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from htc.experiment import ExperimentConfig, ExperimentResult, Sample
from htc.measurement import Measurement, Quality
from htc.reporting import render_report, write_result
from htc.statistics import channel_statistics, derived_metrics, summarize

NOW = datetime(2025, 1, 1, tzinfo=timezone.utc)


def _measurement(
    channel: str, value: float, *, metadata: dict[str, object] | None = None
) -> Measurement:
    return Measurement(
        timestamp=NOW,
        source="synthetic",
        device_id="synthetic-device",
        channel=channel,
        unit="%" if channel == "cpu_utilization" else "°C",
        value=value,
        quality=Quality.GOOD,
        metadata=metadata or {},
    )


def _sample(sequence: int, phase: str, measurements: list[Measurement]) -> Sample:
    timestamp = NOW + timedelta(seconds=sequence)
    return Sample(phase, sequence, timestamp, timestamp, timestamp, measurements)


def _boundary(previous_phase: str, current_phase: str) -> dict[str, object]:
    return {
        "phase_boundary_interval": True,
        "previous_phase": previous_phase,
        "current_phase": current_phase,
    }


def _samples() -> list[Sample]:
    return [
        _sample(
            0,
            "baseline",
            [_measurement("cpu_utilization", 1.0), _measurement("cpu_utilization", 1.0)],
        ),
        _sample(
            1,
            "stimulus",
            [
                _measurement("cpu_utilization", 1.0, metadata=_boundary("baseline", "stimulus")),
                _measurement("temperature", 60.0),
            ],
        ),
        _sample(
            2,
            "stimulus",
            [_measurement("cpu_utilization", 25.0), _measurement("temperature", 61.0)],
        ),
        _sample(3, "stimulus", [_measurement("cpu_utilization", 26.0)]),
        _sample(
            4,
            "recovery",
            [
                _measurement("cpu_utilization", 26.0, metadata=_boundary("stimulus", "recovery")),
                _measurement("temperature", 55.0),
            ],
        ),
        _sample(
            5,
            "recovery",
            [_measurement("cpu_utilization", 1.0), _measurement("temperature", 53.0)],
        ),
        _sample(6, "recovery", [_measurement("cpu_utilization", 0.5)]),
        _sample(7, "recovery", [_measurement("cpu_utilization", 0.5)]),
    ]


def test_boundary_cpu_values_are_excluded_but_instantaneous_values_remain() -> None:
    rows = channel_statistics(_samples())
    cpu_rows = [row for row in rows if row["channel"] == "cpu_utilization"]
    assert {(row["phase"], row["sample_count"]) for row in cpu_rows} == {
        ("baseline", 2),
        ("stimulus", 2),
        ("recovery", 3),
    }
    stimulus = next(row for row in cpu_rows if row["phase"] == "stimulus")
    recovery = next(row for row in cpu_rows if row["phase"] == "recovery")
    assert stimulus["mean"] == 25.5
    assert recovery["mean"] == 2 / 3

    temperature_recovery = next(
        row for row in rows if row["channel"] == "temperature" and row["phase"] == "recovery"
    )
    assert temperature_recovery["sample_count"] == 2
    assert temperature_recovery["mean"] == 54.0


def test_derived_metrics_exclude_boundary_cpu_values() -> None:
    rows = derived_metrics(_samples())
    cpu = next(row for row in rows if row["channel"] == "cpu_utilization")
    assert cpu["stimulus_mean_minus_baseline"] == 24.5
    assert cpu["stimulus_max_minus_baseline"] == 25.0
    assert cpu["recovery_mean_minus_baseline"] == (2 / 3) - 1.0
    assert cpu["recovery_final_minus_baseline"] == -0.5


def test_summary_accounts_for_raw_and_phase_statistic_observations() -> None:
    result = ExperimentResult(
        config=ExperimentConfig(mode="cpu", interval_s=1.0),
        started_at=NOW,
        finished_at=NOW,
        samples=_samples(),
    )
    summary = summarize(result)
    assert summary["numeric_observation_count"] == 13
    assert summary["phase_statistic_observation_count"] == 11
    assert summary["phase_boundary_interval_count"] == 2
    report = render_report({}, summary)
    assert "Numeric observations: 13" in report
    assert "Phase-statistic observations: 11" in report
    assert (
        "Phase-boundary intervals retained in raw evidence (excluded from phase statistics): 2"
        in report
    )
    assert "remain in raw CSV" in report


def test_raw_csv_preserves_boundary_metadata(tmp_path: Path) -> None:
    result = ExperimentResult(
        config=ExperimentConfig(mode="cpu", interval_s=1.0),
        started_at=NOW,
        finished_at=NOW,
        samples=_samples(),
    )
    run_dir = write_result(result, tmp_path)
    with (run_dir / "samples.csv").open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    metadata = [json.loads(row["metadata"]) for row in rows]
    assert {item["current_phase"] for item in metadata if item.get("phase_boundary_interval")} == {
        "stimulus",
        "recovery",
    }
    assert {item["previous_phase"] for item in metadata if item.get("phase_boundary_interval")} == {
        "baseline",
        "stimulus",
    }
    summary = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
    assert summary["phase_boundary_interval_count"] == 2
