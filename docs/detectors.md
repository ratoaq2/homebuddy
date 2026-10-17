# Detectors

A detector reads the history of a sensor and finds one type of event. This page gives the keys of each
detector type, and how each type works. The names in `code` are keys of the
[configuration file](configuration.md).

| Type | Event | Reads |
| --- | --- | --- |
| [`level`](#level) | A long run of a device with a known, constant power, for example a car at a charger that has no sensor | The power sensor of the house |
| [`pulse`](#pulse) | A short run of a load with a constant power, for example a well pump | The power sensor of the house |
| [`ramp`](#ramp) | A run of a device that makes a value rise fast and then fall fast, for example an air conditioner from its discharge temperature | A sensor with numbers |
| [`state`](#state) | A run of a device that shows its state as a text, for example a washing machine | A sensor with a text |
| [`threshold`](#threshold) | A run of a device that has its own power sensor, for example a heater on a smart plug | The power sensor of the device |

Each type also has the keys `type`, `sensor`, `name` and `overrides`. See
[Detectors](configuration.md#detectors) in the configuration page.

## How to set the values of a detector

1. Write the detector with your best estimate of each value.
2. Open the page on a day with a known event.
3. Click the settings button and set "Show debug data". The page shows the debug data of each detector. For
   example, a `pulse` detector shows each candidate with the result of each rule.
4. Change a value in the file and click "Load again".

## Level

```yaml
detectors:
  car:
    type: level
    sensor: sensor.grid_power
    levels_w: [4140, 6900, 11040]
```

| Key | Meaning |
| --- | --- |
| `sensor` | Necessary. The power sensor, in W or kW. |
| `levels_w` | Necessary. Each power that the device can use, in watts. One value or more. |
| `tolerance` | Optional. 0.1 accepts a run 10 % below the lowest level. The default is 0.1. |
| `min_duration` | Optional. homebuddy ignores a shorter run. The default is 10 minutes. |

Use this type for a device that has no sensor of its own and that uses a constant power for a long time.

### Example: a car at a charger that has no sensor

A charger gives a constant power for each current that you can set. Calculate one level for each current:

`level = phases x voltage x current`

| Charger | 6 A | 10 A | 16 A |
| --- | --- | --- | --- |
| 1 phase, 230 V | 1380 W | 2300 W | 3680 W |
| 3 phases, 230 V | 4140 W | 6900 W | 11040 W |

When the sensor measures less than this power, write the measured power. "Show debug data" shows the measured
power of each run.

If your charger has a power sensor in Home Assistant, use a [`threshold`](#threshold) detector with that
sensor. If it has a status sensor, use a [`state`](#state) detector. These are more exact.

### How it works

1. The baseline is the 10th percentile of the power of the day.
2. A run starts when the power is at or above `baseline + lowest level x (1 - tolerance)`. The lowest level is
   the minimum of `levels_w`.
3. A run ends when the power stays below that threshold for more than 1 minute. A shorter drop also ends the
   run when the level changes at the drop: the level of the 2 minutes after the drop is different from the
   level of the 2 minutes before it. A restart of Home Assistant can give a short drop.
4. homebuddy ignores a run shorter than `min_duration`.
5. homebuddy ignores a run that is not a run of the device:
   - A run does not stop. A run with more than 5 % of its points below the threshold is ignored.
   - The step of the power at the start or at the end of the run is at least
     `lowest level x (1 - tolerance)`. The step is the power of the run minus the power of the house, in the
     2 minutes before the start or after the end. The baseline is the low level of the day, so a smaller load
     gets above the threshold when the house uses more power.
6. The floor of a run is the 10th percentile of its power. The level of the run is the one from `levels_w`
   that is nearest to `floor - baseline`. Other loads in the house add power on top of the device, so they do
   not change the floor.
7. The power of the run is its level. The energy is `level x duration`. It is not the measured power.

A run has no label. The power column shows its level. The chart of the sensor shows the baseline as a
horizontal line.

A different long load in the house with the power of the lowest level or more shows as a run.

## Pulse

```yaml
detectors:
  well_pump:
    type: pulse
    sensor: sensor.grid_power
    step_w: [900, 1100]
    duration: [30, 90]
    max_step_difference_w: 50
```

| Key | Meaning |
| --- | --- |
| `sensor` | Necessary. The power sensor, in W or kW. |
| `step_w` | Necessary. The range of the step up or the step down, in watts. |
| `duration` | Necessary. The range of the duration of a run. |
| `max_step_difference_w` | Necessary. The step up and the step down are equal within this value. |
| `side_load_w` | Optional. The range of the power of a second load that can start or stop with the run. |
| `min_gap` | Optional. homebuddy refuses a pulse that has a second pulse in this time. |

How it works:

1. The sensor can write more than one value in an update. homebuddy keeps the last value of each update.
2. A candidate starts at a step up of the power in `step_w`. With `side_load_w`, the range is wider by the
   power of the second load.
3. The candidate ends at the first step down that is equal to the step up, not later than `duration`. One of
   the two steps is in `step_w`. The two steps are equal within `max_step_difference_w`, or the second load is
   the only difference. A small load that starts or stops with the run makes the two steps different. A step
   up without an equal step down is not a candidate.
4. The sensor can show a step in two updates, when the load starts or stops in the time of an update. When no
   single update is a step, homebuddy adds two updates in the same direction. Two loads can also make such a
   step, so it counts only when the power is stable for two updates before the run and two updates after it:
   each change is within `max_step_difference_w`.
5. The power between the two steps does not count. Other loads can start and stop in the run.
6. A candidate is a run when it obeys each of these rules:
   - duration: the duration is in `duration`, with a margin of 8 seconds.
   - alone: no different candidate is less than `min_gap` before the start or after the end. Each candidate
     counts, also a candidate that a different rule refuses. Without `min_gap`, this rule is always true.

The power of a run is the power of its step.

A different load with the same power and duration shows as a run. With `min_gap`, a load that switches on and
off in a series, for example a load with a thermostat, does not show. A run in the time of such a series also
does not show.

## Ramp

```yaml
detectors:
  air_conditioner:
    type: ramp
    sensor: sensor.discharge_temperature
    rise_per_minute: 5
    fall_per_minute: 4
    min_rise: 25
```

| Key | Meaning |
| --- | --- |
| `sensor` | Necessary. The sensor with the value that rises and falls. It does not have to be a power sensor. |
| `rise_per_minute` | Necessary. A faster rise starts a run. |
| `fall_per_minute` | Necessary. A faster fall ends a run. |
| `min_rise` | Necessary. The minimum rise from the start to the peak. |
| `max_pause` | Optional. A new fast rise in this time continues the run. The default is 5 minutes. |

How it works:

1. homebuddy calculates the rate between each two values of the sensor, for each minute.
2. A run starts at the value before a rise that is faster than `rise_per_minute`.
3. A run ends at its largest value, when a fall that is faster than `fall_per_minute` comes after it.
4. A new fast rise in `max_pause` after a fast fall continues the run. A short stop of the device makes such
   a dip.
5. homebuddy ignores a run that rises less than `min_rise` from its start to its largest value.

A run that has no fast fall yet does not show.

A power tab also shows the runs. homebuddy then estimates the power of a run from the power sensor of the
tab. See [The power and the energy of an event](page.md#the-power-and-the-energy-of-an-event).

## State

```yaml
detectors:
  washing_machine:
    type: state
    sensor: sensor.washing_machine_state
    idle_states: [idle]
    energy_sensor: sensor.washing_machine_energy
```

| Key | Meaning |
| --- | --- |
| `sensor` | Necessary. The sensor that shows the state of the device as a text, for example the name of its program. |
| `idle_states` | Necessary. The states of the sensor when the device does not run. |
| `energy_sensor` | Optional. The sensor with the energy of a run, in kWh or Wh. |

How it works:

1. A run starts when the state is not in `idle_states`.
2. A run ends when the state is in `idle_states` again. A change between two states that are not in
   `idle_states` continues the run.
3. The states `unavailable` and `unknown` of Home Assistant do not change the state of the device.
4. A run that has no end yet stops at the present time.
5. The label of the run is its first state.
6. With `energy_sensor`, the energy of the run is the last value of that sensor in the run that is not 0.
   homebuddy also reads the first minute after the run, because some devices write the energy at the end. Some
   devices set the sensor to 0 at the end.
7. A run without a value of `energy_sensor` has no energy.
8. The unit of `energy_sensor` must be kWh or Wh. A different unit is an error on the page.

A run has no power. homebuddy does not estimate it from the power sensor.

The sensor with the text has no numbers, so a tab cannot show its chart. The power tab shows the runs.

In a YAML file, put a state such as `off`, `on`, `yes` or `no` in quotes: `idle_states: ['off']`. Without the
quotes, YAML reads it as true or false.

When the device has no connection in a run, the energy sensor can show the energy of the run before. The run
then shows that energy until the device writes a new value.

## Threshold

```yaml
detectors:
  heater:
    type: threshold
    sensor: sensor.heater_plug_power
    min_w: 10
```

| Key | Meaning |
| --- | --- |
| `sensor` | Necessary. The power sensor of one device only, for example a smart plug. In W or kW. |
| `min_w` | Necessary. The device runs when the power is above this value. |

How it works:

1. A run starts at the first value of `sensor` above `min_w`.
2. A run ends at the next value that is not above `min_w`.
3. A state that is not a number, for example `unavailable`, does not change the run.
4. A run that has no end yet stops at the present time.
5. The power of the run is its average power from `sensor`. The time of each value is its weight.
6. The energy of the run is its power for its duration.

Each run is an event. There is no minimum duration. Set `min_w` above the power of the device when it does not
run.

The power tab shows the runs, with the power and the energy from `sensor`. `sensor` needs no tab. Add a tab
with `sensor` in its `sensors` if you want its chart.

## Conflicts between detectors

Two detectors can find the same event. For example, the power of an air conditioner can look like a run of the car at
its lowest level. You tell homebuddy which detector wins, with `overrides`:

```yaml
detectors:
  air_conditioner:
    type: ramp
    overrides: [car]
```

- `overrides` is an optional key of each detector: a list of detector names.
- An event of the detector removes the same event of each detector in the list.
- Two events are the same event when their common time is half of their total time, or more.
- A detector without `overrides` removes nothing.

A long run of the car with a run of the air conditioner in it is not the same event, so the two stay. A short
run of the car that is fully in a run of the air conditioner is lost. "Show debug data" lists the removed events, with the
detector that won.

## More detector types

A different package can add a detector type. See [Add a detector type](detector-types.md).
