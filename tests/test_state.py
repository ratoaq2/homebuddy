from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

from homebuddy.config import ConfigError, load_settings
from homebuddy.detectors.state import State, runs
from homebuddy.model import Event, History, Reading, SensorError
from homebuddy.search import find_day
from tests.conftest import BASELINE_W, POWER, TABS_YAML, TZ, FakeSource, Info, make_points, rounded, with_detectors

IDLE = ('off', 'ready')
MACHINE = State(sensor='sensor.program', idle_states=IDLE, energy_sensor='sensor.energy')


def at(hour: int, minute: int, second: int = 0) -> datetime:
    return datetime(2026, 9, 13, hour, minute, second, tzinfo=TZ)


def readings(*states: tuple[int, int, str]) -> list[Reading]:
    return [(at(hour, minute), state) for hour, minute, state in states]


def found(program: list[Reading], energy: list[Reading], unit: str = 'kWh') -> list[Event]:
    return MACHINE.detect(
        History({'sensor.program': program, 'sensor.energy': energy}, {'sensor.energy': unit}), at(0, 0), at(23, 0)
    )


def test_a_run_is_the_time_of_the_states_that_are_not_idle() -> None:
    program = readings(
        (8, 0, 'off'), (9, 0, 'wash'), (9, 30, 'rinse'), (10, 0, 'off'), (11, 0, 'ready'), (12, 0, 'dry')
    )
    # A change between two states that are not idle continues the run. Its label is its first state.
    assert runs(program, IDLE, at(23, 0)) == [
        Event(at(9, 0), at(10, 0), label='wash'),
        Event(at(12, 0), at(23, 0), label='dry'),
    ]


def test_a_sensor_without_a_value_does_not_change_the_state() -> None:
    program = readings((9, 0, 'wash'), (9, 10, 'unavailable'), (9, 11, 'wash'), (10, 0, 'off'), (10, 5, 'unknown'))
    assert runs(program, IDLE, at(23, 0)) == [Event(at(9, 0), at(10, 0), label='wash')]


def test_a_run_in_progress_stops_at_the_limit_of_the_search() -> None:
    program = readings((8, 0, 'off'), (9, 0, 'wash'))
    assert runs(program, IDLE, at(9, 40)) == [Event(at(9, 0), at(9, 40), label='wash')]
    # A run that starts after the limit is not a run of the search.
    assert runs(program, IDLE, at(8, 30)) == []


def test_no_run() -> None:
    assert runs([], IDLE, at(23, 0)) == []
    assert runs(readings((8, 0, 'off'), (9, 0, 'unavailable'), (9, 1, 'ready')), IDLE, at(23, 0)) == []


def test_the_energy_stays_after_the_run() -> None:
    # The sensor has the energy of the run before, then no value at the start, then it rises.
    program = readings((8, 0, 'off'), (9, 0, 'wash'), (10, 0, 'off'))
    energy = readings((7, 0, '1.2'), (9, 0, 'unknown'), (9, 10, '0.1'), (9, 40, '0.6'), (9, 50, '0.7'))
    assert found(program, energy) == [Event(at(9, 0), at(10, 0), label='wash', energy_kwh=0.7)]


def test_the_energy_comes_at_the_end_of_the_run() -> None:
    program = readings((8, 0, 'off'), (9, 0, 'on'), (10, 0, 'off'))
    # The sensor writes the energy some moments after the end. A value of the run before is in the run.
    energy = [(at(7, 0), '1.586'), (at(9, 30), '1.586'), (at(10, 0, 20), '0.858')]
    assert found(program, energy) == [Event(at(9, 0), at(10, 0), label='on', energy_kwh=0.858)]
    # A value that comes later is not the energy of the run.
    assert found(program, [(at(10, 2), '0.858')]) == [Event(at(9, 0), at(10, 0), label='on', energy_kwh=None)]


def test_the_energy_goes_to_0_at_the_end_of_the_run() -> None:
    program = readings(
        (8, 0, 'off'), (9, 0, '1 zone'), (9, 5, '2 zones'), (9, 20, 'off'), (11, 0, 'none'), (11, 9, 'off')
    )
    energy = readings((9, 1, '0.008'), (9, 10, '0.1'), (9, 19, '0.186'), (9, 20, '0'), (11, 9, '0'))
    assert found(program, energy) == [
        Event(at(9, 0), at(9, 20), label='1 zone', energy_kwh=0.186),
        Event(at(11, 0), at(11, 9), label='none', energy_kwh=0),
    ]


def test_an_energy_sensor_in_wh_gives_kwh() -> None:
    program = readings((9, 0, 'wash'), (10, 0, 'off'))
    assert found(program, readings((9, 50, '700')), 'Wh') == [Event(at(9, 0), at(10, 0), label='wash', energy_kwh=0.7)]


