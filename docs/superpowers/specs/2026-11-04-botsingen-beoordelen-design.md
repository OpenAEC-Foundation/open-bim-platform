# Botsingen beoordelen: ontwerp

Status: ontwerp voor de volgende stap na fase 1b. Bouwt voort op `2026-10-26-open-bim-platform-design.md` (5.5, 5.6, 7.1)
en op de botsingsrondes van fase 1b. Keuzes van de bouwer staan als *(keuze)*.

## 1. Doel en waarom

Een botsingsronde levert nu een platte lijst paren met GlobalIds, gegroepeerd op klassenpaar, met één keuzelijst voor de
status. Bij echte modellen zijn dat er honderden tot duizenden, waarvan veel geen probleem zijn: een deur in zijn wand,
een balk die net in een kolom steekt. De coördinator moet er dan zelf doorheen.

Met dit werk ziet een coördinator meteen wat telt, werkt hij een lijst in vaste stappen af zonder muis, en onthoudt het
platform die beslissingen over rondes en versies heen. Dat is de kern van het dagelijkse coördinatiewerk. Het sterke deel
van het platform blijft de basis: rechten via Storage, versiekoppeling, auditlog en BCF-API. Alle code is eigen werk;
er wordt geen code uit andere producten overgenomen.

## 2. Doelen

1. Een startvenster met snelle keuzes, zodat je zonder sets in te vullen een zinnige ronde start.
2. Een waarschuwing vooraf als de gekozen modellen elkaar niet overlappen.
3. Regels per disciplinepaar, per project bewaard: soort, afstand en ernst.
4. Slimme indeling: elementen die bij elkaar horen (een deur in zijn wand, delen van een samenstel, verbonden elementen)
   komen apart te staan, zonder dat een botsing verdwijnt.
5. Ernst en categorie per botsing, en een balk met *te beoordelen*, *alleen contact* en *bedoeld aangrenzend*.
6. Groeperen op klassenpaar, verdieping, disciplines, ernst, categorie, raster, ruimte of ontwikkeling.
7. Bevestigen, accepteren en afwijzen met reden, per knop of sneltoets; daarna springt de selectie naar de volgende.
8. Beslissingen gaan mee naar volgende rondes, langs de versiekoppeling.
9. Per ronde *nieuw*, *blijft*, *terug* en *weg*, en een verloop over rondes.
10. Een issue sluit vanzelf als zijn botsing weg is en heropent als ze terugkomt.
11. Filters met aantallen en bewaarde weergaven per project.
12. Een botsing openen isoleert het paar in beeld, met namen in plaats van alleen GlobalIds.

**Klaar als:** de werkplekproef een ronde met een voorinstelling start, op de botsingen filtert, groepeert, met het
toetsenbord beoordeelt en afwijst met reden; een tweede ronde na een nieuwe versie de beslissingen en het issue volgt; en
geen pagina-fouten geeft. Op de demomodellen (49 en 73 MB) is het in de browser te zien.

## 3. Niet-doelen

