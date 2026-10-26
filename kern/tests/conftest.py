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
