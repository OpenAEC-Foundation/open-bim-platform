import hashlib
from unittest.mock import patch
from urllib.parse import unquote

import frappe
from frappe.tests import IntegrationTestCase
from openaec_storage import api as opslag
from openaec_storage.tests.hulp import NagebootsteS3, gebruiker, ruim_op, ruimte, upload

from openaec_bim import afgeleid, api, leestoken
from openaec_bim.kern import KernFout
from openaec_bim.tests.hulp import NepKern, maak_klaar


class TestApi(IntegrationTestCase):
	def setUp(self):
		ruim_op()
		frappe.db.delete(afgeleid.DOCTYPE)
		self.s3 = NagebootsteS3().start()
		self.kern = NepKern()
		self.patch = patch("openaec_bim.kern.roep", self.kern.roep)
		self.patch.start()
		self.lid = gebruiker("bimlid")
		self.buiten = gebruiker("bimbuiten")
		self.ruimte = ruimte("Project BIM", {self.lid: "schrijver"})
		frappe.set_user(self.lid)
		self.map = opslag.maak_map(ruimte=self.ruimte, naam="05 BIM-modellen")["map"]
		self.sub = opslag.maak_map(ruimte=self.ruimte, naam="Constructie", bovenliggende=self.map)["map"]
		self.los = upload(self.ruimte, "terrein.ifc", b"ISO-10303-21; terrein", map_naam=self.map)["bestand"]
		self.wand = upload(self.ruimte, "wand model.ifc", b"ISO-10303-21; wanden", map_naam=self.sub)["bestand"]
		upload(self.ruimte, "notities.txt", b"geen model", map_naam=self.map)

	def tearDown(self):
		self.patch.stop()
		self.s3.stop()
		frappe.set_user("Administrator")
		frappe.db.delete(afgeleid.DOCTYPE)
		ruim_op()

	def maak_klaar(self, bestand, frag=b"FRAG!", sqlite=b"SQLITE"):
		return maak_klaar(self.kern, bestand, frag=frag, sqlite=sqlite)

	def test_project_overleeft_een_gelijktijdige_bijwerking(self):
		# De viewer vraagt het project elke paar seconden, ook terwijl de planner dezelfde omzetting bijwerkt: dan
		# botst het opslaan (MariaDB 1020 of een verouderde tijdstempel). Die keer slaat het project dat over.
		api.project(map=self.map)
		for fout in (frappe.QueryDeadlockError("1020"), frappe.TimestampMismatchError("ouder")):
			with patch.object(afgeleid, "bijwerken", side_effect=fout):
				project = api.project(map=self.map)
			self.assertEqual({m["status"] for m in project["modellen"]}, {"wacht"})

	def test_project_zet_de_omzettingen_klaar(self):
		project = api.project(map=self.map)
		self.assertEqual(project["project"], "05 BIM-modellen")
		modellen = {m["naam"]: m for m in project["modellen"]}
		self.assertEqual(set(modellen), {"terrein", "wand model"})
		self.assertEqual(modellen["wand model"]["discipline"], "Constructie")
		self.assertEqual(modellen["terrein"]["discipline"], "")
		self.assertEqual(modellen["wand model"]["bron"], {"soort": "bestand", "sleutel": self.wand, "versie": "1"})
		self.assertEqual(modellen["wand model"]["status"], "wacht")
		omzettingen = [j for m, p, j in self.kern.verzoeken if p == "/v1/tools/omzetten"]
		self.assertEqual(len(omzettingen), 2)
		self.assertEqual(set(omzettingen[0]["doelen"]), {"index.json", "eigenschappen.sqlite", "ruimtelijk.json", "model.frag"})
		self.assertEqual(omzettingen[0]["bron"]["grootte"], len(b"ISO-10303-21; terrein"))
		doc = afgeleid.laatste(self.wand, 1)
		self.assertIn(f"bim/afgeleid/{self.wand}/1/{doc.name}", doc.prefix)

	def test_een_tweede_keer_openen_start_niets_opnieuw(self):
		api.project(map=self.map)
		api.project(map=self.map)
		self.assertEqual(len([1 for m, p, j in self.kern.verzoeken if p == "/v1/tools/omzetten"]), 2)

	def test_klaar_met_delen_en_samenvatting(self):
		api.project(map=self.map)
		self.maak_klaar(self.wand)
		modellen = {m["naam"]: m for m in api.project(map=self.map)["modellen"]}
		self.assertEqual(modellen["wand model"]["status"], "klaar")
		self.assertEqual(modellen["wand model"]["delen"], [{"naam": "model.frag", "bytes": 5}])
		self.assertEqual(modellen["wand model"]["index"]["schema"], "IFC4")
		self.assertEqual(modellen["terrein"]["status"], "wacht")

	def test_een_fout_van_de_kern_staat_bij_het_model(self):
		api.project(map=self.map)
		doc = afgeleid.laatste(self.wand, 1)
		self.kern.taken[doc.kern_taak] = {"status": "fout", "fout": {"error_code": "omzetten_mislukt", "melding": "kapot"}}
		modellen = {m["naam"]: m for m in api.project(map=self.map)["modellen"]}
		self.assertEqual(modellen["wand model"]["status"], "fout")
		self.assertEqual(modellen["wand model"]["fout"]["error_code"], "omzetten_mislukt")
		self.assertEqual(api.opnieuw(bestand=self.wand, versie="1")["status"], "wacht")

	def test_een_verloren_taak_wordt_een_fout(self):
		api.project(map=self.map)
		self.kern.taken.clear()
		modellen = {m["naam"]: m for m in api.project(map=self.map)["modellen"]}
		self.assertEqual(modellen["wand model"]["fout"]["error_code"], "taak_onbekend")

	def test_kern_niet_bereikbaar_bij_starten(self):
		def stuk(*args, **kwargs):
			raise KernFout("kern_onbereikbaar", "weg")

		with patch("openaec_bim.kern.roep", stuk):
			modellen = api.project(map=self.map)["modellen"]
		self.assertTrue(all(m["status"] == "fout" for m in modellen))

	def test_zonder_rechten_geen_project(self):
		frappe.set_user(self.buiten)
		with self.assertRaises(frappe.PermissionError):
			api.project(map=self.map)

	def test_lees_adres_en_lees(self):
		api.project(map=self.map)
		self.maak_klaar(self.wand, frag=b"FRAG!")
		adres = api.lees_adres(bestand=self.wand, versie="1", deel="model.frag")
		self.assertEqual(adres["bytes"], 5)
		token = adres["adres"].split("token=", 1)[1]
		frappe.set_user("Guest")
		respons = api.lees(token=unquote(token))
		self.assertEqual(b"".join(respons.response), b"FRAG!")
		self.assertEqual(respons.mimetype, "application/octet-stream")

	def test_lees_met_een_sessie_geweigerd(self):
		api.project(map=self.map)
		doc = self.maak_klaar(self.wand)
		api.project(map=self.map)
		with self.assertRaises(frappe.PermissionError):
			api.lees(token=leestoken.nieuw(doc.name, "model.frag", self.lid))

	def test_lees_adres_van_een_model_dat_niet_klaar_is(self):
		api.project(map=self.map)
		with self.assertRaises(api.NogNietKlaar):
			api.lees_adres(bestand=self.wand, versie="1", deel="model.frag")

	def test_lees_adres_van_een_onbekend_deel(self):
		api.project(map=self.map)
		self.maak_klaar(self.wand)
		api.project(map=self.map)
		with self.assertRaises(api.DeelOnbekend):
			api.lees_adres(bestand=self.wand, versie="1", deel="deel-9.frag")

	def test_eigenschappen_met_de_index_en_zijn_sha256(self):
		api.project(map=self.map)
		self.maak_klaar(self.wand, sqlite=b"DE INDEX")
		api.project(map=self.map)
		self.kern.elementen = {"g1": {"klasse": "IfcWall"}}
		self.assertEqual(api.eigenschappen(bestand=self.wand, versie="1", globalids='["g1"]'), {"g1": {"klasse": "IfcWall"}})
		vraag = [j for m, p, j in self.kern.verzoeken if p == "/v1/tools/eigenschappen"][0]
		self.assertEqual(vraag["globalids"], ["g1"])
		self.assertEqual(vraag["index"]["sha256"], hashlib.sha256(b"DE INDEX").hexdigest())

	def test_onderdelen_volgen_het_splitsen_van_de_kern(self):
		standaard = {"openaec_bim_deel_bytes": 0, "openaec_bim_splits_vanaf_bytes": 0}
		with patch.dict(frappe.local.conf, standaard):
			self.assertEqual(afgeleid.onderdelen(10)[-1], "model.frag")
			self.assertEqual(afgeleid.onderdelen(2_500_000_000)[-3:], ["deel-1.frag", "deel-2.frag", "deel-3.frag"])
		with patch.dict(frappe.local.conf, {"openaec_bim_deel_bytes": 400_000_000}):
			self.assertEqual(afgeleid.onderdelen(1_756_000_000)[-1], "deel-5.frag")

	def test_token_van_een_andere_site_of_kapot(self):
		with self.assertRaises(frappe.PermissionError):
			leestoken.lees("kapot.token")
