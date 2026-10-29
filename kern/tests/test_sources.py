import hashlib
import socket
import threading

import pytest
from pydantic import ValidationError

from openbim_kern.errors import KernError
from openbim_kern.sources import Source, deliver, fetch_source

DATA = b"0123456789abcdef" * 4


def test_fetch_ok(httpserver, tmp_path):
    httpserver.expect_request("/a.ifc").respond_with_data(DATA)
    src = Source(url=httpserver.url_for("/a.ifc"), sha256=hashlib.sha256(DATA).hexdigest(), grootte=len(DATA))
    path = fetch_source(src, tmp_path, 1000)
    assert path.read_bytes() == DATA
    assert path.parent == tmp_path
    assert list(tmp_path.iterdir()) == [path]


def test_fetch_checks_sha256(httpserver, tmp_path):
    httpserver.expect_request("/a.ifc").respond_with_data(DATA)
    src = Source(url=httpserver.url_for("/a.ifc"), sha256="0" * 64)
    with pytest.raises(KernError) as exc:
        fetch_source(src, tmp_path, 1000)
    assert exc.value.error_code == "bron_ongeldig"
    assert exc.value.status == 422
    assert list(tmp_path.iterdir()) == []


def test_fetch_checks_declared_size(httpserver, tmp_path):
    httpserver.expect_request("/a.ifc").respond_with_data(DATA)
    src = Source(url=httpserver.url_for("/a.ifc"), grootte=len(DATA) + 1)
    with pytest.raises(KernError) as exc:
        fetch_source(src, tmp_path, 1000)
    assert exc.value.error_code == "bron_ongeldig"
    assert list(tmp_path.iterdir()) == []


def test_fetch_truncated_download(tmp_path):
    # Raw socket server: announces 100 bytes, sends 50 and closes (the test HTTP server would correct the header).
    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen(1)

    def serve():
        conn, _ = server.accept()
        with conn:
            conn.recv(65536)
            head = b"HTTP/1.1 200 OK\r\nContent-Length: 100\r\nConnection: close\r\n\r\n"
            conn.sendall(head + b"x" * 50)

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    try:
        with pytest.raises(KernError) as exc:
            fetch_source(Source(url=f"http://127.0.0.1:{server.getsockname()[1]}/a.ifc"), tmp_path, 1000)
    finally:
        thread.join(timeout=5)
        server.close()
    assert exc.value.error_code == "bron_ongeldig"
    assert exc.value.status == 422
    assert list(tmp_path.iterdir()) == []


def test_fetch_too_large(httpserver, tmp_path):
    httpserver.expect_request("/a.ifc").respond_with_data(b"x" * 11)
    with pytest.raises(KernError) as exc:
        fetch_source(Source(url=httpserver.url_for("/a.ifc")), tmp_path, 10)
    assert exc.value.error_code == "bron_te_groot"
    assert exc.value.status == 413
    assert list(tmp_path.iterdir()) == []


def test_fetch_http_error(httpserver, tmp_path):
    httpserver.expect_request("/a.ifc").respond_with_data("nee", status=404)
    with pytest.raises(KernError) as exc:
        fetch_source(Source(url=httpserver.url_for("/a.ifc")), tmp_path, 1000)
    assert exc.value.error_code == "bron_onbereikbaar"
    assert exc.value.status == 502
    assert list(tmp_path.iterdir()) == []


def test_fetch_unreachable(tmp_path):
    with pytest.raises(KernError) as exc:
        fetch_source(Source(url="http://127.0.0.1:1/a.ifc"), tmp_path, 1000)
    assert exc.value.error_code == "bron_onbereikbaar"


@pytest.mark.parametrize("url", ["file:///etc/passwd", "ftp://example.com/a"])
def test_only_http_urls(url):
    with pytest.raises(ValidationError):
        Source(url=url)


def test_source_forbids_extra_fields():
    with pytest.raises(ValidationError):
        Source(url="http://example.com/a", pad="/etc/passwd")


def test_deliver_puts_bytes(httpserver, tmp_path):
    f = tmp_path / "out.frag"
    f.write_bytes(DATA)
    httpserver.expect_request("/out", method="PUT", data=DATA).respond_with_data("", status=201)
    deliver(f, httpserver.url_for("/out"))
    httpserver.check_assertions()


def test_deliver_failure(httpserver, tmp_path):
    f = tmp_path / "out.frag"
    f.write_bytes(DATA)
    httpserver.expect_request("/out", method="PUT").respond_with_data("", status=500)
    with pytest.raises(KernError) as exc:
        deliver(f, httpserver.url_for("/out"))
    assert exc.value.error_code == "doel_onbereikbaar"
    assert exc.value.status == 502


def test_fetch_does_not_follow_redirects(httpserver, tmp_path):
    location = httpserver.url_for("/geheim")
    httpserver.expect_request("/a.ifc").respond_with_data("", status=302, headers={"Location": location})
    httpserver.expect_request("/geheim").respond_with_data(DATA)
    with pytest.raises(KernError) as exc:
        fetch_source(Source(url=httpserver.url_for("/a.ifc")), tmp_path, 1000)
    assert exc.value.error_code == "bron_onbereikbaar"
    assert exc.value.status == 502
    assert [r.path for r, _ in httpserver.log] == ["/a.ifc"]
    assert list(tmp_path.iterdir()) == []


def test_deliver_redirect_is_failure(httpserver, tmp_path):
    f = tmp_path / "out.frag"
    f.write_bytes(DATA)
    httpserver.expect_request("/out", method="PUT").respond_with_data("", status=307, headers={"Location": "/elders"})
    with pytest.raises(KernError) as exc:
        deliver(f, httpserver.url_for("/out"))
    assert exc.value.error_code == "doel_onbereikbaar"
    assert exc.value.status == 502
