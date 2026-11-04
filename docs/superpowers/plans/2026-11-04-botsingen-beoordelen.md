# Botsingen beoordelen Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Een botsingsronde levert een werklijst: met snelle keuzes starten, indeling in emmers met ernst en plaats, beoordelen met sneltoetsen, beslissingen die meegaan over rondes, issues die hun botsing volgen, en het paar geïsoleerd in beeld.

**Architecture:** De kern rekent meerdere controles op één scène en voegt per botsing context toe (naam, verdieping, raster, ruimte, emmer, ernst, categorie). De Frappe-app bewaart die velden, volgt rondes in een reeks en beheert status, regels en weergaven. De viewer doet filteren, groeperen en sneltoetsen als pure logica in `model/clashes.ts`, met schermen eromheen; alles loopt via de `bim.*`-berichten van de gastpagina.

**Tech Stack:** Python 3.12, IfcOpenShell 0.8.4, pydantic (kern); Frappe v16 (app); React 18, TypeScript, That Open Fragments 3.6 (viewer); TypeScript in `openaec-bench` (gastpagina).

**Spec:** `docs/superpowers/specs/2026-11-04-botsingen-beoordelen-design.md` — lees de genoemde hoofdstukken bij elke taak.

## Global Constraints

- Branch `fase-1c-botsingen-beoordelen` in `open-bim-platform`. De gastpagina zit in `../openaec-bench-bim`, branch `bouw/bim-werkplek`: lokaal committen, niet pushen.
- Nergens in repo's of commits namen van andere commerciële of concurrerende BIM-programma's, en geen verwijzingen naar gesprekken. Geen code overnemen uit andere producten.
- Code in `kern/` en `viewer/`: Engels (namen, comments). `frappe/` volgt de bestaande Nederlandse namen. Documentatie Nederlands. Commits: `type(scope): Nederlandse omschrijving`, afgesloten met de regel `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Schrijfrecht vereist voor beoordelen, regels en weergaven; lezen mag iedereen met leesrecht op de modelmap.
- De viewer bewaart niets in de browser. Stijlen alleen met tokens van het stijlboek (`viewer/vendor/openaec-style-book`, klassen `oa-*`); tekst via `viewer/src/i18n/nl.json` en `en.json`.
- De som van de emmers is altijd het totaal: indeling verbergt, ze gooit niets weg.
- Waarden uit de spec: contact onder 5 mm, ernstgrens 20 mm, aansluiting en systeem onder 50 mm, `dubbel` 10 mm per zijde, hoogstens 30 controles per ronde, reden hoogstens 200 tekens, groepsactie hoogstens 500, hoogstens 50 weergaven, verloop hoogstens 20 rondes, 100 rijen per groep, kolom 360 px op *Issues* en *Botsingen*.

**Commando's**

| Doel | Commando |
|---|---|
| Kern | `cd kern && .venv/Scripts/python.exe -m pytest tests/<bestand> -q` en `.venv/Scripts/ruff.exe check src tests scripts && .venv/Scripts/ruff.exe format --check src tests scripts` |
| App | `bash /c/Users/rickd/AppData/Local/Temp/obp/frappe-test.sh openaec_bim.tests.test_botsingen` (de container `openaec-bim-bench-1` draait; bij een andere doctype eerst `MSYS_NO_PATHCONV=1 docker exec openaec-bim-bench-1 bash -lc 'cd ~/benches/frappe-bench && bench --site klant0.cloud.open-aec.localhost migrate'`) |
| Viewer | `cd viewer && npx vitest run src/<bestand> && npx tsc --noEmit` |
| Gastpagina | in `../openaec-bench-bim/frontend`: `npx vitest run apps/werkplek/test/bim.test.ts`; bouwen: `bash scripts/build-frontend.sh` vanuit `../openaec-bench-bim` |

Op deze machine: geen `MSYS_NO_PATHCONV` bij `scripts/build-werkplek.sh`, wel bij `docker exec` met paden in de container.

## Review Focus

- **Een ronde zonder één botsing, of waarvan alles weg is:** lege lijst met een uitleg, geen fout; de vorige rijen worden `weg`. Test: taak 4.
- **Een issue dat intussen is verwijderd:** het inlezen van de ronde loopt door en laat de koppeling leeg. Test: taak 4.
- **Een model direct in de modelmap (geen submap):** de discipline is de bestandsnaam zonder `.ifc`, en *Volgens de projectregels* werkt. Test: taak 4 en taak 7.
- **Een element zonder naam:** de rij toont de klasse. Test: taak 7.
- **Een letter typen in een veld, of Ctrl+B:** geen sneltoets. Test: taak 7.

---

### Task 1: Kern: meerdere controles op één scène

**Files:**
- Modify: `kern/src/openbim_kern/clash.py`, `kern/src/openbim_kern/tools/botsingen.py`
- Test: `kern/tests/test_clash.py`

**Interfaces:**
- Produces (in `clash.py`):
  - `ClashCheck(BaseModel)`: `regel: str = ""`, `set_a: list[ClashModel]`, `set_b: list[ClashModel]`, `soort: Literal["hard","afstand","dubbel"]`, `tolerantie: float = 0.0`, `ernst: Literal["klein","groot","kritiek"] | None = None`, `alleen_tussen_modellen: bool = False`
  - `ElementRef` krijgt `naam: str | None = None`, `verdieping: str | None = None`
  - `Botsing` krijgt `soort: str = "hard"`, `regel: str = ""`, `emmer: str = "beoordelen"`, `emmer_reden: str | None = None`, `ernst: str | None = None`, `categorie: str | None = None`, `raster: str | None = None`, `ruimte: str | None = None`
  - `class ClashScene`: `__init__(self, paths: list[Path], progress: Callable[[float], None] = _no_progress)` leest elk pad één keer, vult `tree`, `files` en `boxes: dict[str, tuple[Vec3, Vec3]]` per GlobalId; `check(self, check: ClashCheck) -> list[Botsing]`
  - `run_checks(checks: list[ClashCheck], progress: Callable[[float], None] = _no_progress) -> list[Botsing]`
  - `find_clashes(set_a, set_b, soort, tolerantie) -> list[Botsing]` blijft en gebruikt `ClashScene`
- Produces (in de tool): `BotsingControle` en `BotsingIn{controles: list[BotsingControle] (1 tot 30), doel: HttpUrl}`; `BotsingUit{aantal}`; de tool neemt `progress`.

- [ ] **Step 1: Write the failing tests in `tests/test_clash.py`**

Op `ifc_small`, met `model()` en `gids()` die er al zijn:

```python
def test_two_checks_read_the_file_once_and_report_a_pair_once(ifc_small, monkeypatch):
    opens = []
    real = ifcopenshell.open
    monkeypatch.setattr(ifcopenshell, "open", lambda p: opens.append(p) or real(p))
    check = ClashCheck(set_a=[model(ifc_small, ["IfcDuctSegment"])], set_b=[model(ifc_small, ["IfcWall"])], soort="hard")
    found = run_checks([check.model_copy(update={"regel": "een"}), check.model_copy(update={"regel": "twee"})])
    assert len(opens) == 1
    assert len({frozenset((c.a.globalid, c.b.globalid)) for c in found}) == len(found) > 0
    assert {c.regel for c in found} == {"een"}


