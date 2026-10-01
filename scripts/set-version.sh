#!/bin/sh
# Set one version in the three files that carry it, and update both lock files.
#   sh scripts/set-version.sh 0.2.1
set -eu
version="${1:?give a version, for example 0.2.1}"
root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$root"

npm version "$version" --no-git-tag-version --allow-same-version > /dev/null
sed -i.bak "s/^version = \".*\"/version = \"$version\"/" server/pyproject.toml
sed -i.bak "s/^__version__ = \".*\"/__version__ = \"$version\"/" server/src/talktome_server/__init__.py
rm -f server/pyproject.toml.bak server/src/talktome_server/__init__.py.bak
(cd server && uv lock -q)

echo "Version $version is set in package.json, server/pyproject.toml, and talktome_server/__init__.py."
echo "Next: move the Unreleased lines in CHANGELOG.md under $version, commit, and push the tag v$version."
