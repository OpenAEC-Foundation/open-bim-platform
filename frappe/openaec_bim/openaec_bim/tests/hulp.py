"""Gedeelde opzet voor de tests van openaec_bim: een nagebootste kern, een ruimte met een modelmap en gebruikers."""

from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase
from openaec_storage import api as opslag
from openaec_storage.tests.hulp import NagebootsteS3, gebruiker, ruim_op, ruimte, upload

from openaec_bim.kern import KernFout

BIM_DOCTYPES = (
	"BIM Auditregel",
	"BIM Reactie",
	"BIM Standpunt",
	"BIM Issue",
	"BIM Project",
	"BIM Afgeleid",
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

	def tearDown(self):
		self.patch.stop()
		self.s3.stop()
		frappe.set_user("Administrator")
		frappe.flags.bim_bron = None
		ruim_bim_op()
		ruim_op()