def test_hard_wins_from_distance_for_the_same_pair(ifc_small):
    a, b = [model(ifc_small, ["IfcDuctSegment"])], [model(ifc_small, ["IfcWall"])]
    found = run_checks([
        ClashCheck(regel="ver", set_a=a, set_b=b, soort="afstand", tolerantie=0.05),
        ClashCheck(regel="door", set_a=a, set_b=b, soort="hard"),
    ])
    hit = next(c for c in found if c.b.globalid in gids(ifc_small, "IfcWall"))
    assert hit.soort == "hard" and hit.regel == "door"


def test_only_between_models_skips_pairs_in_one_model(ifc_small, tmp_path):
    copy = tmp_path / "kopie.ifc"; copy.write_bytes(ifc_small.read_bytes())
    # Dezelfde GlobalIds in twee bestanden geven geen paar met zichzelf en geen fout.
    found = run_checks([ClashCheck(set_a=[model(ifc_small)], set_b=[model(ifc_small)], soort="hard", alleen_tussen_modellen=True)])
    assert found == []


def test_duplicate_needs_the_same_class_and_box(tmp_path):
    path = models.ifc_clash_context(tmp_path / "context.ifc")
    found = run_checks([ClashCheck(set_a=[model(path)], set_b=[model(path)], soort="dubbel")])
    assert [c.soort for c in found] == ["dubbel"]
    assert {c.a.klasse, c.b.klasse} == {"IfcWall"}


def test_elements_carry_name_and_storey(ifc_small):
    found = run_checks([ClashCheck(set_a=[model(ifc_small, ["IfcDuctSegment"])], set_b=[model(ifc_small, ["IfcWall"])], soort="hard")])
    assert found[0].a.naam == "Kanaal" and found[0].a.verdieping == "00 begane grond"


def test_virtual_elements_do_not_clash(tmp_path):
    path = models.ifc_clash_context(tmp_path / "context.ifc")
    found = run_checks([ClashCheck(set_a=[model(path)], set_b=[model(path)], soort="hard")])
    assert not any("IfcVirtualElement" in (c.a.klasse, c.b.klasse) for c in found)
```

En in `kern/tests/models.py` de functie `ifc_clash_context(path) -> Path`: één model met naamloze en benoemde elementen, zo dat elke regel uit spec 6.4 geraakt wordt:
- een dragende `IfcWall` (`Pset_WallCommon.LoadBearing` waar) met `IfcOpeningElement` en `IfcDoor` die erin overlapt;
- een `IfcElementAssembly` met twee `IfcMember`-delen die overlappen;
- twee `IfcWall` verbonden met `IfcRelConnectsPathElements` die overlappen;
- twee `IfcPipeSegment` in hetzelfde `IfcDistributionSystem` met 30 mm overlap;
- `IfcBeam` die 30 mm in `IfcColumn` steekt;
- een `IfcDuctSegment` dat 200 mm door de dragende wand gaat, en een die 2 mm in een vloer steekt;
- een tweede wand exact op een derde wand (dubbel);
- een `IfcVirtualElement`, een `IfcGrid` met assen `A`, `B` en `1`, `2`, en een `IfcSpace` met `LongName` `Gang 1` rond het kanaal.

- [ ] **Step 2: Run:** `pytest tests/test_clash.py -q`. Expected: FAIL (`ClashCheck` bestaat niet).

- [ ] **Step 3: Implement in `clash.py` en de tool**

Volgorde in `run_checks`: stabiel sorteren op `dubbel`, `hard`, `afstand`; een paar (`frozenset` van de GlobalIds) komt één keer voor. `dubbel`: een harde vraag met tolerantie 0, daarna alleen paren met `a.is_a() == b.is_a()` en `boxes` die per zijde hoogstens `DUPLICATE_BOX_M = 0.010` verschillen. `boxes` komen uit `shape.geometry.verts` tijdens het trianguleren. `_elements` slaat `IfcVirtualElement` over. Voortgang: laden tot 0,5 naar bestandsgrootte, controles tot 0,9. De tool bouwt per controle `ClashModel`s en haalt elk bestand één keer op (bestaande `paths`-map). `alleen_tussen_modellen` vergelijkt `sleutel` van de twee kanten.

- [ ] **Step 4: Run:** `pytest tests/test_clash.py tests/test_mcp_cli.py -q` en ruff. Expected: PASS. Pas tests die de oude tool-invoer gebruiken aan op `controles`.

- [ ] **Step 5: Commit** `feat(kern): meerdere controles per botsingsronde op één scène, en dubbele elementen`

---

### Task 2: Kern: indeling en plaats van een botsing

**Files:**
- Create: `kern/src/openbim_kern/clash_context.py`, `kern/tests/test_clash_context.py`
- Modify: `kern/src/openbim_kern/clash.py`

**Interfaces:**
- Consumes: `ClashScene`, `Botsing`, `run_checks` uit taak 1.
- Produces:
  - `classify(soort: str, afstand: float, relatie: str | None, zelfde_systeem: bool, familie_a: str, familie_b: str, vaste_ernst: str | None) -> Indeling`, met `Indeling(NamedTuple)`: `emmer`, `emmer_reden`, `ernst`, `categorie`. Puur.
  - `class ModelContext`: `__init__(self, model: ifcopenshell.file, settings)`; `relatie(gid_a, gid_b) -> "vulling"|"samenstel"|"verbonden"|None`; `zelfde_systeem(gid_a, gid_b) -> bool`; `familie(gid) -> "constructie"|"installaties"|"afwerking"`; `naam(gid) -> str|None`; `verdieping(gid) -> str|None`; `raster(punt) -> str|None`; `ruimte(punt) -> tuple[float, str]|None` (volume en naam).
  - `run_checks` vult alle context-velden.

- [ ] **Step 1: Write the failing tests**

```python
@pytest.mark.parametrize("soort,afstand,relatie,systeem,fa,fb,emmer,reden,ernst", [
    ("hard", 0.30, "vulling", False, "afwerking", "constructie", "aangrenzend", "vulling", "klein"),
    ("hard", 0.30, "samenstel", False, "constructie", "constructie", "aangrenzend", "samenstel", "klein"),
    ("hard", 0.30, "verbonden", False, "constructie", "constructie", "aangrenzend", "verbonden", "klein"),
    ("hard", 0.03, None, True, "installaties", "installaties", "aangrenzend", "zelfde_systeem", "klein"),
    ("hard", 0.06, None, True, "installaties", "installaties", "beoordelen", None, "groot"),
    ("hard", 0.03, None, False, "constructie", "constructie", "aangrenzend", "aansluiting", "klein"),
    ("hard", 0.002, None, False, "afwerking", "installaties", "contact", "contact", "klein"),
    ("hard", 0.20, None, False, "constructie", "installaties", "beoordelen", None, "kritiek"),
    ("hard", 0.20, None, False, "afwerking", "installaties", "beoordelen", None, "groot"),
    ("hard", 0.01, None, False, "afwerking", "installaties", "beoordelen", None, "klein"),
    ("afstand", 0.03, None, False, "afwerking", "installaties", "beoordelen", None, "klein"),
    ("dubbel", 0.20, "verbonden", False, "constructie", "constructie", "beoordelen", None, "groot"),
])
def test_classify(soort, afstand, relatie, systeem, fa, fb, emmer, reden, ernst):
    r = classify(soort, afstand, relatie, systeem, fa, fb, None)
    assert (r.emmer, r.emmer_reden, r.ernst) == (emmer, reden, ernst)


