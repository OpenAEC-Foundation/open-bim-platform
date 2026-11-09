# Fase 1b: coördinatie — implementatieplan

> **Voor agents:** VERPLICHTE SUB-SKILL: gebruik superpowers:subagent-driven-development (aanbevolen) of
> superpowers:executing-plans om dit plan taak voor taak uit te voeren. Stappen gebruiken `- [ ]` om af te vinken.

**Doel:** issues met BCF 3.0 als datamodel, direct gevolgd door de BCF-API 3.0, een koppeling van elementen over versies
heen (op GlobalId, met een terugval en een matchrate), een auditlog en botsingscontrole, zodat een coördinator en een
externe partij in de werkplek samen aan issues en botsingen werken die een nieuwe modelversie overleven.

**Architectuur:** de kern krijgt drie dingen die IfcOpenShell nodig hebben: een identiteitstabel in de index, de tool
`koppelen` (versiekoppeling) en de tool `botsingen` (op `ifcopenshell.geom.tree`). De platform-app `openaec_bim` bewaart
issues, standpunten, reacties, botsingsrondes en het auditlog, leest en schrijft `.bcfzip`, en biedt twee ingangen op
dezelfde domeinfuncties: de `bim.*`-berichten van de gastpagina en de BCF-API op `/bcf/3.0`. De viewer krijgt panelen
voor issues en botsingen via een optionele `Coordinatie` op de host.

**Techniek:** Python 3.12 (kern, FastAPI, pydantic, IfcOpenShell 0.8.4), Frappe v16 (`openaec_bim`, `openaec_storage`),
React 18 + TypeScript + That Open (viewer), de werkplek-gastpagina in `openaec-bench` (branch `bouw/bim-werkplek`).

**Ontwerp:** `docs/superpowers/specs/2026-10-26-open-bim-platform-design.md`, hoofdstukken 5.3 (identiteit over versies),
5.6 (`openaec_bim`, BCF, BCF-API, botsingen volgen, auditlog), 8 (punten 5–10) en 9 (fase 1).

**Buiten dit plan (fase 1c):** doorsneden en meten in de viewer, momentopnames, release-assets. De lokale route
(`openbim-kern lokaal`) krijgt geen issues of botsingen; de viewer verbergt die panelen als de host ze niet aanbiedt.

## Globale eisen

- Nergens in de repo namen van commerciële rekensoftware of concurrerende producten, en geen verwijzingen naar gesprekken
  (commitberichten, code, tests, fixtures, documentatie).
- Rechten alleen via Storage: `openaec_storage.rechten.vereis_op_plek(ruimte, map, actie, bestand)`; geen eigen
  rechtenmodel. Leesrecht op de modelmap is genoeg om issues en reacties te lezen en te maken; een issue wijzigen of
  verwijderen mag de maker, wie het toegewezen is, of wie schrijfrecht op de modelmap heeft.
- Het project is de modelmap: `BIM Project.name` = de id van de `Opslagmap`.
- BCF 3.0 is het datamodel; import en export als `.bcfzip` in BCF 2.1 en 3.0, zonder plafond op het aantal topics.
- BCF-API 3.0 op `/bcf/3.0`, Foundation API 1.1 volgens de specificatie van buildingSMART (paden en velden uit de
  specificatie overnemen en vastpinnen in de conformiteitstest van taak 11).
- Versiekoppeling: plaatsing afgerond op 1 mm (in meters), drempel van de matchrate `KOPPEL_DREMPEL = 0.9`.
- Auditlog: alleen toevoegen; elke regel met `gebruiker`, `tijd`, `handeling`, `voor`, `na`, `bron` (`gastpagina`,
  `bcf-api` of `achtergrond`).
- Standpunten: schermafbeelding PNG of JPEG, hoogstens 5 MB; een standpunt zonder schermafbeelding mag.
- Kern: pydantic-invoer met `extra="forbid"`, tools met `@tool`, werk dat langer dan seconden duurt als `lang=True`; de
  nieuwe rij `botsing` met `OPENBIM_RIJ_BOTSING` (standaard 1).
- Frappe-app: tabs voor inspringen, DocTypes met het voorvoegsel `BIM `, API-namen in het Nederlands.
- Viewer: alle teksten via i18n (`nl.json` en `en.json`), geen CDN, de huisstijl uit `viewer/vendor/`.
- Commitberichten in het Nederlands, eindigend met `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

**Testopdrachten** (gebruikt in de taken):

- Kern: `cd kern && .venv/Scripts/python.exe -m pytest <test> -v` (Linux: `.venv/bin/python`).
- Frappe: in `openaec-bench-bim`:
  `docker compose -f compose.yaml -f compose.bim.yaml exec -T bench bash -lc 'cd ~/benches/frappe-bench && bench --site klant0.cloud.open-aec.localhost run-tests --module <module>'`
  (hierna `FRAPPE-TEST <module>`).
- Viewer: `cd viewer && npx vitest run <bestand>` en `npx tsc --noEmit`.
- Gastpagina: in `openaec-bench-bim`: `bash scripts/build-frontend.sh test apps/werkplek`.

## Aandachtspunten voor de review

1. **Gelijktijdig wijzigen:** de viewer en een BCF-programma wijzigen hetzelfde issue. Verwacht: wie met een verouderde
   `modified_date` schrijft, krijgt 409 en niets wordt overschreven (test in taak 5).
2. **Import met onbekende waarden:** een `.bcfzip` met statussen, soorten of labels die het project niet kent. Verwacht:
   de import slaagt, de waarden komen bij de projectinstellingen en dat staat in het auditlog (test in taak 6).
3. **Dubbele sleutels bij de terugval:** veel gelijke elementen op dezelfde plek (een gekopieerde verdieping). Verwacht:
   die worden niet gekoppeld in plaats van verkeerd gekoppeld; de matchrate daalt (test in taak 2).
4. **Een nieuwe versie tijdens een botsingsronde:** de ronde rekent op de versies van het begin en bewaart die; een
   volgende ronde volgt de botsingen via de koppeling (test in taak 8).
5. **Een ingetrokken deling:** een externe partij verliest toegang tot de modelmap. Verwacht: 403 in de gastpagina én in
   de BCF-API, ook met een geldig OAuth-token (tests in taak 9 en 10).

---

### Taak 1: Identiteitstabel in de index

**Bestanden:**
- Maak: `kern/src/openbim_kern/index/identity.py`
- Wijzig: `kern/src/openbim_kern/index/properties.py` (`SCHEMA`, `index_model`)
- Test: `kern/tests/test_identity.py`

**Interfaces:**
- Levert: tabel `identiteit (globalid TEXT PRIMARY KEY, ifc_class TEXT, type_name TEXT, name TEXT, storey_name TEXT,
  x REAL, y REAL, z REAL)` in `eigenschappen.sqlite`, voor elk `IfcProduct` met een `ObjectPlacement`, coördinaten in
  meters afgerond op 0,001; `index_identity(model: ifcopenshell.file, con: sqlite3.Connection) -> None`.

- [ ] **Stap 1: Schrijf de falende tests**

```python
def test_identity_has_placement_in_metres(ifc_small, tmp_path):
    build_property_index(ifc_small, tmp_path / "e.sqlite")
    rows = identity_rows(tmp_path / "e.sqlite")  # hulpje in de test: SELECT * FROM identiteit
    wall = rows[first_wall_globalid(ifc_small)]
    assert wall["ifc_class"] == "IfcWall" and wall["storey_name"] == "00 begane grond"
    assert all(round(v, 3) == v for v in (wall["x"], wall["y"], wall["z"]))

