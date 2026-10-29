import json

import frappe
from openaec_storage import s3
from openaec_storage.tests.hulp import upload

from openaec_bim import audit, botsingen, issues
from openaec_bim import koppeling as koppeling_mod
from openaec_bim.tests.hulp import ProjectTest
from openaec_bim.tests.test_koppeling import uitkomst


class TestBotsingen(ProjectTest):
	def setUp(self):
		super().setUp()
		self.model_klaar(self.constructie)
		self.model_klaar(self.installaties)

	def start(self):
		return botsingen.start(self.project, [{"bestand": self.constructie}], [{"bestand": self.installaties}], "hard", 0.01)

	def lever(self, ronde, paren):
		"""De kern is klaar: het resultaat voor de versies van de ronde staat in de bucket."""
		doc = frappe.get_doc("BIM Botsingsronde", ronde)
		versies = json.loads(doc.bron_versies)
		resultaat = [
			{
				"a": {"sleutel": self.constructie, "versie": versies[self.constructie], "globalid": a, "klasse": "IfcWall"},
				"b": {"sleutel": self.installaties, "versie": versies[self.installaties], "globalid": b, "klasse": "IfcDuctSegment"},
				"punt": [1.0, 2.0, 3.0],
				"afstand": 0.05,
			}
			for a, b in paren
		]
		s3.zet(doc.resultaat, json.dumps(resultaat).encode())
		self.kern.taken[doc.kern_taak] = {"status": "klaar", "voortgang": 1.0, "uitkomst": {"aantal": len(paren)}}
		botsingen.bijwerken(doc)
		return ronde

	def ronde_met(self, paren):
		return self.lever(self.start(), paren)

	def botsing(self, ronde, a, b):
		sleutel = "|".join(sorted((f"{self.constructie}:{a}", f"{self.installaties}:{b}")))
		return frappe.get_doc("BIM Botsing", {"ronde": ronde, "sleutel": sleutel})

	def nieuwe_versie_installaties(self, terugval=()):
		frappe.set_user(self.lid)
		upload(self.ruimte, "installaties.ifc", b"ISO-10303-21; i2", map_naam=self.map, basis_versie=1)
		self.model_klaar(self.installaties, 2)
		k = frappe.get_last_doc(koppeling_mod.DOCTYPE, {"bestand": self.installaties})
		self.kern.taken[k.kern_taak] = uitkomst(terugval=terugval)
		koppeling_mod.bijwerken(k)

	def test_ronde_start_met_de_versies_van_nu(self):
		ronde = self.start()
		doc = frappe.get_doc("BIM Botsingsronde", ronde)
		self.assertEqual(json.loads(doc.bron_versies), {self.constructie: "1", self.installaties: "1"})
		methode, pad, vraag = self.kern.verzoeken[-1]
		self.assertEqual((methode, pad), ("POST", "/v1/tools/botsingen"))
		self.assertEqual([(m["sleutel"], m["versie"]) for m in vraag["set_a"]], [(self.constructie, "1")])
		self.assertEqual((vraag["soort"], vraag["tolerantie"]), ("hard", 0.01))
		self.assertIn(f"bim/botsingen/{ronde}.json", vraag["doel"])
		self.assertEqual(doc.status, "wacht")

	def test_een_model_zonder_omzetting_kan_niet_meedoen(self):
		frappe.set_user(self.lid)
		los = upload(self.ruimte, "terrein.ifc", b"ISO-10303-21; t", map_naam=self.map)["bestand"]
		code = None
		frappe.local.response.pop("foutcode", None)
		with self.assertRaises(frappe.ValidationError):
			botsingen.start(self.project, [{"bestand": los}], [{"bestand": self.installaties}], "hard", 0.01)
		code = frappe.local.response.pop("foutcode", None)
		self.assertEqual(code, "model_niet_omgezet")

	def test_een_lezer_start_geen_ronde(self):
		frappe.set_user(self.lezer)
		self.assertRaises(frappe.PermissionError, self.start)

	def test_resultaten_worden_botsingen_met_een_groep(self):
		ronde = self.ronde_met([("w1", "k1"), ("w2", "k2")])
		doc = frappe.get_doc("BIM Botsingsronde", ronde)
		self.assertEqual((doc.status, doc.aantal), ("klaar", 2))
		b = self.botsing(ronde, "w1", "k1")
		self.assertEqual((b.status, b.groep, b.afstand), ("nieuw", "IfcWall × IfcDuctSegment", 0.05))
		self.assertEqual(json.loads(b.element_a), {"bestand": self.constructie, "versie": "1", "globalid": "w1"})
		self.assertEqual(json.loads(b.punt), [1.0, 2.0, 3.0])

	def test_een_nieuwe_versie_tijdens_de_ronde_verandert_de_ronde_niet(self):
		ronde = self.start()
		self.nieuwe_versie_installaties()
		self.lever(ronde, [("w1", "k1")])
		self.assertEqual(json.loads(self.botsing(ronde, "w1", "k1").element_b)["versie"], "1")
		self.assertEqual(json.loads(frappe.db.get_value("BIM Botsingsronde", ronde, "bron_versies"))[self.installaties], "1")

	def test_volgende_ronde_volgt_via_de_koppeling(self):
		eerste = self.ronde_met([("w1", "k1")])
		botsingen.zet_status(self.botsing(eerste, "w1", "k1").name, "genegeerd")
		self.nieuwe_versie_installaties(terugval=[("k1", "k2")])
		tweede = self.ronde_met([("w1", "k2")])
		self.assertEqual(frappe.db.get_value("BIM Botsingsronde", tweede, "vorige_ronde"), eerste)
		b = self.botsing(tweede, "w1", "k2")
		self.assertEqual((b.status, json.loads(b.element_b)["versie"]), ("genegeerd", "2"))

	def test_een_verdwenen_botsing_is_opgelost_en_komt_terug_als_actief(self):
		eerste = self.ronde_met([("w1", "k1"), ("w2", "k2")])
		tweede = self.ronde_met([("w1", "k1")])
		self.assertEqual(self.botsing(tweede, "w1", "k1").status, "actief")
		self.assertEqual(self.botsing(tweede, "w2", "k2").status, "opgelost")
		self.assertEqual(frappe.db.get_value("BIM Botsingsronde", tweede, "aantal"), 1)
		derde = self.ronde_met([("w1", "k1"), ("w2", "k2")])
		self.assertEqual(self.botsing(derde, "w2", "k2").status, "actief")
		self.assertEqual(self.botsing(eerste, "w2", "k2").status, "nieuw")

	def test_een_issue_bij_een_botsing_gaat_mee_naar_de_volgende_ronde(self):
		eerste = self.ronde_met([("w1", "k1")])
		t = botsingen.naar_issue(self.botsing(eerste, "w1", "k1").name)
		tweede = self.ronde_met([("w1", "k1")])
		self.assertEqual(self.botsing(tweede, "w1", "k1").issue, t["guid"])

	def test_botsing_naar_issue(self):
		ronde = self.ronde_met([("w1", "k1")])
		b = self.botsing(ronde, "w1", "k1")
		t = botsingen.naar_issue(b.name)
		self.assertEqual(t["topic_type"], "Botsing")
		self.assertEqual({(e["ifc_guid"], e["teruggevonden"]) for e in t["elementen"]}, {("w1", True), ("k1", True)})
		[sp] = issues.standpunten(t["guid"])
		self.assertEqual({c["ifc_guid"] for c in sp["components"]["selection"]}, {"w1", "k1"})
		self.assertEqual(frappe.db.get_value("BIM Botsing", b.name, "issue"), t["guid"])
		self.assertNotIn("/v1/tools/eigenschappen", [pad for _m, pad, _j in self.kern.verzoeken])

	def test_een_issue_van_een_botsing_kan_verwijderd_worden(self):
		eerste = self.ronde_met([("w1", "k1")])
		t = botsingen.naar_issue(self.botsing(eerste, "w1", "k1").name)
		tweede = self.ronde_met([("w1", "k1")])
		issues.topic_verwijder(t["guid"])
		self.assertFalse(frappe.db.exists("BIM Issue", t["guid"]))
		self.assertIsNone(self.botsing(eerste, "w1", "k1").issue)
		self.assertIsNone(self.botsing(tweede, "w1", "k1").issue)

	def test_status_zetten_staat_in_het_log_en_vraagt_schrijfrecht(self):
		ronde = self.ronde_met([("w1", "k1")])
		b = self.botsing(ronde, "w1", "k1")
		self.assertEqual(botsingen.zet_status(b.name, "genegeerd")["status"], "genegeerd")
		regel = frappe.get_last_doc("BIM Auditregel", {"object": b.name})
		self.assertEqual((regel.handeling, json.loads(regel.na)), ("gewijzigd", {"status": "genegeerd"}))
		self.assertIn(",gewijzigd,BIM Botsing,", audit.exporteer(self.project))
		self.assertRaises(frappe.ValidationError, botsingen.zet_status, b.name, "weg")
		frappe.set_user(self.lezer)
		self.assertRaises(frappe.PermissionError, botsingen.zet_status, b.name, "actief")
