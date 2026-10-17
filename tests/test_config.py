from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest

from homebuddy.config import ConfigError, Server, Settings, Tab, TabSensor, ha_token, load_settings
from homebuddy.detector import Detector
from homebuddy.detectors import DETECTORS
from homebuddy.detectors.level import Level
from homebuddy.detectors.pulse import Pulse
from homebuddy.detectors.ramp import Ramp
from homebuddy.detectors.state import State
from homebuddy.detectors.threshold import Threshold
from tests.conftest import DURATION, TABS, TABS_YAML, entries

EXAMPLE = Path(__file__).parent.parent / 'homebuddy.example.yml'


# A file needs a time zone and one detector or more.
EV_KEYS = 'type: level, sensor: sensor.grid, levels_w: [4140, 11040]'
DETECTOR = f'timezone: UTC\n{TABS_YAML}detectors: {{ev: {{{EV_KEYS}}}}}\n'
# The detector of ``DETECTOR``
EV = Level(levels_w=(4140, 11040), sensor='sensor.grid')


def ev(keys: str) -> str:
    """The text of a file with these keys in the level detector with the name ``ev``."""
    return f'detectors: {{ev: {{type: level, {keys}}}}}\n'


def ev_of(settings: Settings) -> Level:
    """The detector with the name ``ev``."""
    detector = settings.detectors['ev']
    assert isinstance(detector, Level)
    return detector


def test_missing_url_or_token(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / 'homebuddy.yml').write_text(DETECTOR)
    monkeypatch.delenv('HA_TOKEN')
    with pytest.raises(ConfigError, match='HA_TOKEN: Set it in the environment or in .env'):
        load_settings()
    with pytest.raises(ConfigError, match='HA_TOKEN: Set it in the environment or in .env'):
        ha_token()
    monkeypatch.setenv('HA_TOKEN', 'env-token')
    with pytest.raises(ConfigError, match='home_assistant: Field required'):
        load_settings()


