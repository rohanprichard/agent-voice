# Contributing

Thank you for your help. This file tells you how to set up, test, and send a change.

## Set up

Requirements: macOS, Node.js 22 or later, and [uv](https://docs.astral.sh/uv/).

```sh
npm ci
(cd server && uv sync --frozen)
npm start
```

`npm start` builds the TypeScript in `desktop/src` and starts the app. To use your checkout of the server instead of an installed one, set `TALKTOME_SERVER_BIN=$PWD/server/.venv/bin/talktome-server`.

## Test

Run all checks before you open a pull request:

```sh
npm test
npm run test:server
```

CI runs the same checks on each pull request. `npm test` includes a test that runs the real `talktome-server` from `server/.venv`.
Tests must not use the network or your real data folders. The server tests set a temporary `TALKTOME_DIR` and home folder.

## Send a change

1. Open an issue first for a large change, so that we can agree on the approach.
2. Keep one topic in each pull request.
3. Add or update tests for each behavior that you change.
4. Match the style of the code around your change.
5. Update `README.md` or `server/README.md` when you change behavior that users see.
6. Add a line to `CHANGELOG.md` under **Unreleased**.

## Make a release

The version is in three files: `package.json`, `server/pyproject.toml`, and `server/src/talktome_server/__init__.py`.

1. Set the same version in the three files.
2. Run `npm install --package-lock-only` and `(cd server && uv lock)` to update the lock files.
3. Move the **Unreleased** lines in `CHANGELOG.md` under the new version.
4. Commit the change, then push a tag such as `v0.2.0`.

The release workflow stops if the tag does not match the three files.
It builds the disk image and the zip, then attaches them to a GitHub release.
The job summary shows the `sha256` value for the Homebrew cask.
If the repository variable `PUBLISH_PYPI` is `true`, the workflow also publishes `talktome-server` to PyPI.

## Style

- TypeScript: strict mode. The windows' scripts in `desktop/src/ui` are plain scripts with no imports.
- Python: ruff controls lint and format. Use the settings in `server/pyproject.toml`.
- Comments: explain why, not what. Remove a comment that only repeats the code.
- Documentation: write short, active sentences. Use one term for one thing.

## Where things are

| Path | Contents |
| --- | --- |
| `desktop/src/main.ts` | The Electron main process: the menu bar, the windows, and IPC |
| `desktop/src/phone/` | The call state, the hub, the links to each server, and machine setup |
| `desktop/src/ui/` and `desktop/ui/` | The call pill and the agents window |
| `server/` | `talktome-server`, the Python package that runs where agents run |
| `server/src/talktome_server/plugins/` | The plugins for Claude Code, Codex, Hermes, and OpenClaw |
| `docs/notes/` | Development notes from the earlier app. They can be out of date. |

## Security problems

Do not open a public issue. Read [SECURITY.md](SECURITY.md).

## License

You agree that your contribution uses the MIT license of this project. See [LICENSE](LICENSE).
