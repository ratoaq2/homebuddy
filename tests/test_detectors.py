from __future__ import annotations

from collections.abc import Iterator, Sequence
from datetime import datetime, timedelta
from importlib.metadata import EntryPoint
from pathlib import Path
from typing import Any

import pytest
from pydantic import TypeAdapter, ValidationError

from homebuddy import detectors
from homebuddy.config import ConfigError, load_settings
from homebuddy.detector import Detector
from homebuddy.detectors.pulse import Pulse
from homebuddy.fields import Duration, DurationRange, Positive, Sensor, Text
from homebuddy.model import Event, History, Table
from homebuddy.search import find_day
from tests.conftest import BASELINE_W, TABS_YAML, TZ, FakeSource, Info, make_points, with_detectors


class Above(Detector):
    """A detector type of a different package: each point above ``limit`` is an event."""

    sensor: Sensor
    limit: Positive

    def detect(self, data: History, start: datetime, end: datetime) -> list[Event]:
        return [Event(t, t, label='high') for t, value in data.numbers(self.sensor) if value > self.limit]

    def levels(self, data: History, start: datetime, end: datetime) -> dict[str, float]:
        return {'Limit': self.limit}

    def debug(self, found: Sequence[Event], data: History) -> dict[str, Table]:
        return {'Peaks': Table(('Time', 'Limit'), [(peak.start, self.limit) for peak in found])}


class Plain:
    """A class of a different package that is not a detector type."""


class Word(Detector):
    """A type that reads texts: an event from each ``word`` of ``sensor`` to the next state of ``until``."""

    sensor: Sensor
    word: Text
    until: Sensor

    def detect(self, data: History, start: datetime, end: datetime) -> list[Event]:
        return [
            Event(t, next(after for after, _ in data.readings(self.until) if after > t))
            for t, state in data.readings(self.sensor)
            if state == self.word
        ]


