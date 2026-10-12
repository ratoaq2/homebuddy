"""The result of a search for one tab of the page: the events of its detectors, with numbers."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import NamedTuple
from zoneinfo import ZoneInfo

from homebuddy.conflicts import Conflict
from homebuddy.detector import Detector
from homebuddy.model import Event, History, Point

# The estimate of the power of an event uses the power of this time before the event.
BEFORE_EVENT = timedelta(minutes=5)


class Row(NamedTuple):
    """An event of a detector in a tab, with the values of the sensor of the tab. A value can be None.

    A power tab gives ``power_kw`` and ``energy_kwh``. A different tab gives ``start_value`` and ``peak``,
    in the unit of its sensor. The page makes the text of each value.
    """

    detector: str
    start: datetime
    end: datetime
    label: str
    power_kw: float | None = None
    energy_kwh: float | None = None
    start_value: float | None = None  # The value of the sensor at the start of the event
    peak: float | None = None  # The largest value of the sensor in the event


class Line(NamedTuple):
    """One more line of the chart of a tab: a sensor of the tab after the first one."""

    sensor: str
    name: str  # The name of the sensor in the source
    points: list[Point]  # In the unit of the points of the tab


@dataclass(frozen=True)
class SearchResult:
    """Everything a search produced for one tab of the page.

    ``start`` and ``end`` are the limits of the search. ``points`` can also have the margin that a day
    search loads before and after them. The result has no settings and no token.
    """

    tz: ZoneInfo
    start: datetime
    end: datetime
    points: list[Point]
    # The detectors of the configuration file, by name, in the order of the file
    detectors: Mapping[str, Detector] = field(default_factory=dict)
    # The history of each sensor of the search. The debug data of a detector reads it.
    history: History = History({})
    # What each detector of the tab found, by the name of the detector, in the order of the lanes
    found: dict[str, Sequence[Event]] = field(default_factory=dict)
    tab: str = ''  # The id of the tab
    tab_name: str = ''  # The name of the tab in the configuration file
    sensor: str = ''  # The sensor of the points
    sensor_name: str = ''  # The name of the sensor in the source
    unit: str = 'W'  # The unit of the points. It is W for a power sensor.
    power: bool = True  # True for a power sensor
    # The other sensors of the tab, in the order of the file. The events and the levels do not use them.
    lines: Sequence[Line] = ()
    # The levels of the sensor, by name, from the detectors that read it. The chart shows a line for each one.
    levels: dict[str, float] = field(default_factory=dict)
    conflicts: list[Conflict] = field(default_factory=list)  # The events that the search removed

    @property
    def accepted(self) -> dict[str, list[Event]]:
        """The events of each detector, without the candidates that its rules refuse."""
        return {name: [d for d in found if d.accepted] for name, found in self.found.items()}

    def start_and_peak(self, start: datetime, end: datetime) -> tuple[float | None, float | None]:
        """The value of the sensor at the start of an event, and its largest value in the event."""
        first = [p for t, p in self.points if t <= start][-1:]
        # The end of a run can be its peak, so the end is in the range.
        peak = max(first + [p for t, p in self.points if start <= t <= end], default=None)
        return (first[0] if first else None, peak)

    def power_kw(self, name: str, found: Event) -> float | None:
        """The power of an event of a detector. None for a sensor that is not a power sensor, or without data.

        A detector can know the power of its events. Without a known power, it is the average power in the
        event, minus the average power of the 5 minutes before it.
        Without a known power, it is None for a detector type without an estimate. See
        ``Detector.estimate_power``.
        """
        if not self.power:
            return None
        if found.power_w is not None:
            return found.power_w / 1000
        if not self.detectors[name].estimate_power:
            return None
        inside = [p for t, p in self.points if found.start <= t < found.end]
        before = [p for t, p in self.points if found.start - BEFORE_EVENT <= t < found.start]
        if not inside or not before:
            return None
        return (sum(inside) / len(inside) - sum(before) / len(before)) / 1000

    def energy(self, name: str, found: Event) -> float | None:
        """The energy of an event of a detector, in kWh. None for a sensor that is not a power sensor.

        A detector can know the energy of its events. Without a known energy, it is the power of the event for
        its duration.
        """
        if not self.power:
            return None
        if found.energy_kwh is not None:
            return found.energy_kwh
        power_kw = self.power_kw(name, found)
        return None if power_kw is None else power_kw * (found.end - found.start).total_seconds() / 3600

    @property
    def energy_kwh(self) -> dict[str, float]:
        """The energy of the events of each detector that has an event with an energy. Empty without a power sensor."""
        total: dict[str, float] = {}
        for name, found in self.accepted.items():
            for d in found:
                energy = self.energy(name, d)
                if energy is not None:
                    total[name] = total.get(name, 0) + energy
        return total

    @property
    def events(self) -> list[Row]:
        """The events of each detector, in the order of time, with the values of this sensor.

        A power sensor gives the power of the event and its energy. A different sensor gives its value at the
        start and its largest value in the event.
        """
        events = []
        for name, found in self.accepted.items():
            for d in found:
                row = Row(name, d.start, d.end, d.label)
                if self.power:
                    row = row._replace(power_kw=self.power_kw(name, d), energy_kwh=self.energy(name, d))
                else:
                    start_value, peak = self.start_and_peak(d.start, d.end)
                    row = row._replace(start_value=start_value, peak=peak)
                events.append(row)
        return sorted(events, key=lambda e: e.start)
