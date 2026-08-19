"""Deterministic sampling and bounded characterization experiments."""

from __future__ import annotations

import math
import os
import signal
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Protocol

from .collectors.base import Collector, collector_status
from .measurement import Measurement, Quality, utc_now


class ExperimentInterrupted(KeyboardInterrupt):
    """Raised by CLI signal handlers so experiment cleanup can run."""


@dataclass(frozen=True, slots=True)
class ExperimentConfig:
    mode: str = "passive"
    interval_s: float = 2.0
    duration_s: float = 10.0
    baseline_s: float = 6.0
    stimulus_s: float = 10.0
    recovery_s: float = 6.0
    workers: int = 1
    max_temperature_c: float | None = 85.0
    privileged_read: bool = False

    def __post_init__(self) -> None:
        if self.mode not in {"passive", "cpu"}:
            raise ValueError("mode must be passive or cpu")
        if self.interval_s <= 0:
            raise ValueError("interval_s must be positive")
        for name in ("duration_s", "baseline_s", "stimulus_s", "recovery_s"):
            if getattr(self, name) < 0:
                raise ValueError(f"{name} cannot be negative")
        if self.mode == "cpu" and self.workers < 1:
            raise ValueError("workers must be positive")


@dataclass(slots=True)
class Sample:
    phase: str
    sequence: int
    scheduled_at: datetime
    started_at: datetime
    finished_at: datetime
    measurements: list[Measurement]


@dataclass(slots=True)
class ExperimentResult:
    config: ExperimentConfig
    started_at: datetime
    finished_at: datetime
    samples: list[Sample]
    guardrail_triggered: str | None = None
    workload_error: str | None = None
    interrupted: bool = False
    metadata: dict[str, str | int | float | bool | None] = field(default_factory=dict)


class WorkloadHandle(Protocol):
    def start(self) -> None:
        """Start bounded workload processes."""

    def stop(self) -> None:
        """Stop every process and release resources."""

    @property
    def failed(self) -> bool:
        """Whether a workload process exited unexpectedly."""

    @property
    def failure_reason(self) -> str | None:
        """Human-readable failure detail."""


class CpuWorkload:
    """Small CPU-only worker group with deterministic termination."""

    _WORKER_CODE = (
        "import time\nx = 0\nwhile True:\n    x = (x * 1664525 + 1013904223) & 0xffffffff\n"
    )

    def __init__(self, workers: int, python_executable: str = sys.executable):
        self.workers = workers
        self.python_executable = python_executable
        self.processes: list[subprocess.Popen[str]] = []
        self._failure_reason: str | None = None
        self._monitor_stop = threading.Event()
        self._monitor_thread: threading.Thread | None = None
        self._termination_lock = threading.Lock()

    def start(self) -> None:
        self._monitor_stop.clear()
        try:
            for _ in range(self.workers):
                self.processes.append(
                    subprocess.Popen(
                        [self.python_executable, "-c", self._WORKER_CODE],
                        stdin=subprocess.DEVNULL,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        text=True,
                        start_new_session=True,
                    )
                )
            self._monitor_thread = threading.Thread(
                target=self._monitor_workers,
                name="htc-cpu-workload-monitor",
                daemon=True,
            )
            self._monitor_thread.start()
        except OSError as exc:
            self._failure_reason = str(exc)
            self.stop()
            raise RuntimeError(f"could not start CPU workload: {exc}") from exc

    @property
    def failed(self) -> bool:
        if self._failure_reason is not None:
            return True
        for process in self.processes:
            code = process.poll()
            if code is not None and code != 0:
                try:
                    self._terminate_processes()
                except RuntimeError as exc:
                    self._failure_reason = f"workload cleanup failed: {exc}"
                else:
                    self._failure_reason = f"worker exited with status {code}"
                return True
        return False

    @property
    def failure_reason(self) -> str | None:
        return self._failure_reason

    def stop(self) -> None:
        self._monitor_stop.set()
        monitor = self._monitor_thread
        if monitor is not None and monitor is not threading.current_thread():
            monitor.join()
        self._terminate_processes()
        self.processes.clear()
        self._monitor_thread = None

    def _monitor_workers(self) -> None:
        while not self._monitor_stop.wait(0.05):
            for process in self.processes:
                code = process.poll()
                if code is not None and code != 0:
                    try:
                        self._terminate_processes()
                    except RuntimeError as exc:
                        self._failure_reason = f"workload cleanup failed: {exc}"
                    else:
                        self._failure_reason = f"worker exited with status {code}"
                    return

    def _terminate_processes(self) -> None:
        with self._termination_lock:
            processes = tuple(self.processes)
            for process in processes:
                try:
                    if process.poll() is None:
                        process.terminate()
                except OSError:
                    continue
            for process in processes:
                try:
                    if process.poll() is None:
                        process.wait(timeout=1.0)
                except subprocess.TimeoutExpired:
                    try:
                        process.kill()
                        process.wait(timeout=1.0)
                    except (OSError, subprocess.TimeoutExpired):
                        continue
            remaining = tuple(process for process in processes if process.poll() is None)
            if remaining:
                raise RuntimeError(f"{len(remaining)} workload process(es) did not terminate")


