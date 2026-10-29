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

	def nieuwe_versie_installaties(self, terugval=(), niet_gevonden=(), klaar=True):
		frappe.set_user(self.lid)
		upload(self.ruimte, "installaties.ifc", b"ISO-10303-21; i2", map_naam=self.map, basis_versie=1)
		self.model_klaar(self.installaties, 2)
		k = frappe.get_last_doc(koppeling_mod.DOCTYPE, {"bestand": self.installaties})
		if klaar:
			self.kern.taken[k.kern_taak] = uitkomst(terugval=terugval, niet_gevonden=niet_gevonden)
			koppeling_mod.bijwerken(k)
		return k

	def test_ronde_start_met_de_versies_van_nu(self):
		ronde = self.start()
		doc = frappe.get_doc("BIM Botsingsronde", ronde)
		self.assertEqual(json.loads(doc.bron_versies), {self.constructie: "1", self.installaties: "1"})
		methode, pad, vraag = self.kern.verzoeken[-1]
		self.assertEqual((methode, pad), ("POST", "/v1/tools/botsingen"))
		self.assertEqual([(m["sleutel"], m["versie"]) for m in vraag["set_a"]], [(self.constructie, "1")])
		self.assertEqual((vraag["soort"], vraag["tolerantie"]), ("hard", 0.01))
		self.assertIn(f"bim/botsingen/{ronde}.json", vraag["doel"])
		# De rij botsing doet één taak tegelijk: de adressen blijven een dag geldig, ook na lang wachten.
		self.assertIn("X-Amz-Expires=86400", vraag["set_a"][0]["bron"]["url"])
		self.assertIn("X-Amz-Expires=86400", vraag["doel"])
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

	def test_een_ronde_wacht_op_een_koppeling_die_nog_loopt(self):
		eerste = self.ronde_met([("w1", "k1")])
		botsingen.zet_status(self.botsing(eerste, "w1", "k1").name, "genegeerd")
		k = self.nieuwe_versie_installaties(klaar=False)
		tweede = self.ronde_met([("w1", "k2")])
		self.assertEqual(frappe.db.get_value("BIM Botsingsronde", tweede, "status"), "bezig")
		self.assertEqual(frappe.db.count("BIM Botsing", {"ronde": tweede}), 0)
		self.kern.taken[k.kern_taak] = uitkomst(terugval=[("k1", "k2")])
		koppeling_mod.bijwerken(k)
		botsingen.bijwerken(frappe.get_doc("BIM Botsingsronde", tweede))
		self.assertEqual(self.botsing(tweede, "w1", "k2").status, "genegeerd")

	def test_een_kapotte_keten_volgt_de_botsingen_op_globalid(self):
		eerste = self.ronde_met([("w1", "k1")])
		botsingen.zet_status(self.botsing(eerste, "w1", "k1").name, "genegeerd")
		k = self.nieuwe_versie_installaties(klaar=False)
		self.kern.taken[k.kern_taak] = {"status": "fout", "fout": {"error_code": "interne_fout", "melding": "kapot"}}
		koppeling_mod.bijwerken(k)
		for _ in range(koppeling_mod.MAX_POGINGEN - 1):
			frappe.get_doc({**k.as_dict(), "name": None, "status": "fout", "kern_taak": None}).insert(ignore_permissions=True)
		tweede = self.ronde_met([("w1", "k1")])
		b = self.botsing(tweede, "w1", "k1")
		self.assertEqual((b.status, json.loads(b.element_b)["versie"]), ("genegeerd", "2"))

	def test_een_verdwenen_element_gaat_een_keer_mee_als_opgelost(self):
		self.ronde_met([("w1", "k1"), ("w2", "k2")])
		self.nieuwe_versie_installaties(niet_gevonden=["k2"])
		tweede = self.ronde_met([("w1", "k1")])
		self.assertEqual(self.botsing(tweede, "w2", "k2").status, "opgelost")
		derde = self.ronde_met([("w1", "k1")])
		self.assertEqual(frappe.db.count("BIM Botsing", {"ronde": derde}), 1)

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
