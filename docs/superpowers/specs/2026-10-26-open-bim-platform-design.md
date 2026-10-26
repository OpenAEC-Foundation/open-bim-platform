# Open BIM Platform: ontwerp

Datum: 26 oktober 2026. Status: ontwerp, ter goedkeuring door de eigenaar.

## 1. Doel en waarom

De OpenAEC SuperCloud biedt per klant een omgeving met ERP, OpenAEC Storage (bestanden, versies, delen), Beheer
(rechten per tool), een werkplek voor browsertools en een AI-assistent. Wat ontbreekt, is samenwerken in 3D: modellen
van alle partijen in een project samen bekijken, bespreken en controleren.

Het Open BIM Platform levert dat, als open-source alternatief voor de gangbare bouw-cloudplatforms en BIM-viewers. Op
termijn hoort daar alles bij wat zulke platforms bieden: modelcoördinatie, samenvoegen van disciplines,
botsingscontrole, issues en BCF, markeringen, metingen, doorsneden, eigenschappen, versies en vergelijken,
documentbeheer en meer. Het platform werkt **op de bestanden in Storage van de klantomgeving**, niet op een eigen kopie.

Wat het bijzonder maakt:

- **Open en controleerbaar:** open-source, open formaten (IFC, BCF, IDS), in een EU-cloud.
- **Eén omgeving:** dezelfde login, rechten, opslag en AI-tegoed als de rest van de SuperCloud; externe partijen
  werken mee via de delingen die Storage al kent.
- **Groot:** projecten met federaties van tientallen GB.

## 2. Doelen, niet-doelen en anti-doelen

**Doelen**

- Tientallen modellen per project hosten en samen in de browser bekijken.
- Een eerste bruikbare versie die een coördinator dagelijks gebruikt (fase 1), en een gefaseerde weg naar de volledige
  functielijst (hoofdstuk 9).
- Drie werkwijzen per project (hoofdstuk 6): losse bestanden, IfcGit traditioneel, IfcGit met IFCX-graaf.
- Zware verwerking (omzetten, botsingen, vergelijken) op de server met IfcOpenShell.

**Niet-doelen (nu)**

- Modelleren: het platform is geen ontwerpprogramma. Bewerken van IFC beperkt zich tot wat de Git-werkwijzen nodig
  hebben (samenvoegen) en, later, eenvoudige eigenschapswijzigingen.
- Een eigen bestandsopslag, eigen gebruikersbeheer of eigen rechtenmodel naast Storage en Beheer.
- Een eigen renderer: de weergave is That Open.

**Anti-doelen (dan is het mislukt, ook als het technisch werkt)**

- Een model dat in de viewer anders is dan het bestand in Storage, of een ingetrokken deling die in de viewer nog werkt.
- Een kopie van de modellen buiten Storage waar mensen in gaan werken.
- Een viewer die alleen op een zware werkplek draait: een gewone laptop moet een gefedereerd project kunnen openen,
  desnoods in delen.
- Onverwachte kosten op AWS.

## 3. Randvoorwaarden

- **Techniek, vastgelegd door de eigenaar:**
  - frontend: That Open (`@thatopen/components`, `@thatopen/components-front`, `@thatopen/fragments`);
  - backend: IfcOpenShell server-side voor de functies (eigenschappen, botsingen, vergelijken, controles);
  - het omzetten naar het weergaveformaat gebeurt met de IFC-import van That Open zelf, op de server (zie 5.3).
    IfcLite valt buiten de eerste opzet; we volgen het.
