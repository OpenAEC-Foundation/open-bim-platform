# Open BIM Platform

3D-samenwerkingsomgeving voor de OpenAEC SuperCloud: modellen bekijken, samenvoegen en bespreken, rechtstreeks op de
bestanden in de opslag van de klantomgeving.

Status: fase 0 (fundament) in ontwikkeling. Het ontwerp en de plannen staan in `docs/`.

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
draait als werkplek-app `bim` (`/werkplek/bim?map=<id>`) en praat via de werkplekbrug in `bim.*`-berichten
(`viewer/src/host/WerkplekHost.ts`). De werkplekkant (gastpagina, adapter, bouwstap, lokale MinIO en kern) staat in
`openaec-bench`, branch `bouw/bim-werkplek`; zie `docs/werkplek.md` daar. Plan: `docs/superpowers/plans/2026-10-28-fase-1a-werkplek.md`.

Nog een besluit van de eigenaar: de projectlicentie van deze repo, prijsniveau en status in de catalogus, welke app
een `.ifc` standaard opent (nu de planner), en een machine met genoeg geheugen voor het omzetten op staging.

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

Een groot, geldig IFC voor metingen maken en een map met modellen doormeten:

```bash
cd kern
python scripts/enlarge.py <in.ifc> <factor> <uit.ifc>
python scripts/measure.py <map> --uit <rapport.md>
```

`measure.py` zet elk model om in een eigen proces en schrijft per bestand de grootte, de duur per stap en het
piekgeheugen van de omzetter en van IfcOpenShell. De uitvoer komt in `<map>/.afgeleid/`, zodat `openbim-kern lokaal
<map>` en de viewer de map daarna meteen openen.

### Container

```bash
cd kern
OPENBIM_KERN_SLEUTELS=<sleutel> docker compose up --build
```

Dit start de kern op poort 8730 en de werker, uit dezelfde image, met de wachtrij en werkmappen op het volume `/data`.

### Instellingen

| Variabele | Standaard | Betekenis |
|---|---|---|
| `OPENBIM_KERN_SLEUTELS` | (verplicht voor `serve`) | API-sleutels, komma-gescheiden |
| `OPENBIM_KERN_DATA` | tijdelijke map | wachtrij (`taken.sqlite`), cache en werkmappen |
| `OPENBIM_OMZETTER_CMD` | `node converter/convert.mjs` | opdracht voor de omzetter |
| `OPENBIM_SPLITS_VANAF_BYTES` | `1500000000` | bestanden hierboven worden gesplitst |
| `OPENBIM_DEEL_BYTES` | `1000000000` | doelgrootte van een deel bij splitsen |
| `OPENBIM_GEHEUGEN_GRENS_BYTES` | 3 × grootte + 1 GB | geheugengrens per omzetproces |
| `OPENBIM_TIJD_GRENS_S` | max(300 s, 1800 s per GB) | tijdslimiet per omzetproces |
| `OPENBIM_RIJ_OMZETTEN` | `1` | gelijktijdige taken in de rij `omzetten` |
| `OPENBIM_RIJ_LICHT` | `4` | gelijktijdige taken in de rij `licht` |

Onderdeel van de [OpenAEC Foundation](https://github.com/OpenAEC-Foundation). Build free. Build together.