class ScheduledSampler:
    """Aim for absolute scheduled times, accounting for collection duration."""

    def __init__(
        self,
        interval_s: float,
        *,
        monotonic: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] = time.sleep,
        wall_clock: Callable[[], datetime] = utc_now,
    ):
        self.interval_s = interval_s
        self.monotonic = monotonic
        self.sleeper = sleeper
        self.wall_clock = wall_clock

    def collect_phase(
        self,
        phase: str,
        duration_s: float,
        collect: Callable[[datetime], list[Measurement]],
        *,
        sequence_start: int = 0,
        stop_requested: Callable[[], bool] | None = None,
    ) -> list[Sample]:
        started_mono = self.monotonic()
        started_wall = self.wall_clock()
        deadline = started_mono + duration_s
        next_due = started_mono
        sequence = sequence_start
        samples: list[Sample] = []
        while next_due <= deadline or not samples:
            remaining = next_due - self.monotonic()
            if remaining > 0:
                self.sleeper(remaining)
            scheduled_at = started_wall + timedelta(seconds=next_due - started_mono)
            sample_started = self.wall_clock()
            measurements = collect(sample_started)
            sample_finished = self.wall_clock()
            samples.append(
                Sample(
                    phase=phase,
                    sequence=sequence,
                    scheduled_at=scheduled_at,
                    started_at=sample_started,
                    finished_at=sample_finished,
                    measurements=measurements,
                )
            )
            sequence += 1
            if stop_requested and stop_requested():
                break
            next_due += self.interval_s
        return samples


