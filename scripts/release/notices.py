"""THIRD-PARTY-NOTICES.txt for the release assets of the Open BIM Platform.

    python notices.py image <out> [--node-license <path>]   inside the kern image: Python, npm, Node.js and Debian
    python notices.py bundle <project> <dist> <out>          a built browser bundle: the packages its sourcemaps name

Standard library only and no network: what is listed follows from what is installed in the image or bundled by the
build. Per component the name, version, licence and the licence texts it ships, plus a link to the source of exactly
that version (the (L)GPL and MPL components need one; the others get it too).

A bundle needs hidden sourcemaps (`vite build --sourcemap hidden`): every source in them belongs to the nearest
package.json with a name above it (in node_modules or vendored), or to a vendored tree under `vendor/<name>/`;
sources of the project itself are left out. Files in the bundle without a sourcemap (an icon, a worker) are matched
on content against the project and node_modules.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import platform
import re
import subprocess
import sys
import sysconfig
from collections.abc import Callable
from dataclasses import dataclass, field

NOTICES = "THIRD-PARTY-NOTICES.txt"
LICENSE_FILE = re.compile(r"^(licen[cs]e|copying|notice|copyright|ofl|unlicense)([._-].*)?$", re.I)
# Vite makes no sourcemap for CSS; what a stylesheet holds follows from the CSS imports in the sources instead.
TRACEABLE = (".js", ".mjs", ".cjs", ".wasm")
VITE_SOURCE = re.compile(r"\x00|__vite-browser-external|(^|/)vite/(preload-helper|modulepreload-polyfill)")
VITE_RUNTIME = b"vite:preloadError"
CSS_IMPORT = re.compile(r"""(?:\bimport\s*\(?|\brequire\s*\(|@import)\s*(?:url\()?\s*['"]([^'"]+\.css)['"]""")
PACKAGE_NAME = re.compile(r"^((?:@[\w.-]+/)?[\w][\w.-]*)")
MIN_SIZE = 256  # smaller files are not matched on content (too many accidental equals)
UNKNOWN = "onbekend (niet in de pakketgegevens)"
HEAVY = "=" * 80
THIN = "-" * 80


@dataclass
class Component:
    name: str
    version: str
    license: str
    source: str = ""  # the source of exactly this version
    homepage: str = ""
    texts: list[tuple[str, str]] = field(default_factory=list)
    note: str = ""


def _read(path: str) -> str:
    with open(path, encoding="utf-8", errors="replace") as f:
        return f.read().strip("\n")


def _json(path: str) -> dict:
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _files(root: str, skip: tuple[str, ...] = ()) -> list[str]:
    found = []
    for base, dirs, names in os.walk(root):
        dirs[:] = [d for d in dirs if os.path.join(base, d) not in skip]
        found += [os.path.join(base, n) for n in names]
    return found


def _license_texts(directory: str) -> list[tuple[str, str]]:
    return [
        (name, _read(os.path.join(directory, name)))
        for name in sorted(os.listdir(directory))
        if LICENSE_FILE.match(name) and os.path.isfile(os.path.join(directory, name))
    ]


# --- npm --------------------------------------------------------------------------------------------------------


def _npm_license(pkg: dict) -> str:
    lic = pkg.get("license")
    if isinstance(lic, dict):
        lic = lic.get("type")
    if not lic and isinstance(pkg.get("licenses"), list):
        lic = " OR ".join(str(x.get("type") if isinstance(x, dict) else x) for x in pkg["licenses"])
    return str(lic or UNKNOWN)


def _npm_homepage(pkg: dict) -> str:
    repo = pkg.get("repository")
    if isinstance(repo, dict):
        repo = repo.get("url")
    return str(repo or pkg.get("homepage") or "")


def _npm_component(directory: str) -> Component | None:
    pkg = _json(os.path.join(directory, "package.json"))
    name, version = pkg.get("name"), pkg.get("version")
    if not name or not version:
        return None
    texts = _license_texts(directory)
    lic = _npm_license(pkg)
    note = "" if texts else f"Het pakket heeft geen licentiebestand; licentie volgens package.json: {lic}."
    return Component(
        name=str(name),
        version=str(version),
        license=_npm_license(pkg),
        source=f"https://registry.npmjs.org/{name}/-/{str(name).split('/')[-1]}-{version}.tgz",
        homepage=_npm_homepage(pkg),
        texts=texts,
        note=note,
    )


def _package_root(path: str) -> str | None:
    """The package directory a path in node_modules lies in: after the last `node_modules/` (with scope)."""
    parts = path.replace("\\", "/").split("/")
    if "node_modules" not in parts:
        return None
    i = len(parts) - 1 - parts[::-1].index("node_modules")
    if i + 1 >= len(parts) or parts[i + 1].startswith("."):
        return None
    end = i + 3 if parts[i + 1].startswith("@") else i + 2
    return "/".join(parts[:end]) if end <= len(parts) else None


def npm_components(node_modules: str) -> list[Component]:
    """Every package installed in node_modules, nested ones included (npm ci --omit=dev ships them all)."""
    found: dict[tuple[str, str], Component] = {}
    for base, dirs, names in os.walk(node_modules):
        dirs[:] = sorted(d for d in dirs if not d.startswith("."))
        root = _package_root(base)
        if "package.json" not in names or root is None or os.path.normpath(root) != os.path.normpath(base):
            continue
        component = _npm_component(base)
        if component:
            found.setdefault((component.name, component.version), component)
    return _sorted(found.values())


# --- a browser bundle --------------------------------------------------------------------------------------------


def _owner(path: str, project: str) -> str | None:
    """The package or vendored tree a file of the project belongs to; None for the project's own files."""
    project = os.path.normpath(project)
    vendor = os.path.join(project, "vendor")
    directory = os.path.dirname(os.path.normpath(path))
    while directory.startswith(project + os.sep):
        pkg = _json(os.path.join(directory, "package.json"))
        if pkg.get("name") and pkg.get("version"):
            return directory
        if os.path.dirname(directory) == vendor:
            return directory
        directory = os.path.dirname(directory)
    return None


def _vendored_component(directory: str) -> Component:
    texts = _license_texts(directory)
    name = os.path.basename(directory)
    return Component(
        name=name,
        version="meegeleverd",
        license=UNKNOWN if not texts else f"zie {texts[0][0]}",
        homepage=f"vendor/{name}/ in de broncode van deze release",
        texts=texts,
        note="Meegeleverde kopie in de repo; de broncode van deze versie staat in de broncode van deze release.",
    )


def _find_package(start: str, name: str, project: str) -> str | None:
    """The directory of package `name` as Node finds it from `start` (node_modules upwards, up to the project)."""
    directory = os.path.abspath(start)
    limit = os.path.dirname(os.path.abspath(project))
    while True:
        candidate = os.path.join(directory, "node_modules", *name.split("/"))
        if os.path.isfile(os.path.join(candidate, "package.json")):
            return os.path.normpath(os.path.realpath(candidate))
        parent = os.path.dirname(directory)
        if parent == directory or directory == limit:
            return None
        directory = parent


def _hidden(sourcemap: str) -> bool:
    """A sourcemap the file itself does not point to (from `--sourcemap hidden`)."""
    target = sourcemap[:-4]
    if not os.path.isfile(target):
        return False
    with open(target, "rb") as f:
        return b"sourceMappingURL=" not in f.read()


def bundle_components(project: str, dist: str) -> tuple[list[Component], list[str]]:
    """The third-party components in a built bundle, and the scripts in it that could not be traced to a source."""
    project, dist = os.path.abspath(project), os.path.abspath(dist)
    node_modules = os.path.join(project, "node_modules")
    every = [p for p in _files(dist) if not p.endswith(".gz") and os.path.basename(p) != NOTICES]
    maps = [p for p in every if p.endswith(".map")]
    owners: set[str] = set()
    covered: set[str] = set()
    own: set[str] = set()
    sources_of_packages: set[str] = set()
    vite = False

    # 1. The sourcemaps of the bundler.
    for sourcemap in maps:
        data = _json(sourcemap)
        sources = data.get("sources") or []
        if not isinstance(sources, list):
            continue
        covered.add(sourcemap[:-4])
        root = os.path.join(os.path.dirname(sourcemap), data.get("sourceRoot") or "")
        for source in sources:
            if not isinstance(source, str):
                continue
            source = source.split("?")[0]
            if VITE_SOURCE.search(source):
                vite = True  # virtual modules of the bundler
                continue
            path = os.path.normpath(os.path.join(root, source))
            owner = _owner(path, project)
            if owner:
                owners.add(owner)
                sources_of_packages.add(path)
            else:
                own.add(path)
    # Stylesheets are not in the sourcemaps of the scripts, and Vite makes no sourcemap for CSS: what a stylesheet holds
    # follows from the CSS imports in the sources that are in the bundle (`import "package/style.css"`, a relative
    # import, or `@import` in a stylesheet), followed through the stylesheets they import.
    todo, seen = sorted(own | sources_of_packages), set()
    while todo:
        path = todo.pop()
        if path in seen:
            continue
        seen.add(path)
        try:
            content = _read(path)
        except OSError:
            continue
        for specifier in CSS_IMPORT.findall(content):
            if specifier.startswith("."):
                target = os.path.normpath(os.path.join(os.path.dirname(path), specifier))
            else:
                name = PACKAGE_NAME.match(specifier)
                directory = _find_package(os.path.dirname(path), name.group(1), project) if name else None
                if not directory:
                    continue
                target = os.path.join(directory, *specifier[len(name.group(1)) :].lstrip("/").split("/"))
            if owner := _owner(target, project):
                owners.add(owner)
            todo.append(target)
    # The runtime of Vite (the preload helper) is in the bundle but not in the sourcemaps: it is known by its event.
    for path in every:
        if not vite and path.endswith((".js", ".mjs")):
            with open(path, "rb") as f:
                vite = VITE_RUNTIME in f.read()
    if vite and os.path.isfile(os.path.join(node_modules, "vite", "package.json")):
        owners.add(os.path.join(node_modules, "vite"))

    # 2. Copied as they are: the same content as a file in the project (node_modules included).
    rest = [p for p in every if not p.endswith(".map") and p not in covered]
    sizes = {os.path.getsize(p) for p in rest if os.path.getsize(p) >= MIN_SIZE}
    by_hash: dict[str, set[str | None]] = {}
    for candidate in _files(project, skip=(dist,)):
        try:
            if os.path.islink(candidate) or os.path.getsize(candidate) not in sizes:
                continue
        except OSError:
            continue
        by_hash.setdefault(_sha256(candidate), set()).add(_owner(candidate, project))
    untraced = []
    for path in rest:
        digest = _sha256(path) if os.path.getsize(path) >= MIN_SIZE else None
        if digest in by_hash:
            owners.update(o for o in by_hash[digest] if o)
        elif path.endswith(TRACEABLE):
            untraced.append(os.path.relpath(path, dist).replace(os.sep, "/"))

    found: dict[tuple[str, str], Component] = {}
    for directory in sorted(owners):
        has_package = os.path.isfile(os.path.join(directory, "package.json"))
        component = _npm_component(directory) if has_package else _vendored_component(directory)
        if component:
            found.setdefault((component.name, component.version), component)
    return _sorted(found.values()), sorted(untraced)


def remove_hidden_sourcemaps(dist: str) -> None:
    for path in _files(dist):
        if path.endswith(".map") and _hidden(path):
            os.remove(path)


# --- Python ------------------------------------------------------------------------------------------------------


def _base_version(version: str) -> str:
    match = re.match(r"\d+(\.\d+)*", version)
    return match.group(0) if match else version


def _shapely(version: str) -> dict:
    try:
        import shapely

        geos = shapely.geos_version_string
    except Exception:  # noqa: BLE001  (not installed here, or no GEOS)
        return {}
    return {
        "note": f"De wheel bevat GEOS {geos} (LGPL-2.1-or-later), broncode: https://github.com/libgeos/geos/tree/{geos}"
    }


# Wheels without licence metadata, or that bundle libraries under a licence of their own.
PYTHON_EXTRA: dict[str, Callable[[str], dict]] = {
    "ifcopenshell": lambda version: {
        "license": "LGPL-3.0-or-later",
        "source": f"https://github.com/IfcOpenShell/IfcOpenShell/tree/ifcopenshell-python-{_base_version(version)}",
        "note": "De wheel bevat bibliotheken zoals Open CASCADE; hun versies liggen vast in de bouwscripts bij die "
        "tag. De tekst van de LGPL-3.0 staat in COPYING.LESSER.",
    },
    "shapely": _shapely,
}


def _python_license(md) -> str:
    if expression := md.get("License-Expression"):
        return expression
    classifiers = [c.split(" :: ")[-1] for c in md.get_all("Classifier") or [] if c.startswith("License :: ")]
    text = (md.get("License") or "").strip()
    if text and "\n" not in text and len(text) <= 80:
        return f"{text} ({'; '.join(classifiers)})" if classifiers and text not in classifiers else text
    return "; ".join(classifiers) or UNKNOWN


def _python_homepage(md) -> str:
    urls = {}
    for entry in md.get_all("Project-URL") or []:
        label, _, url = entry.partition(",")
        urls[label.strip().lower()] = url.strip()
    for label in ("source", "source code", "repository", "homepage", "home"):
        if urls.get(label):
            return urls[label]
    return md.get("Home-page") or ""


def python_components(exclude: set[str] = frozenset()) -> list[Component]:
    """Every installed distribution, with the licence files in its dist-info."""
    excluded = {e.lower() for e in exclude}
    found: dict[tuple[str, str], Component] = {}
    for dist in importlib.metadata.distributions():
        md = dist.metadata
        name = md.get("Name") or ""
        if not name or name.lower() in excluded or (name.lower(), dist.version) in found:
            continue
        texts = []
        for path in dist.files or []:
            parts = path.parts
            in_info = parts and parts[0].endswith(".dist-info")
            if in_info and (LICENSE_FILE.match(path.name) or "licenses" in parts[1:-1]):
                try:
                    texts.append((path.name, path.read_text(encoding="utf-8").strip("\n")))
                except (OSError, UnicodeDecodeError):
                    continue
        component = Component(
            name=name,
            version=dist.version,
            license=_python_license(md),
            source=f"https://pypi.org/project/{name}/{dist.version}/#files",
            homepage=_python_homepage(md),
            texts=texts,
        )
        if extra := PYTHON_EXTRA.get(name.lower()):
            for key, value in extra(dist.version).items():
                setattr(component, key, value)
        found[(name.lower(), dist.version)] = component
    return _sorted(found.values())


# --- the image: interpreters and the operating system ------------------------------------------------------------


def runtime_components(node_license: str | None) -> list[Component]:
    """Python itself, and Node.js when it is on the path."""
    version = platform.python_version()
    python_license = os.path.join(sysconfig.get_paths()["stdlib"], "LICENSE.txt")
    found = [
        Component(
            name="Python",
            version=version,
            license="PSF-2.0",
            source=f"https://www.python.org/ftp/python/{version}/",
            homepage="https://www.python.org",
            texts=[("LICENSE.txt", _read(python_license))] if os.path.isfile(python_license) else [],
        )
    ]
    try:
        node = subprocess.run(["node", "--version"], capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return found
    found.append(
        Component(
            name="Node.js",
            version=node.lstrip("v"),
            license="MIT (en de licenties van de meegebouwde bibliotheken in LICENSE)",
            source=f"https://github.com/nodejs/node/tree/{node}",
            homepage="https://nodejs.org",
            texts=[("LICENSE", _read(node_license))] if node_license and os.path.isfile(node_license) else [],
        )
    )
    return found


def _dpkg() -> str | None:
    query = "${binary:Package}\t${Version}\t${source:Package}\t${source:Version}\n"
    try:
        return subprocess.run(["dpkg-query", "-W", "-f", query], capture_output=True, text=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError):
        return None


def debian_packages(query: Callable[[], str | None] = _dpkg) -> list[tuple[str, str, str]]:
    """(package, version, link to the source of exactly that version) of the packages of the base image."""
    output = query()
    if not output:
        return []
    found = []
    for line in output.splitlines():
        parts = line.split("\t")
        if len(parts) != 4 or not parts[0]:
            continue
        package, version, source, source_version = parts
        found.append((package, version, f"https://snapshot.debian.org/package/{source}/{source_version}/"))
    return sorted(found)


# --- writing -----------------------------------------------------------------------------------------------------


def _sorted(components) -> list[Component]:
    return sorted(components, key=lambda c: (c.name.lower(), c.version))


def write(path: str, title: str, intro: list[str], groups: list[tuple[str, list[Component]]], debian=()) -> None:
    lines = [f"{title}: onderdelen van derden", "", *intro, ""]
    for heading, components in groups:
        if components:
            lines += [f"{heading} ({len(components)}):"]
            lines += [f"  {c.name} {c.version} ({c.license})" for c in components]
            lines.append("")
    if debian:
        lines += [
            f"Debian-pakketten van het basisimage ({len(debian)}); per pakket de licentie en copyright in",
            "/usr/share/doc/<pakket>/copyright in het image, en de broncode van precies die versie:",
        ]
        lines += [f"  {package} {version}  {source}" for package, version, source in debian]
        lines.append("")
    for _, components in groups:
        for c in components:
            lines += [HEAVY, f"{c.name} {c.version}", f"Licentie: {c.license}"]
            if c.source:
                lines.append(f"Broncode van deze versie: {c.source}")
            if c.homepage:
                lines.append(f"Website: {c.homepage}")
            if c.note:
                lines.append(f"Opmerking: {c.note}")
            for name, text in c.texts:
                lines += [THIN, f"[{name}]", text]
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines).rstrip("\n") + "\n")


def image(out: str, node_license: str | None, node_modules: str, exclude: set[str]) -> None:
    write(
        out,
        "Open BIM Platform, BIM-kern (container-image)",
        [
            "Gemaakt door scripts/release/notices.py tijdens de bouw van het image, uit wat er in het image is",
            "geinstalleerd: de Python-distributies, de npm-pakketten van de omzetter, Python en Node.js zelf, en de",
            "Debian-pakketten van het basisimage. De BIM-kern zelf valt onder de LGPL-3.0-or-later (COPYING.LESSER",
            "en COPYING naast dit bestand); de broncode van deze versie staat in bron.json.",
        ],
        [
            ("Runtimes", runtime_components(node_license)),
            ("Python-distributies", python_components(exclude)),
            ("npm-pakketten van de omzetter", npm_components(node_modules) if os.path.isdir(node_modules) else []),
        ],
        debian_packages(),
    )


def bundle(project: str, dist: str, out: str, title: str) -> list[str]:
    components, untraced = bundle_components(project, dist)
    write(
        out,
        title,
        [
            "Gemaakt door scripts/release/notices.py uit de gebouwde bundel: de bronnen in de sourcemaps van de",
            "bundler en de bestanden die ongewijzigd uit het project of node_modules zijn meegekopieerd. Naam,",
            "versie en licentie uit package.json van elk pakket, de licentieteksten uit het pakket zelf. De viewer",
            "zelf valt onder de LGPL-3.0-or-later (COPYING.LESSER en COPYING); de broncode van deze versie staat in",
            "bron.json.",
        ],
        [("npm-pakketten en meegeleverde onderdelen", components)],
    )
    return untraced


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="mode", required=True)
    p_image = sub.add_parser("image")
    p_image.add_argument("out")
    p_image.add_argument("--node-license")
    p_image.add_argument("--node-modules", default="/app/converter/node_modules")
    p_image.add_argument("--exclude", action="append", default=["openbim-kern"])
    p_bundle = sub.add_parser("bundle")
    p_bundle.add_argument("project")
    p_bundle.add_argument("dist")
    p_bundle.add_argument("out")
    p_bundle.add_argument("--title", default="Open BIM Platform, viewer")
    args = parser.parse_args()
    if args.mode == "image":
        image(args.out, args.node_license, args.node_modules, set(args.exclude))
    else:
        for path in bundle(args.project, args.dist, args.out, args.title):
            print(f"LET OP: {path} heeft geen sourcemap en komt niet uit het project of node_modules", file=sys.stderr)
