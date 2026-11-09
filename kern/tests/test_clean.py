"""Lossless cleaning (converter/clean.mjs): duplicates become one record, orphans go, the model stays the same."""

import hashlib
import importlib.util
import json
import re
import sqlite3
from contextlib import closing
from pathlib import Path

import ifcopenshell
import ifcopenshell.geom
import numpy as np
import pytest

from openbim_kern.compare import model_differences
from openbim_kern.converter import CONVERT_SCRIPT, clean_ifc
from openbim_kern.errors import KernError
from openbim_kern.index.properties import build_property_index
from openbim_kern.tools import omzetten

DUPLICATES = Path(__file__).with_name("dubbel.ifc")
SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
_RECORD = re.compile(r"^#(\d+)=", re.M)
_REF = re.compile(r"#(\d+)")


@pytest.fixture(scope="module")
def cleaned(tmp_path_factory):
    out = tmp_path_factory.mktemp("opgeschoond") / "dubbel.ifc"
    stats = clean_ifc(DUPLICATES, out)
    return stats, ifcopenshell.open(str(out)), out


def ids(path: Path) -> set[int]:
    return {int(m) for m in _RECORD.findall(path.read_text(encoding="latin-1"))}


def references(path: Path) -> set[int]:
    """Every id referred to outside strings."""
    found = set()
    for line in path.read_text(encoding="latin-1").split(";\n"):
        outside = line.split("'")[0::2]
        for part in outside:
            found.update(int(m) for m in _REF.findall(part))
    return found


def points(model, coordinates):
    return [p.id() for p in model.by_type("IfcCartesianPoint") if p.Coordinates == coordinates]


def test_duplicate_points_and_values_become_one(cleaned):
    stats, model, _ = cleaned
    assert points(model, (0.0, 0.0, 0.0)) == [6, 163]  # #163 sits in a loop next to #6, see below
    assert [d.id() for d in model.by_type("IfcDirection") if d.DirectionRatios == (0.0, 0.0, 1.0)] == [7]
    assert [p.id() for p in model.by_type("IfcRectangleProfileDef")] == [105]
    # Wall B had its own copy of the body of wall A; the copy merged, with everything it referred to.
    assert model.by_id(208).Items[0].id() == 106
    # The value IsExternal of both property sets is one record; so are the material and the classification.
    assert {p.id() for p in model.by_id(502).HasProperties} & {p.id() for p in model.by_id(507).HasProperties} == {500}
    assert [m.id() for m in model.by_type("IfcMaterial")] == [600]
    assert [r.id() for r in model.by_type("IfcClassificationReference")] == [701]
    # The red style of wall E was a copy of that of wall C.
    assert model.by_id(463).Styles[0].id() == 312
    assert stats.merged == 20 and stats.records_in == 123 and stats.records_out == 99


def test_references_follow_the_merge(cleaned):
    _, _, out = cleaned
    assert references(out) <= ids(out)
    assert not ids(out) & {101, 102, 202, 205, 206, 504, 603, 703}


def test_the_model_is_the_same(cleaned):
    _, _, out = cleaned
    assert model_differences(DUPLICATES, out) == []


@pytest.mark.parametrize("fixture", ["ifc_small", "ifc_2x3", "ifc_georef"])
def test_generated_models_stay_the_same(fixture, request, tmp_path):
    source = request.getfixturevalue(fixture)
    stats = clean_ifc(source, tmp_path / "schoon.ifc")
    assert stats.merged > 0 and stats.out_bytes < stats.in_bytes
    assert model_differences(source, tmp_path / "schoon.ifc") == []


def _rows(db: Path) -> dict[str, set[tuple]]:
    with closing(sqlite3.connect(db)) as con:
        tables = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type = 'table'")]
        return {t: set(con.execute(f"SELECT * FROM {t}")) for t in tables}


@pytest.mark.parametrize("fixture", ["ifc_small", "ifc_2x3"])
def test_property_index_is_the_same(fixture, request, tmp_path):
    """The elements, property sets, materials, classifications and types of the kern's own index."""
    source = request.getfixturevalue(fixture)
    clean_ifc(source, tmp_path / "schoon.ifc")
    build_property_index(source, tmp_path / "bron.sqlite")
    build_property_index(tmp_path / "schoon.ifc", tmp_path / "schoon.sqlite")
    before, after = _rows(tmp_path / "bron.sqlite"), _rows(tmp_path / "schoon.sqlite")
    assert before == after and before["properties"] and before["materials"]


def test_property_index_of_the_duplicates_is_the_same(cleaned, tmp_path):
    _, _, out = cleaned
    build_property_index(DUPLICATES, tmp_path / "bron.sqlite")
    build_property_index(out, tmp_path / "schoon.sqlite")
    assert _rows(tmp_path / "bron.sqlite") == _rows(tmp_path / "schoon.sqlite")


