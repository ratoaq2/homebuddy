# Contributing

## Setup

```
uv sync
uv run pre-commit install
```

pre-commit runs ruff, mypy and the lock check of uv.

Run the page from the source tree:

```
uv run homebuddy
```

## Commands

The command list is in [`AGENTS.md`](AGENTS.md). `bash scripts/test.sh` runs all the checks of CI: `ruff check`,
`ruff format --check`, `mypy` (strict) and `pytest`.

## AI assistants

homebuddy is developed with AI assistants. [`AGENTS.md`](AGENTS.md) has the rules of the project: the
architecture, the layers, the names of the keys and the glossary. An assistant loads it in each session. Read
it one time before your first change.

- A decision is a rule in `AGENTS.md`, not an entry in a log. Change the rule in the commit of the code.
- The reason for each main rule is in [`docs/architecture.md`](docs/architecture.md).

## Code

- Keep the code small. See "Code: lazy senior dev" in `AGENTS.md`.
- Strict mypy: annotate every function.
- Ruff formats the code (single quotes, 120-character lines). Do not format by hand against it.
- The imports go in one direction. `tests/test_layers.py` checks it. A new module gets its rule in `PERMITTED`
  of that test.
- To add a detector type, see [`docs/detector-types.md`](docs/detector-types.md).

## No data of a real house

homebuddy is public. Do not put the setup of a real house in a tracked file: no real entity id, device name,
brand, address or measured value, and no copy of a real history. This rule is also for tests, screenshots and
commit messages.

- Use the invented house of `AGENTS.md` in each example and each test.
- Generate the data of a test in the test.
- Your own values go in `homebuddy.yml` and `.env`. Git ignores these files.

## Docs

`README.md` is short. The details are in `docs/`. When a change makes a statement in a doc wrong, fix it in
the same commit. A change of a key also changes `homebuddy.example.yml`.

## Commits

- Conventional Commits (`feat:`, `fix:`, `test:`, `docs:`, `chore:`), with a one-line subject.
- No body, except one `Closes #<n>` line when the commit fixes an issue.
- No attribution trailers (`Co-Authored-By` and similar).
- Bug fix: first commit a test that fails and shows the bug, then commit the fix.

## Writing

Write all text (comments, docs, commits, PRs, issues) in ASD-STE100 Simplified Technical English. Most
contributors are not native English speakers. The rules are in "Writing" of `AGENTS.md`.
