# Botsingen beoordelen: restpunten

Kleine punten die na de reviews bewust zijn blijven liggen. Geen ervan blokkeert het gebruik. Regelnummers staan er niet bij, omdat ze
verschuiven; zoek op de genoemde functie of het bestand. De tekortkomingen die een gebruiker merkt, staan in
[de meting](../../metingen/2026-botsingen-beoordelen.md).

## Bewust niet gedaan

- Klikken in 3D tijdens het isoleren wist de kleur, terwijl de rij open blijft.
- `zet_status` heeft geen versiecontrole: een beoordelaar met een oude lijst kan de reden van een ander overschrijven.
- `verwerk` en `zet_status_veel` doen per rij een query; `vervang` en `facetten` zoeken per rij in de lijst. Bij deze aantallen is dat niet merkbaar.
- `naar_issue` vraagt alleen leesrecht, en een lezer die de rondes opent kan `verwerk` starten. Bestaand ontwerp.
- `alleen_tussen_modellen` rekent alles tegen alles en filtert daarna. Dat kan sneller.
- De lijst heeft geen virtualisatie; de grens is 100 rijen per groep.
- Een afgewezen of geaccepteerde botsing laat een open issue met rust. Het ontwerp zegt er niets over.
- `rijFout` heeft één plek, dus een late fout van een andere rij kan een melding wegdrukken.
- De knop *Te beoordelen* blijft ingedrukt als een filter op ontwikkeling ook andere rijen toont; de chip legt het uit.
- De melding dat een element niet in beeld is, ververst niet als het model later klaar komt.
- Een poll en de planner kunnen dezelfde ronde tegelijk verwerken; de tijdstempel vangt dat op.
- Omzettingen en koppelingen hebben geen tijdgrens, en een blijvende `ClientError` zoals `AccessDenied` logt bij elke tik.
- De tests van `openaec_storage` wissen ook alle ruimtes, en hebben de beveiliging voor de testsite nog niet.

## Per taak

### Taak 1

- clash.py importeert privaat _storey uit index.properties
- _no_progress dubbel in botsingen.py en clash.py
- afstand betekent bij dubbel de kleinste doosmaat, bij hard de diepte
- boxes en owners op alleen GlobalId; twee bestanden met dezelfde GlobalIds overschrijven elkaar
- testgaten: dubbel met andere klasse, terugval verdieping samenstel, virtual zou anders botsen

### Taak 2

- test `assert hit.raster` controleert alleen dat er iets staat, niet de assen
- test emmers tellen op is bijna tautologisch; controleer dat elke emmer geldig is
- _arc_points neemt graden aan en negeert SenseAgreement
- fouten in context verdwijnen zonder logregel

### Taak 3

- `tolerantie` op een gemengde ronde is de maximale, en dat toont ronde_naar_json als de tolerantie
- `_('Botsingen')` in een f-string is niet door elk vertaalgereedschap te vinden

### Taak 4

- geen test van het opnieuw verwerken na een botsing in de database
- meldingen bij een issue-opslag zijn niet nagekeken op dubbel versturen bij een teruggedraaide poging
- _dichte_status wordt per rij opnieuw berekend
- disciplines sorteren hoofdlettergevoelig
- enkele tests gebruiken kale assert naast self.assert

### Taak 5

- zet_status_veel met dubbele namen laadt hetzelfde document twee keer; ontdubbelen
- flt() maakt van mm "abc" 0, de except-tak is dood; echt getal eisen
- geen grens op aantal regels en lengte van teksten in regels en weergaven
- geen API-tests voor de nieuwe methoden (_gastpagina, JSON-tekst als argument)
- enkele tests gebruiken kale assert

### Taak 6

- controles null valt terug op de oude vorm in plaats van een fout
- geen grens op lengte van regel of klassen en negatieve tolerantie aan de gastkant; de server beslist

### Taak 7

- codepunt vergelijkt UTF-16-eenheden, niet echte codepunten; verschil alleen boven U+FFFF

### Taak 8

- klassenaam viewer__body--breed is Nederlands in viewer-code
- highlightMaterial is nog maar een wrapper van een regel

### Taak 9

- een regel op uit zetten bewaart mm 0 en gooit de bewaarde afstand weg
- bewaren schrijft de standaardrijen voor elk disciplinepaar mee
- het mm-veld in de kaart bijna-botsingen heeft geen eigen label voor schermlezers
- ClashPanel herlaadt de rondelijst ook bij annuleren
- voortgangProcent(Infinity) geeft 0

### Taak 10

- geen controle in de viewer op 50 weergaven; de server weigert en de melding staat in beeld
- een lege groepswaarde en null delen de sleutel "" in sleutelVan
- ClashRound.tsx is 406 regels; de groepskop kan een eigen onderdeel worden

### Taak 11

- 8.5rem in app.css is geen token; docstring van variant.py zegt meters terwijl de verschuiving de eenheid van het model volgt
