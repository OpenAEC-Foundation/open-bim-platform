import base64
import hashlib
import json
import os
import tarfile

import assets
import bron
import notices
import pytest

COMMIT = "a" * 40


def schrijf(pad, inhoud):
    os.makedirs(os.path.dirname(pad), exist_ok=True)
    with open(pad, "w", encoding="utf-8", newline="\n") as f:
        f.write(inhoud)


def pakket(map_, naam, versie, licentie="MIT", licentietekst=None):
    schrijf(os.path.join(map_, "package.json"), json.dumps({"name": naam, "version": versie, "license": licentie}))
    if licentietekst:
        schrijf(os.path.join(map_, "LICENSE"), licentietekst)


@pytest.fixture
def project(tmp_path):
    """A built viewer: an own source, a package from node_modules, a vendored package and a vendored tree."""
    p = str(tmp_path / "viewer")
    pakket(p, "openbim-viewer", "0.1.0", "LGPL-3.0-or-later")
    pakket(os.path.join(p, "node_modules", "foo"), "foo", "1.2.3", licentietekst="foo licence text")
    pakket(os.path.join(p, "node_modules", "@scope", "bar"), "@scope/bar", "2.0.0", "MPL-2.0")
    pakket(os.path.join(p, "vendor", "boek", "packages", "shell"), "@boek/shell", "0.1.0")
    schrijf(os.path.join(p, "vendor", "boek", "LICENSE"), "boek licence text")
    schrijf(os.path.join(p, "vendor", "boek", "logos", "logo.svg"), "<svg>" + "x" * 400 + "</svg>")
    pakket(os.path.join(p, "node_modules", "kleur"), "kleur", "4.0.0", "ISC")
    schrijf(os.path.join(p, "node_modules", "kleur", "kleur.css"), "a{}")
    schrijf(os.path.join(p, "vendor", "thema", "LICENSE"), "thema licence text")
    schrijf(os.path.join(p, "vendor", "thema", "themes.css"), '@import "./basis.css";')
    schrijf(os.path.join(p, "vendor", "thema", "basis.css"), "body{}")
    schrijf(os.path.join(p, "src", "main.ts"), 'import "kleur/kleur.css";\nimport "../vendor/thema/themes.css";\n')
    for bronpad in ("node_modules/foo/index.js", "node_modules/@scope/bar/dist/index.mjs"):
        schrijf(os.path.join(p, bronpad), "export {};\n")
    dist = os.path.join(p, "dist")
    schrijf(
        os.path.join(dist, "index.html"),
        '<!doctype html>\n<html>\n  <head>\n    <link rel="icon" href="./assets/logo.svg" />\n'
        '    <script type="module" crossorigin src="./assets/index.js"></script>\n'
        '    <link rel="stylesheet" crossorigin href="./assets/index.css">\n  </head>\n'
        '  <body><div id="root"></div></body>\n</html>\n',
    )
    schrijf(os.path.join(dist, "assets", "index.js"), "console.log(1);\n")
    schrijf(os.path.join(dist, "assets", "index.css"), "body{margin:0}\n")
    schrijf(os.path.join(dist, "assets", "logo.svg"), "<svg>" + "x" * 400 + "</svg>")
    bronnen = [
        "../../src/main.ts",
        "../../node_modules/foo/index.js",
        "../../node_modules/@scope/bar/dist/index.mjs",
        "../../vendor/boek/packages/shell/src/Shell.tsx",
    ]
    schrijf(os.path.join(dist, "assets", "index.js.map"), json.dumps({"version": 3, "sources": bronnen}))
    return p


def test_bron_heeft_de_velden_van_het_contract():
    assert bron.source_info("2026.44.1", "v2026.44.1", COMMIT) == {
        "versie": "2026.44.1",
        "tag": "v2026.44.1",
        "commit": COMMIT,
        "licentie": "LGPL-3.0-or-later",
        "broncode": "https://github.com/OpenAEC-Foundation/open-bim-platform",
    }


