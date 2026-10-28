# Elementopslag en relatiegraaf: ontwerpnotitie

Status: meshstore, manifest, de tabel `relaties` en het kolombestand met eigenschappen zijn besloten voor fase 2 en
opgenomen in `2026-10-26-open-bim-platform-design.md` (5.3, 5.4, 9 en 10); de andere punten van 8 staan nog open.

## 1. Vraag

- **Data-efficiëntie.** De viewer krijgt een afgeleid weergavebestand (`.frag`), maar de geometrie en de semantiek
  moeten ook "echt" goed opgeslagen worden, als één grote database van het project. Hoort dat in een graafdatabase?
- **Rolverdeling.** De viewer doet alleen het tonen. De backend houdt het model met IfcOpenShell in het geheugen
  (zonder het te tonen) en voert daar bewerkingen op uit.
- **Eerst opschonen.** Haal vóór het splitsen de overbodige dingen uit een IFC (dubbele entiteiten, verweesde
  entiteiten, te fijne tessellaties) en splits daarna pas.

## 2. Uitgangspunten

- Het geüploade IFC in Storage (versie en SHA-256) blijft de bron. Alles wat de kern maakt, is een afgeleide per
  `(bestand, versie, omzetter)`, opnieuw te maken en te verwijderen.
- Elementen heten overal hun GlobalId, plus bestand en versie.
- Uit de meting van fase 0 (`docs/metingen/2026-fase-0.md`): IfcOpenShell vraagt **12–13 GB geheugen per GB IFC**
  met de index erbij; alles wat de kern doet (splitsen, omzetten, indexeren) schaalt met het aantal STEP-regels.

## 3. Proef

`kern/scripts/storage_study.py` meet per model:

- **de semantische graaf zonder geometrie:** elke objectdefinitie (element, ruimtelijk element, type, groep) en elk
  materiaal of elke classificatie waar die aan hangt, is een knoop; elke geobjectiveerde relatie (`IfcRel…`) wordt
  relaties tussen haar `Relating…`- en `Related…`-objecten; eigenschappen zijn waarden op de knopen;
- die graaf als **relatietabellen** (SQLite, gemeten) en in een **record-gebaseerde graafopslag** (ondergrens met de
  klassieke recordindeling: 15 B per knoop, 34 B per relatie, 41 B per vier eigenschappen, tekst boven 7 bytes in
  blokken van 128 B; zonder indexen en transactielog);
- de **naïeve graaf** waarin elke STEP-entiteit een knoop is en elke verwijzing een relatie (ondergrens, idem);
- de eigenschapswaarden **kolom voor kolom gecomprimeerd** (zlib), als benadering van een kolomgericht bestand;
- de **geometrie per element**, getrianguleerd in de eigen coördinaten van het element (na het uitsnijden van de
  sparingen), gehasht op inhoud: hoekpunten op 0,1 mm, onafhankelijk van de volgorde van hoekpunten en driehoeken;
  binnen het model en tussen twee versies, met de verschillen per IFC-klasse;
- het **openen** in IfcOpenShell: tijd en extra geheugen.

Drie metingen: een openbaar woningbouwmodel (IFC2X3, 47 MB), en drie opeenvolgende versies van een echt bouwkundig
model uit een project (IFC2X3, ~144 MB elk; niet in de repo): twee versies vijf maanden uit elkaar, en twee versies
2,5 week uit elkaar. Bij het openbare model is een tweede versie gemaakt door 10 % van de elementen te verplaatsen en
3 % (de geëxtrudeerde) dieper te maken.

### 3.1 Semantiek en index

| meting | openbaar, 47 MB | echt, 144 MB |
|---|---:|---:|
| STEP-entiteiten / verwijzingen | 714 485 / 516 452 | 2 892 461 / 4 990 976 |
| openen in IfcOpenShell | 3,0 s, +435 MB | 10,4 s, +1,47 GB |
| semantische graaf: knopen / relaties | 4 539 / 15 533 | 12 318 / 36 702 |
| eigenschapswaarden | 318 716 | 49 144 |
| graaf als relatietabellen (SQLite) | 25,2 MB | 7,0 MB |
| graaf in een graafopslag (ondergrens) | 21,4 MB | 10,7 MB |
| eigenschapswaarden kolomgericht gecomprimeerd | 0,8 MB | 0,1 MB |
| huidige eigenschappen-index (`eigenschappen.sqlite`) | 60,5 MB | 13,3 MB |
| naïeve graaf (elke entiteit een knoop, ondergrens) | 28,3 MB | 213 MB |
| `.frag` | 6,4 MB | 10,6 MB |

