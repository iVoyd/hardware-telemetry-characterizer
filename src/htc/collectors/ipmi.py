"""Read-only generic IPMI sensor collector."""

from __future__ import annotations

import re
from datetime import datetime

from ..adapters import (
    CommandRunner,
    CommandTimeout,
    CommandUnavailable,
    Filesystem,
    PathFilesystem,
    SubprocessRunner,
)
from ..measurement import Measurement, Quality, utc_now
from .base import collector_status

_NUMBER = re.compile(r"[-+]?\d+(?:\.\d+)?")
_LOCAL_IPMI_DEVICES = ("/dev/ipmi0", "/dev/ipmi/0", "/dev/ipmidev/0")


def _ipmi_unit(raw: str) -> str:
    value = raw.lower()
    if "degree" in value or value in {"c", "°c"}:
        return "°C"
    if "rpm" in value:
        return "rpm"
    if "volt" in value or value == "v":
        return "V"
    return raw or "raw"


class IPMICollector:
    """Parse the common pipe-delimited ``ipmitool sensor`` output format."""

    name = "ipmi"

    def __init__(
        self,
        runner: CommandRunner | None = None,
        timeout_s: float = 5.0,
        *,
        filesystem: Filesystem | None = None,
        command_prefix: tuple[str, ...] = (),
    ):
        self.runner = runner or SubprocessRunner()
        self.timeout_s = timeout_s
        self.filesystem = filesystem or PathFilesystem()
        self.command_prefix = tuple(command_prefix)

    def collect(self, timestamp: datetime | None = None) -> list[Measurement]:
        timestamp = timestamp or utc_now()
        try:
            result = self.runner.run(
                (*self.command_prefix, "ipmitool", "sensor"), timeout_s=self.timeout_s
            )
        except CommandUnavailable as exc:
            return [
                collector_status(
                    self.name,
                    timestamp,
                    Quality.UNAVAILABLE,
                    self._access_failure_reason(str(exc)),
                )
            ]
        except CommandTimeout as exc:
            return [collector_status(self.name, timestamp, Quality.TIMEOUT, str(exc))]
        if result.returncode != 0 and not result.stdout.strip():
            return [
                collector_status(
                    self.name,
                    timestamp,
                    Quality.UNAVAILABLE,
                    self._access_failure_reason(result.stderr),
                )
            ]

        measurements: list[Measurement] = []
        malformed = 0
        for line in result.stdout.splitlines():
            if not line.strip():
                continue
            parts = [part.strip() for part in line.split("|")]
            if len(parts) < 4:
                parts = [part.strip() for part in line.split(",")]
            if len(parts) < 4:
                malformed += 1
                continue
            sensor, raw_value, raw_unit, status = parts[:4]
            if not sensor:
                malformed += 1
                continue
            unit = _ipmi_unit(raw_unit)
            lowered = raw_value.lower()
            if lowered in {"na", "n/a", "no reading", "disabled", "not readable"}:
                quality = Quality.MISSING
                value: float | str | None = None
                error = "sensor did not provide a reading"
            else:
                match = _NUMBER.search(raw_value)
                if match:
                    value = float(match.group())
                    quality = Quality.GOOD
                    error = None
                    if value.is_integer():
                        value = int(value)
                else:
                    value = None
                    quality = Quality.PARSE_ERROR
                    error = f"unparseable sensor value: {raw_value}"
            measurements.append(
                Measurement(timestamp, self.name, "bmc", sensor, unit, value, quality, error)
            )
            measurements.append(
                Measurement(timestamp, self.name, "bmc", f"{sensor}.status", "status", status)
            )
        if not measurements:
            return [
                collector_status(
                    self.name,
                    timestamp,
                    Quality.PARSE_ERROR,
                    "no parseable IPMI sensor rows",
                )
            ]
        if malformed:
            measurements.append(
                collector_status(
                    self.name,
                    timestamp,
                    Quality.PARSE_ERROR,
                    f"ignored {malformed} malformed IPMI row(s)",
                    channel="parse_warnings",
                )
            )
        return measurements

    def _interface_present(self) -> bool:
        return any(self.filesystem.exists(path) for path in _LOCAL_IPMI_DEVICES)

    def _access_failure_reason(self, detail: str) -> str:
        if detail and "command not found" in detail.lower():
            return detail
        if self.command_prefix:
            return "privileged IPMI read unavailable"
        if self._interface_present():
            return "insufficient permission to access local IPMI interface"
        return "local IPMI interface is not present"
