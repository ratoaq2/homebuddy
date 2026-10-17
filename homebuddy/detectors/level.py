"""Level detector.

Finds a run of a device that uses a known, constant power for a long time, for example a car at a charger.
It looks for sustained power above the house baseline, then matches each run to the nearest level of the rules.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from statistics import median
from typing import Annotated

from pydantic import AfterValidator, Field

from homebuddy.detector import Detector
from homebuddy.fields import Duration, Positive, Sensor
from homebuddy.model import Event, History, Point, Table

BASELINE_PERCENTILE = 0.1
# A run does not stop. A run with more than this part of its points below the threshold is not a run of the device.
MAX_LOW_PART = 0.05
# The times around the start and the end of a run that give the step of the power. The points next to
# the start and the end are not in the levels of the house, because the power changes there.
STEP_NEAR = timedelta(seconds=20)
STEP_FAR = timedelta(minutes=2)
STEP_INSIDE = timedelta(minutes=1)
# A shorter drop below the threshold does not end a run.
DROP_GRACE = timedelta(minutes=1)
BASELINE = 'Baseline'  # The name of the level of the house that the chart shows


@dataclass(frozen=True)
class Run(Event):
    """A run of the device. Its power is its level of the rules, not the measured power."""

    avg_power_w: float
    level_w: float


def _below_one(value: float) -> float:
    if value >= 1:
        raise ValueError('must be a number between 0 and 1')
    return value


class Level(Detector):
    """The rules of a ``level`` detector: the power levels of the device, and the runs that count."""

    sensor: Sensor  # The power sensor
    levels_w: Annotated[tuple[Positive, ...], Field(min_length=1)]  # Each power that the device can use
    tolerance: Annotated[Positive, AfterValidator(_below_one)] = 0.1
    min_duration: Duration = timedelta(minutes=10)  # The detector ignores a shorter run

    def levels(self, data: History, start: datetime, end: datetime) -> dict[str, float]:
        # The baseline is the baseline of the search, without the margin of the points.
        return {BASELINE: compute_baseline([(t, p) for t, p in data.numbers(self.sensor) if start <= t <= end])}

    def detect(self, data: History, start: datetime, end: datetime) -> list[Run]:
        return detect_runs(data.numbers(self.sensor), self.levels(data, start, end)[BASELINE], self)

    def debug(self, found: Sequence[Event], data: History) -> dict[str, Table]:
        """The points of each run. The average power of a run does not use the first and the last one."""
        points = data.numbers(self.sensor)
        blocks = {}
        for i, run in enumerate(found, 1):
            inside = [(t, p) for t, p in points if run.start <= t <= run.end]
            marks = {0: 'first, excluded', len(inside) - 1: 'last, excluded'}
            blocks[f'Run {i}: {len(inside)} data points'] = Table(
                ('#', 'Time', 'Power (kW)', 'Average'),
                [(j, t, round(p / 1000, 3), marks.get(j, '')) for j, (t, p) in enumerate(inside)],
            )
        return blocks


def lowest_step_w(rules: Level) -> float:
    """The smallest step of the power that is a run: the lowest level, minus the tolerance."""
    return min(rules.levels_w) * (1 - rules.tolerance)


def threshold_w(baseline: float, rules: Level) -> float:
    """Power at or above this value means that the device runs, at its lowest level or more."""
    return baseline + lowest_step_w(rules)


def _percentile(values: list[float], fraction: float) -> float:
    return sorted(values)[int(len(values) * fraction)]


def compute_baseline(points: list[Point]) -> float:
    """House baseline: a low percentile of the power, so a run of any length does not raise it."""
    return _percentile([v for _, v in points], BASELINE_PERCENTILE) if points else 0


def _nearest_level(powers: list[float], baseline: float, rules: Level) -> float:
    """The level of the rules for these powers of a run."""
    # House load only adds power, so the floor of the run is the level of the device
    floor = _percentile(powers, BASELINE_PERCENTILE)
    return min(rules.levels_w, key=lambda w: abs(w - (floor - baseline)))


def _close_run(start: datetime, end: datetime, powers: list[float], baseline: float, rules: Level) -> Run:
    # The average does not use the first and the last point, where the power rises and falls.
    stable_powers = powers[1:-1] if len(powers) > 2 else powers
    avg_power = sum(stable_powers) / len(stable_powers) if stable_powers else 0
    duration_h = (end - start).total_seconds() / 3600.0
    level = _nearest_level(powers, baseline, rules)
    # The energy uses the level of the rules, not the measured power
    return Run(start, end, avg_power, level, power_w=level, energy_kwh=level / 1000.0 * duration_h)


def _split_run(
    start: datetime,
    end: datetime,
    run: list[Point],
    dips: list[tuple[int, datetime, datetime]],
    baseline: float,
    rules: Level,
) -> list[Run]:
    """Close a run. A short dip splits it when the level near the dip changes.

    ``run`` has the points of the run above the threshold. Each dip is the number of these points before it,
    its start and its end. The level of each side comes from ``STEP_FAR`` next to the dip, because the device
    can change its level later in the run without a dip.
    """
    runs: list[Run] = []
    first = 0
    powers = [power for _, power in run]
    for count, dip_start, dip_end in dips:
        last_before, first_after = run[count - 1][0], run[count][0]
        before = [power for ts, power in run[first:count] if ts >= last_before - STEP_FAR]
        after = [power for ts, power in run[count:] if ts <= first_after + STEP_FAR]
        if _nearest_level(before, baseline, rules) != _nearest_level(after, baseline, rules):
            runs.append(_close_run(start, dip_start, powers[first:count], baseline, rules))
            start, first = dip_end, count
    runs.append(_close_run(start, end, powers[first:], baseline, rules))
    return runs


def _level(points: list[Point], first: datetime, last: datetime) -> float | None:
    """The median power from ``first`` to ``last``. None when there is no point."""
    values = [power for ts, power in points if first <= ts <= last]
    return median(values) if values else None


def _is_run(run: Run, points: list[Point], threshold: float, rules: Level) -> bool:
    """True when the run is sustained, and its step up or its step down is the lowest level or more.

    The threshold is above the baseline of the day. The house can be above that baseline, so a smaller load
    also gets above the threshold. The step of the power at the start and at the end shows the real load.
    """
    inside = [power for ts, power in points if run.start <= ts < run.end]
    if sum(power < threshold for power in inside) > MAX_LOW_PART * len(inside):
        return False
    start, end = run.start, run.end
    # The level of the house before and after the run, and the level of the run at its start and end
    before, first = _level(points, start - STEP_FAR, start - STEP_NEAR), _level(points, start, start + STEP_INSIDE)
    last = _level([p for p in points if p[0] < end], end - STEP_INSIDE, end)
    after = _level(points, end + STEP_NEAR, end + STEP_FAR)
    steps = [high - low for high, low in ((first, before), (last, after)) if high is not None and low is not None]
    # A run at a limit of the data has no step. The other rules decide.
    return not steps or max(steps) >= lowest_step_w(rules)


def detect_runs(points: list[Point], baseline: float, rules: Level) -> list[Run]:
    """Each run of ``rules.min_duration`` or more: sustained power above the threshold, with its level.

    ``baseline`` is the power of the house without the device. See ``_is_run`` for the runs that do not count.
    The energy of a run uses its level of the rules, not the measured power.
    """
    if not points:
        return []

    threshold = threshold_w(baseline, rules)

    runs: list[Run] = []
    in_run = False
    run_start = points[0][0]
    run: list[Point] = []  # The points of the run above the threshold
    below_since: datetime | None = None
    # The short drops of the run. A change of the level can be one of them.
    dips: list[tuple[int, datetime, datetime]] = []

    for ts, power in points:
        if power >= threshold:
            if not in_run:
                in_run = True
                run_start = ts
                run = [(ts, power)]
                dips = []
            else:
                if below_since is not None:
                    dips.append((len(run), below_since, ts))
                run.append((ts, power))
            below_since = None
        elif in_run:
            if below_since is None:
                below_since = ts
            elif ts - below_since > DROP_GRACE:
                # A longer drop is the end of the run
                runs += _split_run(run_start, below_since, run, dips, baseline, rules)
                in_run = False
                below_since = None

    # A run that continues at the end of the data
    if in_run and run:
        runs += _split_run(run_start, points[-1][0], run, dips, baseline, rules)

    return [r for r in runs if r.end - r.start >= rules.min_duration and _is_run(r, points, threshold, rules)]
