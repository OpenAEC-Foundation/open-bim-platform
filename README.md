# Open BIM Platform

3D-samenwerkingsomgeving voor de OpenAEC SuperCloud: modellen bekijken, samenvoegen en bespreken, rechtstreeks op de
bestanden in de opslag van de klantomgeving.

Status: fase 0 (fundament) is af en geaccepteerd: tien IFC-bestanden van samen 5,55 GB omgezet, het grootste
(1,76 GB) in vijf delen, en de viewer laadt ze tot zijn geheugenbudget op een laptop met een ingebouwde GPU. Fase 1a
(de viewer in de werkplek van de SuperCloud) draait op de ontwikkelbench. Fase 1b (coördinatie: issues met BCF 3.0,
de BCF-API, de versiekoppeling, het auditlog en botsingsrondes) is gebouwd en in de werkplek geaccepteerd; zie de
meting van fase 1b.

## Documenten

| Document | Inhoud |
|---|---|
| [Ontwerp](docs/superpowers/specs/2026-10-26-open-bim-platform-design.md) | doelen, architectuur, rechten, werkwijzen, roadmap, kosten |
| [Elementopslag en relatiegraaf](docs/superpowers/specs/2026-10-28-elementopslag-en-relatiegraaf.md) | opslag per element na fase 1, met een proef op echte modellen; besloten voor fase 2 |
| [Plan fase 0](docs/superpowers/plans/2026-10-26-fase-0-fundament.md) | kern, omzetten met splitsen, viewer, lokale route |
| [Plan fase 1a](docs/superpowers/plans/2026-10-28-fase-1a-werkplek.md) | platform-app `openaec_bim` en de viewer in de werkplek |
| [Meting fase 0](docs/metingen/2026-fase-0.md) | tijden en geheugen per stap, de viewer op het budget, de proef in de werkplek |
| [Plan fase 1b](docs/superpowers/plans/2026-10-29-fase-1b-coordinatie.md) | issues (BCF 3.0), BCF-API, versiekoppeling, auditlog, botsingen |
| [Conformiteit BCF-API](docs/bcf-conformiteit.md) | de paden van de BCF-API 3.0 op de klantsite, de test en de laatste uitslag |
| [Meting fase 1b](docs/metingen/2026-fase-1b.md) | de acceptatie van de coördinatie in de werkplek, tijden van koppelen en botsen |

**Fase 1** maakt issues met BCF 3.0 als datamodel, direct gevolgd door de BCF-API 3.0, en een koppeling van elementen
over versies heen (op GlobalId, met een terugval als een exporteur GlobalIds verandert), zodat issues en botsingen een
nieuwe versie overleven; alles in een auditlog. **Fase 2** brengt de ISO 19650-werkwijze voor informatiecontainers
(staten, codes, controle en goedkeuring, met IDS als poort naar gepubliceerd), het vergelijken van versies per element
en de opslag per element: geometrie als meshes per hash met een manifest per versie (een nieuwe versie voegt alleen
haar nieuwe meshes toe), een tabel met alle relaties in de index en de eigenschappen kolomgericht per versie.

## Ontwikkelen

De BIM-kern staat in `kern/`: het Python-pakket `openbim_kern` (IfcOpenShell) met een Node-omzetter in
`kern/converter/` (`@thatopen/fragments`). Nodig: Python 3.12 en Node 24.

```bash
cd kern
python -m venv .venv
.venv/bin/pip install -e ".[test]"   # Windows: .venv\Scripts\pip
cd converter && npm ci
```

### Lokaal starten

Een map met IFC-modellen openen met de lokale ontwikkelserver:

```bash
openbim-kern lokaal <map>
```

Dit start de kern op poort 8730, de werker en de lokale server op `http://127.0.0.1:8740`. `GET /lokaal/project`
toont de modellen in de map; `POST /lokaal/omzetten` zet ze om. De afgeleide gegevens komen in `<map>/.afgeleid/`.
Alles luistert alleen op 127.0.0.1.

De onderdelen ook los:

- `openbim-kern serve`: de rekenkern, HTTP op `/v1` en MCP op `/mcp`; sleutels in `OPENBIM_KERN_SLEUTELS`.
- `openbim-kern werker`: voert de lange taken uit de wachtrij uit.
- `openbim-kern omzetten <ifc> <uitmap>`: zet één bestand om op schijf, zonder server.

### Omzetten en geheugen

Per bestandsversie maakt de kern het weergavebestand voor de viewer (`.frag`, met `@thatopen/fragments` in Node) en
de eigenschappen-index, de ruimtelijke boom en een samenvatting (IfcOpenShell). Bestanden boven 1,5 GB worden eerst
gesplitst; elk deel wordt een eigen `.frag`. Elke stap draait in een eigen proces onder een geheugen- en tijdsgrens.
Richtgetallen uit de meting van fase 0:

