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

## Make a release

The version is in three files: `package.json`, `pyproject.toml`, and `src/talktome/__init__.py`.

1. Set the same version in the three files.
2. Run `npm install --package-lock-only` and `uv lock` to update the lock files.
3. Move the **Unreleased** lines in `CHANGELOG.md` under the new version.
4. Commit the change, then push a tag such as `v0.2.0`.

The release workflow stops if the tag does not match the three files.
It builds the disk image and the zip, then attaches them to a GitHub release.
The job summary shows the `sha256` value for the Homebrew cask.
If the repository variable `PUBLISH_PYPI` is `true`, the workflow also publishes the Python package to PyPI.

## Style

- Python: ruff controls lint. Use the settings in `pyproject.toml`.
- JavaScript: plain ES modules with no build step.
- Comments: explain why, not what. Remove a comment that only repeats the code.
- Documentation: write short, active sentences. Use one term for one thing.

## The notch surface

The native notch surface is off until its design is ready. The call uses the pill at the placement that the user selects.
The Swift code stays in `native/`. To work on it:

1. Set `NATIVE_NOTCH` to `true` in `desktop/main.cjs`.
2. Run `TALKTOME_NOTCH=1 npm run build:app` to build the helper and the app. For a quick look at the helper alone, run `npm run build:notch-preview`.

Do not commit `NATIVE_NOTCH = true`.

## Where things are

| Path | Contents |
| --- | --- |
| `desktop/` | Electron main process and preload scripts |
| `native/` | The Swift notch surface. It is off in the app. |
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