def test_fixed_severity_only_for_the_review_bucket():
    assert classify("hard", 0.20, None, False, "afwerking", "installaties", "klein").ernst == "klein"
    assert classify("hard", 0.002, None, False, "afwerking", "installaties", "kritiek").ernst == "klein"


def test_category_is_sorted():
    assert classify("hard", 0.2, None, False, "installaties", "constructie", None).categorie == "constructie × installaties"
```

Op het proefmodel uit taak 1, met `run_checks([ClashCheck(set_a=[m], set_b=[m], soort="hard")])`:
- de deur en de wand: `aangrenzend` / `vulling`; de delen van het samenstel: `samenstel`; de verbonden wanden: `verbonden`; de leidingen: `zelfde_systeem`; balk en kolom: `aansluiting`; het kanaal in de vloer: `contact`;
- het kanaal door de dragende wand: `beoordelen`, `kritiek`, `constructie × installaties`, `raster` niet leeg, `ruimte == "Gang 1"`;
- `sum(emmers) == len(found)`;
- een model zonder raster of ruimte (`ifc_small`) geeft lege velden, en een `ModelContext` waarvan `raster` faalt (monkeypatch) laat de ronde gewoon slagen.

- [ ] **Step 2: Run:** `pytest tests/test_clash_context.py -q`. Expected: FAIL.

- [ ] **Step 3: Implement `clash_context.py`**

Constanten: `DEPTH_CONTACT_M = 0.005`, `DEPTH_SEVERE_M = 0.02`, `DEPTH_JOINT_M = 0.05`. Volgorde en families precies als spec 6.4. Diepte is `abs(afstand)`. Relaties alleen tussen elementen uit hetzelfde model. Verdieping met `_storey` uit `index/properties.py`. `raster`: assen uit `IfcGrid` (`UAxes`, `VAxes`, kromme `AxisCurve`) naar wereld met `ifcopenshell.util.placement.get_local_placement`, per richting de dichtstbijzijnde `AxisTag`, samen als `"C-4"`. `ruimte`: tweede iterator met `include=model.by_type("IfcSpace")`, alleen dozen; de kleinste die het punt bevat, over alle modellen van de ronde; `LongName` of anders `Name`. Elke contextfout (`Exception`) levert een leeg veld, nooit een mislukte ronde. De voortgang gaat van 0,9 naar 1,0 tijdens dit werk.

- [ ] **Step 4: Run:** `pytest tests/test_clash.py tests/test_clash_context.py -q`, ruff. Expected: PASS.

- [ ] **Step 5: Commit** `feat(kern): elke botsing krijgt emmer, ernst, categorie en plaats`

---

### Task 3: App: datamodel en rondes starten

**Files:**
- Modify: `frappe/openaec_bim/openaec_bim/openaec_bim/doctype/bim_botsing/bim_botsing.json`, `.../bim_botsingsronde/bim_botsingsronde.json`, `.../bim_project/bim_project.json`, `frappe/openaec_bim/openaec_bim/botsingen.py`, `frappe/openaec_bim/openaec_bim/kern.py`, `frappe/openaec_bim/openaec_bim/api_coordinatie.py`
- Test: `frappe/openaec_bim/openaec_bim/tests/test_botsingen.py`

**Interfaces:**
- Consumes: de tool-invoer van taak 1.
- Produces:
  - `kern.start_botsingen(controles: list[dict], doel: str) -> str`
  - `botsingen.start_controles(project, controles: list[dict], titel: str | None = None, voorinstelling: str | None = None) -> str`, met controle `{regel?, set_a: [{bestand, klassen?}], set_b: [...], soort, tolerantie, ernst?, alleen_tussen_modellen?}`
  - `botsingen.start(project, set_a, set_b, soort, tolerantie, titel=None)` blijft, roept `start_controles` aan
  - `ronde_naar_json` krijgt `regels`, `voorinstelling`, `reeks`, `voortgang`, `samenvatting`
  - `api_coordinatie.botsingsronde_start(map, set_a=None, set_b=None, soort="hard", tolerantie=0.0, titel=None, controles=None, voorinstelling=None)`

- [ ] **Step 1: Write the failing tests** (in `TestBotsingen`)

```python
def controle(self, **extra):
    return {"set_a": [{"bestand": self.constructie}], "set_b": [{"bestand": self.installaties}], "soort": "hard", "tolerantie": 0.0, **extra}

