from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from homebuddy.detectors.pulse import Candidate, Pulse, candidates, updates
from homebuddy.model import Point
from tests.conftest import DURATION, TZ, make_points

RULES = Pulse(
    step_w=(900, 1100), duration=DURATION, max_step_difference_w=50, side_load_w=(200, 300), sensor='sensor.p'
)
START = datetime(2026, 10, 9, 9, 0, tzinfo=TZ)
# The noise of a power sensor, in watts. It is small against `max_step_difference_w`.
NOISE = (4.0, -3.0, 6.0, -5.0, 2.0, -6.0, 1.0)


def noisy(levels: list[float]) -> list[Point]:
    """One update each 16 seconds, as a power sensor writes it: two writes in an update, and noise on each value."""
    points: list[Point] = []
    for i, level in enumerate(levels):
        ts = START + timedelta(seconds=16 * i)
        points.append((ts, level + 20 * NOISE[i % len(NOISE)]))
        points.append((ts + timedelta(milliseconds=20), level + NOISE[i % len(NOISE)]))
    return points


# A run of 48 seconds with a step of 1000 W
PLAIN = noisy([300.0] * 5 + [1300.0] * 3 + [300.0] * 5)
# A load of 250 W stops in the same update as the start of the run
SIDE_LOAD_STOPS = noisy([550.0] * 5 + [1300.0] * 3 + [300.0] * 5)
# A load of 250 W starts in the run and stops with it
SIDE_LOAD_STARTS = noisy([300.0] * 5 + [1300.0, 1550.0, 1550.0] + [300.0] * 5)


def accepted(points: list[Point], rules: Pulse = RULES) -> list[Candidate]:
    return [c for c in candidates(points, rules) if c.accepted]


def test_updates_keeps_the_last_write() -> None:
    points = [(START, 100.0), (START + timedelta(seconds=1), 120.0), (START + timedelta(seconds=16), 130.0)]
    assert updates(points) == [(START, 120.0), (START + timedelta(seconds=16), 130.0)]


def test_runs_with_noise_are_accepted() -> None:
    found = [accepted(points) for points in (PLAIN, SIDE_LOAD_STOPS, SIDE_LOAD_STARTS)]
    steps = [(1000, 1000), (750, 1000), (1000, 1250)]
    assert [(c.rise, c.fall) for [c] in found] == [pytest.approx(step, abs=15) for step in steps]
    assert [c.duration_s for [c] in found] == [48, 48, 48]


def test_without_the_second_load() -> None:
    rules = RULES.model_copy(update={'side_load_w': None})
    assert [len(accepted(points, rules)) for points in (PLAIN, SIDE_LOAD_STOPS, SIDE_LOAD_STARTS)] == [1, 0, 0]


def test_rules() -> None:
    def found(profile: list[tuple[int, float]]) -> list[tuple[bool, ...]]:
        return [c.rules for c in candidates(make_points(START, [(5, 300.0), *profile, (5, 300.0)], step_s=16), RULES)]

    assert found([(3, 1300.0)]) == [(True, True)]
    assert found([(1, 1300.0)]) == [(False, True)]  # 16 s
    # A step of 1200 W is not in the range. A load of 150 W starts in the run and stops with it: the steps are not
    # equal. No candidate.
    assert found([(3, 1500.0)]) == []
    assert found([(1, 1300.0), (2, 1450.0)]) == []


def test_the_power_between_the_steps_does_not_count() -> None:
    def found(profile: list[tuple[int, float]]) -> list[tuple[float, float, bool]]:
        return [(c.rise, c.fall, c.accepted) for c in candidates(make_points(START, profile, step_s=16), RULES)]

    # A load of 2000 W starts in two updates in the run, and stays on after it
    assert found([(5, 300.0), (1, 1300.0), (1, 2800.0), (1, 3300.0), (5, 2300.0)]) == [(1000, 1000, True)]
    # A load of 2000 W stops in the run
    assert found([(5, 2300.0), (1, 3300.0), (2, 1300.0), (5, 300.0)]) == [(1000, 1000, True)]
    # A load of 100 W starts and stops in the run
    assert found([(5, 300.0), (1, 1300.0), (1, 1400.0), (1, 1300.0), (5, 300.0)]) == [(1000, 1000, True)]


