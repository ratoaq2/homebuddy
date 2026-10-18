"""The events table of a sensor."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from nicegui import ui

from homebuddy.result import Row, SearchResult
from homebuddy.ui.names import detector_name

# The format of the start and the end of an event in the day. See ``shown_format``.
TIME_FORMAT = '%H:%M:%S'
# The text of a cell of the table without a value
NO_VALUE = '–'
# The click must not go to the row, because a click on a row zooms the chart.
COPY_CELL = """
<q-td :props="props" auto-width>
    <q-btn flat round dense size="sm" icon="content_copy" @click.stop="$parent.$emit('copy', props.row)">
        <q-tooltip>Copy row</q-tooltip>
    </q-btn>
</q-td>
"""


def copy_row(row: dict[str, Any], columns: Sequence[str]) -> None:
    """Copy the values of the columns of an event, with a tab between them for a spreadsheet.

    The values are the texts of ``copy`` of the row. A column that the sensor does not have gives no value.
    """
    texts = row['copy']
    ui.clipboard.write('\t'.join(str(texts[name]) for name in columns if name in texts))
    ui.notify('Copied the row')


def duration_text(seconds: float) -> str:
    """Seconds for a short event, minutes for a longer event, hours and minutes from 1 hour on."""
    if seconds < 600:
        return f'{seconds:.0f} s'
    hours, minutes = divmod(round(seconds / 60), 60)
    return f'{hours} h {minutes:02d} min' if hours else f'{minutes} min'


def column_titles(result: SearchResult) -> dict[str, str]:
    """The title of each column that has a text of an event, by the id of the column.

    The sensor of the tab gives the value columns, the same ones for each detector: the power and the energy
    for a power sensor, and the value at the start and the peak, with the unit, for a different sensor.
    """
    titles = {'start': 'Start', 'end': 'End', 'duration': 'Duration', 'label': 'Label'}
    if result.power:
        return {**titles, 'power': 'Power (kW)', 'energy': 'Energy (kWh)'}
    return {**titles, 'start_value': f'Start ({result.unit})', 'peak': f'Peak ({result.unit})'}


def number_text(value: float | None, decimals: int) -> str:
    """The text of a value. It is empty without a value."""
    return '' if value is None else f'{value:.{decimals}f}'


def shown_format(result: SearchResult, event: Row, date_format: str) -> str:
    """The format of the start and the end of an event in the table and in the tooltips of the chart.

    The page shows one day, so an event in the day shows only the time. An event that crosses midnight shows
    ``date_format``, the format of the settings.
    """
    return TIME_FORMAT if result.start <= event.start and event.end <= result.end else date_format


def event_texts(result: SearchResult, event: Row, date_format: str) -> dict[str, str]:
    """The text of each value of an event, by the id of its column. See ``column_titles``.

    The start and the end have ``date_format``. The page shows them with ``shown_format``.
    """
    texts = {
        'start': event.start.astimezone(result.tz).strftime(date_format),
        'end': event.end.astimezone(result.tz).strftime(date_format),
        'duration': duration_text((event.end - event.start).total_seconds()),
        'label': event.label,
        'power': number_text(event.power_kw, 2),
        'energy': number_text(event.energy_kwh, 2),
        'start_value': number_text(event.start_value, 1),
        'peak': number_text(event.peak, 1),
    }
    return {name: texts[name] for name in column_titles(result)}


def event_rows(result: SearchResult, date_format: str) -> list[dict[str, Any]]:
    """One row for each event of the sensor, the latest event first. Each value of the event has its own column.

    ``id`` is the position of the event in the order of time.
    ``key`` is the name of the detector in the file. ``detector`` is its name for the page. Each other key is
    the id of a column, with the text that the table shows: ``NO_VALUE`` for a value that the event does not have.
    See ``event_texts`` and ``shown_format``.
    ``copy`` has the texts that the copy button copies, with ``date_format``. A value that the event does not
    have is empty there, so the cell of a spreadsheet stays empty.
    """
    rows = []
    for i, e in reversed(list(enumerate(result.events, 1))):
        detector = {'detector': detector_name(result, e.detector)}
        texts = event_texts(result, e, shown_format(result, e, date_format))
        shown = {name: text or NO_VALUE for name, text in texts.items()}
        copied = detector | event_texts(result, e, date_format)
        rows.append({'id': i, 'key': e.detector, **detector, **shown, 'copy': copied})
    return rows


def event_columns(result: SearchResult) -> list[dict[str, Any]]:
    """The columns of the events table. The name of a column is its id. See ``column_titles``."""
    left = ('start', 'end', 'label')
    return [
        {'name': 'detector', 'label': 'Detector', 'field': 'detector', 'align': 'left'},
        *(
            {'name': name, 'label': title, 'field': name} | ({'align': 'left'} if name in left else {})
            for name, title in column_titles(result).items()
        ),
        {'name': 'copy', 'label': '', 'field': 'id', 'align': 'left'},
    ]


def copy_columns(result: SearchResult, selected: Sequence[str] | None) -> list[str]:
    """The ids of the columns that the copy button copies: ``selected``, or each column with a text.

    ``selected`` is ``copy_columns`` of the settings. A column that the tab does not have gives no value.
    """
    return list(selected or ['detector', *column_titles(result)])
