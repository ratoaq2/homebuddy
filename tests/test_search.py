from __future__ import annotations

import pickle
from datetime import date, datetime, timedelta
from typing import Any, ClassVar
from zoneinfo import ZoneInfo

import pytest

from homebuddy.config import Settings, Tab
from homebuddy.conflicts import solve_conflicts
from homebuddy.detector import Detector
from homebuddy.detectors.pulse import Pulse
from homebuddy.detectors.ramp import Ramp
from homebuddy.model import Event, History, SensorError
from homebuddy.result import Line, SearchResult
from homebuddy.search import (
    NoDataError,
    Source,
    find_day,
)
from tests.conftest import (
    BASELINE_W,
    DURATION,
    EV,
    LEVELS,
    POWER,
    SETTINGS,
    TABS,
    TZ,
    FakeSource,
    Info,
    entries,
    make_points,
    rounded,
    with_detectors,
)

# A power tab and a tab of the discharge temperature
POWER_AND_AIR = {**TABS, 'air': Tab(sensors=entries('sensor.air'))}
# The discharge sensor. Each other sensor of these tests is a power sensor.
GAS = {'sensor.air': Info('°C')}
DAY = date(2026, 9, 13)


def find_main_day(settings: Settings, source: Source, day: date, now: datetime) -> SearchResult:
    """The result of the day search for the first tab."""
    return find_day(settings, source, day, now)[0]


@pytest.fixture
def night_charge(charge_w: float) -> FakeSource:
    """Three days of history with one charge from 22:00 on 13.09 to 02:00 on 14.09."""
    points = make_points(
        datetime(2026, 9, 12, tzinfo=TZ), [(2760, BASELINE_W), (240, charge_w), (1320, BASELINE_W)], step_s=60
    )

    return FakeSource(points, window=True)


def test_find_day_sessions_window(night_charge: FakeSource) -> None:
    result = find_main_day(SETTINGS, night_charge, date(2026, 9, 13), now=datetime(2026, 9, 20, tzinfo=TZ))

    assert night_charge.calls[0][1:] == (
        datetime(2026, 9, 12, 12, 0, tzinfo=TZ),
        datetime(2026, 9, 14, 12, 0, tzinfo=TZ),
    )
    assert (result.start, result.end) == (
        datetime(2026, 9, 13, tzinfo=TZ),
        datetime(2026, 9, 14, tzinfo=TZ),
    )


def test_find_day_sessions_today_ends_now(night_charge: FakeSource) -> None:
    now = datetime(2026, 9, 13, 15, 0, tzinfo=TZ)
    result = find_main_day(SETTINGS, night_charge, date(2026, 9, 13), now=now)

    assert night_charge.calls[0][2] == now
    assert result.end == now
    assert result.found['ev'] == []


@pytest.mark.parametrize('day', [date(2026, 9, 13), date(2026, 9, 14)])
def test_find_day_sessions_across_midnight(night_charge: FakeSource, day: date) -> None:
    result = find_main_day(SETTINGS, night_charge, day, now=datetime(2026, 9, 20, tzinfo=TZ))

    assert result.levels['Baseline'] == BASELINE_W
    assert [(s.start, s.end) for s in result.found['ev']] == [
        (datetime(2026, 9, 13, 22, 0, tzinfo=TZ), datetime(2026, 9, 14, 2, 0, tzinfo=TZ))
    ]


def test_find_day_sessions_other_day_has_no_session(night_charge: FakeSource) -> None:
    result = find_main_day(SETTINGS, night_charge, date(2026, 9, 12), now=datetime(2026, 9, 20, tzinfo=TZ))
    assert result.found['ev'] == []


def test_find_day_sessions_no_data_in_the_day(night_charge: FakeSource) -> None:
    # 15.09 has no points. Its margin has the points of 14.09.
    with pytest.raises(NoDataError):
        find_main_day(SETTINGS, night_charge, date(2026, 9, 15), now=datetime(2026, 9, 20, tzinfo=TZ))


