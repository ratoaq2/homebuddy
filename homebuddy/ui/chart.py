"""The ECharts options of the chart of a sensor."""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import datetime, timedelta
from html import escape
from typing import Any
from zoneinfo import ZoneInfo

from homebuddy.config import Settings
from homebuddy.model import Event, Point
from homebuddy.result import Row, SearchResult
from homebuddy.ui.events import column_titles, event_texts
from homebuddy.ui.names import detector_name, tab_name
from homebuddy.ui.theme import CHART_COLORS, FONT

CHART_FORMAT = '%Y-%m-%d %H:%M:%S'
ZOOM_MARGIN = timedelta(minutes=2)
FULL_DAY_ZOOM = {'type': 'dataZoom', 'start': 0, 'end': 100}
# The tooltip of an event in a lane shows the text that Python made. See ``event_tooltips``.
EVENT_TOOLTIP = {'trigger': 'item', ':formatter': 'params => params.name'}
# The sizes of the chart in pixels. The left margin has the names of the detectors, the right margin has
# the numbers of their events.
LINE_HEIGHT = 384
LANE_HEIGHT = 22
LANES_BOTTOM = 48
LEFT = 124
RIGHT = 170


def detector_colors(result: SearchResult, dark: bool = False) -> dict[str, str]:
    """The color of each detector, from its position in the file. It is the same one in each chart."""
    detectors = result.detectors
    palette = CHART_COLORS[dark]['detectors']
    return dict(zip(detectors, palette + palette[-1:] * len(detectors), strict=False))


def lane_events(result: SearchResult) -> dict[str, list[Event]]:
    """The events of each detector that has a lane: a detector with one event or more."""
    return {name: found for name, found in result.accepted.items() if found}


def event_tooltips(result: SearchResult, date_format: str) -> dict[tuple[str, datetime], str]:
    """The HTML text of the tooltip of each event, by the name of its detector and its start.

    It has the name of the detector for the page, then each text of the event with its title. The events
    table shows the same texts. See ``event_texts``.
    """
    titles = column_titles(result)
    tooltips = {}
    for event in result.events:
        texts = event_texts(result, event, date_format)
        lines = [f'{escape(titles[name])}: {escape(text)}' for name, text in texts.items() if text]
        tooltips[event.detector, event.start] = '<br>'.join(
            [f'<b>{escape(detector_name(result, event.detector))}</b>', *lines]
        )
    return tooltips


def line_windows(result: SearchResult, settings: Settings) -> list[timedelta | None]:
    """``smooth`` of each sensor of the tab of a result, in the order of the lines of the chart."""
    return [entry.smooth for entry in settings.tabs[result.tab].sensors] if result.tab in settings.tabs else []


def chart_height(result: SearchResult) -> int:
    """The height of the chart in pixels: the line of the sensor, then one lane for each detector with events."""
    return LINE_HEIGHT + LANE_HEIGHT * len(lane_events(result))