- IfcOpenShell (de index): 12–13 GB geheugen per GB IFC; daarom delen van 0,4 tot 1 GB.
- Fragments: ~3,8 × de bestandsgrootte.
- Splitsen: ~6,4 × de bestandsgrootte, lineair in de tijd (0,42 GB in 53 s). De splitser leest het bestand regel
  voor regel met tegendruk (`kern/converter/lines.mjs`).

### Viewer

De viewer staat in `viewer/`: React en Vite met That Open (fragments) en de huisstijl uit het OpenAEC-stijlbook
(overgenomen in `viewer/vendor/`, tot de pakketten op npm staan). Met `openbim-kern lokaal <map>` draaiend:

```bash
cd viewer
npm ci
npm run dev        # http://127.0.0.1:5173
```

De viewer laadt via de host-laag; lokaal is dat de lokale server (`VITE_OPENBIM_LOKAAL`, standaard
`http://127.0.0.1:8740`). De worker van fragments komt uit de bundel, nooit van een CDN: `npm run build && npm run
check:geen-cdn` controleert dat.

### In de SuperCloud (werkplek)

`frappe/openaec_bim` is de platform-app op de klantsite (Frappe, naast OpenAEC Storage en de werkplek). Een modelmap in
Storage is het project: de app laat elke IFC-versie door de BIM-kern omzetten (met ondertekende S3-adressen), volgt de
taken en geeft de gastpagina van de werkplek de delen en eigenschappen, steeds met de rechten van Storage. De viewer
draait als werkplek-app `bim`: de tegel op het startscherm van de werkplek opent hem als tool in de schil
(`/werkplek/open/bim`), met eerst een venster om de modelmap te kiezen (`/werkplek/bim?map=<id>`). Hij praat via de
werkplekbrug in `bim.*`-berichten (`viewer/src/host/WerkplekHost.ts`). De werkplekkant (gastpagina, adapter,
bouwstap, lokale MinIO en kern) staat in `openaec-bench`, branch `bouw/bim-werkplek`; zie `docs/werkplek.md` daar.
De browserproef met grote modellen via de GUI (uploaden in Docs, de tegel, omzetten, laden, aanklikken) is
`scripts/werkplek-e2e/bim-proef.mjs` in dezelfde branch. Plan: `docs/superpowers/plans/2026-10-28-fase-1a-werkplek.md`.

**Coördinatie (fase 1b).** In de werkplek heeft de viewer rechts de tabbladen Eigenschappen, Issues en Botsingen.
Issues volgen het datamodel van BCF 3.0 (`openaec_bim.issues`): een nieuw issue neemt de camera, de selectie en een
schermafbeelding met markering mee; export en import als `.bcfzip` (2.1 en 3.0) in de modelmap. Na elke nieuwe
omgezette versie koppelt de kern de elementen aan de vorige versie (op GlobalId, met een terugval op plaats en naam);
issues en botsingen volgen hun elementen zo naar de versie in beeld, en de modellijst noemt de matchrate. Een
botsingsronde (hard of afstand) rekent op de versies van het moment van starten; een volgende ronde volgt de botsingen
van de vorige. Elke wijziging komt in het auditlog (`BIM Auditregel`, met de bron). Voor controle- en
ontwerpprogramma's biedt de klantsite de BCF-API 3.0 met de Foundation API 1.1 op `/bcf/3.0` en `/foundation`
(OAuth2 van Frappe of een API-sleutel); zie [Conformiteit BCF-API](docs/bcf-conformiteit.md). De acceptatie in de
werkplek is `scripts/werkplek-e2e/bim-coordinatie.mjs` in `openaec-bench`. Plan:
`docs/superpowers/plans/2026-10-29-fase-1b-coordinatie.md`.

Nog een besluit van de eigenaar: prijsniveau en status in de catalogus, welke app een `.ifc` standaard opent (nu de
planner), en een machine met genoeg geheugen voor het omzetten op staging.

### Tests

```bash
cd kern
pytest
ruff check src tests scripts && ruff format --check src tests scripts
cd ../viewer
npx vitest run
npm run test:e2e     # browserproef: kern, lokale server en viewer samen (Playwright)
```

### Meten

Een groot, geldig IFC voor metingen maken, een variant voor proeven (klassen houden of weglaten, een deel van de
GlobalIds vervangen) en een map met modellen doormeten:

```bash
cd kern
python scripts/enlarge.py <in.ifc> <factor> <uit.ifc>
python scripts/variant.py <in.ifc> <uit.ifc> [--alleen IfcWall] [--zonder IfcDuctSegment] [--nieuwe-globalids 0.5]
python scripts/measure.py <map> --uit <rapport.md>
```

`measure.py` zet elk model om in een eigen proces en schrijft per bestand de grootte, de duur per stap en het
piekgeheugen van de omzetter en van IfcOpenShell. De uitvoer komt in `<map>/.afgeleid/`, zodat `openbim-kern lokaal
<map>` en de viewer de map daarna meteen openen. Met `--hervat` slaat hij bestanden over die al gemeten zijn.

