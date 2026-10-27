import pytest
from fastapi.testclient import TestClient

from openbim_kern.app import create_app
from openbim_kern.tools.registry import REGISTRY, tool

KEY = "test-sleutel"


@pytest.fixture
def store(tmp_path):
    from openbim_kern.jobs.store import JobStore

    return JobStore(tmp_path / "taken.sqlite")


@pytest.fixture
def client(store):
    return TestClient(create_app(keys=[KEY], store=store))


@pytest.fixture
def auth():
    return {"Authorization": f"Bearer {KEY}"}


@pytest.fixture
def echo_tool():
    """Register the `echo` test tool for one test and remove it afterwards."""
    import tooltools

    tool("echo", "Echo the given text.")(tooltools.echo)
    try:
        yield
    finally:
        REGISTRY.pop("echo", None)


def _register(naam, fn_name, **kwargs):
    import tooltools

    tool(naam, f"Test tool {naam}.", **kwargs)(getattr(tooltools, fn_name))
    try:
        yield naam
    finally:
        REGISTRY.pop(naam, None)


@pytest.fixture
def slow_tool():
    """Long tool `traag` in queue `licht`: sleeps `seconden`, reporting progress."""
    yield from _register("traag", "traag", lang=True, rij="licht")


@pytest.fixture
def failing_tool():
    yield from _register("faalt", "faalt", lang=True, rij="licht")


@pytest.fixture
def crashing_tool():
    yield from _register("crasht", "crasht", lang=True, rij="licht")


@pytest.fixture(scope="session")
def models_dir(tmp_path_factory):
    return tmp_path_factory.mktemp("ifc-models")


@pytest.fixture(scope="session")
def ifc_small(models_dir):
    import models

    return models.ifc_small(models_dir / "small.ifc")


@pytest.fixture(scope="session")
def ifc_2x3(models_dir):
    import models

    return models.ifc_2x3(models_dir / "small_2x3.ifc")


@pytest.fixture(scope="session")
def ifc_georef(models_dir):
    import models

    return models.ifc_georef(models_dir / "georef.ifc")


@pytest.fixture(scope="session")
def ifc_truncated(models_dir, ifc_small):
    import models

    return models.ifc_truncated(models_dir / "truncated.ifc", ifc_small)


@pytest.fixture
def fake_converter(monkeypatch, tmp_path):
    """Point OPENBIM_OMZETTER_CMD at tests/fakeconv.py (JSON list form, portable)."""
    import json
    import sys
    from pathlib import Path

    script = Path(__file__).parent / "fakeconv.py"
    monkeypatch.setenv("OPENBIM_OMZETTER_CMD", json.dumps([sys.executable, str(script)]))
    monkeypatch.setenv("FAKE_FAIL_ONCE_MARKER", "")
    return tmp_path / "marker"