def test_een_ronde_met_voorinstelling_hoort_bij_haar_reeks(self):
    eerste = botsingen.start_controles(self.project, [self.controle()], voorinstelling="harde")
    self.lever(eerste, [("w1", "k1")])
    tweede = botsingen.start_controles(self.project, [self.controle(tolerantie=0.01)], voorinstelling="harde")
    doc = frappe.get_doc("BIM Botsingsronde", tweede)
    assert doc.reeks == "harde" and doc.vorige_ronde == eerste

def test_zonder_voorinstelling_is_de_reeks_de_sets_en_de_soort(self):
    a = botsingen.start(self.project, [{"bestand": self.constructie}], [{"bestand": self.installaties}], "hard", 0.0)
    self.lever(a, [("w1", "k1")])
    b = botsingen.start(self.project, [{"bestand": self.constructie}], [{"bestand": self.installaties}], "hard", 0.05)
    c = botsingen.start(self.project, [{"bestand": self.constructie}], [{"bestand": self.installaties}], "afstand", 0.05)
    assert frappe.db.get_value("BIM Botsingsronde", b, "vorige_ronde") == a
    assert not frappe.db.get_value("BIM Botsingsronde", c, "vorige_ronde")

def test_te_veel_controles_of_een_vreemd_bestand_wordt_geweigerd(self):
    with self.assertRaises(frappe.ValidationError):
        botsingen.start_controles(self.project, [self.controle()] * 31)
    with self.assertRaises(frappe.ValidationError):
        botsingen.start_controles(self.project, [{**self.controle(), "set_a": [{"bestand": "bestaat-niet"}]}])

def test_de_kern_krijgt_de_controles_met_adressen_en_versies(self):
    botsingen.start_controles(self.project, [self.controle(regel="r", ernst="kritiek", alleen_tussen_modellen=True)])
    verzoek = self.kern.laatste_botsingen  # of hoe de nep-kern in tests/hulp.py het verzoek bewaart
    assert verzoek["controles"][0]["regel"] == "r" and verzoek["controles"][0]["ernst"] == "kritiek"
    assert verzoek["controles"][0]["set_a"][0]["sleutel"] == self.constructie and "bron" in verzoek["controles"][0]["set_a"][0]

def test_soort_is_gemengd_bij_verschillende_soorten(self):
    naam = botsingen.start_controles(self.project, [self.controle(), self.controle(soort="afstand", tolerantie=0.05)])
    assert frappe.db.get_value("BIM Botsingsronde", naam, "soort") == "gemengd"
```

Pas de nep-kern in `tests/hulp.py` aan zodat ze het verzoek bewaart. `bijwerken` neemt `voortgang` over; test dat ook.

- [ ] **Step 2: Run** de app-tests. Expected: FAIL.

- [ ] **Step 3: Implement**

Velden als spec 7.1, ook `status` met de zes waarden en `soort` op de ronde met `dubbel` en `gemengd`. `reeks`: de voorinstelling, anders `"sets:" + sha1` van `_json([set_a, set_b, soort])` over de genormaliseerde vereniging, zonder tolerantie. `regels`: genormaliseerd, zoals spec 7.2. Validatie zoals nu in `start`, per controle. `titel` standaard `{voorinstelling of "Botsingen"} {datum tijd}`; laat de viewer de leesbare naam als `titel` meegeven.

- [ ] **Step 4: Run** migrate en de app-tests. Expected: PASS, ook de bestaande.

- [ ] **Step 5: Commit** `feat(openaec_bim): rondes met controles, in een reeks`

---

### Task 4: App: inlezen, ontwikkeling en issues die hun botsing volgen

**Files:**
- Modify: `frappe/openaec_bim/openaec_bim/botsingen.py`
- Test: `frappe/openaec_bim/openaec_bim/tests/test_botsingen.py`

**Interfaces:**
- Consumes: `start_controles`, kernvelden uit taak 2.
- Produces: `naar_json` geeft alle velden uit spec 7.1; `VELDEN` uitgebreid; `samenvatting` op de ronde zoals spec 7.3.

- [ ] **Step 1: Write the failing tests**

Breid `lever` uit met een optioneel `velden`-argument per paar. Tests, één per rij uit de tabel in spec 7.3, en daarnaast:

```python
def test_besluit_reden_en_nummer_gaan_mee(self):
    ronde = self.ronde_met([("w1", "k1"), ("w2", "k2")])
    rij = self.rij(ronde, "w1")
    botsingen.zet_status(rij.name, "genegeerd", "Is bedoeld")
    volgende = self.ronde_met([("w1", "k1"), ("w3", "k3")])
    nu = self.rij(volgende, "w1")
    assert (nu.status, nu.reden, nu.nummer, nu.ontwikkeling) == ("genegeerd", "Is bedoeld", rij.nummer, "blijft")
    assert self.rij(volgende, "w3").nummer == 3 and self.rij(volgende, "w3").ontwikkeling == "nieuw"

def test_weg_neemt_de_velden_over_en_telt_niet_in_de_emmers(self):
    ronde = self.ronde_met([("w1", "k1")], velden={"emmer": "contact", "ernst": "klein", "verdieping": "00"})
    volgende = self.ronde_met([])
    rij = self.rij(volgende, "w1")
    assert (rij.status, rij.ontwikkeling, rij.emmer, rij.verdieping) == ("opgelost", "weg", "contact", "00")
    s = json.loads(frappe.db.get_value("BIM Botsingsronde", volgende, "samenvatting"))
    assert s["totaal"] == 0 and sum(s["per_emmer"].values()) == 0 and s["weg"] == 1

def test_een_lege_ronde_zonder_vorige_is_gewoon_klaar(self): ...  # status klaar, aantal 0, samenvatting met nullen

def test_samenvatting_open_telt_alleen_de_emmer_beoordelen(self): ...

def test_een_oud_resultaat_zonder_nieuwe_velden_wordt_gelezen(self): ...  # emmer beoordelen, soort van de ronde

def test_de_discipline_is_de_submap_of_anders_de_bestandsnaam(self): ...  # model direct in de modelmap

