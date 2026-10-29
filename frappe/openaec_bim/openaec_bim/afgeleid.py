"""Afgeleide gegevens van modelversies: omzettingen starten bij de BIM-kern, ze volgen, en hun plek in de bucket.

De kern krijgt ondertekende S3-adressen: lezen voor de bron (de versie in Storage), schrijven voor de uitvoer onder
`<prefix>/bim/afgeleid/<bestand>/<versie>/<omzetting>/` (ontwerp 5.4). Elke omzetting heeft een eigen plek, dus wat er
staat verandert nooit; een nieuwe omzetting van dezelfde versie komt ernaast.
"""

import hashlib
import json
import math
import re

import frappe
from frappe import _
from frappe.utils import cint, now_datetime

from openaec_bim import kern

DOCTYPE = "BIM Afgeleid"
BASIS = ("index.json", "eigenschappen.sqlite", "ruimtelijk.json")
# Zoals de kern (OPENBIM_SPLITS_VANAF_BYTES en OPENBIM_DEEL_BYTES): boven 1,5 GB in delen van 1 GB.
SPLITS_VANAF = 1_500_000_000
DEEL = 1_000_000_000
GELDIG_BRON = 6 * 3600  # de taak kan even in de wachtrij staan
GELDIG_DOEL = 12 * 3600
GELDIG_INDEX = 3600
LEESBLOK = 8 * 1024 * 1024
_SHA256 = re.compile(r"[0-9a-f]{64}")


def _s3():
	from openaec_storage import s3

	return s3


def onderdelen(grootte: int) -> list[str]:
	"""De uitvoerbestanden voor een bron van deze grootte: model.frag, of deel-1.frag … als de kern splitst."""
	vanaf = cint(frappe.conf.get("openaec_bim_splits_vanaf_bytes")) or SPLITS_VANAF
	deel = cint(frappe.conf.get("openaec_bim_deel_bytes")) or DEEL
	frags = [f"deel-{i}.frag" for i in range(1, math.ceil(grootte / deel) + 1)] if grootte > vanaf else ["model.frag"]
	return [*BASIS, *frags]


def leesadres(sleutel: str, geldig: int) -> str:
	s3 = _s3()
	return s3._client().generate_presigned_url("get_object", Params={"Bucket": s3.bucket(), "Key": sleutel}, ExpiresIn=geldig)


def schrijfadres(sleutel: str, geldig: int) -> str:
	s3 = _s3()
	return s3._client().generate_presigned_url("put_object", Params={"Bucket": s3.bucket(), "Key": sleutel}, ExpiresIn=geldig)


def laatste(bestand: str, versie: int):
	"""De laatste omzetting van deze versie, of None."""
	naam = frappe.db.get_value(DOCTYPE, {"bestand": bestand, "versie": cint(versie)}, "name", order_by="creation desc")
	return frappe.get_doc(DOCTYPE, naam) if naam else None


def getoonde_versie(bestand: str) -> int | None:
	"""De versie die het project van dit bestand toont: de laatste die omgezet is."""
	versie = frappe.db.get_value(DOCTYPE, {"bestand": bestand, "status": "klaar"}, "versie", order_by="versie desc")
	return cint(versie) or None


def bron(bestand: str, versie: int) -> dict:
	"""Een ondertekend leesadres van de IFC van deze versie voor de kern, met grootte en (als bekend) sha256."""
	gegevens = frappe.db.get_value(
		"Bestandsversie", {"bestand": bestand, "volgnummer": cint(versie)}, ["s3_sleutel", "sha256", "grootte"], as_dict=True
	)
	if not gegevens or not gegevens.s3_sleutel:
		frappe.throw(_("Versie bestaat niet"), frappe.DoesNotExistError)
	uit = {"url": leesadres(gegevens.s3_sleutel, GELDIG_BRON), "grootte": cint(gegevens.grootte)}
	sha256 = (gegevens.sha256 or "").lower()
	if _SHA256.fullmatch(sha256):
		uit["sha256"] = sha256
	return uit


def start(bestand: str, versie: int):
	"""Een nieuwe omzetting van deze versie: plek in de bucket, ondertekende adressen, taak bij de kern."""
	bron_ = bron(bestand, versie)
	doc = frappe.get_doc({"doctype": DOCTYPE, "bestand": bestand, "versie": cint(versie), "status": "wacht"})
	doc.insert(ignore_permissions=True)
	doc.prefix = _s3()._met_prefix(f"bim/afgeleid/{bestand}/{cint(versie)}/{doc.name}")
	doelen = {naam: schrijfadres(f"{doc.prefix}/{naam}", GELDIG_DOEL) for naam in onderdelen(bron_["grootte"])}
	try:
		doc.kern_taak = kern.start_omzetten(bron_, doelen)
	except kern.KernFout as fout:
		doc.status = "fout"
		doc.fout = {"error_code": fout.code, "melding": str(fout)}
	doc.save(ignore_permissions=True)
	return doc


