# Collect the license text of every runtime package the frozen server bundles.
# MIT and BSD licenses require their notices in a binary copy, and PyInstaller
# drops the dist-info folders that hold them. Run by packaging/build-server.sh.
import sys
from importlib import metadata
from pathlib import Path

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

ROOT = "talktome-local"


def runtime_closure():
    seen = {}
    visited = set()
    # A dependency such as pyjwt[crypto] pulls in more packages through the
    # extra, so each package is visited once for each extra it is asked for.
    pending = [(canonicalize_name(ROOT), "")]
    while pending:
        name, extra = pending.pop()
        if (name, extra) in visited:
            continue
        visited.add((name, extra))
        try:
            dist = seen.get(name) or metadata.distribution(name)
        except metadata.PackageNotFoundError:
            continue
        seen[name] = dist
        for line in dist.requires or []:
            requirement = Requirement(line)
            # Optional extras that nobody asked for, and other platforms, are
            # not in the bundle.
            if requirement.marker and not requirement.marker.evaluate({"extra": extra}):
                continue
            child = canonicalize_name(requirement.name)
            pending.append((child, ""))
            pending.extend((child, canonicalize_name(wanted)) for wanted in requirement.extras)
    seen.pop(canonicalize_name(ROOT), None)
    return sorted(seen.values(), key=lambda dist: dist.metadata["Name"].lower())


def license_texts(dist):
    for file in dist.files or []:
        name = file.name.upper()
        if any(word in name for word in ("LICENSE", "LICENCE", "COPYING", "NOTICE")):
            path = Path(dist.locate_file(file))
            if path.is_file():
                yield file.name, path.read_text(encoding="utf-8", errors="replace").strip()


def main(output):
    sections = []
    for dist in runtime_closure():
        meta = dist.metadata
        classifiers = [c for c in meta.get_all("Classifier") or [] if c.startswith("License")]
        header = [
            f"{meta['Name']} {dist.version}",
            f"License: {meta.get('License-Expression') or meta.get('License') or ', '.join(classifiers) or 'see below'}",
        ]
        if meta.get("Home-page"):
            header.append(f"Source: {meta['Home-page']}")
        body = [f"--- {name} ---\n{text}" for name, text in license_texts(dist)]
        if not body:
            body = ["No license file ships with this package. See its source for terms."]
        sections.append("\n".join(header) + "\n\n" + "\n\n".join(body))
    Path(output).parent.mkdir(parents=True, exist_ok=True)
    Path(output).write_text(("\n\n" + "=" * 72 + "\n\n").join(sections) + "\n", encoding="utf-8")
    print(f"Wrote {len(sections)} package licenses to {output}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "build/THIRD_PARTY_LICENSES.txt")
