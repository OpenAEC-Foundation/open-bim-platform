import hashlib
import shutil
import socket
from types import SimpleNamespace
from urllib.parse import quote

import httpx
import pytest
from test_index import first_wall_globalid
from typer.testing import CliRunner

from openbim_kern import CONVERTER_VERSION, cli
from openbim_kern.app import create_app
from openbim_kern.jobs.worker import run_worker
from openbim_kern.local.server import BackgroundServer, create_local_app

KEY = "lokale-sleutel"
WALL_MODEL = "Constructie/wand model.ifc"


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(autouse=True)
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENBIM_KERN_DATA", str(tmp_path / "data"))


@pytest.fixture
def local(tmp_path, store):
    """A project folder served by the local server, with a real kern behind it (both over real HTTP)."""
    root = tmp_path / "Project Één"
    root.mkdir()
    port = free_port()
    with BackgroundServer(create_app(keys=[KEY], store=store), free_port()) as kern:
        with BackgroundServer(create_local_app(root, kern.url, KEY, poort=port), port) as server:
            with httpx.Client(base_url=server.url, timeout=60) as client:
                yield SimpleNamespace(root=root, client=client, store=store, url=server.url)


def add_model(local, relative, source):
    path = local.root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, path)
    return path


def models(local):
    r = local.client.get("/lokaal/project")
    assert r.status_code == 200, r.text
    return {m["bron"]["sleutel"]: m for m in r.json()["modellen"]}


def convert(local):
    r = local.client.post("/lokaal/omzetten")
    assert r.status_code == 200, r.text
    run_worker(local.store, {"omzetten": 1}, once=True)
    return r.json()


def test_project_lists_models(local, ifc_small):
    add_model(local, WALL_MODEL, ifc_small)
    (local.root / "notities.txt").write_text("geen model")
    r = local.client.get("/lokaal/project")
    assert r.json()["project"] == "Project Één" and r.json()["werkwijze"] == "bestanden"
    (model,) = r.json()["modellen"]
    sha = hashlib.sha256(ifc_small.read_bytes()).hexdigest()
    assert model["bron"] == {"soort": "bestand", "sleutel": WALL_MODEL, "versie": sha[:12]}
    assert model["naam"] == "wand model" and model["discipline"] == "Constructie"
    assert model["status"] == "wacht" and model["delen"] == [] and model["index"] is None


def test_model_in_root_has_no_discipline(local, ifc_small):
    add_model(local, "los.IFC", ifc_small)
    assert models(local)["los.IFC"]["discipline"] == ""


def test_hidden_folders_are_skipped(local, ifc_small):
    add_model(local, ".git/oud.ifc", ifc_small)
    add_model(local, ".afgeleid/x.ifc", ifc_small)
    assert models(local) == {}


def test_unicode_and_spaces(local, ifc_small):
    add_model(local, "Installaties/kanaal één.ifc", ifc_small)
    r = local.client.get("/lokaal/bestanden/" + quote("Installaties/kanaal één.ifc"))
    assert r.status_code == 200 and r.content == ifc_small.read_bytes()


@pytest.mark.parametrize("path", ["..%2F..%2Fgeheim", "%2Fetc%2Fpasswd", "C:%2FWindows%2Fwin.ini", "a%5C..%5C..%5Cx"])
def test_dotdot_refused(local, path):
    r = local.client.get(f"/lokaal/bestanden/{path}")
    assert r.status_code == 400 and r.json()["error_code"] == "ongeldig_pad"


def test_missing_file(local):
    r = local.client.get("/lokaal/bestanden/bestaat-niet.ifc")
    assert r.status_code == 404 and r.json()["error_code"] == "bestand_onbekend"


def test_put_only_under_derived(local, ifc_small):
    add_model(local, WALL_MODEL, ifc_small)
    r = local.client.put("/lokaal/bestanden/" + quote(WALL_MODEL), content=b"overschreven")
    assert r.status_code == 400 and r.json()["error_code"] == "ongeldig_pad"
    assert (local.root / WALL_MODEL).read_bytes() == ifc_small.read_bytes()
    r = local.client.put("/lokaal/bestanden/.afgeleid/a/b.bin", content=b"inhoud")
    assert r.status_code == 200 and (local.root / ".afgeleid/a/b.bin").read_bytes() == b"inhoud"


