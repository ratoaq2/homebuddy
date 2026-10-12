"""The types of the fields of the configuration file. The type of a field is its check."""

from __future__ import annotations

import re
from datetime import timedelta
from typing import Annotated, Any

from pydantic import AfterValidator, BeforeValidator, Field


def _low_first(value: tuple[Any, Any]) -> tuple[Any, Any]:
    if value[0] > value[1]:
        raise ValueError('the low value must be first')
    return value


def _is_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _duration(value: object) -> timedelta:
    """A duration as Home Assistant has it: a number of seconds, a text ``HH:MM:SS``, or a map."""
    found = None
    if isinstance(value, timedelta):
        found = value
    elif _is_number(value):
        found = timedelta(seconds=value)  # type: ignore[arg-type]
    elif isinstance(value, str) and (parts := re.fullmatch(r'(\d+):([0-5]\d):([0-5]\d)', value)):
        hours, minutes, seconds = map(int, parts.groups())
        found = timedelta(hours=hours, minutes=minutes, seconds=seconds)
    elif isinstance(value, dict) and value and all(k in DURATION_KEYS and _is_number(v) for k, v in value.items()):
        found = timedelta(**value)
    if found is None:
        raise ValueError(f'must be a number of seconds, a text HH:MM:SS, or a map with {", ".join(DURATION_KEYS)}')
    if found <= timedelta(0):
        raise ValueError('must be more than 0')
    return found


def _http(value: str) -> str:
    if not value.startswith(('http://', 'https://')):
        raise ValueError('must start with http:// or https://')
    return value


def _entity_id(value: str) -> str:
    if not re.fullmatch(r'[a-z0-9_]+\.[a-z0-9_]+', value):
        raise ValueError('must be an entity id of Home Assistant, for example sensor.grid_power')
    return value


DURATION_KEYS = ('days', 'hours', 'minutes', 'seconds')


# A text as a number, or true and false, is not a number.
Text = Annotated[str, Field(min_length=1)]
Positive = Annotated[float, Field(gt=0, strict=True)]
PositiveInt = Annotated[int, Field(gt=0, strict=True)]
# The address of a server. The client opens only ``http`` and ``https``.
HttpUrl = Annotated[Text, AfterValidator(_http)]
# The mark of a ``Sensor`` field
SENSOR = 'sensor'
# A sensor that the detector reads: an entity id of Home Assistant, with the form ``domain.object_id``.
# homebuddy loads the history of each field with this type.
Sensor = Annotated[Text, AfterValidator(_entity_id), SENSOR]
# A list of texts with one entry or more
Entities = Annotated[tuple[Text, ...], Field(min_length=1)]
# Two positive numbers, the low one first
Range = Annotated[tuple[Positive, Positive], AfterValidator(_low_first)]
# A time of more than 0: a number of seconds, a text ``HH:MM:SS``, or a map with ``DURATION_KEYS``
Duration = Annotated[timedelta, BeforeValidator(_duration)]
# Two durations, the short one first
DurationRange = Annotated[tuple[Duration, Duration], AfterValidator(_low_first)]
