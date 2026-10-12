"""The data of homebuddy: the history of the sensors, and the events that the detectors find in it."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import KW_ONLY, dataclass, field
from datetime import datetime

Point = tuple[datetime, float]
# A state of a sensor as Home Assistant gives it: a number as a text, or a text.
Reading = tuple[datetime, str]


def numbers(readings: Sequence[Reading]) -> list[Point]:
    """The readings that are numbers."""
    points = []
    for t, state in readings:
        try:
            points.append((t, float(state)))
        except ValueError:
            continue
    return points


@dataclass(frozen=True)
class History:
    """The history of each sensor that the search loaded. A detector reads its sensors from it."""

    states: Mapping[str, Sequence[Reading]]
    # The unit of each sensor in Home Assistant
    units: Mapping[str, str] = field(default_factory=dict)

    def readings(self, sensor: str) -> Sequence[Reading]:
        """Each state of the sensor, also a state that is not a number."""
        return self.states[sensor]

    def unit(self, sensor: str) -> str:
        """The unit of the sensor in Home Assistant. It is empty for a sensor without a unit."""
        return self.units.get(sensor, '')

    def numbers(self, sensor: str) -> list[Point]:
        """The states of the sensor that are numbers. A sensor in kW gives watts."""
        points = numbers(self.states[sensor])
        return [(t, value * 1000) for t, value in points] if self.unit(sensor) == 'kW' else points


# A value of the debug data. The page makes its text. A time shows in the time zone of the page.
Value = datetime | float | str


@dataclass(frozen=True)
class Table:
    """A block of the debug data of a detector: the titles of its columns, and the values of each row."""

    columns: tuple[str, ...]
    rows: Sequence[tuple[Value, ...]]


class SensorError(Exception):
    """A sensor does not have what a detector needs. The text starts with the key of the detector."""


@dataclass(frozen=True)
class Event:
    """What a detector found: a time with a start and an end. Each other field is optional, and has a keyword.

    A type that needs more data for its debug list makes a subclass with its own fields.
    """

    start: datetime
    end: datetime
    _: KW_ONLY
    label: str = ''  # The label of the event in the chart and in the table, for example "16 A"
    power_w: float | None = None  # When the detector knows the power of the event
    energy_kwh: float | None = None  # When the detector knows the energy of the event
    accepted: bool = True  # False for a candidate that the rules refuse. Only the debug list shows it.
