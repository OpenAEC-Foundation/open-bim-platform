"""Het auditlog: elke wijziging aan een BIM-project, issue, standpunt of reactie wordt een regel in BIM Auditregel.

De bron (de BCF-API, een import, de werkplek) zet de aanroeper in `frappe.flags.bim_bron`; zonder bron is het
`achtergrond`.
"""

import csv
import io
import json

import frappe
from frappe.model import no_value_fields, table_fields
from frappe.utils import cint, flt, now_datetime

DOCTYPE = "BIM Auditregel"
KOP = ("tijd", "gebruiker", "handeling", "doctype", "object", "bron")


def _project(doc) -> str | None:
	if doc.doctype == "BIM Project":
		return doc.name
	if doc.doctype == "BIM Issue":
		return doc.project
	return frappe.db.get_value("BIM Issue", doc.get("issue"), "project")


def _waarde(veldtype: str, waarde):
	"""Eén vorm per veldtype, zodat een document uit het geheugen en dezelfde versie uit de database gelijk zijn."""
	if veldtype in ("Int", "Check"):
		return cint(waarde)
	if veldtype in ("Float", "Currency", "Percent"):
		return flt(waarde)
	if waarde in (None, ""):
		return None
	if veldtype == "JSON" and isinstance(waarde, str):
		return json.loads(waarde)
	if veldtype in ("Date", "Datetime", "Time"):
		return str(waarde)
	return waarde


def _velden(doc) -> dict:
	"""De eigen velden van een document, met de rijen van kindtabellen als lijsten."""
	velden = {}
	for veld in doc.meta.fields:
		if veld.fieldtype in table_fields:
			velden[veld.fieldname] = [_velden(rij) for rij in doc.get(veld.fieldname) or []]
		elif veld.fieldtype not in no_value_fields:
			velden[veld.fieldname] = _waarde(veld.fieldtype, doc.get(veld.fieldname))
	return velden


def _json(waarde) -> str | None:
	return None if waarde is None else json.dumps(waarde, default=str, ensure_ascii=False, sort_keys=True)


def schrijf(handeling: str, doc, voor: dict | None, na: dict | None) -> None:
	frappe.get_doc(
		{
			"doctype": DOCTYPE,
			"tijd": now_datetime(),
			"gebruiker": frappe.session.user,
			"handeling": handeling,
			"doctype_naam": doc.doctype,
			"object": doc.name,
			"project": _project(doc),
			"voor": _json(voor),
			"na": _json(na),
			"bron": frappe.flags.bim_bron or "achtergrond",
		}
	).insert(ignore_permissions=True)


def aangemaakt(doc, method=None):
	schrijf("aangemaakt", doc, None, _velden(doc))


def gewijzigd(doc, method=None):
	vorige = doc.get_doc_before_save()
	if doc.flags.in_insert or vorige is None:
		return
	oud, nieuw = _velden(vorige), _velden(doc)
	anders = [k for k in nieuw if _json(oud.get(k)) != _json(nieuw[k])]
	if anders:
		schrijf("gewijzigd", doc, {k: oud.get(k) for k in anders}, {k: nieuw[k] for k in anders})


def verwijderd(doc, method=None):
	schrijf("verwijderd", doc, _velden(doc), None)


def exporteer(project: str) -> str:
	"""Het auditlog van een project als CSV, oudste regel eerst."""
	uit = io.StringIO()
	schrijver = csv.writer(uit, lineterminator="\n")
	schrijver.writerow(KOP)
	for r in frappe.get_all(
		DOCTYPE,
		{"project": project},
		["tijd", "gebruiker", "handeling", "doctype_naam", "object", "bron"],
		order_by="tijd asc, creation asc",
	):
		schrijver.writerow((r.tijd, r.gebruiker, r.handeling, r.doctype_naam, r.object, r.bron))
	return uit.getvalue()
