"""Pulse detector.

Finds a short step up and a step down of the power, for a load that runs for some seconds.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import datetime, timedelta

from homebuddy.detector import Detector
from homebuddy.fields import Duration, DurationRange, Positive, Range, Sensor
from homebuddy.model import Event, History, Point, Table, Value

# The sensor can write more than one value in an update. The last write in this time wins.
SAME_UPDATE_S = 2
# The time between two updates changes by some seconds, so the duration range gets this margin.
DURATION_MARGIN_S = 8

RULES = ('step', 'duration', 'equal steps', 'flat', 'alone')


@dataclass(frozen=True)
class Candidate(Event):
    """A step up and its step down. ``rules`` has the result of each rule, in the order of ``RULES``.

    The rules accept a candidate when each rule is true. Its power is the power of the run above the power
    before it.
    """

    rise: float
    fall: float
    values: tuple[float, ...]  # The power in the run, minus the power before the run
    rules: tuple[bool, ...]

    @property
    def duration_s(self) -> float:
        return (self.end - self.start).total_seconds()


class Pulse(Detector):
    """The rules of a ``pulse`` detector: a short step up and a step down of the power."""

    sensor: Sensor  # The power sensor
    step_w: Range
    duration: DurationRange
    max_ripple_w: Positive  # The power in the run stays in this value
    # The step up and the step down are equal in this value. None is ``max_ripple_w``.
    max_step_difference_w: Positive | None = None
    side_load_w: Range | None = None  # A second load that can start or stop in the run
    # A candidate with a different candidate in this time before or after it is one of a series, and not a run
    min_gap: Duration | None = None

    def detect(self, data: History, start: datetime, end: datetime) -> list[Candidate]:
        return candidates(data.numbers(self.sensor), self)

    def debug(self, found: Sequence[Event], data: History) -> dict[str, Table]:
        """One row for each candidate: start, duration, the two steps, and the result of each rule."""
        rows: list[tuple[Value, ...]] = []
        for c in found:
            assert isinstance(c, Candidate)
            rules = ('ok' if ok else 'NO' for ok in c.rules)
            rows.append((c.start, round(c.duration_s), round(c.rise), round(c.fall), *rules))
        title = f'{len(found)} candidates, {sum(c.accepted for c in found)} accepted'
        return {title: Table(('Start', 'Duration (s)', 'Rise (W)', 'Fall (W)', *RULES), rows)}


def updates(points: list[Point]) -> list[Point]:
    """One value for each update. The last write of an update wins."""
    result: list[Point] = []
    for ts, value in points:
        if result and (ts - result[-1][0]).total_seconds() <= SAME_UPDATE_S:
            result[-1] = (result[-1][0], value)
        else:
            result.append((ts, value))
    return result


def candidates(points: list[Point], rules: Pulse) -> list[Candidate]:
    """Each step up that can be the load, with or without the second load, and the result of each rule."""
    data = updates(points)
    low, high = rules.step_w
    side = rules.side_load_w
    side_max = side[1] if side else 0
    shortest = rules.duration[0].total_seconds() - DURATION_MARGIN_S
    longest = rules.duration[1].total_seconds() + DURATION_MARGIN_S
    gap = rules.min_gap or timedelta(0)

    def same(difference: float, limit: float) -> bool:
        """True when two values are equal, or when the second load is the only difference."""
        return abs(difference) <= limit or (side is not None and side[0] <= abs(difference) <= side[1])

    result = []
    i = 1
    while i < len(data):
        start, before = data[i][0], data[i - 1][1]
        rise = data[i][1] - before
        if not low - side_max <= rise <= high + side_max:
            i += 1
            continue
        # The run ends at the first update that loses more than half of the step
        j = i + 1
        while j < len(data) and data[j][1] >= before + rise / 2 and (data[j][0] - start).total_seconds() <= longest:
            j += 1
        if j == len(data) or (data[j][0] - start).total_seconds() > longest:
            i += 1
            continue
        fall = data[j - 1][1] - data[j][1]
        values = tuple(v - before for _, v in data[i:j])
        up, down = low <= rise <= high, low <= fall <= high
        level = values[0] if up else values[-1]
        duration_s = (data[j][0] - start).total_seconds()
        ok = (
            up or down,
            shortest <= duration_s <= longest,
            same(rise - fall, rules.max_step_difference_w or rules.max_ripple_w),
            all(same(v - level, rules.max_ripple_w) for v in values),
        )
        power_w = sum(values) / len(values)
        result.append(Candidate(start, data[j][0], rise, fall, values, ok, power_w=power_w))
        i = j + 1
    # The rule "alone" needs each candidate, also a candidate that a different rule refuses
    for n, c in enumerate(result):
        near = (n > 0 and c.start - result[n - 1].end < gap) or (
            n + 1 < len(result) and result[n + 1].start - c.end < gap
        )
        checked = (*c.rules, not near)
        result[n] = replace(c, rules=checked, accepted=all(checked))
    return result