Voor de opslag per element meet `storage_study.py` de semantische graaf (als tabellen en in een graafopslag), de
index en de geometrie per element, met een hash die niet van de volgorde afhangt, binnen een versie en tussen twee
versies:

```bash
python scripts/storage_study.py <model.ifc> [--vorige <vorige versie.ifc>] [--frag] [--uit <rapport.json>]
```

### Container

```bash
cd kern
OPENBIM_KERN_SLEUTELS=<sleutel> docker compose up --build
```

Dit start de kern op poort 8730 en de werker, uit dezelfde image, met de wachtrij en werkmappen op het volume `/data`.
De image wordt gebouwd vanuit de hoofdmap van de repo, omdat de licentieteksten en de releasescripts daar staan:
`docker build -f kern/Dockerfile -t openbim-kern .`. In de image staan naast de kern `COPYING`, `COPYING.LESSER`,
`bron.json` en `THIRD-PARTY-NOTICES.txt`: alle Python-distributies, de npm-pakketten van de omzetter, Python en
Node.js zelf en de Debian-pakketten van het basisimage, elk met een link naar de broncode van precies die versie.

### Instellingen

| Variabele | Standaard | Betekenis |
|---|---|---|
| `OPENBIM_KERN_SLEUTELS` | (verplicht voor `serve`) | API-sleutels, komma-gescheiden |
| `OPENBIM_KERN_DATA` | tijdelijke map | wachtrij (`taken.sqlite`), cache en werkmappen |
| `OPENBIM_OMZETTER_CMD` | `node converter/convert.mjs` | opdracht voor de omzetter |
| `OPENBIM_SPLITS_VANAF_BYTES` | `1500000000` | bestanden hierboven worden gesplitst |
| `OPENBIM_DEEL_BYTES` | `1000000000` | doelgrootte van een deel bij splitsen |
| `OPENBIM_GEHEUGEN_GRENS_BYTES` | 3 × grootte + 1 GB (splitsen: 7 × grootte + 1 GB) | geheugengrens per omzetproces; de heap van Node groeit tot deze grens mee |
| `OPENBIM_TIJD_GRENS_S` | max(300 s, 1800 s per GB) | tijdslimiet per omzetproces |
| `OPENBIM_RIJ_OMZETTEN` | `1` | gelijktijdige taken in de rij `omzetten` |
| `OPENBIM_RIJ_LICHT` | `4` | gelijktijdige taken in de rij `licht` |
| `OPENBIM_RIJ_BOTSING` | `1` | gelijktijdige taken in de rij `botsing` (botsingscontrole) |

## Releases

Een tag `v<jaar>.<week>.<n>` (zoals `v2026.44.1`) op een commit van `main` publiceert een release volgens het
SuperCloud-contract (`openaec-supercloud/docs/apps-harmoniseren.md`), via `.github/workflows/release.yml`:

| Asset | Soort | Gebruik |
|---|---|---|
| `ghcr.io/openaec-foundation/open-bim-platform-api:<versie>` | rekenkern als clouddienst, `linux/amd64` en `linux/arm64` | `serve` (standaard) en `openbim-kern werker`, zie *Container* en *Instellingen* |
| `open-bim-platform-web-<versie>.tar.gz` | browsertool voor de werkplek (`/werkplek/app/bim/`) | relatieve base `./`, SRI op scripts en stylesheets, geen inline code |
| `openaec_bim-<versie>.tar.gz` | Frappe-app voor de klantsite | de map `openaec_bim/` met de bestanden die git bijhoudt |

Elk asset heeft `bron.json` (versie, tag, commit, licentie, broncode), `THIRD-PARTY-NOTICES.txt`, `COPYING` en
`COPYING.LESSER`; de tarballs ook `MANIFEST.sha256` en een `.sha256` ernaast. De tarballs zijn reproduceerbaar (vaste
volgorde, eigenaar 0, de tijd van de commit). `/v1/health` van een release-image noemt de tag (`release`).

```bash
git tag v2026.44.1 <commit op main>
git push origin v2026.44.1
```

Een pull request die de release raakt (de workflow, `kern/Dockerfile`, `scripts/release/`) bouwt alles zonder te
publiceren, met de assets als artefact van de workflow. De scripts zelf: `python -m pytest scripts/tests`.

## Licentie

LGPL-3.0-or-later: de GNU Lesser General Public License, versie 3 of later ([COPYING.LESSER](COPYING.LESSER)), als
aanvulling op de GNU General Public License, versie 3 ([COPYING](COPYING)). De onderdelen van derden met hun eigen
licenties staan in `THIRD-PARTY-NOTICES.txt` van elk release-asset.

Onderdeel van de [OpenAEC Foundation](https://github.com/OpenAEC-Foundation). Build free. Build together.
