# openaec_bim

De platform-app van het Open BIM Platform op de klantsite (Frappe). Ze maakt van een modelmap in OpenAEC Storage een
project voor de viewer in de werkplek (`/werkplek/bim?map=<id>`): ze laat de BIM-kern elke IFC-versie omzetten (met
ondertekende S3-adressen: lezen voor de bron, schrijven voor de afgeleide gegevens), volgt die taken, en geeft de
gastpagina de delen en de eigenschappen, steeds met de rechten van Storage.

Nodig: `openaec_storage`, en in de `site_config.json` van de klantsite:

| Sleutel | Betekenis |
|---|---|
| `openaec_bim_kern_url` | adres van de BIM-kern, bijvoorbeeld `http://bim-kern:8730` |
| `openaec_bim_kern_sleutel` | de interne sleutel van deze klantsite bij de kern |

API voor de gastpagina (`openaec_bim.api.*`, POST met de sessie): `project(map)`, `lees_adres(bestand, versie, deel)`,
`eigenschappen(bestand, versie, globalids)`, `opnieuw(bestand, versie)`; `lees(token)` (GET, zonder sessie) stroomt de
bytes van een deel. Ontwerp: `docs/superpowers/specs/2026-10-26-open-bim-platform-design.md` (5.4, 5.6, 7.1).
