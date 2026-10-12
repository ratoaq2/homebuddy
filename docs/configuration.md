# Configuration

This page gives each key of the configuration file. The [README](../README.md) shows a small file.
[`homebuddy.example.yml`](../homebuddy.example.yml) is a full file with comments.

## The token

homebuddy reads the Home Assistant token from the `HA_TOKEN` environment variable. A `.env` file in the
current folder, or in a folder above it, can set the variable. homebuddy reads `.env` one time, when it starts.
Copy `.env.example` to `.env` and fill it in:

```
HA_TOKEN=your-long-lived-access-token
```

To get a token in Home Assistant, go to Profile > Security > Long-lived access tokens > Create token.

A token has the rights of its user. homebuddy only reads from Home Assistant. So make a user in Home Assistant
that is not an administrator, and make the token for that user.

The token is not permitted in the configuration file. The key `ha_token` is an error.

## The configuration file

The file is YAML (`.yml` or `.yaml`). homebuddy reads one file only: the first one that exists in this order.
There is no merge of files.

1. The file that you give with `--config`.
2. `homebuddy.yml` in the current folder.
3. `config.yml` in the user configuration folder:
   - Linux: `~/.config/homebuddy/`
   - macOS: `~/Library/Application Support/homebuddy/`
   - Windows: `%LOCALAPPDATA%\homebuddy\homebuddy\`

The page reads the file when it opens, and when you click "Load again". So you can change a value, click
"Load again", and see the result.

## A full example

The example is an invented house. It has one detector of each type.

```yaml
home_assistant:
  url: http://homeassistant.local:8123
timezone: Europe/Berlin             # optional: the time zone of your home
date_format: '%Y-%m-%d %H:%M:%S'    # optional: Python strftime format
theme: system                       # optional: the theme of the page: light, dark or system
copy_columns: [start, end]          # optional: the columns that the copy button of a row copies

tabs:
  power:
    sensors: [sensor.grid_power]    # the sensor of the chart
  discharge:
    name: Air conditioner           # optional: the page shows this name
    sensors: [sensor.discharge_temperature]

detectors:
  car:
    type: level
    sensor: sensor.grid_power       # the power sensor, in W or kW
    levels_w: [4140, 6900, 11040]   # each power that the device can use, in watts
    tolerance: 0.1                  # optional
    min_duration: {minutes: 10}     # optional: homebuddy ignores a shorter run
  well_pump:
    type: pulse
    name: Well pump                 # optional: the page shows this name
    sensor: sensor.grid_power
    step_w: [900, 1100]             # the step up or the step down, in watts
    duration: [30, 90]              # the duration of a run, in seconds
    max_ripple_w: 50                # the power in the run stays within this value
    max_step_difference_w: 100      # optional: the step up and the step down are equal within this value
    side_load_w: [200, 300]         # optional: a second load that can start or stop in the run
    min_gap: {minutes: 5}           # optional: homebuddy refuses a pulse that has a second pulse in this time
  air_conditioner:
    type: ramp
    sensor: sensor.discharge_temperature
    rise_per_minute: 5              # a faster rise starts a run
    fall_per_minute: 4              # a faster fall ends a run
    min_rise: 25                    # the minimum rise from the start to the peak
    max_pause: {minutes: 5}         # optional: a new fast rise in this time continues the run
    overrides: [car]                # optional: a run removes a run of the car of the same time
  washing_machine:
    type: state
    sensor: sensor.washing_machine_state
    idle_states: [idle]             # the states of the sensor when the device does not run
    energy_sensor: sensor.washing_machine_energy    # optional: the energy of a run, in kWh or Wh
  heater:
    type: threshold
    sensor: sensor.heater_plug_power    # the power sensor of the device, in W or kW
    min_w: 10                       # the device runs when the power is above this value
