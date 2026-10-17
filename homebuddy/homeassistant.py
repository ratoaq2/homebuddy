"""The HTTP client of Home Assistant. homebuddy only reads from Home Assistant."""

from __future__ import annotations

import json
import threading
import time
import urllib.parse
import urllib.request
from collections.abc import Callable, Sequence
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from homebuddy.model import Reading, SensorError

# The client asks again for the attributes of a sensor and for the time zone after this time.
CACHE_SECONDS = 600
# The client keeps the history of a window that ended this time before the request. The past does not change.
SETTLED_SECONDS = 60
# The number of windows of history that the client keeps. Home Assistant keeps about 10 days of history.
MAX_WINDOWS = 10


class HomeAssistant:
    """One Home Assistant. Only this object has the token."""

    def __init__(self, url: str, token: str) -> None:
        self._url = url.rstrip('/')
        self._token = token
        # The answer of each path that the client keeps, with the time of the answer
        self._cache: dict[str, tuple[float, Any]] = {}
        # The history of each past window, by its sensors, its start and its end, the oldest first. The threads of
        # the pages share the client, so a lock protects it.
        self._windows: dict[tuple[tuple[str, ...], datetime, datetime], dict[str, list[Reading]]] = {}
        self._lock = threading.Lock()

    def _get(self, path: str) -> Any:
        headers = {'Authorization': f'Bearer {self._token}', 'Content-Type': 'application/json'}
        req = urllib.request.Request(f'{self._url}{path}', headers=headers)
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode())

    def _cached(self, path: str, read: Callable[[Any], Any] = lambda answer: answer) -> Any:
        """The answer of a path, from the cache. ``read`` changes the answer before the cache keeps it."""
        found = self._cache.get(path)
        if found is None or time.monotonic() - found[0] > CACHE_SECONDS:
            found = self._cache[path] = (time.monotonic(), read(self._get(path)))
        return found[1]

    def history(self, sensors: Sequence[str], start: datetime, end: datetime) -> dict[str, list[Reading]]:
        """The history of each sensor, from one request: each state, also a state that is not a number.

        A sensor without states has an empty list. The client keeps the history of a past window. See
        ``SETTLED_SECONDS`` and ``MAX_WINDOWS``.
        """
        key = (tuple(sensors), start, end)
        with self._lock:
            if key in self._windows:
                return dict(self._windows[key])
        start_iso = start.astimezone(ZoneInfo('UTC')).isoformat()
        end_iso = end.astimezone(ZoneInfo('UTC')).isoformat()
        # Home Assistant reads ``minimal_response`` and ``no_attributes`` without a value. Only the first state of
        # each sensor then has its entity id.
        params = urllib.parse.urlencode(
            {
                'filter_entity_id': ','.join(sensors),
                'end_time': end_iso,
                'minimal_response': '',
                'no_attributes': '',
            }
        )
        data: list[list[dict[str, Any]]] = self._get(f'/api/history/period/{start_iso}?{params}')
        found: dict[str, list[Reading]] = {sensor: [] for sensor in sensors}
        # The order of the lists is not the order of the sensors in the request.
        for items in data:
            readings = found.get(items[0].get('entity_id', '')) if items else None
            if readings is None:
                continue
            for item in items:
                ts_raw = item.get('last_changed') or item.get('last_updated')
                if 'state' not in item or not ts_raw:
                    continue
                ts = datetime.fromisoformat(ts_raw.replace('Z', '+00:00'))
                readings.append((ts, str(item['state'])))
            readings.sort()
        if end < datetime.now(ZoneInfo('UTC')) - timedelta(seconds=SETTLED_SECONDS):
            with self._lock:
                self._windows[key] = found
                while len(self._windows) > MAX_WINDOWS:
                    del self._windows[next(iter(self._windows))]
        return dict(found)

    def _attributes(self, sensor: str) -> dict[str, Any]:
        """The attributes of a sensor. One request gets the state of each entity of Home Assistant."""
        states: dict[str, dict[str, Any]] = self._cached(
            '/api/states', lambda answer: {state['entity_id']: state for state in answer}
        )
        if sensor not in states:
            raise SensorError(f'{sensor}: Home Assistant does not have this sensor')
        return dict(states[sensor].get('attributes', {}))

    def unit(self, sensor: str) -> str:
        """The unit of a sensor. It is empty for a sensor without a unit."""
        return str(self._attributes(sensor).get('unit_of_measurement', ''))

    def is_power(self, sensor: str) -> bool:
        """True for a power sensor: Home Assistant gives it the class ``power``."""
        return self._attributes(sensor).get('device_class') == 'power'

    def name(self, sensor: str) -> str:
        """The name of a sensor in Home Assistant. It is empty for a sensor without a name."""
        return str(self._attributes(sensor).get('friendly_name', ''))

    def timezone(self) -> str:
        """The time zone of Home Assistant, for example ``Europe/Berlin``."""
        return str(self._cached('/api/config')['time_zone'])
