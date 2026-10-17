from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from homebuddy.detectors.level import compute_baseline, detect_runs, threshold_w
from tests.conftest import BASELINE_W, EV, LEVELS, TZ, make_points, make_two_car_day


def test_detect_no_points() -> None:
    assert detect_runs([], 0.0, EV) == []


def test_detect_nothing_above_threshold(day_start: datetime) -> None:
    points = make_points(day_start, [(100, BASELINE_W)])
    assert detect_runs(points, BASELINE_W, EV) == []


def test_detect_one_run(day_start: datetime, charge_w: float) -> None:
    points = make_points(day_start, [(10, BASELINE_W), (120, charge_w), (10, BASELINE_W)])
    runs = detect_runs(points, BASELINE_W, EV)

    assert len(runs) == 1
    r = runs[0]
    assert r.start == day_start + timedelta(seconds=10 * 30)
    assert r.end == day_start + timedelta(seconds=130 * 30)
    assert r.avg_power_w == pytest.approx(charge_w)
    assert (r.level_w, r.label) == (LEVELS[16], '')
    assert r.power_w == LEVELS[16]
    assert r.energy_kwh == pytest.approx(LEVELS[16] / 1000)


def test_detect_two_runs(day_start: datetime, charge_w: float) -> None:
    points = make_points(
        day_start, [(10, BASELINE_W), (20, charge_w), (20, BASELINE_W), (40, charge_w), (10, BASELINE_W)]
    )
    runs = detect_runs(points, BASELINE_W, EV)
    assert [(r.start, r.end) for r in runs] == [
        (day_start + timedelta(seconds=10 * 30), day_start + timedelta(seconds=30 * 30)),
        (day_start + timedelta(seconds=50 * 30), day_start + timedelta(seconds=90 * 30)),
    ]


def test_detect_short_dip_keeps_run(day_start: datetime, charge_w: float) -> None:
    # Two points below the threshold span 30 s, inside the 1 minute grace time.
    points = make_points(day_start, [(10, BASELINE_W), (20, charge_w), (2, BASELINE_W), (20, charge_w), (10, 0.0)])
    runs = detect_runs(points, BASELINE_W, EV)
    assert len(runs) == 1
    assert runs[0].end == day_start + timedelta(seconds=52 * 30)


def test_detect_long_dip_splits_run(day_start: datetime, charge_w: float) -> None:
    # Four points below the threshold span 90 s, longer than the grace time.
    points = make_points(day_start, [(10, BASELINE_W), (20, charge_w), (4, BASELINE_W), (20, charge_w), (10, 0.0)])
    runs = detect_runs(points, BASELINE_W, EV)
    assert len(runs) == 2
    assert runs[0].end == day_start + timedelta(seconds=30 * 30)


def test_detect_short_dip_splits_at_level_change(day_start: datetime) -> None:
    # The car changes inside the grace time: an 8 A charge, two points at the house load, then a 6 A charge.
    eight, six = (BASELINE_W + LEVELS[c] for c in (8, 6))
    points = make_points(day_start, [(10, BASELINE_W), (210, eight), (2, BASELINE_W), (140, six), (10, BASELINE_W)])
    first, second = detect_runs(points, BASELINE_W, EV)

    assert (first.level_w, first.start, first.end) == (
        LEVELS[8],
        day_start + timedelta(seconds=10 * 30),
        day_start + timedelta(seconds=220 * 30),
    )
    assert (second.level_w, second.start, second.end) == (
        LEVELS[6],
        day_start + timedelta(seconds=222 * 30),
        day_start + timedelta(seconds=362 * 30),
    )


def test_detect_short_dip_keeps_run_when_the_level_changes_later(day_start: datetime) -> None:
    # A restart of Home Assistant gives one point at 0 W in an 8 A charge. The car changes to 6 A later.
    eight, six = (BASELINE_W + LEVELS[c] for c in (8, 6))
    points = make_points(day_start, [(10, BASELINE_W), (200, eight), (1, 0.0), (100, eight), (20, six), (10, 0.0)])
    runs = detect_runs(points, BASELINE_W, EV)

    assert [(r.level_w, r.start, r.end) for r in runs] == [
        (LEVELS[8], day_start + timedelta(seconds=10 * 30), day_start + timedelta(seconds=331 * 30))
    ]


def test_detect_run_open_at_end(day_start: datetime, charge_w: float) -> None:
    points = make_points(day_start, [(10, BASELINE_W), (30, charge_w)])
    runs = detect_runs(points, BASELINE_W, EV)
    assert len(runs) == 1
    assert runs[0].end == points[-1][0]


def test_detect_average_excludes_first_and_last(day_start: datetime) -> None:
    points = make_points(day_start, [(1, 20000.0), (30, 12000.0), (1, 20000.0), (10, 0.0)])
    [run] = detect_runs(points, 0.0, EV)
    assert run.avg_power_w == pytest.approx(12000.0)


def test_detect_tolerance(day_start: datetime) -> None:
    points = make_points(day_start, [(10, 0.0), (20, LEVELS[6] * 0.85), (10, 0.0)])
    assert detect_runs(points, 0.0, EV) == []
    assert len(detect_runs(points, 0.0, EV.model_copy(update={'tolerance': 0.2}))) == 1


