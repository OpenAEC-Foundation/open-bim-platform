"""Botsingsrondes: een botsingscontrole door de BIM-kern tussen twee sets modellen van een project.

Een ronde legt bij de start de versies vast die ze gebruikt (de versie die het project toont), zodat een nieuwe versie
tijdens de ronde niets verandert. Een volgende ronde met dezelfde sets volgt de botsingen van de vorige via de
versiekoppeling: een paar dat terugkomt houdt zijn status (genegeerd blijft genegeerd, opgelost wordt weer actief) en
zijn issue; een paar dat niet meer voorkomt, komt als opgelost in de nieuwe ronde.
"""

import hashlib
import json
import math

import frappe
from frappe import _
from frappe.utils import cint, flt, now_datetime

from openaec_bim import afgeleid, api, issues, kern, koppeling

RONDE = "BIM Botsingsronde"
BOTSING = "BIM Botsing"
SOORTEN = ("hard", "afstand", "dubbel")
ERNSTEN = ("klein", "groot", "kritiek")
MAX_CONTROLES = 30
STATUSSEN = ("nieuw", "actief", "bevestigd", "geaccepteerd", "genegeerd", "opgelost")
# De rij botsing doet één taak tegelijk en een ronde kan uren duren: de adressen blijven een dag geldig.
GELDIG = 24 * 3600
VELDEN = (
	"ronde",
	"sleutel",
	"element_a",
	"element_b",
	"punt",
	"afstand",
	"status",
	"issue",
	"groep",
	"soort",
	"regel",
	"emmer",
	"emmer_reden",
	"ernst",
	"categorie",
	"disciplines",
	"verdieping",
	"raster",
	"ruimte",
	"ontwikkeling",
	"nummer",
	"reden",
	"beoordeeld_door",
	"beoordeeld_op",
	"issue_status_voor",
)
EMMERS = ("beoordelen", "contact", "aangrenzend")
GEVONDEN = ("nieuw", "blijft", "terug")
OPEN_STATUSSEN = ("nieuw", "actief", "bevestigd")
# Wat een rij van de vorige ronde aan haar opvolger meegeeft.
BESLISSING = ("reden", "beoordeeld_door", "beoordeeld_op", "issue", "issue_status_voor", "nummer")
DICHTE_STATUSSEN = ("Opgelost", "Gesloten")
MAX_REDEN = 200
MAX_GROEPSACTIE = 500
MAX_WEERGAVEN = 50
MAX_VERLOOP = 20
REGELSOORTEN = ("uit", "hard", "afstand")
MAX_MM = 1000


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


def _controle(controle: dict, modellen: dict) -> dict:
	"""Een controle genormaliseerd en gevalideerd: sets op bestand en klassen gesorteerd, soort en tolerantie in bereik."""
	soort = controle.get("soort")
	if soort not in SOORTEN:
		_weiger(_("Kies hard, afstand of dubbel."), "soort_onbekend")
	tolerantie = flt(controle.get("tolerantie"))
	if not 0 <= tolerantie <= 1:
		_weiger(_("De tolerantie ligt tussen 0 en 1 m."), "tolerantie_ongeldig")
	ernst = controle.get("ernst") or None
	if ernst is not None and ernst not in ERNSTEN:
		_weiger(_("Onbekende ernst {0}.").format(ernst), "ernst_onbekend")
	return {
		"regel": str(controle["regel"])[:140] if controle.get("regel") else None,
		"set_a": _set(controle.get("set_a"), modellen),
		"set_b": _set(controle.get("set_b"), modellen),
		"soort": soort,
		"tolerantie": tolerantie,
		"ernst": ernst,
		"alleen_tussen_modellen": bool(controle.get("alleen_tussen_modellen")),
	}


def _vereniging(sets: list[list[dict]]) -> list[dict]:
	"""De sets van alle controles samen, zonder dubbelen, op volgorde van bestand."""
	uniek = {_json(item): item for items in sets for item in items}
	return sorted(uniek.values(), key=lambda m: (m["bestand"], _json(m["klassen"])))