def test_identity_uses_metres_for_a_millimetre_model(tmp_path):
    # hetzelfde model met lengte-eenheid millimeter: dezelfde coördinaten in meters
    ...
    assert rows_mm[gid]["x"] == rows_m[gid]["x"]

def test_identity_names_the_type(tmp_path):
    # een wand met een IfcWallType "Binnenwand 100" (zoals test_index_types)
    assert rows[wall.GlobalId]["type_name"] == "Binnenwand 100"
```

- [ ] **Stap 2: Draai de tests:** `pytest tests/test_identity.py -v` — verwacht: FAIL (`no such table: identiteit`).
- [ ] **Stap 3: Implementeer `index_identity` in `identity.py`** met `ifcopenshell.util.placement.get_local_placement`
  (kolom 3 van de matrix) maal `ifcopenshell.util.unit.calculate_unit_scale(model)`, `element_util.get_type` voor de
  typenaam en de naam van de verdieping uit `_storey`; aanroepen vanuit `index_model`, `INSERT OR IGNORE` zoals de andere
  tabellen (delen van een gesplitst bestand vullen één index).
- [ ] **Stap 4: Draai de tests** en `pytest tests/test_index.py` — verwacht: PASS.
- [ ] **Stap 5: Commit** `feat(kern): identiteitstabel in de index voor de versiekoppeling`.

### Taak 2: Versiekoppeling en de tool `koppelen`

**Bestanden:**
- Maak: `kern/src/openbim_kern/linking.py`, `kern/src/openbim_kern/tools/koppelen.py`
- Wijzig: `kern/src/openbim_kern/tools/__init__.py` (registratie)
- Test: `kern/tests/test_linking.py`

**Interfaces:**
- Gebruikt: tabel `identiteit` (taak 1).
- Levert: `link_versions(old_db: Path, new_db: Path) -> Koppeling` en tool `koppelen` (`lang=True`, rij `licht`) met
  invoer `KoppelIn {vorige: Source, nieuwe: Source}` (de `eigenschappen.sqlite` van beide versies) en uitvoer
  `Koppeling {elementen_vorige: int, op_globalid: int, terugval: list[Paar], niet_gevonden: list[str], matchrate: float}`,
  `Paar {van: str, naar: str}`.

- [ ] **Stap 1: Schrijf de falende tests** (twee indexen maken met `index_model` op aangepaste kopieën van `ifc_small`)

```python
def test_same_model_matches_on_globalid(...):
    k = link_versions(db_a, db_a_copy)
    assert k.matchrate == 1.0 and k.op_globalid == k.elementen_vorige and k.terugval == []

def test_new_globalids_are_found_back_by_their_identity(...):
    # v2: dezelfde elementen, alle GlobalIds van de wanden nieuw
    k = link_versions(db_v1, db_v2)
    assert {p.van for p in k.terugval} == old_wall_gids and k.matchrate == 1.0

def test_a_moved_element_with_a_unique_name_is_found_back(...):
    # v2: één wand nieuwe GlobalId én 0,5 m verplaatst, naam uniek binnen klasse en type
    assert Paar(van=old, naar=new) in k.terugval

def test_identical_elements_at_the_same_place_are_not_guessed(...):
    # v2: twee wanden met nieuwe GlobalIds, gelijke klasse, type, naam, verdieping en plaats
    assert set(k.niet_gevonden) >= {a_old, b_old} and k.matchrate < 1.0

def test_a_removed_element_is_not_found(...):
    assert removed_gid in k.niet_gevonden

def test_koppelen_tool_over_http(httpserver, ...):  # bronnen via pytest-httpserver, zoals de omzet-tests
    assert run_tool("koppelen", {...})["matchrate"] == 1.0
```

- [ ] **Stap 2: Draai de tests** — verwacht: FAIL (`No module named 'openbim_kern.linking'`).
- [ ] **Stap 3: Implementeer `link_versions`** in drie rondes over de elementen die nog niet gekoppeld zijn:

```text
1. op GlobalId (in beide indexen)
2. sleutel (klasse, typenaam, naam, verdieping, x, y, z): koppel alleen als de sleutel precies één keer voorkomt in
   de overgebleven elementen van de vorige én van de nieuwe versie
3. sleutel (klasse, typenaam, naam): idem (een verplaatst element met een unieke naam)
matchrate = (op_globalid + len(terugval)) / elementen_vorige, en 1.0 als er geen elementen waren
```

  Ruimtelijke elementen (project, terrein, gebouw, verdieping) tellen mee als gewone elementen. De tool haalt beide
  indexen met `fetch_source` zoals `eigenschappen` (met de cache op sha256).
- [ ] **Stap 4: Draai de tests** — verwacht: PASS. Daarna de hele kernsuite.
- [ ] **Stap 5: Commit** `feat(kern): versiekoppeling met terugval en matchrate`.

### Taak 3: Botsingscontrole en de tool `botsingen`

**Bestanden:**
- Maak: `kern/src/openbim_kern/clash.py`, `kern/src/openbim_kern/tools/botsingen.py`
- Wijzig: `kern/src/openbim_kern/jobs/worker.py` (rij `botsing`, `OPENBIM_RIJ_BOTSING`, standaard 1), `README.md`
  (instelling)
- Test: `kern/tests/test_clash.py`

**Interfaces:**
- Levert: `find_clashes(set_a: list[ClashModel], set_b: list[ClashModel], soort: Literal["hard", "afstand"],
  tolerantie: float) -> list[Botsing]` met `ClashModel {sleutel: str, versie: str, pad: Path, klassen: list[str] | None}`
  en `Botsing {a: ElementRef, b: ElementRef, punt: tuple[float, float, float], afstand: float}`,
  `ElementRef {sleutel: str, versie: str, globalid: str}`; tool `botsingen` (`lang=True`, rij `botsing`) met invoer
  `BotsingIn {set_a: list[BotsingBron], set_b: list[BotsingBron], soort, tolerantie (0 ≤ t ≤ 1, meter), doel: HttpUrl}`,
  `BotsingBron {sleutel, versie, bron: Source, klassen: list[str] | None}`; schrijft de lijst als JSON naar `doel` en geeft
  `BotsingUit {aantal: int}`.

- [ ] **Stap 1: Schrijf de falende tests** (het testmodel `ifc_small` heeft een kanaal door een wand; hulpje
  `model(pad, klassen=None)` geeft een `ClashModel` met `sleutel` = bestandsnaam en `versie` = `"1"`; `duct_gid` en
  `wall_gids` uit het model)

```python
def test_duct_through_wall_is_a_hard_clash(ifc_small):
    found = find_clashes([model(ifc_small, klassen=["IfcFlowSegment", "IfcDuctSegment"])],
                         [model(ifc_small, klassen=["IfcWall"])], "hard", 0.0)
    assert any(c.a.globalid == duct_gid and c.b.globalid in wall_gids for c in found)