def test_foreign_host_refused(local):
    r = local.client.get("/lokaal/project", headers={"Host": "kwaadwillend.example"})
    assert r.status_code == 400


def test_cors_only_for_vite(local):
    allowed = local.client.options(
        "/lokaal/project",
        headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "GET"},
    )
    assert allowed.headers.get("access-control-allow-origin") == "http://localhost:5173"
    other = local.client.get("/lokaal/project", headers={"Origin": "http://kwaadwillend.example"})
    assert "access-control-allow-origin" not in other.headers


def test_convert_then_ready(local, ifc_small):
    add_model(local, WALL_MODEL, ifc_small)
    queued = convert(local)
    assert [t["sleutel"] for t in queued["taken"]] == [WALL_MODEL]
    model = models(local)[WALL_MODEL]
    assert model["status"] == "klaar", model
    assert [d["naam"] for d in model["delen"]] == ["model.frag"] and model["delen"][0]["bytes"] > 0
    assert model["index"]["omzetter"] == CONVERTER_VERSION
    derived = local.root / ".afgeleid" / WALL_MODEL / model["bron"]["versie"] / CONVERTER_VERSION
    assert (derived / "model.frag").stat().st_size == model["delen"][0]["bytes"]
    assert local.client.post("/lokaal/omzetten").json()["taken"] == []  # nothing left to convert


def test_status_while_queued(local, ifc_small):
    add_model(local, WALL_MODEL, ifc_small)
    local.client.post("/lokaal/omzetten")
    assert models(local)[WALL_MODEL]["status"] == "wacht"
    assert local.client.post("/lokaal/omzetten").json()["taken"] == []  # already queued


def test_failed_model_reported_and_retried(local, ifc_truncated):
    add_model(local, "kapot.ifc", ifc_truncated)
    convert(local)
    model = models(local)["kapot.ifc"]
    assert model["status"] == "fout" and model["fout"]["error_code"] == "omzetten_mislukt"
    assert [t["sleutel"] for t in local.client.post("/lokaal/omzetten").json()["taken"]] == ["kapot.ifc"]


def test_new_version_detected(local, ifc_small, ifc_2x3):
    path = add_model(local, WALL_MODEL, ifc_small)
    convert(local)
    old = models(local)[WALL_MODEL]
    shutil.copyfile(ifc_2x3, path)
    new = models(local)[WALL_MODEL]
    assert new["bron"]["versie"] != old["bron"]["versie"] and new["status"] == "wacht"
    assert (local.root / ".afgeleid" / WALL_MODEL / old["bron"]["versie"] / CONVERTER_VERSION / "index.json").is_file()


def test_eigenschappen(local, ifc_small):
    add_model(local, WALL_MODEL, ifc_small)
    bron = models(local)[WALL_MODEL]["bron"]
    wall = first_wall_globalid(ifc_small)
    early = local.client.post("/lokaal/eigenschappen", json={"bron": bron, "globalids": [wall]})
    assert early.status_code == 409 and early.json()["error_code"] == "nog_niet_klaar"
    convert(local)
    r = local.client.post("/lokaal/eigenschappen", json={"bron": bron, "globalids": [wall]})
    assert r.status_code == 200, r.text
    assert r.json()["elementen"][wall]["psets"]["Pset_WallCommon"]["FireRating"] == "60"


def test_eigenschappen_unknown_model(local):
    bron = {"soort": "bestand", "sleutel": "bestaat-niet.ifc", "versie": "0" * 12}
    r = local.client.post("/lokaal/eigenschappen", json={"bron": bron, "globalids": ["a"]})
    assert r.status_code == 404 and r.json()["error_code"] == "model_onbekend"


def test_cli_lokaal(monkeypatch, tmp_path):
    calls = {}
    monkeypatch.setattr(cli.uvicorn, "run", lambda app, **kwargs: calls.update(kwargs, app=app))
    result = CliRunner().invoke(cli.app, ["lokaal", str(tmp_path), "--poort", "9741", "--kern-poort", str(free_port())])
    assert result.exit_code == 0, result.output
    assert calls["host"] == "127.0.0.1" and calls["port"] == 9741
