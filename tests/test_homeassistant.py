from __future__ import annotations

import io
import json
from datetime import datetime, timedelta
from typing import Any

import pytest

from homebuddy import homeassistant
from homebuddy.homeassistant import HomeAssistant
from homebuddy.model import numbers
from tests.conftest import TZ, UTC


class FakeResponse(io.BytesIO):
    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()


@pytest.fixture
def requests(monkeypatch: pytest.MonkeyPatch) -> list[Any]:
    """The requests of the client. Home Assistant answers each one with ``ANSWERS``, by the path of the request."""
    seen: list[Any] = []

    def fake_urlopen(req: Any, timeout: float) -> FakeResponse:
        seen.append(req)
        path = req.full_url.removeprefix('http://ha:8123').split('?')[0]
        return FakeResponse(json.dumps(ANSWERS[path]).encode())

    monkeypatch.setattr('urllib.request.urlopen', fake_urlopen)
    return seen


HISTORY = [
    [
        {'state': '1500.5', 'last_changed': '2026-09-13T10:01:00Z'},
        {'state': 'unavailable', 'last_changed': '2026-09-13T10:02:00Z'},
        {'state': '800', 'last_updated': '2026-09-13T10:00:00+00:00'},
        {'last_changed': '2026-09-13T10:03:00Z'},
        {'state': '900'},
    ]
]
STATE = {'state': '21.5', 'attributes': {'unit_of_measurement': '°C', 'friendly_name': 'Discharge'}}
ANSWERS: dict[str, Any] = {
    '/api/history/period/2026-09-13T10:00:00+00:00': HISTORY,
    '/api/history/period/2026-09-14T10:00:00+00:00': [],
    '/api/states/sensor.air': STATE,
    '/api/states/sensor.p': {'state': '1.5', 'attributes': {'unit_of_measurement': 'kW', 'device_class': 'power'}},
    '/api/states/sensor.door': {'state': 'on'},
    '/api/states/sensor.a%2Fb%3Fc': {'state': 'on'},
    '/api/config': {'time_zone': 'Europe/Berlin', 'version': '2026.10.0'},
}


def test_history(requests: list[Any]) -> None:
    start = datetime(2026, 9, 13, 12, 0, tzinfo=TZ)
    readings = HomeAssistant('http://ha:8123/', 'tok').history('sensor.p', start, start + timedelta(hours=1))

    # Each state that has a time, in the order of time. A state that is not a number stays.
    assert readings == [
        (datetime(2026, 9, 13, 10, 0, tzinfo=UTC), '800'),
        (datetime(2026, 9, 13, 10, 1, tzinfo=UTC), '1500.5'),
        (datetime(2026, 9, 13, 10, 2, tzinfo=UTC), 'unavailable'),
    ]
    assert numbers(readings) == [
        (datetime(2026, 9, 13, 10, 0, tzinfo=UTC), 800.0),
        (datetime(2026, 9, 13, 10, 1, tzinfo=UTC), 1500.5),
    ]
    [request] = requests
    assert request.full_url.startswith('http://ha:8123/api/history/period/2026-09-13T10:00:00+00:00?')
    assert 'filter_entity_id=sensor.p' in request.full_url
    assert request.get_header('Authorization') == 'Bearer tok'


def test_history_without_states(requests: list[Any]) -> None:
    start = datetime(2026, 9, 14, 12, 0, tzinfo=TZ)
    assert HomeAssistant('http://ha:8123', 'tok').history('sensor.p', start, start) == []


def test_unit_power_class_and_name_of_a_sensor(requests: list[Any]) -> None:
    client = HomeAssistant('http://ha:8123/', 'tok')
    assert (client.unit('sensor.air'), client.is_power('sensor.air'), client.name('sensor.air')) == (
        '°C',
        False,
        'Discharge',
    )
    # A sensor is a power sensor when Home Assistant gives it the class ``power``. A sensor can have no attributes.
    assert (client.unit('sensor.p'), client.is_power('sensor.p'), client.name('sensor.p')) == ('kW', True, '')
    assert (client.unit('sensor.door'), client.is_power('sensor.door'), client.name('sensor.door')) == ('', False, '')
    # The client asks one time for each sensor.
    assert [request.full_url for request in requests] == [
        'http://ha:8123/api/states/sensor.air',
        'http://ha:8123/api/states/sensor.p',
        'http://ha:8123/api/states/sensor.door',
    ]


def test_the_client_quotes_the_sensor_in_the_path(requests: list[Any]) -> None:
    assert HomeAssistant('http://ha:8123', 'tok').unit('sensor.a/b?c') == ''
    assert [request.full_url for request in requests] == ['http://ha:8123/api/states/sensor.a%2Fb%3Fc']


def test_timezone(requests: list[Any]) -> None:
    assert HomeAssistant('http://ha:8123', 'tok').timezone() == 'Europe/Berlin'
    assert [request.full_url for request in requests] == ['http://ha:8123/api/config']


def test_the_client_asks_again_after_the_time_limit(requests: list[Any], monkeypatch: pytest.MonkeyPatch) -> None:
    now = 1000.0
    monkeypatch.setattr('time.monotonic', lambda: now)
    client = HomeAssistant('http://ha:8123', 'tok')

    client.unit('sensor.air')
    client.timezone()
    now += homeassistant.CACHE_SECONDS
    assert (client.name('sensor.air'), client.timezone()) == ('Discharge', 'Europe/Berlin')
    # In the time limit, the client asks one time for each sensor and one time for the time zone.
    assert len(requests) == 2

    now += 1
    client.unit('sensor.air')
    client.timezone()
    assert len(requests) == 4
    # A second client has its own cache.
    HomeAssistant('http://ha:8123', 'tok').unit('sensor.air')
    assert len(requests) == 5


def test_the_text_of_the_client_does_not_show_the_token() -> None:
    assert 'tok' not in repr(HomeAssistant('http://ha:8123', 'tok'))
