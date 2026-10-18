"""State detector.

Finds a run of a device in a sensor that shows a text, for example the state of a washing machine. The energy of
a run comes from an energy sensor of the device, not from a power sensor.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from datetime import datetime, timedelta
from typing import ClassVar

from homebuddy.detector import Detector
from homebuddy.fields import Entities, Sensor, Text
from homebuddy.model import Event, History, Reading, SensorError

# The states of Home Assistant for a sensor without a value. They do not change the state of the device.
NO_VALUE = ('unavailable', 'unknown')
# The energy sensor can get the energy of a run some moments after the end of the run.
AFTER_RUN = timedelta(minutes=1)
# The units of an energy sensor, with the number of each unit in 1 kWh
ENERGY_UNITS = {'kWh': 1, 'Wh': 1000}


class State(Detector):
    """The rules of a ``state`` detector: a device runs when the state of its sensor is not an idle state."""

    sensor: Sensor  # The sensor that shows the state of the device as a text
    idle_states: Entities  # The states of the sensor when the device does not run
    energy_sensor: Sensor | None = None  # The sensor with the energy of a run, in kWh or Wh
    labels: dict[Text, Text] = {}  # The label of a run, by its first state. Other runs show their first state.

    estimate_power: ClassVar[bool] = False

    def detect(self, data: History, start: datetime, end: datetime) -> list[Event]:
        energy = []
        if self.energy_sensor:
            unit = data.unit(self.energy_sensor)
            if unit not in ENERGY_UNITS:
                raise SensorError(f'energy_sensor: the unit of {self.energy_sensor} is `{unit}`. It must be kWh or Wh.')
            energy = [(t, value / ENERGY_UNITS[unit]) for t, value in data.numbers(self.energy_sensor)]
        return [
            replace(
                run,
                label=self.labels.get(run.label, run.label),
                energy_kwh=run_energy([v for t, v in energy if run.start <= t <= run.end + AFTER_RUN]),
            )
            for run in runs(data.readings(self.sensor), self.idle_states, end)
        ]


def runs(readings: Sequence[Reading], idle: Sequence[str], end: datetime) -> list[Event]:
    """Each run, from the first state that is not idle to the next idle state. Its label is its first state.

    A change between two states that are not idle continues the run.

    A run without an end is in progress. It stops at ``end``, the limit of the search.
    """
    result: list[Event] = []
    first: Reading | None = None
    for t, state in readings:
        if state in NO_VALUE:
            continue
        if first is None and state not in idle:
            first = (t, state)
        elif first is not None and state in idle:
            result.append(Event(first[0], t, label=first[1]))
            first = None
    if first is not None and first[0] < end:
        result.append(Event(first[0], end, label=first[1]))
    return result


def run_energy(values: Sequence[float]) -> float | None:
    """The energy of a run from the values of the energy sensor in the run: the last value that is not 0.

    Some devices set the sensor to 0 at the end of a run. None without a value.
    """
    return next((v for v in reversed(values) if v), values[-1] if values else None)
