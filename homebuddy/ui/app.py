"""NiceGUI page: day navigation, the tabs of the configuration file, and the card of the selected tab."""

from __future__ import annotations

import json
import urllib.error
from datetime import date, datetime, timedelta
from functools import cache
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from dotenv import find_dotenv, load_dotenv
from nicegui import app, ui
from nicegui import run as nicegui_run

from homebuddy import config, search
from homebuddy.homeassistant import HomeAssistant
from homebuddy.model import SensorError
from homebuddy.result import SearchResult
from homebuddy.ui.card import show_card, show_details
from homebuddy.ui.chart import chart_height, chart_options, tab_lines
from homebuddy.ui.names import tab_name
from homebuddy.ui.theme import NARROW, PAGE_CSS, PRIMARY

STATIC = Path(__file__).parent / 'static'
REFRESH_SECONDS = 60
DATE_STYLE = "{weekday: 'short', day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC'}"
SYSTEM_DARK = '(prefers-color-scheme: dark)'
# The page in a frame, for example a webpage card of Home Assistant, has a compact header. The URL parameter
# ``embed=1`` or ``embed=0`` overrides the check. The script is in the head, so the class is there before the
# browser shows the page.
EMBED_JS = """
const embed = new URLSearchParams(location.search).get('embed');
if (embed === '1' || (embed !== '0' && window.self !== window.top)) {
    document.documentElement.classList.add('hb-embed');
}
"""


def media_js(query: str, event: str) -> str:
    """JavaScript: the browser sends if it matches a media query, now and at each change."""
    return f"""
const query = matchMedia({json.dumps(query)});
const send = () => emitEvent({json.dumps(event)}, query.matches);
query.addEventListener('change', send);
send();
"""


@cache
def client(url: str, token: str) -> HomeAssistant:
    """The client of a Home Assistant. The page uses one client again, so its cache stays."""
    return HomeAssistant(url, token)


def today(tz_name: str) -> date:
    """Today in the time zone. An unknown time zone gives the local date. The load reports the error."""
    try:
        return datetime.now(ZoneInfo(tz_name)).date()
    except (ZoneInfoNotFoundError, ValueError):
        return date.today()


