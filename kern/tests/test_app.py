import pytest

from openbim_kern import __version__
from openbim_kern.app import create_app
from openbim_kern.tools.registry import REGISTRY


def test_health_is_public(client):
    assert client.get("/v1/health").json() == {"status": "ok", "versie": __version__}


def test_openapi_is_public(client):
    assert client.get("/v1/openapi.json").status_code == 200


def test_tools_requires_bearer(client):
    r = client.get("/v1/tools")
    assert r.status_code == 401 and r.json()["error_code"] == "geen_toegang"


def test_wrong_bearer_refused(client):
    r = client.get("/v1/tools", headers={"Authorization": "Bearer fout"})
    assert r.status_code == 401 and r.json()["error_code"] == "geen_toegang"
    assert set(r.json()) == {"error_code", "melding", "remedie"}


def test_unknown_tool(client, auth):
    r = client.post("/v1/tools/bestaat_niet", headers=auth, json={})
    assert r.status_code == 404 and r.json()["error_code"] == "tool_onbekend"


def test_extra_argument_refused(client, auth, echo_tool):
    r = client.post("/v1/tools/echo", headers=auth, json={"tekst": "a", "path": "/etc"})
    assert r.status_code == 422 and r.json()["error_code"] == "ongeldige_invoer"


def test_echo_roundtrip(client, auth, echo_tool):
    r = client.post("/v1/tools/echo", headers=auth, json={"tekst": "hallo"})
    assert r.status_code == 200 and r.json() == {"tekst": "hallo"}


def test_tool_listing(client, auth, echo_tool):
    r = client.get("/v1/tools", headers=auth)
    assert r.status_code == 200
    (entry,) = [t for t in r.json() if t["naam"] == "echo"]
    assert entry["lang"] is False
    assert "tekst" in entry["invoer_schema"]["properties"]
    assert "tekst" in entry["uitvoer_schema"]["properties"]


def test_spec_carries_importable_ref(echo_tool):
    assert REGISTRY["echo"].ref == "tooltools:echo"


def test_registry_clean_after_tests():
    assert "echo" not in REGISTRY


def test_no_keys_no_start(monkeypatch):
    monkeypatch.delenv("OPENBIM_KERN_SLEUTELS", raising=False)
    with pytest.raises(RuntimeError):
        create_app()


def test_keys_from_env(monkeypatch):
    from fastapi.testclient import TestClient

    monkeypatch.setenv("OPENBIM_KERN_SLEUTELS", "a, b")
    c = TestClient(create_app())
    assert c.get("/v1/tools", headers={"Authorization": "Bearer b"}).status_code == 200
