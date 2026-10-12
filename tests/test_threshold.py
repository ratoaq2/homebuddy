from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

from homebuddy.config import ConfigError, Tab, load_settings
from homebuddy.detectors.threshold import Threshold, runs
from homebuddy.model import Event, History, Point, Reading
from homebuddy.search import find_day
from tests.conftest import BASELINE_W, TABS, TABS_YAML, TZ, FakeSource, entries, make_points, rounded, with_detectors

MIN_W = 5
MACHINE = Threshold(sensor='sensor.plug', min_w=MIN_W)


def at(hour: int, minute: int) -> datetime:
    return datetime(2026, 9, 13, hour, minute, tzinfo=TZ)


def points(*values: tuple[int, int, float]) -> list[Point]:
    return [(at(hour, minute), value) for hour, minute, value in values]


def test_a_run_is_the_time_of_the_values_above_the_limit() -> None:
    power = points((8, 0, 0), (9, 0, 600), (9, 30, 120), (10, 0, 0), (11, 0, 5), (12, 0, 300), (12, 30, 0))
    # A value at the limit is not above it.
    assert runs(power, MIN_W, at(23, 0)) == [
        Event(at(9, 0), at(10, 0), power_w=360),
        Event(at(12, 0), at(12, 30), power_w=300),
    ]


def test_the_power_of_a_run_has_the_time_of_each_value_as_its_weight() -> None:
    power = points((9, 0, 800), (9, 45, 400), (10, 0, 0))
    [run] = runs(power, MIN_W, at(23, 0))
    assert run.power_w == 700


def test_the_detector_reads_its_sensor_and_a_state_that_is_not_a_number_does_not_change_the_run() -> None:
    history: dict[str, list[Reading]] = {
        'sensor.plug': [(at(9, 0), '600.0'), (at(9, 10), 'unavailable'), (at(9, 11), '600.0'), (at(10, 0), '0.0')]
    }
    assert MACHINE.sensors == ('sensor.plug',)
    assert MACHINE.detect(History(history), at(0, 0), at(23, 0)) == [Event(at(9, 0), at(10, 0), power_w=600)]


def test_a_run_in_progress_stops_at_the_limit_of_the_search() -> None:
    power = points((8, 0, 0), (9, 0, 600), (9, 30, 300))
    assert runs(power, MIN_W, at(9, 40)) == [Event(at(9, 0), at(9, 40), power_w=525)]
    # The values after the limit are not in the run.
    assert runs(power, MIN_W, at(9, 20)) == [Event(at(9, 0), at(9, 20), power_w=600)]
    # A run that starts after the limit is not a run of the search.
    assert runs(power, MIN_W, at(8, 30)) == []


def test_no_run() -> None:
    assert runs([], MIN_W, at(23, 0)) == []
    assert runs(points((8, 0, 0), (9, 0, 2)), MIN_W, at(23, 0)) == []


def test_the_power_chart_shows_the_run_with_the_power_of_its_sensor(
    monkeypatch: pytest.MonkeyPatch, charge_w: float
) -> None:
    # A charge and a run of the machine have the same time.
    history: dict[str, list[Any]] = {
        'sensor.p': make_points(at(8, 0), [(60, BASELINE_W), (120, charge_w), (60, BASELINE_W)], 60),
        'sensor.plug': [(at(8, 0), '0.0'), (at(9, 0), '800.0'), (at(10, 0), '400.0'), (at(11, 0), '0.0')],
    }
    source = FakeSource(history)
    now = at(13, 0)

    # The sensor of the machine is not in a tab: it has no result.
    [result] = find_day(with_detectors(machine=MACHINE), source, now.date(), now=now)

    assert result.sensor == 'sensor.p'
    # The charge and the run stay. The power of the run is the power of its sensor, not the power of the chart.
    assert [(e.detector, f'{e.start:%H:%M}', f'{e.end:%H:%M}') for e in result.events] == [
        ('ev', '09:00', '11:00'),
        ('machine', '09:00', '11:00'),
    ]
    assert rounded(result.events[1]) == (0.6, 1.2, None, None)
    assert result.conflicts == []
    assert result.energy_kwh['machine'] == pytest.approx(1.2)


def test_each_power_tab_shows_the_power_of_the_run(monkeypatch: pytest.MonkeyPatch) -> None:
    history: dict[str, list[Any]] = {
        'sensor.p': [(at(8, 0), '500.0')],
        'sensor.q': [(at(8, 0), '100.0'), (at(9, 30), '900.0')],
        'sensor.plug': [(at(9, 0), '800.0'), (at(10, 0), '0.0')],
    }
    source = FakeSource(history)
    now = at(12, 0)
    tabs = {**TABS, 'second': Tab(sensors=entries('sensor.q'))}

    first, second = find_day(with_detectors(tabs, machine=MACHINE), source, now.date(), now=now)

    # The detector knows the power of the run. It does not come from the sensor of the tab.
    assert [rounded(e) for e in first.events] == [(0.8, 0.8, None, None)]
    assert [rounded(e) for e in second.events] == [(0.8, 0.8, None, None)]


def test_settings(tmp_path: Path) -> None:
    file = tmp_path / 'homebuddy.yml'
    rules = 'type: threshold, sensor: sensor.plug'
    file.write_text(
        f'home_assistant:\n  url: http://ha\ntimezone: UTC\n{TABS_YAML}detectors: {{machine: {{{rules}, min_w: 5}}}}'
    )
    assert load_settings().detectors['machine'] == MACHINE

    file.write_text(f'home_assistant:\n  url: http://ha\ntimezone: UTC\n{TABS_YAML}detectors: {{machine: {{{rules}}}}}')
    with pytest.raises(ConfigError, match='detectors.machine.min_w: Field required'):
        load_settings()

    file.write_text(
        f'home_assistant:\n  url: http://ha\ntimezone: UTC\n{TABS_YAML}detectors: {{machine: {{{rules}, min_w: 0}}}}'
    )
    with pytest.raises(ConfigError, match='detectors.machine.min_w: Input should be greater than 0'):
        load_settings()
