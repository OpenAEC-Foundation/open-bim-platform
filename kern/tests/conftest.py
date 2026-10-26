import pytest
from fastapi.testclient import TestClient

from openbim_kern.app import create_app
from openbim_kern.tools.registry import REGISTRY, tool

KEY = "test-sleutel"


@pytest.fixture
def client():
    return TestClient(create_app(keys=[KEY]))


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
