"""The release assets of the Open BIM Platform besides the container image, as the SuperCloud contract asks.

    python assets.py web --out release --version 2026.44.1 --tag v2026.44.1 --commit <sha>      (viewer/dist)
    python assets.py frappe --out release --version 2026.44.1 --tag v2026.44.1 --commit <sha>   (frappe/openaec_bim)

`web` makes open-bim-platform-web-<version>.tar.gz from a viewer built with `vite build --sourcemap hidden`: SRI on
every script and stylesheet in index.html (inline code and scripts from elsewhere are refused), THIRD-PARTY-NOTICES.txt
from the sourcemaps (which then leave the bundle), bron.json, COPYING and COPYING.LESSER, and MANIFEST.sha256.
`frappe` makes openaec_bim-<version>.tar.gz: the files of the Frappe app that git tracks, in a directory openaec_bim/,
with the same additions. Every asset gets a <asset>.sha256 next to it. The tarballs are reproducible: sorted, owner 0,
and every timestamp set to the commit time (`--mtime`, default: the commit time from git).
"""

from __future__ import annotations

import argparse
import base64
import gzip
import hashlib
import io
import os
import re
import shutil
import subprocess
import tarfile
import tempfile

import bron
import notices

MANIFEST = "MANIFEST.sha256"
LICENCES = ("COPYING", "COPYING.LESSER")
TAG = re.compile(r"<(script|link)\b([^>]*)>", re.I)
ATTRIBUTE = re.compile(r'([\w:-]+)(?:\s*=\s*(?:"([^"]*)"|\'([^\']*)\'|([^\s>]+)))?')
INLINE_SCRIPT = re.compile(r"<script\b(?![^>]*\bsrc\s*=)[^>]*>\s*\S", re.I)
EVENT_HANDLER = re.compile(r"<[^>]+\son[a-z]+\s*=", re.I)
NEEDS_SRI = {"stylesheet", "modulepreload", "preload"}


def _attributes(text: str) -> dict[str, str | None]:
    found = {}
    for m in ATTRIBUTE.finditer(text):
        value = next((g for g in m.group(2, 3, 4) if g is not None), None)
        found[m.group(1).lower()] = value
    return found


def _sri(path: str) -> str:
    with open(path, "rb") as f:
        return "sha384-" + base64.b64encode(hashlib.sha384(f.read()).digest()).decode()


def add_sri(html: str, root: str) -> str:
    """index.html with integrity and crossorigin on every local script, stylesheet and (module)preload."""
    if INLINE_SCRIPT.search(html):
        raise ValueError("index.html has inline script; the werkplek allows scripts from the bundle only")
    if EVENT_HANDLER.search(html):
        raise ValueError("index.html has an on... attribute; the werkplek allows no inline code")

    def replace(m: re.Match) -> str:
        tag, attrs = m.group(1).lower(), m.group(2)
        values = _attributes(attrs)
        if tag == "link" and (values.get("rel") or "").lower() not in NEEDS_SRI:
            return m.group(0)
        address = values.get("src" if tag == "script" else "href")
        if not address:
            return m.group(0)
        if re.match(r"^([a-z][a-z0-9+.-]*:|//)", address, re.I):
            raise ValueError(f"index.html loads {address} from elsewhere; everything must come from the bundle")
        path = os.path.normpath(os.path.join(root, address.split("?")[0].split("#")[0]))
        if not os.path.isfile(path):
            raise ValueError(f"index.html refers to {address}, which is not in the bundle")
        end = attrs.rstrip()
        closing = "/" if end.endswith("/") else ""
        end = end[:-1].rstrip() if closing else end
        extra = f' integrity="{_sri(path)}"' if "integrity" not in values else ""
        extra += ' crossorigin="anonymous"' if "crossorigin" not in values else ""
        return f"<{m.group(1)}{end}{extra}{' ' + closing if closing else ''}>"

    return TAG.sub(replace, html)


def _relative_files(root: str) -> list[str]:
    found = []
    for base, dirs, names in os.walk(root):
        dirs.sort()
        for name in names:
            found.append(os.path.relpath(os.path.join(base, name), root).replace(os.sep, "/"))
    return sorted(found)


