"""Synthetic scenario/replay support with no physical hardware dependency."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from .experiment import ExperimentConfig, ExperimentResult, Sample
from .measurement import Measurement, Quality
from .reporting import write_result


def scenario_path(name_or_path: str | Path) -> Path:
    candidate = Path(name_or_path)
    if candidate.is_file():
        return candidate
    names = [candidate, Path("tests/fixtures/scenarios") / candidate / "scenario.json"]
    repo_root = Path(__file__).resolve().parents[2]
    names.append(repo_root / "tests/fixtures/scenarios" / candidate / "scenario.json")
    for path in names:
        if path.is_file():
            return path
    raise FileNotFoundError(f"synthetic scenario not found: {name_or_path}")


def load_scenario(name_or_path: str | Path) -> dict[str, Any]:
    path = scenario_path(name_or_path)
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("synthetic") is not True:
        raise ValueError("replay refuses scenarios that are not explicitly marked synthetic")
    return data


def replay_scenario(name_or_path: str | Path, base_dir: str | Path = "results") -> Path:
    data = load_scenario(name_or_path)
    default_time = datetime(2025, 1, 1, tzinfo=UTC)
    samples: list[Sample] = []
    for sequence, record in enumerate(data.get("samples", [])):
        timestamp = _parse_time(record.get("timestamp"), default_time + timedelta(seconds=sequence))
        measurements = [
            Measurement(
                timestamp=timestamp,
                source=item["source"],
                device_id=item["device_id"],
                channel=item["channel"],
                unit=item.get("unit", "raw"),
                value=item.get("value"),
                quality=Quality(item.get("quality", "GOOD")),
                error=item.get("error"),
                metadata=item.get("metadata", {}),
            )
            for item in record.get("measurements", [])
        ]
        samples.append(
            Sample(
                phase=record.get("phase", "passive"),
                sequence=sequence,
                scheduled_at=timestamp,
                started_at=timestamp,
                finished_at=timestamp + timedelta(seconds=float(record.get("duration_s", 0))),
                measurements=measurements,
            )
        )
    started = samples[0].started_at if samples else default_time
    finished = samples[-1].finished_at if samples else started
    config = ExperimentConfig(
        mode=data.get("mode", "passive"),
        interval_s=float(data.get("interval_s", 1.0)),
        duration_s=float(data.get("duration_s", max(0, len(samples) - 1))),
        max_temperature_c=data.get("max_temperature_c", 85.0),
    )
    result = ExperimentResult(
        config=config,
        started_at=started,
        finished_at=finished,
        samples=samples,
        guardrail_triggered=data.get("guardrail_triggered"),
        workload_error=data.get("workload_error"),
        interrupted=bool(data.get("interrupted", False)),
        metadata={
            "synthetic": True,
            "scenario": data.get("scenario", scenario_path(name_or_path).parent.name),
        },
    )
    return write_result(result, base_dir)


def _parse_time(value: str | None, default: datetime) -> datetime:
    if not value:
        return default
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