def start_controles(
	project, controles: list[dict], titel: str | None = None, voorinstelling: str | None = None
) -> str:
	"""Start een ronde met een of meer controles op de versies die het project nu toont; geeft de naam van de ronde."""
	project = issues._project(project)
	_vereis_schrijver(project)
	if not 1 <= len(controles or []) <= MAX_CONTROLES:
		_weiger(_("Een ronde heeft 1 tot {0} controles.").format(MAX_CONTROLES), "controles_aantal")
	map_doc = frappe.db.get_value("Opslagmap", project.modelmap, ["name", "ruimte", "naam"], as_dict=True)
	modellen = {b.name: b for b, _discipline in api.ifc_in_map(map_doc)}
	controles = [_controle(c, modellen) for c in controles]
	set_a = _vereniging([c["set_a"] for c in controles])
	set_b = _vereniging([c["set_b"] for c in controles])
	soorten = {c["soort"] for c in controles}
	soort = soorten.pop() if len(soorten) == 1 else "gemengd"
	versies = {}
	for item in set_a + set_b:
		versie = afgeleid.getoonde_versie(item["bestand"])
		if not versie:
			_weiger(_("{0} is nog niet omgezet.").format(modellen[item["bestand"]].naam), "model_niet_omgezet")
		versies[item["bestand"]] = str(versie)
	voorinstelling = (voorinstelling or "").strip() or None
	reeks = voorinstelling or "sets:" + hashlib.sha1(_json([set_a, set_b, soort]).encode()).hexdigest()
	vorige = frappe.db.get_value(
		RONDE, {"project": project.name, "status": "klaar", "reeks": reeks}, "name", order_by="creation desc"
	)
	doc = frappe.get_doc(
		{
			"doctype": RONDE,
			"project": project.name,
			"titel": titel or f"{voorinstelling or _('Botsingen')} {now_datetime().strftime('%Y-%m-%d %H:%M')}",
			"set_a": _json(set_a),
			"set_b": _json(set_b),
			"soort": soort,
			"regels": _json(sorted(controles, key=_json)),
			"voorinstelling": voorinstelling,
			"reeks": reeks,
			"tolerantie": max(c["tolerantie"] for c in controles),
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
				"bron": afgeleid.bron(m["bestand"], cint(versies[m["bestand"]]), GELDIG),
				"klassen": m["klassen"],
			}
			for m in items
		]

	# De kern leest `regel` als tekst: zonder regel (de snelle keuzes) gaat het veld niet mee.
	kern_controles = [
		{**{k: v for k, v in c.items() if k != "regel" or v}, "set_a": kern_set(c["set_a"]), "set_b": kern_set(c["set_b"])}
		for c in controles
	]
	try:
		doc.kern_taak = kern.start_botsingen(kern_controles, afgeleid.schrijfadres(doc.resultaat, GELDIG))
	except kern.KernFout as fout:
		doc.status = "fout"
		doc.fout = json.dumps({"error_code": fout.code, "melding": str(fout)})
	doc.save(ignore_permissions=True)
	return doc.name


def start(project, set_a, set_b, soort: str, tolerantie: float, titel: str | None = None) -> str:
	"""Start een ronde met één controle op de versies die het project nu toont; geeft de naam van de ronde."""
	controle = {"set_a": set_a, "set_b": set_b, "soort": soort, "tolerantie": tolerantie}
	return start_controles(project, [controle], titel=titel)


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
		if _wacht_op_koppeling(doc):
			# De vorige ronde volgen kan pas als de koppeling er is: anders lijkt elke botsing opgelost.
			if doc.status != "bezig":
				doc.status = "bezig"
				doc.save(ignore_permissions=True)
			return
		verwerk(doc.name)
		doc.reload()
		return
	if status in ("wacht", "bezig"):
		voortgang = flt(taak.get("voortgang"))
		if doc.status == status and flt(doc.voortgang) == voortgang:
			return
		doc.status = status
		doc.voortgang = voortgang
	else:
		doc.status = "fout"
		doc.fout = json.dumps(taak.get("fout") or {"error_code": status or "onbekend", "melding": _("De ronde is gestopt.")})
	doc.save(ignore_permissions=True)