def write_manifest(root: str) -> None:
    """MANIFEST.sha256 in the format of sha256sum: every file of the directory except the manifest itself."""
    lines = []
    for rel in _relative_files(root):
        if rel != MANIFEST:
            with open(os.path.join(root, rel), "rb") as f:
                lines.append(f"{hashlib.sha256(f.read()).hexdigest()}  {rel}")
    with open(os.path.join(root, MANIFEST), "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines) + "\n")


def _tarball(root: str, out: str, mtime: int, prefix: str = "") -> None:
    """A reproducible .tar.gz of `root`: sorted, owner 0, mode 644/755, every timestamp `mtime`, gzip without name."""
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w", format=tarfile.PAX_FORMAT) as tar:
        directories = set()
        for rel in _relative_files(root):
            parts = rel.split("/")
            for i in range(1, len(parts)):
                directories.add("/".join(parts[:i]))
        entries = [(d, True) for d in directories] + [(f, False) for f in _relative_files(root)]
        if prefix:
            entries.append(("", True))
        for rel, is_dir in sorted(entries):
            name = "/".join(p for p in (prefix, rel) if p)
            info = tarfile.TarInfo(name)
            info.mtime, info.uid, info.gid, info.uname, info.gname = mtime, 0, 0, "", ""
            if is_dir:
                info.type, info.mode = tarfile.DIRTYPE, 0o755
                tar.addfile(info)
            else:
                path = os.path.join(root, rel)
                info.size, info.mode = os.path.getsize(path), 0o644
                with open(path, "rb") as f:
                    tar.addfile(info, f)
    with open(out, "wb") as f, gzip.GzipFile(filename="", mode="wb", fileobj=f, mtime=mtime) as gz:
        gz.write(buffer.getvalue())
    with open(out, "rb") as f:
        digest = hashlib.sha256(f.read()).hexdigest()
    with open(out + ".sha256", "w", encoding="utf-8", newline="\n") as f:
        f.write(f"{digest}  {os.path.basename(out)}\n")


def _finish(directory: str, licences: str, version: str, tag: str, commit: str) -> None:
    for name in LICENCES:
        shutil.copyfile(os.path.join(licences, name), os.path.join(directory, name))
    bron.write(os.path.join(directory, "bron.json"), version, tag, commit)
    write_manifest(directory)


def web_asset(
    dist: str, project: str, out: str, *, version: str, tag: str, commit: str, mtime: int, licences: str
) -> str:
    """open-bim-platform-web-<version>.tar.gz from the built viewer; the build output itself is left as it was."""
    os.makedirs(out, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        stage = os.path.join(tmp, "web")
        shutil.copytree(dist, stage)
        # The sourcemaps point into the project, so the notices are made from the build output where it lies.
        untraced = notices.bundle(project, dist, os.path.join(stage, notices.NOTICES), "Open BIM Platform, viewer")
        if untraced:
            raise ValueError(f"no source found for {', '.join(untraced)}; the notices would be incomplete")
        notices.remove_hidden_sourcemaps(stage)
        index = os.path.join(stage, "index.html")
        with open(index, encoding="utf-8") as f:
            html = add_sri(f.read(), stage)
        with open(index, "w", encoding="utf-8", newline="\n") as f:
            f.write(html)
        _finish(stage, licences, version, tag, commit)
        asset = os.path.join(out, f"open-bim-platform-web-{version}.tar.gz")
        _tarball(stage, asset, mtime)
    return asset


def frappe_asset(
    app: str, files: list[str], out: str, *, version: str, tag: str, commit: str, mtime: int, licences: str
) -> str:
    """openaec_bim-<version>.tar.gz: the given files of the app (relative to `app`) in a directory openaec_bim/."""
    os.makedirs(out, exist_ok=True)
    name = os.path.basename(os.path.normpath(app))
    with tempfile.TemporaryDirectory() as tmp:
        stage = os.path.join(tmp, name)
        for rel in files:
            target = os.path.join(stage, *rel.split("/"))
            os.makedirs(os.path.dirname(target), exist_ok=True)
            shutil.copyfile(os.path.join(app, *rel.split("/")), target)
        with open(os.path.join(stage, notices.NOTICES), "w", encoding="utf-8", newline="\n") as f:
            f.write(
                f"Open BIM Platform, Frappe-app {name}: onderdelen van derden\n\n"
                "Deze app bevat geen code van derden. Wat hij nodig heeft (Frappe, OpenAEC Storage en de\n"
                "Python-pakketten uit pyproject.toml) installeert de bench zelf, met hun eigen licenties.\n"
                "De app valt onder de LGPL-3.0-or-later (COPYING.LESSER en COPYING); de broncode van deze versie\n"
                "staat in bron.json.\n"
            )
        _finish(stage, licences, version, tag, commit)
        asset = os.path.join(out, f"{name}-{version}.tar.gz")
        _tarball(stage, asset, mtime, prefix=name)
    return asset


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], capture_output=True, text=True, check=True).stdout


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("kind", choices=("web", "frappe"))
    parser.add_argument("--dist", default="viewer/dist")
    parser.add_argument("--project", default="viewer")
    parser.add_argument("--app", default="frappe/openaec_bim")
    parser.add_argument("--out", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--tag", default="")
    parser.add_argument("--commit", required=True)
    parser.add_argument("--mtime", type=int)
    parser.add_argument("--licences", default=".")
    args = parser.parse_args()
    mtime = args.mtime if args.mtime is not None else int(_git("log", "-1", "--format=%ct", args.commit).strip())
    common = dict(version=args.version, tag=args.tag, commit=args.commit, mtime=mtime, licences=args.licences)
    if args.kind == "web":
        asset = web_asset(args.dist, args.project, args.out, **common)
    else:
        tracked = _git("ls-files", "-z", "--", args.app).split("\0")
        prefix = args.app.rstrip("/").replace(os.sep, "/") + "/"
        files = [p[len(prefix) :] for p in tracked if p.startswith(prefix)]
        asset = frappe_asset(args.app, files, args.out, **common)
    print(asset)