def test_find_day_sessions_has_the_events_of_each_detector(monkeypatch: pytest.MonkeyPatch, charge_w: float) -> None:
    # One point each 16 s from 08:00: a pump run of 48 s at 08:16, then a charge of one hour at 09:04.
    profile = [(60, BASELINE_W), (3, BASELINE_W + 1000), (177, BASELINE_W), (225, charge_w), (60, BASELINE_W)]
    points = make_points(datetime(2026, 9, 13, 8, 0, tzinfo=TZ), profile, step_s=16)
    source = FakeSource(points)
    pump = Pulse(step_w=(900, 1100), duration=DURATION, max_step_difference_w=50, sensor='sensor.p')
    settings = with_detectors(well_pump=pump, other=pump.model_copy(update={'step_w': (400, 500)}))

    result = find_main_day(settings, source, date(2026, 9, 13), now=datetime(2026, 9, 14, 12, 0, tzinfo=TZ))

    assert {name: len(found) for name, found in result.accepted.items()} == {'ev': 1, 'well_pump': 1, 'other': 0}
    # The energy of each detector that has events
    assert {name: round(energy, 2) for name, energy in result.energy_kwh.items()} == {'ev': 11.04, 'well_pump': 0.01}
    # One table for the sensor: the events of each detector in the order of time, with the same columns.
    assert [(e.detector, f'{e.start:%H:%M}', e.label, rounded(e)) for e in result.events] == [
        ('well_pump', '08:16', '', (1.0, 0.01, None, None)),
        ('ev', '09:04', '', (11.04, 11.04, None, None)),
    ]


def test_find_day_has_a_result_for_each_sensor(monkeypatch: pytest.MonkeyPatch, charge_w: float) -> None:
    # One point each minute from 08:00. The discharge temperature rises from 09:00 and falls from 09:06.
    power = make_points(
        datetime(2026, 9, 13, 8, 0, tzinfo=TZ), [(60, BASELINE_W), (60, charge_w), (60, BASELINE_W)], 60
    )
    air = [30.0] * 60 + [40.0, 48.0, 52.0, 54.0, 56.0, 58.0, 50.0, 44.0, 40.0, 38.0] + [36.0] * 20
    history = {
        'sensor.p': power,
        'sensor.air': [(datetime(2026, 9, 13, 8, 0, tzinfo=TZ) + timedelta(minutes=i), v) for i, v in enumerate(air)],
    }
    source = FakeSource(history)
    sensors = {'sensor.p': POWER, 'sensor.air': Info('°C', name='Discharge')}
    source.sensor_info = lambda entity: sensors[entity]
    # The air conditioner reads the discharge sensor. The chart of the power sensor also shows its runs.
    ramp = Ramp(rise_per_minute=5, fall_per_minute=4, min_rise=25, sensor='sensor.air')
    settings = with_detectors(POWER_AND_AIR, air_conditioner=ramp)

    power_result, air_result = find_day(
        settings, source, date(2026, 9, 13), now=datetime(2026, 9, 14, 12, 0, tzinfo=TZ)
    )

    # Only the sensor that the EV detector reads has the baseline.
    assert (power_result.sensor, power_result.unit, power_result.levels) == ('sensor.p', 'W', {'Baseline': BASELINE_W})
    assert (air_result.sensor, air_result.unit, air_result.levels) == ('sensor.air', '°C', {})
    assert list(air_result.found) == ['air_conditioner']
    # The name of a sensor comes from the source. It is empty for a sensor without a name.
    assert (power_result.sensor_name, air_result.sensor_name) == ('', 'Discharge')
    # The sensor gives the columns. The run of the air conditioner has power values in the result of the power sensor.
    air_conditioner, ev = power_result.events
    assert (ev.detector, ev.label, ev.start_value, ev.peak) == ('ev', '', None, None)
    assert (air_conditioner.detector, f'{air_conditioner.start:%H:%M}', f'{air_conditioner.end:%H:%M}') == (
        'air_conditioner',
        '08:59',
        '09:05',
    )
    # The charge started at 09:00, one minute after the start of the run: 5 of the 6 values have the charge.
    assert rounded(air_conditioner) == (9.2, 0.92, None, None)
    [run] = air_result.events
    assert (run.detector, run.start, run.end) == air_conditioner[:3]
    assert rounded(run) == (None, None, 30.0, 58.0)


class Machine(Detector):
    """A detector type without a power estimate: it knows its events, and the energy of some of them."""

    cycles: tuple[Event, ...]

    estimate_power: ClassVar[bool] = False

    def detect(self, data: History, start: datetime, end: datetime) -> tuple[Event, ...]:
        return self.cycles


