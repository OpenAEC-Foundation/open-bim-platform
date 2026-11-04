# Meting botsingen beoordelen: de werklijst in de werkplek

Acceptatie van het beoordelen van botsingen (plan `2026-11-04-botsingen-beoordelen`, taak 11): een ronde starten met een
snelle keuze, de emmers, groeperen, sneltoetsen, afwijzen met een reden, bevestigen tot een issue, een volgende ronde met de
ontwikkeling, en het paar geïsoleerd in beeld, beproefd via de GUI in de werkplek van een lokale SuperCloud. Daarnaast een
meting op de twee demomodellen van 49 en 73 MB: de duur van een ronde, de aantallen per emmer en ernst, of de indeling klopt, en
de tijd van isoleren.

## Opzet

- **Machine:** dezelfde laptop als bij fase 1b (Intel Core i9-14900HX, 32 GB, Windows 11 Pro; Docker-VM met 15,5 GB); de
  werkplek in headless Chromium op de GPU (Playwright, `--use-angle=d3d11`).
- **Bench:** `openaec-bench`, branch `bouw/bim-werkplek`, met `compose.bim.yaml`. De viewer is gebouwd uit
  `fase-1c-botsingen-beoordelen` (vastgepind in `scripts/werkplek-versies.txt` op de commit die als laatste is getest). De
  BIM-kern en zijn werker draaien het image dat voor deze meting opnieuw is gebouwd (`docker build -f kern/Dockerfile`).
- **Proef:** `scripts/werkplek-e2e/bim-coordinatie.mjs`; de meting: `scripts/werkplek-e2e/bim-meting-botsingen.mjs`.

```bash
WP_BASIS=http://klant0.cloud.open-aec.localhost:8001 node bim-coordinatie.mjs <uitmap> <map met de modellen>
WP_BASIS=http://klant0.cloud.open-aec.localhost:8001 node bim-meting-botsingen.mjs <uitmap>
```

### Modellen van de proef

Gemaakt met `kern/scripts/variant.py` uit het kleine testmodel van de kern; twee opties zijn hiervoor toegevoegd
(`--zonder-naam` en `--kopie`):

```bash
python tests/models.py                      # klein.ifc
python scripts/variant.py klein.ifc constructie.ifc --zonder IfcDuctSegment
python scripts/variant.py klein.ifc installaties.ifc --alleen IfcDuctSegment --kopie IfcDuctSegment:0,0,3
python scripts/variant.py constructie.ifc constructie-v2.ifc --nieuwe-globalids 0.5
python scripts/variant.py constructie-v2.ifc constructie-v3.ifc --zonder-naam "Wand B 0"
```

Het kanaal staat dus twee keer in het installatiemodel (begane grond en eerste verdieping): twee botsingen, *Wand B 0* en
*Wand B 1*. De proef bevestigt de eerste (er komt een issue) en wijst de tweede af met een reden. Versie 3 van de constructie
mist *Wand B 0*, zodat een botsing echt verdwijnt.

## Uitkomst van de proef: 63 van 63 controles geslaagd

De 25 controles van fase 1b zijn gebleven; de stappen met de oude schermen (`ronde()`, *Issue maken*, de keuzelijst per botsing)
gebruiken de nieuwe: een snelle keuze, de knop *Bevestigen* en de status van de rij. Daarbij zijn 38 controles gekomen:

| Onderwerp | Controles |
|---|---|
| Starten | een ronde met *Constructie tegen installaties*; de titel is de keuze met datum en tijd |
| Werklijst | de emmerbalk telt op tot het totaal; het paneel past in de kolom; groeperen op verdieping; de kolom is 360 px op *Issues* en *Botsingen* en 280 px op *Eigenschappen* |
| Sneltoetsen | `J` en `K`; `X` met een **getypte** reden bewaart precies die reden |
| In 3D | het paar geïsoleerd in twee kleuren; *Alles tonen* zet terug; *Naar A* en *Naar B* brengen elk een ander element midden in beeld; een element dat niet te vinden is, wordt op de rij genoemd en het andere blijft gemarkeerd; van tabblad wisselen beëindigt het isoleren |
| Beoordelen | bevestigen maakt een issue met een badge op de rij; *Heropenen*; een groepsactie met bevestiging raakt alleen de getoonde rijen; een ronde met een opvolger is alleen-lezen, ook als de opvolger komt terwijl de rij open staat |
| Weergaven en regels | een weergave bewaren, loslaten, weer kiezen en verwijderen; het regelscherm bewaart een regel, en dan is *Volgens de projectregels* beschikbaar |
| Volgende rondes | de afwijzing komt terug met reden en ontwikkeling; een botsing die weg is staat in de emmer *weg* als *Opgelost*; haar issue staat op *Opgelost* met een reactie, met *Botsingsronde* als auteur |
| Lange namen | een ronde met namen van meer dan 140 tekens komt door; rij, groep, filter en issue passen in de kolom; bevestigen geeft een gekorte titel met de volledige naam in de omschrijving |