def test_tolerance_ignores_shallow_penetrations(ifc_small):
    assert find_clashes(..., "hard", 1.0) == []

def test_clearance_finds_elements_closer_than_the_distance(ifc_small):
    assert find_clashes(..., "afstand", 0.05)  # wanden die elkaar raken

def test_an_element_never_clashes_with_itself(ifc_small):
    found = find_clashes([model(ifc_small)], [model(ifc_small)], "hard", 0.0)
    assert all(c.a.globalid != c.b.globalid for c in found)

def test_botsingen_tool_delivers_json(httpserver, ifc_small):
    assert uit["aantal"] == len(json.loads(geleverd))
```

- [ ] **Stap 2: Draai de tests** — verwacht: FAIL.
- [ ] **Stap 3: Implementeer `find_clashes`** met `ifcopenshell.geom.tree` (geometrie in wereldcoördinaten, één
  iterator per model, filter op `klassen`); `hard` via `tree.clash_intersection_many(a, b, tolerance=t, check_all=True)`,
  `afstand` via `tree.clash_clearance_many(a, b, clearance=t, check_all=False)`; dubbele paren (a, b) en (b, a) één keer.
  De tool haalt de IFC-bronnen met `fetch_source` en levert het JSON-bestand met `deliver`.
- [ ] **Stap 4: Draai de tests** — verwacht: PASS. Daarna de hele kernsuite.
- [ ] **Stap 5: Commit** `feat(kern): botsingscontrole als lange taak in de rij botsing`.

### Taak 4: DocTypes en het auditlog

**Bestanden:**
- Maak: DocTypes in `frappe/openaec_bim/openaec_bim/openaec_bim/doctype/`: `bim_project`, `bim_issue`,
  `bim_issue_element` (kindtabel), `bim_standpunt`, `bim_reactie`, `bim_auditregel`; module
  `frappe/openaec_bim/openaec_bim/audit.py`
- Wijzig: `frappe/openaec_bim/openaec_bim/hooks.py` (`doc_events`)
- Test: `frappe/openaec_bim/openaec_bim/tests/test_audit.py`

**Interfaces:**
- Levert DocTypes (velden):
  - `BIM Project` (naam = id van de modelmap): `ruimte`, `titel`, `soorten`, `statussen`, `prioriteiten`, `fasen`,
    `labels` (Small Text, één waarde per regel; standaard `Fout/Vraag/Opmerking/Botsing`,
    `Open/In behandeling/Opgelost/Gesloten`, `Laag/Normaal/Hoog/Kritiek`, leeg, leeg), `standaard_status` (`Open`).
  - `BIM Issue` (naam = BCF-guid): `project`, `titel`, `beschrijving`, `soort`, `status`, `prioriteit`, `fase`,
    `toegewezen_aan`, `vervaldatum`, `labels` (JSON), `verwante_issues` (JSON), `documentverwijzingen` (JSON), `index`,
    `elementen` (tabel `BIM Issue Element`: `bestand`, `versie`, `globalid`).
  - `BIM Standpunt` (naam = BCF-guid): `issue`, `index`, `standpunt` (JSON: BCF 3.0-viewpoint zonder `snapshot`),
    `snapshot` (Attach Image, privé), `snapshot_type` (`png` of `jpg`).
  - `BIM Reactie` (naam = BCF-guid): `issue`, `tekst`, `standpunt` (Link `BIM Standpunt`).
  - `BIM Auditregel`: `tijd`, `gebruiker`, `handeling` (`aangemaakt`, `gewijzigd`, `verwijderd`, of een eigen woord
    zoals `geïmporteerd`), `doctype_naam`, `object`, `project`, `voor` (JSON), `na` (JSON), `bron`.
- Levert `audit.schrijf(handeling: str, doc, voor: dict | None, na: dict | None) -> None` (bron uit
  `frappe.flags.bim_bron`, standaard `achtergrond`) en `audit.exporteer(project: str) -> str` (CSV).

- [ ] **Stap 1: Schrijf de falende tests**

```python
def test_een_issue_aanmaken_wijzigen_en_verwijderen_staat_in_het_log(self):
    issue = maak_issue(self.project, titel="Wand botst met kanaal")
    issue.status = "In behandeling"; issue.save()
    issue.delete()
    regels = frappe.get_all("BIM Auditregel", {"object": issue.name}, ["handeling", "voor", "na"], order_by="tijd")
    assert [r.handeling for r in regels] == ["aangemaakt", "gewijzigd", "verwijderd"]
    assert json.loads(regels[1].voor)["status"] == "Open" and json.loads(regels[1].na)["status"] == "In behandeling"

def test_een_auditregel_kan_niet_gewijzigd_of_verwijderd_worden(self):
    regel = frappe.get_last_doc("BIM Auditregel")
    regel.handeling = "anders"
    self.assertRaises(frappe.PermissionError, regel.save)
    self.assertRaises(frappe.PermissionError, regel.delete)

def test_de_bron_komt_uit_de_flags(self):
    frappe.flags.bim_bron = "bcf-api"
    ...
    assert frappe.get_last_doc("BIM Auditregel").bron == "bcf-api"

def test_exporteer_geeft_csv_per_project(self):
    assert exporteer(self.project).splitlines()[0] == "tijd,gebruiker,handeling,doctype,object,bron"
```

- [ ] **Stap 2: Draai** `FRAPPE-TEST openaec_bim.tests.test_audit` — verwacht: FAIL.
- [ ] **Stap 3: Maak de DocTypes en `audit.py`**; `doc_events` op de vijf DocTypes (`after_insert`, `on_update` met
  `doc.get_doc_before_save()`, `on_trash`); `BIM Auditregel` weigert in `validate` elke opslag die niet nieuw is en in
  `on_trash` elke verwijdering (`frappe.PermissionError`), ook voor de beheerder.
- [ ] **Stap 4: Draai de test** — verwacht: PASS; ook `test_api` blijft groen.
- [ ] **Stap 5: Commit** `feat(openaec_bim): projecten, issues, standpunten, reacties en een auditlog`.

### Taak 5: Issues als BCF 3.0 (domeinfuncties)

**Bestanden:**
- Maak: `frappe/openaec_bim/openaec_bim/issues.py`
- Test: `frappe/openaec_bim/openaec_bim/tests/test_issues.py`

**Interfaces:**
- Gebruikt: DocTypes uit taak 4.
- Levert (alle in- en uitvoer in de JSON-vorm van BCF-API 3.0, velden met underscores zoals `topic_type`,
  `creation_date`, `authorization`):
  `project_van(map_: str) -> BIM Project` (maakt hem bij het eerste gebruik),
  `uitbreidingen(project) -> dict` (BCF `extensions`),
  `topics(project) -> list[dict]`, `topic(guid) -> dict`, `topic_maak(project, data: dict) -> dict`,
  `topic_wijzig(guid, data: dict) -> dict` (409 `VerouderdeVersie` als `data["modified_date"]` ouder is dan de opgeslagen),
  `topic_verwijder(guid) -> None`,
  `reacties(guid) -> list[dict]`, `reactie_maak(guid, data) -> dict`, `reactie_wijzig(guid, reactie, data) -> dict`,
  `reactie_verwijder(guid, reactie) -> None`,
  `standpunten(guid) -> list[dict]`, `standpunt(guid, sp) -> dict`, `standpunt_maak(guid, data) -> dict` (snapshot
  base64, PNG of JPEG, ≤ 5 MB, anders `ValidationError` met `snapshot_ongeldig`), `snapshot(guid, sp) -> tuple[bytes, str]`,
  `standpunt_verwijder(guid, sp) -> None`,
  `verwante(guid) -> list[dict]`, `verwante_zet(guid, guids: list[str]) -> list[dict]`,
  `documentverwijzingen(guid) -> list[dict]`, `documentverwijzing_maak(guid, data) -> dict`.
  Rechten volgens de globale eisen; `authorization.topic_actions` en `topic_status` per gebruiker.
  Elementen: uit `components.selection` van de standpunten komen rijen in `BIM Issue Element` (`bestand` en `versie`
  via de index van de modellen in het project: `zoek_elementen(project, globalids) -> dict[str, tuple[str, str]]`).

- [ ] **Stap 1: Schrijf de falende tests** (gebruikers en ruimtes met `openaec_storage.tests.hulp`, de kern als `NepKern`)

```python
def test_topic_maken_volgt_bcf_3(self):
    t = issues.topic_maak(self.project, {"title": "Kanaal door wand", "topic_type": "Botsing"})
    assert t["guid"] and t["topic_status"] == "Open" and t["creation_author"] == self.lid
    assert set(t["authorization"]["topic_actions"]) >= {"update", "createComment", "createViewpoint"}

