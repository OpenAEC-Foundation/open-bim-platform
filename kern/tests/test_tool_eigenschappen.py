import hashlib

import pytest
from test_index import first_wall_globalid

from openbim_kern.index.properties import build_property_index


@pytest.fixture
def index_db(ifc_small, tmp_path):
    db = tmp_path / "idx" / "e.sqlite"
    db.parent.mkdir()
    build_property_index(ifc_small, db)
    return db


@pytest.fixture(autouse=True)
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENBIM_KERN_DATA", str(tmp_path / "data"))
    return tmp_path / "data"


def test_tool_eigenschappen_http(client, auth, httpserver, index_db, ifc_small):
    data = index_db.read_bytes()
    httpserver.expect_request("/e.sqlite").respond_with_data(data)
    wall = first_wall_globalid(ifc_small)
    sha = hashlib.sha256(data).hexdigest()
    body = {"index": {"url": httpserver.url_for("/e.sqlite"), "sha256": sha}, "globalids": [wall, "onbekend"]}
    r = client.post("/v1/tools/eigenschappen", json=body, headers=auth)
    assert r.status_code == 200, r.text
    el = r.json()["elementen"]
    assert set(el) == {wall}
    assert el[wall]["psets"]["Pset_WallCommon"]["FireRating"] == "60"


def test_tool_caches_on_sha256(client, auth, httpserver, index_db, ifc_small, data_dir):
    data = index_db.read_bytes()
    httpserver.expect_request("/e.sqlite").respond_with_data(data)
    wall = first_wall_globalid(ifc_small)
    sha = hashlib.sha256(data).hexdigest()
    body = {"index": {"url": httpserver.url_for("/e.sqlite"), "sha256": sha}, "globalids": [wall]}
    assert client.post("/v1/tools/eigenschappen", json=body, headers=auth).status_code == 200
    assert (data_dir / "cache" / "index" / f"{sha}.sqlite").is_file()
    httpserver.clear()  # a second call must be served from the cache
    assert client.post("/v1/tools/eigenschappen", json=body, headers=auth).status_code == 200


def test_tool_without_sha256_does_not_cache(client, auth, httpserver, index_db, ifc_small, data_dir):
    (data_dir / "cache" / "index").mkdir(parents=True)
    httpserver.expect_request("/e.sqlite").respond_with_data(index_db.read_bytes())
    wall = first_wall_globalid(ifc_small)
    body = {"index": {"url": httpserver.url_for("/e.sqlite")}, "globalids": [wall]}
    assert client.post("/v1/tools/eigenschappen", json=body, headers=auth).status_code == 200
    assert not list((data_dir / "cache" / "index").glob("*.sqlite"))


@pytest.mark.parametrize("ids", [[], ["x"] * 1001])
def test_globalids_length_enforced(client, auth, ids):
    body = {"index": {"url": "http://127.0.0.1:1/e.sqlite"}, "globalids": ids}
    r = client.post("/v1/tools/eigenschappen", json=body, headers=auth)
    assert r.status_code == 422 and r.json()["error_code"] == "ongeldige_invoer"