- Rapporten, plaatjes per botsing en overzichtskaarten (golf 3 en #7).
- Toewijzen per botsing; dat loopt via het issue.
- Groeperen op meer niveaus tegelijk.
- Sparingen beoordelen: een kanaal door een uitgespaarde opening geeft al geen harde botsing, en *ontbrekende sparing* hoort
  bij golf 3.
- Volumes van overlap via booleaanse bewerkingen; de indeling gebruikt de doordringingsdiepte van de kern.
- Alleen gewijzigde elementen opnieuw rekenen.
- AI-hulp bij beoordelen.
- Een matrix als scherm: de regels zijn een lijst paren, omdat de kolom smal is.

## 4. Randvoorwaarden

- De rechten en lagen blijven zoals in het hoofdontwerp: de viewer praat alleen via `bim.*`-berichten met de gastpagina,
  de gastpagina met `openaec_bim.api_coordinatie`, en de app met de kern. Lezers mogen kijken en filteren; alleen wie in de
  modelmap mag schrijven, mag beoordelen, regels wijzigen en weergaven bewaren.
- De viewer bewaart niets in de browser (werkplek-contract). Regels en weergaven staan op de server.
- Het OpenAEC-stijlboek geldt volledig. Geen eigen kleuren buiten de tokens, behalve de twee kleuren voor het paar in 3D.
- Alle tellingen zijn eerlijk: de som van de emmers is gelijk aan het totaal. De indeling verbergt alleen, ze gooit nooit
  iets weg.
- Taal: documentatie Nederlands, code in `kern/` en `viewer/` Engels; `frappe/` volgt de bestaande Nederlandse namen.
- Vertalingen in `viewer/src/i18n/nl.json` en `en.json`.
- De app en de kern gaan samen de lucht in; de app stuurt alleen de nieuwe invoer. De app leest de uitvoer wel tolerant (zie
  7.3), omdat een ronde die vóór de uitrol is gestart nog een resultaat in de oude vorm kan opleveren *(keuze)*.

## 5. Termen

| Term | Betekenis |
|---|---|
| **controle** | Eén vraag aan de kern: set A tegen set B, met soort, tolerantie en eventueel een vaste ernst. |
| **ronde** | Een of meer controles, samen op de versies van het moment van starten. |
| **reeks** | Rondes die elkaar opvolgen: dezelfde snelle keuze, of bij *zelf instellen* dezelfde sets en soort. |
| **emmer** | Waar een botsing staat: `beoordelen`, `contact` of `aangrenzend`. Precies één. |
| **ernst** | `klein`, `groot` of `kritiek`. |
| **categorie** | Het paar families: `constructie × installaties`, enzovoort. |
| **ontwikkeling** | Wat de botsing deed ten opzichte van de vorige ronde: `nieuw`, `blijft`, `terug`, `weg`, `eerder_weg`. |

## 6. Kern (`kern/`)

### 6.1 Invoer van de tool `botsingen`

`BotsingIn` wordt `{controles: [BotsingControle], doel}`, met 1 tot 30 controles.

```json
{
  "regel": "Constructie × Installaties",
  "set_a": [{"sleutel": "...", "versie": "3", "bron": {}, "klassen": ["IfcBeam"]}],
  "set_b": [{"sleutel": "...", "versie": "2", "bron": {}, "klassen": null}],
  "soort": "hard",
  "tolerantie": 0.0,
  "ernst": null,
  "alleen_tussen_modellen": false
}
```

- `soort`: `hard`, `afstand` of `dubbel`.
- `ernst`: leeg of een vaste ernst voor botsingen in de emmer `beoordelen`.
- `alleen_tussen_modellen`: paren uit hetzelfde model tellen niet mee.

De oude velden `set_a`, `set_b`, `soort` en `tolerantie` vervallen in de tool. Er is nog geen uitrol, dus de app en de kern
wijzigen samen *(keuze)*.

### 6.2 Rekenen

- Elk bestand wordt één keer gelezen en getrianguleerd, ook bij meerdere controles. `find_clashes` splitst daarvoor op in een
  scène die de bestanden en de boom laadt, en een vraag per controle. `find_clashes(set_a, set_b, soort, tolerantie)` blijft
  bestaan voor de bestaande tests.
- Volgorde: eerst `dubbel`, dan `hard`, dan `afstand`. Een paar komt één keer voor; de eerste controle die het vindt, wint.
- `dubbel`: paren met dezelfde klasse en een omhullende doos die per zijde hoogstens 10 mm afwijkt. De dozen komen uit de
  vertices tijdens het trianguleren. Dit gaat niet via een harde vraag: exact samenvallende volumes hebben coplanaire vlakken
  en geven in de geometrieboom geen botsing. `punt` is het midden van de doos en `afstand` de kleinste maat ervan.
- `hard`: `afstand` is het minimum van de afstand van de geometrieboom en de kleinste overlap van de twee omhullende dozen, over
  de drie assen. De afstand van de boom is de lengte van één straal langs een vlaknormaal, geen doordringingsdiepte: een raam dat
  2 mm in een dag steekt kan zo 400 mm krijgen. De echte diepte is nooit groter dan de overlap van de dozen. `punt` is het midden
  van die overlap, omdat raster, ruimte en camera daarvan afhangen. Bij `afstand` en `dubbel` verandert hier niets.
- De detectie blijft die van de geometrieboom: echte overlappen met samenvallende vlakken worden niet altijd gevonden. In een
  controle met 400 willekeurige dozenparen ontbraken er 45, waaronder twee balken met 1 m overlap.
- `IfcVirtualElement` valt voortaan af, naast de al uitgesloten openingen.
- De tool meldt voortgang: laden tot 50% (naar bestandsgrootte), controles tot 90% (per controle), context tot 100%. De voortgang
  wordt alleen weggeschreven als een heel procent verandert.

### 6.3 Uitvoer per botsing

```json
{
  "a": {"sleutel": "...", "versie": "3", "globalid": "...", "klasse": "IfcWall", "naam": "Wand B 0", "verdieping": "00 begane grond"},
  "b": {"...": "..."},
  "punt": [1.0, 2.0, 3.0],
  "afstand": 0.05,
  "soort": "hard",
  "regel": "Constructie × Installaties",
  "emmer": "beoordelen",
  "emmer_reden": null,
  "ernst": "kritiek",
  "categorie": "constructie × installaties",
  "raster": "C-4",
  "ruimte": "Gang 1"
}
```

### 6.4 Indeling (een nieuwe module, `clash_context.py`)

Puur en uitlegbaar; elke regel heeft een code in `emmer_reden`. In volgorde, de eerste die past wint. Elke drempel is een
benoemde constante.

| Regel | Voorwaarde | Emmer | `emmer_reden` |
|---|---|---|---|
| vulling | hetzelfde model; een element vult een opening in het andere (`IfcRelFillsElement` en `IfcRelVoidsElement`) | `aangrenzend` | `vulling` |
| samenstel | hetzelfde model; ouder en kind, of kinderen van dezelfde ouder (`IfcRelAggregates`) | `aangrenzend` | `samenstel` |
| verbonden | hetzelfde model; `IfcRelConnectsElements` of een subtype | `aangrenzend` | `verbonden` |
| systeem | beide installatie, hetzelfde `IfcSystem`, diepte onder 50 mm | `aangrenzend` | `zelfde_systeem` |
| aansluiting | beide constructie, soort `hard`, diepte onder 50 mm | `aangrenzend` | `aansluiting` |
| contact | soort `hard`, diepte onder 5 mm | `contact` | `contact` |
| de rest | | `beoordelen` | leeg |

`dubbel` komt altijd in `beoordelen`, en de regels voor vulling, samenstel en verbonden gelden niet voor `dubbel`.

**Families.** `installaties`: `IfcDistributionElement`. `constructie`: `IfcBeam`, `IfcColumn`, `IfcFooting`, `IfcPile`,
`IfcMember`, `IfcSlab`, plus `IfcWall` met `Pset_WallCommon.LoadBearing` waar. `afwerking`: al het andere. De `categorie` is
het gesorteerde paar.

**Ernst.**

| Situatie | Ernst |
|---|---|
| emmer `contact` of `aangrenzend` | `klein` |
| `dubbel` | `groot` |
| `afstand` | `klein` |
| `hard`, diepte vanaf 20 mm, constructie × installaties | `kritiek` |
| `hard`, diepte vanaf 20 mm, overig | `groot` |
| `hard`, diepte onder 20 mm | `klein` |

Een vaste `ernst` van de controle gaat voor, maar alleen in de emmer `beoordelen`.

**Plaats.**
- `verdieping`: met de bestaande regel uit `index/properties.py`.
- `raster`: de dichtstbijzijnde as per richting uit `IfcGrid` in wereldcoördinaten, als `C-4`. Zonder raster, of bij een fout
  in het raster, leeg.
- `ruimte`: de kleinste `IfcSpace` waarvan de omhullende doos het botspunt bevat, met `LongName` of anders `Name`. Eén extra
  rondgang over alleen de ruimtes; bij fouten leeg.

Fouten in de context mogen een ronde nooit laten mislukken: het veld blijft dan leeg.

## 7. Platform-app (`frappe/openaec_bim/`)

### 7.1 Datamodel

**BIM Botsing** krijgt erbij: `soort`, `regel`, `emmer`, `emmer_reden`, `ernst`, `categorie`, `disciplines` (*Constructie ×
Installaties*, uit de submappen van de modellen), `verdieping`, `raster`, `ruimte`, `ontwikkeling`, `nummer` (Int), `reden`
(Small Text), `beoordeeld_door`, `beoordeeld_op`, `issue_status_voor`.

De keuzelijst `status` wordt `nieuw`, `actief`, `bevestigd`, `geaccepteerd`, `genegeerd`, `opgelost`. De waarde `genegeerd`
blijft, zodat bestaande rijen geldig zijn; de viewer noemt hem *Afgewezen* *(keuze)*. `verdieping` en `naam` staan ook in
`element_a` en `element_b`.

**BIM Botsingsronde** krijgt erbij: `regels` (JSON), `voorinstelling`, `reeks`, `voortgang` (Float), `samenvatting` (JSON). De
keuzelijst `soort` krijgt `dubbel` en `gemengd`.

**BIM Project** krijgt erbij: `botsingsregels` (JSON), `botsingsweergaven` (JSON).

Er is geen datamigratie nodig: rijen van vóór dit werk hebben lege velden en de viewer leest ze als `beoordelen`, zonder ernst.
Lege velden blijven dus geldig.

### 7.2 Rondes starten

- Nieuw: `start_controles(project, controles, titel=None, voorinstelling=None)`. Valideert dat elk bestand een model in de
  modelmap is en omgezet is, soort en tolerantie (0 tot 1 m), en hoogstens 30 controles.
- `start(project, set_a, set_b, soort, tolerantie, titel)` blijft als dunne laag die één controle maakt.
- `regels` is de genormaliseerde lijst controles (gesorteerd, klassen gesorteerd) als JSON met gesorteerde sleutels.
  `set_a` en `set_b` op de ronde worden de vereniging, alleen voor weergave. `soort` is de soort van alle controles, of
  `gemengd`.
- `reeks` is de `voorinstelling`, of zonder voorinstelling een hash van de sets en de soort, zonder de tolerantie.
- De vorige ronde is de laatste ronde van het project met status `klaar` en dezelfde `reeks`. Zo gaan beslissingen mee als er een
  model bijkomt, of een afstand of ernst verandert.
- Zijn de `regels` anders dan die van de vorige ronde, dan is de ronde *gewijzigd*: beslissingen gaan gewoon mee, maar paren die
  niet meer gevonden zijn, zijn wel `weg` zonder dat hun issue vanzelf sluit, want ze kunnen ook buiten de nieuwe regels vallen.
  De samenvatting krijgt `regels_gewijzigd` en de viewer noemt dat in één regel *(keuze)*.
- `titel` standaard: de naam van de voorinstelling met datum en tijd.
- `bijwerken` neemt `voortgang` over van de kerntaak.

### 7.3 Inlezen (`verwerk`)

Velden uit de kern worden tolerant gelezen: zonder `emmer` is het `beoordelen`, zonder `soort` die van de ronde, zonder `regel`
leeg, zonder `ernst` leeg.

**Status en ontwikkeling ten opzichte van de vorige ronde:**

| Vorige rij | Nu gevonden | Nieuwe status | `ontwikkeling` |
|---|---|---|---|
| geen | ja | `nieuw` | `nieuw` |
| `nieuw`, `actief` | ja | `actief` | `blijft` |
| `bevestigd`, `geaccepteerd`, `genegeerd` | ja | gelijk | `blijft` |
| `opgelost` | ja | `actief` | `terug` |
| niet `opgelost` | nee | `opgelost` | `weg` |
| `opgelost` | nee | `opgelost` | `eerder_weg` |

`reden`, `beoordeeld_door`, `beoordeeld_op`, `issue`, `issue_status_voor` en `nummer` gaan mee. Een nieuwe botsing krijgt
`nummer` = hoogste van de vorige ronde plus 1, oplopend op volgorde van `sleutel`.

Rijen die niet meer gevonden zijn (`weg`, `eerder_weg`) nemen alle velden over van de vorige rij, ook `emmer`, `ernst`,
`categorie`, `disciplines`, `verdieping`, `raster` en `ruimte`. Rijen met `eerder_weg` blijven meegaan, omdat een paar dat
terugkomt zijn beslissing en issue terug moet krijgen *(keuze)*.

**Gevonden** betekent hier: `ontwikkeling` is `nieuw`, `blijft` of `terug`.

**Samenvatting** op de ronde:
- `totaal`: het aantal gevonden rijen; gelijk aan `aantal`.
- `per_emmer`, `per_categorie`: alleen gevonden rijen, zodat de som van de emmers `totaal` is.
- `nieuw`, `blijft`, `terug`, `weg`: de aantallen per ontwikkeling.
- `open`: gevonden, in de emmer `beoordelen`, met status `nieuw`, `actief` of `bevestigd`. Een bevestigde botsing is nog niet
  opgelost, dus nog open. `per_ernst` telt deze rijen *(keuze)*.
- `per_status`: alle rijen.
- `regels_gewijzigd`: zie 7.2.

### 7.4 Issues volgen hun botsing

Bij `verwerk`, met `frappe.flags.bim_bron = "achtergrond"`. Bij een ronde met `regels_gewijzigd` sluit er niets vanzelf;
heropenen kan wel:

- **Weg:** staat het gekoppelde issue niet op een dichte status, dan bewaart de rij `issue_status_voor` en gaat het issue naar de
  dichte status, met een reactie. Dichte statussen: `Opgelost` en `Gesloten`. Dichte status die het krijgt: `Opgelost`, of anders
  de laatste uit de lijst van het project.
- **Terug:** heeft de vorige rij `issue_status_voor` en staat het issue nog op die dichte status, dan gaat het terug naar de
  bewaarde status, met een reactie, en wordt `issue_status_voor` leeg. Heeft iemand het issue intussen zelf gewijzigd, dan
  gebeurt er niets.
- Reacties staan op naam van *Botsingsronde*.

### 7.5 Beoordelen

- `zet_status(botsing, status, reden=None)`:
  - `reden` is hoogstens 200 tekens en alleen voor `genegeerd`; een andere status wist de reden.
  - `beoordeeld_door` en `beoordeeld_op` worden gezet.
  - `bevestigd` maakt het issue als dat er nog niet is en geeft de bijgewerkte botsing terug. Bevestigen is in de viewer de
    enige weg naar een issue; `botsing_naar_issue` blijft in de API bestaan *(keuze)*.
- `zet_status_veel(botsingen, status, reden=None)`: tot 500 tegelijk, voor de groepsactie; één rechtencontrole per ronde. Een
  bevestiging maakt per botsing één issue.
- `naar_issue` blijft en gebruikt de elementnamen in titel en omschrijving.

### 7.6 Regels en weergaven

- `instellingen(project)` geeft `{regels, weergaven, mag_wijzigen}`.
- `instellingen_bewaar(project, regels=None, weergaven=None)` vraagt schrijfrecht.
- Regel: `{a, b, soort: "uit"|"hard"|"afstand", mm, ernst}`. Discipline `a` en `b` zijn gesorteerd.
- De discipline van een model is de eerste submap van de modelmap. Staat een model direct in de modelmap, dan is de discipline
  de bestandsnaam zonder `.ifc`, zodat er altijd iets te kiezen is. Hetzelfde geldt voor `disciplines` op een botsing *(keuze)*.
- Weergave: `{naam, filter, groep}`; hoogstens 50, namen uniek.
- Alles gaat via het auditlog.

### 7.7 Verloop

`trends(ronde)`: de samenvattingen langs `vorige_ronde`, hoogstens de laatste 20, oudste eerst, met titel en datum.

### 7.8 API (`api_coordinatie.py`)

Dunne laag, altijd met `_gastpagina()`:

| Methode | Argumenten |
|---|---|
| `botsingsronde_start` | ook `controles`, `voorinstelling` |
| `botsing_status` | ook `reden` |
| `botsing_status_veel` | `botsingen`, `status`, `reden` |
| `botsing_instellingen` | `map` |
| `botsing_instellingen_bewaar` | `map`, `regels`, `weergaven` |
| `botsing_trends` | `ronde` |

## 8. Gastpagina (`openaec-bench`, `frontend/apps/werkplek/src/gast/bim-berichten.ts`)

- `bim.botsingsronde_start` krijgt `controles` en `voorinstelling`. Elk bestand in een controle moet uit het laatste
  `bim.project` komen, net als bij sets nu.
- `bim.botsing_status` krijgt `reden`; `STATUSSEN` wordt uitgebreid.
- Nieuw: `bim.botsing_status_veel`, `bim.botsing_instellingen`, `bim.botsing_instellingen_bewaar`, `bim.botsing_trends`.
- De lijst berichten in `docs/werkplek.md` wordt bijgewerkt.

## 9. Viewer (`viewer/`)

### 9.1 Logica (`src/model/clashes.ts`, puur en getest)

- `voorinstellingen(modellen)`: de snelle keuzes als controles, elk met `beschikbaar` en zo nodig een reden. Of klassen aanwezig
  zijn, volgt uit `aantallen_per_klasse` met een korte lijst bekende installatieklassen in de viewer, omdat die telling alleen
  concrete klassen kent *(keuze)*.
- `controlesUitRegels(regels, modellen)`: de regels naar controles. Regels `uit` en paren zonder modellen vallen af.
- `standaardRegels(disciplines)`: paren die nog niet bewaard zijn, tussen verschillende disciplines `hard`, binnen één
  discipline `uit`.
- `overlapWaarschuwing(setA, setB)`: waar als de omhullende dozen (`index.begrenzing`) elkaar ook met 1 m marge niet raken.
  Ontbrekende dozen geven geen waarschuwing.
- `filter(botsingen, filter)`, `facetten(botsingen, filter)`: aantallen per waarde binnen de overige filters.
- `groepeer(botsingen, op)`, grootste groep eerst; lege waarden onder *Onbekend*.
- `volgende(lijst, huidige)`: binnen de getoonde lijst, dus binnen emmer en filters, de eerstvolgende botsing met status `nieuw`
  of `actief`, en na het einde weer vanaf het begin. Is die er niet, dan de volgende in de lijst; is er geen volgende, dan
  blijft de selectie staan.

### 9.2 Snelle keuzes

| Keuze | Controle |
|---|---|
| Harde botsingen | alle modellen tegen alle, `hard`, 0 mm |
| Constructie tegen installaties | `IfcBeam`, `IfcColumn`, `IfcFooting`, `IfcPile`, `IfcMember`, `IfcSlab` en alle `IfcWall` tegen `IfcDistributionElement`, `hard`, 0 mm |
| Wanden en vloeren tegen installaties | `IfcWall`, `IfcSlab` tegen `IfcDistributionElement`, `hard`, 0 mm |
| Tussen modellen | alle tegen alle, `alleen_tussen_modellen`, `hard`, 0 mm |
| Bijna-botsingen | alle tegen alle, `alleen_tussen_modellen`, `afstand`, instelbaar, standaard 50 mm |
| Dubbele elementen | alle tegen alle, `dubbel` |
| Volgens de projectregels | `controlesUitRegels`; niet beschikbaar zonder regels |
| Zelf instellen | het bestaande formulier met sets, soort en tolerantie |

Alle wanden doen hier mee; of een wand dragend is, telt alleen voor de categorie en de ernst (6.4) *(keuze)*. Een keuze is niet
beschikbaar, met de reden erbij, als de modellen volgens `aantallen_per_klasse` de benodigde klassen niet
hebben, of als er voor *Tussen modellen* maar één model is. Boven de knop staat de overlapwaarschuwing; starten blijft
mogelijk.

### 9.3 Regels

Een scherm in het tabblad *Botsingen*: per paar disciplines een rij met soort, afstand in mm en ernst, bewaard op de server.
Voor wie niet mag schrijven alleen te lezen.

### 9.4 Een ronde

Boven de lijst:
- de **emmerbalk** met de aantallen gevonden rijen, standaard op *Te beoordelen*; de andere twee zijn een klik weg;
- een regel met open, nieuw en weg. Een klik op *weg* toont de rijen die niet meer gevonden zijn. Die staan niet in de emmers;
  `eerder_weg` is alleen te zien via het filter op ontwikkeling *(keuze)*;
- een inklapbaar **verloop**: een klein staafdiagram van de laatste rondes, met een tabel als toegankelijk alternatief;
- **filters** (ernst, status, categorie, disciplines, verdieping, ontwikkeling, tekst) met aantallen, en actieve filters als
  verwijderbare chips;
- **weergaven**: kiezen en, met schrijfrecht, bewaren;
- **groeperen op**: een keuzelijst.

De voortgang van een lopende ronde staat als percentage.

Een rij toont `#nummer`, de twee elementnamen met klasse als er geen naam is, ernst, verdieping en ontwikkeling. Een rij met de
focus klapt open:
- afstand, disciplines, raster, ruimte, de GlobalIds en een eventuele reden;
- knoppen *Bevestigen* (maakt het issue), *Accepteren* en *Afwijzen* (vraagt een reden, die mag leeg zijn), of *Heropenen* bij een
  afgehandelde botsing; een bestaand issue staat als badge bij de rij;
- *Naar A*, *Naar B* en *Alles tonen*.

Grote lijsten: per groep de eerste 100 rijen met een knop voor meer *(keuze)*. Groepen zijn inklapbaar. Een groepskop heeft een
actie om de hele groep in één keer af te wijzen of te accepteren, met bevestiging.

### 9.5 Sneltoetsen

Alleen als het tabblad open is, de focus niet in een veld staat en er geen Ctrl of Alt is:

| Toets | Actie |
|---|---|
| `J`, pijl omlaag | volgende |
| `K`, pijl omhoog | vorige |
| `B` | bevestigen |
| `A` | accepteren |
| `X` | afwijzen (reden invullen, Enter bevestigt) |
| `Esc` | alles tonen, de rij sluiten |
| `?` | de sneltoetsen tonen |

Na een beslissing springt de selectie met `volgende` door. De rij blijft staan tot je wegspringt, zodat een fout zichtbaar blijft.

### 9.6 In 3D (`Weergave`, `FragmentsEngine`)

`Weergave` krijgt `isoleer(paar, punt)`, `naarElement(element)` en `herstel()`.

- `isoleer`: alle andere elementen doorzichtig (`setOpacity`), het paar in twee kleuren, de camera op het botspunt met een
  straal naar de grootte van de elementen. Twee klassen voor A en B *(keuze: A de accentkleur van het stijlboek, B de
  informatiekleur)*.
- `herstel` zet alles terug. De keuze *Alles tonen* en het verlaten van de ronde of het tabblad roepen `herstel` aan.
- Doorzichtig maken moet ook op een federatie van 288 MB vlot blijven. Is het te traag, dan alleen het paar markeren met de
  camera erop, en dat noteren in de meting.

### 9.7 Breedte

De kolom rechts wordt 360 px op de tabbladen *Issues* en *Botsingen*, en blijft 280 px op *Eigenschappen* *(keuze)*. De canvas
past zich aan.

## 10. Tests en acceptatie

- **Kern:** een nieuw proefmodel in `tests/models.py` met deur in wand, samenstel, verbonden elementen, systeem, balk in kolom,
  dubbel element, raster en ruimte. Per regel uit 6.4 een test; de som van de emmers is het totaal; `dubbel`; volgorde en
  dubbele paren; `alleen_tussen_modellen`; context-fouten laten de ronde niet mislukken.
- **App:** `tests/test_botsingen.py`: elke rij uit de tabel in 7.3, samenvatting, nummers, issue sluiten en heropenen, geen
  heropening na eigen wijziging, regels en weergaven met rechten, `zet_status_veel`, tolerant lezen.
- **Gastpagina:** `test/bim.test.ts` voor de nieuwe berichten en het weigeren van onbekende bestanden.
- **Viewer:** Vitest voor alles in 9.1 en de berichten in `WerkplekHost.test.ts`.
- **Werkplekproef:** `scripts/werkplek-e2e/bim-coordinatie.mjs` blijft slagen, met daarbij: starten met een voorinstelling,
  emmerbalk, groeperen, sneltoetsen, afwijzen met reden die in de tweede ronde terugkomt, het issue dat sluit als de botsing weg
  is, en het paar dat geïsoleerd in beeld staat.
- **Meting:** `docs/metingen/2026-botsingen-beoordelen.md`: de proef, en een ronde op de demomodellen van 49 en 73 MB met tijd en
  aantallen per emmer, om te zien of de indeling klopt op echte modellen.
- **Laten zien:** het eindresultaat staat open in het browserpaneel, met de demoruimte.

## 11. Wat aan de bouwer is

Bestandsindeling in de viewer (ook splitsen van `ClashPanel.tsx`), exacte teksten, CSS binnen de tokens, en de volgorde van de
taken. De drempels (5, 20 en 50 mm, 10 mm voor `dubbel`) mogen na de meting op echte modellen worden bijgesteld; noteer dat dan
in de meting.

## 12. Later

Golf 2 (viewer), golf 3 (kwaliteit, versies vergelijken, rapporten, ontbrekende sparingen), golf 4. Zie de roadmap in het
hoofdontwerp en de issues.
