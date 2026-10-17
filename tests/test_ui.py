from __future__ import annotations

import asyncio
import json
import os
import time
from dataclasses import replace
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, get_args
from zoneinfo import ZoneInfo

import pytest

pytest.importorskip('nicegui')

from nicegui import ui  # noqa: E402
from nicegui.testing.user_simulation import user_simulation  # noqa: E402

from homebuddy import search  # noqa: E402
from homebuddy.config import CopyColumn, Tab, TabSensor  # noqa: E402
from homebuddy.detectors.level import detect_runs  # noqa: E402
from homebuddy.detectors.pulse import Pulse, candidates  # noqa: E402
from homebuddy.detectors.ramp import Ramp, runs  # noqa: E402
from homebuddy.homeassistant import HomeAssistant  # noqa: E402
from homebuddy.model import SensorError, Table  # noqa: E402
from homebuddy.result import Line, SearchResult  # noqa: E402
from homebuddy.ui import app  # noqa: E402
from homebuddy.ui.app import today  # noqa: E402
from homebuddy.ui.chart import (  # noqa: E402
    chart_height,
    chart_options,
    event_tooltips,
    event_zoom,
    smoothed,
    tab_lines,
)
from homebuddy.ui.debug import table_lines  # noqa: E402
from homebuddy.ui.events import copy_columns, duration_text, event_columns, event_rows  # noqa: E402
from homebuddy.ui.names import tab_name  # noqa: E402
from tests.conftest import (  # noqa: E402
    BASELINE_W,
    DURATION,
    EV,
    SETTINGS,
    TABS_YAML,
    TZ,
    make_history,
    make_points,
)
from tests.test_detectors import Above  # noqa: E402

DAY = date(2026, 9, 13)
DATE_FORMAT = SETTINGS.date_format


def make_result(charge_w: float) -> SearchResult:
    points = make_points(datetime(2026, 9, 13, 13, 0, tzinfo=TZ), [(100, BASELINE_W), (120, charge_w), (20, 0)])
    return SearchResult(
        tz=TZ,
        start=datetime(2026, 9, 13, tzinfo=TZ),
        end=datetime(2026, 9, 14, tzinfo=TZ),
        levels={'Baseline': BASELINE_W},
        detectors=SETTINGS.detectors,
        points=points,
        history=make_history('sensor.p', points),
        found={'ev': detect_runs(points, BASELINE_W, EV)},
        tab='power',
        sensor='sensor.p',
    )


def test_today() -> None:
    assert today('Europe/Berlin') == datetime.now(TZ).date()
    assert today('No/Such_Zone') == date.today()


def test_manifest_icons_exist() -> None:
    manifest = json.loads((app.STATIC / 'manifest.webmanifest').read_text())
    assert manifest['display'] == 'standalone'
    assert [icon['sizes'] for icon in manifest['icons']] == ['192x192', '512x512']
    for icon in manifest['icons']:
        assert (app.STATIC / icon['src']).is_file()


def lane(options: dict[str, Any], name: str) -> tuple[str, list[tuple[str, str]]]:
    """The color of the lane of a detector, and the start and the end of each of its bars."""
    [series] = [s for s in options['series'][1:] if s['name'] == name]
    assert (series['xAxisIndex'], series['yAxisIndex']) == (1, 1)
    bars = [(a['coord'][0], b['coord'][0]) for a, b in series['markLine']['data']]
    # A bar has no text. The label of an event is in its tooltip.
    assert series['markLine']['label'] == {'show': False}
    # Each bar has a mark at its start, in the lane of the detector.
    assert [point['value'] for point in series['data']] == [[start, name] for start, _ in bars]
    # The mark and the bar of an event show the same tooltip.
    assert [point['name'] for point in series['data']] == [a['name'] for a, _ in series['markLine']['data']]
    return series['itemStyle']['color'], bars


def test_chart_options(charge_w: float) -> None:
    result = make_result(charge_w)
    options = chart_options(result, DATE_FORMAT)
    series = options['series'][0]
    # The line and the lanes have the same time axis.
    for axis in options['xAxis']:
        assert (axis['min'], axis['max']) == ('2026-09-13 00:00:00', '2026-09-14 00:00:00')
    assert len([point for point in series['data'] if point[1] is not None]) == len(result.points)
    # A sensor without a name in Home Assistant shows its entity id.
    assert series['name'] == 'sensor.p'
    assert series['data'][1] == ['2026-09-13 13:00:00', 0.5]
    assert [line['name'] for line in series['markLine']['data']] == ['Baseline 500 W']
    # One lane for each detector of the sensor. The first detector has the color of the line.
    assert options['yAxis'][1]['data'] == ['ev']
    assert lane(options, 'ev') == ('#03a9f4', [('2026-09-13 13:50:00', '2026-09-13 14:50:00')])
    assert chart_height(result) == 384 + 22


def test_chart_options_bar_of_an_event_across_midnight(charge_w: float) -> None:
    # A charge from 22:05 of the day before to 02:05. The bar shows the part in the day.
    points = make_points(datetime(2026, 9, 12, 22, 0, tzinfo=TZ), [(10, BASELINE_W), (480, charge_w), (10, 0)])
    result = replace(make_result(charge_w), points=points, found={'ev': detect_runs(points, BASELINE_W, EV)})
    assert lane(chart_options(result, DATE_FORMAT), 'ev')[1] == [('2026-09-13 00:00:00', '2026-09-13 02:05:00')]
    # A charge from 22:05 to 02:05 of the next day
    later = [(t + timedelta(days=1), p) for t, p in points]
    result = replace(make_result(charge_w), points=later, found={'ev': detect_runs(later, BASELINE_W, EV)})
    assert lane(chart_options(result, DATE_FORMAT), 'ev')[1] == [('2026-09-13 22:05:00', '2026-09-14 00:00:00')]


def test_chart_options_today_shows_the_full_day(charge_w: float) -> None:
    result = replace(make_result(charge_w), end=datetime(2026, 9, 13, 15, 0, tzinfo=TZ))
    assert chart_options(result, DATE_FORMAT)['xAxis'][0]['max'] == '2026-09-14 00:00:00'


