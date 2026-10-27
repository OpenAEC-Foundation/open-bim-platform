import hashlib
import importlib.util
import json
from collections import Counter
from pathlib import Path

import ifcopenshell
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

    # The output lands where the local server looks, so the viewer can open the folder without converting again.
    for source in sources:
        versie = hashlib.sha256(source.read_bytes()).hexdigest()[:12]
        derived = folder / ".afgeleid" / source.relative_to(folder).as_posix() / versie / CONVERTER_VERSION
        assert (derived / "index.json").is_file() and (derived / "model.frag").is_file()