def test_detect_ignores_short_peak(day_start: datetime, charge_w: float) -> None:
    # 19 points span 9.5 minutes, shorter than the minimum run.
    points = make_points(day_start, [(10, BASELINE_W), (19, charge_w), (10, BASELINE_W)])
    assert detect_runs(points, BASELINE_W, EV) == []


def test_detect_min_duration(day_start: datetime, charge_w: float) -> None:
    # 41 points span 20 minutes.
    points = make_points(day_start, [(10, BASELINE_W), (41, charge_w), (10, BASELINE_W)])
    assert len(detect_runs(points, BASELINE_W, EV)) == 1
    assert detect_runs(points, BASELINE_W, EV.model_copy(update={'min_duration': timedelta(minutes=30)})) == []


def test_detect_with_other_levels(day_start: datetime) -> None:
    rules = EV.model_copy(update={'levels_w': (6900.0, 11040.0, 22080.0)})
    charge = BASELINE_W + 22080
    [run] = detect_runs(make_points(day_start, [(10, BASELINE_W), (30, charge), (10, BASELINE_W)]), BASELINE_W, rules)
    assert (run.level_w, run.power_w) == (22080, 22080)
    # A load of 4140 W is below the threshold of the lowest level, 6900 W.
    low = make_points(day_start, [(10, BASELINE_W), (30, BASELINE_W + LEVELS[6]), (10, BASELINE_W)])
    assert detect_runs(low, BASELINE_W, rules) == []
    assert len(detect_runs(low, BASELINE_W, EV)) == 1


def test_detect_one_level(day_start: datetime) -> None:
    # A device with one level, for example a heater of 2000 W
    rules = EV.model_copy(update={'levels_w': (2000.0,)})
    points = make_points(day_start, [(10, BASELINE_W), (30, BASELINE_W + 2050), (10, BASELINE_W)])
    [run] = detect_runs(points, BASELINE_W, rules)
    assert (run.level_w, run.power_w, run.avg_power_w) == (2000, 2000, BASELINE_W + 2050)


@pytest.mark.parametrize('level_w', EV.levels_w)
def test_detect_level(day_start: datetime, level_w: float) -> None:
    points = make_points(day_start, [(10, BASELINE_W), (30, BASELINE_W + level_w), (10, BASELINE_W)])
    [run] = detect_runs(points, BASELINE_W, EV)
    assert run.level_w == level_w


def test_detect_two_cars_in_one_day() -> None:
    points = make_two_car_day()
    day = datetime(2026, 10, 4, tzinfo=TZ)
    six, eight = detect_runs(points, compute_baseline(points), EV)

    assert (six.level_w, six.start, six.end) == (LEVELS[6], day.replace(hour=10), day.replace(hour=14, minute=30))
    assert (eight.level_w, eight.start, eight.end) == (
        LEVELS[8],
        day.replace(hour=14, minute=33),
        day.replace(hour=19, minute=9),
    )
    assert eight.energy_kwh == pytest.approx(LEVELS[8] / 1000 * 4.6)


def test_detect_long_house_load_keeps_level() -> None:
    # One hour of house load on top of the 8 A charge, from 17:45.
    points = make_two_car_day(peak_start_min=192, peak_min=60)
    runs = detect_runs(points, compute_baseline(points), EV)
    assert [r.level_w for r in runs] == [LEVELS[6], LEVELS[8]]


def test_compute_baseline(day_start: datetime, charge_w: float) -> None:
    # A run at the start of the day does not raise the baseline.
    points = make_points(day_start, [(120, charge_w), (600, BASELINE_W), (50, 100.0)])
    assert compute_baseline(points) == BASELINE_W
    assert compute_baseline([]) == 0


def test_threshold_w() -> None:
    # The lowest level, minus the tolerance of 10 %, above the baseline
    assert threshold_w(BASELINE_W, EV) == pytest.approx(BASELINE_W + 4140 * 0.9)


def test_detect_refuses_a_load_below_the_lowest_level(day_start: datetime) -> None:
    # The house is at 1400 W, above the baseline. A load of 3100 W for 15 minutes is above the threshold,
    # but its step is below the lowest level.
    house = 1400.0
    points = make_points(day_start, [(20, BASELINE_W), (10, house), (30, house + 3100), (10, house), (20, BASELINE_W)])
    assert detect_runs(points, BASELINE_W, EV) == []
    # The same load with the step of the lowest level is a run
    charge = house + LEVELS[6]
    points = make_points(day_start, [(20, BASELINE_W), (10, house), (30, charge), (10, house), (20, BASELINE_W)])
    assert len(detect_runs(points, BASELINE_W, EV)) == 1


def test_detect_refuses_a_load_that_is_not_sustained(day_start: datetime) -> None:
    # A load with the power of the lowest level that stops for 30 seconds in each 2.5 minutes. A run does not stop.
    charge = BASELINE_W + LEVELS[6]
    points = make_points(day_start, [(10, BASELINE_W), *[(4, charge), (1, BASELINE_W)] * 8, (10, BASELINE_W)])
    assert detect_runs(points, BASELINE_W, EV) == []