def root(config_path: str | None = None) -> None:
    ui.page_title('homebuddy')
    ui.colors(primary=PRIMARY)
    ui.add_css(PAGE_CSS)
    # The manifest lets a phone install the page as an app. The browser needs HTTPS for that.
    ui.add_head_html('<link rel="manifest" href="/static/manifest.webmanifest">')
    ui.add_head_html(f'<script>{EMBED_JS}</script>')
    # The settings of the page. They are None for a wrong configuration file: ``errors`` then has its errors.
    loaded: config.Settings | None = None
    errors = ''

    def read_file() -> None:
        """Read the configuration file. The page reads it when it opens, and at each click on "Load again"."""
        nonlocal loaded, errors
        try:
            loaded, errors = config.load_settings(config=config_path), ''
        except config.ConfigError as e:
            loaded, errors = None, str(e)

    read_file()
    # None is the theme of the computer of the user. The page reads the theme only when it opens.
    dark = ui.dark_mode({'light': False, 'dark': True}.get(loaded.theme if loaded else 'system'))
    # The time zone of the file. Without it, the first load gets the time zone of Home Assistant.
    tz_name = (loaded.timezone if loaded else None) or ''

    # The header is one row: the logo at the left edge, the tabs and the buttons of the day with the width of the
    # cards, and the buttons of the settings and the theme at the right edge.
    with ui.header(elevated=False).classes('hb-header'), ui.element().classes('hb-bar'):
        # The CSS shows the logo of the theme of the page.
        with ui.element().classes('hb-logo'):
            for theme in ('light', 'dark'):
                ui.element('img').props(f'src=/static/logo-{theme}.png alt=homebuddy').classes(f'hb-logo-{theme}')
        with ui.row().classes('hb-main items-center gap-1'):
            # The tabs of the configuration file that have data, when there is more than one. The row of tabs
            # scrolls when the tabs do not fit.
            tabs = ui.tabs().props('dense no-caps align=left outside-arrows mobile-arrows').classes('hb-tabs')
            tabs.set_visibility(False)
            with ui.row().classes('hb-days items-center gap-1 no-wrap'):
                prev_button = (
                    ui.button(icon='chevron_left', color=None)
                    .props('flat round dense')
                    .mark('prev')
                    .tooltip('Previous day')
                )
                # The button shows the day in words. A click opens the calendar.
                with ui.button(icon='event', color=None).props('flat dense no-caps').classes('hb-pill') as date_button:
                    with ui.menu() as date_menu:
                        date_picker = ui.date(value=today(tz_name).isoformat(), on_change=date_menu.close)

                def show_date() -> None:
                    # The browser writes the day in the format of its language.
                    day = f'new Date({json.dumps(date_picker.value)}).toLocaleDateString(undefined, {DATE_STYLE})'
                    date_button.props(remove='label')
                    date_button.props[':label'] = day if date_picker.value else 'null'

                date_picker.on_value_change(show_date)
                show_date()
                next_button = (
                    ui.button(icon='chevron_right', color=None)
                    .props('flat round dense')
                    .mark('next')
                    .tooltip('Next day')
                )
                today_button = ui.button('Today', color=None).props('flat dense no-caps').classes('hb-pill')
                reload_button = (
                    ui.button(icon='refresh', color=None).props('flat round dense').mark('reload').tooltip('Load again')
                )
        with ui.row().classes('hb-tools items-center gap-1 no-wrap'):
            settings_button = ui.button(icon='tune', color=None).props('flat round dense').tooltip('Settings')
            with settings_button, ui.menu(), ui.column().classes('p-4 gap-2 w-72'):
                ui.label('Settings').classes('font-semibold')
                debug_input = ui.switch('Show debug data')
            theme_button = (
                ui.button(icon='light_mode' if dark.value else 'dark_mode', color=None)
                .props('flat round dense')
                .mark('theme')
                .tooltip('Dark or light theme')
            )

    results = ui.column().classes('w-full max-w-screen-2xl mx-auto gap-4')
    # The chart and the details of the selected tab
    card: tuple[ui.echart, ui.element] | None = None
    # The detectors that the events table of each tab does not show. A tab starts with ``hidden_detectors`` of
    # the file. The choice stays for each load, until the file changes.
    hidden: dict[str, set[str]] = {}
    shown_day: date | None = None
    shown: list[SearchResult] = []
    # The day that the page opened on, until the first load knows the time zone. It is the day of the computer
    # for a file without ``timezone``.
    opening: str | None = today(tz_name).isoformat()
    # The browser sends if its screen is narrow, now and at each change. The chart gets its layout from it.
    narrow = False

    def update_chart(target: ui.echart, result: SearchResult) -> None:
        if loaded is None:
            return
        # Update the chart in place, so the zoom stays. The number of lanes can change.
        target.options.clear()
        entries = tab_lines(result, loaded)
        target.options.update(chart_options(result, loaded.date_format, bool(dark.value), entries, narrow))
        target.style(f'height: {chart_height(result, narrow)}px')
        target.update()

    def selected() -> SearchResult | None:
        """The result of the selected tab."""
        return next((result for result in shown if result.tab == tabs.value), None)

    def show(keep_chart: bool = False) -> None:
        """Render the selected tab. ``keep_chart`` updates the chart that the page has, so its zoom stays."""
        nonlocal card
        result = selected()
        if result is None or shown_day is None or loaded is None:
            return
        if keep_chart and card:
            update_chart(card[0], result)
        else:
            results.clear()
            with results:
                card = show_card(result, loaded, shown_day, bool(dark.value), narrow)
        chart, details = card
        tab = loaded.tabs.get(result.tab)
        details.clear()
        with details:
            show_details(
                result,
                loaded,
                chart,
                bool(debug_input.value),
                hidden.setdefault(result.tab, set(tab.hidden_detectors if tab else ())),
            )

    def set_dark(value: bool) -> None:
        dark.value = value
        theme_button.props(f'icon={"light_mode" if value else "dark_mode"}')
        draw_chart()

    def set_narrow(value: bool) -> None:
        nonlocal narrow
        narrow = value
        draw_chart()

    def draw_chart() -> None:
        """Update the chart of the selected tab, when the page has one."""
        result = selected()
        if card and result:
            update_chart(card[0], result)

    def show_message(title: str, lines: list[str]) -> None:
        """Show a message in place of the tabs and the card of the sensor."""
        nonlocal card, shown
        card, shown = None, []
        tabs.clear()
        tabs.set_visibility(False)
        results.clear()
        with results, ui.card().classes('hb-card w-full items-center py-8'):
            ui.label(title).classes('hb-muted')
            for line in lines:
                ui.label(line).classes('font-mono text-sm')

    def show_error(error: Exception, day: date) -> None:
        """Show the error of the search of a day."""
        match error:
            case search.NoDataError():
                show_message(f'No data for {day:%A}, {day.day} {day:%B %Y}', [])
            case SensorError():
                show_message(str(error), [])
            case urllib.error.HTTPError():
                ui.notify(f'Home Assistant error: HTTP {error.code} {error.reason}', type='negative')
            case _:
                ui.notify(f'Cannot reach Home Assistant: {error}', type='negative')

    async def load() -> None:
        nonlocal card, shown_day, shown, tz_name, opening
        if loaded is None:
            # The first line is the number of errors, or the only error.
            title, *lines = errors.splitlines()
            show_message(title, lines)
            return
        settings = loaded
        try:
            day = date.fromisoformat(date_picker.value or '')
        except ValueError as e:
            ui.notify(str(e), type='negative')
            return

        def selected_day() -> bool:
            """True when the day of this load is still the selected day. Else a newer load shows the selected day."""
            return bool(date_picker.value == day.isoformat())

        try:
            source = client(settings.home_assistant.url, config.ha_token())
            try:
                # Without ``timezone`` in the file, the time zone comes from Home Assistant.
                tz = await nicegui_run.io_bound(search.timezone, settings, source)
            except (ZoneInfoNotFoundError, ValueError) as e:
                if selected_day():
                    ui.notify(str(e), type='negative')
                return
            if tz is None or not selected_day():  # the app is shutting down, or a newer load
                return
            tz_name = tz.key
            opened, opening = opening, None
            if date_picker.value == opened and day != today(tz_name):
                # The page still shows the day of the computer. The day of the home is a different one.
                date_picker.value = today(tz_name).isoformat()  # the change of the day loads the page
                return
            is_today = day == today(tz_name)
            next_button.set_enabled(not is_today)
            refresh_timer.active = is_today
            found = await nicegui_run.io_bound(search.find_day, settings, source, day)
        except (search.NoDataError, SensorError, OSError) as e:
            if selected_day():
                show_error(e, day)
            return
        if found is None or not selected_day():  # the app is shutting down, or a newer load
            return

        names = {result.tab: tab_name(result) for result in found}
        same = bool(card) and day == shown_day and names == {result.tab: tab_name(result) for result in shown}
        shown, shown_day = found, day
        if not same:
            tabs.clear()
            with tabs:
                for tab, name in names.items():
                    ui.tab(tab, label=name)
            tabs.set_visibility(len(names) > 1)
        if tabs.value in names:
            show(keep_chart=same)
        else:
            # The page keeps the selected tab. The first tab is selected when the day does not have it.
            tabs.value = next(iter(names))  # the change of the tab shows the sensor

    async def load_again() -> None:
        """Read the configuration file again, then load the day."""
        before = loaded
        read_file()
        if loaded != before:
            # The file changed, so each tab starts with its ``hidden_detectors`` again.
            hidden.clear()
        await load()

    def shift(days: int) -> None:
        try:
            day = date.fromisoformat(date_picker.value or '')
        except ValueError:
            day = today(tz_name)
        date_picker.value = (day + timedelta(days=days)).isoformat()

    def go_today() -> None:
        date_picker.value = today(tz_name).isoformat()

    async def refresh() -> None:
        """Load today again. After midnight, the page goes to the new day, so a wall display shows today."""
        if date_picker.value == today(tz_name).isoformat():
            await load()
        else:
            go_today()  # the change of the day loads the page

    prev_button.on_click(lambda: shift(-1))
    next_button.on_click(lambda: shift(1))
    today_button.on_click(go_today)
    reload_button.on_click(load_again)
    theme_button.on_click(lambda: set_dark(not dark.value))
    date_picker.on_value_change(load)
    tabs.on_value_change(lambda: show())
    debug_input.on_value_change(load)
    # The timer is active only when the page shows today, so a day in the past stays.
    refresh_timer = ui.timer(REFRESH_SECONDS, refresh, active=False).mark('refresh')
    ui.timer(0, load, once=True)
    ui.on('narrow', lambda e: set_narrow(bool(e.args)))
    ui.timer(0, lambda: ui.run_javascript(media_js(NARROW, 'narrow')), once=True)
    if dark.value is None:
        # The browser sends the theme of the computer, now and at each change. The chart gets its colors from it.
        ui.on('system_dark', lambda e: set_dark(bool(e.args)))
        ui.timer(0, lambda: ui.run_javascript(media_js(SYSTEM_DARK, 'system_dark')), once=True)


def run(host: str, port: int, native: bool, show: bool, config_path: str | None = None) -> None:
    # homebuddy reads ``.env`` one time, when it starts. The token of Home Assistant can be in it. The file is
    # in the current folder, or in a folder above it. Without ``usecwd``, dotenv looks from the folder of this
    # module, so it does not find the file of a user.
    load_dotenv(find_dotenv(usecwd=True))
    app.add_static_files('/static', STATIC)
    ui.run(
        lambda: root(config_path),
        host=host,
        port=port,
        native=native,
        show=show,
        reload=False,
        title='homebuddy',
        favicon=STATIC / 'icon-192.png',
    )
