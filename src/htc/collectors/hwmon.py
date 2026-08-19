"""Linux hwmon/sysfs collector with instance-preserving identities."""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from ..adapters import Filesystem, PathFilesystem
from ..measurement import Measurement, Quality, utc_now

_NVME_CONTROLLER = re.compile(r"nvme\d+")


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

    For NVMe hwmon entries, the resolved sysfs path is inspected for a generic
    controller component such as ``nvme0``. If resolution is unavailable, the
    hwmon instance remains part of a collision-safe fallback identity.
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
            device_id = self._device_id(driver_name, entry)
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

    def _device_id(self, driver_name: str, entry: Path) -> str:
        if driver_name.lower() == "nvme":
            try:
                resolved_parts = self.filesystem.resolve(entry).parts
            except (OSError, RuntimeError):
                resolved_parts = ()
            for component in reversed(resolved_parts):
                if _NVME_CONTROLLER.fullmatch(component):
                    return component
        return f"{driver_name}:{entry.name}"

    def _channel_for(self, entry: Path, prefix: str) -> tuple[str, tuple[str, float]]:
        unit, scale = _channel_unit(prefix)
        label_path = entry / f"{prefix}_label"
        try:
            label = self.filesystem.read_text(label_path).strip()
        except OSError:
            label = ""
        return label or prefix, (unit, scale)
