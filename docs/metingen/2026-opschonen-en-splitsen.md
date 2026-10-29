# Meting: opschonen en splitsen op een compacte STEP-index

Vóór het omzetten schoont de kern een IFC nu verliesvrij op en splitst hij grote bestanden met een eigen splitser.
Beide werken op dezelfde STEP-index in `kern/converter/stepindex.mjs`. De volgorde in `convert_model` is: opschonen →
splitsen (boven `OPENBIM_SPLITS_VANAF_BYTES`) → fragments → index.

Aanleiding: de splitser van `@thatopen/fragments` hield een object per regel bij (~320 B per regel, ~6,4 × de
bestandsgrootte), zodat een model van 1,76 GB splitsen ~11 GB vroeg (`2026-fase-0.md`). Alles daarna schaalt met het
aantal STEP-regels: IfcOpenShell neemt 12–13 GB per GB IFC. Minder regels scheelt dus in elke volgende stap.

## Wat er gebouwd is

**STEP-index.** Het bestand wordt in stukken van 4 MB als bytes gelezen, zonder een string of object per regel. Per
record staan id, type, positie in het bestand en de verwijzingen (met per verwijzing het attribuut en of hij in een
lijst staat) in getypte arrays; een id wordt een volgnummer via een vlakke tabel. Voor opschonen komt er per record
een hash van 64 bit bij van de tekst zonder id, witruimte en verwezen ids. Strings (ook met `;`, `#`, `''` en
`/*`), commentaar en records over meerdere regels worden goed gelezen; bytes buiten ASCII blijven ongemoeid.

**Opschonen (verliesvrij).** Twee records zijn gelijk als type en tekst gelijk zijn en ze naar dezelfde (samengevoegde)
records verwijzen; dat wordt van onder naar boven bepaald, eerst punten, richtingen en waarden, dan wat ernaar
verwijst. Verwijzingen worden herschreven naar het eerste record van elke groep; de ids van wat blijft, blijven gelijk.
Wat zijn eigen identiteit houdt:

- alles met een GlobalId, plaatsingen, representaties en contexten (die horen bij hun product of project);
- records waarvoor het schema maar één verwijzer toestaat (een `IfcStyledItem` per representatie-item, een
  `IfcMaterialLayer` in één laagset, in IFC2X3 een plaatsing per product); de tabel daarvoor komt uit de schema's
  van IfcOpenShell (`scripts/step_schema.py` → `converter/schema.json`);
- de records waar een annotatie naar wijst (een stijl, een laag, een materiaalweergave, een externe verwijzing):
  samengevoegd zou een rode en een blauwe wand met dezelfde vorm allebei beide kleuren krijgen;
- leden van een SET of een `LIST OF UNIQUE` die door het samenvoegen dubbel zouden komen (twee samenvallende
  punten in één `IfcPolyLoop`, twee gelijke eigenschappen in één set); dan begint het samenvoegen opnieuw.

Verweesd zijn alleen geometrie, profielen, eigenschappen, hoeveelheden, stijlen en eenheden waar (via andere records)
niets naar verwijst; wat verder los staat (een persoon, een eigenaarsgeschiedenis) blijft. Bij het schrijven wordt
elk weggelaten duplicaat opnieuw vergeleken met het record dat het vervangt: byte voor byte als beide in de
leesbuffer staan, anders met een tweede, onafhankelijke hash van 64 bit (128 bit samen met de eerste). Een verschil
stopt het opschonen; `convert_model` zet dan de bron om zoals hij is en noteert waarom.

**Splitsen.** Zelfde contract als de splitser van fragments: `split <in> <n> <map>` geeft `{"delen": [...]}`. Elk
product behalve de ruimtelijke structuur (elementen, ruimten, poorten, rasters, annotaties) staat in precies één deel,
samen met zijn sparingen, vullingen, geaggregeerde en geneste delen en poorten; de typelijsten komen uit
`WEBIFC.InheritanceDef`. De delen worden verdeeld op het aantal bytes van hun producten (zwaarste groep eerst naar
het lichtste deel). Elk deel krijgt de ruimtelijke structuur en alles waar zijn producten naar verwijzen. Een relatie
gaat naar elk deel met producten die ze verbindt, met haar lijsten ingekort tot die producten; een relatie zonder
producten (eigenschappen van een type, een groep) gaat mee waar haar objecten zijn; een annotatie (stijl, laag) gaat
mee met wat ze annoteert. Nieuw ten opzichte van fragments: geneste delen en poorten blijven bij hun element, en
relaties met één verwijzing aan de gerelateerde kant (`IfcRelNests`, ruimtegrenzen) worden niet meer tot een
ongeldige lijst herschreven.