def test_defaults(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv('HA_TOKEN', 'env-token')
    (tmp_path / 'homebuddy.yml').write_text(f'home_assistant:\n  url: http://file\n{DETECTOR}')
    settings = load_settings()
    ev = ev_of(settings)
    assert settings == Settings(
        tabs=TABS, home_assistant=Server(url='http://file'), timezone='UTC', detectors={'ev': ev}
    )
    assert settings.date_format == '%Y-%m-%d %H:%M:%S'
    assert ev == EV
    assert ev.tolerance == 0.1
    assert ev.min_duration == timedelta(minutes=10)


def test_env_has_only_the_token(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / 'homebuddy.yml').write_text(DETECTOR)
    monkeypatch.setenv('HA_URL', 'http://env')
    monkeypatch.setenv('HA_ENTITY', 'sensor.grid')
    monkeypatch.setenv('TZ_NAME', 'UTC')
    monkeypatch.setenv('HA_TOKEN', 'env-token')
    with pytest.raises(ConfigError):
        load_settings()
    (tmp_path / 'homebuddy.yml').write_text(f'home_assistant:\n  url: http://file\n{DETECTOR}')
    assert load_settings() == Settings(
        tabs=TABS, home_assistant=Server(url='http://file'), timezone='UTC', detectors={'ev': EV}
    )


def test_keys_are_the_settings_without_the_token() -> None:
    assert DETECTORS == {'level': Level, 'pulse': Pulse, 'ramp': Ramp, 'state': State, 'threshold': Threshold}


def test_the_settings_of_a_file(tmp_path: Path) -> None:
    (tmp_path / 'a.yml').write_text(
        'home_assistant:\n  url: http://file\ntimezone: UTC\n' + TABS_YAML + "date_format: '%Y-%m-%d %H:%M'\n"
        'detectors:\n'
        '  ev:\n    type: level\n    sensor: sensor.grid\n    levels_w: [2400, 3840.5, 7680]\n'
        '    tolerance: 0.2\n    min_duration: "00:30:00"\n'
        '  well_pump:\n    type: pulse\n    sensor: sensor.grid\n'
        '    step_w: [900, 1100]\n    duration: [30, 90]\n    max_step_difference_w: 100\n'
        '    min_gap: {minutes: 5}\n'
    )
    detectors: dict[str, Detector] = {
        'ev': Level(
            levels_w=(2400, 3840.5, 7680),
            tolerance=0.2,
            min_duration=timedelta(minutes=30),
            sensor='sensor.grid',
        ),
        'well_pump': Pulse(
            step_w=(900, 1100),
            duration=DURATION,
            max_step_difference_w=100,
            min_gap=timedelta(minutes=5),
            sensor='sensor.grid',
        ),
    }
    expected = Settings(
        tabs=TABS,
        home_assistant=Server(url='http://file'),
        timezone='UTC',
        date_format='%Y-%m-%d %H:%M',
        detectors=detectors,
    )
    assert load_settings(config=str(tmp_path / 'a.yml')) == expected


def test_the_detectors_have_the_order_of_the_file(tmp_path: Path) -> None:
    (tmp_path / 'homebuddy.yml').write_text(
        f'home_assistant:\n  url: http://file\ntimezone: UTC\n{TABS_YAML}'
        'detectors:\n'
        '  pump: {type: pulse, sensor: sensor.grid, step_w: [900, 1100], duration: [30, 90],\n'
        '         max_step_difference_w: 50}\n'
        '  air_conditioner:\n    type: ramp\n    sensor: sensor.air\n'
        '    rise_per_minute: 5\n    fall_per_minute: 4\n    min_rise: 25\n'
        '  fan: {type: ramp, sensor: sensor.air, rise_per_minute: 1, fall_per_minute: 1, min_rise: 5,\n'
        '    max_pause: {minutes: 2}}\n'
        f'  ev: {{{EV_KEYS}}}\n'
    )
    settings = load_settings()
    assert settings.detectors == {
        'pump': Pulse(step_w=(900, 1100), duration=DURATION, max_step_difference_w=50, sensor='sensor.grid'),
        'air_conditioner': Ramp(rise_per_minute=5, fall_per_minute=4, min_rise=25, sensor='sensor.air'),
        'fan': Ramp(
            rise_per_minute=1, fall_per_minute=1, min_rise=5, max_pause=timedelta(minutes=2), sensor='sensor.air'
        ),
        'ev': EV,
    }
    # The detectors have the order of the file.
    assert list(settings.detectors) == ['pump', 'air_conditioner', 'fan', 'ev']


def test_file_without_an_ev_detector(tmp_path: Path) -> None:
    pulse = 'type: pulse, sensor: sensor.grid, step_w: [1, 2], duration: [1, 2], max_step_difference_w: 50'
    (tmp_path / 'homebuddy.yml').write_text(
        f'home_assistant:\n  url: http://file\ntimezone: UTC\n{TABS_YAML}detectors: {{pump: {{{pulse}}}}}\n'
    )
    assert list(load_settings().detectors) == ['pump']


def test_the_tabs_have_the_order_of_the_file(tmp_path: Path) -> None:
    (tmp_path / 'homebuddy.yml').write_text(
        'home_assistant:\n  url: http://file\ntimezone: UTC\n'
        'tabs:\n'
        '  air: {sensors: [sensor.air], detectors: []}\n'
        '  power: {name: House, sensors: [sensor.grid], detectors: [ev]}\n'
        '  all: {sensors: [sensor.grid], hidden_detectors: [ev]}\n'
        '  lines: {sensors: [sensor.grid, sensor.solar]}\n' + ev(EV_KEYS)
    )
    assert load_settings().tabs == {
        'air': Tab(sensors=entries('sensor.air'), detectors=()),
        'power': Tab(name='House', sensors=entries('sensor.grid'), detectors=('ev',)),
        'all': Tab(sensors=entries('sensor.grid'), hidden_detectors=('ev',)),
        # Each sensor of a tab is a line of its chart.
        'lines': Tab(sensors=entries('sensor.grid', 'sensor.solar')),
    }
    assert list(load_settings().tabs) == ['air', 'power', 'all', 'lines']


def test_two_ev_detectors(tmp_path: Path) -> None:
    (tmp_path / 'homebuddy.yml').write_text(
        f'home_assistant:\n  url: http://file\ntimezone: UTC\n{TABS_YAML}'
        f'detectors: {{garage: {{{EV_KEYS}}}, street: {{{EV_KEYS}, tolerance: 0.2}}}}\n'
    )
    assert load_settings().detectors == {'garage': EV, 'street': EV.model_copy(update={'tolerance': 0.2})}


def test_file_without_a_time_zone(tmp_path: Path) -> None:
    (tmp_path / 'homebuddy.yml').write_text(
        f'home_assistant:\n  url: http://file\n{TABS_YAML}detectors: {{ev: {{{EV_KEYS}}}}}\n'
    )
    # The search then uses the time zone of Home Assistant.
    assert load_settings().timezone is None


def test_each_error_of_the_file(tmp_path: Path) -> None:
    (tmp_path / 'homebuddy.yml').write_text(
        f'home_assistant:\n  url: http://file\ntimezone: UTC\n{TABS_YAML}theme: blue\nvoltage: 230\n'
        f'detectors: {{ev: {{{EV_KEYS}, tolerance: 2}}}}\n'
    )
    with pytest.raises(ConfigError) as error:
        load_settings()
    first, *lines = str(error.value).splitlines()
    assert (first.startswith('3 errors in '), first.endswith('homebuddy.yml:')) == (True, True)
    assert lines == [
        'detectors.ev.tolerance: must be a number between 0 and 1',
        "theme: Input should be 'light', 'dark' or 'system'",
        'voltage: Extra inputs are not permitted',
    ]


def test_the_token_is_not_in_the_settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv('HA_TOKEN', 'secret-token')
    (tmp_path / 'homebuddy.yml').write_text(f'home_assistant:\n  url: http://file\n{DETECTOR}')
    settings = load_settings()
    assert ha_token() == 'secret-token'
    assert 'secret-token' not in repr(settings) + str(settings.model_dump()) + str(vars(settings))


def test_file_without_a_detector(tmp_path: Path) -> None:
    (tmp_path / 'homebuddy.yml').write_text(f'home_assistant:\n  url: http://file\ntimezone: UTC\n{TABS_YAML}')
    with pytest.raises(ConfigError, match='detectors: Add one detector or more'):
        load_settings()


def test_name_of_a_detector(tmp_path: Path) -> None:
    pulse = 'type: pulse, sensor: sensor.grid, step_w: [1, 2], duration: [1, 2], max_step_difference_w: 50'
    (tmp_path / 'homebuddy.yml').write_text(
        f'home_assistant:\n  url: http://file\ntimezone: UTC\n{TABS_YAML}'
        'detectors:\n'
        f'  ev: {{{EV_KEYS}, name: Car}}\n'
        f'  garden: {{name: Garden pump, {pulse}}}\n'
        f'  pump: {{{pulse}}}\n'
    )
    settings = load_settings()
    assert [detector.name for detector in settings.detectors.values()] == ['Car', 'Garden pump', None]


def test_copy_columns(tmp_path: Path) -> None:
    (tmp_path / 'homebuddy.yml').write_text(f'home_assistant:\n  url: http://file\n{DETECTOR}')
    # Without the key, the copy button copies each column.
    assert load_settings().copy_columns is None
    (tmp_path / 'homebuddy.yml').write_text(
        f'home_assistant:\n  url: http://file\ntimezone: UTC\n{TABS_YAML}copy_columns: [start, end]\n{DETECTOR}'
    )
    assert load_settings().copy_columns == ('start', 'end')


def test_homebuddy_reads_one_file(tmp_path: Path) -> None:
    # conftest sets the user directory to "user" and the current directory to tmp_path.
    with pytest.raises(ConfigError, match='No configuration file. Use --config, or .*:\n.*homebuddy.yml\n.*config.yml'):
        load_settings()

    (tmp_path / 'user').mkdir()
    (tmp_path / 'user' / 'config.yaml').write_text(f'home_assistant:\n  url: http://user\n{DETECTOR}')
    assert load_settings().home_assistant.url == 'http://user'

    # The file of the current directory wins. No key comes from the file of the user directory.
    (tmp_path / 'homebuddy.yml').write_text('home_assistant:\n  url: http://cwd\n')
    with pytest.raises(ConfigError, match='2 errors in .*homebuddy.yml:\ndetectors: Add one detector or more\ntabs'):
        load_settings()
    (tmp_path / 'homebuddy.yml').write_text(f'home_assistant:\n  url: http://cwd\n{DETECTOR}')
    assert load_settings().home_assistant.url == 'http://cwd'

    # The file of the argument wins.
    (tmp_path / 'other.yml').write_text(f'home_assistant:\n  url: http://other\n{DETECTOR}')
    assert load_settings(config=str(tmp_path / 'other.yml')).home_assistant.url == 'http://other'


def test_empty_yaml_file(tmp_path: Path) -> None:
    (tmp_path / 'homebuddy.yml').write_text('# nothing\n')
    with pytest.raises(
        ConfigError,
        match='3 errors in .*homebuddy.yml:\ndetectors: Add one detector or more\n'
        'home_assistant: Field required\ntabs: Field required',
    ):
        load_settings()


@pytest.mark.parametrize(
    ('name', 'content', 'message'),
    [
        ('a.yml', 'voltage_v: 230\n', 'voltage_v: Extra inputs are not permitted'),
        ('a.yml', 'ha_token: secret\n', 'ha_token is not permitted in .*a.yml'),
        ('a.yml', 'date_format: 8123\n', 'date_format: Input should be a valid string'),
        ('a.yml', 'copy_columns: start\n', 'copy_columns: Input should be a valid list'),
        ('a.yml', 'copy_columns: []\n', 'copy_columns: List should have at least 1 item'),
        # A title of a column is not an id.
        (
            'a.yml',
            'copy_columns: [start, Power (kW)]\n',
            r"copy_columns.1: Input should be 'detector', 'start', 'end', 'duration', 'label', 'power', 'energy', "
            "'start_value' or 'peak'",
        ),
        ('a.yml', 'theme: blue\n', "theme: Input should be 'light', 'dark' or 'system'"),
        ('a.yml', 'voltage: 230\n', 'voltage: Extra inputs are not permitted'),
        ('a.yml', ev('tolerance: 0.2'), 'detectors.ev.levels_w: Field required'),
        ('a.yml', ev('levels_w: []'), 'detectors.ev.levels_w: List should have at least 1 item'),
        ('a.yml', ev('levels_w: 4140'), 'detectors.ev.levels_w: Input should be a valid list'),
        ('a.yml', ev('levels_w: [4140, high]'), 'detectors.ev.levels_w.1: Input should be a valid number'),
        ('a.yml', ev('levels_w: [4140, 0]'), 'detectors.ev.levels_w.1: Input should be greater than 0'),
        ('a.yml', ev('levels_w: [true]'), 'detectors.ev.levels_w.0: Input should be a valid number'),
        ('a.yml', ev('phases: 3'), 'detectors.ev.phases: Extra inputs are not permitted'),
        ('a.yml', ev('tolerance: 1'), 'detectors.ev.tolerance: must be a number between 0 and 1'),
        ('a.yml', ev('min_duration: -1'), 'detectors.ev.min_duration: must be more than 0'),
        ('a.yml', 'detectors: [ev]\n', 'detectors in .*a.yml must be a map of detectors'),
        ('a.yml', 'detectors: {ev: 230}\n', 'detectors.ev in .*a.yml must contain keys and values'),
        ('a.yml', ev('step_w: [1, 2]'), 'detectors.ev.step_w: Extra inputs are not permitted'),
        ('a.yml', ev('name: 5'), 'detectors.ev.name: Input should be a valid string'),
        (
            'a.yml',
            'detectors: {pump: {max_step_difference_w: 50}}\n',
            'detectors.pump in .*a.yml must have the type level or pulse or ramp',
        ),
        # The name of a detector does not give its type.
        (
            'a.yml',
            'detectors: {ev: {phases: 3}}\n',
            'detectors.ev in .*a.yml must have the type level or pulse or ramp',
        ),
        ('a.yml', 'detectors: {pump: {type: pump}}\n', 'detectors.pump in .*a.yml must have the type level or pulse'),
        (
            'a.yml',
            'detectors: {pump: {type: pulse, step_w: [9, 1]}}\n',
            'detectors.pump.step_w: the low value must be first',
        ),
        (
            'a.yml',
            'detectors: {pump: {type: pulse, step_w: 2000}}\n',
            'detectors.pump.step_w: Input should be a valid list',
        ),
        (
            'a.yml',
            'detectors: {pump: {type: pulse, max_step_difference_w: 50}}\n',
            'detectors.pump.step_w: Field required',
        ),
        ('a.yml', 'detectors: {c: {type: ramp, min_rise: 20}}\n', 'detectors.c.rise_per_minute: Field required'),
        ('a.yml', 'detectors: {c: {type: ramp, sensor: 5}}\n', 'detectors.c.sensor: Input should be a valid string'),
        ('a.yml', ev('sensor: ""'), 'detectors.ev.sensor: String should have at least 1 character'),
        # The old key of the sensors
        ('a.yml', ev(f'{EV_KEYS}, entities: [sensor.grid]'), 'detectors.ev.entities: Extra inputs are not permitted'),
        ('a.yml', 'entity: sensor.grid\n', 'entity: Extra inputs are not permitted'),
        (
            'a.yml',
            'detectors: {c: {type: ramp, rise_per_minute: 5, fall_per_minute: 4, min_rise: 25}}\n',
            'detectors.c.sensor: Field required',
        ),
        ('a.yml', ev(f'{EV_KEYS}, overrides: [pump]'), 'detectors.ev.overrides.0: pump is not a detector'),
        ('a.yml', ev(f'{EV_KEYS}, overrides: [ev]'), 'detectors.ev.overrides.0: a detector cannot override itself'),
        ('a.yml', ev('overrides: ev'), 'detectors.ev.overrides: Input should be a valid list'),
        ('a.yml', 'tabs: {}\n', 'tabs: Dictionary should have at least 1 item'),
        ('a.yml', 'tabs: {power: {sensor: sensor.p}}\n', 'tabs.power.sensors: Field required'),
        ('a.yml', 'tabs: {power: {sensors: []}}\n', 'tabs.power.sensors: List should have at least 1 item'),
        (
            'a.yml',
            'tabs: {power: {sensors: [sensor.p], detectors: [ev, pump]}}\n' + ev(EV_KEYS),
            'tabs.power.detectors.1: pump is not a detector',
        ),
        (
            'a.yml',
            'tabs: {power: {sensors: [sensor.p], hidden_detectors: [ev, pump]}}\n' + ev(EV_KEYS),
            'tabs.power.hidden_detectors.1: pump is not a detector',
        ),
        (
            'a.yml',
            'tabs: {power: {sensors: [sensor.p], hidden_detectors: ev}}\n' + ev(EV_KEYS),
            'tabs.power.hidden_detectors: Input should be a valid list',
        ),
        # Only a Home Assistant on the network: no file and no different scheme
        (
            'a.yml',
            'home_assistant:\n  url: file:///etc/passwd\n',
            'home_assistant.url: must start with http:// or https://',
        ),
        ('a.yml', 'home_assistant:\n  url: ftp://ha\n', 'home_assistant.url: must start with http:// or https://'),
        # A sensor is an entity id, so it cannot change the path of a request.
        ('a.yml', ev('sensor: sensor.p/../../config'), 'detectors.ev.sensor: must be an entity id of Home Assistant'),
        ('a.yml', ev('sensor: grid'), 'detectors.ev.sensor: must be an entity id of Home Assistant'),
        (
            'a.yml',
            'tabs: {power: {sensors: [sensor.p, "sensor.p?x=1"]}}\n',
            'tabs.power.sensors.1.sensor: must be an entity id of Home Assistant',
        ),
        ('a.yml', '- home_assistant\n', 'a.yml must contain keys and values'),
        ('a.yml', 'home_assistant: [\n', 'Cannot read .*a.yml'),
        ('a.json', '{"home_assistant": {"url": "http://ha"}}', 'a.json is not a .yml or .yaml file'),
    ],
)
def test_wrong_file(tmp_path: Path, name: str, content: str, message: str) -> None:
    (tmp_path / name).write_text(content)
    with pytest.raises(ConfigError, match=message):
        load_settings(config=str(tmp_path / name))


def test_config_file_does_not_exist(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match='Cannot read .*none.yml'):
        load_settings(config=str(tmp_path / 'none.yml'))


def test_example_file_has_the_defaults() -> None:
    settings = load_settings(config=str(EXAMPLE))
    # Each optional key of the file shows the default of the code.
    example = Level(levels_w=(4140, 6900, 11040), sensor='sensor.grid_power')
    url = 'http://homeassistant.local:8123'
    tabs = {'power': Tab(sensors=entries('sensor.grid_power'))}
    assert settings == Settings(tabs=tabs, home_assistant=Server(url=url), detectors={'car': example})


def test_a_sensor_of_a_tab_with_keys(tmp_path: Path) -> None:
    def write(solar: str) -> None:
        (tmp_path / 'homebuddy.yml').write_text(
            'home_assistant:\n  url: http://file\n'
            f'tabs:\n  power:\n    sensors:\n      - sensor.grid\n      - {solar}\n' + ev(EV_KEYS)
        )

    # An entry is an entity id, or a map with the keys of the sensor.
    write('{sensor: sensor.solar, smooth: {minutes: 5}}')
    assert load_settings().tabs['power'].sensors == (
        TabSensor(sensor='sensor.grid'),
        TabSensor(sensor='sensor.solar', smooth=timedelta(minutes=5)),
    )
    for solar, error in [
        ('{sensor: sensor.solar, smooth: 0}', 'tabs.power.sensors.1.smooth: must be more than 0'),
        ('{smooth: 300}', 'tabs.power.sensors.1.sensor: Field required'),
        ('{sensor: sensor.solar, color: red}', 'tabs.power.sensors.1.color: Extra inputs are not permitted'),
    ]:
        write(solar)
        with pytest.raises(ConfigError, match=error):
            load_settings()
