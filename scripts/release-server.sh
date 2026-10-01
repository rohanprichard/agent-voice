#!/bin/sh
# Build talktome-server, check it, and publish it.
#
#   sh scripts/release-server.sh check      test, build, and install the result in a clean folder
#   sh scripts/release-server.sh testpypi   check, then upload to TestPyPI
#   sh scripts/release-server.sh pypi       check, then upload to PyPI
#
# An upload needs a token in UV_PUBLISH_TOKEN, from TestPyPI or PyPI
# (Account settings > API tokens). The GitHub workflow publish-server.yml
# uploads with trusted publishing instead, and needs no token.
set -eu
target="${1:-check}"
root="$(cd "$(dirname "$0")/.." && pwd)"
server="$root/server"
cd "$server"

version=$(sed -n 's/^version = "\(.*\)"/\1/p' pyproject.toml)
package=$(sed -n 's/^__version__ = "\(.*\)"/\1/p' src/talktome_server/__init__.py)
app=$(node -p "require('$root/package.json').version" 2>/dev/null || echo "$version")
if [ "$version" != "$package" ] || [ "$version" != "$app" ]; then
  echo "The versions do not match: pyproject.toml $version, __init__.py $package, package.json $app." >&2
  echo "Set them with: sh scripts/set-version.sh $version" >&2
  exit 1
fi

echo "== talktome-server $version: tests"
uv sync -q --frozen
uv run -q pytest -q
uvx -q ruff check src tests
uvx -q ruff format --check src tests > /dev/null

echo "== build"
rm -rf dist
uv build -q
uvx -q twine check dist/*

echo "== install the source archive in a clean folder"
scratch=$(mktemp -d)
trap 'rm -rf "$scratch"' EXIT
mkdir -p "$scratch/home/.claude"
HOME="$scratch/home" UV_TOOL_DIR="$scratch/tools" UV_TOOL_BIN_DIR="$scratch/bin" \
  uv tool install -q "$(ls "$server"/dist/*.tar.gz)"
installed=$("$scratch/bin/talktome-server" version)
[ "$installed" = "$version" ] || { echo "The installed version is $installed, not $version." >&2; exit 1; }
HOME="$scratch/home" "$scratch/bin/talktome-server" plugin install --host claude > /dev/null
test -f "$scratch/home/.claude/skills/talktome/.claude-plugin/plugin.json"
echo "Installed $installed, and its Claude Code plugin installs."

case "$target" in
  check)
    echo "== ready: $(ls dist | tr '\n' ' ')"
    ;;
  testpypi)
    echo "== upload to TestPyPI"
    uv publish --publish-url https://test.pypi.org/legacy/ dist/*
    echo "Try it: uv tool install --index-url https://test.pypi.org/simple/ --extra-index-url https://pypi.org/simple/ --index-strategy unsafe-best-match talktome-server==$version"
    ;;
  pypi)
    echo "== upload to PyPI"
    uv publish dist/*
    echo "Try it: uv tool install talktome-server==$version"
    ;;
  *)
    echo "Use: sh scripts/release-server.sh check|testpypi|pypi" >&2
    exit 2
    ;;
esac
