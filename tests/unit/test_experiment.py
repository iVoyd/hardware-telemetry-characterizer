from __future__ import annotations

import time
from collections.abc import Callable
from datetime import datetime, timedelta, timezone

import pytest

from htc.experiment import (
    CpuWorkload,
    ExperimentConfig,
    ExperimentEngine,
    ScheduledSampler,
    default_worker_count,
)
from htc.measurement import Measurement, Quality


class FakeClock:
    def __init__(self) -> None:
        self.value = 0.0
        self.wall_start = datetime(2025, 1, 1, tzinfo=timezone.utc)

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
        self.on_collect: Callable[[int], None] | None = None
        self.sample_index = 0

    def collect(self, timestamp: datetime | None = None) -> list[Measurement]:
        if self.on_collect:
            self.on_collect(self.sample_index)
        self.sample_index += 1
        return [
            Measurement(
                timestamp or datetime.now(timezone.utc),
                "hwmon",
                "cpu:synthetic",
                "temp",
                "°C",
                next(self.values),
            )
        ]


class UtilizationCollector:
    name = "synthetic-system"

    def __init__(
        self,
        values: list[float],
        *,
        source: str = "system",
        device_id: str = "system",
    ) -> None:
        self.values = iter(values)
        self.source = source
        self.device_id = device_id

    def collect(self, timestamp: datetime | None = None) -> list[Measurement]:
        return [
            Measurement(
                timestamp or datetime.now(timezone.utc),
                self.source,
                self.device_id,
                "cpu_utilization",
                "%",
                next(self.values),
            )
        ]


class FakeWorkload:
    def __init__(self, failed: bool = False) -> None:
        self.started = False
        self.stopped = False
        self.stop_count = 0
        self._failed = failed

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.stopped = True
        self.stop_count += 1

    @property
    def failed(self) -> bool:
        return self._failed and self.started

    @property
    def failure_reason(self) -> str | None:
        return "synthetic worker exited" if self.failed else None


class StopFailingWorkload(FakeWorkload):
    def __init__(self) -> None:
        super().__init__()
        self.stop_attempts = 0

    def stop(self) -> None:
        self.stop_attempts += 1
        raise RuntimeError("synthetic shutdown failure")


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
    collector = TemperatureCollector([40.0, 86.0, 87.0])
    recovery_observed_stopped: list[bool] = []
    collector.on_collect = lambda index: (
        recovery_observed_stopped.append(workload.stopped) if index == 2 else None
    )
    config = ExperimentConfig(
        mode="cpu",
        interval_s=1.0,
        baseline_s=0,
        stimulus_s=3.0,
        recovery_s=0,
        max_temperature_c=85.0,
    )
    result = ExperimentEngine(
        [collector],
        config,
        sampler=sampler(clock),
        workload_factory=lambda _workers: workload,
    ).run()
    assert result.guardrail_triggered is not None
    assert workload.started and workload.stopped
    assert workload.stop_count == 1
    assert [sample.phase for sample in result.samples] == ["baseline", "stimulus", "recovery"]
    assert sum(sample.phase == "stimulus" for sample in result.samples) == 1
    assert recovery_observed_stopped == [True]


def test_baseline_guard_prevents_workload_start_and_active_stimulus() -> None:
    clock = FakeClock()
    workload = FakeWorkload()
    factory_calls: list[int] = []
    config = ExperimentConfig(
        mode="cpu",
        interval_s=1.0,
        baseline_s=0,
        stimulus_s=2.0,
        recovery_s=0,
        max_temperature_c=85.0,
    )
    result = ExperimentEngine(
        [TemperatureCollector([86.0, 87.0])],
        config,
        sampler=sampler(clock),
        workload_factory=lambda workers: factory_calls.append(workers) or workload,
    ).run()
    assert result.guardrail_triggered is not None
    assert factory_calls == []
    assert workload.started is False
    assert "stimulus" not in [sample.phase for sample in result.samples]


def test_worker_failure_stops_before_first_recovery_sample() -> None:
    clock = FakeClock()
    workload = FakeWorkload(failed=True)
    collector = TemperatureCollector([40.0, 41.0, 42.0])
    recovery_observed_stopped: list[bool] = []
    collector.on_collect = lambda index: (
        recovery_observed_stopped.append(workload.stopped) if index == 2 else None
    )
    config = ExperimentConfig(
        mode="cpu", interval_s=1.0, baseline_s=0, stimulus_s=2.0, recovery_s=0
    )
    result = ExperimentEngine(
        [collector],
        config,
        sampler=sampler(clock),
        workload_factory=lambda _workers: workload,
    ).run()
    assert result.workload_error == "synthetic worker exited"
    assert recovery_observed_stopped == [True]
    assert workload.stop_count == 1