```

## Global keys

| Key | Meaning |
| --- | --- |
| `home_assistant` | Necessary. A section with one key, `url`: the address of Home Assistant. It must start with `http://` or `https://`. |
| `tabs` | Necessary. One tab or more. See [Tabs](#tabs). |
| `detectors` | Necessary. One detector or more. See [Detectors](#detectors). |
| `timezone` | Optional. The time zone of your home, for example `Europe/Berlin`. Without it, homebuddy uses the time zone of Home Assistant. |
| `date_format` | Optional. A Python `strftime` format. The default is `'%Y-%m-%d %H:%M:%S'`. |
| `theme` | Optional. `light`, `dark` or `system`. The default is `system`: the theme of your computer. |
| `copy_columns` | Optional. The columns that the copy button of a row copies. See [The copy button](page.md#the-copy-button). |

A key that homebuddy does not know is an error.

With `http`, the token goes over the network as clear text. Use `https` when Home Assistant is not on the same
trusted network as homebuddy.

A sensor is an entity id of Home Assistant, for example `sensor.grid_power`. A different text is an error.

## Tabs

`tabs` has the tabs of the page, in the order of the file. Each tab has an id and these keys:

| Key | Meaning |
| --- | --- |
| `sensors` | Necessary. The sensors of the chart, in a list. Each sensor is a line. The first sensor is the sensor of the tab. An entry can have keys: see [A smooth line](#a-smooth-line). |
| `name` | Optional. Without it, the tab shows the name of the sensor from Home Assistant. |
| `detectors` | Optional. The names of the detectors that the tab shows, in the order of the lanes. |
| `hidden_detectors` | Optional. The names of the detectors whose rows the events table does not show when the page opens. |

A sensor is a power sensor when Home Assistant gives it the device class `power`. Its unit can be W or kW.
A power tab is a tab whose sensor is a power sensor.

### The detectors of a tab

A tab without `detectors` has a default:

- A power tab shows each detector of the file. Each device of the house is behind the main meter, so each
  event is an event of the power.
- A tab of a different sensor shows only the detectors that read its sensor.

`detectors: []` gives a chart with no detector.

In the example, the `power` tab shows each detector. The `discharge` tab shows only the `air_conditioner`
detector. The sensor of the `heater` detector and the sensor of the `washing_machine` detector are in no tab,
so they have no chart.

### Hide the rows of a detector

`hidden_detectors` is for a detector with many events, for example a heater with a thermostat. The chart
shows its lane. The events table does not show its rows until you click its filter:

```yaml
tabs:
  power:
    sensors: [sensor.grid_power]
    hidden_detectors: [heater]
```

### More than one line in a chart

A tab can have more than one sensor, for example the power of the grid and the power of the solar panels:

```yaml
tabs:
  power:
    sensors: [sensor.grid_power, sensor.solar_power]
```

- The first sensor is the sensor of the tab. The events, the levels and the default of `detectors` use it.
- Each other sensor is one more line of the chart, with a light area below it. The second line is amber and
  the third line is green, as solar and a battery in Home Assistant. So put the solar sensor second.
- With more than one line, the chart shows a legend with the name of each sensor from Home Assistant. A click
  on a name hides its line.
- The lines have one axis. Each sensor must have the class and the unit of the first one. A different sensor
  gives a message with the path of its entry.

### A smooth line

An entry of `sensors` is an entity id, or a map with these keys:

| Key | Meaning |
| --- | --- |
| `sensor` | Necessary. The entity id. |
| `smooth` | Optional. A duration. The line shows the average of the sensor in each window of this time. |

Use `smooth` for a sensor with many fast changes, for example the power of the solar panels:

```yaml
tabs:
  power:
    sensors:
      - sensor.grid_power
      - sensor: sensor.solar_power
        smooth: {minutes: 5}
```

- `smooth` changes only the line of the chart. The detectors and the values of the events table always use
  each value of the sensor.
- The time of each value is its weight in the average.
- A line with `smooth` does not show a short run. For example, a run of 60 seconds disappears in a window of
  5 minutes. Its bar in the lane stays. So think before you set `smooth` on the first sensor of a tab.

## Detectors

Each entry of `detectors` has a name and a type. `type` is necessary. The name does not give the type. The
file can have many detectors of each type, in any order.

These keys are for each type:

| Key | Meaning |
| --- | --- |
| `type` | Necessary. `level`, `pulse`, `ramp`, `state` or `threshold`, or a type of a different package. |
| `sensor` | Necessary. The sensor that the detector reads. |
| `name` | Optional. The page shows it in place of the name of the detector in the file. |
| `overrides` | Optional. A list of detector names. See [Conflicts between detectors](detectors.md#conflicts-between-detectors). |

These keys are also necessary:

| Type | Necessary keys |
| --- | --- |
| `level` | `levels_w` |
| `pulse` | `step_w`, `duration`, `max_ripple_w` |
| `ramp` | `rise_per_minute`, `fall_per_minute`, `min_rise` |
| `state` | `idle_states` |
| `threshold` | `min_w` |

[Detectors](detectors.md) gives each key of each type, and how each type works.

## Values

### Durations

A duration has three forms, as in Home Assistant. Each of these lines is 90 minutes:

```yaml
min_duration: 5400                      # a number of seconds
min_duration: '01:30:00'                # a text: hours, minutes, seconds
min_duration: {hours: 1, minutes: 30}   # a map with days, hours, minutes or seconds
```

### Power and ranges

A key with a power has the suffix `_w`. Its value is in watts, also when the sensor is in kW.

A range is a list of two values, the low one first: `step_w: [900, 1100]`.

### Texts that YAML changes

Put a state such as `off`, `on`, `yes` or `no` in quotes: `idle_states: ['off']`. Without the quotes, YAML reads
it as true or false.

## Errors

When the file has errors, the page shows each error, with the path of its key:

```
2 errors in homebuddy.yml:
detectors.well_pump.step_w: the low value must be first
detectors.well_pump.max_riple_w: Extra inputs are not permitted
```

A missing token is one of these errors. Correct the file and click "Load again".

A sensor that does not have what a detector needs also gives a message on the page, with the key of the
detector. For example, `energy_sensor` of a `state` detector must be in kWh or Wh.