def test_chart_options_line_has_the_limits_of_the_day(charge_w: float) -> None:
    # The mini graph of the zoom slider has the time range of the data of the line, not of the time axis.
    result = make_result(charge_w)
    data = chart_options(result, DATE_FORMAT)['series'][0]['data']
    assert (data[0], data[-1]) == (['2026-09-13 00:00:00', None], ['2026-09-14 00:00:00', None])
    # The line stops at its last point. It does not continue to the end of the day.
    assert data[len(result.points) : len(result.points) + 2] == [
        ['2026-09-13 14:59:30', 0.0],
        ['2026-09-13 14:59:30', None],
    ]
    # A point before or after the day gives the value of the line at the limit.
    points = make_points(datetime(2026, 9, 12, 23, 0, tzinfo=TZ), [(26 * 120, 300)])
    data = chart_options(replace(result, points=points), DATE_FORMAT)['series'][0]['data']
    assert (data[0], data[-1]) == (['2026-09-13 00:00:00', 0.3], ['2026-09-14 00:00:00', 0.3])
    assert len(data) == 24 * 120 + 2


def test_chart_options_has_a_line_for_each_sensor_of_the_tab(charge_w: float) -> None:
    result = make_result(charge_w)
    # One line: the name of the tab, and no legend.
    assert chart_options(result, DATE_FORMAT)['legend']['show'] is False
    solar = Line('sensor.solar', 'Solar', make_points(datetime(2026, 9, 13, 13, 0, tzinfo=TZ), [(10, 1500)]))
    result = replace(result, tab_name='Power', lines=[solar, solar._replace(name='')])

    options = chart_options(result, DATE_FORMAT)

    # Each line has the name of its sensor and its color. The lanes are after the lines.
    names = ['sensor.p', 'Solar', 'sensor.solar']
    assert [(s['name'], s['lineStyle']['color']) for s in options['series'][:3]] == list(
        zip(names, ['#03a9f4', '#eda100', '#1baf7a'], strict=True)
    )
    assert (options['legend']['show'], options['legend']['data']) == (True, names)
    assert options['series'][1]['data'][1] == ['2026-09-13 13:00:00', 1.5]
    # Only the first line has the levels. Only the other lines have an area.
    assert 'markLine' not in options['series'][1]
    assert ['areaStyle' in s for s in options['series'][:3]] == [False, True, True]
    assert [s['name'] for s in options['series'][3:]] == ['ev']

    # A line with ``name`` has this name in the legend. A line without it keeps the name of its sensor.
    entries = [
        TabSensor(sensor='sensor.p', name='Grid'),
        TabSensor(sensor='sensor.solar'),
        TabSensor(sensor='sensor.solar', name='Solar panels'),
    ]
    options = chart_options(result, DATE_FORMAT, entries=entries)
    assert options['legend']['data'] == ['Grid', 'Solar', 'Solar panels']


def test_chart_options_theme(charge_w: float) -> None:
    result = make_result(charge_w)
    light, dark = chart_options(result, DATE_FORMAT), chart_options(result, DATE_FORMAT, dark=True)
    # The line has the primary color of Home Assistant in the two themes. The tooltip has the color of the theme.
    assert light['series'][0]['lineStyle']['color'] == dark['series'][0]['lineStyle']['color'] == '#03a9f4'
    assert (light['tooltip']['backgroundColor'], dark['tooltip']['backgroundColor']) == ('#fcfcfb', '#1c1c1c')


def make_pump_result(charge_w: float) -> SearchResult:
    """The result of ``make_result`` with a pump run of one minute at 13:08."""
    result = make_result(charge_w)
    pump = make_points(datetime(2026, 9, 13, 13, 8, tzinfo=TZ), [(3, BASELINE_W + 1000)], step_s=16)
    points = sorted([p for p in result.points if not pump[0][0] <= p[0] <= pump[-1][0]] + pump)
    rules = Pulse(step_w=(900, 1100), duration=DURATION, max_step_difference_w=50, sensor='sensor.p')
    found = {**result.found, 'well_pump': candidates(points, rules)}
    history = make_history('sensor.p', points)
    return replace(
        result, detectors={**result.detectors, 'well_pump': rules}, points=points, history=history, found=found
    )


def test_chart_options_has_a_lane_for_each_detector(charge_w: float) -> None:
    options = chart_options(make_pump_result(charge_w), DATE_FORMAT)
    assert options['yAxis'][1]['data'] == ['ev', 'well_pump']
    # At the right of each lane: the number of events and their energy
    assert options['yAxis'][2]['data'] == ['1 event  11.04 kWh', '1 event  0.02 kWh']
    assert lane(options, 'well_pump') == ('#eb6834', [('2026-09-13 13:08:00', '2026-09-13 13:09:00')])
    # The line of the sensor has no mark of an event.
    assert [line['name'] for line in options['series'][0]['markLine']['data']] == ['Baseline 500 W']


def test_chart_options_of_a_narrow_screen(charge_w: float) -> None:
    result = make_pump_result(charge_w)
    wide, narrow = chart_options(result, DATE_FORMAT), chart_options(result, DATE_FORMAT, narrow=True)
    # The margins are small, so the line has the width of the screen.
    assert [(grid['left'], grid['right']) for grid in wide['grid']] == [(124, 170)] * 2
    assert [(grid['left'], grid['right']) for grid in narrow['grid']] == [(40, 20)] * 2
    # A lane has two rows: its texts, then its bars. The texts are in the lane.
    assert narrow['yAxis'][1]['data'] == ['', 'ev', '', 'well_pump']
    assert narrow['yAxis'][2]['data'] == ['1 event  11.04 kWh', '', '1 event  0.02 kWh', '']
    labels = json.dumps(['{c0|●} ev', '', '{c1|●} well_pump', ''])
    assert f'{labels}[index]' in narrow['yAxis'][1]['axisLabel'][':formatter']
    assert [axis['axisLabel']['inside'] for axis in narrow['yAxis'][1:]] == [True, True]
    assert [axis['axisLabel']['inside'] for axis in wide['yAxis'][1:]] == [False, False]
    assert (narrow['grid'][1]['height'], chart_height(result, narrow=True)) == (4 * 22, 384 + 4 * 22)
    # The bars of a lane are the same.
    assert lane(narrow, 'well_pump') == lane(wide, 'well_pump')