def test_normal_stimulus_completion_stops_before_first_recovery_sample() -> None:
    clock = FakeClock()
    workload = FakeWorkload()
    collector = TemperatureCollector([40.0] * 6)
    recovery_observed_stopped: list[bool] = []
    collector.on_collect = lambda index: (
        recovery_observed_stopped.append(workload.stopped) if index >= 3 else None
    )
    config = ExperimentConfig(
        mode="cpu",
        interval_s=1.0,
        baseline_s=0,
        stimulus_s=1.0,
        recovery_s=1.0,
        max_temperature_c=85.0,
    )
    result = ExperimentEngine(
        [collector],
        config,
        sampler=sampler(clock),
        workload_factory=lambda _workers: workload,
    ).run()
    phases = [sample.phase for sample in result.samples]
    assert workload.started
    assert workload.stopped
    assert workload.stop_count == 1
    assert recovery_observed_stopped[0] is True
    assert result.workload_error is None
    assert phases[:3] == ["baseline", "stimulus", "stimulus"]
    assert phases[3:] == ["recovery", "recovery"]


def test_workload_stop_failure_blocks_recovery_and_retries_cleanup() -> None:
    clock = FakeClock()
    workload = StopFailingWorkload()
    config = ExperimentConfig(
        mode="cpu", interval_s=1.0, baseline_s=0, stimulus_s=1.0, recovery_s=1.0
    )
    result = ExperimentEngine(
        [TemperatureCollector([40.0] * 4)],
        config,
        sampler=sampler(clock),
        workload_factory=lambda _workers: workload,
    ).run()
    assert workload.started
    assert workload.stop_attempts == 2
    assert result.workload_error == "workload stop failed: synthetic shutdown failure"
    assert [sample.phase for sample in result.samples] == ["baseline", "stimulus", "stimulus"]
    assert workload.stopped is False


def test_phase_boundary_metadata_preserves_interval_value_and_quality() -> None:
    clock = FakeClock()
    workload = FakeWorkload()
    result = ExperimentEngine(
        [UtilizationCollector([1.0, 25.0, 26.0, 26.0, 1.0])],
        ExperimentConfig(mode="cpu", interval_s=1.0, baseline_s=0, stimulus_s=1.0, recovery_s=1.0),
        sampler=sampler(clock),
        workload_factory=lambda _workers: workload,
    ).run()
    stimulus_boundary = next(
        measurement
        for sample in result.samples
        if sample.phase == "stimulus"
        for measurement in sample.measurements
        if measurement.channel == "cpu_utilization" and measurement.value == 25.0
    )
    recovery_boundary = next(
        measurement
        for sample in result.samples
        if sample.phase == "recovery"
        for measurement in sample.measurements
        if measurement.channel == "cpu_utilization" and measurement.value == 26.0
    )
    assert stimulus_boundary.quality == Quality.GOOD
    assert stimulus_boundary.metadata == {
        "phase_boundary_interval": True,
        "previous_phase": "baseline",
        "current_phase": "stimulus",
    }
    assert recovery_boundary.quality == Quality.GOOD
    assert recovery_boundary.metadata == {
        "phase_boundary_interval": True,
        "previous_phase": "stimulus",
        "current_phase": "recovery",
    }


def test_baseline_to_recovery_boundary_is_tagged_when_workload_never_starts() -> None:
    class StartFailingWorkload(FakeWorkload):
        def start(self) -> None:
            raise RuntimeError("synthetic workload start failure")

    clock = FakeClock()
    result = ExperimentEngine(
        [UtilizationCollector([1.0, 0.5])],
        ExperimentConfig(mode="cpu", interval_s=1.0, baseline_s=0, recovery_s=0),
        sampler=sampler(clock),
        workload_factory=lambda _workers: StartFailingWorkload(),
    ).run()
    recovery_measurement = next(
        measurement
        for sample in result.samples
        if sample.phase == "recovery"
        for measurement in sample.measurements
    )
    assert recovery_measurement.value == 0.5
    assert recovery_measurement.metadata["phase_boundary_interval"] is True
    assert recovery_measurement.metadata["previous_phase"] == "baseline"
    assert result.workload_error == "synthetic workload start failure"