def test_find_day_has_the_energy_that_a_detector_knows(monkeypatch: pytest.MonkeyPatch, charge_w: float) -> None:
    # One point each minute from 08:00, with a charge from 09:00 to 10:00.
    profile = [(60, BASELINE_W), (60, charge_w), (120, BASELINE_W)]
    points = make_points(datetime(2026, 9, 13, 8, 0, tzinfo=TZ), profile, step_s=60)
    source = FakeSource(points)
    # The first cycle has the time of the charge.
    cycles = (Event(at(9, 0), at(10, 0), energy_kwh=0.7), Event(at(10, 30), at(11, 0)))
    settings = with_detectors(machine=Machine(cycles=cycles))

    result = find_main_day(settings, source, date(2026, 9, 13), now=datetime(2026, 9, 14, 12, 0, tzinfo=TZ))

    # The charge stays, because the machine does not override the EV detector.
    assert len(result.found['ev']) == 1
    assert result.conflicts == []
    # The power sensor gives no power and no energy to a cycle. The energy is the one that the machine knows.
    assert [rounded(e) for e in result.events if e.detector == 'machine'] == [
        (None, 0.7, None, None),
        (None, None, None, None),
    ]
    assert {name: round(energy, 2) for name, energy in result.energy_kwh.items()} == {'ev': 11.04, 'machine': 0.7}


def test_find_day_shows_the_sessions_in_a_tab_that_lists_the_ev_detector(
    monkeypatch: pytest.MonkeyPatch, charge_w: float
) -> None:
    profile = [(60, BASELINE_W), (60, charge_w), (60, BASELINE_W)]
    points = make_points(datetime(2026, 9, 13, 8, 0, tzinfo=TZ), profile, step_s=60)
    source = FakeSource(points)
    sensors = {'sensor.p': POWER, 'sensor.current': Info('A')}
    source.sensor_info = lambda entity: sensors[entity]
    settings = with_detectors({**TABS, 'current': Tab(sensors=entries('sensor.current'), detectors=('ev',))})

    power_result, current_result = find_day(
        settings, source, date(2026, 9, 13), now=datetime(2026, 9, 14, 12, tzinfo=TZ)
    )

    assert (current_result.sensor, current_result.unit, current_result.levels) == ('sensor.current', 'A', {})
    assert current_result.found['ev'] == power_result.found['ev'] != []


def test_a_power_sensor_in_kw_gives_the_same_result_as_the_sensor_in_w(
    monkeypatch: pytest.MonkeyPatch, charge_w: float
) -> None:
    # One point each 16 s from 08:00: a pump run of 48 s at 08:16, then a charge of one hour at 09:04.
    profile = [(60, BASELINE_W), (3, BASELINE_W + 1000), (177, BASELINE_W), (225, charge_w), (60, BASELINE_W)]
    points = make_points(datetime(2026, 9, 13, 8, 0, tzinfo=TZ), profile, step_s=16)
    pump = Pulse(step_w=(900, 1100), duration=DURATION, max_step_difference_w=50, sensor='sensor.p')
    settings = with_detectors(well_pump=pump)
    now = datetime(2026, 9, 14, 12, 0, tzinfo=TZ)

    watts = find_main_day(settings, FakeSource(points), date(2026, 9, 13), now=now)
    source = FakeSource([(t, value / 1000) for t, value in points], lambda sensor: Info('kW', power=True))
    kilowatts = find_main_day(settings, source, date(2026, 9, 13), now=now)

    assert [e.detector for e in watts.events] == ['well_pump', 'ev']
    assert kilowatts.events == watts.events
    # The points and the levels of the result are in watts for the two units.
    assert (kilowatts.unit, kilowatts.power) == (watts.unit, watts.power) == ('W', True)
    assert kilowatts.points == pytest.approx(watts.points)
    assert kilowatts.levels == pytest.approx(watts.levels)


def test_a_sensor_in_w_without_the_power_class_is_not_a_power_sensor(
    monkeypatch: pytest.MonkeyPatch, charge_w: float
) -> None:
    profile = [(60, BASELINE_W), (60, charge_w), (60, BASELINE_W)]
    points = make_points(datetime(2026, 9, 13, 8, 0, tzinfo=TZ), profile, step_s=60)
    source = FakeSource(points)
    source.sensor_info = lambda sensor: Info('W')
    machine = Machine(cycles=())

    result = find_main_day(
        with_detectors(machine=machine), source, date(2026, 9, 13), now=datetime(2026, 9, 14, tzinfo=TZ)
    )

    assert (result.unit, result.power) == ('W', False)
    # The tab shows only the detector that reads its sensor. The columns are those of a sensor that is not power.
    assert list(result.found) == ['ev']
    assert [rounded(e) for e in result.events] == [(None, None, round(charge_w, 2), round(charge_w, 2))]
    assert result.energy_kwh == {}