**Het geïsoleerde paar is gemeten, niet alleen bekeken.** De proef leest de pixels van het 3D-beeld (uit een schermafbeelding
van het canvas) en telt die in de kleur van A (`--theme-accent`, 217,119,6) en van B (`--color-semantic-info`, 37,99,235),
binnen een afstand van 60 in RGB, en de overige pixels die van de achtergrond verschillen. Geïsoleerd: 159.612 pixels A, 11.828
pixels B en 2.750 overige; na *Alles tonen* 0, 0 en 214.699. De rest is dus doorzichtig en de kleuren zijn weg. *Naar A* en
*Naar B* zijn op dezelfde manier gemeten: het zwaartepunt van het element ligt binnen 6 % van het midden. Wat de meting niet zegt, is
of de rest "mooi" doorzichtig is; dat is een visuele indruk (zie hieronder).

Tijden in de werkplek (kleine modellen): omzetten en laden van beide modellen 13 s; een ronde van starten tot resultaat 5 s; een
nieuwe versie omzetten en koppelen 15 s; isoleren tot het beeld stilstaat 1,2 s.

### Gevonden en opgelost

Dit was de eerste keer dat de nieuwe schermen in een browser draaiden en dat een ronde op deze modellen liep. Deze fouten zijn gevonden
door de proef, een beoordeling van de hele branch, of deze meting, en hersteld, met een test.

| Bevinding | Oorzaak | Oplossing |
|---|---|---|
| **Elke ronde op de woning stopte met exitcode -11** | een wand zonder geometrie (de opening snijdt alles weg) laat de geometrieboom crashen; de kleine testmodellen raakten dit niet | een element zonder vertices gaat de boom niet in; in dit model zijn dat er 65 |
| **Een naam van meer dan 140 tekens legde de botsingen van het hele project plat** | `bulk_insert` valideert niet en de kolom is 140 tekens; `verwerk` faalde telkens, ook voor rondes van andere projecten | korten op de veldlengte, en een fout blijft bij die ene ronde |
| **Bevestigen faalde op echte elementnamen** | de titel van het issue is hoogstens 140 tekens | een gekorte titel, met de volledige namen in de omschrijving |
| **De diepte was geen doordringingsdiepte** | de diepte kwam van één straal uit de geometrieboom: een raam dat 2 mm in een dag steekt, kreeg 200 mm | het minimum van de straal en de kleinste overlap van de omhullende dozen; het botspunt wordt in die overlap geklemd |
| Een paar dat terugkwam, verloor zijn beslissing | een rij die weg was, onthield de beslissing niet | het veld `status_voor` |
| Een beslissing op een oude ronde ging stil verloren; twee rondes tegelijk splitsten de keten | de vorige ronde werd bij de start bepaald en al gelezen | een ronde met een opvolger is alleen-lezen, een tweede lopende ronde in een reeks wordt geweigerd, en een ronde zonder verandering stopt na 2 uur |
| `X` typte een "x" in het redenveld; `B` vasthouden bevestigde rij na rij | geen `preventDefault`, en `e.repeat` niet bekeken | beide afgevangen; de proef typt nu echt |
| Een element zonder naam toonde de GlobalId; een rij die weg was, verloor haar namen | de app liet `klasse` en de namen vallen | de velden gaan mee |
| *Naar A* en *Naar B* keken op de verkeerde plek bij een tweede model | de transformatie van het model werd dubbel toegepast | één keer |
| Isoleren faalde stil als een element niet gevonden werd | geen terugmelding | de rij noemt wat ontbreekt; niets gevonden betekent niets doorzichtig |
| Een ronde met een snelle keuze mislukte direct met "Input should be a valid string" | de app stuurde `regel: null` naar de kern | het veld gaat alleen mee als er een regel is |
| De zes keuzelijsten van de filters lieten per veld één teken zien | `flex: 1` met `min-width: 0` in een kolom van 360 px | elk veld minstens 8,5 rem, de zoekbalk de hele breedte |
| Een botsing die direct na een tabwissel in beeld kwam, werd weer gewist | herstel en markeren waren twee stappen in de wachtrij | één stap |
| De reden van een weigering kwam niet bij de viewer | de werkplek gooide de foutcode van de site weg | de code gaat mee |

