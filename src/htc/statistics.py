"""Small deterministic statistical summaries for characterization evidence."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Iterator
from statistics import fmean, pstdev

from .experiment import ExperimentResult, Sample
from .measurement import Measurement, Quality


def _is_phase_boundary_interval(measurement: Measurement) -> bool:
    return measurement.metadata.get("phase_boundary_interval") is True


def _numeric_measurements(
    samples: Iterable[Sample], *, include_boundaries: bool
) -> Iterator[tuple[Sample, Measurement]]:
    for sample in samples:
        for measurement in sample.measurements:
            if (
                measurement.quality == Quality.GOOD
                and measurement.is_numeric
                and (include_boundaries or not _is_phase_boundary_interval(measurement))
            ):
                yield sample, measurement


def _numeric_by_channel(
    samples: Iterable[Sample],
) -> dict[tuple[str, str, str, str, str], list[float]]:
    grouped: dict[tuple[str, str, str, str, str], list[float]] = defaultdict(list)
    for sample, measurement in _numeric_measurements(samples, include_boundaries=False):
        key = (
            sample.phase,
            measurement.source,
            measurement.device_id,
            measurement.channel,
            measurement.unit,
        )
        grouped[key].append(float(measurement.value))
    return grouped


def channel_statistics(samples: Iterable[Sample]) -> list[dict[str, object]]:
    """Summarize only GOOD numeric observations, retaining quality in raw CSV."""

    rows: list[dict[str, object]] = []
    for key, values in sorted(_numeric_by_channel(samples).items()):
        phase, source, device_id, channel, unit = key
        rows.append(
            {
                "phase": phase,
                "source": source,
                "device_id": device_id,
                "channel": channel,
                "unit": unit,
                "sample_count": len(values),
                "min": min(values),
                "max": max(values),
                "mean": fmean(values),
                "standard_deviation": pstdev(values) if len(values) > 1 else 0.0,
            }
        )
    return rows


def timing_statistics(samples: Iterable[Sample], expected_interval_s: float) -> dict[str, object]:
    """Report actual cadence and late samples from scheduled wall-clock starts."""

    grouped: dict[str, list[Sample]] = defaultdict(list)
    for sample in samples:
        grouped[sample.phase].append(sample)
    phases: dict[str, dict[str, object]] = {}
    all_intervals: list[float] = []
    for phase, phase_samples in sorted(grouped.items()):
        intervals = [
            (current.started_at - previous.started_at).total_seconds()
            for previous, current in zip(phase_samples, phase_samples[1:], strict=False)
        ]
        all_intervals.extend(intervals)
        phases[phase] = _interval_row(intervals, expected_interval_s)
    return {
        "expected_interval_s": expected_interval_s,
        "phases": phases,
        "overall": _interval_row(all_intervals, expected_interval_s),
    }


def _interval_row(intervals: list[float], expected_interval_s: float) -> dict[str, object]:
    if not intervals:
        return {
            "sample_count": 0,
            "min_s": None,
            "max_s": None,
            "mean_s": None,
            "standard_deviation_s": None,
            "late_samples": 0,
        }
    return {
        "sample_count": len(intervals) + 1,
        "min_s": min(intervals),
        "max_s": max(intervals),
        "mean_s": fmean(intervals),
        "standard_deviation_s": pstdev(intervals) if len(intervals) > 1 else 0.0,
        "late_samples": sum(interval > expected_interval_s * 1.25 for interval in intervals),
    }


def derived_metrics(samples: Iterable[Sample]) -> list[dict[str, object]]:
    """Calculate modest baseline/stimulus/recovery deltas for matching channels."""

    grouped = _numeric_by_channel(samples)
    by_channel: dict[tuple[str, str, str, str], dict[str, list[float]]] = defaultdict(dict)
    for (phase, source, device_id, channel, unit), values in grouped.items():
        by_channel[(source, device_id, channel, unit)][phase] = values
    rows: list[dict[str, object]] = []
    for (source, device_id, channel, unit), phases in sorted(by_channel.items()):
        baseline = phases.get("baseline")
        stimulus = phases.get("stimulus")
        recovery = phases.get("recovery")
        if not baseline:
            continue
        baseline_mean = fmean(baseline)
        row: dict[str, object] = {
            "source": source,
            "device_id": device_id,
            "channel": channel,
            "unit": unit,
            "baseline_mean": baseline_mean,
        }
        if stimulus:
            row["stimulus_mean_minus_baseline"] = fmean(stimulus) - baseline_mean
            row["stimulus_max_minus_baseline"] = max(stimulus) - baseline_mean
        if recovery:
            row["recovery_mean_minus_baseline"] = fmean(recovery) - baseline_mean
            row["recovery_final_minus_baseline"] = recovery[-1] - baseline_mean
        rows.append(row)
    return rows


def summarize(result: ExperimentResult) -> dict[str, object]:
    channels = channel_statistics(result.samples)
    numeric_observation_count = sum(
        1
        for _sample, _measurement in _numeric_measurements(result.samples, include_boundaries=True)
    )
    phase_boundary_interval_count = sum(
        1
        for sample in result.samples
        for measurement in sample.measurements
        if _is_phase_boundary_interval(measurement)
    )
    return {
        "mode": result.config.mode,
        "guardrail_triggered": result.guardrail_triggered,
        "workload_error": result.workload_error,
        "interrupted": result.interrupted,
        "sample_frame_count": len(result.samples),
        "numeric_observation_count": numeric_observation_count,
        "phase_statistic_observation_count": sum(row["sample_count"] for row in channels),
        "phase_boundary_interval_count": phase_boundary_interval_count,
        "timing": timing_statistics(result.samples, result.config.interval_s),
        "channels": channels,
        "derived": derived_metrics(result.samples),
    }
