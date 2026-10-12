from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, NamedTuple
from zoneinfo import ZoneInfo

import pytest

from homebuddy.config import Server, Settings, Tab, TabSensor
from homebuddy.detector import Detector
from homebuddy.detectors.level import Level
from homebuddy.model import History, Point, Reading
from homebuddy.result import Row

TZ = ZoneInfo('Europe/Berlin')
UTC = ZoneInfo('UTC')
BASELINE_W = 500.0
# The levels of the level detector of the tests, in watts, by the current of a charger with 3 phases at 230 V
LEVELS = {current: 3 * 230.0 * current for current in (6, 8, 10, 12, 16)}
# The level detector of the tests: a car at that charger
EV = Level(levels_w=tuple(LEVELS.values()), sensor='sensor.p')
# The duration range of the pulse detector of the tests
DURATION = (timedelta(seconds=30), timedelta(seconds=90))


class Info(NamedTuple):
    """What a source knows of a sensor: its unit, if it is a power sensor, and its name."""

    unit: str = ''
    power: bool = False
    name: str = ''


# A power sensor in W
POWER = Info('W', power=True)
# The tab of the files of the tests, as text and as settings
TABS_YAML = 'tabs: {power: {sensors: [sensor.p]}}\n'
TABS = {'power': Tab(sensors=(TabSensor(sensor='sensor.p'),))}


def entries(*sensors: str) -> tuple[TabSensor, ...]:
    """The sensors of a tab, each one without more keys."""
    return tuple(TabSensor(sensor=sensor) for sensor in sensors)


SETTINGS = Settings(home_assistant=Server(url='http://ha'), timezone='Europe/Berlin', tabs=TABS, detectors={'ev': EV})


def with_detectors(tabs: dict[str, Tab] = TABS, **detectors: Detector) -> Settings:
    """``SETTINGS`` with these detectors and tabs. A detector with the name ``ev`` replaces the EV detector."""
    return SETTINGS.model_copy(update={'detectors': {**SETTINGS.detectors, **detectors}, 'tabs': tabs})


@dataclass
class FakeSource:
    """A data source of the search.

    ``states`` has the history of each sensor by its entity id, or one history for each sensor. Each sensor
    is a power sensor in W. A test that needs a different sensor sets ``sensor_info``.
    ``zone`` is the time zone of the source.
    With ``window``, the source gives only the states from the start to the end of the call.
    """

    states: Any
    sensor_info: Callable[[str], Info] = lambda sensor: POWER
    window: bool = False
    zone: str = 'UTC'
    # The number of times that the search asked for the time zone
    zone_calls: int = 0
    calls: list[tuple[str, datetime, datetime]] = field(default_factory=list)

    def history(self, sensor: str, start: datetime, end: datetime) -> list[Reading]:
        self.calls.append((sensor, start, end))
        found: list[Reading] = self.states[sensor] if isinstance(self.states, dict) else self.states
        return [state for state in found if start <= state[0] <= end] if self.window else found

    def unit(self, sensor: str) -> str:
        return self.sensor_info(sensor).unit

    def is_power(self, sensor: str) -> bool:
        return self.sensor_info(sensor).power

    def name(self, sensor: str) -> str:
        return self.sensor_info(sensor).name

    def timezone(self) -> str:
        self.zone_calls += 1
        return self.zone


def rounded(row: Row) -> tuple[float | None, ...]:
    """The values of a row, with 2 decimals: the power, the energy, the value at the start and the peak."""
    return tuple(None if value is None else round(value, 2) for value in row[4:])


def make_history(sensor: str, points: list[Point]) -> History:
    """The history of one sensor, with each value as a text, as Home Assistant gives it."""
    return History({sensor: [(t, str(value)) for t, value in points]})


def make_points(start: datetime, profile: list[tuple[int, float]], step_s: int = 30) -> list[Point]:
    """Build points from ``(count, power_w)`` runs, one point every ``step_s`` seconds."""
    points: list[Point] = []
    ts = start
    for count, power in profile:
        for _ in range(count):
            points.append((ts, power))
            ts += timedelta(seconds=step_s)
    return points


def make_two_car_day(peak_start_min: int = 214, peak_min: int = 18) -> list[Point]:
    """One point each minute: a 6 A charge from 10:00 to 14:30, then an 8 A charge from 14:33 to 19:09.

    House peaks sit on top of the two charges. ``peak_start_min`` and ``peak_min`` place the peak
    in the 8 A charge, in minutes after 14:33.
    """
    house, six, eight = 400.0, 4540.0, 5920.0
    profile = [
        (375, house),
        (10, 3400.0),
        (215, house),
        (5, 6300.0),
        (95, six),
        (5, 7600.0),
        (15, six),
        (5, 6500.0),
        (145, six),
        (3, 2700.0),
        (peak_start_min, eight),
        (peak_min, 7400.0),
        (276 - peak_start_min - peak_min, eight),
        (20, house),
    ]
    return make_points(datetime(2026, 10, 4, tzinfo=TZ), profile, step_s=60)


@pytest.fixture
def day_start() -> datetime:
    return datetime(2026, 9, 13, 0, 0, tzinfo=TZ)


@pytest.fixture
def charge_w() -> float:
    return BASELINE_W + LEVELS[16]


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    # The environment has a token. A test of a missing token removes it.
    monkeypatch.setenv('HA_TOKEN', 'tok')
    # Keep the repo .env, the repo homebuddy.yml and the user configuration out of the tests.
    monkeypatch.setattr('homebuddy.config.user_config_dir', lambda name: str(tmp_path / 'user'))
    monkeypatch.chdir(tmp_path)
