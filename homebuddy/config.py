"""Settings from the configuration file. The Home Assistant token is only in the environment."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Annotated, Any, Literal

import yaml
from platformdirs import user_config_dir
from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, SkipValidation, ValidationError

from homebuddy.detector import Detector
from homebuddy.detectors import detector_types
from homebuddy.fields import Duration, HttpUrl, Sensor, Text

EXTENSIONS = ('.yml', '.yaml')


class ConfigError(Exception):
    """A setting is missing or wrong. The text can have more than one line: one line for each error."""


# The ids of the columns of the events table that the copy button can copy. A power tab has ``power`` and
# ``energy``. A different tab has ``start_value`` and ``peak``.
CopyColumn = Literal['detector', 'start', 'end', 'duration', 'label', 'power', 'energy', 'start_value', 'peak']


class TabSensor(BaseModel):
    """A sensor of a tab: one line of the chart. In the file, it is an entity id, or a map with these keys."""

    model_config = ConfigDict(frozen=True, extra='forbid')

    sensor: Sensor
    # The chart shows the average of the sensor in each window of this time. None is each value of the sensor.
    # The detectors and the values of the events always use each value.
    smooth: Duration | None = None
    # The name of the line in the legend of the chart. None is the name of the sensor in Home Assistant.
    name: str | None = None


def _tab_sensor(value: object) -> object:
    """An entry that is only an entity id is a sensor without more keys."""
    return {'sensor': value} if isinstance(value, str) else value


class Tab(BaseModel):
    """A tab of the page: the chart of a sensor, and the events of some detectors."""

    model_config = ConfigDict(frozen=True, extra='forbid')

    # The sensors of the chart: one line for each sensor. The first sensor is the sensor of the tab.
    sensors: Annotated[tuple[Annotated[TabSensor, BeforeValidator(_tab_sensor)], ...], Field(min_length=1)]
    # The name of the tab for the page. Without it, the page shows the name of the sensor in Home Assistant.
    name: Text | None = None
    # The names of the detectors that the tab shows, in the order of the lanes. None is the default of the
    # search: each detector for a power sensor, and the detectors that read the sensor for a different one.
    detectors: tuple[Text, ...] | None = None
    # The names of the detectors whose rows the events table does not show when the page opens. The filter of
    # the detector shows them.
    hidden_detectors: tuple[Text, ...] = ()


class Server(BaseModel):
    """The ``home_assistant`` section of the file: where Home Assistant is. The token is not in it."""

    model_config = ConfigDict(frozen=True, extra='forbid')

    url: HttpUrl


class Settings(BaseModel):
    """The settings. Each field is a key of the configuration file.

    The type of a field is its check. A key that is not a field is an error. The token of Home Assistant
    is not a setting. See ``ha_token``.
    """

    model_config = ConfigDict(frozen=True, extra='forbid')

    home_assistant: Server
    # The time zone of the home. None is the time zone of Home Assistant.
    timezone: Text | None = None
    date_format: Text = '%Y-%m-%d %H:%M:%S'
    # The tabs of the page, by id, in the order of the configuration file
    tabs: Annotated[dict[str, Tab], Field(min_length=1)]
    # The detectors, by name, in the order of the configuration file. ``load_settings`` checks each one.
    detectors: dict[str, Annotated[Detector, SkipValidation]] = {}
    # The ids of the columns of the events table that the copy button of a row copies, in this order. None is
    # each column.
    copy_columns: Annotated[tuple[CopyColumn, ...], Field(min_length=1)] | None = None
    # The theme of the page. ``system`` is the theme of the computer of the user.
    theme: Literal['light', 'dark', 'system'] = 'system'


def ha_token() -> str:
    """The token of Home Assistant, from the ``HA_TOKEN`` environment variable.

    homebuddy reads ``.env`` into the environment one time, when it starts. See ``homebuddy.ui.app.run``.

    Give the token only to the client of Home Assistant. Do not keep it in an object that the page shows,
    logs or stores.
    """
    token = os.environ.get('HA_TOKEN')
    if not token:
        raise ConfigError('HA_TOKEN: Set it in the environment or in .env')
    return token


def config_path(config: str | None = None) -> Path:
    """The configuration file. homebuddy reads one file only.

    It is ``config``, or ``homebuddy.yml`` in the current directory, or ``config.yml`` in the user directory.
    The first one that exists wins.
    """
    if config:
        return Path(config)
    places = [Path(os.getcwd(), 'homebuddy'), Path(user_config_dir('homebuddy'), 'config')]
    found = [place.with_suffix(extension) for place in places for extension in EXTENSIONS]
    path = next((p for p in found if p.is_file()), None)
    if path is None:
        raise ConfigError(f'No configuration file. Use --config, or make one of these files:\n{found[0]}\n{found[2]}')
    return path


def read_file(path: Path) -> dict[str, Any]:
    """Read a .yml or .yaml configuration file. ``load_settings`` checks the values of the keys."""
    if path.suffix.lower() not in EXTENSIONS:
        raise ConfigError(f'{path} is not a .yml or .yaml file')

    try:
        with open(path, encoding='utf-8') as f:
            values = yaml.safe_load(f)
    except (OSError, ValueError, yaml.YAMLError) as e:
        raise ConfigError(f'Cannot read {path}: {e}') from e

    if values is None:
        values = {}
    if not isinstance(values, dict):
        raise ConfigError(f'{path} must contain keys and values')
    if 'ha_token' in values:
        raise ConfigError(f'ha_token is not permitted in {path}. Set HA_TOKEN in the environment or in .env.')
    if not isinstance(values.setdefault('detectors', {}), dict):
        raise ConfigError(f'detectors in {path} must be a map of detectors')
    types = detector_types()
    for name, detector in values['detectors'].items():
        if not isinstance(detector, dict):
            raise ConfigError(f'detectors.{name} in {path} must contain keys and values')
        if str(detector.get('type')) not in types:
            raise ConfigError(f'detectors.{name} in {path} must have the type {" or ".join(types)}')
    return values


def _errors(error: ValidationError, prefix: str = '') -> list[str]:
    """One line for each wrong key: the path of the key, then the problem. A tuple of pydantic is a list of the file."""
    return [
        f'{prefix}{".".join(map(str, e["loc"]))}: '
        + e['msg'].removeprefix('Value error, ').replace('tuple', 'list').replace('Tuple', 'List')
        for e in error.errors()
    ]


def load_settings(config: str | None = None) -> Settings:
    """Read the settings from the configuration file. See ``config_path``. The file wins over the defaults.

    The detectors are those of the file, in the order of the file. One ``ConfigError`` has each error of the
    file. A missing token is one of these errors. The settings do not have the token. See ``ha_token``.
    """
    path = config_path(config)
    values = read_file(path)
    errors: list[str] = []
    types = detector_types()
    detectors: dict[str, Detector] = {}
    found = values.pop('detectors')
    if not found:
        errors.append('detectors: Add one detector or more')
    for name, rules in found.items():
        kind = types[rules.pop('type')]
        if isinstance(kind, str):
            errors.append(f'detectors.{name}.type: {kind}')
            continue
        try:
            detectors[name] = kind.model_validate(rules)
        except ValidationError as e:
            errors += _errors(e, f'detectors.{name}.')
    for name, detector in detectors.items():
        for i, other in enumerate(detector.overrides):
            if other == name:
                errors.append(f'detectors.{name}.overrides.{i}: a detector cannot override itself')
            elif other not in found:
                errors.append(f'detectors.{name}.overrides.{i}: {other} is not a detector')
    tabs = values.get('tabs')
    for tab, keys in tabs.items() if isinstance(tabs, dict) else ():
        for key in ('detectors', 'hidden_detectors'):
            names = keys.get(key) if isinstance(keys, dict) else None
            for i, other in enumerate(names if isinstance(names, list) else ()):
                if other not in found:
                    errors.append(f'tabs.{tab}.{key}.{i}: {other} is not a detector')
    try:
        ha_token()
    except ConfigError as e:
        errors.append(str(e))
    try:
        settings = Settings(detectors=detectors, **values)
    except ValidationError as e:
        errors += _errors(e)
    if errors:
        raise ConfigError('\n'.join([f'{len(errors)} error{"" if len(errors) == 1 else "s"} in {path}:', *errors]))
    return settings