### 3.2 Geometrie binnen één versie

| meting | openbaar, 47 MB | echt, 144 MB |
|---|---:|---:|
| elementen met geometrie | 3 654 | 7 434 |
| representaties in het IFC | 3 466 | 5 315 |
| unieke meshes op inhoud | 2 073 | 2 984 |
| meshes per element opgeslagen (float32) | 4,8 MB | 34,0 MB |
| één keer per hash | 2,4 MB (−51 %) | 18,9 MB (−44 %) |

### 3.3 Geometrie tussen versies

| | openbaar, kunstmatig | echt, 5 maanden | echt, 2,5 week |
|---|---:|---:|---:|
| elementen v1 → v2 | 3 654 → 3 654 | 6 654 → 7 434 | 7 434 → 7 409 |
| zelfde GlobalId, zelfde mesh | 3 536 | 2 057 | 6 189 (84 %) |
| zelfde GlobalId, andere mesh | 118 | 2 890 | 1 168 |
| GlobalId nieuw / weg | 0 / 0 | 2 487 / 1 707 | 52 / 77 |
| nieuwe geometrie in v2 bij één keer per hash | 34 kB van 2,4 MB (1,4 %) | 16,3 van 18,9 MB (86 %) | 1,7 van 18,8 MB (9 %) |

Per klasse (2,5 week): deuren 414 zelfde / 172 anders, wanden 770 / 200, sparingen 935 / 425, ramen 384 / 0,
afwerkingen 1 502 / 202. Over vijf maanden zijn bijna alle wanden anders (103 / 667) en veel sparingen en
afwerkingen nieuw of weg; de deuren bleven grotendeels gelijk (554 / 1). De volgorde-onafhankelijke hash vindt maar
1 % meer gelijke meshes dan een hash op de volgorde van de iterator: de verschillen zijn echte wijzigingen, geen ruis
van de exporteur.

## 4. Wat de cijfers zeggen

1. **De semantiek is geen grote graaf.** Een model van 144 MB heeft twaalfduizend objecten en zevenendertigduizend
   relaties; de semantiek zonder geometrie is 7 MB als tabellen, 5 % van het IFC. Wat groot kan zijn, zijn de
   eigenschapswaarden, en die zijn vooral herhaling: in het openbare model, met veel eigenschappen, kolomgericht
   gecomprimeerd 0,8 MB tegen 25 MB als rijen (~30 keer kleiner).
2. **Een graafdatabase maakt het niet kleiner.** Dezelfde graaf kost in een graafopslag ongeveer evenveel of meer
   dan in tabellen (10,7 tegen 7,0 MB bij het echte model: elke GlobalId en naam gaat als tekst naar een eigen blok).
   De naïeve aanpak (elke STEP-entiteit een knoop, met de geometrie als miljoenen punten) is groter dan het IFC zelf
   (213 MB bij 144 MB).
3. **De winst zit in de geometrie per hash, over versies heen.** Binnen één versie halveert het hashen de geometrie
   (herhaalde kozijnen, deuren, profielen die het IFC niet als type deelt). Tussen twee versies van 2,5 week komt er
   9 % nieuwe geometrie bij in plaats van een volledig nieuw bestand; over vijf maanden, met een ontwerp dat echt
   veranderd is, 86 %. Het effect is dus groot in een uitwerkingsfase met veel kleine aanleveringen, en klein tussen
   ontwerpfasen.
4. **Ruwe meshes zijn groter dan `.frag`.** 18,9 MB unieke meshes als float32 tegen 10,6 MB `.frag` voor het echte
   model: een meshstore wint alleen met een compacte codering (gekwantiseerd en gecomprimeerd) en over versies heen.