def _werk_bij(doc) -> None:
	"""Eén ronde bijwerken. Een fout blijft bij die ronde: ze krijgt status `fout` met de melding, en de rest gaat door."""
	frappe.db.savepoint("openaec_bim_ronde")
	try:
		afgeleid.zonder_botsing(bijwerken, doc)
	except Exception as fout:
		frappe.db.rollback(save_point="openaec_bim_ronde")
		frappe.log_error(title=f"Botsingsronde {doc.name}")
		doc.reload()
		doc.status = "fout"
		doc.fout = json.dumps({"error_code": "inlezen_mislukt", "melding": str(fout)})
		doc.save(ignore_permissions=True)


def volg_lopende() -> None:
	for naam in frappe.get_all(RONDE, filters={"status": ("in", ("wacht", "bezig"))}, pluck="name"):
		_werk_bij(frappe.get_doc(RONDE, naam))
		frappe.db.commit()


def _sleutel(a: dict, b: dict) -> str:
	return "|".join(sorted((f"{a['bestand']}:{a['globalid']}", f"{b['bestand']}:{b['globalid']}")))


def _element(ref: dict) -> dict:
	uit = {"bestand": ref["sleutel"], "versie": str(ref["versie"]), "globalid": ref["globalid"]}
	for veld in ("klasse", "naam", "verdieping"):
		if ref.get(veld):
			uit[veld] = ref[veld]
	return uit


def _wacht_op_koppeling(doc) -> bool:
	"""Loopt er nog een koppeling tussen de versies van de vorige ronde en die van deze?"""
	if not doc.vorige_ronde:
		return False
	vorige = json.loads(frappe.db.get_value(RONDE, doc.vorige_ronde, "bron_versies") or "{}")
	for bestand, versie in json.loads(doc.bron_versies or "{}").items():
		van = cint(vorige.get(bestand, versie))
		if van < cint(versie) and not koppeling.volg(bestand, "", van, cint(versie))[1]:
			if koppeling.keten_loopt(bestand, van, cint(versie)):
				return True
	return False


def _gevolgd(element: dict, versies: dict) -> dict | None:
	"""Het element in de versie van deze ronde, langs de versiekoppeling; None als het niet is teruggevonden. Is de
	keten blijvend onvolledig (de koppeling is mislukt), dan dezelfde GlobalId: liever dat dan elke botsing opgelost."""
	naar = cint(versies.get(element["bestand"], element["versie"]))
	globalid, compleet = koppeling.volg(element["bestand"], element["globalid"], cint(element["versie"]), naar)
	if not compleet:
		globalid = element["globalid"]
	return None if globalid is None else {**element, "versie": str(naar), "globalid": globalid}


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
		elif rij.status != "opgelost":
			# Een element is verdwenen: de botsing is opgelost. Eén keer meegeven, daarna kan ze niet terugkomen.
			uit[f"weg:{rij.sleutel}"] = (rij, a, b)
	return uit


def _disciplines(project) -> dict[str, str]:
	"""Per modelbestand de discipline: de submap van de modelmap, of anders de bestandsnaam zonder .ifc."""
	if not project.modelmap:
		return {}
	map_doc = frappe.db.get_value("Opslagmap", project.modelmap, ["name", "ruimte", "naam"], as_dict=True)
	uit = {}
	for bestand, discipline in api.ifc_in_map(map_doc):
		naam = bestand.naam or ""
		uit[bestand.name] = discipline or (naam[:-4] if naam.lower().endswith(".ifc") else naam)
	return uit


