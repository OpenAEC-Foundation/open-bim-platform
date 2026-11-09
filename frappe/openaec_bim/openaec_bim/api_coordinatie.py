"""API voor issues en botsingen in de gastpagina van de werkplek, met de sessie van de gebruiker.

Elke methode is een dunne laag over `issues`, `botsingen` en `audit`, die de rechten via Storage controleren. De
modelmap (`map`) is het project. Wijzigingen komen in het auditlog met de bron `gastpagina`.
"""

import json

import frappe
from frappe import _

from openaec_bim import audit, botsingen as botsingen_mod, issues as issues_mod


def _gastpagina() -> None:
	frappe.flags.bim_bron = "gastpagina"


def _object(waarde) -> dict:
	"""Een JSON-argument: als object, of als tekst uit een formulierverzoek."""
	waarde = json.loads(waarde) if isinstance(waarde, str) else waarde
	if not isinstance(waarde, dict):
		frappe.throw(_("Verwacht een object."))
	return waarde


def _lijst(waarde) -> list:
	waarde = json.loads(waarde) if isinstance(waarde, str) else waarde
	if not isinstance(waarde, list):
		frappe.throw(_("Verwacht een lijst."))
	return waarde


@frappe.whitelist(methods=["POST"])
def instellingen(map: str) -> dict:
	"""De BCF-uitbreidingen van het project (soorten, statussen, prioriteiten, fasen, labels, gebruikers, acties)."""
	_gastpagina()
	return issues_mod.uitbreidingen(issues_mod.project_van(map))


@frappe.whitelist(methods=["POST"])
def issues(map: str) -> list[dict]:
	_gastpagina()
	return issues_mod.topics(issues_mod.project_van(map))


@frappe.whitelist(methods=["POST"])
def issue_bewaar(map: str, topic) -> dict:
	"""Een nieuw issue, of (met een bekende `guid`) een wijziging van een issue van dit project."""
	_gastpagina()
	project = issues_mod.project_van(map)
	topic = _object(topic)
	guid = topic.get("guid")
	if guid and frappe.db.exists(issues_mod.ISSUE, guid):
		if frappe.db.get_value(issues_mod.ISSUE, guid, "project") != project.name:
			frappe.throw(_("Dit issue hoort bij een ander project."))
		return issues_mod.topic_wijzig(guid, topic)
	return issues_mod.topic_maak(project, topic)


@frappe.whitelist(methods=["POST"])
def issue_verwijder(guid: str) -> None:
	_gastpagina()
	issues_mod.topic_verwijder(guid)


@frappe.whitelist(methods=["POST"])
def reacties(guid: str) -> list[dict]:
	_gastpagina()
	return issues_mod.reacties(guid)


@frappe.whitelist(methods=["POST"])
def reactie_bewaar(guid: str, reactie) -> dict:
	_gastpagina()
	reactie = _object(reactie)
	if reactie.get("guid") and frappe.db.exists(issues_mod.REACTIE, reactie["guid"]):
		return issues_mod.reactie_wijzig(guid, reactie["guid"], reactie)
	return issues_mod.reactie_maak(guid, reactie)


@frappe.whitelist(methods=["POST"])
def standpunten(guid: str) -> list[dict]:
	"""De standpunten van een issue, zonder de schermafbeeldingen zelf (die geeft `snapshot`)."""
	_gastpagina()
	return issues_mod.standpunten(guid)


@frappe.whitelist(methods=["POST"])
def standpunt_bewaar(guid: str, standpunt) -> dict:
	_gastpagina()
	return issues_mod.standpunt_maak(guid, _object(standpunt))


@frappe.whitelist(methods=["POST"])
def snapshot(guid: str, standpunt: str) -> dict:
	"""De schermafbeelding van een standpunt als base64 (de gastpagina geeft hem door aan het frame)."""
	import base64

	inhoud, mime = issues_mod.snapshot(guid, standpunt)
	return {"snapshot_type": "png" if mime == "image/png" else "jpg", "snapshot_data": base64.b64encode(inhoud).decode()}


@frappe.whitelist(methods=["POST"])
def bcf_export(map: str, versie: str = "3.0") -> dict:
	_gastpagina()
	return issues_mod.exporteer_zip(issues_mod.project_van(map), versie)


@frappe.whitelist(methods=["POST"])
def bcf_import(map: str, bestand: str) -> dict:
	_gastpagina()
	return issues_mod.importeer(issues_mod.project_van(map), bestand)


@frappe.whitelist(methods=["POST"])
def botsingsronde_start(map: str, set_a, set_b, soort: str = "hard", tolerantie=0.0, titel: str | None = None) -> dict:
	_gastpagina()
	project = issues_mod.project_van(map)
	ronde = botsingen_mod.start(project, _lijst(set_a), _lijst(set_b), soort, float(tolerantie), titel)
	return {"ronde": ronde}


@frappe.whitelist(methods=["POST"])
def botsingsrondes(map: str) -> list[dict]:
	_gastpagina()
	return botsingen_mod.rondes(issues_mod.project_van(map))


@frappe.whitelist(methods=["POST"])
def botsingen(ronde: str) -> list[dict]:
	_gastpagina()
	return botsingen_mod.lijst(ronde)


@frappe.whitelist(methods=["POST"])
def botsing_status(botsing: str, status: str) -> dict:
	_gastpagina()
	return botsingen_mod.zet_status(botsing, status)


@frappe.whitelist(methods=["POST"])
def botsing_naar_issue(botsing: str) -> dict:
	_gastpagina()
	return botsingen_mod.naar_issue(botsing)


@frappe.whitelist(methods=["POST"])
def audit_export(map: str) -> dict:
	"""Het auditlog van het project als CSV; alleen voor wie in de modelmap mag schrijven."""
	project = issues_mod.project_van(map)
	if not issues_mod._schrijver(project):
		frappe.throw(_("Alleen wie in de modelmap mag schrijven, kan het auditlog exporteren."), frappe.PermissionError)
	return {"csv": audit.exporteer(project.name)}