def test_een_tag_moet_bij_de_versie_passen():
    with pytest.raises(ValueError):
        bron.source_info("2026.44.1", "v2026.44.2", COMMIT)
    with pytest.raises(ValueError):
        bron.source_info("2026.44.1", "v2026.44.1", "abc")


def test_de_bundel_noemt_de_pakketten_uit_de_sourcemaps(project):
    componenten, niet_herleid = notices.bundle_components(project, os.path.join(project, "dist"))
    namen = {(c.name, c.version) for c in componenten}
    assert ("foo", "1.2.3") in namen
    assert ("@scope/bar", "2.0.0") in namen
    assert ("@boek/shell", "0.1.0") in namen
    assert "boek" in {c.name for c in componenten}  # the logo is copied from the vendored tree
    assert ("kleur", "4.0.0") in namen  # only imported as a stylesheet
    assert "thema" in {c.name for c in componenten}  # a vendored stylesheet, by a relative import
    assert "openbim-viewer" not in {c.name for c in componenten}
    assert niet_herleid == []
    foo = next(c for c in componenten if c.name == "foo")
    assert foo.texts == [("LICENSE", "foo licence text")]
    assert foo.source == "https://registry.npmjs.org/foo/-/foo-1.2.3.tgz"
    bar = next(c for c in componenten if c.name == "@scope/bar")
    assert bar.source == "https://registry.npmjs.org/@scope/bar/-/bar-2.0.0.tgz"


def test_npm_noemt_elk_geinstalleerd_pakket_ook_genest(tmp_path):
    nm = str(tmp_path / "node_modules")
    pakket(os.path.join(nm, "a"), "a", "1.0.0")
    pakket(os.path.join(nm, "a", "node_modules", "b"), "b", "3.1.0", "ISC")
    pakket(os.path.join(nm, "a", "dist", "esm"), "", "")  # a type stub without a name is no package
    componenten = notices.npm_components(nm)
    assert [(c.name, c.version, c.license) for c in componenten] == [("a", "1.0.0", "MIT"), ("b", "3.1.0", "ISC")]


def test_python_noemt_de_geinstalleerde_distributies():
    componenten = notices.python_components(exclude={"pytest"})
    namen = {c.name.lower() for c in componenten}
    assert "pluggy" in namen and "pytest" not in namen
    pluggy = next(c for c in componenten if c.name.lower() == "pluggy")
    assert pluggy.license and pluggy.texts
    assert pluggy.source == f"https://pypi.org/project/pluggy/{pluggy.version}/#files"


def test_debian_wijst_naar_de_bron_van_precies_die_versie():
    uitvoer = "libc6\t2.36-9+deb12u10\tglibc\t2.36-9+deb12u10\nbash\t5.2.15-2+b8\tbash\t5.2.15-2\n"
    pakketten = notices.debian_packages(lambda: uitvoer)
    assert pakketten[0] == (
        "bash",
        "5.2.15-2+b8",
        "https://snapshot.debian.org/package/bash/5.2.15-2/",
    )
    assert notices.debian_packages(lambda: None) == []


def test_sri_op_lokale_scripts_en_stylesheets(project):
    dist = os.path.join(project, "dist")
    html = assets.add_sri(open(os.path.join(dist, "index.html"), encoding="utf-8").read(), dist)
    js = open(os.path.join(dist, "assets", "index.js"), "rb").read()
    verwacht = "sha384-" + base64.b64encode(hashlib.sha384(js).digest()).decode()
    assert f'src="./assets/index.js" integrity="{verwacht}"' in html
    assert html.count("crossorigin") == 2
    assert 'href="./assets/logo.svg" />' in html  # an icon needs no SRI


@pytest.mark.parametrize(
    "fout",
    ["<script>alert(1)</script>", '<div onclick="x()"></div>', '<script src="https://cdn.example/x.js"></script>'],
)
def test_inline_code_en_scripts_van_buiten_worden_geweigerd(tmp_path, fout):
    with pytest.raises(ValueError):
        assets.add_sri(f"<html><body>{fout}</body></html>", str(tmp_path))


