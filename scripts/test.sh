#!/bin/bash

set -ex

uv run ruff check homebuddy tests
uv run ruff format --check homebuddy tests
uv run mypy homebuddy tests
uv run pytest homebuddy -vv tests