def test_find_day_has_a_result_for_each_tab_of_the_file(monkeypatch: pytest.MonkeyPatch) -> None:
    start = datetime(2026, 9, 13, 8, 0, tzinfo=TZ)
    history = {
        'sensor.p': make_points(start, [(60, BASELINE_W)], step_s=60),
        'sensor.air': make_points(start, [(60, 30.0)], step_s=60),
        'sensor.no_data': [],
    }
    source = FakeSource(history)
    source.sensor_info = lambda entity: GAS.get(entity, POWER)
    ramp = Ramp(rise_per_minute=5, fall_per_minute=4, min_rise=25, sensor='sensor.air')
    tabs = {
        'air': Tab(name='Air conditioner', sensors=entries('sensor.air')),
        'power': Tab(sensors=entries('sensor.p')),
        'only_line': Tab(sensors=entries('sensor.p'), detectors=()),
        'no_data': Tab(sensors=entries('sensor.no_data')),
        'listed': Tab(sensors=entries('sensor.air'), detectors=('air_conditioner', 'ev')),
    }
    settings = with_detectors(tabs, air_conditioner=ramp)

    results = find_day(settings, source, date(2026, 9, 13), now=datetime(2026, 9, 14, 12, 0, tzinfo=TZ))

    # The tabs have the order of the file. A tab whose sensor has no data in the day gives no result.
    assert [(r.tab, r.tab_name, r.sensor) for r in results] == [
        ('air', 'Air conditioner', 'sensor.air'),
        ('power', '', 'sensor.p'),
        ('only_line', '', 'sensor.p'),
        ('listed', '', 'sensor.air'),
    ]
    assert {r.tab: list(r.found) for r in results} == {
        # Without a list, a tab of a different sensor shows the detectors that read its sensor.
        'air': ['air_conditioner'],
        # Without a list, the tab of a power sensor shows each detector, in the order of the file.
        'power': ['ev', 'air_conditioner'],
        'only_line': [],
        # The list of a tab gives its detectors and their order.
        'listed': ['air_conditioner', 'ev'],
    }
    # The levels of a detector are for the tabs of the sensor that it reads.
    assert [list(r.levels) for r in results] == [[], ['Baseline'], [], []]


def test_find_day_has_a_line_for_each_sensor_of_a_tab() -> None:
    start = datetime(2026, 9, 13, 8, 0, tzinfo=TZ)
    solar = make_points(start, [(60, 1.5)], step_s=60)
    history = {
        'sensor.p': make_points(start, [(60, BASELINE_W)], step_s=60),
        'sensor.solar': solar,
        'sensor.air': make_points(start, [(60, 30.0)], step_s=60),
    }
    source = FakeSource(history)
    sensors = {'sensor.solar': Info('kW', power=True, name='Solar'), **GAS}
    source.sensor_info = lambda entity: sensors.get(entity, POWER)
    now = datetime(2026, 9, 14, 12, 0, tzinfo=TZ)

    [result] = find_day(with_detectors({'power': Tab(sensors=entries('sensor.p', 'sensor.solar'))}), source, DAY, now)

    # The first sensor is the sensor of the tab. The other one is a line, in watts.
    assert (result.sensor, list(result.found), list(result.levels)) == ('sensor.p', ['ev'], ['Baseline'])
    assert result.lines == [Line('sensor.solar', 'Solar', [(t, 1500.0) for t, _ in solar])]
    # A sensor of a different class cannot be a line of the chart.
    with pytest.raises(SensorError, match=r'^tabs\.power\.sensors\.1: sensor.air does not have the class'):
        find_day(with_detectors({'power': Tab(sensors=entries('sensor.p', 'sensor.air'))}), source, DAY, now)


def test_find_day_no_data(monkeypatch: pytest.MonkeyPatch) -> None:
    source = FakeSource([])
    with pytest.raises(NoDataError):
        find_day(SETTINGS, source, date(2026, 9, 13), now=datetime(2026, 9, 14, 12, 0, tzinfo=TZ))


def at(hour: int, minute: int) -> datetime:
    return datetime(2026, 9, 13, hour, minute, tzinfo=TZ)


def test_solve_conflicts() -> None:
    overrides = {'air_conditioner': ('ev',), 'ev': (), 'pump': ()}
    session = Event(at(2, 0), at(2, 29))
    long_session = Event(at(1, 0), at(4, 0))
    run = Event(at(1, 53), at(2, 28))

    def lost(found: dict[str, list[Any]]) -> list[tuple[str, datetime, str]]:
        return [(c.detector, c.start, c.winner) for c in solve_conflicts(found, overrides)]

    # The air conditioner overrides the EV detector, and the two events are the same event.
    assert lost({'ev': [session], 'air_conditioner': [run]}) == [('ev', at(2, 0), 'air_conditioner')]
    assert lost({'air_conditioner': [run], 'ev': [session]}) == [('ev', at(2, 0), 'air_conditioner')]
    # A long charge with an air conditioner run in it is not the same event.
    assert lost({'ev': [long_session], 'air_conditioner': [run]}) == []
    # A detector that overrides nothing removes nothing. The two events stay.
    assert lost({'ev': [session], 'pump': [run]}) == []
    assert lost({'ev': [], 'air_conditioner': []}) == []


