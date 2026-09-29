# Contributing

Thank you for your help. This file tells you how to set up, test, and send a change.

## Set up

Requirements: macOS, Node.js 22 or later, and [uv](https://docs.astral.sh/uv/).

```sh
npm ci
uv sync --frozen
npm start
```

## Test

Run all checks before you open a pull request:

```sh
uv run pytest -q
uv run ruff check
node --test tests/
```

CI runs the same commands on each pull request.
Tests must not use the network or your real data folder. `tests/conftest.py` sets a temporary data folder for each test.

Some scripts in `scripts/` are manual smoke tests. They start real agents or real speech providers, so CI does not run them.

## Send a change

1. Open an issue first for a large change, so that we can agree on the approach.
2. Keep one topic in each pull request.
3. Add or update tests for each behavior that you change.
4. Match the style of the code around your change.
5. Update `README.md` or the files in `docs/` when you change behavior that users see.
6. Add a line to `CHANGELOG.md` under **Unreleased**.

## Style

- Python: ruff controls lint. Use the settings in `pyproject.toml`.
- JavaScript: plain ES modules with no build step.
- Comments: explain why, not what. Remove a comment that only repeats the code.
- Documentation: write short, active sentences. Use one term for one thing.

## Where things are

| Path | Contents |
| --- | --- |
| `desktop/` | Electron main process and preload scripts |
| `native/` | The Swift notch surface |
| `src/talktome/` | The local server, speech, and agent adapters |
| `src/talktome/static/` | The onboarding, settings, and call pages |
| `src/talktome/remote/` | The experimental remote bridge |
| `skills/talktome/` | The skill that tells an agent how to call |
| `docs/` | User and contributor documentation |
| `docs/notes/` | Development notes. They can be out of date. |

## Security problems

Do not open a public issue. Read [SECURITY.md](SECURITY.md).

## License

You agree that your contribution uses the MIT license of this project. See [LICENSE](LICENSE).