## Opzet

- **Machine:** dezelfde laptop als in fase 0 (Intel Core i9-14900HX, 24 kernen, 32 GB, Windows 11 Pro).
- **Kern:** Python 3.12.10, IfcOpenShell 0.8.4.post1, Node 24.11, `@thatopen/fragments` 3.6.0, `web-ifc` 0.0.78.
- **Geheugen:** de piek van het proces zoals Node die zelf meldt (`maxRSS`) en zoals de waakhond hem meet.
- **Synthetisch:** `ifc_small` uit de tests, met `scripts/enlarge.py` vergroot. Dat zijn duizenden kopieën van één
  model, dus goed voor geheugen en tijd, niet om de winst van opschonen te meten (vrijwel elke kopie valt weg).
- **Echt:** dezelfde twee openbare modellen als in fase 0: een woningbouwmodel (IFC2X3, 47 MB, 6 verdiepingen) en een
  voorbeeldmodel van een hoogbouwconstructie met funderingspalen (IFC4, 70 MB, 25 verdiepingen).

MB = MiB, zoals in fase 0.

## Uitkomst: geheugen en tijd (synthetisch)

| IFC | stap | s | piek (MB) | piek / grootte | index per record |
|---|---|---:|---:|---:|---:|
| 94 MB, 1,85 mln records | opschonen | 1,7 | 179 | | 51,6 B |
| | splitsen in 4 | 1,4 | 160 | | 37,9 B |
| 979 MB, 18,5 mln records | opschonen | 19,9 | 902 | 0,92 | 51,9 B |
| | splitsen in 4 | 15,2 | 727 | 0,74 | 37,8 B |
| | splitsen in 3, splitser van fragments | 106,6 | 4025 | 4,1 | |
| | splitsen in 3, nieuwe splitser | 9,7 | 728 | 0,74 | |

- Splitsen gaat op hetzelfde bestand van ~4 GB naar ~0,7 GB en van 107 s naar 10 s; de delen zijn op 2 % na even
  groot (op bytes verdeeld). In fase 0 piekte de oude splitser op 6,4 × de grootte bij een ander bestand; het aantal
  bytes per record verschilt per bestand.
- Opschonen kost per record ~52 B: id, type, positie, verwijzingen, twee hashes, de representant en een hashtabel.
  Een proces van Node met de typen van web-ifc geladen begint op ~107 MB.
- Beide lopen lineair: tien keer zo groot is tien keer zo lang en (boven die 107 MB) tien keer zoveel geheugen.

## Uitkomst: echte modellen

`measure.py --vergelijk` op de twee openbare modellen:

| model | MB voor | MB na | records voor | records na | samengevoegd | verweesd | s | piek (MB) | inhoud |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| woningbouw, IFC2X3 | 47,0 | 19,5 | 714 485 | 284 541 (−60 %) | 425 757 | 4 187 | 1,1 | 135 | gelijk |
| hoogbouw, IFC4 | 69,9 | 42,6 | 966 420 | 541 007 (−44 %) | 420 224 | 5 189 | 1,7 | 148 | gelijk |

- **Wat samenvalt:** vooral eigenschapswaarden (`IfcPropertySingleValue` 158 duizend en 131 duizend), hoeveelheden
  (`IfcQuantityLength` 73 duizend, `IfcQuantityArea` 25 duizend in het woningbouwmodel), punten (62 en 114 duizend)
  en vlakken van breps (`IfcPolyLoop`, `IfcFaceOuterBound`, `IfcFace`: elk ~21 duizend), in het hoogbouwmodel ook
  21 duizend segmenten van samengestelde krommen. Een exporteur schrijft voor elk element eigen kopieën.
- **Wat verweesd was:** in het woningbouwmodel 94 breps met hun vlakken en punten waar niets naar verwijst, in het
  hoogbouwmodel 5 046 losse `IfcAxis2Placement3D`.

Wat dat scheelt in de stappen erna, hetzelfde model voor en na opschonen, elke stap in een eigen proces:

| model | stap | bron | opgeschoond |
|---|---|---|---|
| woningbouw | fragments | 6,8 s, piek 517 MB, 6,1 MB `.frag` | 3,5 s, piek 376 MB, 2,7 MB `.frag` |
| | index (IfcOpenShell) | 10,0 s, piek 570 MB | 9,6 s, piek 298 MB (−48 %) |
| hoogbouw | fragments | 16,7 s, piek 671 MB, 9,9 MB `.frag` | 15,6 s, piek 508 MB, 8,1 MB `.frag` |
| | index (IfcOpenShell) | 37,3 s, piek 858 MB | 25,4 s, piek 583 MB (−32 %) |

