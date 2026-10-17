"""The colors, the font and the CSS of the page."""

from __future__ import annotations

from typing import Any

PRIMARY = '#2a78d6'
FONT = 'system-ui, -apple-system, "Segoe UI", sans-serif'
# The media query of a narrow screen, for example a phone. The CSS and the chart use it.
NARROW = '(max-width: 599px)'
# The ECharts element does not follow the dark mode of the page, so the chart gets its colors here.
# Keep them equal to the CSS variables in PAGE_CSS. False is the light theme, True is the dark theme.
CHART_COLORS: dict[bool, dict[str, Any]] = {
    False: {
        'series': PRIMARY,
        # The first detector has the color of the line.
        'detectors': (PRIMARY, '#eb6834', '#1baf7a', '#eda100'),
        # The lines of a chart after the first one, in the order of the tab: the colors of Home Assistant
        # for solar, then for a battery.
        'lines': ('#eda100', '#1baf7a', '#eb6834'),
        'surface': '#fcfcfb',
        'ink': '#0b0b0b',
        'secondary': '#52514e',
        'muted': '#898781',
        'grid': '#e1e0d9',
        'axis': '#c3c2b7',
    },
    True: {
        'series': '#3987e5',
        'detectors': ('#3987e5', '#d95926', '#199e70', '#c98500'),
        'lines': ('#c98500', '#199e70', '#d95926'),
        'surface': '#1a1a19',
        'ink': '#e6e5e0',
        'secondary': '#c3c2b7',
        'muted': '#898781',
        'grid': '#2c2c2a',
        'axis': '#383835',
    },
}
PAGE_CSS = """
:root {
    --hb-plane: #f9f9f7;
    --hb-surface: #fcfcfb;
    --hb-ink: #0b0b0b;
    --hb-muted: #6f6d68;
    --hb-secondary: #52514e;
    --hb-border: rgba(11, 11, 11, 0.10);
    --hb-control-border: rgba(11, 11, 11, 0.22);
    --hb-hover: rgba(11, 11, 11, 0.04);
}
body.body--dark {
    --hb-plane: #0d0d0d;
    --hb-surface: #1a1a19;
    --hb-ink: #e6e5e0;
    --hb-muted: #a3a29b;
    --hb-secondary: #c3c2b7;
    --hb-border: rgba(255, 255, 255, 0.10);
    --hb-control-border: rgba(255, 255, 255, 0.22);
    --hb-hover: rgba(255, 255, 255, 0.05);
}
body {
    background: var(--hb-plane) !important;
    color: var(--hb-ink) !important;
    font-family: system-ui, -apple-system, "Segoe UI", sans-serif;
}
.hb-header {
    background: var(--hb-surface) !important;
    color: var(--hb-ink) !important;
    border-bottom: 1px solid var(--hb-border);
}
.hb-card {
    background: var(--hb-surface) !important;
    color: var(--hb-ink) !important;
    border: 1px solid var(--hb-border);
    border-radius: 12px;
    box-shadow: none !important;
}
.hb-muted { color: var(--hb-muted); }
.hb-card th { color: var(--hb-muted); font-weight: 500; }
.hb-card td { color: var(--hb-secondary); font-variant-numeric: tabular-nums; }
.hb-card thead, .hb-card tr, .hb-card th, .hb-card td { border-color: var(--hb-border); }
.hb-card tbody tr { cursor: pointer; }
.hb-card tbody tr:hover { background: var(--hb-hover); }
.hb-filter {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    padding: 2px 10px;
    border: 1px solid var(--hb-control-border);
    border-radius: 999px;
    font-size: 12px;
    cursor: pointer;
    user-select: none;
}
.hb-filter:hover { background: var(--hb-hover); }
.hb-pill {
    padding: 2px 12px;
    border: 1px solid var(--hb-control-border);
    border-radius: 999px;
    font-size: 13px;
    font-weight: 400;
}
.q-tab--inactive { color: var(--hb-muted); opacity: 1; }
.hb-filter-dot { width: 8px; height: 8px; border-radius: 50%; }
.hb-filter-off { opacity: 0.45; }
.hb-filter-off .hb-filter-name { text-decoration: line-through; }
"""
# The header has three columns. The middle column has the width of the cards, so the tabs and the buttons of the
# day have the edges of the cards. The tabs take the free space of the middle column. In a frame, the logo and the
# buttons of the settings and the theme do not show, and the header has the background of the page, because
# Home Assistant has its own bar above the frame.
PAGE_CSS += """
.hb-bar { display: grid; grid-template-columns: 1fr minmax(0, 1536px) 1fr; align-items: center; width: 100%; }
.hb-logo { grid-column: 1; justify-self: start; }
.hb-logo img { height: 28px; max-width: none; margin-right: 16px; }
.hb-logo-dark, body.body--dark .hb-logo-light { display: none; }
body.body--dark .hb-logo-dark { display: inline; }
.hb-main { grid-column: 2; flex-wrap: nowrap; }
.hb-tabs { flex: 1 1 0; min-width: 0; }
.hb-days { margin-left: auto; }
.hb-tools { grid-column: 3; justify-self: end; margin-left: 16px; }
html.hb-embed .hb-logo, html.hb-embed .hb-tools { display: none !important; }
html.hb-embed .hb-header { background: var(--hb-plane) !important; border-bottom: none; }
"""
# On a narrow screen, the logo and the buttons of the settings and the theme are the first row of the header, the
# buttons of the day are the second row, and the tabs are the third row. The chart gets the space of the margins.
PAGE_CSS += f"""
@media {NARROW} {{
    .hb-header {{ padding: 4px 8px !important; }}
    .hb-bar {{ grid-template-columns: 1fr auto; }}
    .hb-main {{ grid-column: 1 / -1; grid-row: 2; flex-wrap: wrap; }}
    .hb-tools {{ grid-column: 2; grid-row: 1; }}
    .hb-days {{ order: 1; width: 100%; justify-content: center; }}
    .hb-tabs {{ order: 2; flex: none; width: 100%; }}
    .nicegui-content {{ padding: 8px !important; }}
    .hb-card {{ padding: 12px 8px !important; }}
}}
"""
# The color of the detector at each position, as CSS variables, so an element follows the theme of the page.
for _dark, _selector in ((False, ':root'), (True, 'body.body--dark')):
    _colors = ' '.join(f'--hb-detector-{i}: {color};' for i, color in enumerate(CHART_COLORS[_dark]['detectors']))
    PAGE_CSS += f'{_selector} {{ {_colors} }}\n'
