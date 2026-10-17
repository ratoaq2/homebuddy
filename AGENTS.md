# homebuddy

Web page: finds device events in the sensor history of Home Assistant.

The page is the only interface. No command line output of data.

## Commands

`uv` only (not poetry or pip).

```
uv sync
uv run pytest -q --tb=short tests
uv run ruff check .
uv run ruff format .
uv run mypy homebuddy tests
uv run homebuddy
bash scripts/test.sh
```

`scripts/test.sh` runs all the checks of CI.

## Code: lazy senior dev

Lazy means less code, not less care. First understand the problem: read the task and trace the real flow.
Then stop at the first step that works:

1. Is the change necessary? (YAGNI)
2. Does homebuddy already have it? Use it again.
3. Does the standard library or an installed dependency do it? Use it.
4. Only then, write the minimum code.

- Bug fix: fix the root cause, not the symptom. Check every caller of the function that you change.
- No abstraction, dependency, or option that nobody asked for. Delete before you add.
- Not lazy about: errors that lose data, tests, and what the user asked for.
- No default in the Python code for a value of one house: entity id, time zone, device value. Such a key is
  necessary, or it has a neutral default.
- Strict mypy. Narrow `X | None` at the point of use.
- Use quiet flags (`-q --tb=short`). Never send full logs into the context.

