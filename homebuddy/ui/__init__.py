"""Graphical interface: a NiceGUI page in the browser, or a native desktop window."""

from __future__ import annotations

import argparse
import importlib.util
import sys
from collections.abc import Sequence


def main(argv: Sequence[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog='homebuddy', description='Find device events in the history of Home Assistant.')
    p.add_argument('--host', default='127.0.0.1', help='Address to bind (default: 127.0.0.1)')
    p.add_argument('--port', type=int, default=8080, help='Port to listen on (default: 8080)')
    p.add_argument('--native', action='store_true', help='Open a desktop window instead of the browser')
    p.add_argument('--no-show', action='store_true', help='Do not open the browser')
    p.add_argument('--config', help='Configuration file (.yml or .yaml)')
    args = p.parse_args(argv)

    if args.native and importlib.util.find_spec('webview') is None:
        sys.exit('Install the desktop extra: uv tool install "homebuddy[desktop]"')

    from homebuddy.ui.app import run

    run(host=args.host, port=args.port, native=args.native, show=not args.no_show, config_path=args.config)
