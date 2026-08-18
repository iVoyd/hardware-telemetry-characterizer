"""Normalized measurement types shared by collectors, experiments, and reports."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, TypeAlias


class Quality(StrEnum):
    """Acquisition quality, distinct from a DUT rule or characterization result."""

    GOOD = "GOOD"
    MISSING = "MISSING"
    STALE = "STALE"
    TIMEOUT = "TIMEOUT"
    PARSE_ERROR = "PARSE_ERROR"
    COMMAND_ERROR = "COMMAND_ERROR"
    UNAVAILABLE = "UNAVAILABLE"


MeasurementValue: TypeAlias = float | int | str | None


def utc_now() -> datetime:
    """Return an aware UTC timestamp."""

    return datetime.now(UTC)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


@dataclass(frozen=True, slots=True)
class Measurement:
    """One normalized channel observation."""

    timestamp: datetime
    source: str
    device_id: str
    channel: str
    unit: str
    value: MeasurementValue
    quality: Quality = Quality.GOOD
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "timestamp", _as_utc(self.timestamp))
        if self.quality == Quality.GOOD and self.value is None and self.error is None:
            object.__setattr__(self, "quality", Quality.MISSING)

    @property
    def is_numeric(self) -> bool:
        return isinstance(self.value, (int, float)) and not isinstance(self.value, bool)

    def as_row(self) -> dict[str, str | int | float | None]:
        """Return a CSV-friendly representation without losing quality information."""

        value: str | int | float | None = self.value
        return {
            "timestamp": self.timestamp.isoformat(),
            "source": self.source,
            "device_id": self.device_id,
            "channel": self.channel,
            "unit": self.unit,
            "value": value,
            "quality": self.quality.value,
            "error": self.error,
            "metadata": json.dumps(self.metadata, sort_keys=True, separators=(",", ":")),
        }
