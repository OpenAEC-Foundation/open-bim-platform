import hashlib
import importlib.util
import json
from collections import Counter
from pathlib import Path

import ifcopenshell
import numpy as np
import pytest

from openbim_kern import CONVERTER_VERSION
from openbim_kern.converter import convert_to_frag
from openbim_kern.index.properties import build_property_index, count_elements
from openbim_kern.index.spatial import build_summary

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


def load(name):
    spec = importlib.util.spec_from_file_location(f"scripts_{name}", SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def enlarge():
    return load("enlarge").enlarge


def test_enlarge_valid(enlarge, ifc_small, tmp_path):
    enlarge(ifc_small, 3, tmp_path / "g.ifc")
    m = ifcopenshell.open(str(tmp_path / "g.ifc"))
    assert len(m.by_type("IfcProject")) == 1 and len(m.by_type("IfcWall")) == 18
    assert len({e.GlobalId for e in m.by_type("IfcRoot")}) == len(m.by_type("IfcRoot"))


def test_enlarge_shares_the_spatial_structure(enlarge, ifc_small, tmp_path):
    enlarge(ifc_small, 3, tmp_path / "g.ifc")
    big, small = build_summary(tmp_path / "g.ifc"), build_summary(ifc_small)
    assert big["aantallen_per_klasse"]["IfcBuildingStorey"] == 2 and big["aantallen_per_klasse"]["IfcSite"] == 1
    assert big["aantallen_per_verdieping"] == {k: 3 * v for k, v in small["aantallen_per_verdieping"].items()}
    contexts = Counter(
        c.ContextIdentifier
        for c in ifcopenshell.open(str(tmp_path / "g.ifc")).by_type("IfcGeometricRepresentationSubContext")
    )
    assert set(contexts.values()) == {1}  # contexts are shared, not copied


def test_enlarged_file_converts_and_indexes(enlarge, ifc_small, tmp_path):
    enlarge(ifc_small, 4, tmp_path / "g.ifc")
    assert convert_to_frag(tmp_path / "g.ifc", tmp_path / "g.frag").out_bytes > 0
    build_property_index(tmp_path / "g.ifc", tmp_path / "e.sqlite")
    assert count_elements(tmp_path / "e.sqlite")["aantallen_per_klasse"]["IfcWall"] == 24


def test_enlarge_ifc2x3(enlarge, ifc_2x3, tmp_path):
    enlarge(ifc_2x3, 2, tmp_path / "g.ifc")
    m = ifcopenshell.open(str(tmp_path / "g.ifc"))
    assert len(m.by_type("IfcWall")) == 12 and len(m.by_type("IfcProject")) == 1
    assert len({e.GlobalId for e in m.by_type("IfcRoot")}) == len(m.by_type("IfcRoot"))


def test_enlarge_factor_one_is_the_same_model(enlarge, ifc_small, tmp_path):
    enlarge(ifc_small, 1, tmp_path / "g.ifc")
    assert build_summary(tmp_path / "g.ifc")["aantallen_per_klasse"] == build_summary(ifc_small)["aantallen_per_klasse"]


def test_enlarge_cli(ifc_small, tmp_path):
    load("enlarge").main([str(ifc_small), "2", str(tmp_path / "g.ifc")])
    assert len(ifcopenshell.open(str(tmp_path / "g.ifc")).by_type("IfcWall")) == 12


def test_measure_report(tmp_path):
    import models

    folder = tmp_path / "Project"
    sources = models.project_folder(folder)
    report = tmp_path / "rapport.md"
    load("measure").main([str(folder), "--uit", str(report)])

    text = report.read_text(encoding="utf-8")
    assert "| bestand |" in text and "wand model.ifc" in text and "kanaal één.ifc" in text
    assert "Totaal" in text and "browser" in text.lower()
    rows = json.loads(report.with_suffix(".json").read_text(encoding="utf-8"))
    assert {r["bestand"] for r in rows} == {"Constructie/wand model.ifc", "Installaties/kanaal één.ifc"}
    assert all(r["frag_bytes"] > 0 and r["seconden"] > 0 and r["piek_index"] > 0 for r in rows)

    # A second run with --hervat takes the rows over instead of converting again.
    load("measure").main([str(folder), "--uit", str(report), "--hervat"])
    again = json.loads(report.with_suffix(".json").read_text(encoding="utf-8"))
    assert all(r.get("hervat") for r in again) and [r["seconden"] for r in again] == [r["seconden"] for r in rows]

    # The output lands where the local server looks, so the viewer can open the folder without converting again.
    for source in sources:
        versie = hashlib.sha256(source.read_bytes()).hexdigest()[:12]
        derived = folder / ".afgeleid" / source.relative_to(folder).as_posix() / versie / CONVERTER_VERSION
        assert (derived / "index.json").is_file() and (derived / "model.frag").is_file()


@pytest.fixture(scope="module")
def storage_study():
    return load("storage_study")


def test_storage_study_counts_the_graph_and_the_geometry(storage_study, ifc_small):
    result = storage_study.study(ifc_small)
    model = ifcopenshell.open(str(ifc_small))
    graph = result["graaf"]
    assert graph["knopen"] >= len(model.by_type("IfcObjectDefinition"))
    contained = sum(len(r.RelatedElements) for r in model.by_type("IfcRelContainedInSpatialStructure"))
    assert graph["relaties"] >= contained
    assert graph["sqlite_bytes"] > 0 and graph["graafopslag_bytes_ondergrens"] > 0
    assert result["step"]["entities"] == len(list(model))
    geometry = result["geometrie"]
    assert 0 < geometry["unieke_meshes"] <= geometry["elementen"]
    assert geometry["bytes_uniek"] <= geometry["bytes_per_element"]
    versions = result["versies"]
    assert versions["verplaatst"] >= 1 and versions["vervormd"] >= 1
    assert versions["zelfde_mesh"] > 0 and versions["andere_mesh"] >= versions["vervormd"]
    assert 0 < versions["bytes_nieuw_v2"] < versions["bytes_uniek_v2"]


def test_storage_study_compares_versions_by_globalid_and_mesh_hash(storage_study):
    mesh = storage_study.Mesh
    first = {
        "a": mesh("r1", "h1", 10, "IfcWall", "x1"),
        "b": mesh("r2", "h2", 20, "IfcWall", "x2"),
        "c": mesh("r3", "h1", 10, "IfcDoor", "x3"),
    }
    second = {
        "a": mesh("r1", "h1", 10, "IfcWall", "y1"),
        "b": mesh("r9", "h3", 30, "IfcWall", "y2"),
        "d": mesh("r4", "h1", 10, "IfcDoor", "y3"),
    }
    assert storage_study.compare(first, second) == {
        "elementen_v1": 3,
        "elementen_v2": 3,
        "zelfde_mesh": 1,
        "zelfde_mesh_ruwe_hash": 0,
        "andere_mesh": 1,
        "nieuw": 1,
        "weg": 1,
        "unieke_meshes_v2": 2,
        "nieuwe_meshes_v2": 1,
        "bytes_uniek_v2": 40,
        "bytes_nieuw_v2": 30,
        "per_klasse": {"IfcWall": {"zelfde": 1, "andere": 1}, "IfcDoor": {"nieuw": 1, "weg": 1}},
    }


def test_storage_study_hash_ignores_the_order_of_vertices_and_triangles(storage_study):
    verts = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1]], dtype=np.int64)
    faces = np.array([[0, 1, 2], [0, 1, 3]], dtype=np.int64)
    order = [3, 2, 1, 0]
    shuffled = verts[order]
    renumber = {old: new for new, old in enumerate(order)}
    shuffled_faces = np.array([[renumber[i] for i in f] for f in faces[::-1]], dtype=np.int64)
    digest = storage_study.canonical_digest
    assert digest(verts, faces) == digest(shuffled, shuffled_faces)
    assert digest(verts, faces) != digest(verts + 1, faces)


