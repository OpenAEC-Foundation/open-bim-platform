# Conformiteit BCF-API 3.0

De klantsite biedt de BCF-API 3.0 en de Foundation API 1.1 van buildingSMART aan, zodat controle- en
ontwerpprogramma's live issues lezen en schrijven in hetzelfde datamodel als de werkplek (ontwerp 5.6).

| Pad | Wat |
|---|---|
| `/foundation/versions` | de versies, met `api_base_url` (zonder aanmelden) |
| `/foundation/1.1/auth` (ook `1.0`) | de OAuth2-adressen van Frappe, flow `authorization_code_grant` (zonder aanmelden) |
| `/foundation/1.1/current-user` | de aangemelde gebruiker |
| `/bcf/3.0/projects[/{id}[/extensions]]` | de modelmappen met een BIM-project waarop je leesrecht hebt; de projectnaam wijzigen vraagt schrijfrecht |
| `/bcf/3.0/projects/{id}/topics[/{guid}]` | topics: GET, POST, PUT (409 bij een verouderde `modified_date`), DELETE |
| `.../topics/{guid}/comments[/{guid}]` | reacties: GET, POST, PUT, DELETE |
| `.../topics/{guid}/viewpoints[/{guid}]` | standpunten: GET, POST, DELETE (409 zolang er een reactie bij hoort), met `snapshot`, `selection`, `coloring` en `visibility` |
| `.../topics/{guid}/related_topics` | verwante topics: GET, PUT |
| `.../topics/{guid}/document_references[/{guid}]` | documentverwijzingen: GET, POST, PUT |

Aanmelden gaat met een OAuth2-token van Frappe (een OAuth Client op de site, flow authorization code) of met een
API-sleutel (`Authorization: token <key>:<secret>`). Rechten komen uit Storage: wie de modelmap niet (meer) mag lezen,
krijgt 403, ook met een geldig token. Elke wijziging komt in het auditlog met de bron `bcf-api`.

Nog niet in deze versie: snippets, bestanden (`files`, `files_information`), documenten, events, de bitmaps van een
standpunt als eigen pad en de filters (`$filter`, `$orderby`) op de topiclijst.

## De test draaien

`frappe/openaec_bim/scripts/bcf_conformiteit.py` doet de aanroepen uit de specificatie tegen een draaiende site met
een eigen topic, dat aan het eind weer verwijderd wordt, en controleert dat de topics zonder verlies heen en terug gaan
als `.bcfzip` in BCF 2.1 en 3.0. Nodig: Python 3.12 met `requests`, een gebruiker met schrijfrecht op een modelmap
met een BIM-project, en zijn API-sleutel of OAuth2-token.

```bash
python frappe/openaec_bim/scripts/bcf_conformiteit.py --site https://<klantsite> \
    --sleutel "token <api_key>:<api_secret>" --project <id van de modelmap> --uit rapport.md
```

Achter een ander adres (bijvoorbeeld in de container van de ontwikkelbench) zet `--host <sitenaam>` de Host-kop. De
afsluitcode is 1 als een stap faalt.

## Laatste uitslag

29 oktober 2026, ontwikkelbench (klant0), branch `fase-1b-coordinatie`: **15 van 15 stappen geslaagd**.

| Stap | Uitslag |
|---|---|
| GET /foundation/versions | geslaagd |
| GET /foundation/1.1/auth | geslaagd |
| GET /foundation/1.1/current-user | geslaagd |
| Zonder aanmelden: 401 | geslaagd |
| GET /projects en /projects/{id} | geslaagd |
| GET /projects/{id}/extensions | geslaagd |
| POST /topics | geslaagd |
| GET /topics en /topics/{guid}, 404 voor een onbekend topic | geslaagd |
| PUT /topics/{guid}, 409 bij een verouderde modified_date | geslaagd |
| Comments: POST, GET, PUT | geslaagd |
| Viewpoints: POST, GET, snapshot, selection, coloring, visibility | geslaagd |
| PUT en GET /related_topics | geslaagd |
| Document references: POST, PUT, GET | geslaagd |
| BCF 2.1 en 3.0 heen en terug zonder verlies | geslaagd |
| DELETE: viewpoint met reactie 409, comment, viewpoint, topics | geslaagd |