def _shapes(path: Path) -> dict[str, tuple]:
    """Per element the triangulated geometry in world coordinates: sorted vertices and the number of faces."""
    settings = ifcopenshell.geom.settings()
    settings.set("use-world-coords", True)
    model = ifcopenshell.open(str(path))
    found = {}
    for element in model.by_type("IfcProduct"):
        if element.Representation is None:
            continue
        try:
            shape = ifcopenshell.geom.create_shape(settings, element)
        except RuntimeError:
            continue
        verts = np.round(np.array(shape.geometry.verts).reshape(-1, 3), 6)
        found[element.GlobalId] = (tuple(map(tuple, np.unique(verts, axis=0))), len(shape.geometry.faces) // 3)
    return found


@pytest.mark.parametrize("fixture", ["ifc_small", "dubbel"])
def test_geometry_is_the_same(fixture, request, tmp_path):
    source = DUPLICATES if fixture == "dubbel" else request.getfixturevalue(fixture)
    clean_ifc(source, tmp_path / "schoon.ifc")
    before = _shapes(source)
    assert len(before) >= 5
    assert _shapes(tmp_path / "schoon.ifc") == before


def test_styled_geometry_keeps_its_identity(cleaned):
    """Walls C and D have the same body as wall A, but red and blue: merged, all three would get both colours."""
    _, model, _ = cleaned
    bodies = {w.Name[5]: w.Representation.Representations[0].Items[0] for w in model.by_type("IfcWall")}
    assert len({bodies["A"].id(), bodies["C"].id(), bodies["D"].id()}) == 3
    colours = {
        k: [s.Styles[0].Name for s in model.get_inverse(body) if s.is_a("IfcStyledItem")] for k, body in bodies.items()
    }
    assert colours["A"] == colours["B"] == [] and colours["C"] == ["rood"] and colours["D"] == ["blauw"]


def test_a_set_never_gets_a_record_twice(cleaned):
    """The points of an IfcPolyLoop are a LIST OF UNIQUE and properties a SET: identical members stay distinct."""
    _, model, _ = cleaned
    loop = [p.id() for p in model.by_type("IfcPolyLoop")[0].Polygon]
    assert len(set(loop)) == 4 and loop[0] == 6
    assert len({p.id() for p in model.by_id(507).HasProperties}) == 3


def test_a_layer_keeps_its_one_layer_set(cleaned):
    """A material layer belongs to exactly one layer set (inverse ToMaterialLayerSet)."""
    _, model, _ = cleaned
    layers = model.by_type("IfcMaterialLayer")
    assert [layer.id() for layer in layers] == [601, 604]
    assert {layer.Material.id() for layer in layers} == {600}


def test_orphans_go_and_what_stands_alone_stays(cleaned):
    stats, model, out = cleaned
    assert stats.orphans == 4 and not ids(out) & {900, 901, 902, 903}
    assert model.by_id(904).is_a("IfcPerson")  # an actor nothing refers to is not removed
    assert stats.report["orphans_by_type"] == {"IFCCARTESIANPOINT": 2, "IFCPOLYLINE": 1, "IFCPROPERTYSINGLEVALUE": 1}


def test_the_source_is_not_touched(tmp_path):
    source = tmp_path / "bron.ifc"
    source.write_bytes(DUPLICATES.read_bytes())
    before = hashlib.sha256(source.read_bytes()).hexdigest()
    clean_ifc(source, tmp_path / "schoon.ifc")
    assert hashlib.sha256(source.read_bytes()).hexdigest() == before


def test_text_is_kept_byte_for_byte(tmp_path):
    """Strings with ; # '' and comment marks, line breaks in records, CRLF, bytes outside ASCII, dangling ids."""
    data = (
        b"ISO-10303-21;\r\nHEADER;\r\nFILE_DESCRIPTION(('DATA; in een string'),'2;1');\r\n"
        b"FILE_NAME('x','',(''),(''),'','','');\r\nFILE_SCHEMA(('IFC4'));\r\nENDSEC;\r\nDATA;\r\n"
        b"#1=IFCPROJECT('2NGoKFc8vEBg4PCnAn4Tym',$,'Caf\xe9; #2 ''x'' /* y */',$,$,$,$,(#3),#4);\r\n"
        b"#2=IFCCARTESIANPOINT((0.,0.,0.));\r\n"
        b"#5=IFCCARTESIANPOINT(\r\n  (0.,0.,0.));\r\n"
        b"/* tussen records; #2 */\r\n"
        b"#6=IFCAXIS2PLACEMENT3D(#5,$,$);\r\n"
        b"#3=IFCGEOMETRICREPRESENTATIONCONTEXT($,'Model',3,1.E-05,#6,$);\r\n"
        b"#7=IFCAXIS2PLACEMENT3D(#2,$,#999);\r\n"
        b"#8=IFCLOCALPLACEMENT($,#7);\r\n"
        b"#9=IFCSITE('0kF0pBnNj5ZBY3Zt$6cF9C',$,'T',$,$,#8,$,$,$,$,$,$,$,$);\r\n"
        b"ENDSEC;\r\nEND-ISO-10303-21;\r\n"
    )
    source = tmp_path / "randgevallen.ifc"
    source.write_bytes(data)
    stats = clean_ifc(source, tmp_path / "schoon.ifc")
    out = (tmp_path / "schoon.ifc").read_bytes()
    assert out.startswith(data[: data.index(b"DATA;\r\n") + 5])
    assert b"'Caf\xe9; #2 ''x'' /* y */'" in out  # the string as it was: #2 in it is no reference
    assert b"#5=" not in out and b"#6=IFCAXIS2PLACEMENT3D(#2,$,$);" in out  # #5 merged into #2, over two lines
    assert b"#7=IFCAXIS2PLACEMENT3D(#2,$,#999);" in out  # a dangling id stays as it was, and is not merged
    assert out.endswith(b"ENDSEC;\r\nEND-ISO-10303-21;\r\n")
    assert stats.merged == 1


def test_records_larger_than_a_read_chunk(tmp_path):
    """A record of more than the 4 MB the converter reads at a time, and records cut by the chunk boundaries."""
    model = ifcopenshell.file(schema="IFC4")
    coords = [(float(i), float(i % 7), 0.5) for i in range(300_000)]
    big = model.create_entity("IfcCartesianPointList3D", CoordList=coords)
    model.create_entity("IfcStyledItem", Item=model.create_entity("IfcPolygonalFaceSet", Coordinates=big, Faces=[]))
    for i in range(60_000):
        model.create_entity("IfcStyledItem", Name=f"s{i}", Item=model.create_entity("IfcCartesianPoint", (1.0, 2.0)))
    model.write(str(tmp_path / "groot.ifc"))
    assert max(len(line) for line in (tmp_path / "groot.ifc").read_bytes().splitlines()) > 4 * 1024 * 1024
    stats = clean_ifc(tmp_path / "groot.ifc", tmp_path / "schoon.ifc")
    after = ifcopenshell.open(str(tmp_path / "schoon.ifc"))
    assert after.by_type("IfcCartesianPointList3D")[0].CoordList == tuple(coords)
    assert len(after.by_type("IfcStyledItem")) == 60_001 and stats.records_out == stats.records_in


def test_index_bytes_per_record(enlarged):
    """The index costs a few dozen bytes per record (the splitter of fragments kept ~320 B per line)."""
    stats = clean_ifc(enlarged, enlarged.with_name("schoon.ifc"))
    per_record = stats.report["index_bytes"] / stats.records_in
    assert 30 < per_record < 70
    assert stats.report["index_bytes"] < 1.5 * enlarged.stat().st_size


def test_peak_memory(enlarged, tmp_path):
    """Peak memory of the cleaner above that for a tiny file: about the size of the file, not several times it."""
    base = clean_ifc(DUPLICATES, tmp_path / "klein.ifc").peak_rss
    peak = clean_ifc(enlarged, tmp_path / "groot.ifc").peak_rss
    size = enlarged.stat().st_size
    assert peak - base < 2 * size, (peak, base, size)


def test_a_failed_cleaning_converts_the_source(monkeypatch, ifc_small, tmp_path):
    def fail(ifc, out):
        raise KernError("omzetten_mislukt", "kapot", "", status=422)

    monkeypatch.setattr(omzetten, "clean_ifc", fail)
    converted = omzetten.convert_model(ifc_small, tmp_path)
    assert converted.cleaning == {"overgeslagen": "kapot"}
    assert (tmp_path / "uit" / "model.frag").stat().st_size > 0


def test_conversion_starts_with_cleaning(ifc_small, tmp_path):
    converted = omzetten.convert_model(ifc_small, tmp_path)
    assert converted.cleaning["regels_na"] < converted.cleaning["regels_voor"]
    assert converted.cleaning["per_klasse_samengevoegd"]["IFCDIRECTION"] > 0
    assert converted.seconds["opschonen"] > 0 and converted.peaks["opschonen"] > 0
    assert (tmp_path / "opgeschoond.ifc").is_file()


def test_the_cli_reports_as_json(tmp_path):
    import subprocess

    run = subprocess.run(
        ["node", str(CONVERT_SCRIPT), "clean", str(DUPLICATES), str(tmp_path / "x.ifc")], capture_output=True, text=True
    )
    assert run.returncode == 0, run.stderr
    report = json.loads(run.stdout)
    assert report["records_in"] == 123 and report["out_bytes"] == (tmp_path / "x.ifc").stat().st_size


def test_the_comparison_knows_what_cleaning_may_remove():
    from openbim_kern import compare

    script = CONVERT_SCRIPT.with_name("stepindex.mjs").read_text(encoding="utf-8")
    listed = script[script.index("const REMOVABLE = [") : script.index("];", script.index("const REMOVABLE = ["))]
    assert re.findall(r'"(IFC[A-Z0-9]+)"', listed) == [t.upper() for t in compare.REMOVABLE]


def test_the_schema_table_is_current(tmp_path):
    """converter/schema.json comes from scripts/step_schema.py and the IFC schemas of IfcOpenShell."""
    spec = importlib.util.spec_from_file_location("step_schema", SCRIPTS / "step_schema.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.render(module.table()) == module.TABLE.read_text(encoding="utf-8")
    owner = module.table()["schemas"]["IFC4"]["single_owner"]
    assert owner["IFCSTYLEDITEM"] == [0] and owner["IFCMATERIALLAYERSET"] == [0]
