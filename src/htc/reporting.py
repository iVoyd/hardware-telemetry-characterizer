"""Run artifact writing and human-readable report rendering."""

from __future__ import annotations

import csv
import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .experiment import ExperimentResult, Sample
from .statistics import summarize


def write_result(result: ExperimentResult, base_dir: str | Path = "results") -> Path:
    """Write one timestamped run directory and return its path."""

    base = Path(base_dir)
    run_name = "run-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    run_dir = base / run_name
    run_dir.mkdir(parents=True, exist_ok=False)
    summary = summarize(result)
    metadata: dict[str, Any] = {
        "schema_version": 1,
        "created_at": result.started_at.isoformat(),
        "finished_at": result.finished_at.isoformat(),
        "config": asdict(result.config),
        "guardrail_triggered": result.guardrail_triggered,
        "workload_error": result.workload_error,
        "interrupted": result.interrupted,
        "synthetic": False,
        **result.metadata,
    }
    (run_dir / "metadata.json").write_text(
        json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (run_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    _write_samples(run_dir / "samples.csv", result.samples)
    (run_dir / "report.txt").write_text(render_report(metadata, summary), encoding="utf-8")
    return run_dir


def _write_samples(path: Path, samples: list[Sample]) -> None:
    fields = [
        "sample_sequence",
        "phase",
        "scheduled_at",
        "sample_started_at",
        "sample_finished_at",
        "timestamp",
        "source",
        "device_id",
        "channel",
        "unit",
        "value",
        "quality",
        "error",
        "metadata",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for sample in samples:
            for measurement in sample.measurements:
                row = measurement.as_row()
                writer.writerow(
                    {
                        "sample_sequence": sample.sequence,
                        "phase": sample.phase,
                        "scheduled_at": sample.scheduled_at.isoformat(),
                        "sample_started_at": sample.started_at.isoformat(),
                        "sample_finished_at": sample.finished_at.isoformat(),
                        **row,
                    }
                )


def render_report(metadata: dict[str, Any], summary: dict[str, Any]) -> str:
    lines = [
        "Hardware Telemetry Characterizer",
        "=" * 34,
        f"Mode: {summary.get('mode', 'unknown')}",
        f"Created: {metadata.get('created_at', 'unknown')}",
        f"Samples: {summary.get('sample_frame_count', 0)}",
        f"Numeric observations: {summary.get('numeric_observation_count', 0)}",
        f"Guardrail: {summary.get('guardrail_triggered') or 'not triggered'}",
        f"Workload error: {summary.get('workload_error') or 'none reported'}",
        f"Interrupted: {summary.get('interrupted', False)}",
        "",
        "Timing",
        "------",
    ]
    timing = summary.get("timing", {})
    overall = timing.get("overall", {})
    lines.extend(
        [
            f"Expected interval: {timing.get('expected_interval_s')} s",
            f"Observed interval mean: {overall.get('mean_s')} s",
            f"Observed interval range: {overall.get('min_s')} .. {overall.get('max_s')} s",
            f"Late samples: {overall.get('late_samples', 0)}",
            "",
            "Channel statistics (GOOD numeric observations)",
            "-----------------------------------------------",
        ]
    )
    for row in summary.get("channels", []):
        lines.append(
            f"{row['phase']}/{row['device_id']}/{row['channel']} [{row['unit']}]: "
            f"n={row['sample_count']} min={row['min']:.4g} max={row['max']:.4g} "
            f"mean={row['mean']:.4g} stdev={row['standard_deviation']:.4g}"
        )
    lines.extend(
        [
            "",
            "Interpretation note: collector quality is evidence about acquisition;",
            "characterization guardrails are generic safety controls, not acceptance limits.",
            "",
        ]
    )
    return "\n".join(lines)


def report_run(run_dir: str | Path) -> str:
    """Render a report from an existing run directory."""

    path = Path(run_dir)
    metadata = json.loads((path / "metadata.json").read_text(encoding="utf-8"))
    summary = json.loads((path / "summary.json").read_text(encoding="utf-8"))
    report = render_report(metadata, summary)
    (path / "report.txt").write_text(report, encoding="utf-8")
    return report