def test_passive_mode_does_not_add_phase_boundary_metadata() -> None:
    clock = FakeClock()
    result = ExperimentEngine(
        [UtilizationCollector([1.0, 2.0])],
        ExperimentConfig(mode="passive", interval_s=1.0, duration_s=1.0),
        sampler=sampler(clock),
    ).run()
    assert all(
        "phase_boundary_interval" not in measurement.metadata
        for sample in result.samples
        for measurement in sample.measurements
    )


def test_unrelated_cpu_utilization_channel_is_not_tagged() -> None:
    clock = FakeClock()
    result = ExperimentEngine(
        [UtilizationCollector([1.0, 25.0, 26.0, 1.0], source="synthetic", device_id="device")],
        ExperimentConfig(mode="cpu", interval_s=1.0, baseline_s=0, stimulus_s=1.0, recovery_s=1.0),
        sampler=sampler(clock),
        workload_factory=FakeWorkload,
    ).run()
    assert all(
        "phase_boundary_interval" not in measurement.metadata
        for sample in result.samples
        for measurement in sample.measurements
    )


class StimulusRaisingSampler(ScheduledSampler):
    def __init__(self, clock: FakeClock, exception: BaseException):
        super().__init__(1.0, monotonic=clock.monotonic, sleeper=clock.sleep, wall_clock=clock.wall)
        self.exception = exception

    def collect_phase(
        self,
        phase: str,
        duration_s: float,
        collect: Callable[[datetime], list[Measurement]],
        *,
        sequence_start: int = 0,
        stop_requested: Callable[[], bool] | None = None,
    ) -> list:
        if phase == "stimulus":
            raise self.exception
        return super().collect_phase(
            phase,
            duration_s,
            collect,
            sequence_start=sequence_start,
            stop_requested=stop_requested,
        )


def test_interrupt_path_stops_workload() -> None:
    clock = FakeClock()
    workload = FakeWorkload()
    config = ExperimentConfig(mode="cpu", interval_s=1.0, baseline_s=0, stimulus_s=1, recovery_s=0)
    result = ExperimentEngine(
        [TemperatureCollector([40.0])],
        config,
        sampler=StimulusRaisingSampler(clock, KeyboardInterrupt()),
        workload_factory=lambda _workers: workload,
    ).run()
    assert result.interrupted is True
    assert workload.started and workload.stopped
    assert workload.stop_count == 1


def test_exception_path_stops_workload() -> None:
    clock = FakeClock()
    workload = FakeWorkload()
    config = ExperimentConfig(mode="cpu", interval_s=1.0, baseline_s=0, stimulus_s=1, recovery_s=0)
    with pytest.raises(RuntimeError, match="synthetic sampler failure"):
        ExperimentEngine(
            [TemperatureCollector([40.0])],
            config,
            sampler=StimulusRaisingSampler(clock, RuntimeError("synthetic sampler failure")),
            workload_factory=lambda _workers: workload,
        ).run()
    assert workload.started and workload.stopped
    assert workload.stop_count == 1


def test_passive_high_temperature_is_not_an_active_guard_event() -> None:
    clock = FakeClock()
    config = ExperimentConfig(mode="passive", interval_s=1.0, duration_s=0, max_temperature_c=85.0)
    result = ExperimentEngine([TemperatureCollector([99.0])], config, sampler=sampler(clock)).run()
    assert result.guardrail_triggered is None
    assert result.metadata["active_stimulus"] is False


def test_privileged_read_setting_is_recorded_without_changing_experiment_mode() -> None:
    clock = FakeClock()
    config = ExperimentConfig(mode="passive", interval_s=1.0, duration_s=0, privileged_read=True)
    result = ExperimentEngine([TemperatureCollector([40.0])], config, sampler=sampler(clock)).run()
    assert result.metadata["privileged_read"] is True
    assert result.metadata["active_stimulus"] is False


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


def test_cpu_workload_watchdog_stops_remaining_workers_after_failure() -> None:
    workload = CpuWorkload(2)
    workload.start()
    try:
        failed_worker, remaining_worker = workload.processes
        failed_worker.terminate()
        deadline = time.monotonic() + 2.0
        while not workload.failed and time.monotonic() < deadline:
            time.sleep(0.02)
        assert workload.failed
        assert workload.failure_reason is not None
        assert remaining_worker.poll() is not None
    finally:
        workload.stop()
