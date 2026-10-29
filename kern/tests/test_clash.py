import hashlib
import json

import ifcopenshell
import pytest

from openbim_kern.clash import ClashModel, find_clashes
from openbim_kern.jobs.worker import queues_from_env, run_worker
from openbim_kern.tools.registry import REGISTRY


@pytest.fixture(autouse=True)
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENBIM_KERN_DATA", str(tmp_path / "data"))


def model(path, klassen=None):
    return ClashModel(sleutel=path.name, versie="1", pad=path, klassen=klassen)


def gids(path, ifc_class):
    return {e.GlobalId for e in ifcopenshell.open(str(path)).by_type(ifc_class)}


def test_duct_through_wall_is_a_hard_clash(ifc_small):
    found = find_clashes([model(ifc_small, ["IfcDuctSegment"])], [model(ifc_small, ["IfcWall"])], "hard", 0.0)
    (duct,) = gids(ifc_small, "IfcDuctSegment")
    assert any(c.a.globalid == duct and c.b.globalid in gids(ifc_small, "IfcWall") for c in found)
    assert all(c.a.sleutel == ifc_small.name and c.a.versie == "1" for c in found)
    hit = next(c for c in found if c.a.globalid == duct)
    assert hit.afstand == pytest.approx(0.2, abs=0.01)


def test_each_element_carries_its_ifc_class(ifc_small):
    found = find_clashes([model(ifc_small, ["IfcDuctSegment"])], [model(ifc_small, ["IfcWall"])], "hard", 0.0)
    assert {(c.a.klasse, c.b.klasse) for c in found} == {("IfcDuctSegment", "IfcWall")}


def test_tolerance_ignores_shallow_penetrations(ifc_small):
    assert find_clashes([model(ifc_small, ["IfcDuctSegment"])], [model(ifc_small, ["IfcWall"])], "hard", 1.0) == []


def test_clearance_finds_elements_closer_than_the_distance(ifc_small):
    found = find_clashes([model(ifc_small, ["IfcWall"])], [model(ifc_small, ["IfcWall"])], "afstand", 0.05)
    assert found and all(c.afstand <= 0.05 for c in found)


def test_an_element_never_clashes_with_itself_and_pairs_are_counted_once(ifc_small):
    found = find_clashes([model(ifc_small)], [model(ifc_small)], "afstand", 0.05)
    assert all(c.a.globalid != c.b.globalid for c in found)
    pairs = [frozenset((c.a.globalid, c.b.globalid)) for c in found]
    assert len(pairs) == len(set(pairs))


def test_botsing_queue_from_env(monkeypatch):
    monkeypatch.setenv("OPENBIM_RIJ_BOTSING", "2")
    assert queues_from_env()["botsing"] == 2
    monkeypatch.delenv("OPENBIM_RIJ_BOTSING")
    assert queues_from_env()["botsing"] == 1


def test_botsingen_tool_delivers_json(client, auth, store, httpserver, ifc_small):
    assert REGISTRY["botsingen"].lang is True and REGISTRY["botsingen"].rij == "botsing"
    data = ifc_small.read_bytes()
    httpserver.expect_request("/m.ifc").respond_with_data(data)
    geleverd = {}
    httpserver.expect_request("/uit.json", method="PUT").respond_with_handler(
        lambda request: geleverd.setdefault("json", request.data) and "" or ""
    )
    bron = {"url": httpserver.url_for("/m.ifc"), "sha256": hashlib.sha256(data).hexdigest()}
    body = {
        "set_a": [{"sleutel": "b1", "versie": "1", "bron": bron, "klassen": ["IfcDuctSegment"]}],
        "set_b": [{"sleutel": "b1", "versie": "1", "bron": bron, "klassen": ["IfcWall"]}],
        "soort": "hard",
        "tolerantie": 0.0,
        "doel": httpserver.url_for("/uit.json"),
    }
    r = client.post("/v1/tools/botsingen", headers=auth, json=body)
    assert r.status_code == 202, r.text
    run_worker(store, {"botsing": 1}, once=True)
    job = client.get(f"/v1/taken/{r.json()['taak']}", headers=auth).json()
    assert job["status"] == "klaar", job
    resultaten = json.loads(geleverd["json"])
    assert job["uitkomst"]["aantal"] == len(resultaten) == 1
    assert resultaten[0]["a"]["sleutel"] == "b1" and len(resultaten[0]["punt"]) == 3


def test_tolerance_is_limited():
    from pydantic import ValidationError

    from openbim_kern.tools.botsingen import BotsingIn

    with pytest.raises(ValidationError):
        BotsingIn(set_a=[], set_b=[], soort="hard", tolerantie=1.5, doel="http://127.0.0.1:1/x")