De tests van de app wissen alle ruimtes op de site waarop ze draaien; een commit in de geteste code maakt dat blijvend. Op deze
bench is zo de demoruimte verdwenen. Ze draaien nu alleen op een eigen testsite (`test.localhost`); de tests weigeren elke andere
site. De tests van de opslag-app hebben die beveiliging nog niet.

## Meting op de demomodellen

### Modellen

De twee demomodellen uit de ruimte *Demo Open BIM*: `woning.ifc` (49 MB, IFC2X3, 3.714 elementen, discipline *Architectuur*) en
`voorbeeld.ifc` (73 MB, IFC4, 14.749 elementen, discipline *Voorbeeld*). **Dit zijn twee verschillende gebouwen die rond hetzelfde
nulpunt staan.** Elke botsing *tussen modellen* is dus een toevallige overlap van twee gebouwen die niets met elkaar te maken hebben. Die
ronde zegt iets over de duur en over de indeling, niet over een echte coördinatie. Wie dat wil meten, heeft twee disciplinemodellen van
één gebouw nodig.

Omzetten en laden van beide modellen 147 s (193,7 MB geheugen in de viewer van 2 GB).

### Rondes

| Ronde | Duur | Botsingen | Te beoordelen | Contact | Aangrenzend |
|---|---:|---:|---:|---:|---:|
| Tussen modellen | 871 s | 664 | 654 | 0 | 10 |
| Harde botsingen | 871 s | 10.069 | 1.296 | 689 | 8.084 |

De duur is van starten tot klaar, en zit vooral in het laden: alleen de geometrie van het voorbeeldmodel inlezen kostte los gemeten
11 tot 13 minuten. Beide rondes laden hetzelfde en rekenen daarna kort, dus ze duren even lang.

**De emmers halen 87 % weg.** Van de 10.069 harde botsingen blijven er 1.296 te beoordelen. Dat zijn er nog steeds veel; het
groeperen en de groepsacties zijn daarvoor nodig.

**Ernst en emmer.**

| Ronde | Te beoordelen: kritiek | groot | klein | Contact: klein | Aangrenzend: klein |
|---|---:|---:|---:|---:|---:|
| Tussen modellen | 15 | 616 | 23 | 0 | 10 |
| Harde botsingen | 15 | 1.007 | 274 | 689 | 8.084 |

**Redenen.** Harde botsingen: aansluiting 8.058, contact 689, verbonden 23, samenstel 3. Tussen modellen: aansluiting 10.

**Diepte.** De grootste diepte is 0,5 m (harde botsingen) en 0,3 m (tussen modellen).

| Diepte | Harde botsingen | Tussen modellen |
|---|---:|---:|
| onder 5 mm | 1.886 | 0 |
| 5 tot 20 mm | 1.102 | 24 |
| 20 tot 50 mm | 6.310 | 95 |
| 50 tot 200 mm | 677 | 471 |
| 200 mm tot 1 m | 94 | 74 |

**Waar ze zitten.** Harde botsingen per paar disciplines: *Voorbeeld × Voorbeeld* 8.084, *Architectuur × Architectuur* 1.321, *Architectuur ×
Voorbeeld* 664. De grootste groepen: *IfcBeam × IfcSlab* 6.243 en *IfcBeam × IfcBeam* 1.139, vooral ankerrails die in de vloer zijn
gestort. Per categorie: constructie × constructie 8.302, afwerking × constructie 932, afwerking × afwerking 803, constructie × installaties 16.

### Steekproef: klopt de indeling?

Per emmer van *Harde botsingen* drie botsingen, geopend in de viewer met het paar in twee kleuren.

| Emmer | Botsing | Oordeel |
|---|---|---|
| Te beoordelen | #13 buitenblad × gootconstructie, 24 mm, groot | klopt: een echte overlap in dezelfde gevel |
| | #701 regenwaterafvoer × vloer, 80 mm, kritiek | klopt volgens de regels: een installatie door een constructief element. Hier is het de woning door de vloer van het andere gebouw, dus inhoudelijk toeval |
| | #28 stalen latei × buitenblad, 41 mm, groot | twijfel: de oplegging van een latei in metselwerk is gewoonlijk bedoeld, maar is ook een echte overlap van meer dan 20 mm |
| Contact | #38 stelkozijn × gevelisolatie, 0 mm | klopt: raakvlak |
| | #55 zinkwerk × boeideel, net onder 5 mm | klopt: de naam zegt het al, en de overlap is klein |
| | #219 zinkwerk × raam, 0 mm | klopt: raakvlak |
| Aangrenzend | #1988 ankerrail × vloer, 24 mm, reden *aansluiting* | klopt: een in de vloer gestorte rail; dit is de grootste groep en die wil niemand per stuk nalopen |
| | #627 twee delen van een samenstel, 32 mm, reden *samenstel* | klopt |
| | #816 twee delen buitenblad, 0 mm, reden *verbonden* | volgens de gegevens; niet los bekeken in de viewer |