Adapted from [ponytail](https://github.com/DietrichGebert/ponytail) (MIT).

## How the rules work

This file has the decisions of the project, as rules. An AI assistant loads it in each session. A contributor
reads it one time.

- A decision that the next session must obey is a rule in this file. A decision that is only in a chat or in
  `plans/` is lost.
- There is no log of decisions. Change or remove the rule when the decision changes, in the commit of the code.
  The git history has the dates.
- Write a rule that an assistant can obey and a review can check. Prefer a test to a rule, when a test is
  possible, as `tests/test_layers.py`.
- The reason for each main rule is in [`docs/architecture.md`](docs/architecture.md). Read it before you change
  the architecture. Add the reason there when a new rule is not obvious.

## No data of a real house

homebuddy is public. No tracked file shows the setup of a real house: not the code, the docs, the examples,
the tests, a screenshot or a commit message.

- No real entity id, device name, brand, state name, address or measured value. No copy of a real history.
- The values of a real house go only in `homebuddy.yml`, `.env` and `plans/`. Git ignores them.
- Use the invented house in each example and each test:

  | Detector | Type | Sensor |
  | --- | --- | --- |
  | `car` | `level` | `sensor.grid_power` |
  | `well_pump` | `pulse` | `sensor.grid_power` |
  | `air_conditioner` | `ramp` | `sensor.discharge_temperature` |
  | `washing_machine` | `state` | `sensor.washing_machine_state` |
  | `heater` | `threshold` | `sensor.heater_plug_power` |

- Use round invented values, for example `step_w: [900, 1100]`. The time zone of the examples is
  `Europe/Berlin`.
- Generate the data of a test in the test. Learn the properties of a signal from real data, then build them
  into generated data.

## Architecture

- The page is the only interface. No CLI, no export of data.
- A detector type has one declaration: it is a pydantic model with `Detector` as its base. Its fields are
  the keys of the configuration file, and the type of a field is its check. No second list of the keys.
- A check that two types need is a field type in `homebuddy/fields.py`, for example `Range`.
- A field of a detector type with the type `Sensor` is an input. The base class finds these fields, and
  homebuddy loads the history of each one. A type does not write a list of its sensors.
- `detect(data, start, end)` is the only necessary method of a type. `data` is one `History` object. A new
  input for the detectors is a new member of `History`, not a new argument.
- A detector gives `Event` objects. A type that needs more data for its debug data makes a subclass.
  No method of the detector that gets one event back to give one value of it.
- `debug(found, data)` is the only method that gets the events of the detector. It gives `Table` objects
  with values: a time, a number or a text. A detector does not format a time or a number, and it does
  not get the time zone. `ui/debug.py` makes the text.
- A wrong configuration file or a wrong detector type of a different package gives a message with the path of the key. Never a traceback.
  One `ConfigError` has each error.
- The page in `homebuddy/ui/` shows a new detector type without a change.
- The tabs are in the configuration file. A detector does not know the page: a detector type has no key
  for a tab, a chart or a lane. A key of the page for a detector is a key of the tab, for example
  `hidden_detectors`.
- A tab has one line for each entry of `sensors`. The first sensor is the sensor of the tab: the events,
  the levels and the default of `detectors` use only it. The lines have one axis, so each sensor has the
  class and the unit of the first one. No second axis.
- An entry of `sensors` is an entity id, or a map with the key `sensor` and the keys of its line, for
  example `smooth`. A key of one line is a key of its entry, not a key of the tab.
- A key of a line changes only the line. `smooth` shows averages in the chart. The detectors and the
  values of the events always use each value of the sensor. `ui/chart.py` calculates the averages. The
  result of the search has each value.
- A conflict is explicit. An event removes the same event of a different detector only with `overrides`.
  No rule decides a conflict from the number or the type of the sensors.
- The class and the unit of a sensor come from Home Assistant. A power sensor has `device_class: power`.
  No code compares a unit to decide that a sensor is a power sensor. `data.numbers` gives watts for a
  power sensor in W or in kW.
- A sensor that does not have what a detector needs gives a `SensorError` with the key of the detector.
  The page shows it. Never a traceback.
- homebuddy reads one YAML configuration file. No merge of files, no second format. The page reads the
  file when it opens, and at each click on "Load again".

## Layers

Each module has one concern. The imports go in one direction:

`model`, `fields` <- `detector` <- detector types <- `config` <- `search` <- `ui`

| Module | Concern | Can import from homebuddy |
| --- | --- | --- |
| `model.py` | The data: `Point`, `Reading`, `History`, `Event`, `SensorError` | Nothing |
| `fields.py` | The field types of the configuration file, for example `Sensor` and `Duration` | Nothing |
| `detector.py` | The contract of a detector type: `Detector` | Only `model` and `fields` |
| `detectors/<type>.py` | One detector type | Only `model`, `fields` and `detector` |
| `detectors/__init__.py` | The list of the detector types | Only `detector` and its types |
| `config.py` | The configuration file | Only `fields`, `detector` and `detectors` |
| `homeassistant.py` | The HTTP client of Home Assistant | Only `model` |
| `conflicts.py` | The conflicts | Only `model` |
| `result.py` | The result of a search for one tab: `Row`, `SearchResult` | Only `model`, `detector` and `conflicts` |
| `search.py` | The search, the `Source` | Only `config`, `model`, `conflicts` and `result` |
| `ui/` | The page | Each module |

- A module out of a package imports the package, and never a module in it. `config.py` imports
  `homebuddy.detectors`, and never `homebuddy.detectors.level`. This rule is also for the page.
- A type that two layers use is in a root module, not in a package.
- `tests/test_layers.py` checks these rules and fails for an import cycle. A new module gets its rule in
  `PERMITTED` of that test.
- The search gets its data source as an argument: an object with `history`, `unit`, `is_power`, `name`
  and `timezone`. The search does not import the client. A test gives a fake source, and does not replace
  a function of a module.
- Only the client knows the attribute names of Home Assistant, for example `device_class`. The search
  asks the source: `unit(sensor)`, `is_power(sensor)`, `name(sensor)`.
- No text for the page out of `ui/`: no title, no unit text, no format of a value. The result of the
  search has numbers. `ui/events.py` makes each text of an event, for the table and for the tooltips.
  `ui/names.py` selects the name of a tab and of a detector for the page.
- The result of the search has no settings. The page gives the date format and `copy_columns` to its
  functions.
- A text from outside is never code. Names, units and states come from Home Assistant, and a date comes
  from the browser. A value in JavaScript source goes through `json.dumps`. A value in HTML goes through
  `html.escape`. No exception for a value that looks safe.
- `home_assistant.url` has the field type `HttpUrl`: only `http://` and `https://`. A sensor has the field type
  `Sensor`: an entity id with the form `domain.object_id`. The client encodes a sensor in the query of a
  request. No sensor is in the path of a request.
- The token of Home Assistant is only in the `HA_TOKEN` environment variable and in the `HomeAssistant`
  client. It is not in `Settings`, not in a result, not in a log, and not in an argument of the command.
  Only the page gets the token from `config.ha_token()`, to make the client. `load_settings` calls it
  only to check that the token exists.
- The time zone comes from `search.timezone(settings, source)`: the key of the file, or Home Assistant.

## Configuration keys

- Full words: `timezone`, not `tz`. `min_` and `max_` are always "minimum" and "maximum".
- A limit has the prefix `min_` or `max_`. A range has no prefix, and its low value is first.
- A power key has the suffix `_w`.
- A duration has no unit in its key. Its field type is `Duration`: a number of seconds, a text `HH:MM:SS`,
  or a map, as in Home Assistant.
- The name of a detector for the page is `name`. The name of a tab for the page is also `name`.
- The sensor that a detector reads is `sensor`. A second input ends with `_sensor`. The field type is
  `Sensor`.
- A key that refers to detectors is a list of their names in the file, for example `overrides`.
- A key that refers to columns of the events table has their ids, for example `copy_columns: [start,
  power]`. Never a title of a column.
- A change of a key also changes `docs/configuration.md`, `docs/detectors.md`, `homebuddy.example.yml` and the
  tests. It changes `README.md` when the README shows the key.

## Glossary

Use one word for one thing, in the code and in the text.

| Word | Meaning | Do not use |
| --- | --- | --- |
| sensor | An entity of Home Assistant that homebuddy reads | device, input |
| detector | One entry of `detectors` in the configuration file: a type with its values | rule, plug-in |
| detector type | The class that a detector uses, for example `pulse` | kind, detector class |
| event | What a detector finds: a time with a start and an end | detection. "Session" and "run" are only for the events of one type |
| candidate | An event that the rules of its detector refuse. Only the debug data shows it | rejected event |
| tab | One entry of `tabs` in the configuration file: the chart of a sensor, with the events of some detectors | chart (for the full tab), view, page |
| power sensor | A sensor with `device_class: power` in Home Assistant | a sensor in W |
| power tab | A tab whose sensor is a power sensor | power chart |
| source | Where the search gets its data: an object with `history`, `unit`, `is_power`, `name` and `timezone` | API, backend |
| client | The `HomeAssistant` object. It is one source | API |
| page | The web page of homebuddy, in `homebuddy/ui/` | UI, frontend, app |

## Docs

`README.md` is short: what homebuddy is, a quick start, and links. The details are in `docs/`. When a change
makes a statement in a doc wrong, fix it in the same commit.

| File | Content |
| --- | --- |
| `docs/configuration.md` | Each key of the configuration file |
| `docs/detectors.md` | The keys of each detector type, and how each type works |
| `docs/page.md` | The command, and what the page shows |
| `docs/docker.md` | The image and the reverse proxy |
| `docs/detector-types.md` | How to add a detector type |
| `docs/architecture.md` | The design and the reason for each main rule |

## Git

- One-line Conventional Commits subject. Add `Closes #<n>` for a fix. No attribution trailers.
- Bug fix: commit the failing test first, then the fix.

## Writing

All text follows ASD-STE100 Simplified Technical English. Most readers are not native English speakers.

- One idea in each sentence. Short sentences.
- Active voice and simple tenses.
- Common words. Use one word for one thing.
- No semicolons, no phrasal verbs, no idioms, no filler, no emoji.
- Do not change code, commands, logs, or quotes.

## Skills

- The skills are in `.claude/skills/<name>/SKILL.md`. Read the `SKILL.md` before you do its task.
- `plan`: turn an approved spec into `plan.md` (steps, tests, commits), then stop for approval.
- Local work lives in `plans/<issue>-<slug>/`. Each item has a `README.md`, a `spec.md`, and a `plan.md`.