def test_een_onbekende_status_wordt_geweigerd(self):
    self.assertRaises(frappe.ValidationError, issues.topic_maak, self.project, {"title": "x", "topic_status": "Weg"})

def test_lezer_mag_maken_en_reageren_maar_niet_andermans_issue_wijzigen(self):
    t = issues.topic_maak(...)  # als lid
    frappe.set_user(self.lezer)
    issues.reactie_maak(t["guid"], {"comment": "Gezien"})
    self.assertRaises(frappe.PermissionError, issues.topic_wijzig, t["guid"], {"title": "anders"})

def test_een_verouderde_wijziging_geeft_409(self):
    t = issues.topic_maak(...); oud = t["modified_date"]
    issues.topic_wijzig(t["guid"], {"title": "nieuw", "modified_date": oud})
    with self.assertRaises(issues.VerouderdeVersie):
        issues.topic_wijzig(t["guid"], {"title": "nog nieuwer", "modified_date": oud})

def test_standpunt_met_snapshot_en_selectie(self):
    sp = issues.standpunt_maak(t["guid"], {"perspective_camera": CAMERA, "snapshot": {"snapshot_type": "png",
          "snapshot_data": PNG_B64}, "components": {"selection": [{"ifc_guid": WAND}]}})
    assert issues.snapshot(t["guid"], sp["guid"])[1] == "image/png"
    assert frappe.get_all("BIM Issue Element", {"parent": t["guid"]}, pluck="globalid") == [WAND]

def test_een_te_grote_snapshot_wordt_geweigerd(self):
    groot = base64.b64encode(b"\x89PNG" + b"0" * (5 * 1024 * 1024)).decode()
    self.assertRaises(frappe.ValidationError, issues.standpunt_maak, t["guid"], {"snapshot": {...groot...}})
```

- [ ] **Stap 2: Draai** `FRAPPE-TEST openaec_bim.tests.test_issues` — verwacht: FAIL.
- [ ] **Stap 3: Implementeer `issues.py`** (vertaling DocType ↔ BCF-JSON op één plek: `_naar_bcf(doc)` en
  `_van_bcf(data, doc)`; datums als ISO 8601 met tijdzone).
- [ ] **Stap 4: Draai de test** — verwacht: PASS.
- [ ] **Stap 5: Commit** `feat(openaec_bim): issues met BCF 3.0 als datamodel`.

### Taak 6: `.bcfzip` lezen en schrijven, import en export in Storage

**Bestanden:**
- Maak: `frappe/openaec_bim/openaec_bim/bcfzip.py`
- Wijzig: `frappe/openaec_bim/openaec_bim/issues.py` (`importeer`, `exporteer_zip`)
- Test: `frappe/openaec_bim/openaec_bim/tests/test_bcfzip.py`

**Interfaces:**
- Gebruikt: `issues.topic_maak`, `reactie_maak`, `standpunt_maak` (taak 5).
- Levert: `bcfzip.lees(inhoud: bytes) -> list[dict]` (topics in BCF-API-JSON met `comments` en `viewpoints`, snapshot als
  base64; herkent 2.1 en 3.0 aan `bcf.version`), `bcfzip.schrijf(topics: list[dict], versie: Literal["2.1", "3.0"]) ->
  bytes`, `issues.importeer(project, bestand: str) -> dict` (`{nieuw, bijgewerkt}`; leest de huidige versie van het
  Storage-bestand; bestaande guid = bijwerken; onbekende soorten, statussen, prioriteiten, fasen en labels komen bij
  `BIM Project` en in het auditlog als `instellingen aangevuld`), `issues.exporteer_zip(project, versie) -> dict`
  (`{bestand}`; schrijft `<titel> issues <datum>.bcfzip` in de modelmap met `openaec_storage.api.upload_klein_bytes`).

- [ ] **Stap 1: Schrijf de falende tests**

```python
def test_3_0_heen_en_terug_zonder_verlies(self):
    topics = [topic_met_reactie_en_standpunt()]
    assert normaliseer(bcfzip.lees(bcfzip.schrijf(topics, "3.0"))) == normaliseer(topics)

def test_2_1_lezen(self):
    inhoud = bcfzip.schrijf(topics, "2.1")  # en een met de hand gemaakt 2.1-bestand in de test
    assert zipfile.ZipFile(io.BytesIO(inhoud)).read("bcf.version").decode().count('VersionId="2.1"')
    assert bcfzip.lees(inhoud)[0]["title"] == topics[0]["title"]

def test_geen_plafond_op_het_aantal_topics(self):
    assert len(bcfzip.lees(bcfzip.schrijf([topic(i) for i in range(300)], "3.0"))) == 300

def test_import_vult_onbekende_waarden_aan_en_logt_dat(self):
    uit = issues.importeer(self.project, upload_bcfzip([topic(status="Wacht op architect")]))
    assert uit["nieuw"] == 1 and "Wacht op architect" in project_statussen(self.project)
    assert frappe.db.exists("BIM Auditregel", {"handeling": "instellingen aangevuld", "project": self.project})

def test_export_zet_een_bcfzip_in_de_modelmap(self):
    uit = issues.exporteer_zip(self.project, "3.0")
    assert frappe.db.get_value("Opslagbestand", uit["bestand"], "naam").endswith(".bcfzip")
