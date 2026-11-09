import hashlib

import pytest
from pydantic import ValidationError
from test_index import first_wall_globalid

from openbim_kern.index.properties import build_property_index
from openbim_kern.sources import Source


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


def test_sha256_path_traversal_rejected(client, auth):
    body = {"index": {"url": "http://127.0.0.1:1/e.sqlite", "sha256": "../../x"}, "globalids": ["a"]}
    r = client.post("/v1/tools/eigenschappen", json=body, headers=auth)
    assert r.status_code == 422 and r.json()["error_code"] == "ongeldige_invoer"
    with pytest.raises(ValidationError):
        Source(url="http://127.0.0.1:1/x", sha256="../../x")


def test_sha256_normalised_to_lowercase():
    assert Source(url="http://127.0.0.1:1/x", sha256="A" * 64).sha256 == "a" * 64


@pytest.mark.parametrize("with_sha", [True, False])
def test_non_sqlite_index_rejected_and_not_cached(client, auth, httpserver, data_dir, with_sha):
    data = b"this is not a database" * 100
    httpserver.expect_request("/e.sqlite").respond_with_data(data)
    source = {"url": httpserver.url_for("/e.sqlite")}
    if with_sha:
        source["sha256"] = hashlib.sha256(data).hexdigest()
    r = client.post("/v1/tools/eigenschappen", json={"index": source, "globalids": ["a"]}, headers=auth)
    assert r.status_code == 422 and r.json()["error_code"] == "index_ongeldig"
    assert not list(data_dir.rglob("*.sqlite"))
