import hashlib
import json

import ifcopenshell
import models
import pytest

from openbim_kern.clash import ClashCheck, ClashModel, find_clashes, run_checks
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


def test_the_order_of_the_sets_does_not_matter(ifc_small, tmp_path):
    import shutil

    walls, duct = tmp_path / "walls.ifc", tmp_path / "duct.ifc"
    shutil.copy(ifc_small, walls)
    shutil.copy(ifc_small, duct)
    a = [ClashModel(sleutel="constructie", versie="1", pad=walls, klassen=["IfcWall"])]
    b = [ClashModel(sleutel="installaties", versie="1", pad=duct, klassen=["IfcDuctSegment"])]
    for set_a, set_b in ((a, b), (b, a)):
        found = find_clashes(set_a, set_b, "hard", 0.0)
        assert found and all(c.a.sleutel == set_a[0].sleutel and c.b.sleutel == set_b[0].sleutel for c in found)


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
        "controles": [
            {
                "regel": "kanalen x wanden",
                "set_a": [{"sleutel": "b1", "versie": "1", "bron": bron, "klassen": ["IfcDuctSegment"]}],
                "set_b": [{"sleutel": "b1", "versie": "1", "bron": bron, "klassen": ["IfcWall"]}],
                "soort": "hard",
            }
        ],
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
    assert resultaten[0]["regel"] == "kanalen x wanden" and resultaten[0]["soort"] == "hard"


def test_tolerance_is_limited():
    from pydantic import ValidationError

    from openbim_kern.tools.botsingen import BotsingIn

    with pytest.raises(ValidationError):
        BotsingIn(
            controles=[{"set_a": [], "set_b": [], "soort": "hard", "tolerantie": 1.5}], doel="http://127.0.0.1:1/x"
        )


def test_the_number_of_checks_is_limited():
    from pydantic import ValidationError

    from openbim_kern.tools.botsingen import BotsingIn

    check = {"set_a": [], "set_b": [], "soort": "hard"}
    for controles in ([], [check] * 31):
        with pytest.raises(ValidationError):
            BotsingIn(controles=controles, doel="http://127.0.0.1:1/x")


def test_two_checks_read_the_file_once_and_report_a_pair_once(ifc_small, monkeypatch):
    opens = []
    real = ifcopenshell.open
    monkeypatch.setattr(ifcopenshell, "open", lambda p: opens.append(p) or real(p))
    check = ClashCheck(
        set_a=[model(ifc_small, ["IfcDuctSegment"])], set_b=[model(ifc_small, ["IfcWall"])], soort="hard"
    )
    found = run_checks([check.model_copy(update={"regel": "een"}), check.model_copy(update={"regel": "twee"})])
    assert len(opens) == 1
    assert len({frozenset((c.a.globalid, c.b.globalid)) for c in found}) == len(found) > 0
    assert {c.regel for c in found} == {"een"}


def test_hard_wins_from_distance_for_the_same_pair(ifc_small):
    a, b = [model(ifc_small, ["IfcDuctSegment"])], [model(ifc_small, ["IfcWall"])]
    found = run_checks(
        [
            ClashCheck(regel="ver", set_a=a, set_b=b, soort="afstand", tolerantie=0.05),
            ClashCheck(regel="door", set_a=a, set_b=b, soort="hard"),
        ]
    )
    hit = next(c for c in found if c.b.globalid in gids(ifc_small, "IfcWall"))
    assert hit.soort == "hard" and hit.regel == "door"


def test_only_between_models_skips_pairs_in_one_model(ifc_small, tmp_path):
    same = ClashCheck(set_a=[model(ifc_small)], set_b=[model(ifc_small)], soort="hard", alleen_tussen_modellen=True)
    assert run_checks([same]) == []
    # Two builds of the same model have their own GlobalIds and do clash with each other.
    other = models.ifc_small(tmp_path / "ander.ifc")
    two = same.model_copy(update={"set_b": [model(other)]})
    found = run_checks([two])
    assert found and all(c.a.sleutel != c.b.sleutel for c in found)


def test_the_same_global_ids_in_two_files_give_no_pair_with_itself(ifc_small, tmp_path):
    copy = tmp_path / "kopie.ifc"
    copy.write_bytes(ifc_small.read_bytes())
    found = run_checks([ClashCheck(set_a=[model(ifc_small)], set_b=[model(copy)], soort="hard")])
    assert all(c.a.globalid != c.b.globalid for c in found)


def test_duplicate_needs_the_same_class_and_box(tmp_path):
    path = models.ifc_clash_context(tmp_path / "context.ifc")
    found = run_checks([ClashCheck(set_a=[model(path)], set_b=[model(path)], soort="dubbel")])
    assert [c.soort for c in found] == ["dubbel"]
    assert {found[0].a.klasse, found[0].b.klasse} == {"IfcWall"}


def test_elements_carry_name_and_storey(ifc_small):
    check = ClashCheck(
        set_a=[model(ifc_small, ["IfcDuctSegment"])], set_b=[model(ifc_small, ["IfcWall"])], soort="hard"
    )
    found = run_checks([check])
    assert found[0].a.naam == "Kanaal" and found[0].a.verdieping == "00 begane grond"


def test_virtual_elements_do_not_clash(tmp_path):
    path = models.ifc_clash_context(tmp_path / "context.ifc")
    found = run_checks([ClashCheck(set_a=[model(path)], set_b=[model(path)], soort="hard")])
    assert found and not any("IfcVirtualElement" in (c.a.klasse, c.b.klasse) for c in found)


def test_progress_runs_up_to_ninety_percent(ifc_small):
    seen = []
    check = ClashCheck(set_a=[model(ifc_small)], set_b=[model(ifc_small)], soort="hard")
    run_checks([check, check], progress=seen.append)
    assert seen == sorted(seen) and seen[-1] == pytest.approx(0.9)
    assert seen.index(pytest.approx(0.5)) < seen.index(
        pytest.approx(0.7)
    )  # loading ends at 50%, then one step per check