@pytest.mark.parametrize('unit', ['MJ', ''])
def test_an_energy_sensor_with_a_wrong_unit(unit: str) -> None:
    with pytest.raises(SensorError, match=f'energy_sensor: the unit of sensor.energy is `{unit}`. It must be kWh'):
        found(readings((9, 0, 'wash'), (10, 0, 'off')), readings((9, 50, '700')), unit)


def test_the_labels_change_the_label_of_a_run() -> None:
    machine = State(sensor='sensor.program', idle_states=IDLE, labels={'wash': 'Washing'})
    data = History({'sensor.program': readings((9, 0, 'wash'), (10, 0, 'off'), (11, 0, 'dry'), (12, 0, 'off'))})
    # A state without a label shows its name.
    assert [e.label for e in machine.detect(data, at(0, 0), at(23, 0))] == ['Washing', 'dry']


def test_a_run_without_an_energy_sensor_has_no_energy() -> None:
    assert MACHINE.sensors == ('sensor.program', 'sensor.energy')
    machine = State(sensor='sensor.program', idle_states=IDLE)
    assert machine.sensors == ('sensor.program',)
    data = History({'sensor.program': readings((9, 0, 'wash'), (10, 0, 'off'))})
    assert machine.detect(data, at(0, 0), at(23, 0)) == [Event(at(9, 0), at(10, 0), label='wash')]


def test_the_power_chart_shows_the_run_with_the_energy_of_the_device(monkeypatch: pytest.MonkeyPatch) -> None:
    history: dict[str, list[Any]] = {
        'sensor.p': make_points(at(8, 0), [(240, BASELINE_W)], 60),
        'sensor.program': readings((8, 0, 'off'), (9, 0, 'wash'), (10, 0, 'off'), (11, 30, 'dry')),
        'sensor.energy': readings((9, 50, '0.7')),
    }
    source = FakeSource(history)
    sensors = {'sensor.p': POWER, 'sensor.energy': Info('kWh')}
    source.sensor_info = lambda entity: sensors.get(entity, Info())
    now = at(12, 0)

    # The program sensor and the energy sensor are not in a tab: they have no result.
    [result] = find_day(with_detectors(machine=MACHINE), source, now.date(), now=now)

    assert result.sensor == 'sensor.p'
    # The last run is in progress: it stops at the present time, and it has no energy.
    assert [(e.detector, f'{e.start:%H:%M}', f'{e.end:%H:%M}', e.label, rounded(e)) for e in result.events] == [
        ('machine', '09:00', '10:00', 'wash', (None, 0.7, None, None)),
        ('machine', '11:30', '12:00', 'dry', (None, None, None, None)),
    ]
    assert result.energy_kwh == {'machine': 0.7}

    # The error of a wrong unit has the path of the key.
    sensors['sensor.energy'] = Info('MJ')
    with pytest.raises(SensorError, match='detectors.machine.energy_sensor: the unit of sensor.energy is `MJ`'):
        find_day(with_detectors(machine=MACHINE), source, now.date(), now=now)


def test_settings(tmp_path: Path) -> None:
    file = tmp_path / 'homebuddy.yml'
    rules = 'type: state, sensor: sensor.program'
    keys = 'idle_states: ["off", ready], energy_sensor: sensor.energy'
    file.write_text(
        f'home_assistant:\n  url: http://ha\ntimezone: UTC\n{TABS_YAML}detectors: {{machine: {{{rules}, {keys}}}}}'
    )
    assert load_settings().detectors['machine'] == MACHINE

    file.write_text(f'home_assistant:\n  url: http://ha\ntimezone: UTC\n{TABS_YAML}detectors: {{machine: {{{rules}}}}}')
    with pytest.raises(ConfigError, match='detectors.machine.idle_states: Field required'):
        load_settings()

    # YAML reads ``off`` without quotes as false.
    file.write_text(
        f'home_assistant:\n  url: http://ha\ntimezone: UTC\n{TABS_YAML}'
        f'detectors: {{machine: {{{rules}, idle_states: [off]}}}}'
    )
    with pytest.raises(ConfigError, match='detectors.machine.idle_states.0: Input should be a valid string'):
        load_settings()

    file.write_text(
        f'home_assistant:\n  url: http://ha\ntimezone: UTC\n{TABS_YAML}'
        f'detectors: {{machine: {{{rules}, {keys}, labels: {{wash: Washing}}}}}}'
    )
    assert load_settings().detectors['machine'] == MACHINE.model_copy(update={'labels': {'wash': 'Washing'}})
