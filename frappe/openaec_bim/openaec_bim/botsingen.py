"""Botsingsrondes: een botsingscontrole door de BIM-kern tussen twee sets modellen van een project.

Een ronde legt bij de start de versies vast die ze gebruikt (de versie die het project toont), zodat een nieuwe versie
tijdens de ronde niets verandert. Een volgende ronde met dezelfde sets volgt de botsingen van de vorige via de
versiekoppeling: een paar dat terugkomt houdt zijn status (genegeerd blijft genegeerd, opgelost wordt weer actief) en
zijn issue; een paar dat niet meer voorkomt, komt als opgelost in de nieuwe ronde.
"""

import json
import math

import frappe
from frappe import _
from frappe.utils import cint, flt, now_datetime

from openaec_bim import afgeleid, api, issues, kern, koppeling

RONDE = "BIM Botsingsronde"
BOTSING = "BIM Botsing"
SOORTEN = ("hard", "afstand")
STATUSSEN = ("nieuw", "actief", "opgelost", "genegeerd")
VELDEN = ("ronde", "sleutel", "element_a", "element_b", "punt", "afstand", "status", "issue", "groep")


def _weiger(melding: str, foutcode: str, uitzondering=frappe.ValidationError):
	from openaec_storage.rechten import weiger

	weiger(melding, foutcode, uitzondering)


def _vereis_schrijver(project) -> None:
	issues._vereis_meedoen(project)
	if not issues._schrijver(project):
		frappe.throw(_("Alleen wie in de modelmap mag schrijven, kan botsingen beheren."), frappe.PermissionError)


def _set(items, modellen: dict) -> list[dict]:
	"""Een set als `[{bestand, klassen}]`, op volgorde van bestand; elk bestand is een IFC in de modelmap."""
	uit = []
	for item in items or []:
		bestand = item.get("bestand") if isinstance(item, dict) else item
		if bestand not in modellen:
			_weiger(_("{0} is geen model in dit project.").format(bestand), "model_onbekend")
		klassen = sorted({str(k) for k in (item.get("klassen") if isinstance(item, dict) else None) or []}) or None
		uit.append({"bestand": bestand, "klassen": klassen})
	if not uit:
		_weiger(_("Een set heeft minstens één model nodig."), "set_leeg")
	return sorted(uit, key=lambda m: m["bestand"])


def _json(waarde) -> str:
	return json.dumps(waarde, sort_keys=True)


def start(project, set_a, set_b, soort: str, tolerantie: float, titel: str | None = None) -> str:
	"""Start een ronde op de versies die het project nu toont; geeft de naam van de ronde."""
	project = issues._project(project)
	_vereis_schrijver(project)
	if soort not in SOORTEN:
		_weiger(_("Kies hard of afstand."), "soort_onbekend")
	tolerantie = flt(tolerantie)
	if not 0 <= tolerantie <= 1:
		_weiger(_("De tolerantie ligt tussen 0 en 1 m."), "tolerantie_ongeldig")
	map_doc = frappe.db.get_value("Opslagmap", project.modelmap, ["name", "ruimte", "naam"], as_dict=True)
	modellen = {b.name: b for b, _discipline in api.ifc_in_map(map_doc)}
	set_a, set_b = _set(set_a, modellen), _set(set_b, modellen)
	versies = {}
	for item in set_a + set_b:
		versie = afgeleid.getoonde_versie(item["bestand"])
		if not versie:
			_weiger(_("{0} is nog niet omgezet.").format(modellen[item["bestand"]].naam), "model_niet_omgezet")
		versies[item["bestand"]] = str(versie)
	vorige = frappe.db.get_value(
		RONDE,
		{"project": project.name, "status": "klaar", "soort": soort, "set_a": _json(set_a), "set_b": _json(set_b)},
		"name",
		order_by="creation desc",
	)
	doc = frappe.get_doc(
		{
			"doctype": RONDE,
			"project": project.name,
			"titel": titel or _("Botsingen {0}").format(now_datetime().strftime("%Y-%m-%d %H:%M")),
			"set_a": _json(set_a),
			"set_b": _json(set_b),
			"soort": soort,
			"tolerantie": tolerantie,
			"status": "wacht",
			"bron_versies": _json(versies),
			"vorige_ronde": vorige,
		}
	).insert(ignore_permissions=True)
	doc.resultaat = afgeleid._s3()._met_prefix(f"bim/botsingen/{doc.name}.json")

	def kern_set(items):
		return [
			{
				"sleutel": m["bestand"],
				"versie": versies[m["bestand"]],
				"bron": afgeleid.bron(m["bestand"], cint(versies[m["bestand"]])),
				"klassen": m["klassen"],
			}
			for m in items
		]

	try:
		doc.kern_taak = kern.start_botsingen(
			kern_set(set_a), kern_set(set_b), soort, tolerantie, afgeleid.schrijfadres(doc.resultaat, afgeleid.GELDIG_DOEL)
		)
	except kern.KernFout as fout:
		doc.status = "fout"
		doc.fout = json.dumps({"error_code": fout.code, "melding": str(fout)})
	doc.save(ignore_permissions=True)
	return doc.name


