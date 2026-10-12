"""The base of the detector types. A detector finds one type of event in the history of a sensor."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import ClassVar, get_args

from pydantic import BaseModel, ConfigDict
from pydantic.fields import FieldInfo

from homebuddy.fields import SENSOR, Text
from homebuddy.model import Event, History, Table


def _is_sensor(field: FieldInfo) -> bool:
    """True for a field with the type ``Sensor`` or ``Sensor | None``."""
    return SENSOR in field.metadata or any(
        SENSOR in getattr(part, '__metadata__', ()) for part in get_args(field.annotation)
    )


class Detector(BaseModel):
    """The rules of a detector. ``homebuddy.detectors.DETECTORS`` has the built-in types.

    A detector type is a pydantic model that has this class as its base. Its fields are the keys of the
    detector in the configuration file, and the type of a field is its check. A field without a default is
    a necessary key. A list of the file is a tuple in the field. A key that is not a field is an error.

    A field with the type ``Sensor`` is an input of the detector: homebuddy loads the history of that sensor.
    """

    model_config = ConfigDict(frozen=True, extra='forbid')

    # The name of the detector for the page. Without it, the page shows the name of the detector in the file.
    name: Text | None = None
    # The names of other detectors. An event of this detector removes the same event of each one of them.
    overrides: tuple[Text, ...] = ()
    # False for a type whose events have no estimate of their power. In a power tab, homebuddy estimates the
    # power of an event without a known power from the sensor of the tab.
    estimate_power: ClassVar[bool] = True

    @property
    def sensors(self) -> tuple[str, ...]:
        """The sensors that the detector reads: the value of each ``Sensor`` field, in the order of the fields."""
        fields = type(self).model_fields
        values = (getattr(self, name) for name, field in fields.items() if _is_sensor(field))
        return tuple(value for value in values if value is not None)

    def detect(self, data: History, start: datetime, end: datetime) -> Sequence[Event]:
        """What the detector finds in the history of ``sensors``.

        ``start`` and ``end`` are the limits of the search. ``data`` can also have a margin before and after
        them, so an event that crosses a limit keeps its real start and end.
        """
        raise NotImplementedError

    def levels(self, data: History, start: datetime, end: datetime) -> dict[str, float]:
        """The levels of the first sensor that the detector uses, by name. The chart shows a line for each one."""
        return {}

    def debug(self, found: Sequence[Event], data: History) -> dict[str, Table]:
        """The debug data of the search: tables of values, by the title of the table.

        ``found`` also has the candidates that the rules refuse. A table has values and no text of a value:
        the page makes the text of a time and of a number.
        """
        return {}