- **SuperCloud-contract** (`openaec-supercloud/docs/apps-harmoniseren.md`, `openaec-bench/docs/werkplek.md`,
  openaec-supercloud#6):
  - browsertool als statische bundel in de werkplek: opaque sandbox, geen eigen netwerk, geen opslag in de browser,
    alles via `postMessage` met de gastpagina, de app krijgt nooit een token;
  - rekenkern als clouddienst: `/v1/health`, `/v1/openapi.json`, `/v1/tools`, `POST /v1/tools/{naam}`, `/mcp`, achter
    de tools-gateway, die het OpenAEC-token (OIDC) en de rechten per tool controleert;
  - releases met tag `v<jaar>.<week>.<n>`, `bron.json`, `THIRD-PARTY-NOTICES.txt`, `MANIFEST.sha256`, geen geheimen;
  - huisstijl: het OpenAEC-style-book, volledig.
- **Storage** (`openaec-storage/README.md`): ruimtes met rollen (`beheerder`, `schrijver`, `lezer`, `gast`), delingen
  met `lezen`/`schrijven`/`beheren`, versies, sloten, mapregels, het mapsjabloon "Project (BIM)" met
  `05 BIM-modellen/{Werk, Gedeeld, Gepubliceerd}`, en een wijzigingenlijst.
- **Gebruikers:** medewerkers van de klant én externe partijen (constructeur, installateur, opdrachtgever) via delingen
  in Storage.
- **Grootte:** losse IFC-bestanden tot enkele GB; federaties tot tientallen GB.
- **Kosten:** niets op AWS zonder akkoord van de eigenaar; zware verwerking eerst als kostenplan (hoofdstuk 10).
- **Repo-regels:** geen namen van commerciële concurrerende software, geen verwijzingen naar gesprekken. Taal zoals de
  BIM Validator: documentatie in het Nederlands, code (namen, docstrings, commentaar) in het Engels, commits in de vorm
  `type(scope): Nederlandse omschrijving`.

## 4. Wat we weten uit metingen en voorwerk

Gemeten op deze opzet (`@thatopen/fragments` 3.6.0, web-ifc 0.0.78, Node 24, 32 GB RAM):

| IFC | .frag | verhouding | tijd | piekgeheugen |
|---|---|---|---|---|
| 73 MB | 10,4 MB | 14% | 16 s | 0,7 GB |
| 96 MB (installaties) | 7,4 MB | 7,7% | 13 s | 0,75 GB |
| 1,01 GB (synthetisch) | 39 MB | 3,8% | 121 s | 2,5 GB |
| 2,06 GB (synthetisch) | 74 MB | 3,6% | 215 s | 4,9 GB |

- De import van That Open draait zonder browser in Node. Ongeveer 1 op de 6 runs stopte met een WebAssembly-fout; een
  tweede poging slaagde. Gevolg: elke omzetting in een eigen proces, met herhalen.
- Ongeveer 2,4 GB geheugen en 110 s per GB IFC, op één kern.
- **Grens per bestand rond 2 à 2,5 GB**: web-ifc is 32-bits WebAssembly (4 GB plafond), en de uitvoer wordt in één
  keer in het geheugen opgebouwd. Daarboven eerst splitsen met `IfcSplitter` (zit in fragments 3.6.0) en de delen
  samen laden. That Open werkt aan een import in batches over meerdere werkers (engine_fragment#311); die nemen we over
  zodra hij uitkomt.
- **Viewer:** laadt een `.frag` in zijn geheel (geen range-requests), maar rendert alleen wat in beeld is (werkers,
  tegels, LOD). Het geheugen in de browser groeit met elk geladen model: ruwweg 15 tot 20 keer de `.frag`-grootte
  (gemeld in engine_fragment#228). Tien bestanden van 1 GB IFC worden 300 MB tot 1 GB `.frag` en 5 tot 15 GB
  browsergeheugen. Dus: niet alles tegelijk laden (zie 5.4).
- **Eigenschappen:** de standaardeigenschappen zijn ongeveer 40% van de `.frag`. Volledige psets en relaties serveren
  we vanaf de server.

Voorwerk in de organisatie:

- **BIM Validator** (`OpenAEC-BIM-validator`): goede scheiding tussen rekenkern (`src/ifc_validator`) en dunne
  omhulsels (CLI, MCP, web). Zwakke punten die we hier vermijden: taken alleen in het geheugen van één proces, hele
  uploads in RAM, geen controle van het token in de backend, de worker van That Open van een CDN.
- **IfcGit-prototypes** (`ifcgit-server`, `ifcgit-4-nextcloud`): dezelfde combinatie (Git + ifcmerge, fragments per
  commit, IfcOpenShell, BCF, een graaf in Neo4j), als vroeg skelet. Bruikbare patronen: afgeleide gegevens per versie
  in een cache, een werker met voortgang, een diff per element op GlobalId, het BCF-schema. Opnieuw te ontwerpen:
  opslag (hele bestanden in het geheugen), samenvoegen, federatie, botsingen; IFCX zit er niet in.

## 5. Architectuur

### 5.1 Overzicht

```
Browser (klantsite)
  /bim/<project>                gastpagina (eerste partij, sessie van de gebruiker)
    └─ iframe, opaque sandbox   viewer-bundel (That Open)          ← deze repo: viewer/
         postMessage: hallo, bim.*, tool.aanroep, ai.vraag

Klantsite (Frappe)
  openaec_bim                   Frappe-app: projecten, modellen, issues (BCF), botsingsrondes,
                                afgeleide gegevens, taken; rechten via Storage   ← deze repo: frappe/openaec_bim
  openaec_storage               bestanden, versies, delingen (bestaat)
  openaec_werkplek              gastpagina-mechaniek en brug (bestaat; uitbreiding nodig)

Tools-gateway (SuperCloud, openaec-supercloud#6)
  └─ BIM-kern                   rekenkern-container: /v1/…, /mcp; IfcOpenShell + Node-omzetter
                                ← deze repo: kern/
       werkers                  omzetten, eigenschappen-index, botsingen, vergelijken (eigen processen)

S3 (bucket van de omgeving)
  <prefix>/…                    bronbestanden (Storage, ongewijzigd)
  <prefix>/bim/afgeleid/…       afgeleide gegevens (fragments, indexen, resultaten)
```

Drie onderdelen in deze repo:

| Onderdeel | Map | Soort (SuperCloud) | Taal |
|---|---|---|---|
| Viewer | `viewer/` | browsertool (werkplek-bundel) | TypeScript, That Open |
| Platform-app | `frappe/openaec_bim/` | Frappe-app op de klantsite | Python (Frappe) |
| BIM-kern | `kern/` | rekenkern als clouddienst | Python (FastAPI, IfcOpenShell) + Node (omzetter) |

**Waarom zo (mijn keuze):**

- *Viewer in de werkplek.* That Open en onze viewer zijn code die in de browser van de gebruiker draait zonder toegang
  tot de sessie. Dat is precies waar de werkplek voor is. De viewer krijgt nooit een token; alle gegevens komen via
  de gastpagina.
- *Platformgegevens in een Frappe-app op de klantsite.* Projecten, issues en botsingsrondes horen bij de omgeving van
  de klant, naast Storage, met dezelfde rechten, back-ups en het auditspoor. Geen aparte database naast de
  SuperCloud.
- *Zware verwerking in een rekenkern achter de tools-gateway.* Zo komt de BIM-kern via dezelfde weg beschikbaar als
  andere rekenkernen (login, rechten per tool, limieten, verbruik), ook voor de AI-assistent via `/mcp`, en kan hij
  los opschalen.

### 5.2 Rechten

- **Storage beslist.** Wie een bronbestand (versie) mag lezen, mag ook alle afgeleide gegevens ervan lezen. Elke vraag
  om afgeleide gegevens controleert opnieuw de leesrechten op het bronbestand bij Storage (ook via een deling). Een
  ingetrokken of verlopen deling werkt dus meteen ook in de viewer.
- **Een project** in `openaec_bim` hoort bij een ruimte (of, voor een externe partij, bij een deling) en verwijst naar
  een of meer modelmappen, standaard `05 BIM-modellen/Gedeeld`. Wie de map mag lezen, mag het project bekijken. Het
  project houdt geen eigen ledenlijst bij.
- **Schrijven** (een issue maken, een botsingsronde starten, een model aanleveren) vraagt `schrijven` op de modelmap
  (rol `schrijver`/`beheerder` of een schrijfdeling). Een opdrachtgever met `lezen` kan bekijken en, als de beheerder
  van de ruimte dat aanzet, reageren op issues (projectinstelling `lezers_mogen_reageren`, mijn keuze: standaard aan).
- **Licentie per tool** komt uit Beheer (app-id `open-bim-platform` in de catalogus van de regelkamer), zoals bij de
  andere werkplek-apps.
- **Afgeleide gegevens** zijn nooit rechtstreeks voor de browser bereikbaar: de gastpagina vraagt ze aan
  `openaec_bim` met haar sessie en draagt de bytes over aan het frame (zie 7.1).
- **Gearchiveerde ruimtes** zijn alleen te lezen, zoals in Storage: geen nieuwe issues of botsingsrondes.
- **Een deling op een deel van het project** (één bestand of een submap): de externe partij ziet het project, met
  alleen de modellen die ze mag lezen, en alleen issues en botsingen die uitsluitend elementen uit die modellen noemen
  (mijn keuze). Issues toewijzen kan aan iedereen die het project kan zien.
- **Andere versies tijdens het omzetten:** komt er een nieuwe versie binnen, dan toont de viewer de laatst omgezette
  versie met een duidelijke melding ("Versie 7 wordt omgezet, je ziet versie 6") en laadt de nieuwe zodra die klaar
  is. De viewer zegt altijd welke versie van elk model in beeld is; issues, botsingsrondes en momentopnames leggen de
  versies vast die ze gebruikten (mijn keuze).

### 5.3 Van IFC naar weergave: omzetten

Trigger: een nieuwe versie van een IFC-bestand (`.ifc`, `.ifczip`) in een modelmap van een project. `openaec_bim`
volgt de wijzigingenlijst van Storage (een geplande taak elke minuut, plus een hook bij `upload_klaar` als Storage die
krijgt) en zet een taak klaar.

Per bestandsversie maakt de BIM-kern:

| Afgeleid | Inhoud | Gemaakt met |
|---|---|---|
| `model.frag` (of `deel-<n>.frag`) | geometrie + standaardeigenschappen voor de viewer | `@thatopen/fragments` IfcImporter in Node |
| `eigenschappen.sqlite` | alle psets, hoeveelheden, materialen, classificaties, typen, relaties per GlobalId | IfcOpenShell |
| `ruimtelijk.json` | ruimtelijke boom (project, terrein, gebouw, verdieping, ruimte) met GlobalIds | IfcOpenShell |
| `index.json` | samenvatting: schema, eenheden, georeferentie (IfcMapConversion), begrenzingsdoos, aantallen per klasse en verdieping, lijst van delen | IfcOpenShell |

- **Splitsen:** boven 1,5 GB (mijn keuze, ruim onder de gemeten grens) splitst de kern het bestand eerst met
  `IfcSplitter` in `ceil(grootte / 1 GB)` delen. De splitser maakt groepen van ongeveer even veel elementen, houdt
  samenhangende elementen bij elkaar (wand, opening, deur) en geeft elk deel de gedeelde ruimtelijke structuur mee.
  Elk deel wordt een eigen `.frag`; `index.json` zegt per deel de grootte en de verdiepingen waar het elementen in
  heeft.
- **Eén proces per omzetting**, met een geheugengrens (3 GB per GB IFC, plus marge) en een tijdslimiet (30 minuten per
  GB, mijn keuze), herhalen bij een WebAssembly-fout (hoogstens twee keer).
- **Sleutel:** `(bestand, versie, omzetterversie)`. De omzetterversie is de versie van de kern plus de versie van
  fragments; bij een nieuwe omzetter worden versies alleen opnieuw omgezet als ze geopend worden (lui), of op verzoek
  van een beheerder.
- **Eén identiteit:** viewer en IfcOpenShell lezen hetzelfde bestand; elementen worden overal herkend aan GlobalId
  (plus bestand en versie). Verschillen in geometrie tussen web-ifc (weergave) en IfcOpenShell (botsingen) zijn
  mogelijk; de kern meet ze bij elke release op een vaste testset (zie 11).

### 5.4 Opslag en caching van afgeleide gegevens

- **Waar:** in de S3-bucket van de omgeving, onder `<openaec_storage_prefix>/bim/afgeleid/<bestand>/<versie>/<omzetter>/`.
  Niet als bestand in een ruimte (niemand werkt erin), wel in dezelfde bucket en met dezelfde versleuteling (KMS van
  de klant).
- **Quotum:** telt mee in het opslaggebruik van de omgeving als aparte post `bim_afgeleid_bytes`, niet in het quotum
  van een ruimte (mijn keuze; het is ongeveer 10% van de bronbestanden). Issue voor Storage: `api.quotum` met die post.
- **Opruimen:** afgeleide gegevens van een bronversie verdwijnen als die versie in Storage definitief weg is
  (wijzigingenlijst), en van een versie die 90 dagen niemand opende en niet de nieuwste is (instelbaar).
- **Browser:** de viewer heeft geen opslag (opaque frame). Binnen één sessie houdt de gastpagina geladen
  `.frag`-bestanden in het geheugen. HTTP-cache: de gastpagina haalt afgeleide gegevens met een kortlevend, ondertekend
  adres zonder cookies (zoals `lees_token` van de werkplek), met `Cache-Control: private, max-age=…, immutable`; de
  sleutel bevat versie en omzetter, dus de inhoud verandert nooit.
- **Laden in delen:** de viewer laadt per model en per deel, niet alles tegelijk. Openen van een project toont eerst de
  lijst van modellen met disciplines en verdiepingen uit `index.json`; standaard worden de modellen geladen tot een
  geheugenbudget (mijn keuze: 2 GB geschat browsergeheugen, instelbaar per gebruiker in de sessie), de rest staat klaar
  om aan te zetten. Zodra That Open echte streaming uitbrengt, vervangt dat dit mechanisme.

### 5.5 BIM-kern (rekenkern)

- FastAPI-dienst met het rekenkern-contract: `GET /v1/health`, `GET /v1/openapi.json`, `GET /v1/tools`,
  `POST /v1/tools/{naam}`, `POST /mcp`. De tools zijn gewone Python-functies in een los pakket (`kern/src/openbim_kern/`,
  naar het voorbeeld van `src/ifc_validator` in de BIM Validator); HTTP, MCP en CLI zijn dunne omhulsels, en een test
  bewijst dat ze dezelfde uitkomst geven.
- **Eén gedeelde dienst voor alle omgevingen** (mijn keuze), zonder eigen toegang tot buckets van klanten. De kern
  bewaart niets tussen taken behalve de wachtrij en een tijdelijke werkmap per taak.
- **Bestanden in het verzoek, als verwijzing.** Het cloudbeleid zegt: alleen tools die met gegevens in het verzoek
  werken, nooit van schijf lezen. Een model van GB's past niet in een verzoek. Daarom geeft `openaec_bim` (dat op de
  klantsite al bij Storage en de bucket kan) in elk verzoek kortlevende, ondertekende S3-adressen mee: leesadressen
  voor de bron (`{url, sha256, grootte}`) en schrijfadressen voor de uitvoer onder `bim/afgeleid/`. Die maakt
  `openaec_bim` pas na de rechtencontrole bij Storage (bij een taak van een gebruiker) of voor een bestand in een
  modelmap van het project (bij omzetten op de achtergrond). De kern ziet nooit een token van een gebruiker, nooit
  een sleutel van een bucket en leest nooit van zijn eigen schijf buiten de werkmap.
- **Wie roept aan.** Achtergrondtaken (omzetten na een upload) start de klantsite zelf, met haar sitesleutel, zonder
  gebruiker. Taken die een gebruiker start (een botsingsronde), gaan ook via `openaec_bim`, met de gebruiker als
  `namens` voor het verbruik en het auditspoor. De kern wordt dus altijd door een klantsite aangeroepen, nooit
  rechtstreeks door een browser. Tot de tools-gateway er is, gebeurt dat op het interne netwerk met een interne
  sleutel per klantsite; daarna via de gateway met de sitesleutel (zie 7.2).
- **Eerlijk verdelen:** de wachtrij werkt per klantsite (hoogstens N taken tegelijk per omgeving, mijn keuze: 2), zodat
  één groot project de andere klanten niet ophoudt. Verbruik wordt per klantsite en per taak gemeld.
- **Lange taken.** Omzetten en botsingen duren minuten tot uren. Voorstel (issue voor de SuperCloud): tools met
  `"lang": true` in `/v1/tools` geven bij `POST` meteen `202 {taak}`; `GET /v1/taken/{taak}` geeft stand, voortgang
  en uitkomst; `DELETE` breekt af. Tot de gateway dat ondersteunt, roept `openaec_bim` de kern rechtstreeks aan op het
  interne netwerk met een interne sleutel.
- **Werkers:** een wachtrij (Redis-compatibel, valkey zoals in de bench; arq) met aparte rijen voor `omzetten` (veel
  geheugen), `botsing` (veel rekenwerk) en `licht` (eigenschappen opvragen). Elke taak in een eigen subproces met
  grenzen. De stand van taken staat in de wachtrij én wordt teruggemeld aan `openaec_bim`, zodat een herstart niets
  kwijtraakt: een taak die niet af is, begint opnieuw.
- **Tools (eerste set):** `omzetten`, `eigenschappen` (van een of meer GlobalIds), `zoeken` (elementen op klasse,
  eigenschap of waarde over de federatie), `botsingen` (IfcOpenShell `ifcclash`), `vergelijken` (fase 2), `ids_controle`
  (fase 2, via de BIM Validator als aparte rekenkern of als bibliotheek; mijn voorkeur: de BIM Validator aanroepen,
  geen tweede rekenweg).
- **Limieten:** grootte van een verzoek, gelijktijdige taken per rij (503 met `Retry-After`), tijd per taak. Fouten
  altijd als JSON met `error_code`, `melding`, `remedie`. Container niet als root, healthcheck op `/v1/health`.

### 5.6 Platform-app `openaec_bim` (Frappe)

DocTypes (eerste opzet):

| DocType | Velden (kern) |
|---|---|
| `BIM Project` | `naam`, `ruimte`, `werkwijze` (`bestanden`, `ifcgit`, `ifcx`), `modelmappen` (tabel), `lezers_mogen_reageren`, `georeferentie` (keuze: eerste model / vast punt) |
| `BIM Model` | `project`, `bestand` (Link Opslagbestand), `discipline` (afgeleid uit de submap of de naam, aanpasbaar), `zichtbaar_standaard` |
| `BIM Afgeleid` | `bestand`, `versie`, `omzetter`, `status` (`wacht`, `bezig`, `klaar`, `fout`), `delen`, `bytes`, `fout`, `laatst_geopend` |
| `BIM Taak` | `soort`, `project`, `status`, `voortgang`, `kern_taak`, `gestart_door`, `uitkomst` |
| `BIM Issue` | BCF-topic: `guid`, `titel`, `status`, `soort`, `prioriteit`, `toegewezen_aan`, `vervaldatum`, `labels`, `elementen` (GlobalIds met bestand en versie), `standpunten` (tabel: camera, doorsneden, zichtbaarheid, markering, schermafbeelding) |
| `BIM Reactie` | `issue`, `tekst`, `standpunt?` |
| `BIM Botsingsronde` | `project`, `set A`/`set B` (modellen of filters), `tolerantie`, `soort` (hard, afstand), `status`, `resultaten` (aantal), `bron_versies` |
| `BIM Botsing` | `ronde`, `element_a`, `element_b`, `punt`, `afstand`, `status` (`nieuw`, `actief`, `opgelost`, `genegeerd`), `issue?`, `groep` |

- **BCF:** issues zijn BCF 3.0 in het datamodel. Export en import als `.bcfzip` in Storage (map `Gedeeld`), en later een
  BCF-API 3.0 voor externe programma's (fase 2). De bron van waarheid is `openaec_bim`; een `.bcfzip` in Storage is
  een export, geen tweede bron (mijn keuze, zodat meerdere mensen tegelijk werken zonder conflictkopieën).
- **Botsingen volgen:** een volgende ronde op nieuwe versies koppelt botsingen aan de vorige ronde op het paar
  GlobalIds; een opgeloste botsing die terugkomt, wordt weer actief.
- **API voor de gastpagina:** `openaec_bim.api.*` (sessie van de gebruiker), onder meer `project`, `modellen`,
  `afgeleid_adres` (kortlevend leesadres), `eigenschappen`, `zoek`, `issues`, `issue_bewaar`, `botsingsronde_start`,
  `botsingen`. Elke methode controleert de rechten via Storage.
- **Auditspoor:** wijzigingen aan issues en botsingsrondes in de versiegeschiedenis van Frappe.

### 5.7 Viewer (browsertool)

- That Open (`@thatopen/components`, `components-front`, `fragments`, alle drie op dezelfde versie, vastgepind),
  Three.js, TypeScript, Vite. De worker van fragments en de WASM van web-ifc zitten in de bundel (geen CDN).
- UI volgens het OpenAEC-style-book, volledig. Het UI-raamwerk volgt wat het style-book voor webapps voorschrijft;
  schrijft het niets voor, dan React (zoals de viewer van de BIM Validator, zodat code te delen is).
- Draait onder de werkplek-CSP: geen netwerk buiten de eigen bundel, workers via de worker-shim of als klassieke
  blob-worker, geen opslag in de browser.
- **Werkt ook los** (ontwikkelen, desktop later): een `host`-laag met twee uitvoeringen, `werkplek` (postMessage) en
  `lokaal` (een ontwikkelserver die een map met IFC-bestanden en de kern aanspreekt). De viewer zelf weet niet welke.

## 6. Werkwijzen van een project

Een project kiest bij het aanmaken een werkwijze. Viewer, issues en botsingen werken voor alle drie op dezelfde manier:
ze zien een lijst van **modelbronnen** (`{soort, sleutel, versie}`), met afgeleide gegevens per bron.

### 6.1 Losse bestanden (fase 1)

Elke partij zet haar IFC-bestand(en) in de modelmap. Een nieuwe versie is een nieuwe Storage-versie. Het project toont
standaard de nieuwste versie van elk bestand; een gebruiker kan per model een oudere versie kiezen. Een **momentopname**
legt vast welke versie van elk model bij elkaar hoort (bijvoorbeeld "Coördinatie week 44"); issues en botsingsrondes
verwijzen naar een momentopname of naar de versies die op dat moment golden.

### 6.2 IfcGit traditioneel (fase 3)

Per project een Git-repository met de IFC-bestanden als tekst (STEP), met takken per partij of per ontwerpvariant en
samenvoegen met `ifcmerge`. Ontwerplijnen:

- **Grote bestanden:** Git bewaart geen blobs van GB's in de repository zelf. De inhoud staat in S3 (zoals bij Git LFS:
  een verwijzing in Git, de bytes in de bucket); de kern doet Git-handelingen met de Git-opdrachtregel in een werker,
  nooit in het geheugen van een webverzoek.
- **Koppeling met Storage:** de werkkopie van de hoofdtak is zichtbaar als gewone bestanden in de modelmap (alleen
  lezen); een commit maakt een nieuwe Storage-versie. Aanleveren gaat via een tak (een partij uploadt in haar eigen
  map `Werk/<partij>`, het platform maakt er een commit op haar tak van). Samenvoegen is een handeling in het platform,
  met een overzicht van de wijzigingen per element en de conflicten die `ifcmerge` niet zelf oplost.
- **Diff per element** op GlobalId: toegevoegd, verwijderd, gewijzigd (attributen, psets, plaatsing, geometrie).
- **Afgeleide gegevens** per commit en pad.

Dit wordt de app "IfcGit" uit de catalogus van de SuperCloud, als werkwijze binnen dit platform (mijn aanname).

### 6.3 IfcGit met IFCX-graaf (fase 4)

Mijn uitwerking, nog niet bevestigd: het model is geen verzameling bestanden maar een graaf van elementen volgens IFCX
(IFC5, JSON). Elke partij levert een **laag** aan (eigen elementen, of toevoegingen en wijzigingen op elementen van
anderen, zoals een installateur die sparingen vraagt of een kostendeskundige die eigenschappen toevoegt). Lagen worden
in een vaste volgorde op elkaar gestapeld tot het samengestelde model. Versiebeheer gebeurt per laag (Git op de
JSON-bestanden, dus kleine diffs per element). Wat dit boven 6.2 mogelijk maakt:

- wijzigingen op elementen van een ander zonder diens bestand te bewerken;
- diff en samenvoegen per element en per eigenschap in plaats van per regel van een STEP-bestand;
- zoeken in de graaf over het hele project (relaties, eigenschappen, herkomst per laag).

Voor deze fase eerst een verkenning: de stand van IFCX (schema, geometrie, gereedschap in IfcOpenShell en That Open),
en hoe een samengestelde graaf naar fragments gaat. Een graafdatabase (zoals in het IfcGit-prototype) is een mogelijke
uitvoering, geen vaststaande keuze.

## 7. Koppeling met de SuperCloud

### 7.1 Werkplek: gastpagina en berichten

- Route `/bim/<project>` op de klantsite, en `/werkplek/bim?bestand=<id>` om één IFC-bestand te openen (dat wordt dan
  een tijdelijk project zonder opgeslagen gegevens). Bundel onder `/werkplek/app/bim/`.
- De gastpagina hoort bij `openaec_bim` en gebruikt de brug en de mechaniek van `openaec_werkplek` (sandbox, koppen,
  SRI, manifest, verbruik). Nieuwe regel in `APPS` met sleutel `bim`.
- **Nieuwe berichtsoorten** (`bim.*`), naast `hallo`, `melding` en `ai.vraag`:

| Soort | Velden | Antwoord |
|---|---|---|
| `bim.project` | | `{project, werkwijze, modellen: [{bron, naam, discipline, versie, status, delen, index}], momentopnames, rechten}` |
| `bim.laad` | `bron`, `deel?` | `{bytes}` (overgedragen `ArrayBuffer` met de `.frag`); fout `nog_niet_klaar` met voortgang, of `omzetten_mislukt` |
| `bim.eigenschappen` | `bron`, `globalids` | `{per GlobalId: psets, hoeveelheden, materialen, classificatie, type}` |
| `bim.zoek` | `vraag` (klasse, eigenschap, waarde, verdieping) | `[{bron, globalid}]` |
| `bim.issues` / `bim.issue_bewaar` / `bim.reactie` | | lijst / `{issue}` |
| `bim.botsingen` / `bim.botsingsronde_start` | | lijst / `{taak}` |
| `bim.taak` | `taak` | `{status, voortgang, uitkomst}` |
| `bim.export_bcf` | `issues?` | `{bestand}` (een `.bcfzip` in de map `Gedeeld`) |

- De werkplek legt nu een grens van 200 MB per bestand op (`openaec_werkplek_max_mb`). Voor `bim.laad` geldt een eigen
  grens per `.frag` (mijn keuze: 1 GB); grotere modellen zijn al in delen gesplitst.
- Schermafbeeldingen voor issues maakt de viewer zelf (canvas) en geeft ze als bytes mee met `bim.issue_bewaar`.

### 7.2 Tools-gateway

De BIM-kern is de tweede kandidaat voor de tools-gateway (na Open FEM Studio). Nodig in de gateway, als issues voor
openaec-supercloud#6:

1. aanroepen door een klantsite met haar sitesleutel (geen gebruiker), met `namens` voor verbruik en auditspoor;
2. lange taken (`202` + `/v1/taken/{taak}`);
3. verbruik per taak (rekentijd en piekgeheugen) naar de regelkamer, zodat zware verwerking per verbruik of per
   toolniveau af te rekenen is.

De bronbestanden lopen niet via de gateway: `openaec_bim` geeft ondertekende adressen mee (5.5).

### 7.3 AI-assistent

- **In de viewer:** `ai.vraag` met context (geselecteerde elementen en hun eigenschappen, het actieve issue). Vragen als
  "welke brandwerende wanden op de tweede verdieping hebben geen brandwerendheid ingevuld?" vertaalt de assistent naar
  `bim.zoek` en toont de uitkomst in de viewer. De klantsite betaalt uit het AI-tegoed.
- **Via MCP:** de assistent van de klantsite krijgt BIM-tools (`zoeken`, `eigenschappen`, `botsingen`, `issues`) van
  `openaec_bim`, met de rechten van de gebruiker; `openaec_bim` vertaalt ze naar de kern met ondertekende adressen
  (5.5). De kern zelf biedt `/mcp` volgens het contract, met tools die adressen of bytes als argument nemen. Voor
  lokale AI komt dezelfde set als `.mcpb`-bundel, op lokale bestanden.

### 7.4 Storage

Issues voor `openaec-storage`:

1. post `bim_afgeleid_bytes` in `api.quotum` (5.4);
2. een hook of melding bij `upload_klaar` zodat `openaec_bim` niet hoeft te wachten op de geplande taak (5.3);
3. "Openen met" in `/opslag` (bestaand voorstel in `werkplek.md`): `.ifc`, `.ifczip` naar `/werkplek/bim?bestand=…`,
   en een map met IFC-bestanden naar "Openen als BIM-project".

## 8. Eerste versie (fase 1): wat een gebruiker kan

1. Een beheerder van de ruimte maakt een BIM-project op een ruimte met het sjabloon "Project (BIM)"; de modelmap is
   `05 BIM-modellen/Gedeeld`.
2. Partijen zetten hun IFC in die map (browser, desktop-app of WebDAV). Het platform zet ze op de achtergrond om; de
   viewer toont de voortgang per model.
3. Openen toont alle modellen samen, op de juiste plek (IfcMapConversion als die er is, anders het eerste model als
   oorsprong).
4. In de viewer: navigeren (draaien, pannen, zoomen, vliegen), modellen en disciplines aan/uit, ruimtelijke boom per
   model, selecteren, isoleren, verbergen, transparant maken, eigenschappen van een element (volledig, van de server),
   doorsneden (vlakken en een doorsnededoos), meten (afstand, lengte, hoek, oppervlak), kleuren op eigenschap of klasse.
5. Issues: met een standpunt (camera, doorsneden, zichtbaarheid), markering op de schermafbeelding, gekoppelde
   elementen, toewijzen, status, reacties; export en import als `.bcfzip` in Storage.
6. Botsingscontrole: een ronde tussen twee sets (bijvoorbeeld constructie tegen installaties) met tolerantie; de
   resultaten als lijst in de viewer, per botsing in beeld te brengen, te groeperen en om te zetten in een issue.
7. Momentopnames van welke versies bij elkaar horen.

Buiten fase 1: versies vergelijken, IDS-controle, BCF-API, de Git-werkwijzen, rapporten.

## 9. Gefaseerde roadmap

| Fase | Inhoud | Klaar als |
|---|---|---|
| **0. Fundament** | Repo-opzet (drie onderdelen), BIM-kern met het rekenkern-contract en de tools `omzetten`, `eigenschappen`; omzetten met splitsen; viewer die één project laadt met de host-laag `lokaal`; testset van modellen; alles lokaal en op de bench | Een map met tien IFC-bestanden (samen ≥ 5 GB) is volledig omgezet; de viewer laadt modellen tot het geheugenbudget en de rest is aan te zetten, op een laptop met 16 GB geheugen en een ingebouwde GPU (mijn maatstaf voor "gewone laptop") |
| **1. Eerste bruikbare versie** | `openaec_bim` op de klantsite, gastpagina en `bim.*`-berichten, rechten via Storage, functies uit hoofdstuk 8 | Een coördinator en een externe partij (via een deling) werken samen aan issues en botsingen op de bench; release-assets volgens het SuperCloud-contract |
| **2. Coördinatie compleet** | Versies vergelijken (per element, ook geometrie), IDS-controle (BIM Validator), BCF-API 3.0, rapporten (PDF via de rapportage van de organisatie), hoeveelheden per eigenschap, kleuren en filters bewaren als weergaven, AI-assistent in de viewer en via MCP | Vergelijken van twee versies van een model van 1 GB binnen 10 minuten; BCF-uitwisseling met een extern programma via de API |
| **3. IfcGit traditioneel** | Werkwijze 6.2 | Twee partijen werken op eigen takken en voegen samen, met een overzicht van conflicten |
| **4. IfcGit met IFCX-graaf** | Verkenning, daarna werkwijze 6.3 | Volgt uit de verkenning |
| **5. Platform** | Documentbeheer naast het model (tekeningen en PDF's koppelen aan elementen en issues, openen in Open PDF Studio), 4D (koppeling met Open Planner Studio), kosten en hoeveelheden naar ERP, puntenwolken, gebruik op tablet in het veld, meldingen en e-mail bij issues, dashboards per project, streaming van modellen zodra That Open dat levert | Per onderdeel een eigen ontwerp |

## 10. Zware verwerking en kosten

- **Fase 0 en 1 draaien op de bench en lokaal**; er komt niets op AWS zonder akkoord van de eigenaar.
- **Omvang (uit de metingen):** omzetten kost ongeveer 2,4 GB geheugen en 110 s per GB IFC, plus de tijd van
  IfcOpenShell voor de eigenschappen-index (te meten in fase 0). Een omzetwerker met 8 GB geheugen zet een bestand van
  2 GB om; een project van 30 GB is op één werker enkele uren werk, één keer, daarna alleen nieuwe versies.
  Botsingscontrole schaalt met het aantal elementen in beide sets; meting in fase 0.
- **Kostenplan vóór productie** (aparte notitie voor de eigenaar, met actuele prijzen van AWS in eu-central-1), met
  deze opties naast elkaar:
  1. werkers als taken die alleen draaien als er werk is (container per taak, op aanvraag);
  2. één vaste kleine dienst voor lichte vragen plus werkers op aanvraag voor omzetten en botsingen;
  3. werkers op goedkopere onderbreekbare capaciteit (een taak die onderbroken wordt, begint opnieuw; dat kan omdat
     elke taak herhaalbaar is);
  en per optie: kosten per GB omgezet, per botsingsronde, vaste kosten per maand, en opslag van afgeleide gegevens
  (ongeveer 10% van de bronbestanden).
- **Afrekenen:** verbruik per taak naar de regelkamer (7.2), zodat de prijs per klant kan meeschalen.

## 11. Kwaliteit en testen

- **Testset:** een vaste set open IFC-modellen (klein, middel, groot, IFC2X3, IFC4, IFC4X3, met openingen, met
  georeferentie, met installaties), plus synthetische grote bestanden. Geen modellen van klanten in de repo.
- **Kern:** pytest; per tool een test dat HTTP, MCP en CLI dezelfde uitkomst geven; geheugen- en tijdmetingen op de
  testset bij elke release, met een grens die de CI bewaakt.
- **Geometrie:** bij elke release per element de begrenzingsdoos uit web-ifc (fragments) tegen die uit IfcOpenShell
  vergelijken op de testset; afwijkingen boven een tolerantie zijn een bevinding.
- **Viewer:** vitest voor logica, een browserproef (headless Chromium) in de werkplek-sandbox (`zelfde-origin.mjs` van
  de bench) en een end-to-end-proef: project openen, issue maken, botsingsronde.
- **Frappe-app:** `bench run-tests` met een nagebootste S3 (moto), net als Storage; rechtentests per rol en per deling,
  ook ingetrokken en verlopen.

## 12. Wat aan de bouwer is

- Indeling binnen de drie onderdelen, namen van modules, het UI-raamwerk binnen het style-book.
- De precieze tabellen in `eigenschappen.sqlite` en de vorm van `index.json`.
- Groeperen van botsingen (op element, type, verdieping) en de standaardtoleranties.
- De keuze van de wachtrijbibliotheek, zolang taken herhaalbaar zijn en een herstart overleven.

## 13. Open punten

- **Werkwijze 6.3** is mijn uitwerking; de eigenaar bevestigt of stuurt bij vóór fase 4.
- **Externe partijen en licenties.** Een externe partij heeft een account op de klantsite nodig (Storage deelt alleen
  met systeemgebruikers). Of zij een licentie van de klant voor dit platform gebruikt, of als ontvanger van een deling
  gratis mag bekijken en reageren, beslist de eigenaar (regelkamer en Beheer). Tot dan volgt het platform Beheer: een
  licentie per persoon. De licentiecontrole zit in één functie in `openaec_bim`, zodat een andere regel later één
  wijziging is.
- **Productie zonder tools-gateway.** Op de bench en in een testomgeving praat `openaec_bim` op het interne netwerk met
  de kern. Of productie daarop mag starten of op de gateway wacht, beslist de eigenaar vóór de eerste uitrol van fase 1.
- **Wijzigingen buiten deze repo** gaan als issue naar de repo die het aangaat, volgens "Issues naar app-repo's" in
  `apps-harmoniseren.md`: tools-gateway (aanroep door een klantsite, lange taken, verbruik), werkplek (`bim` in
  `APPS`, `bim.*`, grens per `.frag`) en Storage (7.4). De gastpagina zelf hoort in `openaec_bim` (deze repo) en
  gebruikt de brug en koppen van `openaec_werkplek`. Tot de tools-gateway er is, praat `openaec_bim` op het interne
  netwerk met de kern.
- **Streaming in That Open** (engine_fragment#228, #311) kan het laden in delen vervangen; we volgen het.
