import json

import ifcopenshell
import pytest
from pydantic import ValidationError
from test_index import first_wall_globalid
from werkzeug import Response

from openbim_kern import CONVERTER_VERSION
from openbim_kern.errors import KernError
from openbim_kern.index.properties import read_properties
from openbim_kern.index.spatial import build_summary
from openbim_kern.tools.omzetten import OmzetVerzoek, omzetten
from openbim_kern.tools.registry import REGISTRY

BASE = ["index.json", "eigenschappen.sqlite", "ruimtelijk.json"]


@pytest.fixture(autouse=True)
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENBIM_KERN_DATA", str(tmp_path / "data"))
    return tmp_path / "data"


def run_omzetten(httpserver, ifc, names, *, grootte=True, progress=None):
    """Serve `ifc` as the source, run the tool with a PUT target per name; returns (uitkomst, received bodies)."""
    received: dict[str, bytes] = {}

    def target(name):
        def handler(request):
            received[name] = request.get_data()
            return Response(status=200)

        httpserver.expect_request(f"/uit/{name}", method="PUT").respond_with_handler(handler)
        return httpserver.url_for(f"/uit/{name}")

    httpserver.expect_request("/bron.ifc", method="GET").respond_with_data(ifc.read_bytes())
    bron = {"url": httpserver.url_for("/bron.ifc")}
    if grootte:
        bron["grootte"] = ifc.stat().st_size
    invoer = OmzetVerzoek(bron=bron, doelen={name: target(name) for name in names})
    return (omzetten(invoer, progress=progress) if progress else omzetten(invoer)), received


def globalids(tree):
    yield tree["globalid"]
    for child in tree["kinderen"]:
        yield from globalids(child)


def wall_globalids(ifc):
    return [w.GlobalId for w in ifcopenshell.open(str(ifc)).by_type("IfcWall")]


def properties_db(received, tmp_path):
    db = tmp_path / "ontvangen.sqlite"
    db.write_bytes(received["eigenschappen.sqlite"])
    return db


def test_omzetten_small(httpserver, ifc_small, tmp_path, data_dir):
    seen = []
    out, got = run_omzetten(httpserver, ifc_small, [*BASE, "model.frag"], progress=seen.append)
    assert [d.naam for d in out.delen] == ["model.frag"]
    assert out.delen[0].bytes == len(got["model.frag"]) > 0
    assert out.omzetter == CONVERTER_VERSION and out.duur_s > 0 and out.piek_geheugen > 0

    index = json.loads(got["index.json"])
    assert index["omzetter"] == CONVERTER_VERSION
    assert index["delen"] == [d.model_dump() for d in out.delen]
    summary = build_summary(ifc_small)
    for key in ("schema", "lengte_eenheid", "georeferentie", "begrenzing", "aantallen_per_klasse"):
        assert index[key] == summary[key]
    assert index["aantallen_per_verdieping"] == summary["aantallen_per_verdieping"]
    assert sorted(out.delen[0].verdiepingen) == sorted(summary["aantallen_per_verdieping"])

    assert json.loads(got["ruimtelijk.json"])["klasse"] == "IfcProject"
    wall = first_wall_globalid(ifc_small)
    props = read_properties(properties_db(got, tmp_path), [wall])[wall]
    assert props["psets"]["Pset_WallCommon"]["FireRating"] == "60"

    assert list(got)[-1] == "index.json"  # the summary goes last: it marks the output as complete
    assert seen == sorted(seen) and seen[-1] == 1.0
    assert not any((data_dir / "werk").iterdir())


