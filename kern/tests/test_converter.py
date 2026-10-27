from collections import Counter

import ifcopenshell
import ifcopenshell.util.element as element_util
import pytest
from leftovers import leftover_processes

from openbim_kern.converter import convert_to_frag, split_ifc
from openbim_kern.errors import KernError


def test_convert_small(ifc_small, tmp_path):
    out = tmp_path / "m.frag"
    s = convert_to_frag(ifc_small, out)
    assert s.out_bytes > 0 and out.stat().st_size == s.out_bytes
    assert s.in_bytes == ifc_small.stat().st_size and s.attempts == 1 and s.peak_rss > 0


def test_truncated_ifc_fails_cleanly(ifc_truncated, tmp_path):
    out = tmp_path / "m.frag"
    e = pytest.raises(KernError, convert_to_frag, ifc_truncated, out).value
    assert e.error_code == "omzetten_mislukt"
    assert "onvolledig" in e.melding
    assert not out.exists()


def test_retries_wasm_exception(fake_converter, monkeypatch, ifc_small, tmp_path):
    monkeypatch.setenv("FAKE_FAIL_ONCE_MARKER", str(fake_converter))
    monkeypatch.setenv("FAKE_PARTIAL", "1")
    out = tmp_path / "m.frag"
    s = convert_to_frag(ifc_small, out)
    assert s.attempts == 2
    assert out.read_bytes() == ifc_small.read_bytes()


def test_no_retry_other_error(fake_converter, monkeypatch, ifc_small, tmp_path):
    monkeypatch.setenv("FAKE_ERROR", "kapot")
    monkeypatch.setenv("FAKE_PARTIAL", "1")
    out = tmp_path / "m.frag"
    e = pytest.raises(KernError, convert_to_frag, ifc_small, out).value
    assert e.error_code == "omzetten_mislukt"
    assert "kapot" in e.melding and "first line" not in e.melding
    assert not out.exists()
    assert not list(tmp_path.glob("m.frag*"))


def test_memory_limit(fake_converter, monkeypatch, ifc_small, tmp_path):
    monkeypatch.setenv("FAKE_HOLD_MB", "400")
    monkeypatch.setenv("OPENBIM_GEHEUGEN_GRENS_BYTES", str(200 * 1024 * 1024))
    e = pytest.raises(KernError, convert_to_frag, ifc_small, tmp_path / "m.frag").value
    assert e.error_code == "omzetten_te_veel_geheugen"
    assert not leftover_processes()


def test_time_limit(fake_converter, monkeypatch, ifc_small, tmp_path):
    monkeypatch.setenv("FAKE_SLEEP_S", "30")
    monkeypatch.setenv("OPENBIM_TIJD_GRENS_S", "1")
    e = pytest.raises(KernError, convert_to_frag, ifc_small, tmp_path / "m.frag").value
    assert e.error_code == "omzetten_tijd_op"
    assert not (tmp_path / "m.frag").exists()
    assert not leftover_processes()


def test_split(ifc_small, tmp_path):
    parts = split_ifc(ifc_small, 2, tmp_path)
    assert len(parts) == 2 and all(ifcopenshell.open(str(p)).by_type("IfcProject") for p in parts)
    assert [p.name for p in parts] == ["deel-1.ifc", "deel-2.ifc"]


def _containers(ifc):
    model = ifcopenshell.open(str(ifc))
    result = {}
    for el in model.by_type("IfcElement"):
        container = element_util.get_container(el)
        result[el.GlobalId] = container.GlobalId if container else None
    return result


def test_split_puts_each_element_in_one_part(ifc_small, tmp_path):
    """IFC4-only element types (an IfcDuctSegment here) must be split like the others, keeping their storey."""
    parts = split_ifc(ifc_small, 2, tmp_path)
    found = [_containers(p) for p in parts]
    counts = Counter(gid for part in found for gid in part)
    source = _containers(ifc_small)
    assert counts == Counter(source.keys())  # every element in exactly one part
    assert {gid: c for part in found for gid, c in part.items()} == source
