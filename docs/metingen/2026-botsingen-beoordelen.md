# Meting botsingen beoordelen: de werklijst in de werkplek

Acceptatie van het beoordelen van botsingen (plan `2026-11-04-botsingen-beoordelen`, taak 11): een ronde starten met een
snelle keuze, de emmers, groeperen, sneltoetsen, afwijzen met een reden, bevestigen tot een issue, een volgende ronde met de
ontwikkeling, en het paar geïsoleerd in beeld, beproefd via de GUI in de werkplek van een lokale SuperCloud.

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

## Uitkomst van de proef: 40 van 40 controles geslaagd

De 25 controles van fase 1b zijn gebleven; de stappen met de oude schermen (`ronde()`, *Issue maken*, de keuzelijst per botsing)
gebruiken de nieuwe: een snelle keuze, de knop *Bevestigen* en de status van de rij. Daarbij zijn 15 controles gekomen:

| Controle | Uitslag |
|---|---|
| een ronde gestart met *Constructie tegen installaties* (twee botsingen) | geslaagd |
| de emmerbalk telt op tot het totaal (2 + 0 + 0 = 2) | geslaagd |
| het paneel past in de kolom met de werklijst | geslaagd |
| groeperen op verdieping toont een groep per verdieping | geslaagd |
| `J` springt naar de volgende botsing, `K` terug | geslaagd (2 controles) |
| het paar staat geïsoleerd in beeld: twee kleuren, de rest doorzichtig | geslaagd |
| *Alles tonen* zet het beeld terug | geslaagd |
| `X` met een reden wijst de botsing af | geslaagd |
| bevestigen maakt een issue (en *een botsing is een issue geworden*: precies één issue *Botsing …* in de modelmap) | geslaagd |
| de tweede ronde toont de afwijzing met reden en de ontwikkeling (*Blijft*) | geslaagd |
| een botsing die weg is staat in de emmer *weg* als *Opgelost* | geslaagd |
| haar issue staat op *Opgelost* met een reactie van *Botsingsronde* | geslaagd |
| de kolom rechts is 360 px op *Issues* en *Botsingen* en 280 px op *Eigenschappen* | geslaagd |
| van tabblad wisselen beëindigt het geïsoleerde beeld | geslaagd |

**Het geïsoleerde paar is gemeten, niet alleen bekeken.** De proef leest de pixels van het 3D-beeld (uit een schermafbeelding
van het canvas) en telt die in de kleur van A (`--theme-accent`, 217,119,6) en van B (`--color-semantic-info`, 37,99,235),
binnen een afstand van 60 in RGB, en de overige pixels die van de achtergrond verschillen. Geïsoleerd: 39.840 pixels A, 1.606
pixels B en 2.262 overige; na *Alles tonen* 0, 0 en 131.563. De rest is dus doorzichtig (ruim vijftig keer minder inhoud) en
de kleuren zijn weg. De schermafbeeldingen staan als `03b-paar-geisoleerd.jpg` en `03c-alles-getoond.jpg`. Wat de meting niet
zegt, is of de rest "mooi" doorzichtig is; dat is een visuele indruk (zie de meting op de echte modellen).

Tijden in de werkplek (kleine modellen): omzetten en laden van beide modellen 13 s; een ronde van starten tot resultaat 6 s
(in de kern 5,1 s); een nieuwe versie omzetten en koppelen 15 s en 21 s; isoleren tot het beeld stilstaat 2 s.

### Gevonden en opgelost tijdens de acceptatie

Dit was de eerste keer dat de nieuwe schermen in een browser draaiden.

| Bevinding | Oorzaak | Oplossing |
|---|---|---|
| Een ronde met een snelle keuze mislukte direct met "Input should be a valid string" | de app stuurde `regel: null` naar de kern, die `regel` als tekst leest | het veld gaat alleen mee als er een regel is; test in `test_botsingen.py` |
| De zes keuzelijsten van de filters lieten per veld één teken zien | `flex: 1` met `min-width: 0` in een kolom van 360 px | elk veld minstens 8,5 rem, de zoekbalk de hele breedte |
| Een botsing die direct na een tabwissel in beeld kwam, werd door het opnieuw markeren van de selectie weer gewist | herstel en markeren waren twee stappen in de wachtrij; een isolatie ertussen verloor | beide zijn één stap in de wachtrij |
| Het testmodel gaf maar één botsing | `variant.py --kopie` kopieerde de vorm van het element niet | de vorm wordt diep gekopieerd, met dezelfde context; test |

Ook de proef zelf had twee eigen fouten die de uitslag niet veranderden maar de controles betrouwbaarder maken: het aantal in de
lijst werd gelezen voordat het bekend was, en het beeld werd gemeten voordat een asynchrone isolatie of herstel was uitgevoerd
(nu wacht de proef eerst op de toestand en dan op stilstand; de eisen zijn niet verlaagd).
