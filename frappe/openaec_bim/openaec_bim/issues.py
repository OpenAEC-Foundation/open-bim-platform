"""Issues met BCF 3.0 als datamodel: topics, reacties, standpunten, verwante issues en documentverwijzingen.

In- en uitvoer hebben de JSON-vorm van de BCF-API 3.0 (`topic_type`, `creation_date`, `authorization`, ...); de
gastpagina en de BCF-API zijn dunne lagen over deze functies. Rechten komen uit Storage: wie de modelmap mag lezen,
mag issues en reacties lezen en maken; een issue wijzigen of verwijderen mag de maker, wie het toegewezen is, of wie
schrijfrecht op de modelmap heeft. Een gearchiveerde ruimte is alleen te lezen.
"""

import base64
import binascii
import copy
import hashlib
import json
import re
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

import frappe
from frappe import _
from frappe.utils import cint, get_datetime, get_system_timezone, getdate, today

from openaec_bim import afgeleid, api, bcfzip, kern, koppeling

PROJECT = "BIM Project"
ISSUE = "BIM Issue"
STANDPUNT = "BIM Standpunt"
REACTIE = "BIM Reactie"

MAX_SNAPSHOT_BYTES = 5 * 1024 * 1024
SNAPSHOT_SOORTEN = {"png": (b"\x89PNG\r\n\x1a\n", "image/png"), "jpg": (b"\xff\xd8\xff", "image/jpeg")}
STANDPUNT_VELDEN = ("perspective_camera", "orthogonal_camera", "lines", "clipping_planes", "bitmaps", "components")

ALLE_TOPIC_ACTIES = [
	"update",
	"updateBimSnippet",
	"updateRelatedTopics",
	"updateDocumentReferences",
	"updateFiles",
	"createComment",
	"createViewpoint",
	"delete",
]
LEZER_TOPIC_ACTIES = ["createComment", "createViewpoint"]

# BCF-veld -> veld van BIM Issue; JSON-velden worden als JSON bewaard.
TOPIC_VELDEN = {
	"title": "titel",
	"description": "beschrijving",
	"topic_type": "soort",
	"topic_status": "status",
	"priority": "prioriteit",
	"stage": "fase",
	"assigned_to": "toegewezen_aan",
	"due_date": "vervaldatum",
	"index": "bcf_index",
	"labels": "labels",
	"reference_links": "referentielinks",
	"bim_snippet": "bim_snippet",
}
JSON_VELDEN = {"labels", "referentielinks", "bim_snippet", "verwante_issues", "documentverwijzingen"}
# BCF-veld -> lijst in BIM Project met de toegestane waarden; een lege lijst laat alles toe.
KEUZELIJSTEN = {"topic_type": "soorten", "topic_status": "statussen", "priority": "prioriteiten", "stage": "fasen"}


class VerouderdeVersie(frappe.ValidationError):
	"""Iemand anders heeft het issue gewijzigd sinds de `modified_date` die de aanroeper meestuurde."""

	http_status_code = 409


def _weiger(melding: str, foutcode: str, uitzondering=frappe.ValidationError):
	from openaec_storage.rechten import weiger

	weiger(melding, foutcode, uitzondering)


# --- datums ---


def _tijdzone() -> ZoneInfo:
	return ZoneInfo(get_system_timezone())


def _iso(waarde) -> str | None:
	"""Een tijdstip uit de database als ISO 8601 met tijdzone, op de milliseconde."""
	if not waarde:
		return None
	return get_datetime(waarde).replace(tzinfo=_tijdzone()).isoformat(timespec="milliseconds")


def _tijdstip(tekst: str) -> datetime:
	try:
		tijd = datetime.fromisoformat(str(tekst).replace("Z", "+00:00"))
	except ValueError:
		_weiger(_("Geen geldige datum: {0}").format(tekst), "datum_ongeldig")
	return tijd if tijd.tzinfo else tijd.replace(tzinfo=_tijdzone())