def _dichte_status(project) -> str:
	"""De dichte status die een issue krijgt als zijn botsing weg is: Opgelost, of anders de laatste van het project."""
	lijst = issues._regels(project.statussen)
	return "Opgelost" if not lijst or "Opgelost" in lijst else lijst[-1]


def _regels_gewijzigd(doc) -> bool:
	if not doc.vorige_ronde:
		return False
	vorige = frappe.db.get_value(RONDE, doc.vorige_ronde, "regels")
	return json.loads(vorige or "null") != json.loads(doc.regels or "null")


def _ontwikkeling(eerder, gevonden: bool) -> tuple[str, str]:
	"""(nieuwe status, ontwikkeling) volgens de overgangstabel; `eerder` is de rij van de vorige ronde of None."""
	if eerder is None:
		return "nieuw", "nieuw"
	if gevonden:
		if eerder.status == "opgelost":
			return "actief", "terug"
		if eerder.status in ("bevestigd", "geaccepteerd", "genegeerd"):
			return eerder.status, "blijft"
		return "actief", "blijft"
	return "opgelost", "eerder_weg" if eerder.status == "opgelost" else "weg"


def _zet_issue(issue: str, status: str, tekst: str) -> None:
	"""Het issue naar een status, met een reactie op naam van de botsingsronde; via het document, dus ook in het log."""
	doc = frappe.get_doc(issues.ISSUE, issue)
	doc.status = status
	doc.save(ignore_permissions=True)
	issues._nieuwe_reactie(doc, {"comment": tekst}, auteur="Botsingsronde")


def _issue_volgt(r: dict, eerder, project, gewijzigd: bool) -> None:
	"""Zet het issue van een rij dicht als haar botsing weg is, en terug als de botsing terugkomt; werkt `r` bij."""
	if not r["issue"]:
		return
	if not frappe.db.exists(issues.ISSUE, r["issue"]):
		r["issue"] = r["issue_status_voor"] = None
		return
	status = frappe.db.get_value(issues.ISSUE, r["issue"], "status")
	dicht = _dichte_status(project)
	if r["ontwikkeling"] == "weg" and not gewijzigd and status not in DICHTE_STATUSSEN:
		r["issue_status_voor"] = status
		_zet_issue(r["issue"], dicht, _("De botsing is in deze ronde niet meer gevonden; het issue is op {0} gezet.").format(dicht))
	elif r["ontwikkeling"] == "terug" and eerder.issue_status_voor:
		if status == dicht:
			_zet_issue(
				r["issue"],
				eerder.issue_status_voor,
				_("De botsing is in deze ronde weer gevonden; het issue is terug op {0}.").format(eerder.issue_status_voor),
			)
		# Is het issue intussen door iemand zelf gewijzigd, dan blijft het zoals het is.
		r["issue_status_voor"] = None


def _samenvatting(rijen: list[dict], gewijzigd: bool) -> dict:
	gevonden = [r for r in rijen if r["ontwikkeling"] in GEVONDEN]
	per_emmer = dict.fromkeys(EMMERS, 0)
	per_categorie: dict[str, int] = {}
	per_status: dict[str, int] = {}
	per_ernst: dict[str, int] = {}
	for r in gevonden:
		per_emmer[r["emmer"]] += 1
		if r["categorie"]:
			per_categorie[r["categorie"]] = per_categorie.get(r["categorie"], 0) + 1
	open_ = [r for r in gevonden if r["emmer"] == "beoordelen" and r["status"] in OPEN_STATUSSEN]
	for r in open_:
		if r["ernst"]:
			per_ernst[r["ernst"]] = per_ernst.get(r["ernst"], 0) + 1
	for r in rijen:
		per_status[r["status"]] = per_status.get(r["status"], 0) + 1
	return {
		"totaal": len(gevonden),
		"per_emmer": per_emmer,
		"per_categorie": per_categorie,
		**{o: sum(1 for r in rijen if r["ontwikkeling"] == o) for o in ("nieuw", "blijft", "terug", "weg")},
		"open": len(open_),
		"per_ernst": per_ernst,
		"per_status": per_status,
		"regels_gewijzigd": gewijzigd,
	}


