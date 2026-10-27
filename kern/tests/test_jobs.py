import threading
import time

import psutil
import pytest

from openbim_kern.errors import KernError
from openbim_kern.jobs.worker import queues_from_env, run_worker

SITE = {"X-OpenAEC-Klantsite": "site-a"}


def drain(store, queues=None, max_per_site=2):
    run_worker(store, queues or {"licht": 2}, max_per_site=max_per_site, once=True)


def wait_for(predicate, timeout=30.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if predicate():
            return True
        time.sleep(0.05)
    return False


def test_long_tool_returns_202(client, auth, slow_tool, store):
    r = client.post("/v1/tools/traag", headers={**auth, **SITE}, json={})
    assert r.status_code == 202 and set(r.json()) == {"taak"}
    job = store.get(r.json()["taak"])
    assert job.status == "wacht" and job.tool == "traag" and job.klantsite == "site-a"


def test_long_tool_input_validated_before_queueing(client, auth, slow_tool):
    r = client.post("/v1/tools/traag", headers=auth, json={"seconden": "lang", "pad": "/etc"})
    assert r.status_code == 422 and r.json()["error_code"] == "ongeldige_invoer"


def test_default_site_is_lokaal(client, auth, slow_tool, store):
    taak = client.post("/v1/tools/traag", headers=auth, json={}).json()["taak"]
    assert store.get(taak).klantsite == "lokaal"


def test_invalid_site_refused(client, auth, slow_tool):
    r = client.post("/v1/tools/traag", headers={**auth, "X-OpenAEC-Klantsite": "a b/c"}, json={})
    assert r.status_code == 422 and r.json()["error_code"] == "ongeldige_invoer"


def test_worker_runs_job(store, slow_tool):
    taak = store.submit("traag", {"seconden": 0.2}, "a")
    drain(store)
    job = store.get(taak)
    assert job.status == "klaar" and job.voortgang == 1.0
    assert job.uitkomst == {"klaar": True} and job.fout is None
    assert job.gestart and job.klaar


def test_job_over_http(client, auth, slow_tool, store):
    taak = client.post("/v1/tools/traag", headers=auth, json={"seconden": 0.1}).json()["taak"]
    drain(store)
    r = client.get(f"/v1/taken/{taak}", headers=auth)
    assert r.status_code == 200
    body = r.json()
    assert body["taak"] == taak and body["status"] == "klaar" and body["uitkomst"] == {"klaar": True}
    assert "invoer" not in body  # may hold signed addresses


def test_taken_requires_bearer(client, slow_tool, store):
    taak = store.submit("traag", {}, "a")
    assert client.get(f"/v1/taken/{taak}").status_code == 401
    assert client.delete(f"/v1/taken/{taak}").status_code == 401


def test_unknown_job(client, auth, store):
    r = client.get("/v1/taken/bestaat-niet", headers=auth)
    assert r.status_code == 404 and r.json()["error_code"] == "taak_onbekend"
    assert client.delete("/v1/taken/bestaat-niet", headers=auth).status_code == 404
    with pytest.raises(KernError):
        store.get("bestaat-niet")


def test_failure_is_json(store, failing_tool):
    taak = store.submit("faalt", {}, "a")
    drain(store)
    job = store.get(taak)
    assert job.status == "fout" and job.uitkomst is None
    assert job.fout["error_code"] == "expres_mislukt"
    assert set(job.fout) == {"error_code", "melding", "remedie"}


def test_crash_is_reported(store, crashing_tool):
    taak = store.submit("crasht", {}, "a")
    drain(store)
    job = store.get(taak)
    assert job.status == "fout" and job.fout["error_code"] == "taak_gestopt"


def test_restart_requeues(store, slow_tool):
    taak = store.submit("traag", {}, "a")
    assert store.claim("licht", max_running=1, max_per_site=2).taak == taak
    assert store.get(taak).status == "bezig"
    assert store.requeue_running() == 1
    job = store.get(taak)
    assert job.status == "wacht" and job.gestart is None and job.voortgang == 0.0


def test_per_site_limit(store, slow_tool):
    first, second, third = (store.submit("traag", {}, "a") for _ in range(3))
    other = store.submit("traag", {}, "b")
    claimed = [store.claim("licht", max_running=10, max_per_site=2) for _ in range(3)]
    assert [j.taak for j in claimed] == [first, second, other]  # site b is not held up by site a
    assert store.claim("licht", max_running=10, max_per_site=2) is None
    store.finish(first, {"klaar": True})
    assert store.claim("licht", max_running=10, max_per_site=2).taak == third


def test_queue_concurrency(store, slow_tool):
    store.submit("traag", {}, "a")
    store.submit("traag", {}, "b")
    assert store.claim("licht", max_running=1, max_per_site=2) is not None
    assert store.claim("licht", max_running=1, max_per_site=2) is None
    assert store.claim("omzetten", max_running=1, max_per_site=2) is None  # other queue


def test_queue_full(client, auth, slow_tool):
    for _ in range(100):
        assert client.post("/v1/tools/traag", headers={**auth, **SITE}, json={}).status_code == 202
    r = client.post("/v1/tools/traag", headers={**auth, **SITE}, json={})
    assert r.status_code == 503 and r.headers["Retry-After"] == "30"
    assert r.json()["error_code"] == "te_druk"
    other = client.post("/v1/tools/traag", headers={**auth, "X-OpenAEC-Klantsite": "site-b"}, json={})
    assert other.status_code == 202


def test_cancel_waiting(client, auth, store, slow_tool):
    taak = store.submit("traag", {}, "a")
    r = client.delete(f"/v1/taken/{taak}", headers=auth)
    assert r.status_code == 200 and r.json() == {"status": "afgebroken"}
    assert store.claim("licht", max_running=1, max_per_site=2) is None


def test_cancel(store, slow_tool):
    taak = store.submit("traag", {"seconden": 60}, "a")
    worker = threading.Thread(target=drain, args=(store,), daemon=True)
    worker.start()
    assert wait_for(lambda: store.get(taak).voortgang > 0)  # the job is really running
    t0 = time.monotonic()
    store.cancel(taak)
    worker.join(timeout=5)
    assert not worker.is_alive() and time.monotonic() - t0 < 5
    assert store.get(taak).status == "afgebroken"
    assert not psutil.Process().children(recursive=True)


def test_finished_job_cannot_be_cancelled(store, slow_tool):
    taak = store.submit("traag", {}, "a")
    drain(store)
    store.cancel(taak)
    assert store.get(taak).status == "klaar"


def test_queues_from_env(monkeypatch):
    assert queues_from_env() == {"omzetten": 1, "licht": 4}
    monkeypatch.setenv("OPENBIM_RIJ_OMZETTEN", "2")
    monkeypatch.setenv("OPENBIM_RIJ_LICHT", "8")
    assert queues_from_env() == {"omzetten": 2, "licht": 8}