def test_a_step_in_two_updates() -> None:
    rules = RULES.model_copy(update={'side_load_w': None})

    def found(profile: list[tuple[int, float]]) -> list[tuple[float, float, float]]:
        return [(c.rise, c.fall, c.duration_s) for c in candidates(make_points(START, profile, step_s=16), rules)]

    # The step up and the step down are in two updates, and the power is stable before and after the run
    assert found([(5, 300.0), (1, 600.0), (2, 1300.0), (1, 1000.0), (5, 300.0)]) == [(1000, 1000, 64)]
    # A different load changes the power before the run: the two updates can be two loads
    assert found([(4, 100.0), (2, 300.0), (1, 600.0), (2, 1300.0), (5, 300.0)]) == []
    # A different load changes the power after the run
    assert found([(5, 300.0), (1, 600.0), (2, 1300.0), (1, 300.0), (1, 500.0), (5, 300.0)]) == []


def test_the_limit_of_the_equal_steps() -> None:
    # A load of 100 W starts with the run and continues after it
    points = make_points(START, [(5, 300.0), (3, 1300.0), (5, 400.0)], step_s=16)
    assert candidates(points, RULES) == []
    [candidate] = candidates(points, RULES.model_copy(update={'max_step_difference_w': 120}))
    assert (candidate.rise, candidate.fall, candidate.accepted) == (1000, 900, True)


def test_a_pulse_of_a_series_is_not_alone() -> None:
    gap = RULES.model_copy(update={'min_gap': timedelta(minutes=5)})
    # Three pulses of 48 s with 64 s between them, then one pulse 10 minutes later
    series = [(5, 300.0), (3, 1300.0), (4, 300.0), (3, 1300.0), (4, 300.0), (3, 1300.0)]
    points = make_points(START, [*series, (38, 300.0), (3, 1300.0), (5, 300.0)], step_s=16)
    assert [c.rules[-1] for c in candidates(points, gap)] == [False, False, False, True]
    assert [c.accepted for c in candidates(points, gap)] == [False, False, False, True]
    assert [c.accepted for c in candidates(points, RULES)] == [True, True, True, True]
    # A pulse of 16 s is not a run, but the run next to it is not alone
    points = make_points(START, [(5, 300.0), (1, 1300.0), (4, 300.0), (3, 1300.0), (5, 300.0)], step_s=16)
    assert [c.rules for c in candidates(points, gap)] == [(False, False), (True, False)]


def test_candidate_times() -> None:
    [candidate] = candidates(make_points(START, [(5, 300.0), (3, 1300.0), (5, 300.0)], step_s=16), RULES)
    assert candidate.start == START + timedelta(seconds=80)
    assert candidate.duration_s == 48
    assert (candidate.rise, candidate.fall, candidate.power_w, candidate.accepted) == (1000, 1000, 1000, True)
    # The power of a run is its step in the range
    [candidate] = candidates(make_points(START, [(5, 550.0), (3, 1300.0), (5, 300.0)], step_s=16), RULES)
    assert (candidate.rise, candidate.fall, candidate.power_w) == (750, 1000, 1000)


def test_no_candidate() -> None:
    assert candidates([], RULES) == []
    # A run that is too long, a run without an end, and a step up without an equal step down
    assert candidates(make_points(START, [(5, 300.0), (10, 1300.0), (5, 300.0)], step_s=16), RULES) == []
    assert candidates(make_points(START, [(5, 300.0), (3, 1300.0)], step_s=16), RULES) == []
    assert candidates(make_points(START, [(5, 300.0), (3, 1300.0), (5, 700.0)], step_s=16), RULES) == []