Van de acht bekeken botsingen klopt de indeling bij zeven, bij één is er twijfel, en geen is aantoonbaar fout. De negende is alleen uit
de gegevens beoordeeld. Dit is een steekproef van negen op 10.069; een uitspraak over de hele indeling is dat niet.

### Isoleren met beide modellen geladen

Acht botsingen na elkaar uit *Harde botsingen*, met beide modellen in de viewer. Elke meting neemt zelf een schermafbeelding van het
canvas, enkele honderden milliseconden; de tijden zijn dus aan de hoge kant.

| | Laagste | Mediaan | Hoogste |
|---|---:|---:|---:|
| Klik tot de kleuren in beeld staan | 488 ms | 666 ms | 791 ms |
| Klik tot het beeld stilstaat | 694 ms | 911 ms | 1.206 ms |
| *Alles tonen* tot het beeld stilstaat | 437 ms | 587 ms | 659 ms |

`ISOLATE_GHOST` blijft aan: het doorzichtig maken kost volgens losse metingen op een ander model 10 tot 25 ms van een klik, dus
uitzetten wint niets. De camera springt zonder overgang, zodat `J` niet achter de vlucht aan loopt.

Bij klik 2 kwam *Alles tonen* niet onder de grens van de meting: 1.487 pixels bleven dicht bij de kleur van B, en de wachttijd liep
af. In de viewer bekeken zijn dat blauwe elementen van het model zelf die daar in beeld staan, geen achtergebleven markering. Het is
een grens van de meting, niet van de viewer.

## Tekortkomingen

- **Een ronde duurt op dit model bijna een kwartier, ook als er weinig te rekenen is.** Elke ronde laadt de geometrie opnieuw. Een
  bewaarde boom per modelversie zou dit grotendeels weghalen.
- **Een klein element in een groot element blijft soms onzichtbaar.** Bij een ankerrail in een vloer staat de vloer ondoorzichtig blauw
  om de rail heen, en bij #627 is alleen B te zien. De camera staat goed, maar A zit erachter of erin. Een van beide half doorzichtig
  tekenen zou helpen.
- **Na *Alles tonen* blijft de camera dicht op het paar staan.** Het beeld is dan vaak één grijs vlak van een nabije wand. Terug naar het
  vorige standpunt staat niet in het ontwerp en is niet gebouwd.
- **De oplegging van een latei staat in *te beoordelen*.** Dit is niet met een drempel op te lossen, wel met een regel per klassenpaar.
- **Een doorsteek door een element dunner dan 5 mm telt als contact**, als gevolg van de manier waarop de diepte nu wordt bepaald.
- **De diepte kan nog te laag zijn.** De bibliotheek gaf in een controle op 400 dozenparen in 3 gevallen een veel te kleine waarde,
  en vond 45 echte overlappen met samenvallende vlakken helemaal niet, waaronder twee balken met 1 m overlap. Dat is de bestaande
  detectie, en die is niet veranderd.
- **Ook een hele lange ronde kan verlopen.** Een ronde zonder verandering in de voortgang stopt na 2 uur, en binnen één controle beweegt de
  voortgang niet. Op deze modellen is dat ruim genoeg; op een veel grotere federatie is het niet gemeten.

## Drempels

Niet bijgesteld. De steekproef geeft geen reden: de 5 mm van *contact*, de 20 mm van *groot* en de 50 mm van *aansluiting* sluiten aan op wat
hier te zien is. Dat 6.310 botsingen tussen 20 en 50 mm zitten, komt door de ankerrails, en die vallen terecht onder *aansluiting*.

## Niet geverifieerd

- Geen twee disciplinemodellen van één gebouw: de ronde *Tussen modellen* gaat hier over toevallige overlappen.
- Geen federatie van 288 MB gemeten; deze meting gaat over 122 MB IFC.
- *Constructie tegen installaties* is op deze modellen niet als eigen ronde gedraaid, wel in de proef op kleine modellen. Kritiek komt
  hier voor via *Harde botsingen*.
- De isolatietijden zijn gemeten op één laptop, met een schermafbeelding per meting.
- `ronde_verlopen`, een echte storing van de opslag en het lange-naamgedrag op echte modellen zijn alleen met tests en de proef
  gedekt, niet met een echte storing.