@pytest.fixture(scope="module")
def variant():
    return load("variant").variant


def test_variant_keeps_only_the_given_classes(variant, ifc_small, tmp_path):
    out = variant(ifc_small, tmp_path / "constructie.ifc", zonder=["IfcDuctSegment"])
    model = ifcopenshell.open(str(out))
    assert not model.by_type("IfcDuctSegment") and model.by_type("IfcWall")
    out = variant(ifc_small, tmp_path / "installaties.ifc", alleen=["IfcDuctSegment"])
    model = ifcopenshell.open(str(out))
    assert len(model.by_type("IfcDuctSegment")) == 1 and not model.by_type("IfcWall")
    assert model.by_type("IfcBuildingStorey")


def test_variant_replaces_part_of_the_globalids_and_the_link_finds_them_back(variant, ifc_small, tmp_path):
    from openbim_kern.linking import link_versions

    out = variant(ifc_small, tmp_path / "v2.ifc", nieuwe_globalids=0.5)
    old = {e.GlobalId for e in ifcopenshell.open(str(ifc_small)).by_type("IfcElement")}
    new = {e.GlobalId for e in ifcopenshell.open(str(out)).by_type("IfcElement")}
    assert len(old) == len(new) and 0 < len(old - new) < len(old)
    build_property_index(ifc_small, tmp_path / "v1.sqlite")
    build_property_index(out, tmp_path / "v2.sqlite")
    koppeling = link_versions(tmp_path / "v1.sqlite", tmp_path / "v2.sqlite")
    assert koppeling.terugval and koppeling.matchrate > 0.9


def test_variant_cli(ifc_small, tmp_path):
    import subprocess
    import sys

    out = tmp_path / "cli.ifc"
    subprocess.run(
        [sys.executable, str(SCRIPTS / "variant.py"), str(ifc_small), str(out), "--zonder", "IfcDuctSegment"],
        check=True,
    )
    assert not ifcopenshell.open(str(out)).by_type("IfcDuctSegment")
