# Fase 1a: de viewer in de werkplek — implementatieplan

**Doel:** de viewer en de BIM-kern van fase 0 in de SuperCloud: een gebruiker opent een modelmap uit OpenAEC Storage in
de werkplek, de modellen worden op de achtergrond omgezet, en de viewer laadt ze binnen het geheugenbudget, met
eigenschappen van de server. Getest op een lokale bench met grote IFC-modellen, via de GUI.

**Ontwerp:** hoofdstukken 5.3–5.7 en 7.1 van `docs/superpowers/specs/2026-10-26-open-bim-platform-design.md`. Dit plan
is de eerste plak van fase 1 (hoofdstuk 8, punten 1–4, zonder doorsneden en meten); issues, BCF, botsingen en
momentopnames volgen in eigen plannen.

## Onderdelen

1. **Viewer (`viewer/`):** `WerkplekHost` implementeert `BimHost` met de berichten `bim.project`, `bim.laad` en
   `bim.eigenschappen` (protocol van de werkplek: `{werkplek: 1, id, soort, …}`, antwoord `{werkplek: 1, antwoord,
   ok, waarde | fout, code}`, bytes als overgedragen `ArrayBuffer`). `main.tsx` kiest de host: met `#ouder=` in de hash
   de werkplek, anders de lokale server. De bundel krijgt een relatieve base (`./`).
2. **Platform-app `openaec_bim` (`frappe/openaec_bim/`):** DocType `BIM Afgeleid` (bestand, versie, omzetter, status,
   kern_taak, delen, index, fout); API voor de gastpagina (`project`, `omzetten`, `lees_adres`, `eigenschappen`), elke
   methode met de rechten van Storage; een geplande taak die de taken bij de kern volgt. De kern krijgt ondertekende
   S3-adressen: lezen voor de bron, schrijven voor `<prefix>/bim/afgeleid/<bestand>/<versie>/<omzetter>/`. De
   afgeleide bytes gaan naar de gastpagina via een kortlevend leesadres op de klantsite (HMAC, zoals de werkplek).
3. **Werkplek (`openaec-bench`, eigen branch):** app `bim` in `APPS` (zonder extensies: `.ifc` hoort bij de planner;
   openen gaat op modelmap, `/werkplek/bim?map=<id>`), gastpagina, adapter `src/gast/bim.ts` met de `bim.*`-berichten,
   bouwstap in `build-werkplek.sh`, catalogusregel `open-bim-platform` (gratis, Beta) en `openaec_bim` in de appset van
   de klantsites.
4. **Lokale omgeving:** MinIO als S3 (op schijf, geschikt voor GB's), de BIM-kern en de werker als containers; een
   eigen Compose-project naast de bestaande bench.

## Besluiten voor de eigenaar (niet in dit plan genomen)

- Welke app opent een `.ifc` standaard: de planner of de viewer.
- Prijsniveau en status van `open-bim-platform` in de catalogus; de projectlicentie van deze repo.
- Uitrol naar staging: een machine met genoeg geheugen voor omzetten (zie de meting van fase 0), de sleutel van de kern
  in SSM, en een push naar `openaec-bench` (die rolt vanzelf uit).