@pytest.fixture
def plugins(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """The entry points of a package that adds the type ``above``, its own ``pulse`` and two wrong types."""
    entry_points = [
        EntryPoint('above', f'{__name__}:Above', detectors.DETECTOR_ENTRY_POINTS),
        EntryPoint('pulse', f'{__name__}:Above', detectors.DETECTOR_ENTRY_POINTS),
        EntryPoint('missing', 'no_such_package.above:Above', detectors.DETECTOR_ENTRY_POINTS),
        EntryPoint('plain', f'{__name__}:Plain', detectors.DETECTOR_ENTRY_POINTS),
    ]
    monkeypatch.setattr(detectors, 'entry_points', lambda group: entry_points)
    detectors.detector_types.cache_clear()
    yield
    detectors.detector_types.cache_clear()


def test_a_package_adds_a_detector_type(plugins: None, caplog: pytest.LogCaptureFixture) -> None:
    types = detectors.detector_types()
    assert types['above'] is Above
    # A built-in type wins over a type with the same name. The log has a warning.
    assert types['pulse'] is Pulse
    assert [record.getMessage() for record in caplog.records] == [
        f'The detector type `pulse` of `{__name__}:Above` has the name of a built-in type. '
        'homebuddy uses the built-in type.'
    ]


@pytest.mark.parametrize(
    ('kind', 'error'),
    [
        (
            'missing',
            'detectors.hot.type: Cannot load the detector type `missing` of `no_such_package.above:Above`: '
            "No module named 'no_such_package'",
        ),
        (
            'plain',
            f'detectors.hot.type: The detector type `plain` of `{__name__}:Plain` must be a subclass of '
            'homebuddy.detector.Detector',
        ),
    ],
)
def test_a_wrong_type_of_a_package_gives_a_message(plugins: None, tmp_path: Path, kind: str, error: str) -> None:
    (tmp_path / 'homebuddy.yml').write_text(
        f'home_assistant:\n  url: http://ha\ntimezone: UTC\n{TABS_YAML}'
        f'detectors: {{hot: {{type: {kind}, sensor: sensor.t, limit: 50}}}}\n'
    )
    with pytest.raises(ConfigError) as e:
        load_settings()
    assert str(e.value).splitlines()[1:] == [error]


def test_the_search_uses_a_type_of_a_package(plugins: None, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / 'homebuddy.yml').write_text(
        'home_assistant:\n  url: http://ha\ntimezone: UTC\ntabs: {heat: {sensors: [sensor.t]}}\n'
        'detectors: {hot: {type: above, sensor: sensor.t, limit: 50}}\n'
    )
    settings = load_settings()
    assert settings.detectors['hot'] == Above(limit=50, sensor='sensor.t')

    history: dict[str, list[Any]] = {
        'sensor.grid_power': [],
        'sensor.t': make_points(datetime(2026, 9, 13, 8, 0, tzinfo=TZ), [(5, 20.0), (1, 60.0), (5, 20.0)], 60),
    }
    source = FakeSource(history)
    source.sensor_info = lambda sensor: Info('°C')
    [result] = find_day(settings, source, datetime(2026, 9, 13).date(), now=datetime(2026, 9, 14, 12, 0, tzinfo=TZ))
    assert [(e.detector, f'{e.start:%H:%M}', e.label) for e in result.events] == [('hot', '08:05', 'high')]


def test_a_necessary_key_of_a_type_of_a_package(plugins: None, tmp_path: Path) -> None:
    (tmp_path / 'homebuddy.yml').write_text(
        'home_assistant:\n  url: http://ha\ntimezone: UTC\n'
        + TABS_YAML
        + 'detectors: {hot: {type: above, limit: 50}}\n'
    )
    with pytest.raises(ConfigError, match='detectors.hot.sensor: Field required'):
        load_settings()


def test_a_type_with_two_sensor_fields_reads_the_two_sensors(monkeypatch: pytest.MonkeyPatch) -> None:
    day = datetime(2026, 9, 13, 8, 0, tzinfo=TZ)
    history: dict[str, list[Any]] = {
        'sensor.p': make_points(day, [(60, BASELINE_W)], 60),
        'sensor.door': [(day.replace(minute=10), 'closed'), (day.replace(minute=20), 'open')],
        'sensor.bell': [(day, 'off'), (day.replace(minute=25), 'on')],
    }
    source = FakeSource(history)
    door = Word(sensor='sensor.door', word='open', until='sensor.bell')
    assert door.sensors == ('sensor.door', 'sensor.bell')

    # The door sensor and the bell sensor are not in a tab: only the power sensor has a result.
    settings = with_detectors(door=door)
    [result] = find_day(settings, source, day.date(), now=datetime(2026, 9, 14, 12, 0, tzinfo=TZ))
    assert result.sensor == 'sensor.p'
    assert [(e.detector, f'{e.start:%H:%M}', f'{e.end:%H:%M}') for e in result.events] == [('door', '08:20', '08:25')]
    # The search loads each sensor one time.
    assert sorted(sensor for sensor, _, _ in source.calls) == ['sensor.bell', 'sensor.door', 'sensor.p']


@pytest.mark.parametrize(
    ('value', 'expected'),
    [
        (90, timedelta(seconds=90)),
        (1.5, timedelta(seconds=1.5)),
        ('01:30:00', timedelta(hours=1, minutes=30)),
        ({'hours': 1, 'minutes': 30}, timedelta(hours=1, minutes=30)),
        ({'days': 1, 'seconds': 5}, timedelta(days=1, seconds=5)),
    ],
)
def test_a_duration_is_a_number_of_seconds_or_a_text_or_a_map(value: object, expected: timedelta) -> None:
    assert TypeAdapter(Duration).validate_python(value) == expected


@pytest.mark.parametrize(
    ('value', 'error'),
    [
        (0, 'must be more than 0'),
        ('00:00:00', 'must be more than 0'),
        ({'minutes': -5}, 'must be more than 0'),
        (True, 'must be a number of seconds, a text HH:MM:SS, or a map with days, hours, minutes, seconds'),
        ('90', 'must be a number of seconds'),
        ('00:75:00', 'must be a number of seconds'),
        ({}, 'must be a number of seconds'),
        ({'weeks': 1}, 'must be a number of seconds'),
        ({'minutes': '5'}, 'must be a number of seconds'),
        ([5], 'must be a number of seconds'),
    ],
)
def test_a_wrong_duration(value: object, error: str) -> None:
    with pytest.raises(ValidationError, match=error):
        TypeAdapter(Duration).validate_python(value)


def test_the_short_duration_of_a_range_is_first() -> None:
    assert TypeAdapter(DurationRange).validate_python([30, {'minutes': 2}]) == (
        timedelta(seconds=30),
        timedelta(minutes=2),
    )
    with pytest.raises(ValidationError, match='the low value must be first'):
        TypeAdapter(DurationRange).validate_python([90, 30])
