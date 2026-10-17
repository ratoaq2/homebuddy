# The page

The page is the only interface of homebuddy. This page gives the command that starts it, and what it shows.

## Start the page

```bash
homebuddy                       # opens http://127.0.0.1:8080 in the browser
homebuddy --native              # opens a desktop window (needs the "desktop" extra)
homebuddy --host 0.0.0.0        # other devices on your network can connect
homebuddy --config my.yml       # use this configuration file
```

| Option | What it does |
| --- | --- |
| `--host` | The address to bind. The default is `127.0.0.1`: only your computer can connect. |
| `--port` | The port. The default is 8080. |
| `--native` | Open a desktop window, not the browser. Install `homebuddy[desktop]` for it. |
| `--no-show` | Do not open the browser. |
| `--config` | The configuration file. See [The configuration file](configuration.md#the-configuration-file). |

homebuddy must run on a computer that can connect to Home Assistant.

## The day

The page opens on today. Use the previous day and next day buttons, the date button, or Today to go to a
different day.

When the page shows today, it loads new data each 60 seconds. This load does not read the configuration file
again. At midnight in the time zone of the home, the page goes to the new day, so a wall display always shows
today. A day in the past that you select stays. "Load again" reads the file and loads the data.

An event that crosses midnight shows on the two days, with its real start and end.

Home Assistant keeps the detailed history for about 10 days by default. An older day shows "No data".

The time zone comes from `timezone` in the configuration file, or from Home Assistant without that key.

## The tabs

The page shows one tab of the configuration file at a time. When the file has two or more tabs with data in
the day, the header has a row of tabs. Click a tab to see it. The selected tab stays when you
change the day.

A tab and the title of its chart show the `name` of the tab, or the name of its sensor from Home Assistant, or
the entity id when it has no name.

A tab whose sensor has no numbers in the day does not show.

## The chart

- The chart shows the sensor of the tab for the day. A power sensor shows kW. A different sensor shows its unit
  from Home Assistant.
- The levels of the sensor are horizontal lines in the chart, with their values. A tab of the sensor that an
  `level` detector reads shows the baseline.
- A line of a sensor with `smooth` shows averages. See [The keys of a line](configuration.md#the-keys-of-a-line).
- Move the pointer on the chart to see the value of the sensor at that time.
- Use the mouse wheel or the slider to zoom. Click Full day to see the full day again.

### The lanes

Below the chart is one lane for each detector of the tab that has events in the day.

- Each event is a bar in the lane, from its start to its end. Move the pointer on a bar to see the values of
  its event and its label. The label of a run of a `state` detector is its first state.
- The lanes have the time axis and the zoom of the chart.
- At the left of a lane is the name of the detector and its color. A detector has the same color in each
  chart. The color comes from the position of the detector in the file.
- At the right is the number of its events, and their energy in a power tab.
- On a narrow screen, for example a phone, the chart has the full width of the screen. The name and the
  numbers of a detector are then in its lane, above its bars.

## The events table

The table has the events of each detector of the tab: detector, start, end, duration, label, and the value
columns of the sensor. The latest event is the first row. The number of a row is the position of its event in
the day.

- Click a row to zoom the chart to that event. The page also moves the chart into the window.
- The sensor gives the value columns, the same ones for each detector. A power tab has the power and the
  energy of the event. A different tab has the value of the sensor at the start of the event and its largest
  value in the event.

### The filters

When two or more detectors have events, the top right of the table has one filter for each detector. Click a
filter to hide the rows of that detector. Click it again to show them.

`hidden_detectors` of a tab hides the rows of a detector when the page opens. Your choice stays until you open
the page again or change the configuration file.

### The copy button

Each row has a copy button at its end. It copies the values of the row with a tab between them, so you can
paste them into the cells of a spreadsheet.

`copy_columns` in the configuration file selects the columns and their order. For example, `[start, end]`
copies only the start and the end. Without `copy_columns`, the button copies each column. The ids of the
columns are:

| Id | Column |
| --- | --- |
| `detector`, `start`, `end`, `duration`, `label` | The columns with these titles |
| `power`, `energy` | "Power (kW)" and "Energy (kWh)", in a power tab |
| `start_value` | The value of the sensor at the start of the event, in a different tab |
| `peak` | The largest value of the sensor in the event, in a different tab |

A different text is an error. A column that the tab does not have gives no value.

The copy buttons work only on `localhost` or on HTTPS.

## The power and the energy of an event

In a power tab, the power of an event is the average power in the event, minus the average power of the
5 minutes before it. The energy is this power multiplied by the duration. These are estimates: a second load
that starts or stops in the event changes them.

Some detector types know the value, so there is no estimate:

| Type | Power | Energy |
| --- | --- | --- |
| `level` | The level of the run | The level for the duration |
| `pulse` | The power of the step | The power for the duration |
| `threshold` | The average power of its own sensor | The power for the duration |
| `state` | No power | The value of `energy_sensor`, or empty |

## Debug data

The settings button at the top right has "Show debug data". It loads the page again.

The page then shows the debug data of each detector, on the card of each tab that shows the detector. The
`level` detector shows the data points of each run. A `pulse` detector shows each candidate with the result of
each rule. Use this data to set the values of a detector.

The debug data also lists the events that a different detector removed. See
[Conflicts between detectors](detectors.md#conflicts-between-detectors).

## The theme

The page uses the theme of your computer. Set `theme` in the configuration file to `light` or `dark` to select
one theme. The button at the top right changes the theme. The page does not keep this selection when you load
it again.

The page has the look of Home Assistant: the Roboto font, the primary color `#03a9f4` in the two themes, and
the neutral grays of the dark theme of Home Assistant.

## Install the page on a phone

On a phone, you can install the page as an app. The page must use HTTPS with a certificate that the phone
trusts. See [Put homebuddy behind a reverse proxy](docker.md#put-homebuddy-behind-a-reverse-proxy).

Open the page in Chrome, open the menu and select "Add to Home screen", then "Install". The icon opens
homebuddy in its own window.

## Show the page in Home Assistant

Add a webpage card to a dashboard of Home Assistant, with the URL of homebuddy. When Home Assistant uses HTTPS,
homebuddy must also use HTTPS. See [Put homebuddy behind a reverse proxy](docker.md#put-homebuddy-behind-a-reverse-proxy).

In a frame, the header has only the tabs and the day buttons, on the background of the page. The logo, the
settings button and the theme button do not show. Add `?embed=1` to the URL to see this header without a
frame, or `?embed=0` to see the full header in a frame.

## Security

The page has no login. The Home Assistant token stays on the server and does not go to the browser. But
anyone who can open the page can run searches. The power data of a house shows when people are at home.

Use `--host 0.0.0.0` only on a network you trust. For a different network, see
[Put homebuddy behind a reverse proxy](docker.md#put-homebuddy-behind-a-reverse-proxy).