def test_een_issue_sluit_als_de_botsing_weg_is_en_heropent(self):
    ronde = self.ronde_met([("w1", "k1")])
    rij = self.rij(ronde, "w1")
    issue = botsingen.naar_issue(rij.name)["guid"]
    frappe.db.set_value("BIM Issue", issue, "status", "In behandeling")
    weg = self.ronde_met([])
    assert frappe.db.get_value("BIM Issue", issue, "status") == "Opgelost"
    assert self.rij(weg, "w1").issue_status_voor == "In behandeling"
    terug = self.ronde_met([("w1", "k1")])
    assert frappe.db.get_value("BIM Issue", issue, "status") == "In behandeling"
    assert self.rij(terug, "w1").ontwikkeling == "terug" and not self.rij(terug, "w1").issue_status_voor
    # beide keren een reactie
    assert frappe.db.count("BIM Reactie", {"issue": issue}) == 2

def test_geen_heropening_na_een_eigen_wijziging(self): ...  # na weg zelf op Gesloten zetten: blijft Gesloten

def test_een_gewijzigde_ronde_sluit_geen_issues(self): ...  # andere tolerantie, zelfde reeks: issue blijft open, samenvatting.regels_gewijzigd

def test_zonder_status_opgelost_de_laatste_van_het_project(self): ...

def test_een_verwijderd_issue_stopt_het_inlezen_niet(self): ...  # rij met issue dat niet meer bestaat
```

Voeg in de testklasse `rij(ronde, globalid)` toe die de rij met dat element in `element_a` geeft.

- [ ] **Step 2: Run** de app-tests. Expected: FAIL.

- [ ] **Step 3: Implement** `verwerk`, de overgangstabel en `_issue_volgt`

Tolerant lezen met `.get`. `verwerk` zet ook `disciplines` uit `api.ifc_in_map`: `f"{a} × {b}"`, gesorteerd; zonder submap de bestandsnaam zonder `.ifc`. Reactie via `issues._nieuwe_reactie(issue, {"comment": tekst}, auteur="Botsingsronde")`, met `frappe.flags.bim_bron = "achtergrond"` (herstel de vorige waarde daarna). `bulk_insert` zoals nu, met de nieuwe kolommen. `verwerk` blijft draaien in `afgeleid.zonder_botsing` via `bijwerken`.

- [ ] **Step 4: Run** de app-tests. Expected: PASS.

- [ ] **Step 5: Commit** `feat(openaec_bim): ontwikkeling per ronde, samenvatting, en issues die hun botsing volgen`

---

### Task 5: App: beoordelen, regels, weergaven en verloop

**Files:**
- Modify: `frappe/openaec_bim/openaec_bim/botsingen.py`, `frappe/openaec_bim/openaec_bim/api_coordinatie.py`
- Test: `frappe/openaec_bim/openaec_bim/tests/test_botsingen.py`, `tests/test_api.py` als de API daar getest wordt

**Interfaces:**
- Produces:
  - `zet_status(botsing: str, status: str, reden: str | None = None) -> dict`
  - `zet_status_veel(botsingen: list[str], status: str, reden: str | None = None) -> list[dict]`
  - `instellingen(project) -> {"regels", "weergaven", "mag_wijzigen"}`
  - `instellingen_bewaar(project, regels=None, weergaven=None) -> zelfde vorm`
  - `trends(ronde: str) -> list[{"naam","titel","gestart","samenvatting"}]`
  - API zoals spec 7.8

- [ ] **Step 1: Write the failing tests**

```python
def test_afwijzen_met_reden_en_wie(self):
    rij = self.rij(self.ronde_met([("w1", "k1")]), "w1")
    uit = botsingen.zet_status(rij.name, "genegeerd", "Bedoeld zo")
    assert uit["reden"] == "Bedoeld zo" and uit["beoordeeld_door"] == frappe.session.user and uit["beoordeeld_op"]

def test_een_te_lange_reden_of_reden_bij_een_andere_status(self):
    rij = self.rij(self.ronde_met([("w1", "k1")]), "w1")
    with self.assertRaises(frappe.ValidationError):
        botsingen.zet_status(rij.name, "genegeerd", "x" * 201)
    botsingen.zet_status(rij.name, "genegeerd", "ok")
    assert botsingen.zet_status(rij.name, "actief")["reden"] is None

def test_bevestigen_maakt_een_issue_met_namen(self):
    ronde = self.ronde_met([("w1", "k1")], namen={"w1": "Wand B 0", "k1": "Kanaal"})
    uit = botsingen.zet_status(self.rij(ronde, "w1").name, "bevestigd")
    assert uit["issue"] and "Wand B 0" in frappe.db.get_value("BIM Issue", uit["issue"], "titel")
    assert botsingen.zet_status(self.rij(ronde, "w1").name, "bevestigd")["issue"] == uit["issue"]

def test_groepsactie_met_grens_en_rechten(self): ...  # 501 geweigerd; een lezer geweigerd; rijen uit twee rondes elk gecontroleerd

def test_regels_en_weergaven_bewaren(self):
    regels = [{"a": "Constructie", "b": "Installaties", "soort": "hard", "mm": 0, "ernst": None}]
    weergaven = [{"naam": "Kritiek", "filter": {"ernst": ["kritiek"]}, "groep": "verdieping"}]
    botsingen.instellingen_bewaar(self.project, regels, weergaven)
    uit = botsingen.instellingen(self.project)
    assert uit["regels"] == regels and uit["weergaven"] == weergaven and uit["mag_wijzigen"]

def test_ongeldige_regels_of_weergaven_worden_geweigerd(self): ...  # onbekende soort; negatieve mm; dubbele naam; meer dan 50 weergaven

def test_een_lezer_mag_lezen_maar_niet_bewaren(self): ...

