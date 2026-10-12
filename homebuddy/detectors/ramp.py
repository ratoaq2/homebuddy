"""Ramp detector.

Finds a run of a device in a value that rises fast at the start of the run and falls fast at its end,
for example the discharge temperature of an air conditioner.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from homebuddy.detector import Detector
from homebuddy.fields import Duration, Positive, Sensor
from homebuddy.model import Event, History, Point


class Ramp(Detector):
    """The rules of a ``ramp`` detector: a value that rises fast at the start of a run and falls fast at its end."""

    sensor: Sensor  # The sensor with the value that rises and falls
    rise_per_minute: Positive  # A faster rise starts a run
    fall_per_minute: Positive  # A faster fall ends a run
    min_rise: Positive  # The minimum rise from the start to the peak
    max_pause: Duration = timedelta(minutes=5)  # A new fast rise in this time after a fast fall continues the run

    def detect(self, data: History, start: datetime, end: datetime) -> list[Event]:
        return runs(data.numbers(self.sensor), self)


def runs(points: list[Point], rules: Ramp) -> list[Event]:
    """Each run that has an end, from the value before the fast rise to the peak before the fast fall.

    A new fast rise soon after a fast fall continues the run.
    """
    result: list[tuple[Point, Point]] = []  # The start and the peak of each run
    start: Point | None = None
    peak = points[0] if points else None
    fall: datetime | None = None  # The time of the last fast fall
    for (t0, v0), (t1, v1) in zip(points, points[1:], strict=False):
        rate = (v1 - v0) / ((t1 - t0).total_seconds() / 60)
        if start is None:
            if rate >= rules.rise_per_minute:
                start, peak, fall = (t0, v0), (t1, v1), None
            continue
        assert peak is not None
        if fall is not None and t1 - fall > rules.max_pause and rate < rules.rise_per_minute:
            result.append((start, peak))
            start = None
            continue
        if rate <= -rules.fall_per_minute:
            fall = t1
        elif rate >= rules.rise_per_minute:
            fall = None
        if v1 > peak[1]:
            peak = (t1, v1)
    if start is not None and peak is not None and fall is not None:
        result.append((start, peak))
    return [Event(start[0], peak[0]) for start, peak in result if peak[1] - start[1] >= rules.min_rise]