def _op_milliseconde(tijd: datetime) -> datetime:
	return tijd.replace(microsecond=tijd.microsecond // 1000 * 1000)


# --- projecten en rechten ---


def _regels(tekst: str | None) -> list[str]:
	return [r.strip() for r in (tekst or "").splitlines() if r.strip()]


def _project(project):
	if isinstance(project, str):
		if not frappe.db.exists(PROJECT, project):
			frappe.throw(_("Project bestaat niet"), frappe.DoesNotExistError)
		return frappe.get_doc(PROJECT, project)
	return project


def _gebruiker() -> str:
	return frappe.session.user


def _vereis_lezen(project) -> None:
	from openaec_storage.rechten import vereis_op_plek

	vereis_op_plek(project.ruimte, project.modelmap, "read")


def _vereis_meedoen(project) -> None:
	"""Lezen en een bijdrage leveren (issue, reactie, standpunt): leesrecht, en de ruimte is niet gearchiveerd."""
	from openaec_storage.rechten import weiger_als_gearchiveerd

	_vereis_lezen(project)
	weiger_als_gearchiveerd(project.ruimte)


def _gearchiveerd(project) -> bool:
	from openaec_storage.rechten import is_gearchiveerd

	return is_gearchiveerd(project.ruimte)


def _schrijver(project, gebruiker: str | None = None) -> bool:
	from openaec_storage.rechten import mag_op_plek

	return mag_op_plek(project.ruimte, project.modelmap, "write", gebruiker=gebruiker)


def _mag_wijzigen(issue, project) -> bool:
	gebruiker = _gebruiker()
	if _gearchiveerd(project):
		return False
	return gebruiker in (issue.owner, issue.toegewezen_aan) or _schrijver(project)


def _vereis_wijzigen(issue, project) -> None:
	_vereis_meedoen(project)
	if not _mag_wijzigen(issue, project):
		frappe.throw(_("Alleen de maker, wie het issue toegewezen is, of een schrijver mag dit wijzigen."), frappe.PermissionError)


def project_van(map_: str):
	"""Het BIM-project van een modelmap; bij het eerste gebruik wordt het gemaakt. Aan het begin van een verzoek
	aanroepen: als een ander verzoek het project tegelijk maakt, begint deze transactie opnieuw."""
	map_doc = api._modelmap(map_)
	if not frappe.db.exists(PROJECT, map_doc.name):
		try:
			frappe.get_doc(
				{"doctype": PROJECT, "modelmap": map_doc.name, "ruimte": map_doc.ruimte, "titel": map_doc.naam}
			).insert(ignore_permissions=True)
		except (frappe.DuplicateEntryError, frappe.QueryDeadlockError):
			# Tegelijk gemaakt door een ander verzoek (de gastpagina vraagt instellingen en issues tegelijk). Een nieuwe
			# transactie ziet dat project; project_van staat aan het begin van een verzoek, er gaat niets verloren.
			frappe.db.rollback()
	return frappe.get_doc(PROJECT, map_doc.name)


def _gebruikers(project) -> list[str]:
	tabel = frappe.get_meta("Ruimte").get_field("leden").options
	return sorted(set(frappe.get_all(tabel, {"parent": project.ruimte}, pluck="gebruiker", ignore_permissions=True)))


def uitbreidingen(project) -> dict:
	"""De BCF-uitbreidingen (`extensions`) van het project, met de acties van deze gebruiker."""
	project = _project(project)
	_vereis_lezen(project)
	actief = not _gearchiveerd(project)
	schrijver = actief and _schrijver(project)
	return {
		"topic_type": _regels(project.soorten),
		"topic_status": _regels(project.statussen),
		"topic_label": _regels(project.labels),
		"snippet_type": [],
		"priority": _regels(project.prioriteiten),
		"users": _gebruikers(project),
		"stage": _regels(project.fasen),
		"project_actions": (["update", "createTopic"] if schrijver else ["createTopic"]) if actief else [],
		"topic_actions": (ALLE_TOPIC_ACTIES if schrijver else LEZER_TOPIC_ACTIES) if actief else [],
		"comment_actions": ["update", "delete"] if actief else [],
	}


# --- topics ---


def _json(waarde):
	return json.loads(waarde) if isinstance(waarde, str) else waarde


def _issue(guid: str):
	"""Het issue en zijn project, na de leescontrole."""
	if not guid or not frappe.db.exists(ISSUE, guid):
		frappe.throw(_("Issue bestaat niet"), frappe.DoesNotExistError)
	issue = frappe.get_doc(ISSUE, guid)
	project = _project(issue.project)
	_vereis_lezen(project)
	return issue, project


def _naar_bcf(issue, project) -> dict:
	mag = _mag_wijzigen(issue, project)
	actief = not _gearchiveerd(project)
	return {
		"guid": issue.name,
		"topic_type": issue.soort,
		"topic_status": issue.status,
		"reference_links": _json(issue.referentielinks) or [],
		"title": issue.titel,
		"priority": issue.prioriteit,
		"index": cint(issue.bcf_index) or None,
		"labels": _json(issue.labels) or [],
		"creation_date": _iso(issue.creation),
		"creation_author": issue.owner,
		"modified_date": _iso(issue.modified),
		"modified_author": issue.modified_by,
		"assigned_to": issue.toegewezen_aan,
		"stage": issue.fase,
		"description": issue.beschrijving,
		"bim_snippet": _json(issue.bim_snippet),
		"due_date": str(getdate(issue.vervaldatum)) if issue.vervaldatum else None,
		"authorization": {
			"topic_actions": (ALLE_TOPIC_ACTIES if mag else LEZER_TOPIC_ACTIES) if actief else [],
			"topic_status": _regels(project.statussen) if mag else [],
		},
		"elementen": _elementen(issue),
	}


def _elementen(issue) -> list[dict]:
	"""De elementen van het issue in de versie die het project toont (de laatste omgezette van elk bestand), langs de
	versiekoppeling; `teruggevonden` is onwaar als het element daar niet (meer) te vinden is."""
	getoond: dict[str, int | None] = {}
	uit = []
	for e in issue.elementen:
		if not e.bestand or not e.versie:
			uit.append({"ifc_guid": e.globalid, "bestand": e.bestand or None, "versie": None, "teruggevonden": False})
			continue
		if e.bestand not in getoond:
			getoond[e.bestand] = afgeleid.getoonde_versie(e.bestand)
		versie = cint(e.versie)
		doel = cint(getoond[e.bestand]) or versie
		gevonden = koppeling.huidig(e.bestand, e.globalid, versie, doel) if doel > versie else e.globalid
		if gevonden is None:
			uit.append({"ifc_guid": e.globalid, "bestand": e.bestand, "versie": str(versie), "teruggevonden": False})
		else:
			uit.append({"ifc_guid": gevonden, "bestand": e.bestand, "versie": str(max(doel, versie)), "teruggevonden": True})
	return uit


def _controleer_waarde(project, bcf_veld: str, waarde) -> None:
	toegestaan = _regels(project.get(KEUZELIJSTEN[bcf_veld]))
	if waarde and toegestaan and waarde not in toegestaan:
		_weiger(_("{0} is geen toegestane waarde voor {1} in dit project.").format(waarde, bcf_veld), "waarde_onbekend")


def _van_bcf(data: dict, issue, project) -> None:
	"""Zet de BCF-velden die in `data` staan op het issue, na controle tegen de projectinstellingen."""
	for bcf_veld, veld in TOPIC_VELDEN.items():
		if bcf_veld not in data:
			continue
		waarde = data[bcf_veld]
		if bcf_veld in KEUZELIJSTEN:
			_controleer_waarde(project, bcf_veld, waarde)
		elif bcf_veld == "labels":
			waarde = [str(label) for label in waarde or []]
			toegestaan = _regels(project.labels)
			if toegestaan and any(label not in toegestaan for label in waarde):
				_weiger(_("Een label is niet toegestaan in dit project."), "waarde_onbekend")
		elif bcf_veld == "assigned_to" and waarde:
			from openaec_storage.rechten import mag_op_plek

			if not frappe.db.exists("User", waarde) or not mag_op_plek(
				project.ruimte, project.modelmap, "read", gebruiker=waarde
			):
				_weiger(_("{0} kan dit project niet zien.").format(waarde), "toegewezen_onbekend")
		elif bcf_veld == "due_date" and waarde:
			waarde = str(getdate(str(waarde)[:10]))
		elif bcf_veld == "index":
			waarde = cint(waarde)
		issue.set(veld, json.dumps(waarde) if veld in JSON_VELDEN and waarde is not None else waarde)
	if not (issue.titel or "").strip():
		_weiger(_("Een issue heeft een titel nodig."), "titel_verplicht")


def topics(project) -> list[dict]:
	project = _project(project)
	_vereis_lezen(project)
	namen = frappe.get_all(ISSUE, {"project": project.name}, pluck="name", order_by="creation asc")
	return [_naar_bcf(frappe.get_doc(ISSUE, naam), project) for naam in namen]


def topic(guid: str) -> dict:
	issue, project = _issue(guid)
	return _naar_bcf(issue, project)


def _nieuwe_guid(gevraagd, doctype: str) -> str:
	if gevraagd:
		try:
			gevraagd = str(uuid.UUID(str(gevraagd)))
		except ValueError:
			_weiger(_("Geen geldige guid: {0}").format(gevraagd), "guid_ongeldig")
		if frappe.db.exists(doctype, gevraagd):
			_weiger(_("De guid {0} bestaat al.").format(gevraagd), "guid_bestaat")
		return gevraagd
	return str(uuid.uuid4())


def _nieuw_issue(project, data: dict):
	issue = frappe.get_doc(
		{
			"doctype": ISSUE,
			"guid": _nieuwe_guid(data.get("guid"), ISSUE),
			"project": project.name,
			"status": project.standaard_status,
		}
	)
	_van_bcf(data, issue, project)
	issue.insert(ignore_permissions=True)
	return issue


def _zet_herkomst(doc, auteur: str | None, datum: str | None) -> None:
	"""Maker en tijdstip uit een BCF-bestand, na de insert: Frappe zet bij elke insert de gebruiker en nu."""
	waarden = {}
	if auteur:
		waarden["owner"] = auteur
	if datum:
		waarden["creation"] = _tijdstip(datum).astimezone(_tijdzone()).replace(tzinfo=None)
	if waarden:
		frappe.db.set_value(doc.doctype, doc.name, waarden, update_modified=False)
		doc.update(waarden)


def topic_maak(project, data: dict) -> dict:
	project = _project(project)
	_vereis_meedoen(project)
	return _naar_bcf(_nieuw_issue(project, data), project)


def topic_wijzig(guid: str, data: dict) -> dict:
	"""Wijzig de velden in `data`. Met `modified_date` ouder dan de opgeslagen versie: `VerouderdeVersie` (409)."""
	_issue(guid)
	issue = frappe.get_doc(ISSUE, guid, for_update=True)
	project = _project(issue.project)
	_vereis_wijzigen(issue, project)
	if data.get("modified_date"):
		if _tijdstip(data["modified_date"]) < _op_milliseconde(get_datetime(issue.modified).replace(tzinfo=_tijdzone())):
			_weiger(_("Dit issue is intussen door iemand anders gewijzigd."), "issue_verouderd", VerouderdeVersie)
	_van_bcf(data, issue, project)
	issue.save(ignore_permissions=True)
	return _naar_bcf(issue, project)


def topic_verwijder(guid: str) -> None:
	issue, project = _issue(guid)
	_vereis_wijzigen(issue, project)
	for reactie in frappe.get_all(REACTIE, {"issue": guid}, pluck="name"):
		frappe.delete_doc(REACTIE, reactie, ignore_permissions=True)
	for standpunt in frappe.get_all(STANDPUNT, {"issue": guid}, pluck="name"):
		frappe.delete_doc(STANDPUNT, standpunt, ignore_permissions=True)
	# Botsingen die naar dit issue wijzen (in elke ronde): de verwijzing vervalt, de botsing blijft.
	for botsing in frappe.get_all("BIM Botsing", {"issue": guid}, pluck="name"):
		doc = frappe.get_doc("BIM Botsing", botsing)
		doc.issue = None
		doc.save(ignore_permissions=True)
	frappe.delete_doc(ISSUE, guid, ignore_permissions=True)


# --- reacties ---


def _reactie_naar_bcf(reactie, issue, project) -> dict:
	eigen = reactie.owner == _gebruiker()
	mag = not _gearchiveerd(project) and (eigen or _schrijver(project))
	return {
		"guid": reactie.name,
		"date": _iso(reactie.creation),
		"author": reactie.owner,
		"comment": reactie.tekst,
		"topic_guid": issue.name,
		"viewpoint_guid": reactie.standpunt,
		"modified_date": _iso(reactie.modified),
		"modified_author": reactie.modified_by,
		"authorization": {"comment_actions": ["update", "delete"] if mag else []},
	}


def _reactie(issue, naam: str):
	if not naam or frappe.db.get_value(REACTIE, naam, "issue") != issue.name:
		frappe.throw(_("Reactie bestaat niet"), frappe.DoesNotExistError)
	return frappe.get_doc(REACTIE, naam)


def _vereis_eigen_reactie(reactie, project) -> None:
	_vereis_meedoen(project)
	if reactie.owner != _gebruiker() and not _schrijver(project):
		frappe.throw(_("Alleen de schrijver van een reactie mag haar wijzigen."), frappe.PermissionError)


def _zet_reactie(reactie, issue, data: dict) -> None:
	if "comment" in data:
		reactie.tekst = data["comment"]
	if "viewpoint_guid" in data:
		standpunt = data["viewpoint_guid"]
		if standpunt and frappe.db.get_value(STANDPUNT, standpunt, "issue") != issue.name:
			_weiger(_("Dit standpunt hoort niet bij het issue."), "standpunt_onbekend")
		reactie.standpunt = standpunt or None
	if not (reactie.tekst or "").strip():
		_weiger(_("Een reactie heeft tekst nodig."), "reactie_leeg")


def reacties(guid: str) -> list[dict]:
	issue, project = _issue(guid)
	namen = frappe.get_all(REACTIE, {"issue": guid}, pluck="name", order_by="creation asc")
	return [_reactie_naar_bcf(frappe.get_doc(REACTIE, naam), issue, project) for naam in namen]


def reactie_maak(guid: str, data: dict) -> dict:
	issue, project = _issue(guid)
	_vereis_meedoen(project)
	return _reactie_naar_bcf(_nieuwe_reactie(issue, data), issue, project)


def _nieuwe_reactie(issue, data: dict, auteur: str | None = None, datum: str | None = None, handeling: str | None = None):
	reactie = frappe.get_doc({"doctype": REACTIE, "guid": _nieuwe_guid(data.get("guid"), REACTIE), "issue": issue.name})
	_zet_reactie(reactie, issue, data)
	reactie.flags.bim_handeling = handeling
	reactie.insert(ignore_permissions=True)
	_zet_herkomst(reactie, auteur, datum)
	return reactie


def reactie_wijzig(guid: str, reactie: str, data: dict) -> dict:
	issue, project = _issue(guid)
	doc = _reactie(issue, reactie)
	_vereis_eigen_reactie(doc, project)
	_zet_reactie(doc, issue, data)
	doc.save(ignore_permissions=True)
	return _reactie_naar_bcf(doc, issue, project)


def reactie_verwijder(guid: str, reactie: str) -> None:
	issue, project = _issue(guid)
	doc = _reactie(issue, reactie)
	_vereis_eigen_reactie(doc, project)
	frappe.delete_doc(REACTIE, doc.name, ignore_permissions=True)


# --- standpunten ---


def _standpunt_naar_bcf(standpunt) -> dict:
	return {
		"guid": standpunt.name,
		"index": cint(standpunt.bcf_index) or None,
		**(_json(standpunt.standpunt) or {}),
		"snapshot": {"snapshot_type": standpunt.snapshot_type} if standpunt.snapshot else None,
	}


def _standpunt(issue, naam: str):
	if not naam or frappe.db.get_value(STANDPUNT, naam, "issue") != issue.name:
		frappe.throw(_("Standpunt bestaat niet"), frappe.DoesNotExistError)
	return frappe.get_doc(STANDPUNT, naam)


def _snapshot_of_niets(snapshot: dict | None) -> tuple[bytes, str] | None:
	"""De bytes en het type van een schermafbeelding als het een PNG of JPEG van hoogstens 5 MB is, anders None."""
	soort = str((snapshot or {}).get("snapshot_type") or "").lower().replace("jpeg", "jpg")
	data = str((snapshot or {}).get("snapshot_data") or "")
	if soort not in SNAPSHOT_SOORTEN or len(data) > (MAX_SNAPSHOT_BYTES + 2) // 3 * 4:
		return None
	try:
		inhoud = base64.b64decode(data, validate=True)
	except (binascii.Error, ValueError):
		return None
	if not inhoud or len(inhoud) > MAX_SNAPSHOT_BYTES or not inhoud.startswith(SNAPSHOT_SOORTEN[soort][0]):
		return None
	return inhoud, soort


def _snapshot(snapshot: dict) -> tuple[bytes, str]:
	gevonden = _snapshot_of_niets(snapshot)
	if gevonden is None:
		_weiger(_("De schermafbeelding moet een PNG of JPEG van hoogstens 5 MB zijn."), "snapshot_ongeldig")
	return gevonden


def zoek_elementen(project, globalids: list[str]) -> dict[str, tuple[str, str]]:
	"""Voor elke GlobalId het bestand en de versie waarin hij staat, uit de index van de omgezette modellen."""
	project = _project(project)
	map_doc = frappe.db.get_value("Opslagmap", project.modelmap, ["name", "ruimte", "naam"], as_dict=True)
	open_ = set(globalids)
	gevonden: dict[str, tuple[str, str]] = {}
	for bestand, _discipline in api.ifc_in_map(map_doc):
		if not open_:
			break
		versie = cint(bestand.huidige_versie)
		doc = afgeleid.laatste(bestand.name, versie)
		if doc and doc.status in ("wacht", "bezig"):
			afgeleid.bijwerken(doc)
		if not doc or doc.status != "klaar":
			continue
		index = {
			"url": afgeleid.leesadres(f"{doc.prefix}/eigenschappen.sqlite", afgeleid.GELDIG_INDEX),
			"sha256": afgeleid.eigenschappen_sha256(doc),
		}
		try:
			elementen = kern.eigenschappen(index, sorted(open_))
		except kern.KernFout as fout:
			frappe.logger("openaec_bim").warning("elementen zoeken in %s mislukt: %s", bestand.name, fout.code)
			continue
		for globalid in elementen:
			if globalid in open_:
				gevonden[globalid] = (bestand.name, str(versie))
				open_.discard(globalid)
	return gevonden


def _nieuwe_globalids(issue, selectie: list[dict]) -> list[str]:
	"""De GlobalIds uit de selectie die het issue nog niet als element heeft."""
	bekend = {e.globalid for e in issue.elementen}
	nieuw = []
	for component in selectie or []:
		globalid = str(component.get("ifc_guid") or "")
		if globalid and globalid not in bekend:
			nieuw.append(globalid)
			bekend.add(globalid)
	return nieuw


def _voeg_elementen_toe(issue, project, selectie: list[dict], plekken: dict | None = None) -> None:
	"""De selectie als elementen van het issue, met bestand en versie uit de index (of uit `plekken`, al opgezocht)."""
	nieuw = _nieuwe_globalids(issue, selectie)
	if not nieuw:
		return
	if plekken is None:
		plekken = zoek_elementen(project, nieuw)
	for globalid in nieuw:
		bestand, versie = plekken.get(globalid, (None, None))
		issue.append("elementen", {"globalid": globalid, "bestand": bestand, "versie": versie})
	issue.save(ignore_permissions=True)


def standpunten(guid: str) -> list[dict]:
	issue, _project_doc = _issue(guid)
	namen = frappe.get_all(STANDPUNT, {"issue": guid}, pluck="name", order_by="creation asc")
	return [_standpunt_naar_bcf(frappe.get_doc(STANDPUNT, naam)) for naam in namen]


def standpunt(guid: str, sp: str) -> dict:
	issue, _project_doc = _issue(guid)
	return _standpunt_naar_bcf(_standpunt(issue, sp))


def standpunt_maak(guid: str, data: dict) -> dict:
	"""Een BCF 3.0-viewpoint; de schermafbeelding (base64) wordt een privébijlage, de selectie elementen van het issue."""
	issue, project = _issue(guid)
	_vereis_meedoen(project)
	snapshot = _snapshot(data["snapshot"]) if data.get("snapshot") else None
	doc = _nieuw_standpunt(issue, data, snapshot)
	_voeg_elementen_toe(issue, project, (data.get("components") or {}).get("selection"))
	return _standpunt_naar_bcf(doc)


def _nieuw_standpunt(issue, data: dict, snapshot: tuple[bytes, str] | None):
	naam = _nieuwe_guid(data.get("guid"), STANDPUNT)
	doc = frappe.get_doc(
		{
			"doctype": STANDPUNT,
			"guid": naam,
			"issue": issue.name,
			"bcf_index": cint(data.get("index")),
			"standpunt": json.dumps({k: data[k] for k in STANDPUNT_VELDEN if data.get(k) is not None}),
		}
	)
	bestand = None
	if snapshot:
		inhoud, soort = snapshot
		bestand = frappe.get_doc(
			{"doctype": "File", "file_name": f"{naam}.{soort}", "content": inhoud, "is_private": 1}
		).insert(ignore_permissions=True)
		doc.snapshot, doc.snapshot_type = bestand.file_url, soort
	doc.insert(ignore_permissions=True)
	if bestand:
		bestand.db_set({"attached_to_doctype": STANDPUNT, "attached_to_name": naam, "attached_to_field": "snapshot"})
	return doc


def snapshot(guid: str, sp: str) -> tuple[bytes, str]:
	issue, _project_doc = _issue(guid)
	doc = _standpunt(issue, sp)
	inhoud = _snapshot_inhoud(doc)
	if inhoud is None:
		frappe.throw(_("Dit standpunt heeft geen schermafbeelding."), frappe.DoesNotExistError)
	return inhoud, SNAPSHOT_SOORTEN[doc.snapshot_type][1]


def _snapshot_inhoud(doc) -> bytes | None:
	bestand = frappe.db.get_value("File", {"file_url": doc.snapshot}, "name") if doc.snapshot else None
	if not bestand:
		return None
	# File.get_content() probeert ook binaire inhoud als tekst te lezen; de bytes rechtstreeks van schijf.
	with open(frappe.get_doc("File", bestand).get_full_path(), "rb") as f:
		return f.read()


def standpunt_verwijder(guid: str, sp: str) -> None:
	issue, project = _issue(guid)
	doc = _standpunt(issue, sp)
	_vereis_meedoen(project)
	if doc.owner != _gebruiker() and not _mag_wijzigen(issue, project):
		frappe.throw(_("Alleen de maker van een standpunt of van het issue mag het verwijderen."), frappe.PermissionError)
	for reactie in frappe.get_all(REACTIE, {"issue": guid, "standpunt": doc.name}, pluck="name"):
		frappe.db.set_value(REACTIE, reactie, "standpunt", None)
	frappe.delete_doc(STANDPUNT, doc.name, ignore_permissions=True)


# --- verwante issues en documentverwijzingen ---


def verwante(guid: str) -> list[dict]:
	issue, _project_doc = _issue(guid)
	return [
		{"related_topic_guid": g} for g in _json(issue.verwante_issues) or [] if frappe.db.exists(ISSUE, g)
	]


def verwante_zet(guid: str, guids: list[str]) -> list[dict]:
	issue, project = _issue(guid)
	_vereis_wijzigen(issue, project)
	guids = list(dict.fromkeys(str(g) for g in guids))
	for g in guids:
		if g == guid or frappe.db.get_value(ISSUE, g, "project") != project.name:
			_weiger(_("{0} is geen ander issue in dit project.").format(g), "issue_onbekend")
	issue.verwante_issues = json.dumps(guids)
	issue.save(ignore_permissions=True)
	return verwante(guid)


def documentverwijzingen(guid: str) -> list[dict]:
	issue, _project_doc = _issue(guid)
	return _json(issue.documentverwijzingen) or []


def documentverwijzing_maak(guid: str, data: dict) -> dict:
	issue, project = _issue(guid)
	_vereis_wijzigen(issue, project)
	if not data.get("url") and not data.get("document_guid"):
		_weiger(_("Een documentverwijzing heeft een url of een document_guid nodig."), "verwijzing_leeg")
	verwijzing = {
		"guid": str(uuid.uuid4()),
		"url": data.get("url"),
		"document_guid": data.get("document_guid"),
		"description": data.get("description"),
	}
	verwijzing = {k: v for k, v in verwijzing.items() if v is not None}
	issue.documentverwijzingen = json.dumps([*(_json(issue.documentverwijzingen) or []), verwijzing])
	issue.save(ignore_permissions=True)
	return verwijzing


def documentverwijzing_wijzig(guid: str, verwijzing: str, data: dict) -> dict:
	"""Vervang url, document_guid en beschrijving van een documentverwijzing (zoals PUT in de BCF-API)."""
	issue, project = _issue(guid)
	_vereis_wijzigen(issue, project)
	lijst = _json(issue.documentverwijzingen) or []
	index = next((i for i, v in enumerate(lijst) if v.get("guid") == verwijzing), None)
	if index is None:
		frappe.throw(_("Documentverwijzing bestaat niet"), frappe.DoesNotExistError)
	if not data.get("url") and not data.get("document_guid"):
		_weiger(_("Een documentverwijzing heeft een url of een document_guid nodig."), "verwijzing_leeg")
	nieuw = {"guid": verwijzing, **{k: data[k] for k in ("url", "document_guid", "description") if data.get(k) is not None}}
	lijst[index] = nieuw
	issue.documentverwijzingen = json.dumps(lijst)
	issue.save(ignore_permissions=True)
	return nieuw


# --- .bcfzip: import en export ---

MAX_BCFZIP_BYTES = 512 * 1024 * 1024
ONVEILIG_IN_NAAM = re.compile(r'[\\/:*?"<>|]+')


def _lees_bestand(bestand: str) -> bytes:
	"""De huidige versie van een Storage-bestand, na de leescontrole."""
	doc = api._bestand(bestand)
	rij = frappe.db.get_value(
		"Bestandsversie",
		{"bestand": doc.name, "volgnummer": cint(doc.huidige_versie)},
		["s3_sleutel", "grootte"],
		as_dict=True,
	)
	if not rij:
		frappe.throw(_("Versie bestaat niet"), frappe.DoesNotExistError)
	if cint(rij.grootte) > MAX_BCFZIP_BYTES:
		_weiger(_("Dit BCF-bestand is groter dan 512 MB."), "bcfzip_te_groot")
	return afgeleid.lees_object(rij.s3_sleutel)


def _vul_instellingen_aan(project, topics: list[dict]) -> None:
	"""Waarden uit de topics die een gevulde keuzelijst van het project niet kent, komen erbij (een lege lijst laat
	alles toe en blijft leeg); in het auditlog als `instellingen aangevuld`."""
	aangevuld = False
	for bcf_veld, veld in (*KEUZELIJSTEN.items(), ("labels", "labels")):
		bestaand = _regels(project.get(veld))
		if not bestaand:
			continue
		if bcf_veld == "labels":
			waarden = [label for t in topics for label in t.get("labels") or []]
		else:
			waarden = [t.get(bcf_veld) for t in topics]
		nieuw = [w for w in dict.fromkeys(str(w).strip() for w in waarden if w) if w and w not in bestaand]
		if nieuw:
			project.set(veld, "\n".join(bestaand + nieuw))
			aangevuld = True
	if aangevuld:
		project.flags.bim_handeling = "instellingen aangevuld"
		project.save(ignore_permissions=True)


def _verwijzingen(topic: dict) -> list[dict]:
	return [
		{k: v[k] for k in ("guid", "url", "document_guid", "description") if v.get(k) is not None}
		for v in topic.get("document_references") or []
		if v.get("url") or v.get("document_guid")
	]


def _toewijzing(project, data: dict, telling: dict) -> None:
	"""Een toewijzing aan iemand die het project niet kan zien, vervalt bij de import."""
	from openaec_storage.rechten import mag_op_plek

	gebruiker = data.get("assigned_to")
	if gebruiker and (
		not frappe.db.exists("User", gebruiker)
		or not mag_op_plek(project.ruimte, project.modelmap, "read", gebruiker=gebruiker)
	):
		data["assigned_to"] = None
		telling["toewijzingen_vervallen"] += 1


def _ouder_dan_opgeslagen(datum: str | None, opgeslagen) -> bool:
	"""Is de datum uit het bestand ouder dan de opgeslagen wijziging? Dan zou de import een nieuwere stand
	terugdraaien. Zonder datum in het bestand is het niet te zeggen: dan niet."""
	if not datum:
		return False
	try:
		return _tijdstip(datum) < _op_milliseconde(get_datetime(opgeslagen).replace(tzinfo=_tijdzone()))
	except frappe.ValidationError:
		return False


def _importeer_reacties(issue, topic: dict) -> None:
	for r in topic.get("comments") or []:
		data = {"comment": r.get("comment") or "", "viewpoint_guid": r.get("viewpoint_guid")}
		if data["viewpoint_guid"] and frappe.db.get_value(STANDPUNT, data["viewpoint_guid"], "issue") != issue.name:
			data["viewpoint_guid"] = None
		if not data["comment"].strip():
			continue
		bestaand = frappe.db.get_value(REACTIE, r["guid"], ["issue", "tekst"], as_dict=True) if r.get("guid") else None
		if bestaand is None:
			_nieuwe_reactie(issue, {"guid": r.get("guid"), **data}, r.get("author"), r.get("date"), "geïmporteerd")
		elif bestaand.issue == issue.name and bestaand.tekst != data["comment"]:
			doc = frappe.get_doc(REACTIE, r["guid"])
			if _ouder_dan_opgeslagen(r.get("modified_date") or r.get("date"), doc.modified):
				continue
			_zet_reactie(doc, issue, data)
			doc.flags.bim_handeling = "geïmporteerd"
			doc.save(ignore_permissions=True)


def _importeer_topic(project, topic: dict, telling: dict) -> tuple[str, list[dict]] | None:
	try:
		guid = str(uuid.UUID(str(topic.get("guid"))))
	except ValueError:
		telling["overgeslagen"] += 1
		return None
	elders = frappe.db.get_value(ISSUE, guid, "project")
	if elders and elders != project.name:
		telling["overgeslagen"] += 1
		return None
	data = {k: topic[k] for k in TOPIC_VELDEN if k in topic}
	data["title"] = (topic.get("title") or "").strip() or _("(zonder titel)")
	_toewijzing(project, data, telling)
	if elders:
		issue = frappe.get_doc(ISSUE, guid, for_update=True)
		verouderd = _ouder_dan_opgeslagen(topic.get("modified_date") or topic.get("creation_date"), issue.modified)
		telling["verouderd" if verouderd else "bijgewerkt"] += 1
	else:
		verouderd = False
		issue = frappe.get_doc({"doctype": ISSUE, "guid": guid, "project": project.name, "status": project.standaard_status})
		telling["nieuw"] += 1
	if not verouderd:
		# Een oudere stand uit het bestand draait een latere wijziging hier niet terug; nieuwe reacties en
		# standpunten uit het bestand komen er wel bij.
		_van_bcf(data, issue, project)
		issue.documentverwijzingen = json.dumps(_verwijzingen(topic))
	issue.flags.bim_handeling = "geïmporteerd"
	if elders:
		if not verouderd:
			issue.save(ignore_permissions=True)
	else:
		issue.insert(ignore_permissions=True)
		_zet_herkomst(issue, topic.get("creation_author"), topic.get("creation_date"))

	selectie = []
	for sp in topic.get("viewpoints") or []:
		if sp.get("guid") and not frappe.db.exists(STANDPUNT, sp["guid"]):
			_nieuw_standpunt(issue, sp, _snapshot_of_niets(sp.get("snapshot")))
			selectie += (sp.get("components") or {}).get("selection") or []
	_importeer_reacties(issue, topic)
	return guid, selectie


def _als_kopie(topic: dict) -> dict:
	"""Het topic met nieuwe guids voor zichzelf, zijn standpunten en reacties (en de verwijzingen daartussen)."""
	kopie = copy.deepcopy(topic)
	kopie["guid"] = str(uuid.uuid4())
	standpunten_ = {}
	for sp in kopie.get("viewpoints") or []:
		standpunten_[sp.get("guid")] = sp["guid"] = str(uuid.uuid4())
	for r in kopie.get("comments") or []:
		r["guid"] = str(uuid.uuid4())
		if r.get("viewpoint_guid"):
			r["viewpoint_guid"] = standpunten_.get(r["viewpoint_guid"])
	return kopie


def importeer(project, bestand: str) -> dict:
	"""Lees een .bcfzip (2.1 of 3.0) uit Storage in het project: een bekende guid wordt bijgewerkt, een nieuwe gemaakt,
	met de maker en datums uit het bestand; een topic dat hier na de datum in het bestand gewijzigd is, blijft staan
	(`verouderd`). Een topic dat al in een ander project staat, komt erin als kopie met een nieuwe guid. Alleen voor wie
	schrijfrecht op de modelmap heeft."""
	project = _project(project)
	_vereis_meedoen(project)
	if not _schrijver(project):
		frappe.throw(_("Alleen wie in de modelmap mag schrijven, kan issues importeren."), frappe.PermissionError)
	try:
		topics = bcfzip.lees(_lees_bestand(bestand))
	except bcfzip.BcfOngeldig as fout:
		_weiger(_("Dit is geen leesbaar BCF-bestand: {0}").format(fout), "bcfzip_ongeldig")
	_vul_instellingen_aan(project, topics)
	telling = {"nieuw": 0, "bijgewerkt": 0, "verouderd": 0, "gekopieerd": 0, "overgeslagen": 0, "toewijzingen_vervallen": 0}
	verwant: dict[str, list[str]] = {}
	selecties: dict[str, list[dict]] = {}
	kopieen: dict[str, str] = {}
	for topic in topics:
		elders = frappe.db.get_value(ISSUE, topic.get("guid"), "project") if topic.get("guid") else None
		if elders and elders != project.name:
			kopie = _als_kopie(topic)
			kopieen[str(topic["guid"])] = kopie["guid"]
			topic = kopie
			telling["gekopieerd"] += 1
		uitkomst = _importeer_topic(project, topic, telling)
		if uitkomst:
			guid, selecties[guid] = uitkomst
			verwant[guid] = [r.get("related_topic_guid") for r in topic.get("related_topics") or []]
	# De elementen van alle topics in één keer opzoeken: één vraag aan de kern per model, niet per topic.
	globalids = sorted({g for guid, sel in selecties.items() for g in _nieuwe_globalids(frappe.get_doc(ISSUE, guid), sel)})
	plekken = zoek_elementen(project, globalids) if globalids else {}
	for guid, selectie in selecties.items():
		_voeg_elementen_toe(frappe.get_doc(ISSUE, guid), project, selectie, plekken)
	# Verwante issues pas na alle topics: ze kunnen later in hetzelfde bestand staan.
	for guid, guids in verwant.items():
		geldig = [
			g
			for g in dict.fromkeys(kopieen.get(str(g), g) for g in guids)
			if g and g != guid and frappe.db.get_value(ISSUE, g, "project") == project.name
		]
		issue = frappe.get_doc(ISSUE, guid)
		if (_json(issue.verwante_issues) or []) != geldig:
			issue.verwante_issues = json.dumps(geldig)
			issue.flags.bim_handeling = "geïmporteerd"
			issue.save(ignore_permissions=True)
	return telling


def _topic_voor_bestand(issue, project) -> dict:
	topic = _naar_bcf(issue, project)
	topic.pop("authorization")
	topic.pop("elementen")
	reacties_ = []
	for naam in frappe.get_all(REACTIE, {"issue": issue.name}, pluck="name", order_by="creation asc"):
		r = _reactie_naar_bcf(frappe.get_doc(REACTIE, naam), issue, project)
		reacties_.append({k: v for k, v in r.items() if k not in ("authorization", "topic_guid")})
	standpunten_ = []
	for naam in frappe.get_all(STANDPUNT, {"issue": issue.name}, pluck="name", order_by="creation asc"):
		doc = frappe.get_doc(STANDPUNT, naam)
		sp = _standpunt_naar_bcf(doc)
		inhoud = _snapshot_inhoud(doc)
		sp["snapshot"] = (
			{"snapshot_type": doc.snapshot_type, "snapshot_data": base64.b64encode(inhoud).decode()} if inhoud else None
		)
		standpunten_.append(sp)
	verwant = [g for g in _json(issue.verwante_issues) or [] if frappe.db.exists(ISSUE, g)]
	return {
		**topic,
		"comments": reacties_,
		"viewpoints": standpunten_,
		"related_topics": [{"related_topic_guid": g} for g in verwant],
		"document_references": _json(issue.documentverwijzingen) or [],
	}


def _zet_in_storage(ruimte: str, map_: str, naam: str, inhoud: bytes) -> str:
	"""Een bestand in Storage zetten met dezelfde stappen als een upload van een klein bestand (rechten, naam,
	mapsjabloon, quotum), maar zonder de grens van 1 MiB: een export met schermafbeeldingen is vaak groter."""
	from openaec_storage import api as opslag
	from openaec_storage import mapsjablonen, s3
	from openaec_storage.rechten import vereis_op_plek

	bestaand = opslag._actief_bestand(ruimte, map_, naam)
	vereis_op_plek(ruimte, map_, "write", bestaand.name if bestaand else None)
	naam = opslag._controleer_naam(naam, ruimte, map_)
	mapsjablonen.controleer_upload(ruimte, map_, naam)
	opslag._controleer_quotum(len(inhoud), ruimte)
	sleutel = s3.nieuwe_sleutel()
	s3.zet(sleutel, inhoud)
	try:
		uit = opslag._registreer(
			{
				"ruimte": ruimte,
				"map": map_,
				"naam": naam,
				"grootte": len(inhoud),
				"basis_versie": cint(bestaand.huidige_versie) if bestaand else None,
				"sha256": hashlib.sha256(inhoud).hexdigest(),
				"bron": "api",
				"sleutel": sleutel,
				"blokgrootte": s3.blokgrootte(len(inhoud)),
				"blokhashes": None,
			}
		)
	except Exception:
		s3.verwijder(sleutel)
		raise
	return uit["bestand"]


def exporteer_zip(project, versie: str) -> dict:
	"""Alle issues van het project als `<titel> issues <datum>.bcfzip` in de modelmap (BCF 2.1 of 3.0)."""
	project = _project(project)
	_vereis_lezen(project)
	if versie not in ("2.1", "3.0"):
		_weiger(_("Kies BCF 2.1 of 3.0."), "versie_onbekend")
	topics = [
		_topic_voor_bestand(frappe.get_doc(ISSUE, naam), project)
		for naam in frappe.get_all(ISSUE, {"project": project.name}, pluck="name", order_by="creation asc")
	]
	inhoud = bcfzip.schrijf(topics, versie, uitbreidingen=uitbreidingen(project))
	titel = ONVEILIG_IN_NAAM.sub("-", project.titel or project.name).strip(" .-") or "project"
	naam = f"{titel} issues {today()}.bcfzip"
	return {"bestand": _zet_in_storage(project.ruimte, project.modelmap, naam, inhoud)}
