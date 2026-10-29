"""API voor de gastpagina van de werkplek (`/werkplek/bim?map=<id>`), met de sessie van de gebruiker.

Elke methode controleert de rechten via Storage (leesrecht op de map of het bestand). Een modelmap is voor deze
eerste versie het project: alle IFC-bestanden in de map en haar submappen, de naam van de submap als discipline.
"""

import json
import os
from urllib.parse import quote

import frappe
import requests
from frappe import _
from frappe.utils import cint
from werkzeug.wrappers import Response

from openaec_bim import afgeleid, kern, koppeling, leestoken

MAX_GLOBALIDS = 1000
LEESBLOK = 256 * 1024
TIMEOUT = (10, 300)


class NogNietKlaar(frappe.ValidationError):
	http_status_code = 409


class DeelOnbekend(frappe.DoesNotExistError):
	pass


def _vereis_plek(ruimte: str, map_: str | None, bestand: str | None = None) -> None:
	from openaec_storage.rechten import vereis_op_plek

	vereis_op_plek(ruimte, map_, "read", bestand)


def _modelmap(map_: str):
	doc = frappe.db.get_value("Opslagmap", map_, ["name", "ruimte", "naam", "verwijderd_op"], as_dict=True)
	if not doc or doc.verwijderd_op:
		frappe.throw(_("Map bestaat niet"), frappe.DoesNotExistError)
	_vereis_plek(doc.ruimte, doc.name)
	return doc


def _bestand(bestand: str):
	doc = frappe.db.get_value(
		"Opslagbestand", bestand, ["name", "ruimte", "map", "naam", "huidige_versie", "verwijderd_op"], as_dict=True
	)
	if not doc or doc.verwijderd_op:
		frappe.throw(_("Bestand bestaat niet"), frappe.DoesNotExistError)
	_vereis_plek(doc.ruimte, doc.map, doc.name)
	return doc


def ifc_in_map(map_doc) -> list[tuple[dict, str]]:
	"""(bestand, discipline) voor elk IFC-bestand in de map en haar submappen; discipline = submap op het eerste niveau."""
	gevonden = []
	te_doen = [(map_doc.name, "")]
	while te_doen:
		huidige, discipline = te_doen.pop(0)
		bestanden = frappe.get_all(
			"Opslagbestand",
			filters={"map": huidige, "verwijderd_op": ("is", "not set")},
			fields=["name", "naam", "huidige_versie", "grootte"],
			order_by="naam asc",
			ignore_permissions=True,
		)
		gevonden += [(b, discipline) for b in bestanden if (b.naam or "").lower().endswith(".ifc")]
		for sub in frappe.get_all(
			"Opslagmap",
			filters={"bovenliggende": huidige, "verwijderd_op": ("is", "not set")},
			fields=["name", "naam"],
			order_by="naam asc",
			ignore_permissions=True,
		):
			te_doen.append((sub.name, discipline or sub.naam))
	return gevonden


def _json(waarde):
	return json.loads(waarde) if isinstance(waarde, str) else waarde


def _model(bestand: dict, discipline: str, doc) -> dict:
	klaar = bool(doc and doc.status == "klaar")
	return {
		"bron": {"soort": "bestand", "sleutel": bestand.name, "versie": str(cint(bestand.huidige_versie))},
		"naam": os.path.splitext(bestand.naam)[0],
		"discipline": discipline,
		"status": doc.status if doc else "wacht",
		"voortgang": doc.voortgang if doc else 0,
		"fout": _json(doc.fout) if doc and doc.status == "fout" else None,
		"delen": [{"naam": d["naam"], "bytes": cint(d["bytes"])} for d in (_json(doc.delen) or [])] if klaar else [],
		"index": _json(doc.samenvatting) if klaar else None,
		"koppeling": koppeling.naar(bestand.name, cint(bestand.huidige_versie)) if klaar else None,
	}


@frappe.whitelist(methods=["POST"])
def project(map: str) -> dict:
	"""De modellen van een modelmap met hun stand. Een versie zonder omzetting wordt nu klaargezet bij de kern."""
	map_doc = _modelmap(map)
	modellen = []
	for bestand, discipline in ifc_in_map(map_doc):
		versie = cint(bestand.huidige_versie)
		doc = afgeleid.laatste(bestand.name, versie)
		if doc is None:
			doc = afgeleid.start(bestand.name, versie)
		elif doc.status in ("wacht", "bezig"):
			afgeleid.bijwerken(doc)
		for lopend in frappe.get_all(
			koppeling.DOCTYPE, {"bestand": bestand.name, "naar_versie": versie, "status": ("in", ("wacht", "bezig"))}, pluck="name"
		):
			koppeling.bijwerken(frappe.get_doc(koppeling.DOCTYPE, lopend))
		modellen.append(_model(bestand, discipline, doc))
	return {"project": map_doc.naam, "werkwijze": "bestanden", "modellen": modellen}