def bijwerken(doc) -> None:
	"""De stand van een lopende ronde bij de kern ophalen; bij klaar de botsingen inlezen."""
	if doc.status not in ("wacht", "bezig") or not doc.kern_taak:
		return
	try:
		taak = kern.taak(doc.kern_taak)
	except kern.KernFout as fout:
		if fout.code != "taak_onbekend":
			return
		taak = {"status": "fout", "fout": {"error_code": "taak_onbekend", "melding": str(fout)}}
	status = taak.get("status")
	if status == "klaar":
		verwerk(doc.name)
		doc.reload()
		return
	if status in ("wacht", "bezig"):
		if doc.status == status:
			return
		doc.status = status
	else:
		doc.status = "fout"
		doc.fout = json.dumps(taak.get("fout") or {"error_code": status or "onbekend", "melding": _("De ronde is gestopt.")})
	doc.save(ignore_permissions=True)


def volg_lopende() -> None:
	for naam in frappe.get_all(RONDE, filters={"status": ("in", ("wacht", "bezig"))}, pluck="name"):
		bijwerken(frappe.get_doc(RONDE, naam))
		frappe.db.commit()


def _sleutel(a: dict, b: dict) -> str:
	return "|".join(sorted((f"{a['bestand']}:{a['globalid']}", f"{b['bestand']}:{b['globalid']}")))


def _element(ref: dict) -> dict:
	return {"bestand": ref["sleutel"], "versie": str(ref["versie"]), "globalid": ref["globalid"]}


def _gevolgd(element: dict, versies: dict) -> dict | None:
	"""Het element in de versie van deze ronde, langs de versiekoppeling; None als het niet is teruggevonden."""
	naar = cint(versies.get(element["bestand"], element["versie"]))
	globalid = koppeling.huidig(element["bestand"], element["globalid"], cint(element["versie"]), naar)
	return None if globalid is None else {"bestand": element["bestand"], "versie": str(naar), "globalid": globalid}


def _vorige(doc, versies: dict) -> dict[str, tuple[dict, dict, dict]]:
	"""De botsingen van de vorige ronde op de sleutel die ze in deze ronde zouden hebben: (rij, a, b)."""
	if not doc.vorige_ronde:
		return {}
	uit = {}
	for rij in frappe.get_all(BOTSING, {"ronde": doc.vorige_ronde}, ["name", *VELDEN], order_by="creation asc"):
		a, b = json.loads(rij.element_a), json.loads(rij.element_b)
		nieuw_a, nieuw_b = _gevolgd(a, versies), _gevolgd(b, versies)
		if nieuw_a and nieuw_b:
			uit[_sleutel(nieuw_a, nieuw_b)] = (rij, nieuw_a, nieuw_b)
		else:
			uit[f"weg:{rij.sleutel}"] = (rij, a, b)  # een element is verdwenen: de botsing is opgelost
	return uit


