# Fase 0: fundament — implementatieplan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Een BIM-kern die IFC-bestanden (tot enkele GB) omzet naar fragments plus een eigenschappen-index, en een
viewer die een map met modellen samen laadt binnen een geheugenbudget, lokaal en op de bench.

**Architecture:** `kern/` is een FastAPI-rekenkern volgens het SuperCloud-contract (`/v1/…`, `/mcp`), met een
Python-pakket `openbim_kern` (IfcOpenShell) en een Node-omzetter (`@thatopen/fragments`) die per taak in een eigen
proces draait. Lange taken lopen via een wachtrij in SQLite met een losse werker. Een lokale ontwikkelserver speelt
voor deze fase de rol van `openaec_bim` en Storage. `viewer/` is een React-app met That Open, met een host-laag zodat
hij in fase 1 ongewijzigd in de werkplek past.

**Tech Stack:** Python 3.12, FastAPI, pydantic 2, httpx, IfcOpenShell 0.8.x, psutil, typer, `mcp` 1.x, pytest;
Node 24, `@thatopen/fragments` 3.6.0, `web-ifc` 0.0.78, `three` 0.186.1; React 18, Vite, TypeScript, vitest,
Playwright; `@openaec/*` 0.1.0 (style-book).

**Spec:** `docs/superpowers/specs/2026-10-26-open-bim-platform-design.md` (hoofdstukken 4, 5.3–5.5, 5.7, 9 fase 0,
11).

## Global Constraints