```

- [ ] **Stap 2: Draai** `FRAPPE-TEST openaec_bim.tests.test_bcfzip` — verwacht: FAIL.
- [ ] **Stap 3: Implementeer `bcfzip.py`** met `zipfile` en `xml.etree.ElementTree` volgens de XSD's van BCF 2.1 en 3.0
  (`markup.bcf`, `viewpoint.bcfv`, snapshots); `importeer` en `exporteer_zip` in `issues.py`.
- [ ] **Stap 4: Draai de test** — verwacht: PASS.
- [ ] **Stap 5: Commit** `feat(openaec_bim): bcfzip 2.1 en 3.0 lezen en schrijven, import en export in Storage`.

### Taak 7: Versiekoppeling in de app

**Bestanden:**
- Maak: DocType `bim_versiekoppeling`; module `frappe/openaec_bim/openaec_bim/koppeling.py`
- Wijzig: `afgeleid.py` (`bijwerken`: start de koppeling als een nieuwere versie klaar is en er een vorige klaar
  versie is), `volg_lopende` (ook koppelingen), `kern.py` (`start_koppelen(vorige: dict, nieuwe: dict) -> str`),
  `api.py` (`_model`: veld `koppeling`), `issues.py` (`_naar_bcf`: elementen op de huidige versie)
- Test: `frappe/openaec_bim/openaec_bim/tests/test_koppeling.py`

**Interfaces:**
- Gebruikt: kerntool `koppelen` (taak 2).
- Levert: DocType `BIM Versiekoppeling` (`bestand`, `van_versie`, `naar_versie`, `status`, `kern_taak`, `matchrate`,
  `op_globalid`, `terugval` (JSON), `niet_gevonden` (JSON), `fout` (JSON));
  `koppeling.huidig(bestand: str, globalid: str, van_versie: int, naar_versie: int) -> str | None` (volgt de keten van
  koppelingen; `None` = niet teruggevonden); in `api.project` per model `koppeling: {vorige_versie, matchrate} | None`;
  in de topic-JSON per element `{ifc_guid, bestand, versie, teruggevonden: bool}` voor de versie die het project toont.

- [ ] **Stap 1: Schrijf de falende tests**

```python
def test_een_nieuwe_klare_versie_start_de_koppeling(self):
    zet_klaar(bestand, versie=1); zet_klaar(bestand, versie=2)
    assert self.kern.verzoeken[-1][1] == "/v1/tools/koppelen"

def test_huidig_volgt_de_keten(self):
    koppeling(bestand, 1, 2, terugval=[{"van": "a1", "naar": "a2"}])
    koppeling(bestand, 2, 3, terugval=[])
    assert koppeling_mod.huidig(bestand, "a1", 1, 3) == "a2"
    assert koppeling_mod.huidig(bestand, "weg", 1, 3) is None  # in niet_gevonden

def test_project_toont_de_matchrate(self):
    assert api.project(self.map)["modellen"][0]["koppeling"] == {"vorige_versie": "1", "matchrate": 0.82}

def test_issue_op_een_element_reist_mee_naar_de_nieuwe_versie(self):
    t = issue_op(bestand, versie=1, globalid="a1")
    assert issues.topic(t["guid"])["elementen"] == [{"ifc_guid": "a2", "bestand": bestand, "versie": "2",
                                                    "teruggevonden": True}]
```

- [ ] **Stap 2: Draai** `FRAPPE-TEST openaec_bim.tests.test_koppeling` — verwacht: FAIL.
- [ ] **Stap 3: Implementeer** zoals in de interfaces; de kern krijgt kortlevende leesadressen van beide
  `eigenschappen.sqlite` (met sha256), zoals bij `eigenschappen`.
- [ ] **Stap 4: Draai de test** — verwacht: PASS; `test_api` blijft groen.
- [ ] **Stap 5: Commit** `feat(openaec_bim): versiekoppeling na elke nieuwe versie, issues reizen mee`.

### Taak 8: Botsingsrondes in de app

**Bestanden:**
- Maak: DocTypes `bim_botsingsronde`, `bim_botsing`; module `frappe/openaec_bim/openaec_bim/botsingen.py`
- Wijzig: `kern.py` (`start_botsingen(set_a, set_b, soort, tolerantie, doel) -> str`), `afgeleid.volg_lopende`
  (ook rondes)
- Test: `frappe/openaec_bim/openaec_bim/tests/test_botsingen.py`

**Interfaces:**
- Gebruikt: kerntool `botsingen` (taak 3), `koppeling.huidig` (taak 7), `issues.topic_maak`/`standpunt_maak` (taak 5).
- Levert: `BIM Botsingsronde` (`project`, `titel`, `set_a`/`set_b` (JSON: `[{bestand, klassen}]`), `soort`,
  `tolerantie`, `status`, `kern_taak`, `bron_versies` (JSON `{bestand: versie}`), `aantal`, `vorige_ronde`, `fout`);
  `BIM Botsing` (`ronde`, `sleutel` (`<bestand_a>:<globalid_a>|<bestand_b>:<globalid_b>`, gesorteerd), `element_a`,
  `element_b` (JSON `{bestand, versie, globalid}`), `punt` (JSON), `afstand`, `status` (`nieuw`, `actief`, `opgelost`,
  `genegeerd`), `issue`, `groep` (`<klasse_a> × <klasse_b>`));
  `botsingen.start(project, set_a, set_b, soort, tolerantie) -> str` (bewaart de versies van dat moment),
  `botsingen.verwerk(ronde) -> None` (resultaten inlezen, volgen ten opzichte van de vorige ronde met dezelfde sets:
  een paar dat via `koppeling.huidig` terugkomt houdt zijn status, `genegeerd` blijft genegeerd, `opgelost` wordt weer
  `actief`, een paar uit de vorige ronde dat niet meer voorkomt wordt `opgelost`),
  `botsingen.zet_status(botsing, status) -> dict`, `botsingen.naar_issue(botsing) -> dict` (topic van soort `Botsing`
  met een standpunt op het botspunt en beide elementen geselecteerd).

- [ ] **Stap 1: Schrijf de falende tests**

```python
def test_ronde_start_met_de_versies_van_nu(self):
    ronde = botsingen.start(self.project, [{"bestand": constructie}], [{"bestand": installaties}], "hard", 0.01)
    assert json.loads(frappe.db.get_value("BIM Botsingsronde", ronde, "bron_versies")) == {constructie: "1", installaties: "1"}

def test_een_nieuwe_versie_tijdens_de_ronde_verandert_de_ronde_niet(self):
    ronde = botsingen.start(...); nieuwe_versie(installaties)
    botsingen.verwerk(ronde)  # NepKern geeft resultaten voor versie 1
    assert botsing(ronde).element_b["versie"] == "1"

def test_volgende_ronde_volgt_via_de_koppeling(self):
    eerste = ronde_met([paar("w1", "k1")]); zet_status(eerste_botsing, "genegeerd")
    koppeling(installaties, 1, 2, terugval=[{"van": "k1", "naar": "k2"}])
    tweede = ronde_met([paar("w1", "k2")], vorige=eerste)
    assert botsing(tweede).status == "genegeerd"

def test_een_verdwenen_botsing_is_opgelost(self):
    assert status_in_tweede_ronde(paar_uit_eerste) == "opgelost"

