from __future__ import annotations

from datetime import datetime, timezone

from htc.measurement import Measurement, Quality, utc_now


def test_utc_now_is_timezone_aware_and_serializes_as_utc() -> None:
    timestamp = utc_now()
    measurement = Measurement(
        timestamp,
        "synthetic",
        "device",
        "channel",
        "count",
        1,
    )

    assert timestamp.tzinfo is timezone.utc
    assert measurement.timestamp.utcoffset() == timezone.utc.utcoffset(timestamp)
    assert measurement.as_row()["timestamp"].endswith("+00:00")


def test_quality_remains_a_string_enum_without_strenum() -> None:
    assert isinstance(Quality.GOOD, str)
    assert Quality.GOOD.value == "GOOD"


def test_naive_timestamps_are_normalized_to_utc() -> None:
    measurement = Measurement(
        datetime(2025, 1, 1),
        "synthetic",
        "device",
        "channel",
        "count",
        1,
    )

    assert measurement.timestamp.tzinfo is timezone.utc
