"""De routes van de Foundation API 1.1 en de BCF-API 3.0 (buildingSMART), als tabel `(methode, patroon) -> functie`.

Een project is een `BIM Project` (de id van de modelmap) waarop de gebruiker leesrecht heeft. Elke functie krijgt het
JSON-lichaam van het verzoek en de padparameters, en geeft `(status, data)` of een eigen Response. Wat niet in de
tabel staat (snippets, bestanden, documenten, events), geeft 404.
"""

import re
from dataclasses import dataclass
from typing import Callable

import frappe
from frappe import _
from frappe.utils import get_url

from openaec_bim import issues

BCF = "/bcf/3.0"
OAUTH_AUTORISEER = "/api/method/frappe.integrations.oauth2.authorize"
OAUTH_TOKEN = "/api/method/frappe.integrations.oauth2.get_token"


@dataclass(frozen=True)
class Route:
	methode: str
	patroon: re.Pattern
	functie: Callable
	ingelogd: bool = True


ROUTES: list[Route] = []


def route(methode: str, pad: str, ingelogd: bool = True):
	"""Registreer een functie voor `methode` op `pad`; `{naam}` in het pad is een parameter (één padsegment)."""
	delen = re.split(r"(\{\w+\})", pad)
	patroon = re.compile(
		"^" + "".join(f"(?P<{d[1:-1]}>[^/]+)" if d.startswith("{") else re.escape(d) for d in delen) + "$"
	)

	def registreer(functie):
		ROUTES.append(Route(methode, patroon, functie, ingelogd))
		return functie

	return registreer


def zoek(methode: str, pad: str) -> tuple[Route, dict] | None:
	for r in ROUTES:
		if r.methode == methode or (methode == "HEAD" and r.methode == "GET"):
			gevonden = r.patroon.match(pad)
			if gevonden:
				return r, gevonden.groupdict()
	return None


def _object(lichaam) -> dict:
	if not isinstance(lichaam, dict):
		frappe.throw(_("Verwacht een JSON-object."))
	return lichaam


def _lijst(lichaam) -> list:
	if not isinstance(lichaam, list):
		frappe.throw(_("Verwacht een JSON-lijst."))
	return lichaam


# --- Foundation API 1.1 ---


@route("GET", "/foundation/versions", ingelogd=False)
def versies(_lichaam):
	return 200, {
		"versions": [
			{
				"api_id": "foundation",
				"version_id": "1.1",
				"detailed_version": "https://github.com/buildingSMART/foundation-API/tree/release_1_1",
				"api_base_url": get_url("/foundation/1.1"),
			},
			{
				"api_id": "bcf",
				"version_id": "3.0",
				"detailed_version": "https://github.com/buildingSMART/BCF-API/tree/release_3_0",
				"api_base_url": get_url(BCF),
			},
		]
	}


def _foundation(pad: str, ingelogd: bool = True):
	"""Foundation-paden onder 1.1 en, voor programma's die 1.0 vragen, onder 1.0 (dezelfde antwoorden)."""

	def registreer(functie):
		for versie in ("1.1", "1.0"):
			route("GET", f"/foundation/{versie}/{pad}", ingelogd)(functie)
		return functie

	return registreer


@_foundation("auth", ingelogd=False)
def auth(_lichaam):
	return 200, {
		"oauth2_auth_url": get_url(OAUTH_AUTORISEER),
		"oauth2_token_url": get_url(OAUTH_TOKEN),
		"http_basic_supported": False,
		"supported_oauth2_flows": ["authorization_code_grant"],
	}


@_foundation("current-user")
def huidige_gebruiker(_lichaam):
	gebruiker = frappe.session.user
	return 200, {"id": gebruiker, "name": frappe.utils.get_fullname(gebruiker)}


# --- projecten ---


def _project(project: str):
	"""Het project na de leescontrole; een modelmap zonder BIM-project is onbekend."""
	if not frappe.db.exists(issues.PROJECT, project):
		frappe.throw(_("Project bestaat niet"), frappe.DoesNotExistError)
	doc = frappe.get_doc(issues.PROJECT, project)
	issues._vereis_lezen(doc)
	return doc


def _project_json(project) -> dict:
	acties = issues.uitbreidingen(project)["project_actions"]
	return {"project_id": project.name, "name": project.titel or project.name, "authorization": {"project_actions": acties}}


