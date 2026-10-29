"""De ingang van de BCF-API: elk verzoek onder `/foundation/` en `/bcf/3.0/`, met alle methoden.

Frappe stuurt buiten `/api/` alleen GET, HEAD en POST naar de website (een paginarenderer krijgt PUT en DELETE nooit
te zien); daarom handelt een `before_request`-hook deze paden af. Hij meldt de gebruiker aan zoals Frappe dat doet
(OAuth2-bearertoken of API-sleutel), roept de route aan, commit bij succes en geeft het antwoord terug via een
HTTPException, zodat Frappe de rest van het verzoek overslaat.
"""

import json

import frappe
from werkzeug.exceptions import HTTPException
from werkzeug.wrappers import Response

from openaec_bim import issues
from openaec_bim.bcf_api import routes

VOORVOEGSELS = ("/foundation/", "/bcf/3.0/")


class Antwoord(HTTPException):
	"""Draagt het antwoord van de BCF-API langs de foutafhandeling van Frappe naar buiten."""

	def __init__(self, response: Response):
		super().__init__(response=response)


def is_bcf(pad: str) -> bool:
	return pad == "/bcf/3.0" or pad.startswith(VOORVOEGSELS)


def json_antwoord(status: int, data=None) -> Response:
	inhoud = "" if data is None else json.dumps(data, ensure_ascii=False, default=str)
	respons = Response(inhoud, status=status, mimetype="application/json")
	respons.headers["Cache-Control"] = "no-store"
	return respons


def _fout(status: int, melding: str, foutcode: str | None = None) -> Response:
	return json_antwoord(status, {"message": melding, **({"foutcode": foutcode} if foutcode else {})})


def _melding(fout: Exception) -> str:
	return frappe.utils.strip_html(str(fout)) or type(fout).__name__


def afhandelen(request) -> Response:
	"""Zoek de route en roep haar aan; fouten worden JSON met de statuscode van de specificatie."""
	frappe.flags.bim_bron = "bcf-api"
	gevonden = routes.zoek(request.method, request.path.rstrip("/") or "/")
	if gevonden is None:
		return _fout(404, "Onbekend pad of onbekende methode.")
	route, parameters = gevonden
	if route.ingelogd and frappe.session.user in (None, "", "Guest"):
		return _fout(401, "Meld je aan met OAuth2 (zie /foundation/1.1/auth).")
	lichaam = None
	if request.method in ("POST", "PUT"):
		try:
			lichaam = json.loads(request.get_data(as_text=True) or "null")
		except ValueError:
			return _fout(400, "Het verzoek is geen geldige JSON.")
	frappe.local.response.pop("foutcode", None)
	try:
		uitkomst = route.functie(lichaam, **parameters)
	except issues.VerouderdeVersie as fout:
		return _fout(409, _melding(fout))
	except frappe.AuthenticationError as fout:
		return _fout(401, _melding(fout))
	except frappe.PermissionError as fout:
		return _fout(401 if frappe.session.user == "Guest" else 403, _melding(fout), frappe.local.response.get("foutcode"))
	except frappe.DoesNotExistError as fout:
		return _fout(404, _melding(fout))
	except frappe.ValidationError as fout:
		return _fout(400, _melding(fout), frappe.local.response.get("foutcode"))
	if isinstance(uitkomst, Response):
		return uitkomst
	status, data = uitkomst
	return json_antwoord(status, data)


def voor_verzoek() -> None:
	"""`before_request`-hook: handel de paden van de BCF-API af, voor elke methode behalve OPTIONS (CORS)."""
	request = frappe.request
	if request is None or request.method == "OPTIONS" or not is_bcf(request.path):
		return
	from frappe.auth import validate_auth

	try:
		validate_auth()
	except frappe.AuthenticationError:
		raise Antwoord(_fout(401, "Het token of de sleutel is ongeldig.")) from None
	try:
		respons = afhandelen(request)
	except Exception:
		frappe.log_error(title="BCF-API")
		respons = _fout(500, "Er ging iets mis op de server.")
	if respons.status_code < 400:
		frappe.db.commit()
	raise Antwoord(respons)
