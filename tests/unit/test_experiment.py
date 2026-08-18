from __future__ import annotations

from datetime import UTC, datetime, timedelta

from htc.experiment import (
    ExperimentConfig,
    ExperimentEngine,
    ScheduledSampler,
    default_worker_count,
)
from htc.measurement import Measurement


class FakeClock:
    def __init__(self) -> None:
        self.value = 0.0
        self.wall_start = datetime(2025, 1, 1, tzinfo=UTC)

    def monotonic(self) -> float:
        return self.value

    def sleep(self, duration: float) -> None:
        self.value += duration

    def wall(self) -> datetime:
        return self.wall_start + timedelta(seconds=self.value)


class TemperatureCollector:
    name = "synthetic"

    def __init__(self, values: list[float]) -> None:
        self.values = iter(values)

    def collect(self, timestamp: datetime | None = None) -> list[Measurement]:
        return [
            Measurement(
                timestamp or datetime.now(UTC),
                "hwmon",
                "cpu:synthetic",
                "temp",
                "°C",
                next(self.values),
            )
        ]


class FakeWorkload:
    def __init__(self, failed: bool = False) -> None:
        self.started = False
        self.stopped = False
        self._failed = failed

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.stopped = True

    @property
    def failed(self) -> bool:
        return self._failed and self.started

    @property
    def failure_reason(self) -> str | None:
        return "synthetic worker exited" if self.failed else None


def sampler(clock: FakeClock) -> ScheduledSampler:
    return ScheduledSampler(
        1.0, monotonic=clock.monotonic, sleeper=clock.sleep, wall_clock=clock.wall
    )


def test_scheduled_sampler_maintains_absolute_cadence() -> None:
    clock = FakeClock()
    samples = sampler(clock).collect_phase(
        "passive", 2.0, lambda timestamp: [], stop_requested=None
    )
    assert [sample.started_at for sample in samples] == [
        clock.wall_start,
        clock.wall_start + timedelta(seconds=1),
        clock.wall_start + timedelta(seconds=2),
    ]


def test_thermal_guard_stops_stimulus_and_always_stops_workload() -> None:
    clock = FakeClock()
    workload = FakeWorkload()
    config = ExperimentConfig(
        mode="cpu",
        interval_s=1.0,
        baseline_s=0,
        stimulus_s=3.0,
        recovery_s=0,
        max_temperature_c=85.0,
    )
    result = ExperimentEngine(
        [TemperatureCollector([40.0, 86.0, 87.0])],
        config,
        sampler=sampler(clock),
        workload_factory=lambda _workers: workload,
    ).run()
    assert result.guardrail_triggered is not None
    assert workload.started and workload.stopped
    assert [sample.phase for sample in result.samples] == ["baseline", "stimulus", "recovery"]
    assert sum(sample.phase == "stimulus" for sample in result.samples) == 1


def test_workload_failure_is_reported_without_losing_collected_data() -> None:
    clock = FakeClock()
    workload = FakeWorkload(failed=True)
    config = ExperimentConfig(
        mode="cpu", interval_s=1.0, baseline_s=0, stimulus_s=2.0, recovery_s=0
    )
    result = ExperimentEngine(
        [TemperatureCollector([40.0, 41.0])],
        config,
        sampler=sampler(clock),
        workload_factory=lambda _workers: workload,
    ).run()
    assert result.workload_error == "synthetic worker exited"
    assert workload.stopped


def test_default_workers_are_bounded() -> None:
    assert default_worker_count(1) == 1
    assert default_worker_count(8) == 2
    assert default_worker_count(64) == 16
