import json
import subprocess
from collections import Counter
from pathlib import Path

import ifcopenshell
import ifcopenshell.util.element as element_util
import pytest
from leftovers import leftover_processes

from openbim_kern import converter
from openbim_kern.converter import CONVERT_SCRIPT, convert_to_frag, split_ifc
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


def test_full_v8_heap_is_reported_as_too_much_memory(fake_converter, monkeypatch, ifc_small, tmp_path):
    monkeypatch.setenv("FAKE_V8_OOM", "1")
    e = pytest.raises(KernError, convert_to_frag, ifc_small, tmp_path / "m.frag").value
    assert e.error_code == "omzetten_te_veel_geheugen"
    assert ifc_small.name in e.melding and "0x" not in e.melding


def test_node_heap_follows_the_memory_limit(monkeypatch):
    # Node stops at about 4 GB of heap by itself, too little to split an IFC of a few GB.
    monkeypatch.setenv("NODE_OPTIONS", "--enable-source-maps")
    env = converter._environment(6 * 2**30)
    assert env["NODE_OPTIONS"] == "--enable-source-maps --max-old-space-size=6144"
    monkeypatch.delenv("NODE_OPTIONS")
    assert converter._environment(2**30)["NODE_OPTIONS"] == "--max-old-space-size=1024"


def test_splitting_may_use_more_memory_than_converting(monkeypatch):
    # Measured: the splitter keeps an index of every line, about 6.4 times the IFC size at its peak.
    monkeypatch.delenv("OPENBIM_GEHEUGEN_GRENS_BYTES", raising=False)
    assert converter._memory_limit(10**9) == 4 * 10**9
    assert converter._memory_limit(10**9, converter.SPLIT_MEMORY_FACTOR) == 8 * 10**9
    monkeypatch.setenv("OPENBIM_GEHEUGEN_GRENS_BYTES", "123")
    assert converter._memory_limit(10**9, converter.SPLIT_MEMORY_FACTOR) == 123


def test_time_limit(fake_converter, monkeypatch, ifc_small, tmp_path):
    monkeypatch.setenv("FAKE_SLEEP_S", "30")
    monkeypatch.setenv("OPENBIM_TIJD_GRENS_S", "1")
    e = pytest.raises(KernError, convert_to_frag, ifc_small, tmp_path / "m.frag").value
    assert e.error_code == "omzetten_tijd_op"
    assert not (tmp_path / "m.frag").exists()
    assert not leftover_processes()


LINES = CONVERT_SCRIPT.with_name("lines.mjs")


def _node_lines(script: str, path: Path) -> dict:
    """Run a module that imports readLines from converter/lines.mjs on `path`; returns its JSON output."""
    code = f"import {{ readLines }} from {json.dumps(LINES.as_uri())};\n{script}"
    run = subprocess.run(["node", "--input-type=module", "-e", code, str(path)], capture_output=True, text=True)
    assert run.returncode == 0, run.stderr
    return json.loads(run.stdout)


def test_lines_are_read_only_as_far_as_they_are_asked_for(tmp_path):
    # The splitter reads an IFC line by line. Reading the whole file ahead into the queue of the stream costs memory
    # in proportion to the file, and every line taken from a queue of millions is slow.
    big = tmp_path / "regels.ifc"
    big.write_text("".join(f"#{i}=IFCWALL('{i}');\n" for i in range(400_000)), encoding="utf-8")
    out = _node_lines(
        """let pieces = 0;
const reader = readLines(process.argv[1], () => pieces++).getReader();
const first = await reader.read();
for (let i = 0; i < 20; i++) await new Promise((r) => setTimeout(r, 5));
console.log(JSON.stringify({ first: first.value, pieces }));""",
        big,
    )
    assert out == {"first": "#0=IFCWALL('0');", "pieces": 1}


def test_lines_without_line_endings_across_pieces(tmp_path):
    text = "".join(f"#{i}=X('{'a' * (i % 97)}');\r\n" for i in range(60_000)) + "END-ISO-10303-21;"
    path = tmp_path / "m.ifc"
    path.write_bytes(text.encode("utf-8"))
    out = _node_lines(
        """const lines = [];
for await (const line of readLines(process.argv[1])) lines.push(line);
const crlf = lines.some((l) => l.includes("\\r"));
console.log(JSON.stringify({ count: lines.length, last: lines.at(-1), crlf }));""",
        path,
    )
    assert out == {"count": 60_001, "last": "END-ISO-10303-21;", "crlf": False}


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
