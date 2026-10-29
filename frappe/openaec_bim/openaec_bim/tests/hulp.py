"""Gedeelde opzet voor de tests van openaec_bim: een nagebootste kern, een ruimte met een modelmap en gebruikers."""

import json
from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase
from openaec_storage import api as opslag
from openaec_storage import s3
from openaec_storage.tests.hulp import NagebootsteS3, gebruiker, ruim_op, ruimte, upload

from openaec_bim import afgeleid
from openaec_bim.kern import KernFout

INDEX = {"schema": "IFC4", "omzetter": "kern-0.1.0+fragments-3.6.0", "delen": [{"naam": "model.frag", "bytes": 5}]}

BIM_DOCTYPES = (
	"BIM Auditregel",
	"BIM Botsing",
	"BIM Botsingsronde",
	"BIM Reactie",
	"BIM Standpunt",
	"BIM Issue",
	"BIM Project",
	"BIM Afgeleid",
	"BIM Versiekoppeling",
)


class NepKern:
	"""Bootst de BIM-kern na: legt de verzoeken vast en geeft per taak de stand die de test zet."""

	def __init__(self):
		self.verzoeken = []
		self.taken = {}
		self.elementen = {}

	def roep(self, methode, pad, json=None):
		self.verzoeken.append((methode, pad, json))
		if pad.startswith("/v1/tools/") and pad.rsplit("/", 1)[1] in ("omzetten", "koppelen", "botsingen"):
			taak = f"taak-{len(self.taken) + 1}"
			self.taken[taak] = {"status": "wacht", "voortgang": 0}
			return {"taak": taak}
		if pad.startswith("/v1/taken/"):
			taak = pad.rsplit("/", 1)[1]
			if taak not in self.taken:
				raise KernFout("taak_onbekend", "Er is geen taak.")
			return self.taken[taak]
		if pad == "/v1/tools/eigenschappen":
			return {"elementen": self.elementen}
		raise AssertionError(pad)


def maak_klaar(kern, bestand, versie=1, frag=b"FRAG!", sqlite=b"SQLITE"):
	"""Zet de taak van deze versie op klaar, met de uitvoer in de bucket zoals de kern hem aflevert."""
	doc = afgeleid.laatste(bestand, versie) or afgeleid.start(bestand, versie)
	for naam, inhoud in (("index.json", json.dumps(INDEX).encode()), ("model.frag", frag), ("eigenschappen.sqlite", sqlite)):
		s3.zet(f"{doc.prefix}/{naam}", inhoud)
	kern.taken[doc.kern_taak] = {
		"status": "klaar",
		"voortgang": 1.0,
		"uitkomst": {"omzetter": INDEX["omzetter"], "delen": [{"naam": "model.frag", "bytes": len(frag), "verdiepingen": []}]},
	}
	return doc


def ruim_bim_op():
	for doctype in BIM_DOCTYPES:
		if frappe.db.table_exists(doctype):
			frappe.db.delete(doctype)
	frappe.db.delete("BIM Issue Element")


class ProjectTest(IntegrationTestCase):
	"""Een ruimte met een modelmap (05 BIM-modellen) en twee IFC-bestanden; een lid (schrijver) en een lezer."""

	def setUp(self):
		ruim_op()
		ruim_bim_op()
		self.s3 = NagebootsteS3().start()
		self.kern = NepKern()
		self.patch = patch("openaec_bim.kern.roep", self.kern.roep)
		self.patch.start()
		self.lid = gebruiker("bimlid")
		self.lezer = gebruiker("bimlezer")
		self.buiten = gebruiker("bimbuiten")
		self.ruimte = ruimte("Project BIM", {self.lid: "schrijver", self.lezer: "lezer"})
		frappe.set_user(self.lid)
		self.map = opslag.maak_map(ruimte=self.ruimte, naam="05 BIM-modellen")["map"]
		self.constructie = upload(self.ruimte, "constructie.ifc", b"ISO-10303-21; c", map_naam=self.map)["bestand"]
		self.installaties = upload(self.ruimte, "installaties.ifc", b"ISO-10303-21; i", map_naam=self.map)["bestand"]
		frappe.set_user("Administrator")
		self.project = frappe.get_doc(
			{"doctype": "BIM Project", "modelmap": self.map, "ruimte": self.ruimte, "titel": "05 BIM-modellen"}
		).insert(ignore_permissions=True).name
		frappe.set_user(self.lid)

	def model_klaar(self, bestand, versie=1):
		"""Zet de omzetting van deze versie klaar en laat de app dat zien, zoals na de taak van de kern."""
		doc = maak_klaar(self.kern, bestand, versie)
		afgeleid.bijwerken(doc)
		return frappe.get_doc(afgeleid.DOCTYPE, doc.name)

	def tearDown(self):
		self.patch.stop()
		self.s3.stop()
		frappe.set_user("Administrator")
		frappe.flags.bim_bron = None
		ruim_bim_op()
		ruim_op()