def test_chart_options_has_no_lane_for_a_detector_without_events(charge_w: float) -> None:
    result = make_pump_result(charge_w)
    result = replace(result, found={**result.found, 'ev': []})
    options = chart_options(result, DATE_FORMAT)
    assert (options['yAxis'][1]['data'], options['yAxis'][2]['data']) == (['well_pump'], ['1 event  0.02 kWh'])
    assert [series['name'] for series in options['series'][1:]] == ['well_pump']
    # The pump keeps the color of the second detector.
    assert lane(options, 'well_pump')[0] == '#eb6834'
    assert options['yAxis'][1]['axisLabel']['rich'] == {'c0': {'color': '#eb6834', 'fontSize': 14}}
    assert (options['grid'][1]['height'], chart_height(result)) == (22, 384 + 22)

    # A day without events has no lanes.
    result = replace(result, found={'ev': [], 'well_pump': []})
    options = chart_options(result, DATE_FORMAT)
    assert (options['yAxis'][1]['data'], options['series'][1:]) == ([], [])
    assert (options['grid'][1]['height'], chart_height(result)) == (0, 384)


def test_event_rows_have_the_columns_of_the_sensor(charge_w: float) -> None:
    result = make_pump_result(charge_w)
    # The latest event is the first row. The id of a row is the position of its event in the order of time.
    assert result.events[event_rows(result, DATE_FORMAT)[0]['id'] - 1].detector == 'ev'
    assert event_rows(result, DATE_FORMAT) == [
        {
            'id': 2,
            'key': 'ev',
            'detector': 'ev',
            'start': '2026-09-13 13:50:00',
            'end': '2026-09-13 14:50:00',
            'duration': '1 h 00 min',
            'label': '',
            'power': '11.04',
            'energy': '11.04',
        },
        {
            'id': 1,
            'key': 'well_pump',
            'detector': 'well_pump',
            'start': '2026-09-13 13:08:00',
            'end': '2026-09-13 13:09:00',
            'duration': '60 s',
            'label': '',
            'power': '1.00',
            'energy': '0.02',
        },
    ]
    assert [column['label'] for column in event_columns(result)] == [
        '#',
        'Detector',
        'Start',
        'End',
        'Duration',
        'Label',
        'Power (kW)',
        'Energy (kWh)',
        '',
    ]


def named(result: SearchResult, detector: str, name: str) -> SearchResult:
    """The result with a name for a detector."""
    rules = result.detectors[detector].model_copy(update={'name': name})
    return replace(result, detectors={**result.detectors, detector: rules})


def make_named_result(charge_w: float) -> SearchResult:
    """The result of ``make_pump_result`` with a name for the pump."""
    return named(make_pump_result(charge_w), 'well_pump', 'Well pump')


def test_name_of_a_detector(charge_w: float) -> None:
    result = make_named_result(charge_w)
    # The lane keeps the name of the detector in the file. Its label shows ``name``.
    options = chart_options(result, DATE_FORMAT)
    assert options['yAxis'][1]['data'] == ['ev', 'well_pump']
    labels = json.dumps(['ev {c0|●}', 'Well pump {c1|●}'])
    assert f'{labels}[index]' in options['yAxis'][1]['axisLabel'][':formatter']
    assert [(row['key'], row['detector']) for row in event_rows(result, DATE_FORMAT)] == [
        ('ev', 'ev'),
        ('well_pump', 'Well pump'),
    ]


def test_debug_data_of_a_detector(charge_w: float) -> None:
    result = make_pump_result(charge_w)
    # A detector gives values. The page makes each text: a time is in the time zone of the page.
    [(title, pulses)] = result.detectors['well_pump'].debug(result.found['well_pump'], result.history).items()
    assert title == '1 candidates, 1 accepted'
    assert pulses.rows == [(datetime(2026, 9, 13, 13, 8, tzinfo=TZ), 60, 1000, 1000, 'ok', 'ok')]
    assert table_lines(pulses, ZoneInfo('UTC')) == [
        'Start     Duration (s)  Rise (W)  Fall (W)  duration  alone',
        '11:08:00  60            1000      1000      ok        ok',
    ]
    [(title, session)] = result.detectors['ev'].debug(result.found['ev'], result.history).items()
    assert title == 'Run 1: 121 data points'
    lines = table_lines(session, TZ)
    assert [lines[0], lines[1], lines[2], lines[-1]] == [
        '#    Time      Power (kW)  Average',
        '0    13:50:00  11.54       first, excluded',
        '1    13:50:30  11.54',
        '120  14:50:00  0.0         last, excluded',
    ]
    # A row of a plug-in with more values than columns is not an error.
    assert table_lines(Table(('Time',), [('a', 5)]), TZ) == ['Time', 'a     5']


def test_name_of_a_tab() -> None:
    result = make_air_result()
    # The name in the file, then the name of the sensor in Home Assistant, then the entity id
    assert tab_name(replace(result, tab_name='Air conditioner')) == 'Air conditioner'
    assert tab_name(result) == 'Discharge'
    assert tab_name(replace(result, sensor_name='')) == 'sensor.air'


def test_event_rows_date_format(charge_w: float) -> None:
    [row] = event_rows(make_result(charge_w), '%Y-%m-%d %H:%M')
    assert (row['start'], row['end']) == ('2026-09-13 13:50', '2026-09-13 14:50')


def test_duration_text() -> None:
    assert [duration_text(s) for s in (48, 599, 600, 16560)] == ['48 s', '599 s', '0 h 10 min', '4 h 36 min']


def test_event_zoom(charge_w: float) -> None:
    # The run is 13:08 to 13:09, with a margin of 2 minutes. The session is 13:50 to 14:50, with 6 minutes.
    run, session = make_pump_result(charge_w).events
    assert event_zoom(run, TZ) == {
        'type': 'dataZoom',
        'startValue': '2026-09-13 13:06:00',
        'endValue': '2026-09-13 13:11:00',
    }
    assert event_zoom(session, TZ) == {
        'type': 'dataZoom',
        'startValue': '2026-09-13 13:44:00',
        'endValue': '2026-09-13 14:56:00',
    }