def test_botsing_naar_issue(self):
    t = botsingen.naar_issue(b)
    assert t["topic_type"] == "Botsing" and {e["ifc_guid"] for e in t["elementen"]} == {"w1", "k1"}
```

- [ ] **Stap 2: Draai** `FRAPPE-TEST openaec_bim.tests.test_botsingen` — verwacht: FAIL.
- [ ] **Stap 3: Implementeer**; de kern krijgt leesadressen van de IFC-bronnen van de versies uit `bron_versies` en een
  schrijfadres voor `<prefix>/bim/botsingen/<ronde>.json`.
- [ ] **Stap 4: Draai de test** — verwacht: PASS.
- [ ] **Stap 5: Commit** `feat(openaec_bim): botsingsrondes die botsingen over versies heen volgen`.

### Taak 9: API voor de gastpagina

**Bestanden:**
- Maak: `frappe/openaec_bim/openaec_bim/api_coordinatie.py`
- Test: `frappe/openaec_bim/openaec_bim/tests/test_api_coordinatie.py`

**Interfaces:**
- Gebruikt: `issues`, `botsingen`, `audit` (taken 4–8).
- Levert whitelisted methoden (POST, sessie, `frappe.flags.bim_bron = "gastpagina"`): `instellingen(map)`,
  `issues(map)`, `issue_bewaar(map, topic)`, `issue_verwijder(guid)`, `reacties(guid)`, `reactie_bewaar(guid, reactie)`,
  `standpunt_bewaar(guid, standpunt)`, `snapshot(guid, standpunt)` (base64), `bcf_export(map, versie)`,
  `bcf_import(map, bestand)`, `botsingsronde_start(map, set_a, set_b, soort, tolerantie)`, `botsingsrondes(map)`,
  `botsingen(ronde)`, `botsing_status(botsing, status)`, `botsing_naar_issue(botsing)`, `audit_export(map)` (alleen met
  schrijfrecht op de modelmap). Elke methode is een dunne laag over de domeinfunctie.

- [ ] **Stap 1: Schrijf de falende tests**

```python
def test_een_externe_partij_via_een_deling_maakt_een_issue(self):
    frappe.set_user(self.extern)  # deling met leesrecht op de modelmap
    assert api_coordinatie.issue_bewaar(self.map, {"title": "Sparing ontbreekt"})["guid"]

def test_na_intrekken_van_de_deling_geen_toegang(self):
    trek_in(self.deling); frappe.set_user(self.extern)
    self.assertRaises(frappe.PermissionError, api_coordinatie.issues, self.map)

def test_bron_is_gastpagina_in_het_auditlog(self):
    assert frappe.get_last_doc("BIM Auditregel").bron == "gastpagina"

def test_audit_export_alleen_met_schrijfrecht(self):
    frappe.set_user(self.lezer)
    self.assertRaises(frappe.PermissionError, api_coordinatie.audit_export, self.map)
```

- [ ] **Stap 2: Draai** `FRAPPE-TEST openaec_bim.tests.test_api_coordinatie` — verwacht: FAIL.
- [ ] **Stap 3: Implementeer** de methoden.
- [ ] **Stap 4: Draai de test** — verwacht: PASS.
- [ ] **Stap 5: Commit** `feat(openaec_bim): API voor issues en botsingen in de gastpagina`.

### Taak 10: BCF-API 3.0 en Foundation API: ontdekken, projecten, topics, reacties

**Bestanden:**
- Maak: `frappe/openaec_bim/openaec_bim/bcf_api/__init__.py`, `bcf_api/renderer.py` (paginarenderer, naar het
  voorbeeld van `openaec_werkplek.appbestanden.AppBestand` in de bench-repo), `bcf_api/routes.py`
- Wijzig: `hooks.py` (`page_renderer = ["openaec_bim.bcf_api.renderer.BcfApi"]`)
- Test: `frappe/openaec_bim/openaec_bim/tests/test_bcf_api.py`

**Interfaces:**
- Gebruikt: `issues` (taak 5).
- Levert: `BcfApi` (`can_render()` voor paden onder `/foundation/` en `/bcf/3.0/`, `render()` geeft JSON met de
  statuscodes van de specificatie: 200, 201, 204, 400, 401, 403, 404, 409), met
  `frappe.flags.bim_bron = "bcf-api"`. Routes: Foundation `versions`, `auth` (OAuth2 van Frappe:
  `/api/method/frappe.integrations.oauth2.authorize` en `.get_token`, flow `authorization_code_grant`) en
  `current-user`; `GET /bcf/3.0/projects`, `GET/PUT /projects/{id}`, `GET /projects/{id}/extensions`;
  `GET/POST /projects/{id}/topics`, `GET/PUT/DELETE /projects/{id}/topics/{guid}`;
  `GET/POST .../topics/{guid}/comments`, `GET/PUT/DELETE .../comments/{guid}`. Projecten = de `BIM Project`-records
  waarop de gebruiker leesrecht heeft.

- [ ] **Stap 1: Schrijf de falende tests** (werkzeug-testclient op `frappe.app.application`, ingelogd met een
  API-sleutel en een OAuth-bearertoken van een `OAuth Client` uit de test)

```python
def test_versions_noemt_bcf_3_0(self):
    r = self.get("/foundation/versions")
    assert any(v["api_id"] == "bcf" and v["version_id"] == "3.0" for v in r.json["versions"])

def test_topic_aanmaken_lezen_en_lijst(self):
    r = self.post(f"/bcf/3.0/projects/{self.map}/topics", {"title": "Via de API", "topic_type": "Vraag"})
    assert r.status_code == 201
    assert self.get(f"/bcf/3.0/projects/{self.map}/topics/{r.json['guid']}").json["title"] == "Via de API"

def test_reactie_via_de_api(self):
    assert self.post(f".../topics/{guid}/comments", {"comment": "Akkoord"}).status_code == 201

def test_zonder_toegang_tot_de_modelmap_403_ook_met_token(self):
    trek_in(self.deling)
    assert self.get(f"/bcf/3.0/projects/{self.map}/topics", token=self.token_extern).status_code == 403

def test_verouderde_wijziging_409(self):
    assert self.put(f".../topics/{guid}", {"title": "x", "modified_date": oud}).status_code == 409
