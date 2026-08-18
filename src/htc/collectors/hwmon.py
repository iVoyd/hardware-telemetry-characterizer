"""Linux hwmon/sysfs collector with instance-preserving identities."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from ..adapters import Filesystem, PathFilesystem
from ..measurement import Measurement, Quality, utc_now


def _channel_unit(prefix: str) -> tuple[str, float]:
    """Map common hwmon raw units to engineering units and scale."""

    if prefix.startswith("temp"):
        return "°C", 0.001
    if prefix.startswith("fan"):
        return "rpm", 1.0
    if prefix.startswith("in"):
        return "V", 0.001
    if prefix.startswith("power"):
        return "W", 0.000001
    if prefix.startswith("curr"):
        return "A", 0.001
    if prefix.startswith("energy"):
        return "J", 0.000001
    if prefix.startswith("humidity"):
        return "%", 0.001
    if prefix.startswith("freq"):
        return "Hz", 1.0
    return "raw", 1.0


class HWMONCollector:
    """Collect generic ``*_input`` channels from Linux hwmon instances.

    The sysfs directory name is part of the identity. This intentionally keeps
    ``nvme:hwmon0`` and ``nvme:hwmon1`` independent even when both ``name``
    files contain the generic driver name ``nvme``.
    """

    name = "hwmon"

    def __init__(self, root: str | Path = "/sys/class/hwmon", filesystem: Filesystem | None = None):
        self.root = Path(root)
        self.filesystem = filesystem or PathFilesystem()
        self._known: dict[tuple[str, str], str] = {}

    def collect(self, timestamp: datetime | None = None) -> list[Measurement]:
        timestamp = timestamp or utc_now()
        measurements: list[Measurement] = []
        seen: set[tuple[str, str]] = set()
        entries = self.filesystem.glob(self.root / "hwmon*")
        for entry in entries:
            instance = entry.name
            try:
                driver_name = self.filesystem.read_text(entry / "name").strip() or instance
            except OSError as exc:
                measurements.append(
                    Measurement(
                        timestamp,
                        self.name,
                        instance,
                        "name",
                        "status",
                        None,
                        Quality.COMMAND_ERROR,
                        str(exc),
                    )
                )
                continue
            device_id = f"{driver_name}:{instance}"
            for input_path in self.filesystem.glob(entry / "*_input"):
                prefix = input_path.name.removesuffix("_input")
                channel, unit_scale = self._channel_for(entry, prefix)
                unit, scale = unit_scale
                key = (device_id, channel)
                seen.add(key)
                self._known[key] = unit
                try:
                    raw = self.filesystem.read_text(input_path).strip()
                    value = float(raw) * scale
                except (OSError, ValueError) as exc:
                    quality = (
                        Quality.COMMAND_ERROR if isinstance(exc, OSError) else Quality.PARSE_ERROR
                    )
                    measurements.append(
                        Measurement(
                            timestamp,
                            self.name,
                            device_id,
                            channel,
                            unit,
                            None,
                            quality,
                            str(exc),
                        )
                    )
                else:
                    measurements.append(
                        Measurement(timestamp, self.name, device_id, channel, unit, value)
                    )

        for (device_id, channel), unit in sorted(self._known.items()):
            if (device_id, channel) not in seen:
                measurements.append(
                    Measurement(
                        timestamp,
                        self.name,
                        device_id,
                        channel,
                        unit,
                        None,
                        Quality.MISSING,
                        "channel was not present during this sample",
                    )
                )
        return measurements

    def _channel_for(self, entry: Path, prefix: str) -> tuple[str, tuple[str, float]]:
        unit, scale = _channel_unit(prefix)
        label_path = entry / f"{prefix}_label"
        try:
            label = self.filesystem.read_text(label_path).strip()
        except OSError:
            label = ""
        return label or prefix, (unit, scale)