def make_air_result() -> SearchResult:
    """The discharge temperature of an air conditioner, one value each minute from 13:00. A run: 13:01 to 13:06."""
    values = [30.0, 30.0, 40.0, 48.0, 52.0, 54.0, 56.0, 50.0, 44.0, 40.0, 38.0, 37.0, 36.0, 36.0, 36.0, 36.0]
    points = [(datetime(2026, 9, 13, 13, i, tzinfo=TZ), value) for i, value in enumerate(values)]
    rules = Ramp(rise_per_minute=5, fall_per_minute=4, min_rise=25, sensor='sensor.air')
    return SearchResult(
        tz=TZ,
        start=datetime(2026, 9, 13, tzinfo=TZ),
        end=datetime(2026, 9, 14, tzinfo=TZ),
        detectors={**SETTINGS.detectors, 'air_conditioner': rules},
        points=points,
        found={'air_conditioner': runs(points, rules)},
        tab='discharge',
        sensor='sensor.air',
        power=False,
        sensor_name='Discharge',
        unit='°C',
    )


def test_chart_options_of_a_sensor_that_is_not_power() -> None:
    options = chart_options(make_air_result(), DATE_FORMAT)
    series = options['series'][0]
    value_axis = options['yAxis'][0]
    assert (value_axis['name'], value_axis['scale'], series['name']) == ('°C', True, 'Discharge')
    assert series['data'][3] == ['2026-09-13 13:02:00', 40.0]
    assert series['markLine']['data'] == []
    assert lane(options, 'air_conditioner') == ('#eb6834', [('2026-09-13 13:01:00', '2026-09-13 13:06:00')])
    # A sensor that is not a power sensor has no energy.
    assert options['yAxis'][2]['data'] == ['1 event']


def test_chart_options_with_a_unit_that_is_javascript() -> None:
    # The unit comes from Home Assistant. It is a text in the JavaScript of the tooltip, never code.
    unit = '"; alert(1); "'
    options = chart_options(replace(make_air_result(), unit=unit), DATE_FORMAT)
    assert options['tooltip'][':valueFormatter'].endswith(f'.toFixed(1) + {json.dumps(" " + unit)} : ""')


def test_event_tooltips(charge_w: float) -> None:
    result = make_named_result(charge_w)
    session, run = result.found['ev'][0], result.found['well_pump'][0]
    # The friendly name of the detector, then the values of the row of the event. An empty value has no line.
    assert event_tooltips(result, DATE_FORMAT) == {
        ('ev', session.start): '<b>ev</b><br>Start: 2026-09-13 13:50:00<br>End: 2026-09-13 14:50:00'
        '<br>Duration: 1 h 00 min<br>Power (kW): 11.04<br>Energy (kWh): 11.04',
        ('well_pump', run.start): '<b>Well pump</b><br>Start: 2026-09-13 13:08:00<br>End: 2026-09-13 13:09:00'
        '<br>Duration: 60 s<br>Power (kW): 1.00<br>Energy (kWh): 0.02',
    }
    # The bar of an event has the tooltip of the event.
    [series] = [s for s in chart_options(result, DATE_FORMAT)['series'][1:] if s['name'] == 'well_pump']
    assert series['data'][0]['name'].startswith('<b>Well pump</b><br>Start: 2026-09-13 13:08:00')
    assert 'silent' not in series and 'silent' not in series['markLine']

    # The text is safe HTML.
    result = named(result, 'ev', '<EV>')
    assert event_tooltips(result, DATE_FORMAT)['ev', session.start].startswith('<b>&lt;EV&gt;</b>')
    [run] = make_air_result().found['air_conditioner']
    assert event_tooltips(make_air_result(), DATE_FORMAT)['air_conditioner', run.start].endswith(
        'Start (°C): 30.0<br>Peak (°C): 56.0'
    )


def test_event_rows_of_a_ramp() -> None:
    result = make_air_result()
    [row] = event_rows(result, DATE_FORMAT)
    assert (row['detector'], row['duration'], row['start_value'], row['peak']) == (
        'air_conditioner',
        '300 s',
        '30.0',
        '56.0',
    )
    assert [column['label'] for column in event_columns(result)][-3:] == ['Start (°C)', 'Peak (°C)', '']


# The file of the page tests: Home Assistant and one detector.
FILE = (
    f'home_assistant:\n  url: http://ha\ntimezone: Europe/Berlin\n{TABS_YAML}'
    'detectors: {ev: {type: level, sensor: sensor.p, levels_w: [4140, 11040]}}\n'
)


@pytest.fixture
def found(monkeypatch: pytest.MonkeyPatch, charge_w: float) -> list[tuple[Any, ...]]:
    """Home Assistant settings, and a fake ``find_day`` that records its calls."""
    Path('homebuddy.yml').write_text(FILE)
    monkeypatch.setenv('HA_TOKEN', 'tok')
    calls: list[tuple[Any, ...]] = []

    def fake_find(*args: Any) -> list[SearchResult]:
        calls.append(args)
        if args[2] < DAY - timedelta(days=1):
            raise SensorError('detectors.machine.energy_sensor: the unit of sensor.energy is `MJ`.')
        if args[2] < DAY:
            raise search.NoDataError('no data')
        return [make_result(charge_w)]

    monkeypatch.setattr(search, 'find_day', fake_find)
    return calls


async def wait_for_calls(calls: list[tuple[Any, ...]], count: int) -> None:
    for _ in range(100):
        if len(calls) >= count:
            return
        await asyncio.sleep(0.02)
    raise AssertionError(f'{len(calls)} calls, expected {count}')


async def test_page_opens_on_today(found: list[tuple[Any, ...]]) -> None:
    async with user_simulation(app.root) as user:
        await user.open('/')
        await user.should_see('Click a row to zoom the chart')
        await user.should_see('Full day')
        await user.should_not_see('Search')

    settings, source, day = found[0]
    # The source of the search is the client of Home Assistant.
    assert isinstance(source, HomeAssistant)
    assert settings.home_assistant.url == 'http://ha'
    assert not hasattr(settings, 'ha_token')
    assert (day, settings.detectors['ev'].tolerance) == (datetime.now(TZ).date(), 0.1)