class ExperimentEngine:
    """Coordinate collectors, phases, thermal guardrails, and cleanup."""

    def __init__(
        self,
        collectors: Iterable[Collector],
        config: ExperimentConfig,
        *,
        sampler: ScheduledSampler | None = None,
        workload_factory: Callable[[int], WorkloadHandle] | None = None,
    ):
        self.collectors = tuple(collectors)
        self.config = config
        self.sampler = sampler or ScheduledSampler(config.interval_s)
        self.workload_factory = workload_factory or (lambda workers: CpuWorkload(workers))
        self._guardrail_triggered: str | None = None
        self._workload_error: str | None = None

    def run(self) -> ExperimentResult:
        started_at = utc_now()
        samples: list[Sample] = []
        workload: WorkloadHandle | None = None
        interrupted = False
        try:
            if self.config.mode == "passive":
                samples.extend(self._phase("passive", self.config.duration_s, len(samples)))
            else:
                samples.extend(self._phase("baseline", self.config.baseline_s, len(samples)))
                if self._guardrail_triggered is None:
                    try:
                        workload = self.workload_factory(self.config.workers)
                        workload.start()
                    except Exception as exc:  # Operational failure becomes evidence, not a crash.
                        self._workload_error = str(exc)
                        if workload is not None:
                            workload.stop()
                            workload = None
                if workload and not self._workload_error:
                    samples.extend(
                        self._phase(
                            "stimulus",
                            self.config.stimulus_s,
                            len(samples),
                            stop_requested=lambda: self._workload_stopped(workload),
                        )
                    )
                samples.extend(self._phase("recovery", self.config.recovery_s, len(samples)))
        except (KeyboardInterrupt, ExperimentInterrupted):
            interrupted = True
        finally:
            if workload is not None:
                workload_failed = workload.failed
                workload_reason = workload.failure_reason
                workload.stop()
                if workload_failed and not self._workload_error:
                    self._workload_error = workload_reason or "workload process failed"
        return ExperimentResult(
            config=self.config,
            started_at=started_at,
            finished_at=utc_now(),
            samples=samples,
            guardrail_triggered=self._guardrail_triggered,
            workload_error=self._workload_error,
            interrupted=interrupted,
            metadata={
                "read_only_collectors": True,
                "privileged_read": self.config.privileged_read,
                "active_stimulus": self.config.mode == "cpu",
                "guardrail_is_not_acceptance_limit": True,
            },
        )

    def _phase(
        self,
        name: str,
        duration_s: float,
        sequence_start: int,
        *,
        stop_requested: Callable[[], bool] | None = None,
    ) -> list[Sample]:
        return self.sampler.collect_phase(
            name,
            duration_s,
            self._collect,
            sequence_start=sequence_start,
            stop_requested=stop_requested or self._guardrail_stop,
        )

    def _collect(self, timestamp: datetime) -> list[Measurement]:
        measurements: list[Measurement] = []
        for collector in self.collectors:
            try:
                measurements.extend(collector.collect(timestamp))
            except Exception as exc:  # Collector isolation is part of the fault model.
                measurements.append(
                    collector_status(
                        getattr(collector, "name", collector.__class__.__name__),
                        timestamp,
                        Quality.COMMAND_ERROR,
                        f"collector exception: {exc}",
                    )
                )
        if self.config.mode == "cpu":
            guardrail_reason = self._thermal_guard_reason(measurements)
            if guardrail_reason and self._guardrail_triggered is None:
                self._guardrail_triggered = guardrail_reason
        return measurements

    def _guardrail_stop(self) -> bool:
        return self._guardrail_triggered is not None

    def _workload_stopped(self, workload: WorkloadHandle) -> bool:
        if workload.failed:
            self._workload_error = workload.failure_reason or "workload process failed"
            workload.stop()
            return True
        if self._guardrail_stop():
            workload.stop()
            return True
        return False

    def _thermal_guard_reason(self, measurements: Iterable[Measurement]) -> str | None:
        limit = self.config.max_temperature_c
        if limit is None:
            return None
        for measurement in measurements:
            if (
                measurement.quality == Quality.GOOD
                and measurement.unit == "°C"
                and measurement.is_numeric
            ):
                if float(measurement.value) >= limit:
                    return (
                        f"thermal guard triggered: {measurement.device_id}/{measurement.channel} "
                        f">= {limit:g} °C"
                    )
        return None


def default_worker_count(logical_cpus: int | None = None) -> int:
    """Choose a modest default of roughly one quarter of logical CPUs."""

    count = logical_cpus or os.cpu_count() or 1
    return max(1, min(count, math.ceil(count * 0.25)))


def install_signal_handlers() -> Callable[[], None]:
    """Install interrupt handlers that allow engine ``finally`` blocks to run."""

    previous = {signum: signal.getsignal(signum) for signum in (signal.SIGINT, signal.SIGTERM)}

    def handler(signum: int, _frame: object) -> None:
        raise ExperimentInterrupted(f"received signal {signum}")

    signal.signal(signal.SIGINT, handler)
    signal.signal(signal.SIGTERM, handler)

    def restore() -> None:
        for signum, old_handler in previous.items():
            signal.signal(signum, old_handler)

    return restore
