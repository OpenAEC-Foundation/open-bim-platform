import json

import pytest
from test_index import first_wall_globalid
from test_tool_omzetten import BASE, run_omzetten
from typer.testing import CliRunner

from openbim_kern import CONVERTER_VERSION, cli
from openbim_kern.index.properties import build_property_index
from openbim_kern.jobs.store import default_store
from openbim_kern.jobs.worker import run_worker
from openbim_kern.tools.eigenschappen import EigenschappenIn

MCP_HEADERS = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}


@pytest.fixture(autouse=True)
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENBIM_KERN_DATA", str(tmp_path / "data"))
    return tmp_path / "data"


def mcp(client, auth, method, params=None, headers=None):
    body = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}}
    r = client.post("/mcp", headers={**auth, **MCP_HEADERS, **(headers or {})}, json=body)
    assert r.status_code == 200, r.text
    return r.json()["result"]


def mcp_call(client, auth, name, arguments, headers=None):
    return mcp(client, auth, "tools/call", {"name": name, "arguments": arguments}, headers)


@pytest.fixture
def index_source(httpserver, ifc_small, tmp_path):
    db = tmp_path / "e.sqlite"
    build_property_index(ifc_small, db)
    httpserver.expect_request("/e.sqlite").respond_with_data(db.read_bytes())
    return {"url": httpserver.url_for("/e.sqlite")}


# MCP


def test_mcp_lists_tools(client, auth):
    tools = {t["name"]: t for t in mcp(client, auth, "tools/list")["tools"]}
    assert {"eigenschappen", "omzetten", "taak_stand"} <= set(tools)
    assert tools["eigenschappen"]["inputSchema"] == EigenschappenIn.model_json_schema()
    assert set(tools["omzetten"]["outputSchema"]["properties"]) == {"taak"}  # long tool: a job, not the outcome


def test_mcp_requires_bearer(client):
    body = {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}
    r = client.post("/mcp", headers=MCP_HEADERS, json=body)
    assert r.status_code == 401 and r.json()["error_code"] == "geen_toegang"


def test_same_result_http_and_mcp(client, auth, index_source, ifc_small):
    body = {"index": index_source, "globalids": [first_wall_globalid(ifc_small), "onbekend"]}
    http = client.post("/v1/tools/eigenschappen", headers=auth, json=body)
    assert http.status_code == 200
    result = mcp_call(client, auth, "eigenschappen", body)
    assert not result["isError"]
    assert result["structuredContent"] == http.json()


def test_same_error_http_and_mcp(client, auth, httpserver):
    httpserver.expect_request("/kapot.sqlite").respond_with_data(b"geen database" * 100)
    body = {"index": {"url": httpserver.url_for("/kapot.sqlite")}, "globalids": ["a"]}
    http = client.post("/v1/tools/eigenschappen", headers=auth, json=body)
    result = mcp_call(client, auth, "eigenschappen", body)
    assert result["isError"] and result["structuredContent"] == http.json()
    assert json.loads(result["content"][0]["text"])["error_code"] == "index_ongeldig"


def test_mcp_invalid_input_like_http(client, auth):
    body = {"index": {"url": "http://127.0.0.1:1/e.sqlite"}, "globalids": ["a"], "pad": "/etc"}
    http = client.post("/v1/tools/eigenschappen", headers=auth, json=body)
    result = mcp_call(client, auth, "eigenschappen", body)
    assert result["isError"] and result["structuredContent"] == http.json()
    assert http.json()["error_code"] == "ongeldige_invoer"


def test_mcp_unknown_tool(client, auth):
    result = mcp_call(client, auth, "bestaat_niet", {})
    assert result["isError"] and result["structuredContent"]["error_code"] == "tool_onbekend"