async def test_page_shows_the_runs_and_the_candidates(
    found: list[tuple[Any, ...]], monkeypatch: pytest.MonkeyPatch, charge_w: float
) -> None:
    monkeypatch.setattr(search, 'find_day', lambda *args: [make_pump_result(charge_w)])
    async with user_simulation(app.root) as user:
        await user.open('/')
        await user.should_see('Click a row to zoom the chart')
        # One table for the sensor, with the events of the two detectors
        [table] = user.find(ui.table).elements
        assert [(row['detector'], row['power']) for row in table.rows] == [('ev', '11.04'), ('well_pump', '1.00')]
        await user.should_not_see('Debug data of well_pump')

        # A click on the filter of a detector hides its rows. A second click shows them again.
        user.find(marker='filter-well_pump').click()
        assert [row['detector'] for row in table.rows] == ['ev']
        # The choice stays after a load.
        user.find(marker='reload').click()
        await asyncio.sleep(0.2)
        [table] = user.find(ui.table).elements
        assert [row['detector'] for row in table.rows] == ['ev']
        user.find(marker='filter-well_pump').click()
        assert [row['detector'] for row in table.rows] == ['ev', 'well_pump']

        # The switch loads the page again.
        user.find(ui.switch).click()
        await user.should_see('Debug data of well_pump')
        await user.should_see('1 candidates, 1 accepted')
        await user.should_see('Debug data of ev')
        await user.should_see('Run 1: 121 data points')


async def test_page_hides_the_rows_of_the_hidden_detectors_of_a_tab(
    found: list[tuple[Any, ...]], monkeypatch: pytest.MonkeyPatch, charge_w: float
) -> None:
    pump = (
        'well_pump: {type: pulse, sensor: sensor.p, step_w: [900, 1100], duration: [30, 90], max_step_difference_w: 50}'
    )
    file = FILE.replace('detectors: {', f'detectors: {{{pump}, ')

    def write(hidden: str) -> None:
        Path('homebuddy.yml').write_text(file.replace('[sensor.p]}', f'[sensor.p], hidden_detectors: [{hidden}]}}'))

    write('well_pump')
    monkeypatch.setattr(search, 'find_day', lambda *args: [make_pump_result(charge_w)])
    async with user_simulation(app.root) as user:
        await user.open('/')
        await user.should_see('Click a row to zoom the chart')
        [table] = user.find(ui.table).elements
        assert [row['detector'] for row in table.rows] == ['ev']
        # A click on the filter shows the rows. The choice stays after a load.
        user.find(marker='filter-well_pump').click()
        user.find(marker='reload').click()
        await asyncio.sleep(0.2)
        [table] = user.find(ui.table).elements
        assert [row['detector'] for row in table.rows] == ['ev', 'well_pump']

        # A change of the file sets the filters again.
        write('ev')
        user.find(marker='reload').click()
        await asyncio.sleep(0.2)
        [table] = user.find(ui.table).elements
        assert [row['detector'] for row in table.rows] == ['well_pump']

        # The only detector with events is hidden. It has its filter.
        monkeypatch.setattr(search, 'find_day', lambda *args: [make_result(charge_w)])
        user.find(marker='reload').click()
        await asyncio.sleep(0.2)
        [table] = user.find(ui.table).elements
        assert table.rows == []
        user.find(marker='filter-ev').click()
        assert [row['detector'] for row in table.rows] == ['ev']


async def test_page_shows_the_name_of_a_detector(
    found: list[tuple[Any, ...]], monkeypatch: pytest.MonkeyPatch, charge_w: float
) -> None:
    monkeypatch.setattr(search, 'find_day', lambda *args: [make_named_result(charge_w)])
    async with user_simulation(app.root) as user:
        await user.open('/')
        await user.should_see('Click a row to zoom the chart')
        [table] = user.find(ui.table).elements
        assert [row['detector'] for row in table.rows] == ['ev', 'Well pump']
        # The filter shows ``name``. Its marker has the name of the detector.
        await user.should_see('Well pump')
        user.find(marker='filter-well_pump').click()
        assert [row['detector'] for row in table.rows] == ['ev']

        user.find(ui.switch).click()
        await user.should_see('Debug data of Well pump')


async def test_page_has_a_tab_for_each_result(
    found: list[tuple[Any, ...]], monkeypatch: pytest.MonkeyPatch, charge_w: float
) -> None:
    calls: list[tuple[Any, ...]] = []

    def fake_find(*args: Any) -> list[SearchResult]:
        calls.append(args)
        return [make_result(charge_w), make_air_result()]

    monkeypatch.setattr(search, 'find_day', fake_find)
    async with user_simulation(app.root) as user:
        await user.open('/')
        await user.should_see('Click a row to zoom the chart')
        # A tab without a name has the name of its sensor. The page shows the first tab.
        [tabs] = user.find(ui.tabs).elements
        assert tabs.visible
        assert [(tab.props['name'], tab.props['label']) for tab in tabs.default_slot.children] == [
            ('power', 'sensor.p'),
            ('discharge', 'Discharge'),
        ]
        [chart] = user.find(ui.echart).elements
        [table] = user.find(ui.table).elements
        assert (chart.options['series'][0]['name'], [row['label'] for row in table.rows]) == ('sensor.p', [''])

        # A click on a tab shows its sensor, without a request to Home Assistant.
        user.find(kind=ui.tab, content='Discharge').click()
        [chart] = user.find(ui.echart).elements
        [table] = user.find(ui.table).elements
        assert (chart.options['series'][0]['name'], [row['peak'] for row in table.rows]) == ('Discharge', ['56.0'])
        assert len(calls) == 1

        # A second load keeps the chart of the selected sensor, and the theme changes it.
        user.find(marker='reload').click()
        await asyncio.sleep(0.2)
        assert user.find(ui.echart).elements == {chart}
        user.find(marker='theme').click()
        assert chart.options['series'][0]['lineStyle']['color'] == '#03a9f4'

        # The selected sensor stays when the day changes.
        [date_input] = user.find(ui.date).elements
        date_input.value = '2026-09-14'
        await asyncio.sleep(0.2)
        assert tabs.value == 'discharge'
        [chart] = user.find(ui.echart).elements
        assert chart.options['series'][0]['name'] == 'Discharge'


async def test_page_with_one_sensor_has_no_tabs(found: list[tuple[Any, ...]]) -> None:
    async with user_simulation(app.root) as user:
        await user.open('/')
        await user.should_see('Click a row to zoom the chart')
        await user.should_not_see(kind=ui.tabs)
        assert len(user.find(ui.echart).elements) == 1


