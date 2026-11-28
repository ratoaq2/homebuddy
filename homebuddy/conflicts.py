"""The conflicts: an event loses against the same event of a detector that overrides its detector."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import NamedTuple

from homebuddy.model import Event

# An event is the same event as a different one when this part of its time, or more, is in the different one.
SAME_EVENT = 0.5


class Conflict(NamedTuple):
    """An event that lost against the same event of a detector that overrides its detector."""

    detector: str
    start: datetime
    end: datetime
    winner: str


def same_event(event: Event, other: Event) -> bool:
    """True when most of the time of ``event`` is in ``other``. A short event in a long one is the same event."""
    common = (min(event.end, other.end) - max(event.start, other.start)).total_seconds()
    total = (event.end - event.start).total_seconds()
    return bool(total > 0 and common / total >= SAME_EVENT)


def solve_conflicts(found: Mapping[str, Sequence[Event]], overrides: Mapping[str, Sequence[str]]) -> list[Conflict]:
    """The events that lose a conflict. ``found`` has the events of each detector.

    ``overrides`` has the detectors that each detector overrides. An event loses when a detector that
    overrides its detector found the same event. A detector that overrides nothing removes nothing.
    """
    return [
        Conflict(name, event.start, event.end, winner)
        for name, events in found.items()
        for event in events
        for winner, others in found.items()
        if name in overrides.get(winner, ()) and any(same_event(event, other) for other in others)
    ]
