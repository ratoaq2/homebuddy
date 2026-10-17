"""Search of the history of the sensors: each detector reads its sensors, and each tab gets a result."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, datetime, time, timedelta
from typing import Protocol
from zoneinfo import ZoneInfo

from homebuddy.config import Settings
from homebuddy.conflicts import solve_conflicts
from homebuddy.model import Event, History, Reading, SensorError
from homebuddy.result import Line, SearchResult

# Constants
DAY_MARGIN_HOURS = 12


class NoDataError(Exception):
    """The source has no history for the search window."""


class Source(Protocol):
    """Where the search gets its data. ``homebuddy.homeassistant.HomeAssistant`` is one source."""

    def history(self, sensors: Sequence[str], start: datetime, end: datetime) -> Mapping[str, Sequence[Reading]]:
        """Each state of each sensor from ``start`` to ``end``, in the order of time. Each sensor is a key."""

    def unit(self, sensor: str) -> str:
        """The unit of the sensor, for example ``kW``. It is empty for a sensor without a unit."""

    def is_power(self, sensor: str) -> bool:
        """True for a power sensor."""

    def name(self, sensor: str) -> str:
        """The name of the sensor for the page. It is empty for a sensor without a name."""

    def timezone(self) -> str:
        """The time zone of the home, for example ``Europe/Berlin``."""


def timezone(settings: Settings, source: Source) -> ZoneInfo:
    """The time zone of the search: ``timezone`` of the settings, or the time zone of the source without it."""
    return ZoneInfo(settings.timezone or source.timezone())


def tab_detectors(settings: Settings, tab: str, power: bool) -> list[str]:
    """The names of the detectors that a tab shows, in the order of its lanes.

    They are the detectors of the tab in the configuration file. Without them, the tab of a power sensor
    shows each detector: each device of the house is behind the meter. A tab of a different sensor shows
    the detectors that read its sensor.
    """
    rules = settings.tabs[tab]
    if rules.detectors is not None:
        return list(rules.detectors)
    return [
        name for name, detector in settings.detectors.items() if power or rules.sensors[0].sensor in detector.sensors
    ]


def find(
    settings: Settings,
    source: Source,
    start: datetime,
    end: datetime,
    now: datetime,
    margin: timedelta = timedelta(0),
) -> list[SearchResult]:
    """The search from ``start`` to ``end``: one result for each tab, in the order of the tabs.

    The data comes from ``source``. Each detector reads its sensors. See ``Detector.sensors``. The result of a
    tab has the events of the detectors of the tab. See ``tab_detectors``. A tab whose first sensor has no
    numbers from ``start`` to ``end`` gives no result. Each other sensor of a tab is one more line of its chart.
    A sensor of a tab without the class and the unit of the first one gives a ``SensorError``.
    The search also loads ``margin`` before and after, so an event that crosses a limit keeps its real start
    and end.
    An event that loses a conflict is not in the result. See ``solve_conflicts``.
    A ``SensorError`` of a detector gets the path of the key of the detector.
    """
    detectors = settings.detectors
    charts = {tab: rules.sensors[0].sensor for tab, rules in settings.tabs.items()}
    lines = [entry.sensor for rules in settings.tabs.values() for entry in rules.sensors]
    read = dict.fromkeys([*lines, *(s for detector in detectors.values() for s in detector.sensors)])
    history = History(
        dict(source.history(list(read), start - margin, min(end + margin, now))),
        {sensor: source.unit(sensor) for sensor in read},
    )
    points = {sensor: history.numbers(sensor) for sensor in dict.fromkeys(lines)}
    shown = {tab: sensor for tab, sensor in charts.items() if any(start <= t <= end for t, _ in points[sensor])}
    if not shown:
        raise NoDataError('No history data returned for that window.')

    # What each detector finds in the search, from its sensors
    found: dict[str, Sequence[Event]] = {}
    for name, detector in detectors.items():
        try:
            found[name] = [d for d in detector.detect(history, start, end) if d.start < end and d.end > start]
        except SensorError as e:
            raise SensorError(f'detectors.{name}.{e}') from e
    accepted = {name: [d for d in events if d.accepted] for name, events in found.items()}
    conflicts = solve_conflicts(accepted, {name: detector.overrides for name, detector in detectors.items()})
    lost = {(c.detector, c.start, c.end) for c in conflicts}
    found = {name: [d for d in events if (name, d.start, d.end) not in lost] for name, events in found.items()}
    tz = timezone(settings, source)

    def unit(sensor: str) -> str:
        # The points of a power sensor are in watts.
        return 'W' if source.is_power(sensor) else history.unit(sensor)

    results = []
    for tab, sensor in shown.items():
        power = source.is_power(sensor)
        names = tab_detectors(settings, tab, power)
        # The lines of a chart have one axis, so each sensor of a tab has the class and the unit of the first one.
        others = [entry.sensor for entry in settings.tabs[tab].sensors]
        for i, other in enumerate(others):
            if (source.is_power(other), unit(other)) != (power, unit(sensor)):
                raise SensorError(f'tabs.{tab}.sensors.{i}: {other} does not have the class and the unit of {sensor}')
        results.append(
            SearchResult(
                tz=tz,
                start=start,
                end=end,
                detectors=detectors,
                points=points[sensor],
                history=history,
                found={name: found[name] for name in names},
                tab=tab,
                tab_name=settings.tabs[tab].name or '',
                sensor=sensor,
                sensor_name=source.name(sensor),
                unit=unit(sensor),
                power=power,
                lines=[Line(other, source.name(other), points[other]) for other in others[1:]],
                # The levels of a detector are for the sensor that it reads.
                levels={
                    name: level
                    for detector in map(detectors.__getitem__, names)
                    if detector.sensors[:1] == (sensor,)
                    for name, level in detector.levels(history, start, end).items()
                },
                conflicts=[c for c in conflicts if c.detector in names],
            )
        )
    return results


def find_day(settings: Settings, source: Source, day: date, now: datetime | None = None) -> list[SearchResult]:
    """The search of one calendar day in the time zone of the search, with a margin. See ``timezone`` and ``find``."""
    tz = timezone(settings, source)
    now = now or datetime.now(tz)
    start = datetime.combine(day, time.min, tzinfo=tz)
    end = min(datetime.combine(day + timedelta(days=1), time.min, tzinfo=tz), now)
    return find(settings, source, start, end, now, timedelta(hours=DAY_MARGIN_HOURS))