@pytest.mark.parametrize(
    ('setting', 'expected'),
    [
        # Without the setting: each column, but not the number of the row
        ('', 'ev\t2026-09-13 13:50:00\t2026-09-13 14:50:00\t1 h 00 min\t\t11.04\t11.04'),
        ('copy_columns: [start, end]', '2026-09-13 13:50:00\t2026-09-13 14:50:00'),
        # The order is that of the setting. The power sensor has no peak column.
        ('copy_columns: [energy, peak, start]', '11.04\t2026-09-13 13:50:00'),
    ],
)
async def test_copy_row(
    found: list[tuple[Any, ...]], monkeypatch: pytest.MonkeyPatch, charge_w: float, setting: str, expected: str
) -> None:
    Path('homebuddy.yml').write_text(f'{FILE}{setting}\n', encoding='utf-8')
    monkeypatch.setattr(search, 'find_day', lambda *args: [make_result(charge_w)])
    copied: list[str] = []
    monkeypatch.setattr(ui.clipboard, 'write', copied.append)
    async with user_simulation(app.root) as user:
        await user.open('/')
        await user.should_see('Click a row to zoom the chart')
        [table] = user.find(ui.table).elements
        # The user simulation cannot click a button in a table cell, so send its event.
        user.find(ui.table).trigger('copy', table.rows[0])
        await user.should_see('Copied the row')

    assert copied == [expected]


async def test_page_uses_the_settings_of_the_file(found: list[tuple[Any, ...]]) -> None:
    Path('homebuddy.yml').write_text(
        f'home_assistant:\n  url: http://ha\ntimezone: UTC\n{TABS_YAML}'
        'detectors:\n  ev:\n    type: level\n    sensor: sensor.file\n'
        '    tolerance: 0.2\n    levels_w: [4140, 11040]\n'
    )
    async with user_simulation(app.root) as user:
        await user.open('/')
        await wait_for_calls(found, 1)

    settings = found[0][0]
    ev = settings.detectors['ev']
    assert (ev.sensor, settings.timezone, ev.tolerance) == ('sensor.file', 'UTC', 0.2)


async def test_config_option(found: list[tuple[Any, ...]], tmp_path: Path) -> None:
    (tmp_path / 'my.yml').write_text(FILE.replace('sensor.p', 'sensor.my'))
    async with user_simulation(lambda: app.root(str(tmp_path / 'my.yml'))) as user:
        await user.open('/')
        await wait_for_calls(found, 1)

    settings = found[0][0]
    assert (settings.home_assistant.url, settings.detectors['ev'].sensor) == ('http://ha', 'sensor.my')


async def test_wrong_config_file(found: list[tuple[Any, ...]]) -> None:
    Path('homebuddy.yml').write_text('detectors: {ev: {type: level, tolerance: 2}}\n')
    async with user_simulation(app.root) as user:
        await user.open('/')
        await user.should_see('must be a number between 0 and 1')

    assert found == []


async def test_file_without_a_detector(found: list[tuple[Any, ...]]) -> None:
    Path('homebuddy.yml').write_text(f'home_assistant:\n  url: http://ha\ntimezone: Europe/Berlin\n{TABS_YAML}')
    async with user_simulation(app.root) as user:
        await user.open('/')
        await user.should_see('detectors: Add one detector or more')

    assert found == []


async def test_navigation(found: list[tuple[Any, ...]]) -> None:
    async with user_simulation(app.root) as user:
        await user.open('/')
        await wait_for_calls(found, 1)
        [date_input] = user.find(ui.date).elements
        [next_button] = user.find(kind=ui.button, marker='next').elements
        assert not next_button.enabled

        # The user simulation cannot type into a date input, so set its value.
        date_input.value = '2026-09-14'
        await wait_for_calls(found, 2)
        assert next_button.enabled

        user.find(marker='prev').click()
        await wait_for_calls(found, 3)
        user.find(marker='next').click()
        await wait_for_calls(found, 4)
        user.find('Today').click()
        await wait_for_calls(found, 5)

    assert [call[2] for call in found[1:]] == [date(2026, 9, 14), DAY, date(2026, 9, 14), datetime.now(TZ).date()]


@pytest.mark.parametrize('fails', [False, True])
async def test_a_slow_load_does_not_replace_the_selected_day(
    found: list[tuple[Any, ...]], monkeypatch: pytest.MonkeyPatch, charge_w: float, fails: bool
) -> None:
    slow = DAY - timedelta(days=1)

    def fake_find(settings: Any, source: Any, day: date) -> list[SearchResult]:
        if day == slow:
            time.sleep(0.5)
            if fails:
                raise search.NoDataError('no data')
        return [make_result(charge_w)]

    monkeypatch.setattr(search, 'find_day', fake_find)
    async with user_simulation(app.root) as user:
        await user.open('/')
        await user.should_see('Click a row to zoom the chart')
        [date_input] = user.find(ui.date).elements

        # The user selects a day, and then a second day before the search of the first day ends.
        date_input.value = slow.isoformat()
        await asyncio.sleep(0.1)
        date_input.value = DAY.isoformat()
        await asyncio.sleep(1)
        await user.should_see(f'{DAY:%A}, {DAY.day} {DAY:%B %Y}')
        # The result or the error of the first day does not show.
        await user.should_not_see(f'{slow:%A}, {slow.day} {slow:%B %Y}')


async def test_date_that_is_javascript(found: list[tuple[Any, ...]]) -> None:
    async with user_simulation(app.root) as user:
        await user.open('/')
        await wait_for_calls(found, 1)
        [date_input] = user.find(ui.date).elements
        [date_button] = [button for button in user.find(ui.button).elements if button.props.get('icon') == 'event']

        # The date comes from the browser. It is a text in the JavaScript of the label, never code.
        value = "'); alert(1); ('"
        date_input.value = value
        assert date_button.props[':label'].startswith(f'new Date({json.dumps(value)}).')
        await user.should_see('Invalid isoformat string')