```

- [ ] **Stap 2: Draai** `FRAPPE-TEST openaec_bim.tests.test_bcf_api` — verwacht: FAIL.
- [ ] **Stap 3: Implementeer** de renderer en de routes (een tabel `(methode, patroon) -> functie`; fouten als
  `{"message": ...}` met de juiste status).
- [ ] **Stap 4: Draai de test** — verwacht: PASS.
- [ ] **Stap 5: Commit** `feat(openaec_bim): BCF-API 3.0 met de Foundation API: projecten, topics en reacties`.

### Taak 11: BCF-API 3.0: standpunten, verwante topics, documentverwijzingen en de conformiteitstest

**Bestanden:**
- Wijzig: `frappe/openaec_bim/openaec_bim/bcf_api/routes.py`
- Maak: `frappe/openaec_bim/scripts/bcf_conformiteit.py` (draait de voorbeeldaanroepen uit de specificatie tegen een
  klantsite en schrijft een rapport), `docs/bcf-conformiteit.md` (hoe draaien, laatste uitslag)
- Test: `frappe/openaec_bim/openaec_bim/tests/test_bcf_api.py` (aanvullen)

**Interfaces:**
- Levert routes: `GET/POST .../topics/{guid}/viewpoints`, `GET/DELETE .../viewpoints/{vp}`,
  `GET .../viewpoints/{vp}/snapshot` (beeld met het juiste `Content-Type`), `GET .../viewpoints/{vp}/selection`,
  `.../coloring`, `.../visibility`, `GET/PUT .../topics/{guid}/related_topics`,
  `GET/POST .../topics/{guid}/document_references`, `PUT .../document_references/{id}`.

- [ ] **Stap 1: Schrijf de falende tests**

```python
def test_standpunt_met_snapshot_heen_en_terug(self):
    vp = self.post(f".../topics/{guid}/viewpoints", VIEWPOINT_MET_PNG).json
    r = self.get(f".../viewpoints/{vp['guid']}/snapshot")
    assert r.status_code == 200 and r.headers["Content-Type"] == "image/png" and r.data == PNG

def test_selectie_van_een_standpunt(self):
    assert self.get(f".../viewpoints/{vp}/selection").json == {"selection": [{"ifc_guid": WAND}]}

def test_verwante_topics_zetten(self):
    assert [t["related_topic_guid"] for t in self.put(f".../{a}/related_topics", [{"related_topic_guid": b}]).json] == [b]