def bijwerken(doc) -> None:
	"""De stand van een lopende omzetting bij de kern ophalen; bij klaar de samenvatting uit de bucket lezen."""
	if doc.status not in ("wacht", "bezig") or not doc.kern_taak:
		return
	try:
		taak = kern.taak(doc.kern_taak)
	except kern.KernFout as fout:
		if fout.code != "taak_onbekend":
			return  # de kern is even weg: later opnieuw
		taak = {"status": "fout", "fout": {"error_code": "taak_onbekend", "melding": str(fout)}}
	status = taak.get("status")
	doc.voortgang = taak.get("voortgang") or 0
	if status in ("wacht", "bezig"):
		doc.status = status
	elif status == "klaar":
		uitkomst = taak.get("uitkomst") or {}
		doc.omzetter = uitkomst.get("omzetter")
		delen = [{"naam": d["naam"], "bytes": cint(d["bytes"])} for d in uitkomst.get("delen") or []]
		# Een JSON-veld van Frappe neemt geen lijst aan: als tekst (api._json leest beide).
		doc.delen = json.dumps(delen)
		doc.frag_bytes = sum(d["bytes"] for d in delen)
		doc.samenvatting = json.loads(lees_object(f"{doc.prefix}/index.json"))
		doc.status = "klaar"
	else:
		doc.status = "fout"
		doc.fout = taak.get("fout") or {"error_code": status or "onbekend", "melding": _("De omzetting is gestopt.")}
	doc.save(ignore_permissions=True)
	if doc.status == "klaar":
		from openaec_bim import koppeling

		koppeling.na_omzetting(doc)


def zonder_botsing(stap, *args) -> None:
	"""Een bijwerking die een ander verzoek tegelijk doet (de viewer vraagt het project elke paar seconden, ook terwijl
	de planner bijwerkt), botst bij het opslaan: MariaDB 1020 of een verouderde tijdstempel. Die keer wordt de stap
	teruggedraaid tot het savepoint en overgeslagen; de volgende vraag ziet de nieuwe stand."""
	frappe.db.savepoint("openaec_bim_bijwerken")
	try:
		stap(*args)
	except (frappe.QueryDeadlockError, frappe.TimestampMismatchError):
		try:
			frappe.db.rollback(save_point="openaec_bim_bijwerken")
		except frappe.db.OperationalError:
			# Na een 1020 heeft MariaDB de hele transactie al teruggedraaid, en het savepoint met haar.
			frappe.db.rollback()
		# Het document in het geheugen kan al een stand hebben die niet is opgeslagen.
		for doc in args:
			if hasattr(doc, "reload") and getattr(doc, "name", None):
				try:
					doc.reload()
				except frappe.DoesNotExistError:
					pass


def volg_lopende() -> None:
	"""Geplande taak: elke lopende omzetting, versiekoppeling en botsingsronde bijwerken."""
	from openaec_bim import botsingen, koppeling

	for naam in frappe.get_all(DOCTYPE, filters={"status": ("in", ("wacht", "bezig"))}, pluck="name"):
		zonder_botsing(bijwerken, frappe.get_doc(DOCTYPE, naam))
		frappe.db.commit()
	koppeling.volg_lopende()
	botsingen.volg_lopende()


def lees_object(sleutel: str) -> bytes:
	s3 = _s3()
	return s3._client().get_object(Bucket=s3.bucket(), Key=sleutel)["Body"].read()


def eigenschappen_sha256(doc) -> str:
	"""SHA-256 van de eigenschappen-index (eenmalig berekend): daarmee bewaart de kern hem in zijn cache."""
	if doc.eigenschappen_sha256:
		return doc.eigenschappen_sha256
	s3 = _s3()
	lichaam = s3._client().get_object(Bucket=s3.bucket(), Key=f"{doc.prefix}/eigenschappen.sqlite")["Body"]
	som = hashlib.sha256()
	for blok in lichaam.iter_chunks(LEESBLOK):
		som.update(blok)
	frappe.db.set_value(DOCTYPE, doc.name, "eigenschappen_sha256", som.hexdigest())
	return som.hexdigest()


def geopend(doc) -> None:
	frappe.db.set_value(DOCTYPE, doc.name, "laatst_geopend", now_datetime(), update_modified=False)