def test_het_manifest_noemt_elk_bestand_met_zijn_sha256(tmp_path):
    schrijf(str(tmp_path / "a.txt"), "a")
    schrijf(str(tmp_path / "sub" / "b.txt"), "b")
    assets.write_manifest(str(tmp_path))
    regels = (tmp_path / "MANIFEST.sha256").read_text(encoding="utf-8").splitlines()
    assert regels == [
        f"{hashlib.sha256(b'a').hexdigest()}  a.txt",
        f"{hashlib.sha256(b'b').hexdigest()}  sub/b.txt",
    ]


def test_de_webbundel_is_compleet_en_reproduceerbaar(project, tmp_path):
    repo = os.path.dirname(project)
    schrijf(os.path.join(repo, "COPYING"), "gpl")
    schrijf(os.path.join(repo, "COPYING.LESSER"), "lgpl")
    uit1, uit2 = str(tmp_path / "uit1"), str(tmp_path / "uit2")
    kwargs = dict(version="2026.44.1", tag="v2026.44.1", commit=COMMIT, mtime=1_700_000_000, licences=repo)
    a = assets.web_asset(os.path.join(project, "dist"), project, uit1, **kwargs)
    b = assets.web_asset(os.path.join(project, "dist"), project, uit2, **kwargs)
    assert os.path.basename(a) == "open-bim-platform-web-2026.44.1.tar.gz"
    assert open(a, "rb").read() == open(b, "rb").read()
    som = open(a + ".sha256", encoding="utf-8").read()
    assert som == f"{hashlib.sha256(open(a, 'rb').read()).hexdigest()}  {os.path.basename(a)}\n"
    with tarfile.open(a) as t:
        namen = set(t.getnames())
        verplicht = {
            "index.html",
            "bron.json",
            "MANIFEST.sha256",
            "THIRD-PARTY-NOTICES.txt",
            "COPYING",
            "COPYING.LESSER",
        }
        assert verplicht <= namen
        assert "assets/index.js.map" not in namen  # hidden sourcemaps stay out of the asset
        assert json.load(t.extractfile("bron.json"))["tag"] == "v2026.44.1"
        assert b"integrity=" in t.extractfile("index.html").read()
        assert b"foo 1.2.3 (MIT)" in t.extractfile("THIRD-PARTY-NOTICES.txt").read()
    # The build output itself is left as it was.
    assert os.path.isfile(os.path.join(project, "dist", "assets", "index.js.map"))


def test_de_frappe_app_staat_in_een_eigen_map(tmp_path):
    repo = str(tmp_path / "repo")
    schrijf(os.path.join(repo, "COPYING"), "gpl")
    schrijf(os.path.join(repo, "COPYING.LESSER"), "lgpl")
    app = os.path.join(repo, "frappe", "openaec_bim")
    schrijf(os.path.join(app, "pyproject.toml"), "[project]\nname = 'openaec_bim'\n")
    schrijf(os.path.join(app, "openaec_bim", "__init__.py"), '__version__ = "0.1.0"\n')
    schrijf(os.path.join(app, "openaec_bim", "__pycache__", "x.pyc"), "niet mee")
    uit = assets.frappe_asset(
        app,
        ["pyproject.toml", "openaec_bim/__init__.py"],
        str(tmp_path / "uit"),
        version="2026.44.1",
        tag="v2026.44.1",
        commit=COMMIT,
        mtime=1_700_000_000,
        licences=repo,
    )
    assert os.path.basename(uit) == "openaec_bim-2026.44.1.tar.gz"
    with tarfile.open(uit) as t:
        namen = set(t.getnames())
    assert {
        "openaec_bim/pyproject.toml",
        "openaec_bim/openaec_bim/__init__.py",
        "openaec_bim/bron.json",
        "openaec_bim/COPYING.LESSER",
        "openaec_bim/MANIFEST.sha256",
        "openaec_bim/THIRD-PARTY-NOTICES.txt",
    } <= namen
    assert not any("__pycache__" in n for n in namen)
