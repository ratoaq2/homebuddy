"""The card of a sensor: chart, events table and debug data."""

from __future__ import annotations

from datetime import date
from typing import Any

from nicegui import ui

from homebuddy.config import Settings
from homebuddy.result import SearchResult
from homebuddy.ui.chart import FULL_DAY_ZOOM, chart_height, chart_options, event_zoom, line_windows
from homebuddy.ui.debug import table_lines
from homebuddy.ui.events import COPY_CELL, copy_columns, copy_row, event_columns, event_rows
from homebuddy.ui.names import detector_name, tab_name
from homebuddy.ui.theme import CHART_COLORS


def show_card(
    result: SearchResult, settings: Settings, day: date, dark: bool, narrow: bool = False
) -> tuple[ui.echart, ui.element]:
    """Render the chart and the empty details of a sensor into the current container.

    ``narrow`` gives the chart its layout for a narrow screen.
    """
    with ui.card().classes('hb-card w-full gap-0'):
        with ui.row().classes('w-full items-baseline gap-3'):
            ui.label(tab_name(result)).classes('font-semibold')
            ui.label(f'{day:%A}, {day.day} {day:%B %Y}').classes('hb-muted text-sm')
            ui.space()
            full_day_button = ui.button('Full day', color=None).props('flat dense no-caps').classes('hb-pill')
        options = chart_options(result, settings.date_format, dark, line_windows(result, settings), narrow)
        chart = ui.echart(options).classes('w-full').style(f'height: {chart_height(result, narrow)}px')
    full_day_button.on_click(lambda: chart.run_chart_method('dispatchAction', FULL_DAY_ZOOM))
    return chart, ui.column().classes('w-full gap-4')


def show_details(result: SearchResult, settings: Settings, chart: ui.echart, debug: bool, hidden: set[str]) -> None:
    """Render the events table of the sensor into the current container.

    ``settings`` has the date format and the columns of the copy button.
    ``hidden`` has the names of the detectors that the table does not show. A click on the filter of a detector
    changes it, so the caller keeps it between two loads.
    """
    tz = result.tz
    events = result.events
    if not events:
        with ui.card().classes('hb-card w-full items-center py-8'):
            ui.label('No events found').classes('hb-muted')
    else:
        with ui.card().classes('hb-card w-full gap-1'):
            with ui.row().classes('w-full items-baseline gap-3'):
                ui.label('Events').classes('font-semibold')
                ui.label('Click a row to zoom the chart').classes('hb-muted text-xs')
                ui.space()
                filters = ui.row().classes('items-center gap-2')
            rows = event_rows(result, settings.date_format)

            def shown_rows() -> list[dict[str, Any]]:
                return [row for row in rows if row['key'] not in hidden]

            table = ui.table(columns=event_columns(result), rows=shown_rows(), row_key='id')

            def toggle(name: str, pill: ui.element) -> None:
                """Show or hide the rows of a detector."""
                hidden.symmetric_difference_update({name})
                pill.classes(add='hb-filter-off') if name in hidden else pill.classes(remove='hb-filter-off')
                table.update_rows(shown_rows())

            # One filter for each detector with events, when there is a choice: its color, its name and its count.
            # A hidden detector always has its filter, so the user can show its rows.
            counts = {name: len(found) for name, found in result.accepted.items() if found}
            last_color = len(CHART_COLORS[False]['detectors']) - 1
            positions = {name: min(i, last_color) for i, name in enumerate(result.detectors)}
            for name, count in counts.items() if len(counts) > 1 or hidden & counts.keys() else ():
                with filters, ui.element('div').classes('hb-filter').mark(f'filter-{name}') as pill:
                    ui.element('div').classes('hb-filter-dot').style(
                        f'background: var(--hb-detector-{positions[name]})'
                    )
                    ui.label(detector_name(result, name)).classes('hb-filter-name')
                    ui.label(str(count)).classes('hb-muted')
                    ui.tooltip('Show or hide the rows of this detector')
                pill.classes('hb-filter-off' if name in hidden else '')
                pill.on('click', lambda name=name, pill=pill: toggle(name, pill))
            table.classes('w-full').props('flat').style('background: transparent')
            table.add_slot('body-cell-copy', COPY_CELL)
            table.on('copy', lambda e: copy_row(e.args, copy_columns(result, settings.copy_columns)))

            def zoom(row: dict[str, Any]) -> None:
                chart.run_chart_method('dispatchAction', event_zoom(events[row['id'] - 1], tz))
                # A long table moves the chart out of the window, so the chart comes back into the window.
                ui.run_javascript(f'getElement({chart.id}).$el.scrollIntoView({{behavior: "smooth", block: "center"}})')

            # The rowClick arguments are the event, the row and the row index.
            table.on('rowClick', lambda e: zoom(e.args[1]))

    if not debug:
        return
    if result.conflicts:
        with ui.card().classes('hb-card w-full gap-1'):
            ui.label('Removed events').classes('font-semibold')
            ui.label('A detector that overrides this one found the same event').classes('hb-muted text-xs')
            times = [
                (detector_name(result, c.detector), c.start.astimezone(tz), c.end.astimezone(tz), c.winner)
                for c in result.conflicts
            ]
            lines = [
                f'{loser}  {a:%H:%M:%S} to {b:%H:%M:%S}  winner: {detector_name(result, winner)}'
                for loser, a, b, winner in times
            ]
            ui.code('\n'.join(lines), language='text').classes('w-full')
    for name, found in result.found.items():
        detector = result.detectors[name]
        blocks = detector.debug(found, result.history)
        if not blocks:
            continue
        with ui.card().classes('hb-card w-full gap-1'):
            ui.label(f'Debug data of {detector_name(result, name)}').classes('font-semibold')
            for title, block in blocks.items():
                # Only one block: it is open.
                with ui.expansion(title, value=len(blocks) == 1).classes('w-full'):
                    ui.code('\n'.join(table_lines(block, tz)), language='text').classes('w-full')
