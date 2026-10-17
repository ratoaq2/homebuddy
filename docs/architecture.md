# Architecture

This page gives the design of homebuddy and the reason for each main choice. The rules that the code must obey
are in [`AGENTS.md`](../AGENTS.md). That file says what. This page says why.

## The flow

```
homebuddy.yml -> config -> search -> result -> page
                             ^
                           source (the Home Assistant client)
```

1. `config` reads one YAML file and makes the `Settings`: the tabs and the detectors.
2. The page makes the client of Home Assistant and gives it to the search as the source.
3. The search loads the history of each sensor that a tab or a detector names, with one request. It gives one
   `History` object to each detector.
4. Each detector gives `Event` objects. `conflicts` removes the events that a detector overrides.
5. The search gives one `SearchResult` for each tab. The result has numbers and no text.
6. The page draws the chart, the lanes and the events table from the result.

homebuddy has no database. The client keeps the history of the last 10 past windows in memory, because the past
does not change. Each other load of the page reads the history from Home Assistant.

## The modules

| Module | Concern |
| --- | --- |
| `homebuddy/model.py` | The data: `Point`, `Reading`, `History`, `Event`, `Table`, `SensorError` |
| `homebuddy/fields.py` | The field types of the configuration file, for example `Sensor` and `Duration` |
| `homebuddy/detector.py` | The contract of a detector type: `Detector` |
| `homebuddy/detectors/<type>.py` | One detector type |
| `homebuddy/detectors/__init__.py` | The list of the detector types, and the types of other packages |
| `homebuddy/config.py` | The configuration file: `Settings`, `Tab`, `ConfigError` |
| `homebuddy/homeassistant.py` | The HTTP client of Home Assistant |
| `homebuddy/conflicts.py` | The conflicts between detectors |
| `homebuddy/result.py` | The result of a search for one tab: `Row`, `SearchResult` |
| `homebuddy/search.py` | The search, and the `Source` that it reads |
| `homebuddy/ui/` | The page: each text, each title, each format |

The imports go in one direction:

`model`, `fields` <- `detector` <- detector types <- `config` <- `search` <- `ui`

`tests/test_layers.py` builds the import graph. It fails for a cycle, and for an import that the layers do not
permit. A rule that a test checks stays true.

## The choices and their reasons

### The page is the only interface

The command `homebuddy` starts the page. No code prints data on the command line or exports data to a file.

- One interface has one set of features to keep correct.
- No argument of the command has the token, so the token does not show in the process list.

### No value of one house in the code

The Python code has no default for an entity id, a time zone or a device value. Such a key is necessary, or it
has a neutral default that is correct for most houses, for example `tolerance: 0.1`. No detector is special: the
detectors are those of the file.

- A missing key gives a clear error. A wrong default gives a wrong result with no message.
- The project is public. The docs, the examples and the tests use an invented house.

### A detector type is a pydantic model

The fields of a type are its only declaration. The type of a field is its check. `Settings` and `Tab` are
pydantic models also.

- One declaration cannot disagree with itself.
- pydantic is already installed, because NiceGUI needs it.
- One `ConfigError` has each error of the file, with the path of each key. The user corrects the file in one
  round.
- The author of a type writes fields and one method.

### A `Sensor` field is an input, and `detect` gets one data object

The base class finds the fields with the type `Sensor`, and homebuddy loads the history of each one.
`detect(data, start, end)` gets one `History` object.

- A type does not write a second list of its inputs.
- A new input for the detectors is a new member of `History`. No detector type changes then.

### Each detector gives `Event` objects

`Event` has a start and an end. The other fields are optional. A type that needs more data for its debug data
makes a subclass.

- The search and the page read fields. They do not call the detector for each event.
- The author of a type writes no class for a simple event.

### The tabs are in the configuration file

A tab names its sensors and, optionally, its detectors. A detector type has no key for the page.

- The user reads a tab and sees all that is on it.
- The page shows a detector type of a different package without a key for the page in that type.
- One detector can show in two tabs, with different settings in each tab, for example `hidden_detectors`.
- Each device of the house is behind the main meter, so a power tab shows each detector by default. A small
  file needs only one tab and the detectors.

