import base64
import json

import frappe
from openaec_storage import api as opslag
from openaec_storage.tests.hulp import gebruiker

from openaec_bim import api_coordinatie
from openaec_bim.tests.hulp import ProjectTest
from openaec_bim.tests import test_botsingen
from openaec_bim.tests.test_issues import CAMERA, PNG


class TestApiCoordinatie(ProjectTest):
	def setUp(self):
		super().setUp()
		self.extern = gebruiker("bimextern")
		frappe.set_user("Administrator")
		self.deling = opslag.deel(
			doel_doctype="Opslagmap", doel=self.map, soort="gebruiker", gebruiker=self.extern, rechten="lezen"
		)["deling"]
		frappe.set_user(self.lid)

	def test_een_externe_partij_via_een_deling_maakt_een_issue(self):
		frappe.set_user(self.extern)
		t = api_coordinatie.issue_bewaar(self.map, {"title": "Sparing ontbreekt"})
		self.assertTrue(t["guid"])
		self.assertEqual([x["guid"] for x in api_coordinatie.issues(self.map)], [t["guid"]])
		self.assertIn("Botsing", api_coordinatie.instellingen(self.map)["topic_type"])

	def test_na_intrekken_van_de_deling_geen_toegang(self):
		frappe.set_user(self.extern)
		t = api_coordinatie.issue_bewaar(self.map, {"title": "Voor het intrekken"})
		frappe.set_user("Administrator")
		opslag.trek_in(deling=self.deling)
		frappe.set_user(self.extern)
		self.assertRaises(frappe.PermissionError, api_coordinatie.issues, self.map)
		self.assertRaises(frappe.PermissionError, api_coordinatie.reacties, t["guid"])
		self.assertRaises(frappe.PermissionError, api_coordinatie.issue_bewaar, self.map, {"title": "Na het intrekken"})

	def test_bron_is_gastpagina_in_het_auditlog(self):
		t = api_coordinatie.issue_bewaar(self.map, {"title": "Uit de werkplek"})
		regel = frappe.get_last_doc("BIM Auditregel", {"object": t["guid"]})
		self.assertEqual((regel.handeling, regel.bron), ("aangemaakt", "gastpagina"))

	def test_issue_bewaar_werkt_een_bestaand_issue_bij(self):
		t = api_coordinatie.issue_bewaar(self.map, json.dumps({"title": "Eerst"}))
		bijgewerkt = api_coordinatie.issue_bewaar(self.map, {"guid": t["guid"], "title": "Daarna", "modified_date": t["modified_date"]})
		self.assertEqual((bijgewerkt["guid"], bijgewerkt["title"]), (t["guid"], "Daarna"))
		api_coordinatie.issue_verwijder(t["guid"])
		self.assertEqual(api_coordinatie.issues(self.map), [])

	def test_een_issue_uit_een_ander_project_wordt_niet_via_deze_map_bewaard(self):
		frappe.set_user(self.lid)
		andere_map = opslag.maak_map(ruimte=self.ruimte, naam="06 Varianten")["map"]
		t = api_coordinatie.issue_bewaar(andere_map, {"title": "Elders"})
		self.assertRaises(frappe.ValidationError, api_coordinatie.issue_bewaar, self.map, {"guid": t["guid"], "title": "x"})

	def test_reacties_standpunten_en_snapshot(self):
		t = api_coordinatie.issue_bewaar(self.map, {"title": "Met standpunt"})
		sp = api_coordinatie.standpunt_bewaar(
			t["guid"], {"perspective_camera": CAMERA, "snapshot": {"snapshot_type": "png", "snapshot_data": PNG}}
		)
		r = api_coordinatie.reactie_bewaar(t["guid"], {"comment": "Zie standpunt", "viewpoint_guid": sp["guid"]})
		self.assertEqual(api_coordinatie.reactie_bewaar(t["guid"], {"guid": r["guid"], "comment": "Zie het standpunt"})["comment"], "Zie het standpunt")
		self.assertEqual([x["comment"] for x in api_coordinatie.reacties(t["guid"])], ["Zie het standpunt"])
		self.assertEqual(api_coordinatie.snapshot(t["guid"], sp["guid"]), {"snapshot_type": "png", "snapshot_data": PNG})

	def test_bcf_export_en_import(self):
		api_coordinatie.issue_bewaar(self.map, {"title": "Heen en terug"})
		bestand = api_coordinatie.bcf_export(self.map, "3.0")["bestand"]
		self.assertEqual(api_coordinatie.bcf_import(self.map, bestand)["bijgewerkt"], 1)

	def test_botsingen_via_de_api(self):
		self.model_klaar(self.constructie)
		self.model_klaar(self.installaties)
		ronde = api_coordinatie.botsingsronde_start(
			self.map, json.dumps([{"bestand": self.constructie}]), [{"bestand": self.installaties}], "hard", "0.01"
		)["ronde"]
		self.assertEqual([(r["naam"], r["status"]) for r in api_coordinatie.botsingsrondes(self.map)], [(ronde, "wacht")])
		test_botsingen.TestBotsingen.lever(self, ronde, [("w1", "k1")])
		[b] = api_coordinatie.botsingen(ronde)
		self.assertEqual((b["status"], b["element_a"]["globalid"]), ("nieuw", "w1"))
		self.assertEqual(api_coordinatie.botsing_status(b["naam"], "actief")["status"], "actief")
		t = api_coordinatie.botsing_naar_issue(b["naam"])
		self.assertEqual(api_coordinatie.botsingen(ronde)[0]["issue"], t["guid"])
		self.assertEqual(api_coordinatie.botsingsrondes(self.map)[0]["aantal"], 1)
		frappe.set_user(self.extern)
		self.assertEqual(len(api_coordinatie.botsingen(ronde)), 1)
		self.assertRaises(frappe.PermissionError, api_coordinatie.botsing_status, b["naam"], "genegeerd")

	def test_audit_export_alleen_met_schrijfrecht(self):
		api_coordinatie.issue_bewaar(self.map, {"title": "In het log"})
		self.assertTrue(api_coordinatie.audit_export(self.map)["csv"].startswith("tijd,gebruiker,handeling"))
		frappe.set_user(self.lezer)
		self.assertRaises(frappe.PermissionError, api_coordinatie.audit_export, self.map)
		self.assertEqual(base64.b64decode(PNG)[:4], b"\x89PNG")