def smoothed(points: list[Point], window: timedelta) -> list[Point]:
    """The average of a line in each window of time, at the middle of the window.

    A value continues until the next point, so the time of a value is its weight. A sensor can write at
    changing intervals.
    """
    size = window.total_seconds()
    totals: dict[int, float] = {}
    times: dict[int, float] = {}
    for (start, value), (end, _) in zip(points, points[1:], strict=False):
        at, last = start.timestamp(), end.timestamp()
        while at < last:
            index = int(at // size)
            part = min(last, (index + 1) * size) - at
            totals[index] = totals.get(index, 0) + value * part
            times[index] = times.get(index, 0) + part
            at += part
    if not totals:
        return points
    zone = points[0][0].tzinfo
    return [(datetime.fromtimestamp((i + 0.5) * size, zone), totals[i] / times[i]) for i in sorted(totals)]


def chart_options(
    result: SearchResult, date_format: str, dark: bool = False, smooth: Sequence[timedelta | None] = ()
) -> dict[str, Any]:
    """ECharts options: the line of the sensor for the day with its levels, and one lane for each detector with events.

    A lane has the events of a detector: a bar from the start to the end of each event. The lanes have the
    time axis and the zoom of the line. At the left of a lane is the color and the name of the detector. At
    the right is the number of its events, and their energy for a power sensor. A bar shows the values of its
    event in a tooltip, with the label of the event.
    Each other sensor of the tab is one more line, with the same axis. The chart then has a legend.
    ``smooth`` has the window of each line of the tab, in the order of its sensors. A line with a window
    shows the average of its sensor in each window. None, or no entry, is each value of the sensor.
    """
    tz = result.tz
    colors = CHART_COLORS[dark]
    series, muted = colors['series'], colors['muted']
    # A power sensor shows kW. A different sensor shows its unit.
    scale, unit, decimals = (1000, 'kW', 2) if result.power else (1, result.unit, 1)

    def local(ts: datetime) -> str:
        return ts.astimezone(tz).strftime(CHART_FORMAT)

    day_start = result.start.astimezone(tz).replace(hour=0, minute=0, second=0, microsecond=0)
    day_end = datetime.combine(day_start.date() + timedelta(days=1), day_start.time(), tzinfo=tz)

    windows = [*smooth, *[None] * (1 + len(result.lines))]

    def line(name: str, points: list[Point], color: str, window: timedelta | None) -> dict[str, Any]:
        """The series of the line of a sensor. A line with a window shows averages, so it has no steps."""
        if window:
            points = smoothed(points, window)

        def held(limit: datetime) -> float | None:
            """The value of the line at a limit of the day: the last point before it. None without a point there."""
            return next((round(p / scale, 3) for t, p in reversed(points) if t < limit), None)

        inside = [[local(t), round(p / scale, 3)] for t, p in points if day_start <= t < day_end]
        # Without a point after the day, the line stops at its last point. A step line goes to the time of the
        # next point, so a point without a value at the time of the last point stops it.
        # The mini graph of the zoom slider draws only some of the points, so many such points stop it.
        end = held(day_end) if points and points[-1][0] >= day_end else None
        stop = [[x, None] for x, _ in inside[-1:]] * (len(inside) // 100 + 1) if end is None else []
        return {
            'name': name,
            'type': 'line',
            'step': False if window else 'end',
            'showSymbol': False,
            'lineStyle': {'color': color, 'width': 1.5},
            'itemStyle': {'color': color},
            # The mini graph of the zoom slider has the time range of this data, not of the time axis.
            # The data starts and ends at the limits of the day, so the two show the same times.
            'data': [
                [local(day_start), held(day_start)],
                *inside,
                *stop,
                [local(day_end), end],
            ],
        }

    # With more than one line, each line has the name of its sensor, and the chart has a legend.
    # The lines after the first one have their own colors, in the order of the file. Each one has a light
    # area and is behind the first line, so the first line stays clear.
    more = result.lines
    main_name = (result.sensor_name or result.sensor) if more else tab_name(result)
    palette = colors['lines']
    more_lines = [
        {
            **line(other.name or other.sensor, other.points, color, window),
            'areaStyle': {'color': color, 'opacity': 0.18},
            'z': 1,
        }
        for other, color, window in zip(more, palette + palette[-1:] * len(more), windows[1:], strict=False)
    ]
    color_of = detector_colors(result, dark)
    events = lane_events(result)
    lanes_height = LANE_HEIGHT * len(events)
    energy = result.energy_kwh
    numbers = [
        f'{len(found)} event{"" if len(found) == 1 else "s"}' + (f'  {energy[name]:.2f} kWh' if name in energy else '')
        for name, found in events.items()
    ]
    names = [detector_name(result, name) for name in events]
    tooltips = event_tooltips(result, date_format)
    lane_axis = {
        'type': 'category',
        'gridIndex': 1,
        'inverse': True,
        'axisLine': {'show': False},
        'axisTick': {'show': False},
        # The tooltip of an event shows no line across its lane.
        'axisPointer': {'show': False},
    }
    time_axis = {
        'type': 'time',
        'min': local(day_start),
        'max': local(day_end),
        'axisLine': {'lineStyle': {'color': colors['axis']}},
        'axisTick': {'show': False},
        'splitLine': {'show': False},
    }
    lanes = [
        {
            'name': name,
            'type': 'scatter',
            'xAxisIndex': 1,
            'yAxisIndex': 1,
            'tooltip': EVENT_TOOLTIP,
            'emphasis': {'disabled': True},
            # A mark at the start of each event, so an event of some seconds shows in the full day.
            'symbol': 'rect',
            'symbolSize': [3, LANE_HEIGHT - 10],
            'itemStyle': {'color': color_of[name]},
            'data': [{'name': tooltips[name, d.start], 'value': [local(d.start), name]} for d in found],
            'markLine': {
                'tooltip': EVENT_TOOLTIP,
                'emphasis': {'disabled': True},
                'symbol': 'none',
                # The label of an event is in its tooltip. A label at the bar goes across the next bars.
                'label': {'show': False},
                'lineStyle': {'color': color_of[name], 'type': 'solid', 'width': LANE_HEIGHT - 10},
                'data': [
                    [
                        {'name': tooltips[name, d.start], 'coord': [local(d.start), name]},
                        {'coord': [local(d.end), name]},
                    ]
                    for d in found
                ],
            },
        }
        for name, found in events.items()
    ]
    return {
        'animation': False,
        'backgroundColor': 'transparent',
        'textStyle': {'color': colors['secondary'], 'fontFamily': FONT},
        'tooltip': {
            'trigger': 'axis',
            # This tooltip is for the line of the sensor. A value of a lane is not a number.
            ':valueFormatter': 'value => typeof value === "number" '
            f'? value.toFixed({decimals}) + {json.dumps(" " + unit)} : ""',
            'backgroundColor': colors['surface'],
            'borderColor': colors['grid'],
            'textStyle': {'color': colors['ink']},
            'axisPointer': {'type': 'line', 'lineStyle': {'color': colors['axis'], 'type': 'solid'}},
        },
        # The two grids have the same left and right limits, so a time is at the same place in the two.
        'grid': [
            {'left': LEFT, 'right': RIGHT, 'top': 36, 'bottom': LANES_BOTTOM + lanes_height + 32},
            {'left': LEFT, 'right': RIGHT, 'height': lanes_height, 'bottom': LANES_BOTTOM},
        ],
        'xAxis': [
            {**time_axis, 'axisLabel': {'color': muted, 'formatter': '{HH}:{mm}', 'hideOverlap': True}},
            {**time_axis, 'gridIndex': 1, 'axisLabel': {'show': False}, 'axisPointer': {'triggerTooltip': False}},
        ],
        'yAxis': [
            {
                'type': 'value',
                'name': unit,
                'scale': not result.power,
                'nameTextStyle': {'color': muted, 'align': 'right'},
                'axisLabel': {'color': muted},
                'splitLine': {'lineStyle': {'color': colors['grid']}},
            },
            {
                **lane_axis,
                'data': list(events),
                'axisLabel': {
                    'color': colors['ink'],
                    'fontSize': 12,
                    # The friendly name of the detector, then a dot in its color
                    ':formatter': f'(value, index) => {json.dumps(names)}[index] + " {{c" + index + "|\u25cf}}"',
                    'rich': {f'c{i}': {'color': color_of[name], 'fontSize': 14} for i, name in enumerate(events)},
                },
                'splitLine': {'show': True, 'lineStyle': {'color': colors['grid']}},
            },
            {
                **lane_axis,
                'position': 'right',
                'data': numbers,
                'axisLabel': {'color': colors['secondary'], 'fontSize': 12},
            },
        ],
        'dataZoom': [
            {'type': 'inside', 'xAxisIndex': [0, 1]},
            {
                'type': 'slider',
                'xAxisIndex': [0, 1],
                'height': 22,
                'bottom': 12,
                'showDetail': False,
                'brushSelect': False,
                'borderColor': 'transparent',
                'backgroundColor': 'transparent',
                'fillerColor': f'{colors["ink"]}14',
                'dataBackground': {'lineStyle': {'color': colors['axis']}, 'areaStyle': {'color': colors['grid']}},
                'selectedDataBackground': {'lineStyle': {'color': series}, 'areaStyle': {'color': series}},
                'handleStyle': {'color': colors['surface'], 'borderColor': muted},
                'moveHandleStyle': {'color': colors['axis']},
            },
        ],
        'series': [
            {
                **line(main_name, result.points, series, windows[0]),
                'markLine': {
                    'silent': True,
                    'symbol': 'none',
                    'lineStyle': {'color': muted, 'type': 'dashed', 'width': 1},
                    'label': {'formatter': '{b}', 'position': 'insideEndTop', 'color': muted, 'fontSize': 11},
                    'data': [
                        {'name': f'{name} {level:.0f} {result.unit}', 'yAxis': round(level / scale, 3)}
                        for name, level in result.levels.items()
                    ],
                },
            },
            *more_lines,
            *lanes,
        ],
        'legend': {
            'show': bool(more),
            'data': [main_name, *(other['name'] for other in more_lines)],
            'top': 4,
            'right': RIGHT,
            'icon': 'roundRect',
            'itemWidth': 14,
            'itemHeight': 3,
            'textStyle': {'color': colors['secondary']},
        },
    }


def event_zoom(event: Row, tz: ZoneInfo) -> dict[str, Any]:
    """ECharts action: zoom to the event, with 10 % of its duration before and after. The minimum is 2 minutes."""
    margin = max((event.end - event.start) / 10, ZOOM_MARGIN)
    return {
        'type': 'dataZoom',
        'startValue': (event.start - margin).astimezone(tz).strftime(CHART_FORMAT),
        'endValue': (event.end + margin).astimezone(tz).strftime(CHART_FORMAT),
    }
