"""Collector protocol and common quality helpers."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from ..measurement import Measurement, Quality


class Collector(Protocol):
    name: str

    def collect(self, timestamp: datetime | None = None) -> list[Measurement]:
        """Collect normalized observations at a single acquisition time."""


def collector_status(
    source: str,
    timestamp: datetime,
    quality: Quality,
    error: str,
    *,
    channel: str = "collector",
) -> Measurement:
    """Represent collector/tool failure explicitly instead of dropping it."""

    return Measurement(
        timestamp=timestamp,
        source=source,
        device_id="collector",
        channel=channel,
        unit="status",
        value=None,
        quality=quality,
        error=error,
    )