def test_find_day_removes_the_event_of_a_detector_that_a_different_one_overrides(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # One point each minute from 08:00. The air conditioner runs from 08:59 to 09:05, with the power of a 6 A charge.
    air = [30.0] * 60 + [40.0, 48.0, 52.0, 54.0, 56.0, 58.0, 50.0, 44.0, 40.0, 38.0] + [36.0] * 20
    power = [BASELINE_W] * 60 + [BASELINE_W + LEVELS[6]] * 6 + [BASELINE_W] * 24
    start = datetime(2026, 9, 13, 8, 0, tzinfo=TZ)
    history = {
        'sensor.p': [(start + timedelta(minutes=i), v) for i, v in enumerate(power)],
        'sensor.air': [(start + timedelta(minutes=i), v) for i, v in enumerate(air)],
    }
    source = FakeSource(history)
    source.sensor_info = lambda entity: GAS.get(entity, POWER)
    ramp = Ramp(rise_per_minute=5, fall_per_minute=4, min_rise=25, sensor='sensor.air', overrides=('ev',))
    ev = EV.model_copy(update={'min_duration': timedelta(minutes=3)})
    settings = with_detectors(POWER_AND_AIR, ev=ev, air_conditioner=ramp)
    now = datetime(2026, 9, 14, 12, 0, tzinfo=TZ)

    power_result, air_result = find_day(settings, source, date(2026, 9, 13), now=now)
    assert power_result.found['ev'] == []
    assert [e.detector for e in power_result.events] == ['air_conditioner']
    assert [(c.detector, f'{c.start:%H:%M}', c.winner) for c in power_result.conflicts] == [
        ('ev', '09:00', 'air_conditioner')
    ]
    assert air_result.conflicts == []

    # Without ``overrides``, the two events stay.
    alone = with_detectors(POWER_AND_AIR, ev=ev, air_conditioner=ramp.model_copy(update={'overrides': ()}))
    power_result, _ = find_day(alone, source, date(2026, 9, 13), now=now)
    assert (len(power_result.found['ev']), power_result.conflicts) == (1, [])
    assert [e.detector for e in power_result.events] == ['air_conditioner', 'ev']


def test_a_result_has_the_detectors_and_no_settings(charge_w: float) -> None:
    profile = [(60, BASELINE_W), (60, charge_w), (60, BASELINE_W)]
    source = FakeSource(make_points(datetime(2026, 9, 13, 8, 0, tzinfo=TZ), profile, step_s=60))
    pump = Pulse(step_w=(900, 1100), duration=DURATION, max_step_difference_w=50, sensor='sensor.p', name='Pump')
    settings = with_detectors(well_pump=pump)

    result = find_main_day(settings, source, date(2026, 9, 13), now=datetime(2026, 9, 14, tzinfo=TZ))

    # The detectors of the file, in the order of the file
    assert result.detectors == settings.detectors
    # The address of Home Assistant is not in the result.
    assert not hasattr(result, 'settings')
    assert settings.home_assistant.url not in repr(result) + pickle.dumps(result).decode('latin1')


def test_a_file_without_a_time_zone_uses_the_time_zone_of_the_source(charge_w: float) -> None:
    profile = [(60, BASELINE_W), (60, charge_w), (60, BASELINE_W)]
    points = make_points(datetime(2026, 9, 13, 8, 0, tzinfo=TZ), profile, step_s=60)
    zone = ZoneInfo('America/New_York')
    now = datetime(2026, 9, 20, tzinfo=TZ)

    # With the key, the search does not ask the source.
    source = FakeSource(points, zone='America/New_York')
    result = find_main_day(SETTINGS, source, date(2026, 9, 13), now=now)
    assert (result.tz, source.zone_calls) == (TZ, 0)

    # Without the key, the day and the result have the time zone of the source.
    source = FakeSource(points, zone='America/New_York')
    result = find_main_day(SETTINGS.model_copy(update={'timezone': None}), source, date(2026, 9, 13), now=now)
    assert result.tz == zone
    assert (result.start, result.end) == (datetime(2026, 9, 13, tzinfo=zone), datetime(2026, 9, 14, tzinfo=zone))
    assert source.zone_calls > 0
