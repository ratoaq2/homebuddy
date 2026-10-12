"""Threshold detector.

Finds a run of a device in a power sensor that measures only that device, for example a smart plug. The device
runs when the power is above a limit. The power of a run comes from that sensor, not from the sensor of a tab.
"""

from __future__ import annotations

from datetime import datetime

from homebuddy.detector import Detector
from homebuddy.fields import Positive, Sensor
from homebuddy.model import Event, History, Point


class Threshold(Detector):
    """The rules of a ``threshold`` detector: a device runs when the power of its sensor is above ``min_w``."""

    sensor: Sensor  # The power sensor of the device
    min_w: Positive

    def detect(self, data: History, start: datetime, end: datetime) -> list[Event]:
        return runs(data.numbers(self.sensor), self.min_w, end)


def runs(points: list[Point], min_w: float, end: datetime) -> list[Event]:
    """Each run, from the first value above the limit to the next value that is not above it.

    The power of a run is its average power.

    A run without an end is in progress. It stops at ``end``, the limit of the search.
    """
    result: list[Event] = []
    first: int | None = None  # The index of the first point of the run
    for i, (t, value) in enumerate(points):
        if first is None and value > min_w:
            first = i
        elif first is not None and value <= min_w:
            result.append(Event(points[first][0], t, power_w=average(points[first:i], t)))
            first = None
    if first is not None and points[first][0] < end:
        result.append(Event(points[first][0], end, power_w=average([p for p in points[first:] if p[0] < end], end)))
    return result


def average(points: list[Point], end: datetime) -> float:
    """The average of the values from the first point to ``end``. A value continues until the next point.

    The sensor can write at changing intervals, so the time of each value is its weight.
    """
    ends = [t for t, _ in points[1:]] + [end]
    total = sum(value * (t1 - t0).total_seconds() for (t0, value), t1 in zip(points, ends, strict=True))
    return total / (end - points[0][0]).total_seconds()