def _kolomlengtes(doctype: str) -> dict[str, int]:
	"""Per veld dat als varchar bewaard wordt de lengte van de kolom, uit de meta van het doctype."""
	lengtes = {}
	for df in frappe.get_meta(doctype).fields:
		kolom = frappe.db.type_map.get(df.fieldtype)
		if kolom and kolom[0] == "varchar":
			lengtes[df.fieldname] = cint(df.length) or cint(kolom[1])
	return lengtes


def _kort_op_kolom(rij: dict, lengtes: dict[str, int]) -> None:
	"""`bulk_insert` valideert niet en de database weigert wat te lang is: namen uit een model zijn soms langer."""
	for veld, lengte in lengtes.items():
		if isinstance(rij.get(veld), str):
			rij[veld] = rij[veld][:lengte]


def verwerk(ronde: str) -> None:
	"""Lees de botsingen van de kern in en volg ze ten opzichte van de vorige ronde in dezelfde reeks."""
	doc = frappe.get_doc(RONDE, ronde)
	project = issues._project(doc.project)
	versies = json.loads(doc.bron_versies)
	vorige = _vorige(doc, versies)
	gewijzigd = _regels_gewijzigd(doc)
	discipline = _disciplines(project)
	rijen: dict[str, dict] = {}
	for ruw in json.loads(afgeleid.lees_object(doc.resultaat)):
		a, b = _element(ruw["a"]), _element(ruw["b"])
		sleutel = _sleutel(a, b)
		if sleutel in rijen:
			continue
		eerder = vorige[sleutel][0] if sleutel in vorige else None
		status, ontwikkeling = _ontwikkeling(eerder, True)
		disciplines = sorted(discipline.get(e["bestand"], "") for e in (a, b))
		rijen[sleutel] = {
			"sleutel": sleutel,
			"element_a": a,
			"element_b": b,
			"punt": [round(flt(x), 4) for x in ruw.get("punt") or []],
			"afstand": flt(ruw.get("afstand")),
			"status": status,
			"issue": None,
			"groep": f"{ruw['a'].get('klasse') or '?'} × {ruw['b'].get('klasse') or '?'}",
			"soort": ruw.get("soort") or (doc.soort if doc.soort in SOORTEN else None),
			"regel": ruw.get("regel") or None,
			"emmer": ruw.get("emmer") if ruw.get("emmer") in EMMERS else "beoordelen",
			"emmer_reden": ruw.get("emmer_reden") or None,
			"ernst": ruw.get("ernst") or None,
			"categorie": ruw.get("categorie") or None,
			"disciplines": " × ".join(disciplines) if all(disciplines) else None,
			"verdieping": a.get("verdieping") or b.get("verdieping"),
			"raster": ruw.get("raster") or None,
			"ruimte": ruw.get("ruimte") or None,
			"ontwikkeling": ontwikkeling,
			"nummer": None,
			"reden": None,
			"beoordeeld_door": None,
			"beoordeeld_op": None,
			"issue_status_voor": None,
		}
		if eerder:
			for veld in BESLISSING:
				rijen[sleutel][veld] = eerder.get(veld)
	for sleutel, (rij, a, b) in vorige.items():
		if sleutel not in rijen:
			status, ontwikkeling = _ontwikkeling(rij, False)
			rijen[sleutel] = {
				**{veld: rij.get(veld) for veld in VELDEN if veld != "ronde"},
				"sleutel": _sleutel(a, b),
				"element_a": a,
				"element_b": b,
				"punt": json.loads(rij.punt or "[]"),
				"status": status,
				"ontwikkeling": ontwikkeling,
				"emmer": rij.emmer or "beoordelen",
			}
	aantal = sum(1 for r in rijen.values() if r["ontwikkeling"] in GEVONDEN)
	# Nummers: wie er een had houdt het; de rest telt door vanaf het hoogste van de vorige ronde, op volgorde van sleutel.
	hoogste = 0
	if doc.vorige_ronde:
		hoogste = cint(frappe.db.sql("select max(nummer) from `tabBIM Botsing` where ronde = %s", doc.vorige_ronde)[0][0])
	for sleutel in sorted(rijen):
		if not cint(rijen[sleutel]["nummer"]):
			hoogste += 1
			rijen[sleutel]["nummer"] = hoogste
	bron = frappe.flags.bim_bron
	frappe.flags.bim_bron = "achtergrond"
	try:
		for sleutel, r in rijen.items():
			_issue_volgt(r, vorige[sleutel][0] if sleutel in vorige else None, project, gewijzigd)
	finally:
		frappe.flags.bim_bron = bron
	nu, gebruiker = now_datetime(), frappe.session.user
	velden = ["name", "creation", "modified", "owner", "modified_by", *VELDEN]
	lengtes = _kolomlengtes(BOTSING)
	waarden = []
	for r in rijen.values():
		_kort_op_kolom(r, lengtes)
		waarden.append(
			(
				frappe.generate_hash(length=10),
				nu,
				nu,
				gebruiker,
				gebruiker,
				ronde,
				*(
					json.dumps(r[veld]) if veld in ("element_a", "element_b", "punt") else r[veld]
					for veld in VELDEN
					if veld != "ronde"
				),
			)
		)
	frappe.db.bulk_insert(BOTSING, velden, waarden)
	doc.aantal = aantal
	doc.samenvatting = _json(_samenvatting(list(rijen.values()), gewijzigd))
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
		"soort": botsing.soort,
		"regel": botsing.regel,
		"emmer": botsing.emmer or "beoordelen",
		"emmer_reden": botsing.emmer_reden,
		"ernst": botsing.ernst,
		"categorie": botsing.categorie,
		"disciplines": botsing.disciplines,
		"verdieping": botsing.verdieping,
		"raster": botsing.raster,
		"ruimte": botsing.ruimte,
		"ontwikkeling": botsing.ontwikkeling,
		"nummer": cint(botsing.nummer) or None,
		"reden": botsing.reden,
		"beoordeeld_door": botsing.beoordeeld_door,
		"beoordeeld_op": str(botsing.beoordeeld_op) if botsing.beoordeeld_op else None,
		"issue_status_voor": botsing.issue_status_voor,
	}


