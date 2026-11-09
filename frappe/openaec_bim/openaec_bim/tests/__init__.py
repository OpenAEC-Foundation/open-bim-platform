"""De tests van openaec_bim wissen alle ruimtes, bestanden en BIM-gegevens op de site waarop ze draaien.

Daarom draaien ze alleen op een eigen testsite: een naam die begint met `test.`, zoals `test.localhost`. Een commit in de
geteste code maakt het wissen blijvend, dus op een site met echte of demogegevens is dat verlies van gegevens.
"""

import frappe


def vereis_testsite(site: str | None) -> None:
	"""Weigert elke andere site dan een testsite; zonder site (geen verbinding) is er niets te wissen."""
	if site and not site.startswith("test."):
		raise RuntimeError(
			f"De tests van openaec_bim wissen alle ruimtes en draaien niet op {site}. "
			"Gebruik een eigen testsite: bench --site test.localhost run-tests --module <module>."
		)


vereis_testsite(getattr(frappe.local, "site", None))
