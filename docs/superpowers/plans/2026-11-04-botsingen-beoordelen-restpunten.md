# Botsingen beoordelen: restpunten

Kleine punten die na de reviews bewust zijn blijven liggen. Geen ervan blokkeert het gebruik. Regelnummers staan er niet bij, omdat ze
verschuiven; zoek op de genoemde functie of het bestand. De tekortkomingen die een gebruiker merkt, staan in
[de meting](../../metingen/2026-botsingen-beoordelen.md).

De punten per taak zijn afgewerkt (zie onder). Wat bewust niet gedaan is, staat er nog; dat zijn keuzes in het ontwerp of zaken die
bij deze aantallen niet merkbaar zijn.

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
- De tests van `openaec_storage` wissen ook alle ruimtes, en hebben de beveiliging voor de testsite nog niet (andere repo).

## Afgewerkt

### Kern (taak 1 en 2)

- **Twee bestanden met dezelfde GlobalIds overschreven elkaars dozen en eigenaars.** De scène kent een element nu als bestand plus
  GlobalId; het bestand van een antwoord van de geometrieboom volgt uit het bestand dat het element opende. Een paar telt in een
  ronde als sleutel, versie en GlobalId van beide kanten. Dezelfde GlobalId aan beide kanten blijft hetzelfde element.
- `storey_of` is openbaar in `index.properties`; `clash_context` gebruikt geen privénaam meer. De terugval naar de verdieping van een
  samenstel in `ModelContext.verdieping` is weg: `get_container` van IfcOpenShell volgt het samenstel al, en zo geeft een botsing
  dezelfde verdieping als de eigenschappenindex.
- `no_progress` staat één keer, in `openbim_kern.progress`, voor de kern en de tools.
- Bij `Botsing` staat wat `afstand` per soort betekent: de diepte bij `hard`, de tussenruimte bij `afstand`, de kleinste maat van de
  gedeelde doos bij `dubbel`.
- Nieuwe tests: een doos van een andere klasse is geen dubbel; een deel van een samenstel krijgt de verdieping van het samenstel;
  het virtuele element steekt echt door een wand (anders bewijst die test niets). Elke test is met een mutatie in de code
  gecontroleerd: hij faalt als het gedrag verdwijnt.
- De rastertest vraagt nu de as (`B-1`), en de emmertest controleert per botsing dat emmer, reden en ernst bij elkaar horen in
  plaats van een som die altijd klopt.
- Een gebogen rasteras volgt de hoekeenheid van het model (graden als het model er geen noemt) en de `SenseAgreement`: tegen de zin
  van de cirkel loopt de boog met de klok mee.
- Een mislukte vraag naar de context logt één waarschuwing per vraag per ronde, en een rasterlezer of ruimtelezer die faalt ook één.

### App (taak 3, 4 en 5)

- Een ronde met controles van verschillende toleranties geeft `tolerantie: null`; de viewer toont dan *tolerantie per regel*.
- Een groepsactie met een naam die twee keer voorkomt, faalde met een verouderde tijdstempel: de tweede kopie van hetzelfde
  document. Elke naam telt nu één keer.
- `botsing_status_veel` weigerde een lijst als JSON-tekst (een formulierverzoek) al bij de typecontrole van Frappe; de typehint laat
  tekst nu toe en `_lijst` leest hem.
- De afstand van een regel moet een getal zijn; tekst, een bool en `NaN` worden geweigerd in plaats van stil 0 mm.
- Grenzen: hoogstens 500 regels, een discipline en de naam van een weergave hoogstens 140 tekens, per filter hoogstens 100 waarden
  van 140 tekens, de zoektekst hoogstens 200, de groepering een bekende, en per model in een set hoogstens 100 klassen van 64 tekens.
- Disciplines sorteren zonder op hoofdletters te letten, en bij gelijke letters op codepunt; de viewer doet hetzelfde.
- `_dichte_status` wordt één keer per ronde bepaald.
- Een test laat een botsing in de database (een verouderde tijdstempel bij het opslaan van de ronde) het inlezen terugdraaien: geen
  rijen, het issue zoals het was, geen reactie en geen fout. De volgende tik leest de ronde één keer in, met één reactie.
- API-tests voor de groepsactie, de regels en weergaven en het verloop met JSON-tekst als argument, en de bron `gastpagina` in het
  auditlog.
- De kale asserts in `test_botsingen.py` zijn assertions van unittest.

### Gastpagina (taak 6, in `openaec-bench-bim`)

- Een bericht met `controles: null` is een fout (`controle_ongeldig`); alleen een bericht zonder het veld is de oude vorm.

### Viewer (taak 7 tot en met 11)

- Disciplines sorteren zoals de server: op alfabet zonder hoofdletters, dan op echte codepunten (ook boven U+FFFF). Een vergelijking
  met Python op lastige namen (ß, İ, Grieks, tekens buiten het basisvlak) geeft dezelfde volgorde.
- Het regelscherm bewaart alleen regels die van de standaard afwijken, en een regel die uit staat houdt zijn afstand. *Volgens de
  projectregels* rekent met de bewaarde regels en voor de andere paren met de standaard; zonder bewaarde regel blijft de keuze uit.
- Het afstandsveld in de kaart *bijna-botsingen* heeft een eigen naam voor schermlezers.
- Annuleren bij een nieuwe ronde laadt de lijst van rondes niet opnieuw.
- `voortgangProcent(Infinity)` geeft 100.
- Bij 50 weergaven biedt de viewer geen nieuwe meer aan en zegt waarom; bewaren onder een bestaande naam kan.
- De groepskop is een eigen onderdeel (`ClashGroupHeader`).
- `viewer__body--breed` heet `viewer__body--wide`; `highlightMaterial` is weg.
- De losse maten in `app.css` (8,5 rem, 8 rem, 7 rem, 4 rem en de kolom van 360 px) zijn uit tokens samengesteld.
- De docstring en de hulptekst van `variant.py` zeggen dat de verschuiving de eenheid van het model volgt.

## Nagekeken, geen wijziging

- `_('Botsingen')` in een f-string: het vertaalgereedschap van Frappe vindt de tekst gewoon.
- Meldingen bij een issue-opslag na een teruggedraaide poging: de reacties zijn databaserijen en gaan mee terug (de test hierboven).
  Mail of eigen meldingen zijn er niet. Wat overblijft, zijn de realtime-berichten van Frappe na een opslag: die ontdubbelt Frappe, en
  een teruggedraaide poging levert hoogstens een overbodige herlaadhint in Desk op.
- Een lege groepswaarde en `null` delen de sleutel in `sleutelVan`: dat is één groep, want `groepWaarde` maakt van een lege waarde al
  `null` (test *groeperen: grootste eerst, lege waarden samen*).
- Geen grens op regel, klassen en tolerantie in de gastpagina: de server beslist, en heeft die grenzen nu ook voor de klassen.
