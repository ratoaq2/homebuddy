# Add a detector type

A detector type is one class with fields and one method. This page is for a built-in type, and for a type of
a different package.

## The class

`homebuddy/detector.py` has the base class `Detector`. `homebuddy/model.py` has the class `Event`.
`homebuddy/fields.py` has the field types.

```python
from datetime import datetime

from homebuddy.detector import Detector
from homebuddy.fields import Duration, Positive, Sensor
from homebuddy.model import Event, History


class Above(Detector):
    """A device runs when the value of the sensor is above ``min_w``."""

    sensor: Sensor
    min_w: Positive
    min_duration: Duration

    def detect(self, data: History, start: datetime, end: datetime) -> list[Event]:
        points = data.numbers(self.sensor)
        ...
```

## The fields

- `Detector` is a frozen pydantic model. The fields of the type are the keys of the detector in the
  configuration file. The type of a field is its check. A field without a default is a necessary key. A key
  that is not a field is an error. There is no second list of the keys.
- `fields.py` has the field types: `Sensor`, `Text`, `Positive`, `PositiveInt`, `Entities`, `Range`,
  `Duration` and `DurationRange`.
- A field with the type `Sensor` or `Sensor | None` is an input of the detector. homebuddy loads the history
  of each one. The type does not write a list of its sensors.
- `name` and `overrides` are fields of `Detector`, so each type has them.
- A type has no key for the page. The `tabs` section of the file says which tab shows a detector.
- A default must be correct for most houses. A value of one house is a necessary key.

Follow the rules for key names in [`AGENTS.md`](../AGENTS.md#configuration-keys).

## The `detect` method

`detect` is the only necessary method. It gets one data object:

| Call | Result |
| --- | --- |
| `data.readings(sensor)` | Each state of the sensor, also a text. |
| `data.numbers(sensor)` | The states that are numbers. A power in kW is in watts. |
| `data.unit(sensor)` | The unit of the sensor in Home Assistant. |

`start` and `end` are the limits of the search. `data` can have a margin before and after them, so an event
that crosses a limit keeps its real start and end.

`detect` gives a list of `Event`:

- An event has a `start` and an `end`. The other fields are optional and have a keyword: `label`, `power_w`,
  `energy_kwh` and `accepted`. For example, `Event(start, end, label='Cotton 40', energy_kwh=0.7)`.
- Set `power_w` or `energy_kwh` only when the detector knows the value. Without them, the page estimates the
  power from the sensor of a power tab.
- Set `estimate_power = False` on a type whose events must not get an estimate of their power.
- Set `accepted=False` for a candidate that the rules refuse. Only the debug data shows it.
- A type that needs more data for its debug data makes a subclass of `Event`, as `Run` in `level.py` and
  `Candidate` in `pulse.py`.

Raise `SensorError` of `homebuddy/model.py` when a sensor does not have what the type needs, for example a
wrong unit. Start the text with the key. The page shows it with the path of the detector.

## The optional methods

`levels` and `debug` are optional. They get the same data object. See `Detector`.

- `levels` gives the levels of the first sensor of the detector, by name. The chart shows a line for each
  one.
- `debug` gives `Table` objects of `homebuddy/model.py`, by the title of the table. A table has the titles of
  its columns and one tuple of values for each row. A value is a time, a number or a text. The page makes the
  text of each value. Round a number in the detector. For example,
  `{'Peaks': Table(('Time', 'Power (W)'), [(peak.start, round(peak.power_w))])}`.

A detector does not format a time or a number, and it does not get the time zone.

The page in `homebuddy/ui/` shows a new type without a change. It draws only the data of these parts.

## A built-in type

1. Add the module `homebuddy/detectors/<type>.py`.
2. Add the type to `DETECTORS` in `homebuddy/detectors/__init__.py`.
3. Add tests with invented data. See [CONTRIBUTING.md](../CONTRIBUTING.md#no-data-of-a-real-house).
4. Add the type to [`docs/detectors.md`](detectors.md), `README.md` and `homebuddy.example.yml`.

## A type of a different package

A different package adds a type with an entry point in the `homebuddy.detectors` group. The name of the entry
point is the name of the type:

```toml
[project.entry-points."homebuddy.detectors"]
above = "mypackage.above:Above"
```

A built-in type wins over a type of a package with the same name. The log then has a warning.

Install only a package that you trust. A package with a detector type runs its code in homebuddy, and that
code can read the Home Assistant token.

A wrong type of a package does not stop homebuddy. The page shows the error only when a detector of the file
uses that type:

```
detectors.heater.type: Cannot load the detector type `above` of `mypackage.above:Above`: No module named 'mypackage'
detectors.heater.type: The detector type `above` of `mypackage.above:Above` must be a subclass of homebuddy.detector.Detector
```