async def test_page_in_a_frame_hides_the_logo_and_the_buttons_of_the_settings(
    found: list[tuple[Any, ...]],
) -> None:
    async with user_simulation(app.root) as user:
        await user.open('/')
        await user.should_see('Click a row to zoom the chart')
        # The script adds the class ``hb-embed`` before the browser shows the page. The CSS of that class hides
        # the elements of these classes.
        assert user.client is not None
        assert f'<script>{app.EMBED_JS}</script>' in user.client.head_html
        classes = {name for element in user.find(ui.element).elements for name in element.classes}
        assert {'hb-logo', 'hb-tools', 'hb-days'} <= classes


async def test_refresh_only_on_today(found: list[tuple[Any, ...]]) -> None:
    async with user_simulation(app.root) as user:
        await user.open('/')
        await wait_for_calls(found, 1)
        [timer] = user.find(kind=ui.timer, marker='refresh').elements
        assert timer.active

        [date_input] = user.find(ui.date).elements
        date_input.value = '2026-09-14'
        await wait_for_calls(found, 2)
        assert not timer.active


async def test_refresh_goes_to_the_new_day_at_midnight(
    found: list[tuple[Any, ...]], monkeypatch: pytest.MonkeyPatch
) -> None:
    async with user_simulation(app.root) as user:
        await user.open('/')
        await wait_for_calls(found, 1)
        [timer] = user.find(kind=ui.timer, marker='refresh').elements
        assert timer.callback is not None

        # Midnight: today is the next day.
        tomorrow = datetime.now(TZ).date() + timedelta(days=1)
        monkeypatch.setattr(app, 'today', lambda tz_name: tomorrow)
        await timer.callback()
        await wait_for_calls(found, 2)
        assert found[1][2] == tomorrow
        assert timer.active


async def test_load_again_keeps_the_chart(found: list[tuple[Any, ...]]) -> None:
    async with user_simulation(app.root) as user:
        await user.open('/')
        await user.should_see('Click a row to zoom the chart')
        [chart] = user.find(ui.echart).elements

        user.find(marker='reload').click()
        await wait_for_calls(found, 2)
        await asyncio.sleep(0.2)  # let the page apply the result
        await user.should_see('Click a row to zoom the chart')
        assert user.find(ui.echart).elements == {chart}


async def test_theme_switch(found: list[tuple[Any, ...]]) -> None:
    async with user_simulation(app.root) as user:
        await user.open('/')
        await user.should_see('Click a row to zoom the chart')
        [chart] = user.find(ui.echart).elements
        [dark] = user.find(ui.dark_mode).elements
        # Without ``theme`` in the configuration file, the page has the theme of the computer of the user.
        assert dark.value is None
        assert chart.options['series'][0]['lineStyle']['color'] == '#03a9f4'

        user.find(marker='theme').click()
        assert dark.value is True
        assert chart.options['series'][0]['lineStyle']['color'] == '#03a9f4'

    assert len(found) == 1


async def test_theme_of_the_file(found: list[tuple[Any, ...]]) -> None:
    Path('homebuddy.yml').write_text(f'{FILE}theme: dark\n')
    async with user_simulation(app.root) as user:
        await user.open('/')
        await user.should_see('Click a row to zoom the chart')
        [chart] = user.find(ui.echart).elements
        [dark] = user.find(ui.dark_mode).elements
        assert dark.value is True
        assert chart.options['series'][0]['lineStyle']['color'] == '#03a9f4'

        user.find(marker='theme').click()
        assert dark.value is False


async def test_day_without_data(found: list[tuple[Any, ...]]) -> None:
    async with user_simulation(app.root) as user:
        await user.open('/')
        [date_input] = user.find(ui.date).elements
        date_input.value = '2026-09-12'
        await user.should_see('No data for Saturday, 12 September 2026')
        await user.should_not_see('Total energy')


async def test_day_with_a_sensor_error(found: list[tuple[Any, ...]]) -> None:
    async with user_simulation(app.root) as user:
        await user.open('/')
        [date_input] = user.find(ui.date).elements
        date_input.value = '2026-09-11'
        await user.should_see('detectors.machine.energy_sensor: the unit of sensor.energy is `MJ`.')


async def test_page_without_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv('HA_TOKEN')
    Path('homebuddy.yml').write_text(FILE)

    async with user_simulation(app.root) as user:
        await user.open('/')
        await user.should_see('HA_TOKEN: Set it in the environment or in .env')


async def test_page_without_a_file(monkeypatch: pytest.MonkeyPatch) -> None:

    async with user_simulation(app.root) as user:
        await user.open('/')
        await user.should_see('No configuration file. Use --config, or make one of these files:')
        await user.should_see(str(Path('homebuddy.yml').resolve()))


def make_above_result() -> SearchResult:
    """The result of a detector type that the page does not know: one event at 13:05."""
    detector = Above(limit=50, sensor='sensor.t')
    start, end = datetime(2026, 9, 13, tzinfo=TZ), datetime(2026, 9, 14, tzinfo=TZ)
    points = make_points(datetime(2026, 9, 13, 13, 0, tzinfo=TZ), [(5, 20.0), (1, 60.0), (5, 20.0)], 60)
    history = make_history('sensor.t', points)
    return SearchResult(
        tz=TZ,
        start=start,
        end=end,
        detectors={**SETTINGS.detectors, 'hot': detector},
        points=points,
        history=history,
        found={'hot': detector.detect(history, start, end)},
        sensor='sensor.t',
        unit='°C',
        power=False,
        levels=detector.levels(history, start, end),
    )


def test_chart_options_of_a_new_detector_type() -> None:
    options = chart_options(make_above_result(), DATE_FORMAT)
    assert [(line['name'], line['yAxis']) for line in options['series'][0]['markLine']['data']] == [('Limit 50 °C', 50)]
    # The second detector of the settings has the second color.
    assert lane(options, 'hot') == ('#eb6834', [('2026-09-13 13:05:00', '2026-09-13 13:05:00')])