```

- [ ] **Stap 2: Draai de test** — verwacht: FAIL.
- [ ] **Stap 3: Implementeer** de routes en het conformiteitsscript (BCF 2.1 en 3.0 heen en terug zonder verlies hoort
  erbij, zie hoofdstuk 11 van het ontwerp).
- [ ] **Stap 4: Draai de test en het script** tegen klant0 — verwacht: PASS en een rapport zonder fouten.
- [ ] **Stap 5: Commit** `feat(openaec_bim): BCF-API-standpunten en een openbare conformiteitstest`.

### Taak 12: Berichten in de gastpagina (repo `openaec-bench`, branch `bouw/bim-werkplek`)

**Bestanden:**
- Wijzig: `frontend/apps/werkplek/src/gast/bim-berichten.ts`
- Test: `frontend/apps/werkplek/test/bim.test.ts`

**Interfaces:**
- Gebruikt: de methoden van `openaec_bim.api_coordinatie` (taak 9).
- Levert de berichtsoorten `bim.instellingen`, `bim.issues`, `bim.issue_bewaar`, `bim.issue_verwijder`,
  `bim.reacties`, `bim.reactie_bewaar`, `bim.standpunt_bewaar`, `bim.snapshot`, `bim.bcf_export`,
  `bim.botsingsronde_start`, `bim.botsingsrondes`, `bim.botsingen`, `bim.botsing_status`, `bim.botsing_naar_issue`,
  `bim.bcf_import` (de gastpagina toont een keuzevenster voor een `.bcfzip` in Storage, met het bladeren van
  `kies-modelmap.ts`, en roept `bcf_import(map, bestand)`; annuleren geeft `null`);
  altijd met de modelmap van de pagina (nooit een map uit het bericht); `guid`'s volgens `/^[0-9a-f-]{36}$/i`, anders
  code `guid_ongeldig`; een snapshot boven 5 MB weigert de pagina al (code `snapshot_te_groot`).

- [ ] **Stap 1: Schrijf de falende tests**

```ts
it("bim.issue_bewaar gaat met de modelmap van de pagina naar openaec_bim", async () => {
  const server = nepServer({ "openaec_bim.api_coordinatie.issue_bewaar": { guid: GUID } });
  await soorten["bim.issue_bewaar"](verzoek("bim.issue_bewaar", { topic: { title: "x" }, map: "andere-map" }));
  expect(server.aanroepen("openaec_bim.api_coordinatie.issue_bewaar")[0].args).toEqual({ map: "map-1", topic: { title: "x" } });
});
it("een ongeldige guid wordt geweigerd", ...);          // rejects.toMatchObject({ code: "guid_ongeldig" })
it("een snapshot boven 5 MB wordt geweigerd", ...);     // rejects.toMatchObject({ code: "snapshot_te_groot" })
```

- [ ] **Stap 2: Draai** `bash scripts/build-frontend.sh test apps/werkplek` — verwacht: FAIL.
- [ ] **Stap 3: Implementeer** de berichtsoorten.
- [ ] **Stap 4: Draai de test** — verwacht: PASS.
- [ ] **Stap 5: Commit (lokaal, niet pushen)** `feat(werkplek): berichten voor issues en botsingen in Open BIM Platform`.

### Taak 13: Host en engine in de viewer

**Bestanden:**
- Wijzig: `viewer/src/host/BimHost.ts`, `viewer/src/host/WerkplekHost.ts`, `viewer/src/host/LocalHost.ts`,
  `viewer/src/engine/FragmentsEngine.ts`
- Maak: `viewer/src/model/bcf.ts` (types en camera-omrekening)
- Test: `viewer/src/host/WerkplekHost.test.ts`, `viewer/src/model/bcf.test.ts`

**Interfaces:**
- Levert: `BimHost.coordinatie?: Coordinatie` (`LocalHost`: afwezig) met de methoden die de berichten van taak 12
  aanroepen (`issues()`, `issueBewaar(topic)`, `issueVerwijder(guid)`, `reacties(guid)`, `reactieBewaar(guid, r)`,
  `standpuntBewaar(guid, s)`, `snapshot(guid, sp)`, `instellingen()`, `bcfExport(versie)`,
  `bcfImport(): Promise<{ nieuw: number; bijgewerkt: number } | null>`, `botsingsrondeStart(...)`,
  `botsingsrondes()`, `botsingen(ronde)`, `botsingStatus(b, s)`, `botsingNaarIssue(b)`); types `Topic`, `Comment`,
  `Viewpoint`, `BcfCamera`, `Extensions`, `Botsingsronde`, `Botsing` in `model/bcf.ts`; `ModelInfo.koppeling?:
  { vorige_versie: string; matchrate: number } | null`; `KOPPEL_DREMPEL = 0.9`;
  `toBcfCamera(position, target, up, fovDeg, aspect) -> BcfCamera` en `fromBcfCamera(c) -> {position, target, up}`;
  engine: `camera(): BcfCamera`, `setCamera(c: BcfCamera): Promise<void>`, `snapshot(): Promise<Blob>` (PNG van het
  canvas), `focus(point: [number, number, number], radius: number): Promise<void>`,
  `highlightMany(targets: { keys: string[]; globalid: string }[]): Promise<void>`.

- [ ] **Stap 1: Schrijf de falende tests**

```ts
test("camera heen en terug", () => {
  const c = toBcfCamera([10, 5, 3], [0, 0, 0], [0, 0, 1], 60, 1.5);
  expect(c.perspective_camera.camera_direction).toEqual(normalize([-10, -5, -3]));
  expect(fromBcfCamera(c).position).toEqual([10, 5, 3]);
});
test("WerkplekHost stuurt bim.issue_bewaar en geeft het topic terug", async () => { ... });
test("LocalHost heeft geen coordinatie", () => expect(new LocalHost("http://x").coordinatie).toBeUndefined());
```

- [ ] **Stap 2: Draai** `npx vitest run src/model/bcf.test.ts src/host/WerkplekHost.test.ts` — verwacht: FAIL.
- [ ] **Stap 3: Implementeer**; three.js werkt in Y-boven, IFC en BCF in Z-boven: de omrekening zit alleen in
  `model/bcf.ts`.
- [ ] **Stap 4: Draai de tests en `npx tsc --noEmit`** — verwacht: PASS.
- [ ] **Stap 5: Commit** `feat(viewer): coördinatie in de host en camera en snapshot in de engine`.

### Taak 14: Issuespaneel in de viewer

**Bestanden:**
- Maak: `viewer/src/ui/IssuesPanel.tsx`, `viewer/src/ui/IssueDetail.tsx`, `viewer/src/ui/Markup.tsx`,
  `viewer/src/model/issues.ts` (filteren, sorteren, een nieuw topic opbouwen)
- Wijzig: `viewer/src/ui/App.tsx` (tabbladen rechts: Eigenschappen, Issues, Botsingen; alleen met `host.coordinatie`),
  `viewer/src/ui/ModelList.tsx` (waarschuwing bij `koppeling.matchrate < KOPPEL_DREMPEL`), `viewer/src/i18n/*.json`
- Test: `viewer/src/model/issues.test.ts`

**Interfaces:**
- Gebruikt: `Coordinatie`, engine-methoden en `KOPPEL_DREMPEL` (taak 13).
- Levert: `filterTopics(topics, {status?, soort?, toegewezen?, tekst?}) -> Topic[]`,
  `nieuwTopic(form, camera, selectie) -> { topic, standpunt }`. Een issue maken: titel, soort, prioriteit, toegewezen
  aan, beschrijving, het huidige standpunt (camera en selectie) en de schermafbeelding met de markering (vrije lijnen in
  één kleur, ingetekend over de schermafbeelding). Een issue openen zet de camera en de selectie terug; elementen die
  niet zijn teruggevonden, krijgen de melding "niet teruggevonden in versie n". Knoppen "Exporteren (BCF 3.0 of 2.1)"
  en "Importeren" roepen `bcfExport` en `bcfImport`.

- [ ] **Stap 1: Schrijf de falende tests**

```ts
test("filter op status en tekst", () => {
  expect(filterTopics(TOPICS, { status: "Open", tekst: "kanaal" }).map((t) => t.guid)).toEqual(["t1"]);
});
test("nieuw topic neemt camera en selectie mee", () => {
  const { standpunt } = nieuwTopic(FORM, CAMERA, ["2O2Fr$t4X7Zf8NOew3FLOH"]);
  expect(standpunt.components?.selection).toEqual([{ ifc_guid: "2O2Fr$t4X7Zf8NOew3FLOH" }]);
});
test("matchrate onder de drempel geeft een waarschuwing", () => expect(koppelWaarschuwing(0.85)).toBe(true));
```

- [ ] **Stap 2: Draai** `npx vitest run src/model/issues.test.ts` — verwacht: FAIL.
- [ ] **Stap 3: Implementeer** de panelen (huisstijl uit `@openaec/shell`).
- [ ] **Stap 4: Draai alle viewertests en `npx tsc --noEmit`** — verwacht: PASS.
- [ ] **Stap 5: Commit** `feat(viewer): issues met standpunt en markering`.

### Taak 15: Botsingspaneel in de viewer

**Bestanden:**
- Maak: `viewer/src/ui/ClashPanel.tsx`, `viewer/src/model/clashes.ts`
- Wijzig: `viewer/src/ui/App.tsx`, `viewer/src/i18n/*.json`
- Test: `viewer/src/model/clashes.test.ts`

**Interfaces:**
- Gebruikt: `Coordinatie.botsingsrondeStart`, `botsingsrondes`, `botsingen`, `botsingStatus`, `botsingNaarIssue`;
  engine `focus` en `highlightMany` (taak 13).
- Levert: `groepeer(botsingen) -> { groep: string; botsingen: Botsing[] }[]` (op `groep`, grootste eerst) en een paneel:
  een ronde starten (set A en set B kiezen uit de modellen, soort hard of afstand, tolerantie in mm), de voortgang, de
  resultaten per groep, per botsing in beeld brengen (camera op het punt, beide elementen gemarkeerd), de status zetten
  en omzetten in een issue.

- [ ] **Stap 1: Schrijf de falende test**

```ts
test("groepeer op klassepaar, grootste groep eerst", () => {
  expect(groepeer(BOTSINGEN).map((g) => [g.groep, g.botsingen.length])).toEqual([["IfcWall × IfcDuctSegment", 3], ["IfcSlab × IfcPipeSegment", 1]]);
});
```

- [ ] **Stap 2: Draai** — verwacht: FAIL.
- [ ] **Stap 3: Implementeer** het paneel.
- [ ] **Stap 4: Draai alle viewertests en `npx tsc --noEmit`** — verwacht: PASS.
- [ ] **Stap 5: Commit** `feat(viewer): botsingsrondes in de viewer`.

### Taak 16: Acceptatie in de werkplek

**Bestanden:**
- Maak: `scripts/werkplek-e2e/bim-coordinatie.mjs` in `openaec-bench` (naast `bim-proef.mjs`, met dezelfde hulp)
- Wijzig: `scripts/werkplek-versies.txt` (pin op de laatste commit van `fase-1-werkplek`), `docs/metingen/` in
  open-bim-platform (`2026-fase-1b.md`), `README.md` (stand en BCF-API)

**Interfaces:**
- Gebruikt: alles hierboven.

- [ ] **Stap 1: Schrijf de proef** (Playwright op de GPU, zoals `bim-proef.mjs`), met als stappen en controles:
  1. een coördinator opent een modelmap met twee disciplines en maakt een issue met markering op een element;
  2. een externe partij met een deling (alleen lezen) ziet het issue, reageert, en maakt zelf een issue;
  3. een botsingsronde constructie tegen installaties: resultaten verschijnen, één botsing wordt een issue;
  4. een nieuwe versie van het constructiemodel met een deel nieuwe GlobalIds (gemaakt met een script dat GlobalIds
     vervangt): de matchrate staat in de modellijst, de issues en botsingen van stap 1–3 zijn er nog;
  5. een BCF-programma (de conformiteitstest als client met een OAuth-token van de externe partij) leest de issues en
     voegt een reactie toe die in de viewer verschijnt;
  6. export als `.bcfzip` in de modelmap en import in een nieuw project geeft dezelfde issues;
  7. het auditlog bevat elke stap met de juiste bron.
- [ ] **Stap 2: Draai de proef** op de lokale bench — verwacht: exit 0, schermafbeeldingen en een verslag.
- [ ] **Stap 3: Leg de uitkomst vast** in `docs/metingen/2026-fase-1b.md` (tijden van koppelen en botsen per
  modelgrootte, matchrate) en werk de README bij.
- [ ] **Stap 4: Commit** in beide repo's (open-bim-platform pushen naar de PR-branch; `openaec-bench` lokaal)
  `test: acceptatie van fase 1b in de werkplek`.
