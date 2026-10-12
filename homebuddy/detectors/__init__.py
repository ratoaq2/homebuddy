"""The detector types. Each type has its own module."""

from __future__ import annotations

import logging
from functools import cache
from importlib.metadata import EntryPoint, entry_points

from homebuddy.detector import Detector
from homebuddy.detectors.level import Level
from homebuddy.detectors.pulse import Pulse
from homebuddy.detectors.ramp import Ramp
from homebuddy.detectors.state import State
from homebuddy.detectors.threshold import Threshold

# The built-in detector types, by the name of the type in the configuration file.
DETECTORS: dict[str, type[Detector]] = {
    'level': Level,
    'pulse': Pulse,
    'ramp': Ramp,
    'state': State,
    'threshold': Threshold,
}
# Other packages add a detector type with an entry point in this group. See docs/detector-types.md.
DETECTOR_ENTRY_POINTS = 'homebuddy.detectors'

log = logging.getLogger(__name__)


def _load(entry_point: EntryPoint) -> type[Detector] | str:
    """The detector type of an entry point, or the error of a wrong one."""
    kind = f'detector type `{entry_point.name}` of `{entry_point.value}`'
    try:
        loaded = entry_point.load()
    except Exception as e:  # The module of a different package can raise each error.
        return f'Cannot load the {kind}: {e}'
    if not (isinstance(loaded, type) and issubclass(loaded, Detector)):
        return f'The {kind} must be a subclass of {Detector.__module__}.{Detector.__name__}'
    return loaded


@cache
def detector_types() -> dict[str, type[Detector] | str]:
    """The built-in types, then the types of other packages. A built-in type wins over a type with the same name.

    A wrong type of a package does not stop homebuddy. Its value is the text of the error, for a detector
    that uses the type.
    """
    types: dict[str, type[Detector] | str] = dict(DETECTORS)
    for entry_point in entry_points(group=DETECTOR_ENTRY_POINTS):
        if entry_point.name in DETECTORS:
            log.warning(
                'The detector type `%s` of `%s` has the name of a built-in type. homebuddy uses the built-in type.',
                entry_point.name,
                entry_point.value,
            )
        else:
            types[entry_point.name] = _load(entry_point)
    return types