def _klaar(bestand: str, versie):
	_bestand(bestand)
	doc = afgeleid.laatste(bestand, cint(versie))
	if doc and doc.status in ("wacht", "bezig"):
		afgeleid.bijwerken(doc)  # misschien is de kern al klaar en heeft niemand het nog gezien
	if not doc or doc.status != "klaar":
		raise NogNietKlaar(_("Dit model is nog niet omgezet."))
	return doc


@frappe.whitelist(methods=["POST"])
def lees_adres(bestand: str, versie: str, deel: str) -> dict:
	"""Een kortlevend adres op deze site voor de bytes van één deel (de gastpagina haalt het zonder cookies)."""
	doc = _klaar(bestand, versie)
	gevonden = next((d for d in _json(doc.delen) or [] if d["naam"] == deel), None)
	if not gevonden:
		raise DeelOnbekend(_("Dit model heeft geen deel {0}.").format(deel))
	afgeleid.geopend(doc)
	token = leestoken.nieuw(doc.name, deel, frappe.session.user)
	return {"adres": f"/api/method/openaec_bim.api.lees?token={quote(token)}", "bytes": cint(gevonden["bytes"])}


@frappe.whitelist(allow_guest=True, methods=["GET"])
def lees(token: str | None = None):
	"""Stroom de bytes van één deel. Alleen zonder sessie (de gastpagina haalt dit zonder cookies), met een geldig
	token; de rechten van Storage worden met de gebruiker uit het token opnieuw gecontroleerd."""
	gegevens = leestoken.lees(token or "")
	aanroeper = frappe.session.user
	if aanroeper != "Guest":
		frappe.throw(_("Dit adres is alleen voor de werkplek."), frappe.PermissionError)
	doc = frappe.get_doc(afgeleid.DOCTYPE, gegevens["a"])
	frappe.set_user(gegevens["u"])
	try:
		_bestand(doc.bestand)
	finally:
		frappe.set_user(aanroeper)
	if doc.status != "klaar":
		frappe.throw(_("Deze link is ongeldig of verlopen."), frappe.PermissionError)
	try:
		antwoord = requests.get(
			afgeleid.leesadres(f"{doc.prefix}/{gegevens['d']}", 600), stream=True, timeout=TIMEOUT, allow_redirects=False
		)
	except requests.RequestException as fout:
		frappe.logger("openaec_bim").warning("opslag onbereikbaar bij lezen: %s", type(fout).__name__)
		frappe.throw(_("De opslag is tijdelijk niet bereikbaar."))
	if antwoord.status_code != 200:
		antwoord.close()
		frappe.throw(_("De opslag is tijdelijk niet bereikbaar."))

	def stroom():
		try:
			yield from antwoord.iter_content(LEESBLOK)
		finally:
			antwoord.close()

	respons = Response(stroom(), mimetype="application/octet-stream", direct_passthrough=True)
	if antwoord.headers.get("Content-Length"):
		respons.headers["Content-Length"] = antwoord.headers["Content-Length"]
	respons.headers["Content-Security-Policy"] = "sandbox; default-src 'none'"
	respons.headers["Cache-Control"] = "private, no-store"
	respons.headers["X-Content-Type-Options"] = "nosniff"
	respons.headers["Cross-Origin-Resource-Policy"] = "same-origin"
	return respons


@frappe.whitelist(methods=["POST"])
def eigenschappen(bestand: str, versie: str, globalids) -> dict:
	"""Eigenschappen, hoeveelheden, materialen en classificaties van elementen, uit de index van deze omzetting."""
	if isinstance(globalids, str):
		globalids = json.loads(globalids)
	if not isinstance(globalids, list) or not globalids or len(globalids) > MAX_GLOBALIDS:
		frappe.throw(_("Geef 1 tot {0} GlobalIds.").format(MAX_GLOBALIDS))
	doc = _klaar(bestand, versie)
	index = {
		"url": afgeleid.leesadres(f"{doc.prefix}/eigenschappen.sqlite", afgeleid.GELDIG_INDEX),
		"sha256": afgeleid.eigenschappen_sha256(doc),
	}
	return kern.eigenschappen(index, [str(g) for g in globalids])


@frappe.whitelist(methods=["POST"])
def opnieuw(bestand: str, versie: str) -> dict:
	"""Een mislukte omzetting opnieuw klaarzetten."""
	_bestand(bestand)
	doc = afgeleid.laatste(bestand, cint(versie))
	if doc and doc.status != "fout":
		return {"status": doc.status}
	return {"status": afgeleid.start(bestand, cint(versie)).status}
