from __future__ import annotations

from datetime import datetime, timedelta

from homebuddy.detectors.ramp import Ramp, runs
from homebuddy.model import Event, Point
from tests.conftest import TZ

RULES = Ramp(rise_per_minute=5, fall_per_minute=4, min_rise=25, sensor='sensor.air')
START = datetime(2026, 10, 9, 9, 0, tzinfo=TZ)
# A run from minute 1 to minute 12. The device stops for a short time in the run: a dip at minutes 7 and 8.
WITH_A_DIP: list[float] = [
    30,
    30,
    40,
    48,
    52,
    54,
    56,
    44,
    32,
    44,
    54,
    58,
    59,
    52,
    46,
    42,
    40,
    39,
    38,
    38,
    38,
    38,
    38,
    38,
    38,
    38,
]


def make_ramp(values: list[float]) -> list[Point]:
    """One value each minute."""
    return [(START + timedelta(minutes=i), value) for i, value in enumerate(values)]


def minutes(found: list[Event]) -> list[tuple[float, float]]:
    """The start and the end of each run, in minutes after ``START``."""
    return [((r.start - START).total_seconds() / 60, (r.end - START).total_seconds() / 60) for r in found]


def test_a_dip_continues_the_run() -> None:
    assert minutes(runs(make_ramp(WITH_A_DIP), RULES)) == [(1, 12)]


def test_a_short_pause_splits_the_run_with_a_dip() -> None:
    found = runs(make_ramp(WITH_A_DIP), RULES.model_copy(update={'max_pause': timedelta(seconds=30)}))
    assert minutes(found) == [(1, 6), (8, 12)]


def test_run() -> None:
    [run] = runs(make_ramp([30, 30, 40, 48, 52, 54, 56, 50, 44, 40, 38, 37, 36, 36, 36, 36]), RULES)
    assert run == Event(START + timedelta(minutes=1), START + timedelta(minutes=6))


def test_no_run() -> None:
    assert runs([], RULES) == []
    # A slow rise, a rise that is too small, and a run without an end
    assert (
        runs(make_ramp([30, 32, 34, 36, 38, 40, 42, 44, 46, 48, 50, 52, 46, 40, 34, 30, 30, 30, 30, 30, 30]), RULES)
        == []
    )
    assert runs(make_ramp([30, 30, 40, 44, 38, 32, 30, 30, 30, 30, 30, 30, 30]), RULES) == []
    assert runs(make_ramp([30, 30, 40, 48, 52, 54, 56]), RULES) == []
