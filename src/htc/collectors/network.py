"""Read-only Linux network interface telemetry."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from ..adapters import Filesystem, PathFilesystem
from ..measurement import Measurement, Quality, utc_now


class NetworkCollector:
    """Collect carrier, negotiated speed, and standard interface counters."""

    name = "network"
    _COUNTERS = {
        "rx_bytes": "bytes",
        "tx_bytes": "bytes",
        "rx_packets": "count",
        "tx_packets": "count",
        "rx_errors": "count",
        "tx_errors": "count",
        "rx_dropped": "count",
        "tx_dropped": "count",
    }

    def __init__(self, root: str | Path = "/sys/class/net", filesystem: Filesystem | None = None):
        self.root = Path(root)
        self.filesystem = filesystem or PathFilesystem()

    def collect(self, timestamp: datetime | None = None) -> list[Measurement]:
        timestamp = timestamp or utc_now()
        measurements: list[Measurement] = []
        for interface in self.filesystem.glob(self.root / "*"):
            name = interface.name
            if name == "lo":
                continue
            device_id = f"net:{name}"
            measurements.extend(
                self._read_value(
                    timestamp, device_id, "carrier", interface / "carrier", "bool", bool_mode=True
                )
            )
            measurements.extend(
                self._read_value(timestamp, device_id, "speed", interface / "speed", "Mb/s")
            )
            for counter, unit in self._COUNTERS.items():
                measurements.extend(
                    self._read_value(
                        timestamp,
                        device_id,
                        counter,
                        interface / "statistics" / counter,
                        unit,
                    )
                )
        if not measurements:
            measurements.append(
                Measurement(
                    timestamp,
                    self.name,
                    "network",
                    "interfaces",
                    "count",
                    0,
                    Quality.UNAVAILABLE,
                    "no non-loopback interfaces discovered",
                )
            )
        return measurements

    def _read_value(
        self,
        timestamp: datetime,
        device_id: str,
        channel: str,
        path: Path,
        unit: str,
        *,
        bool_mode: bool = False,
    ) -> list[Measurement]:
        try:
            raw = self.filesystem.read_text(path).strip()
            value: int | float = int(raw)
            if bool_mode:
                value = int(bool(value))
            elif channel == "speed" and value < 0:
                return [
                    Measurement(
                        timestamp,
                        self.name,
                        device_id,
                        channel,
                        unit,
                        None,
                        Quality.MISSING,
                        "negotiated speed is unavailable",
                    )
                ]
            return [Measurement(timestamp, self.name, device_id, channel, unit, value)]
        except OSError as exc:
            return [
                Measurement(
                    timestamp, self.name, device_id, channel, unit, None, Quality.MISSING, str(exc)
                )
            ]
        except ValueError as exc:
            return [
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
            ]