5. **Sparingen maken wanden "anders".** De meshes zijn na het uitsnijden van de sparingen; schuift een raam, dan
   verandert de wand. Het lichaam vóór het uitsnijden hashen en de sparingen apart houden deelt veel meer (de viewer
   krijgt het uitgesneden resultaat toch uit `.frag`).
6. **GlobalIds zijn niet altijd stabiel.** Over vijf maanden zijn er 2 487 nieuw en 1 707 weg, vooral sparingen,
   afwerkingen en liggers. Een diff per element op GlobalId heeft een terugval nodig: zelfde klasse en zelfde
   mesh-hash.
7. **IfcOpenShell in het geheugen:** openen kost 9–10 × de bestandsgrootte en 60–70 s per GB; met de index erbij
   12–13 ×. Het model permanent in het geheugen houden kan niet voor elk project; op verzoek openen en warm houden wel.

## 5. Voorstel: vier lagen, elk met de vorm die bij de data past

### 5.1 Geometrie: meshes per hash, een manifest per versie

- De kern trianguleert elk element in zijn eigen coördinaten, zonder de sparingen uit te snijden, en slaat de mesh
  compact gecodeerd op onder zijn hash (`bim/geometrie/<hash>`), één keer per omgeving. Per versie komt er een
  **manifest**: per GlobalId de hash, de plaatsing (matrix), de sparingen die erin snijden en het deel/de verdieping.
- Een nieuwe versie schrijft alleen nieuwe meshes; het manifest zegt wat er veranderd is (zelfde hash = zelfde vorm,
  andere plaatsing = verplaatst). Dat is meteen de **diff per element** van fase 2 en 6.2, met de terugval op klasse
  en hash voor elementen waarvan de GlobalId veranderd is.
- De viewer blijft voorlopig een `.frag` per versie laden (het formaat van That Open). Het manifest en de meshstore
  zijn de bron waaruit het `.frag` gemaakt kan worden en waaruit later het streamen per element komt, zodra That Open
  dat levert. Tot die tijd blijft het `.frag` per versie bestaan; de meshstore spaart dan nog niets op de weergave,
  wel op de diff, de botsingen en de geschiedenis.

### 5.2 Semantiek en relaties: een graaf, eerst als tabellen

- Het **model** is een graaf: knopen zijn objectdefinities, materialen en classificaties; relaties zijn de
  geobjectiveerde `IfcRel…` (bevat, staat in, is van type, vult, maakt een sparing in, hoort bij systeem, …), elk met
  een soort. Zo gaat het ook naar IFCX in fase 4.
- **Opslag nu:** per versie in de bestaande `eigenschappen.sqlite` een tabel `relaties (van, naar, soort)` naast
  `elements` (36 702 rijen voor het echte model). Projectbreed (koppelingen tussen modellen, issues, BCF,
  momentopnamen) in de database van `openaec_bim` op de klantsite. Vragen over meerdere stappen (alles in deze ruimte,
  met dit systeem, met deze brandwerendheid) gaan met recursieve queries prima op deze omvang.
- **Een losse graafdatabase** wordt pas zinvol als vragen over veel stappen en over modellen en versies heen de kern
  van het product worden (fase 4: lagen van IFCX, herkomst per laag). Dan wegen mee: een extra dienst per omgeving
  (back-up, versleuteling met de sleutel van de klant, beheer), de licentie (de bekendste property-graph-database heeft
  een community-editie onder GPLv3 zonder clustering; productie vraagt dan een betaalde editie of een open
  alternatief) en de scheiding tussen klanten. Dat is een beslissing voor de eigenaar met de vragen van fase 4 op
  tafel, niet nu. Geometrie hoort er in geen geval in.

### 5.3 Eigenschappen: kolomgericht per versie

- Voor de viewer blijft het opzoeken per GlobalId uit SQLite (snel, klein genoeg).
- Voor zoeken en rapporteren over modellen heen (hoeveelheden per eigenschap, filters, vragen aan de assistent) komt
  per versie een **kolomgericht bestand** (Parquet) naast de index: in de proef ~30 keer kleiner dan dezelfde
  waarden als rijen. Een vraag over het hele project leest alleen de kolommen die hij nodig heeft, uit S3, zonder
  database.