@route("GET", f"{BCF}/projects")
def projecten(_lichaam):
	from openaec_storage.rechten import mag_op_plek

	uit = []
	for p in frappe.get_all(issues.PROJECT, ["name", "ruimte", "modelmap"], order_by="titel asc"):
		if frappe.db.exists("Ruimte", p.ruimte) and mag_op_plek(p.ruimte, p.modelmap, "read"):
			uit.append(_project_json(frappe.get_doc(issues.PROJECT, p.name)))
	return 200, uit


@route("GET", f"{BCF}/projects/{{project}}")
def project(_lichaam, project):
	return 200, _project_json(_project(project))


@route("PUT", f"{BCF}/projects/{{project}}")
def project_wijzig(lichaam, project):
	doc = _project(project)
	if "update" not in issues.uitbreidingen(doc)["project_actions"]:
		frappe.throw(_("Alleen wie in de modelmap mag schrijven, kan het project wijzigen."), frappe.PermissionError)
	naam = str(_object(lichaam).get("name") or "").strip()
	if naam:
		doc.titel = naam
		doc.save(ignore_permissions=True)
	return 200, _project_json(doc)


@route("GET", f"{BCF}/projects/{{project}}/extensions")
def extensions(_lichaam, project):
	return 200, issues.uitbreidingen(_project(project))


# --- topics ---


def _topic(project: str, guid: str) -> str:
	"""Controleer dat het topic bij dit project hoort; een topic van een ander project is hier onbekend."""
	doc = _project(project)
	if frappe.db.get_value(issues.ISSUE, guid, "project") != doc.name:
		frappe.throw(_("Topic bestaat niet"), frappe.DoesNotExistError)
	return guid


def topic_json(topic: dict) -> dict:
	"""De topic-JSON van de domeinlaag zonder wat de BCF-API niet kent (de elementen per versie)."""
	return {k: v for k, v in topic.items() if k != "elementen"}


@route("GET", f"{BCF}/projects/{{project}}/topics")
def topics(_lichaam, project):
	return 200, [topic_json(t) for t in issues.topics(_project(project))]


@route("POST", f"{BCF}/projects/{{project}}/topics")
def topic_maak(lichaam, project):
	return 201, topic_json(issues.topic_maak(_project(project), _object(lichaam)))


@route("GET", f"{BCF}/projects/{{project}}/topics/{{guid}}")
def topic(_lichaam, project, guid):
	return 200, topic_json(issues.topic(_topic(project, guid)))


@route("PUT", f"{BCF}/projects/{{project}}/topics/{{guid}}")
def topic_wijzig(lichaam, project, guid):
	return 200, topic_json(issues.topic_wijzig(_topic(project, guid), _object(lichaam)))


@route("DELETE", f"{BCF}/projects/{{project}}/topics/{{guid}}")
def topic_verwijder(_lichaam, project, guid):
	issues.topic_verwijder(_topic(project, guid))
	return 200, None


# --- reacties ---


@route("GET", f"{BCF}/projects/{{project}}/topics/{{guid}}/comments")
def reacties(_lichaam, project, guid):
	return 200, issues.reacties(_topic(project, guid))


@route("POST", f"{BCF}/projects/{{project}}/topics/{{guid}}/comments")
def reactie_maak(lichaam, project, guid):
	return 201, issues.reactie_maak(_topic(project, guid), _object(lichaam))


@route("GET", f"{BCF}/projects/{{project}}/topics/{{guid}}/comments/{{reactie}}")
def reactie(_lichaam, project, guid, reactie):
	gevonden = [r for r in issues.reacties(_topic(project, guid)) if r["guid"] == reactie]
	if not gevonden:
		frappe.throw(_("Reactie bestaat niet"), frappe.DoesNotExistError)
	return 200, gevonden[0]


@route("PUT", f"{BCF}/projects/{{project}}/topics/{{guid}}/comments/{{reactie}}")
def reactie_wijzig(lichaam, project, guid, reactie):
	return 200, issues.reactie_wijzig(_topic(project, guid), reactie, _object(lichaam))


@route("DELETE", f"{BCF}/projects/{{project}}/topics/{{guid}}/comments/{{reactie}}")
def reactie_verwijder(_lichaam, project, guid, reactie):
	issues.reactie_verwijder(_topic(project, guid), reactie)
	return 200, None