def verwerk(ronde: str) -> None:
	"""Lees de botsingen van de kern in en volg ze ten opzichte van de vorige ronde met dezelfde sets."""
	doc = frappe.get_doc(RONDE, ronde)
	versies = json.loads(doc.bron_versies)
	vorige = _vorige(doc, versies)
	rijen: dict[str, dict] = {}
	for ruw in json.loads(afgeleid.lees_object(doc.resultaat)):
		a, b = _element(ruw["a"]), _element(ruw["b"])
		sleutel = _sleutel(a, b)
		if sleutel in rijen:
			continue
		eerder = vorige.get(sleutel)
		status = "nieuw" if eerder is None else ("genegeerd" if eerder[0].status == "genegeerd" else "actief")
		rijen[sleutel] = {
			"sleutel": sleutel,
			"element_a": a,
			"element_b": b,
			"punt": [round(flt(x), 4) for x in ruw.get("punt") or []],
			"afstand": flt(ruw.get("afstand")),
			"status": status,
			"issue": eerder[0].issue if eerder else None,
			"groep": f"{ruw['a'].get('klasse') or '?'} × {ruw['b'].get('klasse') or '?'}",
		}
	aantal = len(rijen)
	for sleutel, (rij, a, b) in vorige.items():
		if sleutel not in rijen:
			rijen[sleutel] = {
				"sleutel": _sleutel(a, b),
				"element_a": a,
				"element_b": b,
				"punt": json.loads(rij.punt or "[]"),
				"afstand": rij.afstand,
				"status": "opgelost",
				"issue": rij.issue,
				"groep": rij.groep,
			}
	nu, gebruiker = now_datetime(), frappe.session.user
	velden = ["name", "creation", "modified", "owner", "modified_by", *VELDEN]
	waarden = []
	for r in rijen.values():
		waarden.append(
			(
				frappe.generate_hash(length=10),
				nu,
				nu,
				gebruiker,
				gebruiker,
				ronde,
				r["sleutel"],
				json.dumps(r["element_a"]),
				json.dumps(r["element_b"]),
				json.dumps(r["punt"]),
				r["afstand"],
				r["status"],
				r["issue"],
				r["groep"],
			)
		)
	frappe.db.bulk_insert(BOTSING, velden, waarden)
	doc.aantal = aantal
	doc.status = "klaar"
	doc.save(ignore_permissions=True)


def _project_van(botsing):
	return issues._project(frappe.db.get_value(RONDE, botsing.ronde, "project"))


def naar_json(botsing) -> dict:
	return {
		"naam": botsing.name,
		"ronde": botsing.ronde,
		"sleutel": botsing.sleutel,
		"element_a": json.loads(botsing.element_a or "null"),
		"element_b": json.loads(botsing.element_b or "null"),
		"punt": json.loads(botsing.punt or "null"),
		"afstand": flt(botsing.afstand),
		"status": botsing.status,
		"issue": botsing.issue,
		"groep": botsing.groep,
	}


def zet_status(botsing: str, status: str) -> dict:
	doc = frappe.get_doc(BOTSING, botsing)
	_vereis_schrijver(_project_van(doc))
	if status not in STATUSSEN:
		_weiger(_("Onbekende status {0}.").format(status), "status_onbekend")
	doc.status = status
	doc.save(ignore_permissions=True)
	return naar_json(doc)


def _camera(punt: list[float]) -> dict:
	"""Een perspectief dat schuin van boven op het botspunt kijkt, op een paar meter afstand."""
	x, y, z = (list(punt) + [0.0, 0.0, 0.0])[:3]
	oog = (x + 4.0, y - 4.0, z + 3.0)
	richting = (x - oog[0], y - oog[1], z - oog[2])
	lengte = math.sqrt(sum(c * c for c in richting))
	return {
		"camera_view_point": dict(zip("xyz", oog, strict=True)),
		"camera_direction": dict(zip("xyz", (c / lengte for c in richting), strict=True)),
		"camera_up_vector": {"x": 0.0, "y": 0.0, "z": 1.0},
		"field_of_view": 60.0,
	}


def naar_issue(botsing: str) -> dict:
	"""Een issue van soort Botsing, met beide elementen en een standpunt op het botspunt."""
	doc = frappe.get_doc(BOTSING, botsing)
	project = _project_van(doc)
	issues._vereis_meedoen(project)
	if doc.issue and frappe.db.exists(issues.ISSUE, doc.issue):
		return issues.topic(doc.issue)
	a, b = json.loads(doc.element_a), json.loads(doc.element_b)
	soorten = issues._regels(project.soorten)
	t = issues.topic_maak(
		project,
		{
			"title": _("Botsing {0}").format(doc.groep or "").strip(),
			"topic_type": "Botsing" if not soorten or "Botsing" in soorten else None,
			"description": _("{0} en {1}, afstand {2} m.").format(a["globalid"], b["globalid"], flt(doc.afstand)),
		},
	)
	issue = frappe.get_doc(issues.ISSUE, t["guid"])
	for e in (a, b):
		issue.append("elementen", {"bestand": e["bestand"], "versie": e["versie"], "globalid": e["globalid"]})
	issue.save(ignore_permissions=True)
	issues.standpunt_maak(
		t["guid"],
		{
			"perspective_camera": _camera(json.loads(doc.punt or "[]")),
			"components": {"selection": [{"ifc_guid": a["globalid"]}, {"ifc_guid": b["globalid"]}]},
		},
	)
	doc.issue = t["guid"]
	doc.save(ignore_permissions=True)
	return issues.topic(t["guid"])
