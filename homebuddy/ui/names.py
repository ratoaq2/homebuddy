"""The names that the page shows for a tab and for a detector."""

from __future__ import annotations

from homebuddy.result import SearchResult


def tab_name(result: SearchResult) -> str:
    """The name of the tab: its name in the file, or the name of the sensor in Home Assistant.

    It is the entity id without the two names.
    """
    return result.tab_name or result.sensor_name or result.sensor


def detector_name(result: SearchResult, name: str) -> str:
    """The name of a detector. It is the name of the detector in the file without ``name``."""
    return result.detectors[name].name or name