- De eigenschappen-index (`eigenschappen.sqlite`) is in beide gevallen even groot en heeft dezelfde rijen.
- **Het `.frag` is kleiner, de weergave gelijk.** Per GlobalId hetzelfde aantal geometrie-instanties met dezelfde
  begrenzing in wereldcoördinaten (op 1 mm), en dezelfde representaties, materialen en transformaties. Wat afneemt
  is het aantal lokale ids van fragments, één per IFC-record: 341 duizend → 67 duizend (woningbouw), 300 duizend →
  169 duizend (hoogbouw).
- De viewer schat zijn geheugen als 18 × het `.frag`. Die schatting daalt mee, maar de geometrie is dezelfde: de
  werkelijke post in de browser daalt waarschijnlijk minder. Opnieuw meten in de viewer is een vervolgstap.

## Controle: inhoudelijk gelijk

- `openbim_kern.compare.model_differences` (ook `measure.py --vergelijk`): per GlobalId een vingerafdruk van alles
  waar het record naar verwijst, tot op de coördinaat, waarbij een verwijzing naar een ander record met GlobalId telt
  als die GlobalId; annotaties zonder GlobalId als verzameling; en de samenvatting van de kern (schema, eenheid,
  georeferentie, begrenzing, aantallen per klasse en verdieping). Beide echte modellen: gelijk.
- De tests (`kern/tests/test_clean.py`): dezelfde rijen in de eigenschappen-index (elementen, property sets,
  materialen, classificaties, typen), dezelfde geometrie per element (driehoeken van IfcOpenShell in
  wereldcoördinaten), en per regel van het samenvoegen een geval in een handgeschreven model (`tests/dubbel.ifc`):
  dubbele punten en waarden worden één, verwijzingen kloppen, gestileerde geometrie, materiaallagen en de leden van
  een SET houden hun eigen record, wezen gaan weg, het origineel blijft onaangeroerd.
- Splitsen (`kern/tests/test_split.py`): de index over de delen samen is die van het model, elk product in precies
  één deel, geen verwijzingen naar records buiten het deel, relaties per deel ingekort, sparingen, vullingen en
  poorten bij hun element, stijlen en lagen bij hun geometrie.
- Geheugen: tests op de bytes per record van de index en op de piek van het proces boven die van een klein bestand.

## Instellingen

- `SPLIT_MEMORY_FACTOR` van 7 naar 2 en een nieuwe `CLEAN_MEMORY_FACTOR` van 2,5 (grens = factor × grootte + 1 GB).
  Gemeten is 0,74 en 0,92; de marge is voor bestanden met kortere records: de index kost per record, en bij ~25 B
  per record (alleen punten) is hij ~2 × de bestandsgrootte.
- Of er gesplitst wordt, hangt nog af van de grootte van de bron (de doeladressen zijn daarop gepland); gesplitst
  wordt het opgeschoonde bestand, dus de delen zijn kleiner dan `OPENBIM_DEEL_BYTES`.
- Het opgeschoonde IFC staat tijdens het omzetten in de werkmap naast de bron (bij deze modellen 40–60 % van haar
  grootte) en wordt niet afgeleverd.

## Niet in deze stap, en vervolg

- **Met verlies vereenvoudigen** (te fijne tessellaties) hoort niet bij opschonen: het verandert de vorm, en
  botsingen en hoeveelheden willen de echte vorm. Een vervolgstap, alleen voor het weergavebestand.
- **Eigen grote modellen:** de winst hangt af van de exporteur. Een meting met echte modellen van meer dan 1 GB
  volgt zodra de eigenaar die aanlevert (`measure.py <map> --uit <rapport.md> --vergelijk`).
- **Het opgeschoonde IFC bewaren** als afgeleide, zodat latere modelsessies in IfcOpenShell er ook van profiteren
  (minder records, minder geheugen): een afweging tegen de opslag, voor de eigenaar.
- **Omzetterversie:** `kern-0.1.0+fragments-3.6.0` is niet opgehoogd, hoewel `.frag` en delen veranderen. Ophogen
  laat bestaande versies lui opnieuw omzetten; ook dat is een keuze voor de eigenaar.
- Samenvoegen is bewust voorzichtig: plaatsingen, representaties en gestileerde geometrie houden hun identiteit,
  ook waar het schema samenvoegen zou toestaan.

## Opnieuw meten

```bash
cd kern
python scripts/enlarge.py <in.ifc> 100000 <groot.ifc>
node converter/convert.mjs clean <groot.ifc> <opgeschoond.ifc>
node converter/convert.mjs split <groot.ifc> 4 <map>
python scripts/measure.py <map met modellen> --uit <rapport.md> --vergelijk
```