def test_mcp_long_tool_returns_job(client, auth, store, slow_tool):
    result = mcp_call(client, auth, "traag", {"seconden": 0.1}, headers={"X-OpenAEC-Klantsite": "site-m"})
    assert not result["isError"] and set(result["structuredContent"]) == {"taak"}
    taak = result["structuredContent"]["taak"]
    assert store.get(taak).klantsite == "site-m"

    run_worker(store, {"licht": 1}, once=True)
    stand = mcp_call(client, auth, "taak_stand", {"taak": taak})
    assert not stand["isError"]
    assert stand["structuredContent"] == client.get(f"/v1/taken/{taak}", headers=auth).json()
    assert stand["structuredContent"]["status"] == "klaar"


def test_mcp_unknown_job(client, auth):
    result = mcp_call(client, auth, "taak_stand", {"taak": "bestaat-niet"})
    assert result["isError"] and result["structuredContent"]["error_code"] == "taak_onbekend"


# CLI


def test_cli_lists_commands():
    result = CliRunner().invoke(cli.app, ["--help"])
    assert result.exit_code == 0
    for command in ("serve", "werker", "omzetten"):
        assert command in result.stdout


def test_cli_omzetten(ifc_small, tmp_path):
    out = tmp_path / "uit"
    result = CliRunner().invoke(cli.app, ["omzetten", str(ifc_small), str(out)])
    assert result.exit_code == 0, result.output
    assert (out / "model.frag").stat().st_size > 0
    for name in BASE:
        assert (out / name).is_file()
    uitkomst = json.loads(result.stdout)
    assert uitkomst["omzetter"] == CONVERTER_VERSION and [d["naam"] for d in uitkomst["delen"]] == ["model.frag"]
    assert not [p for p in out.iterdir() if p.name.startswith(".")]  # no work directory left behind


def test_cli_omzetten_same_as_tool(httpserver, ifc_small, tmp_path):
    _, got = run_omzetten(httpserver, ifc_small, [*BASE, "model.frag"])
    out = tmp_path / "uit"
    assert CliRunner().invoke(cli.app, ["omzetten", str(ifc_small), str(out)]).exit_code == 0
    cli_index, tool_index = json.loads((out / "index.json").read_bytes()), json.loads(got["index.json"])
    # A .frag carries a random model id, so its size can differ by a few bytes between two conversions.
    for index in (cli_index, tool_index):
        for deel in index["delen"]:
            assert deel.pop("bytes") > 0
    assert cli_index == tool_index
    assert json.loads((out / "ruimtelijk.json").read_bytes()) == json.loads(got["ruimtelijk.json"])


def test_cli_omzetten_broken_file(ifc_truncated, tmp_path):
    out = tmp_path / "uit"
    result = CliRunner().invoke(cli.app, ["omzetten", str(ifc_truncated), str(out)])
    assert result.exit_code == 1
    assert "onvolledig" in result.stderr
    assert not out.exists() or not list(out.iterdir())


def test_cli_werker_once(slow_tool):
    store = default_store()
    taak = store.submit("traag", {"seconden": 0.1}, "lokaal")
    result = CliRunner().invoke(cli.app, ["werker", "--eenmalig"])
    assert result.exit_code == 0, result.output
    assert store.get(taak).status == "klaar"


def test_cli_serve_without_keys(monkeypatch):
    monkeypatch.delenv("OPENBIM_KERN_SLEUTELS", raising=False)
    monkeypatch.setattr(cli.uvicorn, "run", lambda *a, **k: pytest.fail("must not start"))
    result = CliRunner().invoke(cli.app, ["serve"])
    assert result.exit_code == 1 and "OPENBIM_KERN_SLEUTELS" in result.stderr


def test_cli_serve(monkeypatch):
    calls = {}
    monkeypatch.setattr(cli.uvicorn, "run", lambda app, **kwargs: calls.update(kwargs, app=app))
    monkeypatch.setenv("OPENBIM_KERN_SLEUTELS", "a")
    result = CliRunner().invoke(cli.app, ["serve", "--poort", "9999"])
    assert result.exit_code == 0, result.output
    assert calls["port"] == 9999 and calls["host"] == "127.0.0.1"
