import hashlib

import ifcopenshell
import ifcopenshell.api
import ifcopenshell.guid
import ifcopenshell.util.element
import ifcopenshell.util.placement
import pytest

from openbim_kern.index.properties import build_property_index
from openbim_kern.jobs.worker import run_worker
from openbim_kern.linking import Paar, link_versions
from openbim_kern.tools.registry import REGISTRY


@pytest.fixture(autouse=True)
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENBIM_KERN_DATA", str(tmp_path / "data"))


def index(model, tmp_path, name):
    model.write(str(tmp_path / f"{name}.ifc"))
    build_property_index(tmp_path / f"{name}.ifc", tmp_path / f"{name}.sqlite")
    return tmp_path / f"{name}.sqlite"


def move(model, element, dx):
    matrix = ifcopenshell.util.placement.get_local_placement(element.ObjectPlacement)
    matrix[0, 3] += dx
    ifcopenshell.api.run("geometry.edit_object_placement", model, product=element, matrix=matrix, is_si=True)


def walls(model):
    return sorted(model.by_type("IfcWall"), key=lambda w: w.Name)


def test_same_model_matches_on_globalid(ifc_small, tmp_path):
    model = ifcopenshell.open(str(ifc_small))
    k = link_versions(index(model, tmp_path, "a"), index(model, tmp_path, "b"))
    assert k.matchrate == 1.0 and k.op_globalid == k.elementen_vorige and k.terugval == []


def test_new_globalids_are_found_back_by_their_identity(ifc_small, tmp_path):
    v1 = ifcopenshell.open(str(ifc_small))
    old = {w.Name: w.GlobalId for w in walls(v1)}
    db_v1 = index(v1, tmp_path, "v1")
    for wall in walls(v1):
        wall.GlobalId = ifcopenshell.guid.new()
    k = link_versions(db_v1, index(v1, tmp_path, "v2"))
    assert {p.van for p in k.terugval} == set(old.values())
    assert k.matchrate == 1.0 and k.niet_gevonden == []


def test_a_moved_element_with_a_unique_name_is_found_back(ifc_small, tmp_path):
    v1 = ifcopenshell.open(str(ifc_small))
    db_v1 = index(v1, tmp_path, "v1")
    wall = walls(v1)[0]
    old = wall.GlobalId
    wall.GlobalId = ifcopenshell.guid.new()
    move(v1, wall, 0.5)
    k = link_versions(db_v1, index(v1, tmp_path, "v2"))
    assert Paar(van=old, naar=wall.GlobalId) in k.terugval


def test_identical_elements_at_the_same_place_are_not_guessed(ifc_small, tmp_path):
    v1 = ifcopenshell.open(str(ifc_small))
    a = walls(v1)[0]
    storey = ifcopenshell.util.element.get_container(a)
    b = next(w for w in walls(v1) if w != a and ifcopenshell.util.element.get_container(w) == storey)
    for wall in (a, b):
        wall.Name = "Kopie"
    b.ObjectPlacement = a.ObjectPlacement  # same place, same storey
    db_v1 = index(v1, tmp_path, "v1")
    a_old, b_old = a.GlobalId, b.GlobalId
    a.GlobalId, b.GlobalId = ifcopenshell.guid.new(), ifcopenshell.guid.new()
    k = link_versions(db_v1, index(v1, tmp_path, "v2"))
    assert {a_old, b_old} <= set(k.niet_gevonden)
    assert k.matchrate < 1.0


def test_a_removed_element_is_not_found(ifc_small, tmp_path):
    v1 = ifcopenshell.open(str(ifc_small))
    db_v1 = index(v1, tmp_path, "v1")
    removed = walls(v1)[-1]
    gid = removed.GlobalId
    ifcopenshell.api.run("root.remove_product", v1, product=removed)
    k = link_versions(db_v1, index(v1, tmp_path, "v2"))
    assert gid in k.niet_gevonden


def test_koppelen_is_a_long_tool(client, auth, store, httpserver, ifc_small, tmp_path):
    assert REGISTRY["koppelen"].lang is True and REGISTRY["koppelen"].rij == "licht"
    model = ifcopenshell.open(str(ifc_small))
    bronnen = {}
    for name in ("v1", "v2"):
        data = index(model, tmp_path, name).read_bytes()
        httpserver.expect_request(f"/{name}.sqlite").respond_with_data(data)
        bronnen[name] = {"url": httpserver.url_for(f"/{name}.sqlite"), "sha256": hashlib.sha256(data).hexdigest()}
    r = client.post("/v1/tools/koppelen", headers=auth, json={"vorige": bronnen["v1"], "nieuwe": bronnen["v2"]})
    assert r.status_code == 202, r.text
    run_worker(store, {"licht": 1}, once=True)
    job = client.get(f"/v1/taken/{r.json()['taak']}", headers=auth).json()
    assert job["status"] == "klaar", job
    assert job["uitkomst"]["matchrate"] == 1.0