- De huidige index kan kleiner: hij is 1,9 tot 2,4 keer zo groot als de tabellen van de proef (unieke indexen per
  waarde, eenheden en soort als tekst per rij).

### 5.4 Modelsessies in de kern: IfcOpenShell op verzoek, warm gehouden

- Lezen (eigenschappen, structuur, zoeken) gaat uit de index en de kolombestanden; daar is geen model in het geheugen
  voor nodig.
- Bewerkingen die het hele model vragen (botsingen, controles, wijzigen, exporteren) openen het model, of een deel,
  in een **modelsessie**: een werker die het model in IfcOpenShell houdt zolang er vragen komen, met een
  geheugenbudget per machine; de langst niet gebruikte sessie gaat eruit als het budget op is.
- Een model van 144 MB is in 10 s open en kost 1,5 GB; een deel van 0,4 GB ~4 GB. Een werker met 16 GB houdt dus
  drie à vier delen of tien modellen van deze grootte warm. Mijn voorstel: warm tot 15 minuten na de laatste vraag.

### 5.5 Eerst opschonen, dan splitsen

- **Verliesvrij opschonen** (identieke entiteiten samenvoegen, verweesde verwijderen) komt vóór het splitsen en maakt
  elke volgende stap kleiner; de GlobalIds en de inhoud blijven gelijk. Het opgeschoonde IFC is een afgeleide; de bron
  blijft onaangeroerd.
- **Met verlies** (te fijne tessellaties vereenvoudigen) alleen voor de weergave: het verandert de vorm, en botsingen
  en hoeveelheden willen de echte vorm.
- Opschonen en splitsen delen dezelfde compacte STEP-index (ids, types en verwijzingen in arrays in plaats van een
  object per regel); dat is één onderdeel van de kern.

## 6. Gevolgen voor het ontwerp

| onderdeel | nu | voorstel |
|---|---|---|
| afgeleid per versie (5.3) | `.frag`, `eigenschappen.sqlite`, `ruimtelijk.json`, `index.json` | plus manifest, `relaties` in de index, kolombestand met eigenschappen |
| opslag (5.4) | alles per versie onder `bim/afgeleid/<bestand>/<versie>/<omzetter>/` | meshes één keer per omgeving onder `bim/geometrie/<hash>`; opruimen met een telling van verwijzingen uit manifesten |
| omzetten (5.3) | splitsen → fragments → index | opschonen → splitsen → meshes en manifest → fragments → index |
| kern (5.5) | elke taak opent het bestand opnieuw | modelsessies met een geheugenbudget voor zware bewerkingen |
| kosten (10) | afgeleid ~10 % van de bron per versie | per versie alleen nieuwe meshes (9 % bij een aanlevering na 2,5 week), het manifest en de index |

## 7. Fasering

1. **Fase 2:** tabel `relaties` in de index; meshes hashen (vóór het uitsnijden) en het manifest per versie schrijven,
   eerst voor de diff per element; verliesvrij opschonen vóór het splitsen; kolombestand met eigenschappen.
2. **Fase 3 (IfcGit):** manifest per commit; de diff per element en het samenvoegen lezen het manifest.
3. **Fase 4 (IFCX):** de graaf per laag; dan de keuze voor een graafdatabase, op basis van de vragen die het product
   moet beantwoorden.
4. **Streaming:** zodra That Open het levert, laadt de viewer per element uit de meshstore en vervalt het `.frag` per
   versie.

## 8. Beslissingen voor de eigenaar

- **Besloten:** meshstore en manifest, de tabel `relaties` in de index en het kolombestand met eigenschappen komen in
  fase 2.
- Verliesvrij opschonen vóór het splitsen in fase 2 (aanbevolen, apart uit te werken).
- Wel of geen graafdatabase in fase 4, en zo ja: welke licentie past bij het verdienmodel.
- De tolerantie voor gelijke geometrie (voorstel 0,1 mm) en de codering van meshes in de store.
- Het geheugenbudget per werker voor modelsessies (16 GB voorgesteld), te nemen in het kostenplan.