- Geen namen van commerciële concurrerende software en geen verwijzingen naar gesprekken, nergens in de repo.
- Code (namen, docstrings, commentaar) in het Engels; documentatie in het Nederlands; commits
  `type(scope): Nederlandse omschrijving`, eindigend op `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Het HTTP-contract volgt de SuperCloud en is Nederlands: toolnamen (`omzetten`, `eigenschappen`), velden (`bron`,
  `doelen`, `taak`, `status`, `voortgang`, `uitkomst`), fouten `{"error_code", "melding", "remedie"}`.
- Ingangen: `GET /v1/health` en `GET /v1/openapi.json` openbaar; `GET /v1/tools`, `POST /v1/tools/{naam}`,
  `GET|DELETE /v1/taken/{taak}`, `POST /mcp` alleen met `Authorization: Bearer <sleutel>`. Zonder sleutels
  (`OPENBIM_KERN_SLEUTELS`, komma-gescheiden) start de dienst niet.
- Cloudbeleid: tools werken alleen met gegevens in het verzoek; bronnen en doelen zijn `http(s)`-adressen, nooit een
  pad; argumenten die niet in het schema staan, weigeren (pydantic `extra="forbid"`).
- Versies exact vastgezet: `@thatopen/fragments` `3.6.0`, `@thatopen/components` `3.6.0`,
  `@thatopen/components-front` `3.6.0`, `web-ifc` `0.0.78`, `three` `0.186.1`, `@openaec/*` `0.1.0`.
- Omzetten: splitsen boven `1_500_000_000` bytes (`OPENBIM_SPLITS_VANAF_BYTES`) in `ceil(grootte / 1_000_000_000)`
  delen; geheugengrens per omzetproces `3 × grootte + 1 GB`; tijdslimiet `max(300 s, 1800 s per GB)`; hoogstens 2
  herhalingen bij een WebAssembly-fout.
- Omzetterversie: `kern-<versie van openbim_kern>+fragments-3.6.0`.
- Viewer: de worker van fragments en de WASM in de bundel, nooit van een CDN; geen `localStorage`, IndexedDB of
  cookies zonder `try/catch` met terugval in het geheugen; geschat browsergeheugen per model = `18 × .frag-bytes`;
  standaardbudget `2 GB`.
- Geen modellen van klanten in de repo; testmodellen worden in de tests gemaakt met IfcOpenShell.

## Review Focus

1. **Kapot of afgebroken IFC-bestand** → `omzetten` eindigt binnen de tijdslimiet met `omzetten_mislukt` en een
   leesbare melding, nooit een hangend proces. Test in taak 5 (`test_truncated_ifc_fails_cleanly`).
2. **Dezelfde GlobalIds in twee bestanden** (een gekopieerd model) → eigenschappen en selectie blijven per bron
   gescheiden. Test in taak 4 (`test_index_is_per_source`) en taak 12 (`selection keys include source`).
3. **IFC2X3 en een model met IfcMapConversion** → index werkt en legt de georeferentie vast. Test in taak 4.
4. **Download onderbroken of sha256 klopt niet** → `bron_ongeldig`, geen half bestand gebruikt. Test in taak 2.
5. **Bestandsnamen met spaties, accenten of `..`** → de lokale server serveert de eerste twee en weigert `..`. Test in
   taak 9.

---

## Bestandsindeling

```
kern/
  pyproject.toml
  src/openbim_kern/
    __init__.py            __version__, CONVERTER_VERSION
    app.py                 FastAPI-app, auth, foutafhandeling, /v1-routes
    errors.py              KernError(error_code, melding, remedie, status)
    tools/registry.py      ToolSpec, @tool, REGISTRY
    tools/omzetten.py      de tool omzetten
    tools/eigenschappen.py de tool eigenschappen
    sources.py             Source, fetch_source, deliver
    index/properties.py    build_property_index, merge_property_index, read_properties
    index/spatial.py       build_spatial_tree, build_summary
    converter.py           convert_to_frag, split_ifc (Node in subprocess, watchdog)
    jobs/store.py          JobStore (SQLite)
    jobs/worker.py         run_worker
    mcp_server.py          MCP over Streamable HTTP, uit REGISTRY
    cli.py                 typer: serve, werker, lokaal, omzetten
    local/server.py        lokale ontwikkelserver (rol van openaec_bim + Storage)
  converter/
    package.json, package-lock.json
    convert.mjs            `frag <in> <out>` en `split <in> <n> <map>`
  scripts/enlarge.py       synthetisch groot IFC
  scripts/measure.py       meetrapport over een map
  tests/
    conftest.py            fixtures, o.a. ifc_small, ifc_2x3, ifc_georef
    models.py              testmodellen met ifcopenshell.api
  Dockerfile, compose.yaml
viewer/
  package.json, vite.config.ts, index.html
  src/host/BimHost.ts      interface + typen
  src/host/LocalHost.ts
  src/model/budget.ts
  src/model/selection.ts
  src/engine/FragmentsEngine.ts
  src/ui/App.tsx, ModelList.tsx, PropertiesPanel.tsx
  e2e/smoke.spec.ts
.github/workflows/ci.yml
```

---

### Task 1: Kern-skelet met het rekenkern-contract

**Files:**
- Create: `kern/pyproject.toml`, `kern/src/openbim_kern/{__init__,app,errors}.py`, `kern/src/openbim_kern/tools/registry.py`
- Test: `kern/tests/test_app.py`

**Interfaces:**
- Produces:
  - `KernError(error_code: str, melding: str, remedie: str, status: int = 400)` (exception); de app zet hem om naar
    JSON `{error_code, melding, remedie}` met `status`.
  - `ToolSpec(naam: str, beschrijving: str, invoer: type[BaseModel], uitvoer: type[BaseModel], lang: bool, rij: str, fn: Callable)`.
  - Decorator `tool(naam: str, beschrijving: str, *, lang: bool = False, rij: str = "licht")`; registreert in
    `REGISTRY: dict[str, ToolSpec]`. Invoer- en uitvoertype komen uit de typehints van `fn(invoer) -> uitvoer`.
  - `create_app(keys: list[str] | None = None) -> FastAPI` (leest anders `OPENBIM_KERN_SLEUTELS`; leeg → `RuntimeError`).
  - `GET /v1/tools` → `[{naam, beschrijving, lang, invoer_schema, uitvoer_schema}]`.
  - `POST /v1/tools/{naam}` voor een niet-lange tool: lichaam = invoer, antwoord = uitvoer. (Lange tools: taak 7.)

- [ ] **Step 1: Write the failing tests**

```python
def test_health_is_public(client): assert client.get("/v1/health").json() == {"status": "ok", "versie": __version__}
def test_openapi_is_public(client): assert client.get("/v1/openapi.json").status_code == 200
def test_tools_requires_bearer(client): r = client.get("/v1/tools"); assert r.status_code == 401 and r.json()["error_code"] == "geen_toegang"
def test_unknown_tool(client, auth): r = client.post("/v1/tools/bestaat_niet", headers=auth, json={}); assert r.status_code == 404 and r.json()["error_code"] == "tool_onbekend"
def test_extra_argument_refused(client, auth, echo_tool): r = client.post("/v1/tools/echo", headers=auth, json={"tekst": "a", "path": "/etc"}); assert r.status_code == 422 and r.json()["error_code"] == "ongeldige_invoer"
def test_no_keys_no_start(monkeypatch): monkeypatch.delenv("OPENBIM_KERN_SLEUTELS", raising=False); pytest.raises(RuntimeError, create_app)
```

`echo_tool` is een fixture die een tool `echo` (invoer `{tekst: str}`, uitvoer `{tekst: str}`) registreert en
na de test weer weghaalt.

- [ ] **Step 2: Run** `cd kern && pip install -e .[test] && pytest tests/test_app.py -v` — Expected: FAIL (module ontbreekt).
- [ ] **Step 3: Implement** pyproject (pakket `openbim-kern`, src-layout, extras `test`: pytest, pytest-httpserver; script `openbim-kern = openbim_kern.cli:app`), `errors.py`, `registry.py`, `app.py`. Validatiefouten van pydantic worden `ongeldige_invoer` (422).
- [ ] **Step 4: Run** `pytest tests/test_app.py -v` — Expected: PASS.
- [ ] **Step 5: Commit** `feat(kern): skelet met het rekenkern-contract`.

### Task 2: Bronnen ophalen en uitvoer afleveren

**Files:**
- Create: `kern/src/openbim_kern/sources.py`
- Test: `kern/tests/test_sources.py`

**Interfaces:**
- Produces:
  - `class Source(BaseModel): url: HttpUrl; sha256: str | None = None; grootte: int | None = None` (`extra="forbid"`).
  - `fetch_source(source: Source, workdir: Path, max_bytes: int) -> Path` — streamt naar een tijdelijk bestand in
    `workdir`, controleert grootte en sha256, en hernoemt pas daarna naar de definitieve naam.
  - `deliver(path: Path, url: str) -> None` — streamt met PUT.
  - Fouten: `KernError("bron_ongeldig", …, status=422)` voor een sha256- of grootteverschil of een afgebroken
    download; `KernError("bron_onbereikbaar", …, status=502)` voor een HTTP-fout; `KernError("bron_te_groot", …, 413)`;
    `KernError("doel_onbereikbaar", …, 502)`.

- [ ] **Step 1: Write the failing tests** (met `pytest-httpserver`)

```python
def test_fetch_checks_sha256(httpserver, tmp_path): ...  # verkeerde sha256 → error_code == "bron_ongeldig" en geen bestand achtergebleven in tmp_path
def test_fetch_truncated_download(httpserver, tmp_path): ...  # Content-Length 100, 50 bytes gestuurd → "bron_ongeldig"
def test_fetch_too_large(httpserver, tmp_path): ...  # max_bytes=10, bestand 11 bytes → "bron_te_groot"
def test_only_http_urls(): pytest.raises(ValidationError, Source, url="file:///etc/passwd")
def test_deliver_puts_bytes(httpserver, tmp_path): ...  # server ontvangt precies de bytes met PUT
```

- [ ] **Step 2: Run** `pytest tests/test_sources.py -v` — Expected: FAIL.
- [ ] **Step 3: Implement** met `httpx.stream`, blokken van 8 MiB, `hashlib.sha256` tijdens het lezen.
- [ ] **Step 4: Run** — Expected: PASS.
- [ ] **Step 5: Commit** `feat(kern): bronnen ophalen en uitvoer afleveren`.

### Task 3: Testmodellen

**Files:**
- Create: `kern/tests/models.py`, `kern/tests/conftest.py`
- Test: `kern/tests/test_models.py`

**Interfaces:**
- Produces (functies in `tests/models.py`, fixtures met dezelfde naam in `conftest.py`, die een `Path` geven):
  - `ifc_small(path) -> Path`: IFC4; project, site, gebouw, verdiepingen `00 begane grond` en `01 eerste verdieping`;
    per verdieping 3 `IfcWall` met `Pset_WallCommon.FireRating = "60"` op de eerste wand; één wand met `IfcOpeningElement`
    en `IfcDoor`; één `IfcSlab`; één `IfcDuctSegment` dat door een wand loopt; materiaal `Beton` op de wanden;
    classificatie NL-SfB `21.12` op de wanden.
  - `ifc_2x3(path) -> Path`: hetzelfde in IFC2X3 (zonder classificatie).
  - `ifc_georef(path) -> Path`: als `ifc_small` met `IfcMapConversion` (Eastings 155000, Northings 463000, OrthogonalHeight 0) en `IfcProjectedCRS` `EPSG:28992`.
  - `ifc_truncated(path) -> Path`: de eerste helft van de bytes van `ifc_small`.

- [ ] **Step 1: Write the failing test**

```python
def test_small_model_contents(ifc_small):
    m = ifcopenshell.open(ifc_small)
    assert m.schema == "IFC4" and len(m.by_type("IfcWall")) == 6 and len(m.by_type("IfcBuildingStorey")) == 2
    assert len({e.GlobalId for e in m.by_type("IfcRoot")}) == len(m.by_type("IfcRoot"))
```

- [ ] **Step 2: Run** `pytest tests/test_models.py -v` — Expected: FAIL.
- [ ] **Step 3: Implement** met `ifcopenshell.api` (`root.create_entity`, `aggregate.assign_object`, `spatial.assign_container`, `geometry.add_wall_representation`, `pset.add_pset`, `material.assign_material`, `classification.*`, `georeference.*`).
- [ ] **Step 4: Run** — Expected: PASS.
- [ ] **Step 5: Commit** `test(kern): testmodellen met IfcOpenShell`.

### Task 4: Eigenschappen-index, ruimtelijke boom en samenvatting

**Files:**
- Create: `kern/src/openbim_kern/index/{__init__,properties,spatial}.py`, `kern/src/openbim_kern/tools/eigenschappen.py`
- Test: `kern/tests/test_index.py`, `kern/tests/test_tool_eigenschappen.py`

**Interfaces:**
- Consumes: `Source`, `fetch_source` (taak 2); `tool` (taak 1).
- Produces:
  - `build_property_index(ifc: Path, db: Path) -> None` — maakt of vult SQLite met de tabellen
    `elements(globalid PRIMARY KEY, ifc_class, name, type_globalid, storey_globalid)`,
    `properties(globalid, set_name, name, value, unit, kind)` met `kind` in `pset|qto`,
    `materials(globalid, material)`, `classifications(globalid, system, code, name)`.
    `INSERT OR IGNORE`, zodat delen van een gesplitst bestand in dezelfde database kunnen.
  - `read_properties(db: Path, globalids: list[str]) -> dict[str, ElementProperties]` met
    `ElementProperties = {klasse, naam, type, verdieping, psets: {set: {naam: waarde}}, hoeveelheden: {set: {naam: waarde}}, materialen: [str], classificaties: [{systeem, code, naam}]}`.
  - `build_spatial_tree(ifc: Path) -> dict` — knooppunten `{globalid, klasse, naam, kinderen: [...]}`, alleen de
    werkelijke decompositie (`IfcRelAggregates`) en containment.
  - `build_summary(ifc: Path) -> dict` — `{schema, lengte_eenheid, georeferentie: {eastings, northings, orthogonal_height, x_axis_abscissa, x_axis_ordinate, scale, crs} | None, begrenzing: {min: [x,y,z], max: [x,y,z]} | None, aantallen_per_klasse: {klasse: n}, aantallen_per_verdieping: {globalid: n}}`.
  - Tool `eigenschappen` (niet lang): invoer `{index: Source, globalids: list[str] (1..1000)}`, uitvoer
    `{elementen: dict[str, ElementProperties]}`; de index-database wordt in de werkmap gecachet op `sha256`.

- [ ] **Step 1: Write the failing tests**

```python
def test_index_small(ifc_small, tmp_path):
    build_property_index(ifc_small, tmp_path / "e.sqlite")
    wall = first_wall_globalid(ifc_small)
    p = read_properties(tmp_path / "e.sqlite", [wall])[wall]
    assert p["klasse"] == "IfcWall" and p["psets"]["Pset_WallCommon"]["FireRating"] == "60"
    assert p["materialen"] == ["Beton"] and p["classificaties"][0]["code"] == "21.12"
def test_index_2x3(ifc_2x3, tmp_path): ...  # zelfde wand, FireRating "60", geen classificaties
def test_index_is_per_source(ifc_small, tmp_path): ...  # twee aparte databases van hetzelfde bestand geven elk hun eigen rij; read_properties leest alleen de eigen db
def test_summary_georef(ifc_georef): s = build_summary(ifc_georef); assert s["georeferentie"]["eastings"] == 155000 and s["georeferentie"]["crs"] == "EPSG:28992"
def test_summary_counts(ifc_small): s = build_summary(ifc_small); assert s["aantallen_per_klasse"]["IfcWall"] == 6 and len(s["aantallen_per_verdieping"]) == 2
def test_spatial_tree(ifc_small): t = build_spatial_tree(ifc_small); assert t["klasse"] == "IfcProject" and depth_of_storeys(t) == 3
def test_tool_eigenschappen_http(client, auth, httpserver, index_db): ...  # POST /v1/tools/eigenschappen met een index-URL geeft FireRating "60"
```

- [ ] **Step 2: Run** `pytest tests/test_index.py tests/test_tool_eigenschappen.py -v` — Expected: FAIL.
- [ ] **Step 3: Implement** met `ifcopenshell.util.element` (`get_psets`, `get_type`, `get_container`, `get_material`) en `ifcopenshell.util.classification`. `begrenzing` komt uit de placements (geen geometrie-iterator: die is te duur voor bestanden van GB's) en mag `None` zijn.
- [ ] **Step 4: Run** — Expected: PASS.
- [ ] **Step 5: Commit** `feat(kern): eigenschappen-index en samenvatting`.

### Task 5: Node-omzetter met bewaking

**Files:**
- Create: `kern/converter/{package.json,package-lock.json,convert.mjs}`, `kern/src/openbim_kern/converter.py`
- Test: `kern/tests/test_converter.py`

**Interfaces:**
- Produces:
  - `convert.mjs frag <in.ifc> <out.frag>`: `FRAGS.IfcImporter` met `wasm = {path: <node_modules/web-ifc/>, absolute: true}`,
    `readFromCallback` met blokken van 1 MiB, standaardeigenschappen; schrijft één JSON-regel naar stdout:
    `{"in_bytes", "out_bytes", "sec"}`. Exitcode 0 bij succes.
  - `convert.mjs split <in.ifc> <n> <outdir>`: `FRAGS.IfcSplitter` met een `IfcSplitterIO` over `node:fs`; schrijft
    `deel-<i>.ifc` (i vanaf 1) en één JSON-regel `{"delen": ["deel-1.ifc", …]}`.
  - `@dataclass ConvertStats: in_bytes: int; out_bytes: int; seconds: float; peak_rss: int; attempts: int`.
  - `convert_to_frag(ifc: Path, out: Path) -> ConvertStats`.
  - `split_ifc(ifc: Path, parts: int, outdir: Path) -> list[Path]`.
  - Beide starten Node als subproces (`OPENBIM_OMZETTER_CMD`, standaard `node <kern/converter/convert.mjs>`), meten
    de RSS van de procesboom met psutil elke seconde, en stoppen het proces boven de geheugengrens of na de
    tijdslimiet (Global Constraints). Fouten: `KernError("omzetten_te_veel_geheugen")`, `("omzetten_tijd_op")`,
    `("omzetten_mislukt")` met de laatste regel van stderr in `melding`. Herhalen alleen als stderr
    `WebAssembly.Exception` bevat.

- [ ] **Step 1: Write the failing tests**

```python
def test_convert_small(ifc_small, tmp_path): s = convert_to_frag(ifc_small, tmp_path / "m.frag"); assert s.out_bytes > 0 and (tmp_path / "m.frag").stat().st_size == s.out_bytes
def test_truncated_ifc_fails_cleanly(ifc_truncated, tmp_path): e = pytest.raises(KernError, convert_to_frag, ifc_truncated, tmp_path / "m.frag").value; assert e.error_code == "omzetten_mislukt"
def test_retries_wasm_exception(fake_converter, ifc_small, tmp_path): ...  # nep-omzetter die de eerste keer "WebAssembly.Exception" op stderr zet → attempts == 2
def test_no_retry_other_error(fake_converter, ...): ...  # andere fout → attempts == 1, "omzetten_mislukt"
def test_memory_limit(fake_converter, monkeypatch, ...): ...  # nep-omzetter die geheugen vasthoudt, grens verlaagd via OPENBIM_GEHEUGEN_GRENS_BYTES → "omzetten_te_veel_geheugen"
def test_split(ifc_small, tmp_path): parts = split_ifc(ifc_small, 2, tmp_path); assert len(parts) == 2 and all(ifcopenshell.open(p).by_type("IfcProject") for p in parts)
```

`fake_converter` is een fixture die `OPENBIM_OMZETTER_CMD` naar een klein Python-script in `tests/` zet.

- [ ] **Step 2: Run** `cd kern/converter && npm ci && cd .. && pytest tests/test_converter.py -v` — Expected: FAIL.
- [ ] **Step 3: Implement** `convert.mjs` (de signatuur van `IfcSplitterIO` staat in `node_modules/@thatopen/fragments/dist/index.d.ts`) en `converter.py`.
- [ ] **Step 4: Run** — Expected: PASS.
- [ ] **Step 5: Commit** `feat(kern): omzetter naar fragments met bewaking`.

### Task 6: De tool `omzetten`

**Files:**
- Create: `kern/src/openbim_kern/tools/omzetten.py`
- Test: `kern/tests/test_tool_omzetten.py`

**Interfaces:**
- Consumes: taken 2, 4 en 5.
- Produces:
  - Invoer `OmzetVerzoek {bron: Source, doelen: dict[str, HttpUrl]}`. Verplichte sleutels in `doelen`: `index.json`,
    `eigenschappen.sqlite`, `ruimtelijk.json`, en `model.frag` (niet gesplitst) of `deel-1.frag` … `deel-<n>.frag`
    (gesplitst). Ontbreekt er een, dan `KernError("doel_ontbreekt", 422)` vóór het werk begint, als de grootte uit
    `bron.grootte` bekend is, en anders na het ophalen; meer delen nodig dan er doelen zijn: `"te_veel_delen"`.
  - Uitvoer `OmzetUitkomst {omzetter: str, delen: [{naam, bytes, verdiepingen: [globalid]}], duur_s: float, piek_geheugen: int}`.
  - `index.json` = `build_summary(...)` plus `{"omzetter", "delen"}`.
  - Gesplitst: per deel `convert_to_frag` en `build_property_index` in dezelfde database; `build_summary` en
    `build_spatial_tree` op het eerste deel (de splitser geeft elk deel de ruimtelijke structuur mee), aantallen
    opgeteld over de delen.
  - Geregistreerd als `@tool("omzetten", …, lang=True, rij="omzetten")`; de functie neemt een extra parameter
    `progress: Callable[[float], None]` (taak 7 geeft die door).

- [ ] **Step 1: Write the failing tests** (met `pytest-httpserver` als bron en doel)

```python
def test_omzetten_small(httpserver, ifc_small, tmp_path):
    out = run_omzetten(httpserver, ifc_small, ["index.json", "eigenschappen.sqlite", "ruimtelijk.json", "model.frag"])
    assert [d["naam"] for d in out["delen"]] == ["model.frag"] and received(httpserver, "model.frag") > 0
    assert json.loads(received_bytes(httpserver, "index.json"))["omzetter"] == CONVERTER_VERSION
def test_omzetten_splits(monkeypatch, httpserver, ifc_small): monkeypatch.setenv("OPENBIM_SPLITS_VANAF_BYTES", "1"); ...  # met deel-1..deel-n doelen → len(delen) >= 1 en elk deel ontvangen; eigenschappen van een wand uit elk deel te lezen
def test_missing_target(httpserver, ifc_small): ...  # zonder "ruimtelijk.json" → "doel_ontbreekt"
```

- [ ] **Step 2: Run** `pytest tests/test_tool_omzetten.py -v` — Expected: FAIL.
- [ ] **Step 3: Implement** in een werkmap per aanroep (`tempfile.TemporaryDirectory` onder `OPENBIM_KERN_DATA/werk/`), die altijd wordt opgeruimd.
- [ ] **Step 4: Run** — Expected: PASS.
- [ ] **Step 5: Commit** `feat(kern): tool omzetten met splitsen`.

### Task 7: Lange taken: wachtrij en werker

**Files:**
- Create: `kern/src/openbim_kern/jobs/{__init__,store,worker}.py`
- Modify: `kern/src/openbim_kern/app.py` (routes voor lange tools en `/v1/taken`)
- Test: `kern/tests/test_jobs.py`

**Interfaces:**
- Consumes: `REGISTRY` (taak 1).
- Produces:
  - `JobStore(db: Path)` met `submit(tool: str, invoer: dict, klantsite: str) -> str`, `get(job_id) -> Job`,
    `cancel(job_id) -> None`, `claim(queue: str, max_running: int, max_per_site: int) -> Job | None`,
    `set_progress(job_id, value: float)`, `finish(job_id, uitkomst: dict)`, `fail(job_id, error: dict)`,
    `requeue_running() -> int`.
  - `Job {taak, tool, status: "wacht"|"bezig"|"klaar"|"fout"|"afgebroken", voortgang: float, uitkomst: dict | None, fout: dict | None, klantsite: str, gemaakt, gestart, klaar}`.
  - `run_worker(store: JobStore, queues: dict[str, int], max_per_site: int = 2, once: bool = False) -> None`; voert elke
    taak uit in een eigen proces (`multiprocessing`, `spawn`); een afgebroken taak wordt binnen 5 s gestopt.
  - HTTP: `POST /v1/tools/{naam}` voor een lange tool → `202 {"taak": id}`; `GET /v1/taken/{taak}` → `Job` als JSON;
    `DELETE /v1/taken/{taak}` → `{"status": "afgebroken"}`. De klantsite komt uit de kop `X-OpenAEC-Klantsite`
    (standaard `lokaal`). Meer dan 100 wachtende taken voor een klantsite → `503` met `Retry-After: 30` en
    `error_code: "te_druk"`.
  - Rijen en gelijktijdigheid uit de omgeving: `OPENBIM_RIJ_OMZETTEN` (standaard 1), `OPENBIM_RIJ_LICHT` (standaard 4).

- [ ] **Step 1: Write the failing tests**

```python
def test_long_tool_returns_202(client, auth, slow_tool): r = client.post("/v1/tools/traag", headers=auth, json={}); assert r.status_code == 202 and "taak" in r.json()
def test_worker_runs_job(store, slow_tool): ...  # submit, run_worker(once=True) → status "klaar", uitkomst gezet, voortgang 1.0
def test_failure_is_json(store, failing_tool): ...  # KernError in de tool → status "fout", fout["error_code"] == de code
def test_restart_requeues(store): ...  # taak op "bezig" zetten, requeue_running() == 1, status weer "wacht"
def test_per_site_limit(store): ...  # 3 taken van site a, max_per_site=2 → claim geeft de derde pas na finish
def test_queue_full(client, auth, slow_tool): ...  # 101e taak voor dezelfde site → 503, Retry-After 30, "te_druk"
def test_cancel(store, slow_tool): ...  # cancel tijdens bezig → status "afgebroken" binnen 5 s
```

- [ ] **Step 2: Run** `pytest tests/test_jobs.py -v` — Expected: FAIL.
- [ ] **Step 3: Implement** met `sqlite3` (WAL, één tabel `jobs`); `claim` in één transactie (`BEGIN IMMEDIATE`).
- [ ] **Step 4: Run** — Expected: PASS.
- [ ] **Step 5: Commit** `feat(kern): lange taken met wachtrij en werker`.

### Task 8: MCP en CLI uit dezelfde tools

**Files:**
- Create: `kern/src/openbim_kern/{mcp_server,cli}.py`
- Modify: `kern/src/openbim_kern/app.py` (koppel `/mcp`)
- Test: `kern/tests/test_mcp_cli.py`

**Interfaces:**
- Consumes: `REGISTRY`, `JobStore`, `create_app`.
- Produces:
  - `POST /mcp` (Streamable HTTP, antwoorden als JSON) met per niet-lange tool een MCP-tool met hetzelfde schema; een
    lange tool geeft via MCP `{taak}` terug, plus een MCP-tool `taak_stand(taak)`. SDK `mcp>=1.10,<2`.
  - CLI `openbim-kern`: `serve [--poort 8730]`, `werker`, `lokaal <map> [--poort 8740]` (taak 9),
    `omzetten <ifc> <uitmap>` (lokaal gebruik: leest en schrijft schijf; staat niet in `/v1/tools`).

- [ ] **Step 1: Write the failing tests**

```python
def test_same_result_http_and_mcp(client, auth, index_server): assert http_eigenschappen(...) == mcp_eigenschappen(...)
def test_mcp_lists_tools(client, auth): assert {"eigenschappen", "omzetten", "taak_stand"} <= mcp_tool_names(client, auth)
def test_cli_omzetten(ifc_small, tmp_path): CliRunner().invoke(app, ["omzetten", str(ifc_small), str(tmp_path)]); assert (tmp_path / "model.frag").exists() and (tmp_path / "index.json").exists()
```

- [ ] **Step 2: Run** `pytest tests/test_mcp_cli.py -v` — Expected: FAIL.
- [ ] **Step 3: Implement**; de CLI-opdracht `omzetten` roept dezelfde interne functies aan als de tool (`convert_to_frag`, `split_ifc`, `build_property_index`, `build_summary`, `build_spatial_tree`), op lokale paden: geen tweede rekenweg.
- [ ] **Step 4: Run** — Expected: PASS.
- [ ] **Step 5: Commit** `feat(kern): MCP en CLI`.

### Task 9: Lokale ontwikkelserver

**Files:**
- Create: `kern/src/openbim_kern/local/{__init__,server}.py`
- Test: `kern/tests/test_local_server.py`

**Interfaces:**
- Consumes: `create_app`, `JobStore`, `run_worker` (in-process thread voor lokaal gebruik), tool `omzetten`.
- Produces (`create_local_app(root: Path, kern_url: str, kern_key: str) -> FastAPI`; geen auth, alleen op `127.0.0.1`):
  - `GET /lokaal/project` → `{project: <naam van de map>, werkwijze: "bestanden", modellen: [{bron: {soort: "bestand", sleutel: <relatief pad>, versie: <sha256[:12]>}, naam, discipline: <naam van de submap of "">, status: "wacht"|"bezig"|"klaar"|"fout", delen: [{naam, bytes}], index: <index.json> | null}]}`.
  - `GET /lokaal/bestanden/{pad}` en `PUT /lokaal/bestanden/{pad}`: alleen binnen `root` (na `resolve()`), `..` of
    absolute paden → 400 `ongeldig_pad`. Afgeleide gegevens onder `root/.afgeleid/<sleutel>/<versie>/<omzetter>/`.
  - `POST /lokaal/omzetten` → zet voor elk model zonder afgeleide gegevens een `omzetten`-taak klaar, met
    `http://127.0.0.1:<poort>/lokaal/bestanden/…` als bron en doelen.
  - `POST /lokaal/eigenschappen {bron, globalids}` → roept de tool `eigenschappen` aan met de index van die bron.
  - CORS alleen voor `http://localhost:5173` en `http://127.0.0.1:5173` (Vite).

- [ ] **Step 1: Write the failing tests**

```python
def test_project_lists_models(local_client, tmp_path, ifc_small): ...  # map met "Constructie/wand model.ifc" → één model, discipline "Constructie", status "wacht"
def test_unicode_and_spaces(local_client, ...): ...  # "Installaties/kanaal één.ifc" te downloaden via GET met de URL-gecodeerde naam
def test_dotdot_refused(local_client): assert local_client.get("/lokaal/bestanden/..%2F..%2Fgeheim").status_code == 400
def test_convert_then_ready(local_client, ...): ...  # POST /lokaal/omzetten, werker draaien → status "klaar", delen[0].naam == "model.frag"
def test_new_version_detected(local_client, ...): ...  # bestand wijzigen → nieuwe versie, status "wacht"; afgeleide gegevens van de oude versie blijven bestaan
```

- [ ] **Step 2: Run** `pytest tests/test_local_server.py -v` — Expected: FAIL.
- [ ] **Step 3: Implement**; de sha256 per bestand wordt gecachet op `(pad, mtime, grootte)`.
- [ ] **Step 4: Run** — Expected: PASS.
- [ ] **Step 5: Commit** `feat(kern): lokale ontwikkelserver`.

### Task 10: Container en CI

**Files:**
- Create: `kern/Dockerfile`, `kern/compose.yaml`, `.github/workflows/ci.yml`
- Modify: `README.md` (sectie "Ontwikkelen": lokaal starten, tests)

**Interfaces:**
- Produces: image met Python 3.12 en Node 24, `npm ci` in `converter/`, gebruiker `openbim` (uid 10001),
  `HEALTHCHECK` op `/v1/health`, standaardopdracht `openbim-kern serve`. `compose.yaml` met diensten `kern` en
  `werker` uit dezelfde image en een gedeeld volume op `OPENBIM_KERN_DATA=/data`. CI: kern (Node 24 + `npm ci` in
  `converter/`, pytest, ruff) en image bouwen; taak 11 voegt de viewer toe (vitest, build, `check:geen-cdn`) en
  taak 13 de Playwright-proef.

- [ ] **Step 1: Run** `docker build -t openbim-kern kern && docker run --rm -e OPENBIM_KERN_SLEUTELS=x -p 8730:8730 openbim-kern` en `curl -s localhost:8730/v1/health` — Expected: `{"status":"ok",…}`; `docker run --rm openbim-kern` zonder sleutels stopt met een melding.
- [ ] **Step 2: Run** `docker run --rm openbim-kern id -u` — Expected: `10001`.
- [ ] **Step 3: Commit** `build(kern): container en CI`.

### Task 11: Viewer-skelet met host-laag

**Files:**
- Create: `viewer/{package.json,vite.config.ts,tsconfig.json,index.html}`, `viewer/src/host/{BimHost,LocalHost}.ts`, `viewer/src/engine/FragmentsEngine.ts`, `viewer/src/ui/App.tsx`, `viewer/src/main.tsx`
- Test: `viewer/src/host/LocalHost.test.ts`

**Interfaces:**
- Consumes: de lokale server (taak 9).
- Produces:
  - `ModelSource = { soort: "bestand"; sleutel: string; versie: string }`; `sourceKey(s: ModelSource): string` = `${soort}:${sleutel}@${versie}`.
  - `ModelInfo = { bron: ModelSource; naam: string; discipline: string; status: "wacht" | "bezig" | "klaar" | "fout"; delen: { naam: string; bytes: number }[]; index: ModelIndex | null }`.
  - `interface BimHost { project(): Promise<{ project: string; werkwijze: string; modellen: ModelInfo[] }>; laad(bron: ModelSource, deel: string): Promise<ArrayBuffer>; eigenschappen(bron: ModelSource, globalids: string[]): Promise<Record<string, ElementProperties>>; }`
  - `class LocalHost implements BimHost` (`constructor(baseUrl = "http://127.0.0.1:8740")`).
  - `class FragmentsEngine { constructor(container: HTMLElement); load(key: string, bytes: ArrayBuffer): Promise<void>; unload(key: string): Promise<void>; dispose(): void }` — `OBC.Components`, `SimpleWorld`, `FragmentsManager`, met de worker uit de bundel (`import workerUrl from "@thatopen/fragments/worker?url"` of het pad in `dist/Worker/`, zie het pakket).
  - Huisstijl: `@openaec/design-tokens`, `@openaec/shell`, `@openaec/icons`, `@openaec/i18n` (NL/EN), volledig; geen eigen kleuren of lettertypen.

- [ ] **Step 1: Write the failing test**

```ts
test("LocalHost.project calls /lokaal/project", async () => { fetchMock(...); expect((await new LocalHost("http://x").project()).modellen).toHaveLength(1); });
test("LocalHost.laad returns bytes of the part", async () => { ... expect(new Uint8Array(buf)[0]).toBe(1); });
test("sourceKey includes version", () => expect(sourceKey({ soort: "bestand", sleutel: "a.ifc", versie: "abc" })).toBe("bestand:a.ifc@abc"));
```

- [ ] **Step 2: Run** `cd viewer && npm ci && npx vitest run` — Expected: FAIL.
- [ ] **Step 3: Implement**; `npm run build` mag geen verwijzing naar `unpkg.com` of `thatopen.github.io` in `dist/` bevatten (controle in `package.json` als script `check:geen-cdn`).
- [ ] **Step 4: Run** `npx vitest run && npm run build && npm run check:geen-cdn` — Expected: PASS.
- [ ] **Step 5: Commit** `feat(viewer): skelet met host-laag en That Open`.

### Task 12: Laden binnen het geheugenbudget, modellijst en eigenschappen

**Files:**
- Create: `viewer/src/model/{budget,selection}.ts`, `viewer/src/ui/{ModelList,PropertiesPanel}.tsx`
- Modify: `viewer/src/ui/App.tsx`
- Test: `viewer/src/model/budget.test.ts`, `viewer/src/model/selection.test.ts`

**Interfaces:**
- Consumes: `BimHost`, `FragmentsEngine`, `sourceKey` (taak 11).
- Produces:
  - `estimateBytes(m: ModelInfo): number` = `18 × som van delen[].bytes`.
  - `planLoad(models: ModelInfo[], budgetBytes: number): { load: ModelInfo[]; available: ModelInfo[] }` — alleen
    modellen met status `klaar`; volgorde zoals aangeleverd; een model dat niet meer in het budget past, en alle
    volgende, gaan naar `available`; het eerste model wordt altijd geladen, ook als het alleen al boven het budget
    zit.
  - `DEFAULT_BUDGET = 2 * 1024 ** 3`.
  - `Selection = { bron: ModelSource; globalid: string }`; `selectionKey(s) = sourceKey(s.bron) + "#" + s.globalid`.
  - `ModelList`: per model naam, discipline, status (met "wordt omgezet" en de versie), een schakelaar laden/uit en de
    geschatte geheugenpost; bovenaan het totaal tegenover het budget.
  - `PropertiesPanel`: bij een selectie `host.eigenschappen(bron, [globalid])`, gegroepeerd per pset, met
    hoeveelheden, materialen en classificaties.

- [ ] **Step 1: Write the failing tests**

```ts
test("loads in order until budget", () => expect(planLoad([m(100e6), m(10e6), m(20e6)], DEFAULT_BUDGET).load).toHaveLength(2)); // 1,8e9 + 0,18e9 past, + 0,36e9 niet
test("first model always loads", () => expect(planLoad([m(500e6)], 1).load).toHaveLength(1));
test("skips models not ready", () => expect(planLoad([m(1e6, "bezig")], DEFAULT_BUDGET).load).toHaveLength(0));
test("selection keys include source", () => expect(selectionKey(selA)).not.toBe(selectionKey(selB))); // zelfde globalid, andere bron
```

- [ ] **Step 2: Run** `npx vitest run src/model` — Expected: FAIL.
- [ ] **Step 3: Implement**; de app laadt bij het starten `planLoad(..., DEFAULT_BUDGET).load` met `host.laad` per deel, en een klik in 3D wordt via `FragmentsEngine` een `Selection`.
- [ ] **Step 4: Run** `npx vitest run` — Expected: PASS.
- [ ] **Step 5: Commit** `feat(viewer): laden binnen budget, modellijst en eigenschappen`.

### Task 13: Browserproef

**Files:**
- Create: `viewer/e2e/smoke.spec.ts`, `viewer/playwright.config.ts`
- Test: deze proef

**Interfaces:**
- Consumes: CLI `openbim-kern lokaal` (taak 8/9), de viewer (taak 12).
- Produces: een proef die een map met twee testmodellen (gemaakt met `python -m tests.models <map>`, een kleine
  hoofdfunctie in `kern/tests/models.py`) omzet via `POST /lokaal/omzetten`, wacht tot beide `klaar` zijn, de viewer
  opent en controleert dat de modellijst twee geladen modellen toont, dat er een `canvas` is en dat de console geen
  fouten heeft. Het paneel met eigenschappen wordt geopend via een testingang `window.__openbimSelect(selection)`, die
  alleen in de ontwikkelbouw bestaat; het paneel toont `FireRating` `60`.

- [ ] **Step 1: Write the test** als hierboven.
- [ ] **Step 2: Run** `npx playwright test` — Expected: FAIL tot de testingang er is; daarna PASS.
- [ ] **Step 3: Commit** `test(viewer): browserproef met de lokale server`.

### Task 14: Meten op grote bestanden en acceptatie

**Files:**
- Create: `kern/scripts/{enlarge,measure}.py`, `docs/metingen/2026-fase-0.md` (uitkomst van de acceptatie)
- Test: `kern/tests/test_scripts.py`

**Interfaces:**
- Produces:
  - `python scripts/enlarge.py <in.ifc> <factor> <out.ifc>`: herhaalt de bouwelementen en hun geometrie `factor`
    keer in één geldig IFC (één `IfcProject`, unieke GlobalIds, unieke ids), gestreamd (niet het hele bestand in het
    geheugen).
  - `python scripts/measure.py <map> --uit <rapport.md>`: zet elk IFC in de map om via de lokale route en schrijft een
    tabel `bestand | MB IFC | MB .frag | s | piekgeheugen | delen`, plus totalen en de geschatte browserpost.

- [ ] **Step 1: Write the failing test**

```python
def test_enlarge_valid(ifc_small, tmp_path):
    enlarge(ifc_small, 3, tmp_path / "g.ifc"); m = ifcopenshell.open(tmp_path / "g.ifc")
    assert len(m.by_type("IfcProject")) == 1 and len(m.by_type("IfcWall")) == 18
    assert len({e.GlobalId for e in m.by_type("IfcRoot")}) == len(m.by_type("IfcRoot"))
```

- [ ] **Step 2: Run** `pytest tests/test_scripts.py -v` — Expected: FAIL, daarna implementeren — Expected: PASS.
- [ ] **Step 3: Acceptatie** (handmatig, niet in CI): een map met tien IFC-bestanden van samen ≥ 5 GB (eigen open
  modellen of `enlarge.py`, waarvan minstens één boven 1,5 GB zodat splitsen meedoet), `measure.py`, daarna de viewer
  openen op een laptop met 16 GB geheugen en een ingebouwde GPU. Expected: alle bestanden `klaar`; de viewer laadt
  tot het budget, de rest staat klaar om aan te zetten; uitkomsten in `docs/metingen/2026-fase-0.md`, met de tijd en
  het piekgeheugen van IfcOpenShell voor de eigenschappen-index (nodig voor het kostenplan, ontwerp hoofdstuk 10).
- [ ] **Step 4: Commit** `docs(metingen): acceptatie fase 0`.

---

## Buiten dit plan (volgende plannen)

Fase 1: `openaec_bim` (Frappe), gastpagina en `bim.*`-berichten, host `werkplek` in de viewer, rechten via Storage,
issues en BCF, botsingen (`ifcclash`), doorsneden, meten, release-assets volgens het SuperCloud-contract, en de
geometrievergelijking tussen web-ifc en IfcOpenShell (ontwerp hoofdstuk 11).