def test_omzetten_splits(monkeypatch, httpserver, ifc_small, tmp_path, data_dir):
    monkeypatch.setenv("OPENBIM_SPLITS_VANAF_BYTES", "1")
    monkeypatch.setenv("OPENBIM_DEEL_BYTES", str(ifc_small.stat().st_size // 2 + 1))
    out, got = run_omzetten(httpserver, ifc_small, [*BASE, "deel-1.frag", "deel-2.frag"])
    assert [d.naam for d in out.delen] == ["deel-1.frag", "deel-2.frag"]
    assert all(len(got[d.naam]) == d.bytes > 0 for d in out.delen)
    assert all(d.verdiepingen for d in out.delen)

    # Every part carries the shared spatial structure; it must still be counted once.
    index = json.loads(got["index.json"])
    summary = build_summary(ifc_small)
    assert index["aantallen_per_klasse"] == summary["aantallen_per_klasse"]
    assert index["aantallen_per_verdieping"] == summary["aantallen_per_verdieping"]
    assert index["begrenzing"] == summary["begrenzing"]

    walls = wall_globalids(ifc_small)
    assert set(read_properties(properties_db(got, tmp_path), walls)) == set(walls)
    assert set(walls) <= set(globalids(json.loads(got["ruimtelijk.json"])))
    assert not any((data_dir / "werk").iterdir())


def test_missing_target_before_fetch(httpserver, ifc_small):
    names = ["index.json", "eigenschappen.sqlite", "model.frag"]
    e = pytest.raises(KernError, run_omzetten, httpserver, ifc_small, names).value
    assert e.error_code == "doel_ontbreekt" and "ruimtelijk.json" in e.melding
    assert not httpserver.log  # nothing fetched, nothing delivered


def test_missing_target_after_fetch_without_size(httpserver, ifc_small):
    e = pytest.raises(KernError, run_omzetten, httpserver, ifc_small, BASE, grootte=False).value
    assert e.error_code == "doel_ontbreekt" and "model.frag" in e.melding
    assert not [r for r, _ in httpserver.log if r.method == "PUT"]


def test_split_needs_part_targets(monkeypatch, httpserver, ifc_small):
    monkeypatch.setenv("OPENBIM_SPLITS_VANAF_BYTES", "1")
    e = pytest.raises(KernError, run_omzetten, httpserver, ifc_small, [*BASE, "model.frag"]).value
    assert e.error_code == "doel_ontbreekt" and "deel-1.frag" in e.melding


def test_too_many_parts(monkeypatch, httpserver, ifc_small):
    monkeypatch.setenv("OPENBIM_SPLITS_VANAF_BYTES", "1")
    monkeypatch.setenv("OPENBIM_DEEL_BYTES", str(ifc_small.stat().st_size // 2 + 1))
    e = pytest.raises(KernError, run_omzetten, httpserver, ifc_small, [*BASE, "deel-1.frag"]).value
    assert e.error_code == "te_veel_delen"
    assert not httpserver.log


def test_truncated_source_delivers_nothing(httpserver, ifc_truncated, data_dir):
    e = pytest.raises(KernError, run_omzetten, httpserver, ifc_truncated, [*BASE, "model.frag"]).value
    assert e.error_code == "omzetten_mislukt"
    assert not [r for r, _ in httpserver.log if r.method == "PUT"]
    assert not any((data_dir / "werk").iterdir())


@pytest.mark.parametrize("name", ["../model.frag", "model.ifc", "deel-0.frag", "index.json/x"])
def test_unknown_target_name_refused(name):
    with pytest.raises(ValidationError):
        OmzetVerzoek(bron={"url": "http://127.0.0.1:1/b.ifc"}, doelen={name: "http://127.0.0.1:1/x"})


def test_target_must_be_http():
    with pytest.raises(ValidationError):
        OmzetVerzoek(bron={"url": "http://127.0.0.1:1/b.ifc"}, doelen={"model.frag": "file:///tmp/x"})


def test_registered_as_long_tool(client, auth):
    spec = REGISTRY["omzetten"]
    assert spec.lang is True and spec.rij == "omzetten"
    (entry,) = [t for t in client.get("/v1/tools", headers=auth).json() if t["naam"] == "omzetten"]
    assert set(entry["invoer_schema"]["properties"]) == {"bron", "doelen"}
