"""Read-only SMART/NVMe collector using ``smartctl``."""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import PurePosixPath

from ..adapters import CommandRunner, CommandTimeout, CommandUnavailable, SubprocessRunner
from ..measurement import Measurement, Quality, utc_now
from .base import collector_status

_DEVICE = re.compile(r"^\s*(/dev/nvme\d+)\b")
_NUMERIC_PREFIX = re.compile(
    r"^\s*(?:(?P<hex>[+-]?0[xX][0-9a-fA-F]+)|"
    r"(?P<decimal>[+-]?(?:(?:\d{1,3}(?:,\d{3})+)|\d+)(?:\.\d+)?))"
)
_NUMERIC_SUFFIX = re.compile(r"^(?:%|[A-Za-z°][A-Za-z0-9° /_-]*)?$")
_FIELDS: tuple[tuple[str, str, str], ...] = (
    ("Critical Warning", "critical_warning", "count"),
    ("Temperature", "composite_temperature", "°C"),
    ("Available Spare", "available_spare", "%"),
    ("Percentage Used", "percentage_used", "%"),
    ("Power On Hours", "power_on_hours", "h"),
    ("Power Cycles", "power_cycles", "count"),
    ("Unsafe Shutdowns", "unsafe_shutdowns", "count"),
    ("Media and Data Integrity Errors", "media_data_integrity_errors", "count"),
    ("Error Information Log Entries", "error_log_entries", "count"),
)


def parse_smart_numeric(raw: str) -> int | float:
    """Parse one leading numeric SMART value without accepting malformed text."""

    match = _NUMERIC_PREFIX.match(raw)
    if match is None:
        raise ValueError(f"no leading numeric value: {raw!r}")
    suffix = raw[match.end() :].strip()
    if not _NUMERIC_SUFFIX.fullmatch(suffix):
        raise ValueError(f"unexpected SMART value suffix: {suffix!r}")
    token = match.group("hex") or match.group("decimal")
    if token is None:
        raise ValueError(f"no numeric token: {raw!r}")
    if token.lower().startswith(("0x", "+0x", "-0x")):
        return int(token, 0)
    value = float(token.replace(",", ""))
    return int(value) if value.is_integer() else value


class SmartCollector:
    """Discover and observe all generic NVMe controller paths without writes."""

    name = "smart"

    def __init__(self, runner: CommandRunner | None = None, timeout_s: float = 10.0):
        self.runner = runner or SubprocessRunner()
        self.timeout_s = timeout_s

    def collect(self, timestamp: datetime | None = None) -> list[Measurement]:
        timestamp = timestamp or utc_now()
        try:
            scan = self.runner.run(("smartctl", "--scan-open"), timeout_s=self.timeout_s)
        except CommandUnavailable as exc:
            return [collector_status(self.name, timestamp, Quality.UNAVAILABLE, str(exc))]
        except CommandTimeout as exc:
            return [collector_status(self.name, timestamp, Quality.TIMEOUT, str(exc))]
        devices = self._discover(scan.stdout)
        if not devices:
            quality = Quality.PARSE_ERROR if scan.stdout.strip() else Quality.UNAVAILABLE
            message = (
                "no NVMe controllers discovered"
                if quality == Quality.UNAVAILABLE
                else "malformed smartctl scan output"
            )
            return [collector_status(self.name, timestamp, quality, message, channel="nvme")]

        measurements: list[Measurement] = []
        for device in devices:
            measurements.extend(self._collect_device(device, timestamp))
        return measurements

    def _discover(self, output: str) -> list[str]:
        devices: list[str] = []
        for line in output.splitlines():
            match = _DEVICE.match(line)
            if match and match.group(1) not in devices:
                devices.append(match.group(1))
        return devices

    def _collect_device(self, device: str, timestamp: datetime) -> list[Measurement]:
        try:
            result = self.runner.run(
                ("smartctl", "-a", "-d", "nvme", device), timeout_s=self.timeout_s
            )
        except CommandUnavailable as exc:
            return [
                collector_status(
                    self.name, timestamp, Quality.UNAVAILABLE, str(exc), channel=device
                )
            ]
        except CommandTimeout as exc:
            return [
                collector_status(self.name, timestamp, Quality.TIMEOUT, str(exc), channel=device)
            ]
        device_id = PurePosixPath(device).name
        output = result.stdout
        measurements: list[Measurement] = []
        health_match = re.search(
            r"SMART overall-health self-assessment test result:\s*(.+)", output, re.IGNORECASE
        )
        if health_match:
            measurements.append(
                Measurement(
                    timestamp,
                    self.name,
                    device_id,
                    "overall_health",
                    "status",
                    health_match.group(1).strip(),
                )
            )
        recognized = bool(health_match)
        for label, channel, unit in _FIELDS:
            match = re.search(
                rf"^\s*{re.escape(label)}\s*:\s*(.+)$", output, re.MULTILINE | re.IGNORECASE
            )
            if not match:
                continue
            recognized = True
            try:
                value = parse_smart_numeric(match.group(1))
            except ValueError as exc:
                measurements.append(
                    Measurement(
                        timestamp,
                        self.name,
                        device_id,
                        channel,
                        unit,
                        None,
                        Quality.PARSE_ERROR,
                        str(exc),
                    )
                )
            else:
                measurements.append(
                    Measurement(timestamp, self.name, device_id, channel, unit, value)
                )
        for match in re.finditer(r"^\s*(Temperature Sensor \d+)\s*:\s*(.+)$", output, re.MULTILINE):
            channel = match.group(1).lower().replace(" ", "_")
            recognized = True
            try:
                value = parse_smart_numeric(match.group(2))
            except ValueError as exc:
                measurements.append(
                    Measurement(
                        timestamp,
                        self.name,
                        device_id,
                        channel,
                        "°C",
                        None,
                        Quality.PARSE_ERROR,
                        str(exc),
                    )
                )
            else:
                measurements.append(
                    Measurement(timestamp, self.name, device_id, channel, "°C", value)
                )

        if not measurements or not recognized:
            return [
                collector_status(
                    self.name,
                    timestamp,
                    Quality.COMMAND_ERROR if result.returncode else Quality.PARSE_ERROR,
                    result.stderr.strip() or "no recognized NVMe SMART fields",
                    channel=device,
                )
            ]
        return measurements
