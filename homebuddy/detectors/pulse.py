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

RULES = ('duration', 'alone')


@dataclass(frozen=True)
class Candidate(Event):
    """A step up and its step down. ``rules`` has the result of each rule, in the order of ``RULES``.

    The rules accept a candidate when each rule is true. Its power is its step in ``step_w``.
    """

    rise: float
    fall: float
    rules: tuple[bool, ...]

    @property
    def duration_s(self) -> float:
        return (self.end - self.start).total_seconds()


class Pulse(Detector):
    """The rules of a ``pulse`` detector: a short step up and a step down of the power."""

    sensor: Sensor  # The power sensor
    step_w: Range
    duration: DurationRange
    max_step_difference_w: Positive  # The step up and the step down are equal in this value
    side_load_w: Range | None = None  # A second load that can start or stop with the run
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
    """Each step up with an equal step down after it, not later than the longest duration.

    One of the two steps is in ``step_w``. The power between the two steps does not count, because other loads
    can start and stop in the run. A second load that starts or stops with the run makes the two steps different
    by its power.
    """
    data = updates(points)
    low, high = rules.step_w
    side = rules.side_load_w
    side_max = side[1] if side else 0
    shortest = rules.duration[0].total_seconds() - DURATION_MARGIN_S
    longest = rules.duration[1].total_seconds() + DURATION_MARGIN_S
    gap = rules.min_gap or timedelta(0)

    def equal(rise: float, fall: float) -> bool:
        """True when one step is in ``step_w``, and the two steps are equal or the second load is the difference."""
        difference = abs(rise - fall)
        return (low <= rise <= high or low <= fall <= high) and (
            difference <= rules.max_step_difference_w or (side is not None and side[0] <= difference <= side[1])
        )

    def near_range(rise: float) -> bool:
        return low - side_max <= rise <= high + side_max

    def stable(first: int, last: int) -> bool:
        """True when each change of the power from update ``first`` to update ``last`` is a small difference."""
        return (
            0 < first
            and last < len(data)
            and all(abs(data[k][1] - data[k - 1][1]) <= rules.max_step_difference_w for k in range(first, last + 1))
        )

    result = []
    for i in range(1, len(data)):
        s = i  # The first update of the step up
        rise = data[i][1] - data[i - 1][1]
        # The sensor can show a step in two updates, when the load starts in the time of an update
        if not near_range(rise) and i > 1 and not near_range(first := data[i - 1][1] - data[i - 2][1]) and first > 0:
            s, rise = i - 1, data[i][1] - data[i - 2][1]
        if not near_range(rise):
            continue
        start = data[s][0]
        # The end is the first step down that is equal to the step up. It can also be in two updates.
        for j in range(i + 1, len(data)):
            duration_s = (data[j][0] - start).total_seconds()
            if duration_s > longest:
                break
            fall, split = data[j - 1][1] - data[j][1], s < i
            if not equal(rise, fall) and j > i + 1 and data[j - 1][1] < data[j - 2][1]:
                fall, split = data[j - 2][1] - data[j][1], True
            # A step in two updates can also be two loads. It counts only when no other load changes before and after.
            if split and equal(rise, fall) and not (stable(s - 2, s - 1) and stable(j + 1, j + 2)):
                break
            if equal(rise, fall):
                power_w = rise if low <= rise <= high else fall
                result.append(Candidate(start, data[j][0], rise, fall, (duration_s >= shortest,), power_w=power_w))
                break
    # The rule "alone" needs each candidate, also a candidate that a different rule refuses
    for n, c in enumerate(result):
        near = (n > 0 and c.start - result[n - 1].end < gap) or (
            n + 1 < len(result) and result[n + 1].start - c.end < gap
        )
        checked = (*c.rules, not near)
        result[n] = replace(c, rules=checked, accepted=all(checked))
    return result