async def test_page_shows_a_new_detector_type(found: list[tuple[Any, ...]], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(search, 'find_day', lambda *args: [make_above_result()])
    async with user_simulation(app.root) as user:
        await user.open('/')
        await user.should_see('Click a row to zoom the chart')
        [table] = user.find(ui.table).elements
        assert [(row['detector'], row['label'], row['peak']) for row in table.rows] == [('hot', 'high', '60.0')]

        user.find(ui.switch).click()
        user.find(marker='reload').click()
        await user.should_see('Debug data of hot')
        await user.should_see('Peaks')


def test_copy_columns_are_the_ids_of_the_columns_of_the_tab(charge_w: float) -> None:
    power = ['detector', 'start', 'end', 'duration', 'label', 'power', 'energy']
    assert copy_columns(make_result(charge_w), None) == power
    air = make_air_result()
    assert copy_columns(air, None) == [*power[:5], 'start_value', 'peak']
    # ``copy_columns`` of the file accepts the ids of the columns of the two tabs, and no other id.
    assert set(get_args(CopyColumn)) == {*power, 'start_value', 'peak'}
    # The setting gives the columns and their order. A row has no value for a column that the tab does not have.
    assert copy_columns(air, ('peak', 'power', 'start_value')) == ['peak', 'power', 'start_value']
    [row] = event_rows(air, DATE_FORMAT)
    assert [row[name] for name in ('peak', 'power', 'start_value') if name in row] == ['56.0', '30.0']


async def test_file_without_a_time_zone(found: list[tuple[Any, ...]], monkeypatch: pytest.MonkeyPatch) -> None:
    # The day of this time zone is the day of UTC, or one day after it.
    zone = 'Pacific/Kiritimati'
    monkeypatch.setattr(HomeAssistant, 'timezone', lambda self: zone)
    Path('homebuddy.yml').write_text(FILE.replace('timezone: Europe/Berlin\n', ''))
    async with user_simulation(app.root) as user:
        await user.open('/')
        await user.should_see('Click a row to zoom the chart')
        [date_input] = user.find(ui.date).elements
        # The page opens on today of Home Assistant, not on today of the computer.
        assert date_input.value == datetime.now(ZoneInfo(zone)).date().isoformat()
        [next_button] = user.find(kind=ui.button, marker='next').elements
        assert not next_button.enabled

    settings, _, day = found[-1]
    assert (settings.timezone, day) == (None, datetime.now(ZoneInfo(zone)).date())


async def test_wrong_time_zone_of_the_file(found: list[tuple[Any, ...]]) -> None:
    Path('homebuddy.yml').write_text(FILE.replace('Europe/Berlin', 'No/Such_Zone'))
    async with user_simulation(app.root) as user:
        await user.open('/')
        await user.should_see('No/Such_Zone')
    assert found == []


async def test_the_page_reads_the_file_when_it_opens_and_at_load_again(found: list[tuple[Any, ...]]) -> None:
    async with user_simulation(app.root) as user:
        await user.open('/')
        await wait_for_calls(found, 1)

        # A load of a different day, as a load of the timer, uses the settings that the page has.
        Path('homebuddy.yml').write_text(
            FILE.replace('levels_w: [4140, 11040]', 'levels_w: [4140, 11040], tolerance: 0.2')
        )
        [date_input] = user.find(ui.date).elements
        date_input.value = '2026-09-14'
        await wait_for_calls(found, 2)
        assert found[1][0].detectors['ev'].tolerance == 0.1

        user.find(marker='reload').click()
        await wait_for_calls(found, 3)
        assert found[2][0].detectors['ev'].tolerance == 0.2


async def test_load_again_after_a_correction_of_the_file(found: list[tuple[Any, ...]]) -> None:
    Path('homebuddy.yml').write_text('detectors: {ev: {type: level, tolerance: 2}}\n')
    async with user_simulation(app.root) as user:
        await user.open('/')
        await user.should_see('must be a number between 0 and 1')

        # A different day still shows the errors of the file.
        [date_input] = user.find(ui.date).elements
        date_input.value = '2026-09-14'
        await user.should_see('must be a number between 0 and 1')
        assert found == []

        Path('homebuddy.yml').write_text(FILE)
        user.find(marker='reload').click()
        await user.should_see('Click a row to zoom the chart')
        await user.should_not_see('must be a number between 0 and 1')


def test_homebuddy_reads_the_env_file_one_time_when_it_starts(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(app, 'load_dotenv', lambda path: calls.append('env'))
    monkeypatch.setattr(ui, 'run', lambda *args, **kwargs: calls.append('run'))
    app.run(host='127.0.0.1', port=8080, native=False, show=False)
    assert calls == ['env', 'run']


def test_homebuddy_reads_the_env_file_of_the_current_folder(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    # The current folder of a test is tmp_path. It is not in the source tree.
    monkeypatch.delenv('HOMEBUDDY_TEST_VALUE', raising=False)
    (tmp_path / '.env').write_text('HOMEBUDDY_TEST_VALUE=from the file\n')
    monkeypatch.setattr(ui, 'run', lambda *args, **kwargs: None)
    app.run(host='127.0.0.1', port=8080, native=False, show=False)
    assert os.environ.get('HOMEBUDDY_TEST_VALUE') == 'from the file'


def test_smoothed() -> None:
    start = datetime(2026, 9, 13, 12, 0, tzinfo=TZ)
    minute = timedelta(minutes=1)
    # 1000 W for 1 minute, then 0 W for 4 minutes, then 600 W. The time of a value is its weight.
    points = [(start, 1000.0), (start + minute, 0.0), (start + 5 * minute, 600.0), (start + 10 * minute, 600.0)]
    assert smoothed(points, 5 * minute) == [(start + 2.5 * minute, 200.0), (start + 7.5 * minute, 600.0)]
    assert smoothed(points[:1], 5 * minute) == points[:1]
    assert smoothed([], 5 * minute) == []


def test_a_line_with_smooth_shows_averages(charge_w: float) -> None:
    result = make_result(charge_w)
    plain = chart_options(result, DATE_FORMAT)['series'][0]
    entry = TabSensor(sensor='sensor.p', smooth=timedelta(minutes=10))
    smooth = chart_options(result, DATE_FORMAT, entries=[entry])['series'][0]
    assert (plain['step'], smooth['step']) == ('end', False)
    assert len(smooth['data']) < len(plain['data'])
    # The settings give the keys of each line of the tab of a result.
    tab = Tab(sensors=(entry, TabSensor(sensor='sensor.q')))
    settings = SETTINGS.model_copy(update={'tabs': {result.tab: tab}})
    assert tab_lines(result, settings) == tab.sensors