def _controleer_status(status: str, reden: str | None) -> str | None:
	"""De status en de reden voor een beoordeling; de reden telt alleen bij `genegeerd`."""
	if status not in STATUSSEN:
		_weiger(_("Onbekende status {0}.").format(status), "status_onbekend")
	reden = (reden or "").strip() or None
	if reden and len(reden) > MAX_REDEN:
		_weiger(_("Een reden is hoogstens {0} tekens.").format(MAX_REDEN), "reden_te_lang")
	return reden if status == "genegeerd" else None


def _beoordeel(doc, status: str, reden: str | None) -> dict:
	"""Zet status, reden en wie en wanneer; een bevestiging maakt het issue. De aanroeper heeft de rechten gecontroleerd."""
	doc.status = status
	doc.reden = reden
	doc.beoordeeld_door = frappe.session.user
	doc.beoordeeld_op = now_datetime()
	doc.save(ignore_permissions=True)
	if status == "bevestigd":
		naar_issue(doc.name)
		doc.reload()
	return naar_json(doc)


def zet_status(botsing: str, status: str, reden: str | None = None) -> dict:
	"""Beoordeelt een botsing; `bevestigd` maakt een issue als er nog geen is en houdt het daarna."""
	doc = frappe.get_doc(BOTSING, botsing)
	_vereis_schrijver(_project_van(doc))
	return _beoordeel(doc, status, _controleer_status(status, reden))