### One axis for the lines of a tab

Each sensor of a tab is a line. Each sensor must have the class and the unit of the first one. The colors of
the lines are fixed: blue, amber, green.

- One axis keeps the lines comparable. Two scales in one chart give a wrong picture.
- An entry with only an entity id is the minimum. Home Assistant already has a name for each sensor.
  `name` of an entry is for a name that is long or not clear in Home Assistant. It changes only the legend.
- A key of one line is a key of its entry: an entry can be a map with `sensor` and, for example,
  `smooth`. The user sees the sensor and its keys in one place.
- `smooth` changes only the line of the chart. A detector that reads averages finds different events,
  so the search always uses each value of the sensor.
- The colors are those of Home Assistant for solar and a battery. homebuddy does not know which sensor is
  solar, so the order of the file decides.

### A conflict is explicit

An event removes the same event of a different detector only with `overrides`.

- Only the user knows which device looks like a different one. Two devices that run at the same time are not a
  conflict.
- One line of the file says who wins.
- A number, for example `priority: 10`, needs all the other numbers to have a meaning.
- A subtraction of the power of a measured device from the main sensor gives false steps, because the two
  sensors do not write at the same time.

### The class and the unit of a sensor come from Home Assistant

A sensor is a power sensor when Home Assistant gives it `device_class: power`. `data.numbers` gives watts for
a power sensor in W or in kW. A sensor with a wrong unit gives a `SensorError`.

- Home Assistant already knows the class and the unit. The user does not write them again.
- A wrong unit gives a message, not a wrong value.

W and kW are the only power units that homebuddy knows.

### One YAML file

homebuddy reads one file: the first one that exists. There is no merge and no second format.

- One file has each value. An error has one source.
- The tabs and the detectors refer to each other by name. A merge of two files makes these names hard to
  check.

### The search gets its source as an argument

A source is an object with `history`, `unit`, `is_power`, `name` and `timezone`. The `HomeAssistant` client is
one source. The search does not import the client.

- A test gives a small fake source. It does not replace a function of a module.
- Only the client knows the attribute names of Home Assistant. A second source does not copy them.
- The client keeps the attributes of the sensors and the time zone in a cache for 10 minutes. A new name or
  unit in Home Assistant shows without a restart.

### The result has numbers, and the page makes each text

No module out of `homebuddy/ui/` makes a title, a unit text or a format of a value. The debug data of a
detector has values also: a time, a number or a text. Each column of the events table has an id that does not
change, and `copy_columns` uses these ids.

- A change of a title does not change the configuration file of a user.
- The table and the tooltips cannot show different values for one event.
- The format of a time is in one place, for each detector type. A type of a different package cannot show a
  time in a wrong time zone.
- A later feature can store a result or make a report from it, with no text to read back.

### The time zone comes from Home Assistant

`timezone` is an optional key. Without it, homebuddy uses the time zone of Home Assistant.

- The value of Home Assistant is correct for the home. It is not a default of one house in the code.
- The key stays for a user who wants a different time zone on the page.

### The token is only in the environment and in the client

`Settings` has no token, and a result has no settings. Only the page calls `config.ha_token()`, to make the
client.

- The settings and each result are safe to show, to log and to store.
- A field with a hidden `repr` is not sufficient. The token then still shows in a dump of the model and in a
  validation error.

### A text from outside is never code

Names, units and states come from Home Assistant, where a second person or an integration can set them. A
value in JavaScript source goes through `json.dumps`. A value in HTML goes through `html.escape`. `home_assistant.url`
accepts only `http://` and `https://`. A sensor is an entity id with the form `domain.object_id`, and the
client encodes it in the query of a request.

- One rule without an exception is easy to check in a review.
- The configuration check gives a message with the path of the key. A wrong address or a wrong sensor does not
  get to the client.
- The encoding in the client is a second barrier, for a caller that the configuration did not check.
