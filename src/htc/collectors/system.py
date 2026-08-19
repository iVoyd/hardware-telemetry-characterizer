"""Read-only CPU and system telemetry from generic Linux interfaces."""

from __future__ import annotations

import os
from datetime import datetime

from ..adapters import Filesystem, PathFilesystem
from ..measurement import Measurement, Quality, utc_now


class SystemCollector:
    """Collect CPU utilization, load, memory availability, and frequency."""

    name = "system"

    def __init__(self, filesystem: Filesystem | None = None):
        self.filesystem = filesystem or PathFilesystem()
        self._previous_cpu: tuple[int, int] | None = None

    def collect(self, timestamp: datetime | None = None) -> list[Measurement]:
        timestamp = timestamp or utc_now()
        measurements: list[Measurement] = []
        measurements.extend(self._cpu_stat(timestamp))
        measurements.extend(self._loadavg(timestamp))
        measurements.extend(self._memory(timestamp))
        measurements.extend(self._frequency(timestamp))
        measurements.append(
            Measurement(
                timestamp, self.name, "system", "logical_cpus", "count", self._logical_cpus()
            )
        )
        return measurements

    def _cpu_stat(self, timestamp: datetime) -> list[Measurement]:
        try:
            line = next(
                line
                for line in self.filesystem.read_text("/proc/stat").splitlines()
                if line.startswith("cpu ")
            )
            fields = [int(value) for value in line.split()[1:]]
            total = sum(fields)
            idle = fields[3] + (fields[4] if len(fields) > 4 else 0)
        except (OSError, StopIteration, ValueError, IndexError) as exc:
            return [
                Measurement(
                    timestamp,
                    self.name,
                    "system",
                    "cpu_utilization",
                    "%",
                    None,
                    Quality.PARSE_ERROR
                    if isinstance(exc, (ValueError, IndexError, StopIteration))
                    else Quality.COMMAND_ERROR,
                    str(exc),
                )
            ]
        previous = self._previous_cpu
        self._previous_cpu = (total, idle)
        if previous is None or total == previous[0]:
            return [
                Measurement(
                    timestamp,
                    self.name,
                    "system",
                    "cpu_utilization",
                    "%",
                    None,
                    Quality.UNAVAILABLE,
                    "awaiting two /proc/stat samples",
                )
            ]
        total_delta = total - previous[0]
        idle_delta = idle - previous[1]
        utilization = max(0.0, min(100.0, 100.0 * (total_delta - idle_delta) / total_delta))
        return [Measurement(timestamp, self.name, "system", "cpu_utilization", "%", utilization)]

    def _loadavg(self, timestamp: datetime) -> list[Measurement]:
        try:
            values = self.filesystem.read_text("/proc/loadavg").split()[:3]
            channels = ("load_1m", "load_5m", "load_15m")
            return [
                Measurement(timestamp, self.name, "system", channel, "load", float(value))
                for channel, value in zip(channels, values, strict=False)
            ]
        except (OSError, ValueError) as exc:
            return [
                Measurement(
                    timestamp,
                    self.name,
                    "system",
                    "load_1m",
                    "load",
                    None,
                    Quality.COMMAND_ERROR if isinstance(exc, OSError) else Quality.PARSE_ERROR,
                    str(exc),
                )
            ]

    def _memory(self, timestamp: datetime) -> list[Measurement]:
        try:
            line = next(
                line
                for line in self.filesystem.read_text("/proc/meminfo").splitlines()
                if line.startswith("MemAvailable:")
            )
            kib = float(line.split()[1])
            return [
                Measurement(timestamp, self.name, "system", "memory_available", "MiB", kib / 1024)
            ]
        except (OSError, StopIteration, ValueError, IndexError) as exc:
            return [
                Measurement(
                    timestamp,
                    self.name,
                    "system",
                    "memory_available",
                    "MiB",
                    None,
                    Quality.COMMAND_ERROR if isinstance(exc, OSError) else Quality.PARSE_ERROR,
                    str(exc),
                )
            ]

    def _frequency(self, timestamp: datetime) -> list[Measurement]:
        paths = self.filesystem.glob("/sys/devices/system/cpu/cpu*/cpufreq/scaling_cur_freq")
        values: list[float] = []
        for path in paths:
            try:
                values.append(float(self.filesystem.read_text(path).strip()) / 1000)
            except (OSError, ValueError):
                continue
        if not values:
            return [
                Measurement(
                    timestamp,
                    self.name,
                    "system",
                    "frequency",
                    "MHz",
                    None,
                    Quality.UNAVAILABLE,
                    "cpufreq is not available",
                )
            ]
        return [
            Measurement(
                timestamp, self.name, "system", "frequency", "MHz", sum(values) / len(values)
            )
        ]

    def _logical_cpus(self) -> int:
        try:
            count = sum(
                1
                for line in self.filesystem.read_text("/proc/stat").splitlines()
                if line.startswith("cpu") and line[3:].lstrip().isdigit()
            )
        except OSError:
            count = 0
        return count or (os.cpu_count() or 1)