def zet_status_veel(botsingen: list[str], status: str, reden: str | None = None) -> list[dict]:
	"""Dezelfde beoordeling voor tot 500 botsingen, met één rechtencontrole per ronde."""
	botsingen = list(botsingen or [])
	if len(botsingen) > MAX_GROEPSACTIE:
		_weiger(_("Een groepsactie omvat hoogstens {0} botsingen.").format(MAX_GROEPSACTIE), "te_veel_botsingen")
	reden = _controleer_status(status, reden)
	docs = [frappe.get_doc(BOTSING, naam) for naam in botsingen]
	gecontroleerd = set()
	for doc in docs:
		if doc.ronde not in gecontroleerd:
			_vereis_schrijver(_project_van(doc))
			gecontroleerd.add(doc.ronde)
	return [_beoordeel(doc, status, reden) for doc in docs]


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
	klassen = [k.strip() for k in (doc.groep or "").split("×")] + ["", ""]
	naam_a, naam_b = a.get("naam") or klassen[0] or a["globalid"], b.get("naam") or klassen[1] or b["globalid"]
	omschrijving = _("{0} ({1}) en {2} ({3}), afstand {4} m.").format(
		naam_a, a["globalid"], naam_b, b["globalid"], flt(doc.afstand)
	)
	if doc.verdieping:
		omschrijving = _("Verdieping {0}. {1}").format(doc.verdieping, omschrijving)
	titel = _("Botsing {0} / {1}").format(naam_a, naam_b)
	lengte = _kolomlengtes(issues.ISSUE)["titel"]
	# De volledige namen staan in de omschrijving.
	titel = titel if len(titel) <= lengte else titel[: lengte - 1].rstrip() + "…"
	t = issues.topic_maak(
		project,
		{
			"title": titel,
			"topic_type": "Botsing" if not soorten or "Botsing" in soorten else None,
			"description": omschrijving,
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


def ronde_naar_json(ronde) -> dict:
	return {
		"naam": ronde.name,
		"titel": ronde.titel,
		"set_a": json.loads(ronde.set_a or "[]"),
		"set_b": json.loads(ronde.set_b or "[]"),
		"soort": ronde.soort,
		"tolerantie": flt(ronde.tolerantie),
		"regels": json.loads(ronde.regels or "[]"),
		"voorinstelling": ronde.voorinstelling,
		"reeks": ronde.reeks,
		"voortgang": flt(ronde.voortgang),
		"samenvatting": json.loads(ronde.samenvatting) if ronde.samenvatting else None,
		"status": ronde.status,
		"aantal": cint(ronde.aantal),
		"bron_versies": json.loads(ronde.bron_versies or "{}"),
		"vorige_ronde": ronde.vorige_ronde,
		"gestart": str(ronde.creation),
		"gestart_door": ronde.owner,
		"fout": json.loads(ronde.fout) if ronde.fout else None,
	}


def rondes(project) -> list[dict]:
	"""De rondes van het project, nieuwste eerst; lopende rondes worden eerst bij de kern bijgewerkt."""
	project = issues._project(project)
	issues._vereis_lezen(project)
	uit = []
	for naam in frappe.get_all(RONDE, {"project": project.name}, pluck="name", order_by="creation desc"):
		doc = frappe.get_doc(RONDE, naam)
		_werk_bij(doc)
		uit.append(ronde_naar_json(doc))
	return uit


def lijst(ronde: str) -> list[dict]:
	"""De botsingen van een ronde, per groep en sleutel."""
	project = issues._project(frappe.db.get_value(RONDE, ronde, "project") or "")
	issues._vereis_lezen(project)
	rijen = frappe.get_all(BOTSING, {"ronde": ronde}, ["name", *VELDEN], order_by="groep asc, sleutel asc")
	return [naar_json(rij) for rij in rijen]


def _lijst_uit(tekst) -> list:
	waarde = json.loads(tekst) if isinstance(tekst, str) and tekst else tekst
	return waarde if isinstance(waarde, list) else []


def instellingen(project) -> dict:
	"""De botsingsregels en opgeslagen weergaven van het project; `mag_wijzigen` is waar voor wie in de modelmap mag schrijven."""
	project = issues._project(project)
	issues._vereis_lezen(project)
	return {
		"regels": _lijst_uit(project.botsingsregels),
		"weergaven": _lijst_uit(project.botsingsweergaven),
		"mag_wijzigen": bool(issues._schrijver(project)),
	}


def _regel(regel) -> dict:
	if not isinstance(regel, dict):
		_weiger(_("Een regel is een object."), "regels_ongeldig")
	a, b = str(regel.get("a") or "").strip(), str(regel.get("b") or "").strip()
	if not a or not b:
		_weiger(_("Een regel heeft twee disciplines nodig."), "regels_ongeldig")
	if regel.get("soort") not in REGELSOORTEN:
		_weiger(_("Kies uit, hard of afstand."), "regels_ongeldig")
	try:
		mm = flt(regel.get("mm"))
	except (TypeError, ValueError):
		mm = -1
	if not 0 <= mm <= MAX_MM:
		_weiger(_("De afstand ligt tussen 0 en {0} mm.").format(MAX_MM), "regels_ongeldig")
	ernst = regel.get("ernst") or None
	if ernst is not None and ernst not in ERNSTEN:
		_weiger(_("Onbekende ernst {0}.").format(ernst), "regels_ongeldig")
	a, b = sorted((a, b))
	return {"a": a, "b": b, "soort": regel["soort"], "mm": mm, "ernst": ernst}


def _weergave(weergave) -> dict:
	if not isinstance(weergave, dict):
		_weiger(_("Een weergave is een object."), "weergave_ongeldig")
	naam = str(weergave.get("naam") or "").strip()
	if not naam:
		_weiger(_("Een weergave heeft een naam nodig."), "weergave_ongeldig")
	filter_ = weergave.get("filter") or {}
	if not isinstance(filter_, dict):
		_weiger(_("Het filter van een weergave is een object."), "weergave_ongeldig")
	groep = weergave.get("groep") or None
	if groep is not None and not isinstance(groep, str):
		_weiger(_("De groepering van een weergave is een tekst."), "weergave_ongeldig")
	return {"naam": naam, "filter": filter_, "groep": groep}


def instellingen_bewaar(project, regels=None, weergaven=None) -> dict:
	"""Bewaart de regels en/of weergaven die zijn meegegeven; wat `None` is blijft zoals het was."""
	project = issues._project(project)
	_vereis_schrijver(project)
	if regels is not None:
		project.botsingsregels = _json([_regel(r) for r in regels])
	if weergaven is not None:
		if len(weergaven) > MAX_WEERGAVEN:
			_weiger(_("Hoogstens {0} weergaven.").format(MAX_WEERGAVEN), "weergave_ongeldig")
		nieuw = [_weergave(w) for w in weergaven]
		if len({w["naam"] for w in nieuw}) != len(nieuw):
			_weiger(_("Elke weergave heeft een eigen naam."), "weergave_ongeldig")
		project.botsingsweergaven = _json(nieuw)
	project.save(ignore_permissions=True)
	return instellingen(project)


def trends(ronde: str) -> list[dict]:
	"""De samenvattingen langs `vorige_ronde`, hoogstens de laatste 20, oudste eerst."""
	project = issues._project(frappe.db.get_value(RONDE, ronde, "project") or "")
	issues._vereis_lezen(project)
	uit = []
	naam = ronde
	while naam and len(uit) < MAX_VERLOOP:
		rij = frappe.db.get_value(RONDE, naam, ["name", "titel", "creation", "samenvatting", "vorige_ronde"], as_dict=True)
		if not rij:
			break
		uit.append(
			{
				"naam": rij.name,
				"titel": rij.titel,
				"gestart": str(rij.creation),
				"samenvatting": json.loads(rij.samenvatting) if rij.samenvatting else None,
			}
		)
		naam = rij.vorige_ronde
	return uit[::-1]
