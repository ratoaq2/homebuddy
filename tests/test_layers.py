"""The layers of homebuddy: which module can import which one. See ``AGENTS.md``."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

import homebuddy

ROOT = Path(homebuddy.__file__).parent
MODEL = 'homebuddy.model'
FIELDS = 'homebuddy.fields'
DETECTOR = 'homebuddy.detector'
# The modules of homebuddy that a module can import. A name with ``.*`` is each module in that package.
# The first entry that matches the module wins. The page in ``homebuddy.ui`` can import each module.
PERMITTED = {
    MODEL: (),
    FIELDS: (),
    DETECTOR: (MODEL, FIELDS),
    # A detector type knows only the data, the field types and the contract.
    'homebuddy.detectors.*': (MODEL, FIELDS, DETECTOR),
    'homebuddy.detectors': (DETECTOR, 'homebuddy.detectors.*'),
    # The client of Home Assistant knows no search, no settings and no page.
    'homebuddy.homeassistant': (MODEL,),
    'homebuddy.conflicts': (MODEL,),
    'homebuddy.result': (MODEL, DETECTOR, 'homebuddy.conflicts'),
    'homebuddy.config': (FIELDS, DETECTOR, 'homebuddy.detectors'),
    # The search gets its data source as an argument.
    'homebuddy.search': ('homebuddy.config', 'homebuddy.conflicts', 'homebuddy.result', MODEL),
}


def matches(name: str, pattern: str) -> bool:
    return name.startswith(pattern[:-1]) if pattern.endswith('*') else name == pattern


def module_name(path: Path, root: Path) -> str:
    parts = path.relative_to(root.parent).with_suffix('').parts
    return '.'.join(parts[:-1] if parts[-1] == '__init__' else parts)


def imports(tree: ast.AST, modules: set[str]) -> set[str]:
    """The modules of homebuddy that the code imports, also in a function."""
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            assert node.level == 0, 'use an absolute import'
            # ``from homebuddy import config`` imports the module ``homebuddy.config``.
            names = {f'{node.module}.{alias.name}' for alias in node.names} & modules
            found.update(names or {node.module})
    return found & modules


def import_graph(root: Path = ROOT) -> dict[str, set[str]]:
    files = {module_name(path, root): path for path in sorted(root.rglob('*.py'))}
    return {name: imports(ast.parse(path.read_text(encoding='utf-8')), set(files)) for name, path in files.items()}


def cycle(graph: dict[str, set[str]]) -> list[str]:
    """The modules of one import cycle. Empty without a cycle."""
    done: set[str] = set()

    def visit(name: str, path: list[str]) -> list[str]:
        if name in path:
            return [*path[path.index(name) :], name]
        if name in done:
            return []
        done.add(name)
        return next((found for other in sorted(graph[name]) if (found := visit(other, [*path, name]))), [])

    return next((found for name in sorted(graph) if (found := visit(name, []))), [])


def wrong_imports(graph: dict[str, set[str]]) -> list[str]:
    """Each import that the layers do not permit, as ``module -> module``.

    A module out of a package imports the package, and never a module in it.
    """
    wrong = []
    for name, others in sorted(graph.items()):
        permitted = next((to for pattern, to in PERMITTED.items() if matches(name, pattern)), None)
        for other in sorted(others):
            package = other.rpartition('.')[0]
            in_other_package = package != 'homebuddy' and not f'{name}.'.startswith(f'{package}.')
            if in_other_package or (permitted is not None and not any(matches(other, to) for to in permitted)):
                wrong.append(f'{name} -> {other}')
    return wrong


def test_the_imports_obey_the_layers() -> None:
    graph = import_graph()
    assert len(graph) > 10
    assert cycle(graph) == []
    assert wrong_imports(graph) == []


@pytest.mark.parametrize(
    ('module', 'code', 'error'),
    [
        ('detectors/ramp.py', 'from homebuddy.config import Settings', 'homebuddy.detectors.ramp -> homebuddy.config'),
        (
            'detectors/ramp.py',
            'import homebuddy.detectors.level',
            'homebuddy.detectors.ramp -> homebuddy.detectors.level',
        ),
        ('model.py', 'import homebuddy.fields', 'homebuddy.model -> homebuddy.fields'),
        ('detector.py', 'import homebuddy.detectors', 'homebuddy.detector -> homebuddy.detectors'),
        ('config.py', 'from homebuddy.ui import theme', 'homebuddy.config -> homebuddy.ui.theme'),
        ('search.py', 'from homebuddy import homeassistant', 'homebuddy.search -> homebuddy.homeassistant'),
        ('homeassistant.py', 'from homebuddy.config import Settings', 'homebuddy.homeassistant -> homebuddy.config'),
        # A module out of a package does not import a module in the package.
        ('config.py', 'from homebuddy.detectors.level import Level', 'homebuddy.config -> homebuddy.detectors.level'),
        (
            'ui/theme.py',
            'from homebuddy.detectors.level import Level',
            'homebuddy.ui.theme -> homebuddy.detectors.level',
        ),
    ],
)
def test_a_wrong_import_fails(tmp_path: Path, module: str, code: str, error: str) -> None:
    root = tmp_path / 'homebuddy'
    names = ('model.py', 'fields.py', 'detector.py', 'config.py', 'search.py', 'homeassistant.py')
    for name in (*names, 'detectors/__init__.py', 'detectors/level.py', 'ui/theme.py'):
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_text('')
    (root / module).parent.mkdir(parents=True, exist_ok=True)
    (root / module).write_text(code)
    assert wrong_imports(import_graph(root)) == [error]


def test_a_cycle_fails(tmp_path: Path) -> None:
    root = tmp_path / 'homebuddy'
    (root / 'ui').mkdir(parents=True)
    (root / 'ui' / 'card.py').write_text('from homebuddy.ui import chart')
    (root / 'ui' / 'chart.py').write_text('def f():\n    import homebuddy.ui.card')
    assert cycle(import_graph(root)) == ['homebuddy.ui.card', 'homebuddy.ui.chart', 'homebuddy.ui.card']