def test_verloop_volgt_de_keten_met_de_oudste_eerst(self): ...  # drie rondes; hoogstens 20
```

`lever` krijgt `namen` voor `element.naam`.

- [ ] **Step 2: Run** de app-tests. Expected: FAIL.

- [ ] **Step 3: Implement**

`naar_issue`: titel `Botsing {naam a} / {naam b}`, met de klasse als er geen naam is; omschrijving met de verdieping en de GlobalIds. Rijen bijwerken met `doc.save` en `issues._vereis...` zoals nu, één rechtencontrole per ronde in `zet_status_veel`. Foutcodes: `reden_te_lang`, `te_veel_botsingen`, `regels_ongeldig`, `weergave_ongeldig`.

- [ ] **Step 4: Run** de app-tests. Expected: PASS. Draai ook de hele app: `frappe-test.sh openaec_bim.tests.test_api`, `openaec_bim.tests.test_bcfzip`.

- [ ] **Step 5: Commit** `feat(openaec_bim): beoordelen met reden, regels, weergaven en verloop`

---

### Task 6: Gastpagina: de nieuwe berichten

**Files (in `../openaec-bench-bim`):**
- Modify: `frontend/apps/werkplek/src/gast/bim-berichten.ts`, `frontend/apps/werkplek/test/bim.test.ts`, `docs/werkplek.md`

**Interfaces:**
- Consumes: de API uit taak 3 en 5.
- Produces: `bim.botsingsronde_start {controles?, voorinstelling?, titel?, set_a?, set_b?, botsingsoort?, tolerantie?}`, `bim.botsing_status {botsing, status, reden?}`, `bim.botsing_status_veel {botsingen, status, reden?}`, `bim.botsing_instellingen {}`, `bim.botsing_instellingen_bewaar {regels?, weergaven?}`, `bim.botsing_trends {ronde}`.

- [ ] **Step 1: Write the failing tests** in `bim.test.ts`, in de stijl van de bestaande: elk bericht roept de juiste methode met `map` uit de pagina; `controles` met een bestand buiten het laatste `bim.project` wordt geweigerd; een onbekende status wordt geweigerd; de statussen `bevestigd` en `geaccepteerd` mogen; `reden` gaat alleen mee als het tekst is; `botsingen` moet een lijst namen zijn.

- [ ] **Step 2: Run** `npx vitest run apps/werkplek/test/bim.test.ts`. Expected: FAIL.

- [ ] **Step 3: Implement.** Hergebruik `set()` voor de sets van elke controle; `soort` in een controle is een veld van de controle, niet de berichtsoort. Geef alleen bekende velden door.

- [ ] **Step 4: Run** de test en `bash scripts/build-frontend.sh`. Expected: PASS en een geslaagde bouw. Werk de berichtenlijst bovenin het bestand en `docs/werkplek.md` bij.

- [ ] **Step 5: Commit** (in `openaec-bench-bim`, niet pushen) `feat(bim): berichten voor controles, beoordelen, regels en verloop`

---

### Task 7: Viewer: logica en berichten

**Files:**
- Modify: `viewer/src/model/bcf.ts`, `viewer/src/model/clashes.ts`, `viewer/src/model/clashes.test.ts`, `viewer/src/host/BimHost.ts`, `viewer/src/host/WerkplekHost.ts`, `viewer/src/host/WerkplekHost.test.ts`

**Interfaces:**
- Produces in `bcf.ts`: `ClashKind`, `ClashBucket`, `ClashSeverity`, `ClashDevelopment`, de uitgebreide `ClashStatus` en `Clash`, `ClashElement` met `klasse`, `naam`, `verdieping`; `ClashCheck`, `ClashRule`, `ClashFilter`, `ClashGroupBy`, `ClashView`, `ClashSettings`, `ClashTrend`, `ClashSummary`.
  - `ClashFilter`: `{emmer: ClashBucket | "weg" | null; ernst: ClashSeverity[]; status: ClashStatus[]; categorie: string[]; disciplines: string[]; verdieping: string[]; ontwikkeling: ClashDevelopment[]; tekst: string}`
  - `ClashGroupBy`: `"klassen"|"verdieping"|"disciplines"|"ernst"|"categorie"|"raster"|"ruimte"|"ontwikkeling"`
- Produces in `clashes.ts`:
  - `STATUSSEN`, `leegFilter(): ClashFilter` (emmer `beoordelen`)
  - `disciplineVan(model: ModelInfo): string`
  - `voorinstellingen(modellen: ModelInfo[]): Voorinstelling[]`, met `Voorinstelling = {id: string; controles: ClashCheck[]; beschikbaar: boolean; reden: string | null; instelbaar: boolean}`; `reden` is een vertaalsleutel; ids: `harde`, `constructie_installaties`, `wanden_installaties`, `tussen_modellen`, `bijna`, `dubbel`, `regels`
  - `bijnaMet(mm: number, modellen: ModelInfo[]): ClashCheck[]`
  - `controlesUitRegels(regels: ClashRule[], modellen: ModelInfo[]): ClashCheck[]`
  - `standaardRegels(disciplines: string[], bewaard: ClashRule[]): ClashRule[]`
  - `overlapWaarschuwing(a: ModelInfo[], b: ModelInfo[]): boolean`
  - `filter(botsingen: Clash[], f: ClashFilter): Clash[]`
  - `facetten(botsingen: Clash[], f: ClashFilter): Record<keyof Facetten, Record<string, number>>`
  - `emmerTelling(botsingen: Clash[]): Record<ClashBucket, number>`
  - `groepeer(botsingen: Clash[], op: ClashGroupBy): {groep: string | null; botsingen: Clash[]}[]`
  - `volgende(lijst: Clash[], huidige: string | null): string | null`, `vorige(...)`
  - `elementNaam(e: ClashElement): string`, `isGevonden(b: Clash): boolean`
  - `sneltoets(e: Pick<KeyboardEvent,"key"|"ctrlKey"|"altKey"|"metaKey"> & {target: unknown}): SneltoetsActie | null`
- Produces in `Coordinatie`: `botsingsrondeControles(controles, voorinstelling, titel?)`, `botsingStatus(botsing, status, reden?)`, `botsingStatusVeel(botsingen, status, reden?)`, `botsingInstellingen()`, `botsingInstellingenBewaar({regels?, weergaven?})`, `botsingTrends(ronde)`.

- [ ] **Step 1: Write the failing tests** in `clashes.test.ts`

```ts
test("constructie tegen installaties is niet beschikbaar zonder installaties, met reden", ...);
test("tussen modellen vraagt twee modellen", ...);
test("een model zonder submap krijgt de bestandsnaam als discipline", () => {
  expect(disciplineVan(model({ naam: "woning.ifc", discipline: "" }))).toBe("woning");
});
test("regels: uit en paren zonder modellen vallen af; mm wordt meter", ...);
test("standaardregels: hard tussen disciplines, uit binnen een discipline, bewaard gaat voor", ...);
test("overlapwaarschuwing met 1 m marge, en niet zonder dozen", ...);
test("het filter en de aantallen per waarde binnen de overige filters", ...);
test("de emmertelling telt alleen gevonden rijen; de som is het totaal", ...);
test("weg toont alleen ontwikkeling weg; eerder_weg alleen met het filter op ontwikkeling", ...);
test("groeperen: grootste eerst, lege waarden samen", ...);
test("volgende springt naar de eerstvolgende te beoordelen, en rond", () => {
  const lijst = [b("a", "genegeerd"), b("b", "nieuw"), b("c", "bevestigd"), b("d", "actief")];
  expect(volgende(lijst, "b")).toBe("d");
  expect(volgende(lijst, "d")).toBe("b");
  expect(volgende([b("a", "genegeerd"), b("c", "bevestigd")], "a")).toBe("c");
  expect(volgende([b("c", "bevestigd")], "c")).toBe("c");
});
test("een element zonder naam heet naar zijn klasse", () => {
  expect(elementNaam({ ...element, naam: null, klasse: "IfcWall" })).toBe("IfcWall");
});
test("geen sneltoets in een veld of met Ctrl", () => {
  const veld = { tagName: "INPUT" };
  expect(sneltoets({ key: "b", ctrlKey: false, altKey: false, metaKey: false, target: veld })).toBeNull();
  expect(sneltoets({ key: "b", ctrlKey: true, altKey: false, metaKey: false, target: null })).toBeNull();
  expect(sneltoets({ key: "x", ctrlKey: false, altKey: false, metaKey: false, target: null })).toBe("afwijzen");
});
```

Plus in `WerkplekHost.test.ts`: elke nieuwe methode stuurt het bericht uit taak 6.

- [ ] **Step 2: Run** `npx vitest run src/model/clashes.test.ts src/host/WerkplekHost.test.ts`. Expected: FAIL.

- [ ] **Step 3: Implement.** Klassenlijsten als `const` boven in `clashes.ts`: `KLASSEN_CONSTRUCTIE = ["IfcBeam","IfcColumn","IfcFooting","IfcPile","IfcMember","IfcSlab","IfcWall"]`, `KLASSEN_VLAK = ["IfcWall","IfcSlab"]`; aanwezigheid van installaties met een regex op bekende klassen (`IfcFlow*`, `IfcDistribution*`, `IfcDuct*`, `IfcPipe*`, `IfcCable*`, `IfcAirTerminal`, `IfcLightFixture`, `IfcSanitaryTerminal`, `IfcValve`, `IfcPump`, `IfcFan`, enzovoort). Sleutels die een vertaling nodig hebben blijven sleutels; de schermen vertalen.

- [ ] **Step 4: Run** de tests en `npx tsc --noEmit`. `ClashPanel.tsx` mag hier nog fouten geven door de nieuwe velden: maak velden optioneel waar nodig of pas de bestaande regels minimaal aan, zodat `tsc` schoon blijft. Expected: PASS.

- [ ] **Step 5: Commit** `feat(viewer): logica voor filteren, groeperen, snelle keuzes en sneltoetsen`

---

### Task 8: Viewer: het paar geïsoleerd in beeld

**Files:**
- Modify: `viewer/src/engine/FragmentsEngine.ts`, `viewer/src/ui/weergave.ts`, `viewer/src/ui/App.tsx`, `viewer/src/ui/app.css`
- Test: `viewer/e2e/smoke.spec.ts` als de lokale route het kan, anders dekt taak 11 het

**Interfaces:**
- Produces:
  - `Weergave.isoleer(a: ElementRef, b: ElementRef, punt: Vec3): Promise<void>`, `Weergave.naarElement(e: ElementRef): Promise<void>`, `Weergave.herstel(): Promise<void>`
  - `FragmentsEngine.isolate(a: Target[], b: Target[], point: Vec3): Promise<void>`, `FragmentsEngine.focusElements(targets: Target[]): Promise<void>`, `FragmentsEngine.clearIsolation(): Promise<void>`, met `Target = {keys: string[]; globalid: string}`
  - App: kolom 360 px op *Issues* en *Botsingen*, via een modifier op `.viewer__body--inspector`; `herstel()` bij wisselen van tabblad.

- [ ] **Step 1: Implement** met `model.setOpacity(undefined, 0.12)`, `model.resetOpacity([id])` en `model.highlight([id], material)`, per model in `fragments.list`. Twee materialen: A uit `--theme-accent`, B uit de informatiekleur van het stijlboek (`--color-semantic-info`, of de token die er is). De camera: `focus` op het punt, straal uit `model.getMergedBox`, hoogstens 10 m. Elke stap via de bestaande wachtrij `later`, zodat snel doorklikken in volgorde loopt.

- [ ] **Step 2: Verify** op de bench met de demomodellen, na een bouw zoals in taak 11: paar in twee kleuren, de rest doorzichtig, *Alles tonen* zet terug. Meet de tijd van `isolate` op beide modellen samen (288 MB). Blijft die boven de seconde, val dan terug op alleen markeren plus camera, en noteer dat voor de meting.

- [ ] **Step 3: Run** `npx tsc --noEmit && npx vitest run`. Expected: PASS.

- [ ] **Step 4: Commit** `feat(viewer): een botsing isoleert het paar in beeld`

---

### Task 9: Viewer: starten en regels

**Files:**
- Create: `viewer/src/ui/ClashStart.tsx`, `viewer/src/ui/ClashRules.tsx`
- Modify: `viewer/src/ui/ClashPanel.tsx`, `viewer/src/i18n/nl.json`, `viewer/src/i18n/en.json`, `viewer/src/ui/app.css`

**Interfaces:**
- Consumes: `voorinstellingen`, `bijnaMet`, `controlesUitRegels`, `standaardRegels`, `overlapWaarschuwing`, de `Coordinatie`-methoden uit taak 7.
- Produces: `ClashStart({coordinatie, modellen, instellingen, onKlaar})`, `ClashRules({coordinatie, modellen, instellingen, onKlaar})`. `ClashPanel` laadt `botsingInstellingen()` en toont `ClashStart` bij *Nieuwe ronde*, met een knop *Regels*.

- [ ] **Step 1: Implement** volgens spec 9.2 en 9.3:
- een kaart per voorinstelling, in één kolom, met titel en uitleg; niet-beschikbare uitgeschakeld met de reden;
- *Bijna-botsingen* met een mm-veld, standaard 50;
- *Zelf instellen* opent het bestaande formulier, dat ook via `botsingsrondeControles` start, zonder voorinstelling;
- de overlapwaarschuwing boven de startknop, met de naam van de gekozen voorinstelling als titel van de ronde;
- de voortgang in de rondelijst als percentage;
- regels: per paar disciplines soort, mm, ernst. Bewaren alleen met `mag_wijzigen`.

- [ ] **Step 2: Verify:** `npx tsc --noEmit && npx vitest run`, en de bestaande teksten in `nl.json` en `en.json` zijn compleet: elke nieuwe sleutel staat in beide. Expected: PASS.

- [ ] **Step 3: Commit** `feat(viewer): een ronde starten met snelle keuzes, en regels per disciplinepaar`

---

### Task 10: Viewer: de ronde als werklijst

**Files:**
- Create: `viewer/src/ui/ClashRound.tsx`, `viewer/src/ui/ClashFilters.tsx`, `viewer/src/ui/ClashTrends.tsx`
- Modify: `viewer/src/ui/ClashPanel.tsx`, `viewer/src/i18n/nl.json`, `viewer/src/i18n/en.json`, `viewer/src/ui/app.css`

**Interfaces:**
- Consumes: alles uit taak 7 en 8.
- Produces: `ClashRound({coordinatie, weergave, ronde, modellen, instellingen, onInstellingen, onTerug})`.

- [ ] **Step 1: Implement** volgens spec 9.4 en 9.5, met `data-*`-attributen die de proef kan vinden (`data-emmer`, `data-botsing`, `data-groep`):
- emmerbalk, regel met open, nieuw en weg; bij `regels_gewijzigd` één regel uitleg;
- inklapbaar verloop: staafjes in SVG met tokens, plus een tabel;
- filters met aantallen, chips die je kunt wegklikken, tekstzoeker over namen en GlobalIds;
- weergaven kiezen en bewaren; groeperen op;
- groepen inklapbaar, eerste 100 rijen plus *Meer*, groepsactie met bevestiging via `botsingStatusVeel`;
- rij en opengeklapte rij met knoppen, `Naar A`, `Naar B`, `Alles tonen`;
- afwijzen: invoerregel met reden, Enter bevestigt, Esc annuleert;
- sneltoetsen via `sneltoets` op `window`, opgeruimd bij het verlaten; `?` toont de lijst;
- `isoleer` bij de focus op een rij, `herstel` bij *Alles tonen*, `Esc` en het verlaten van de ronde;
- lege toestanden: geen botsingen in deze emmer, met een knop om de filters te wissen; een ronde zonder botsingen zegt dat ook.

De oude `Ronde` en `verberg_afgehandeld` vervallen.

- [ ] **Step 2: Verify:** `npx tsc --noEmit && npx vitest run && npm run build && npm run check:geen-cdn`. Expected: PASS.

- [ ] **Step 3: Commit** `feat(viewer): een ronde als werklijst met emmers, filters en sneltoetsen`

---

### Task 11: Acceptatie, meting en documentatie

**Files:**
- Modify (in `../openaec-bench-bim`): `scripts/werkplek-e2e/bim-coordinatie.mjs`, `scripts/werkplek-versies.txt`
- Create: `docs/metingen/2026-botsingen-beoordelen.md`
- Modify: `README.md`, `docs/superpowers/specs/2026-10-26-open-bim-platform-design.md` (hoofdstuk 5.6 en 9, een verwijzing)

**Interfaces:**
- Consumes: alles.

- [ ] **Step 1: Bouw de bench op de nieuwste commit**

Migrate; de kern: `docker build -f ../open-bim-platform/kern/Dockerfile -t openbim-kern ../open-bim-platform` en `MSYS_NO_PATHCONV=1 docker compose -f compose.yaml -f compose.bim.yaml up -d bim-kern bim-werker`; de regel `bim` in `werkplek-versies.txt` op de nieuwe commit, ref `fase-1c-botsingen-beoordelen`; `bash scripts/build-werkplek.sh bim` en `bash scripts/build-frontend.sh`. Staat de webserver niet aan: `bash scripts/start.sh` met `compose.bim.yaml` of `bench start` zoals in die scripts.

- [ ] **Step 2: Breid de werkplekproef uit en draai ze**

De bestaande controles blijven. Pas de stappen aan die oude schermen gebruiken. Nieuw, elk met `eis`:
- een ronde gestart met *Constructie tegen installaties*;
- de emmerbalk telt op tot het totaal;
- groeperen op verdieping toont een groep;
- `J` springt naar de volgende en `X` met een reden wijst af;
- bevestigen maakt een issue;
- de tweede ronde (nieuwe versie) toont de afwijzing met reden en de ontwikkeling;
- het issue van een botsing die weg is, staat op `Opgelost` met een reactie;
- het paar staat geïsoleerd in beeld (schermafbeelding in `<uitmap>`);
- geen fouten in de pagina.

Commando: `WP_BASIS=http://klant0.cloud.open-aec.localhost:8001 node bim-coordinatie.mjs <uit> <modellen>` in `scripts/werkplek-e2e`, met de modellen in `C:/Users/rickd/AppData/Local/Temp/claude/C--Users-rickd-Documents-GitHub-open-bim-platform/c6af30aa-5dc5-42da-9d3f-c75d62f1cd78/scratchpad/modellen`. Expected: alle controles OK, exit 0.

- [ ] **Step 3: Meet op de demomodellen**

In de ruimte *Demo Open BIM* een ronde *Tussen modellen* en een *Harde botsingen*. Noteer in `docs/metingen/2026-botsingen-beoordelen.md`: duur, aantallen per emmer en ernst, drie steekproeven per emmer of de indeling klopt, de tijd van isoleren, en eventueel bijgestelde drempels met reden. Beschrijf echte tekortkomingen; niets mooier maken. Noem geen andere programma's.

- [ ] **Step 4: Werk `README.md` bij** met een korte alinea onder *Coördinatie*, en een verwijzing in het hoofdontwerp naar dit ontwerp.

- [ ] **Step 5: Commit** in beide repo's: `docs(metingen): botsingen beoordelen in de werkplek` en `test(werkplek-e2e): een ronde beoordelen met emmers, sneltoetsen en reden`.
