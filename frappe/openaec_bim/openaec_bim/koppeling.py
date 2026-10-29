"""Versiekoppeling: na elke nieuwe omgezette versie van een IFC-bestand koppelt de BIM-kern haar elementen aan de vorige
omgezette versie, op GlobalId en met een terugval op plaats en naam (ontwerp 5.3). Issues en botsingen volgen zo hun
elementen naar de versie die het project toont, ook als een exporteur GlobalIds verandert.
"""

import functools
import json

import frappe
from frappe import _
from frappe.utils import cint, flt

from openaec_bim import afgeleid, kern

DOCTYPE = "BIM Versiekoppeling"


def _bron(omzetting) -> dict:
	"""Een kortlevend leesadres van de eigenschappen-index van een omzetting, met de sha256 voor de cache van de kern."""
	return {
		"url": afgeleid.leesadres(f"{omzetting.prefix}/eigenschappen.sqlite", afgeleid.GELDIG_BRON),
		"sha256": afgeleid.eigenschappen_sha256(omzetting),
	}


def start(bestand: str, van_versie: int, naar_versie: int):
	doc = frappe.get_doc(
		{"doctype": DOCTYPE, "bestand": bestand, "van_versie": van_versie, "naar_versie": naar_versie, "status": "wacht"}
	).insert(ignore_permissions=True)
	try:
		doc.kern_taak = kern.start_koppelen(
			_bron(afgeleid.laatste(bestand, van_versie)), _bron(afgeleid.laatste(bestand, naar_versie))
		)
	except kern.KernFout as fout:
		doc.status = "fout"
		doc.fout = json.dumps({"error_code": fout.code, "melding": str(fout)})
	doc.save(ignore_permissions=True)
	return doc


def na_omzetting(omzetting) -> None:
	"""Een versie is klaar: koppel haar aan de vorige omgezette versie van hetzelfde bestand, als die er is."""
	versie = cint(omzetting.versie)
	vorige = frappe.db.get_value(
		afgeleid.DOCTYPE,
		{"bestand": omzetting.bestand, "status": "klaar", "versie": ("<", versie)},
		"versie",
		order_by="versie desc",
	)
	if not vorige:
		return
	if frappe.db.exists(DOCTYPE, {"bestand": omzetting.bestand, "naar_versie": versie, "status": ("!=", "fout")}):
		return
	start(omzetting.bestand, cint(vorige), versie)


def bijwerken(doc) -> None:
	"""De stand van een lopende koppeling bij de kern ophalen."""
	if doc.status not in ("wacht", "bezig") or not doc.kern_taak:
		return
	try:
		taak = kern.taak(doc.kern_taak)
	except kern.KernFout as fout:
		if fout.code != "taak_onbekend":
			return  # de kern is even weg: later opnieuw
		taak = {"status": "fout", "fout": {"error_code": "taak_onbekend", "melding": str(fout)}}
	status = taak.get("status")
	if status in ("wacht", "bezig"):
		doc.status = status
	elif status == "klaar":
		uitkomst = taak.get("uitkomst") or {}
		doc.matchrate = flt(uitkomst.get("matchrate"))
		doc.elementen_vorige = cint(uitkomst.get("elementen_vorige"))
		doc.op_globalid = cint(uitkomst.get("op_globalid"))
		doc.terugval = json.dumps(uitkomst.get("terugval") or [])
		doc.niet_gevonden = json.dumps(uitkomst.get("niet_gevonden") or [])
		doc.status = "klaar"
	else:
		doc.status = "fout"
		doc.fout = json.dumps(taak.get("fout") or {"error_code": status or "onbekend", "melding": _("De koppeling is gestopt.")})
	doc.save(ignore_permissions=True)


def volg_lopende() -> None:
	for naam in frappe.get_all(DOCTYPE, filters={"status": ("in", ("wacht", "bezig"))}, pluck="name"):
		bijwerken(frappe.get_doc(DOCTYPE, naam))
		frappe.db.commit()


def naar(bestand: str, versie: int) -> dict | None:
	"""De klare koppeling naar deze versie, als `{vorige_versie, matchrate}` (voor de viewer)."""
	rij = frappe.db.get_value(
		DOCTYPE,
		{"bestand": bestand, "naar_versie": cint(versie), "status": "klaar"},
		["van_versie", "matchrate"],
		as_dict=True,
		order_by="creation desc",
	)
	return {"vorige_versie": str(rij.van_versie), "matchrate": flt(rij.matchrate)} if rij else None


@functools.lru_cache(maxsize=64)
def _kaart(site: str, naam: str) -> tuple[dict[str, str], frozenset[str]]:
	"""Terugval en niet gevonden van een klare koppeling; die veranderen niet meer (per site: een proces bedient er
	meer)."""
	terugval, niet_gevonden = frappe.db.get_value(DOCTYPE, naam, ["terugval", "niet_gevonden"])
	return (
		{p["van"]: p["naar"] for p in json.loads(terugval or "[]")},
		frozenset(json.loads(niet_gevonden or "[]")),
	)


def huidig(bestand: str, globalid: str, van_versie: int, naar_versie: int) -> str | None:
	"""De GlobalId van dit element in een latere versie, langs de keten van klare koppelingen; None als het element
	onderweg niet is teruggevonden of de keten nog niet compleet is."""
	versie, naar_versie = cint(van_versie), cint(naar_versie)
	while versie < naar_versie:
		stap = frappe.db.get_value(
			DOCTYPE,
			{"bestand": bestand, "van_versie": versie, "naar_versie": ("<=", naar_versie), "status": "klaar"},
			["name", "naar_versie"],
			as_dict=True,
			order_by="naar_versie desc",
		)
		if not stap:
			return None
		terugval, niet_gevonden = _kaart(frappe.local.site, stap.name)
		if globalid in niet_gevonden:
			return None
		globalid = terugval.get(globalid, globalid)
		versie = cint(stap.naar_versie)
	return globalid if versie == naar_versie else None
