"""Client van de BIM-kern (het rekenkern-contract: /v1/tools, /v1/taken), met de interne sleutel van deze klantsite.

Tot de tools-gateway er is, roept de klantsite de kern rechtstreeks aan op het interne netwerk (ontwerp 5.5).
"""

import re

import frappe
import requests
from frappe import _

TIMEOUT = (10, 120)  # verbinden, lezen (seconden)


class KernFout(frappe.ValidationError):
	"""Een fout van de kern, met zijn error_code (bijvoorbeeld omzetten_mislukt, index_ongeldig)."""

	http_status_code = 502

	def __init__(self, code: str, melding: str):
		super().__init__(melding)
		self.code = code


def _instelling() -> tuple[str, str]:
	url = (frappe.conf.get("openaec_bim_kern_url") or "").rstrip("/")
	sleutel = frappe.conf.get("openaec_bim_kern_sleutel") or ""
	if not url or not sleutel:
		raise KernFout("kern_niet_ingesteld", _("De BIM-kern is op deze omgeving niet ingesteld."))
	return url, sleutel


def _klantsite() -> str:
	"""De naam van deze klantsite zoals de kern hem verwacht (kop X-OpenAEC-Klantsite: eerlijk verdelen per site)."""
	naam = re.sub(r"[^A-Za-z0-9._-]", "-", frappe.local.site or "lokaal").lstrip(".-_")
	return (naam or "lokaal")[:100]


def roep(methode: str, pad: str, json: dict | None = None) -> dict:
	url, sleutel = _instelling()
	try:
		antwoord = requests.request(
			methode,
			url + pad,
			json=json,
			headers={"Authorization": f"Bearer {sleutel}", "X-OpenAEC-Klantsite": _klantsite()},
			timeout=TIMEOUT,
		)
	except requests.RequestException as fout:
		frappe.logger("openaec_bim").warning("kern onbereikbaar: %s", type(fout).__name__)
		raise KernFout("kern_onbereikbaar", _("De BIM-kern is tijdelijk niet bereikbaar.")) from fout
	try:
		inhoud = antwoord.json()
	except ValueError:
		inhoud = None
	if not antwoord.ok:
		if isinstance(inhoud, dict) and isinstance(inhoud.get("error_code"), str):
			raise KernFout(inhoud["error_code"], inhoud.get("melding") or inhoud["error_code"])
		raise KernFout("kern_fout", _("De BIM-kern gaf een onverwacht antwoord (HTTP {0}).").format(antwoord.status_code))
	if not isinstance(inhoud, dict):
		raise KernFout("kern_fout", _("De BIM-kern gaf een onverwacht antwoord."))
	return inhoud


def start_omzetten(bron: dict, doelen: dict[str, str]) -> str:
	"""Zet een omzetting klaar bij de kern; geeft het taaknummer."""
	return roep("POST", "/v1/tools/omzetten", {"bron": bron, "doelen": doelen})["taak"]


def start_koppelen(vorige: dict, nieuwe: dict) -> str:
	"""Zet een versiekoppeling klaar bij de kern (twee eigenschappen-indexen); geeft het taaknummer."""
	return roep("POST", "/v1/tools/koppelen", {"vorige": vorige, "nieuwe": nieuwe})["taak"]


def taak(taak_id: str) -> dict:
	return roep("GET", f"/v1/taken/{taak_id}")


def eigenschappen(index: dict, globalids: list[str]) -> dict:
	return roep("POST", "/v1/tools/eigenschappen", {"index": index, "globalids": globalids})["elementen"]
