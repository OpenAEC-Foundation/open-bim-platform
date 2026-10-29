import base64

import frappe
from openaec_storage import api as opslag
from openaec_storage.tests.hulp import foutcode

from openaec_bim import issues
from openaec_bim.tests.hulp import ProjectTest

WAND = "2O2Fr$t4X7Zf8NOew3FLOH"
KANAAL = "1kTvXnbbzCWw8lcMd1dR4o"
PNG = base64.b64encode(
	base64.b64decode(
		"iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
	)
).decode()
CAMERA = {
	"camera_view_point": {"x": 10.0, "y": -5.0, "z": 3.0},
	"camera_direction": {"x": -1.0, "y": 0.5, "z": -0.2},
	"camera_up_vector": {"x": 0.0, "y": 0.0, "z": 1.0},
	"field_of_view": 60.0,
	"aspect_ratio": 1.6,
}


class TestIssues(ProjectTest):
	def topic(self, **velden):
		return issues.topic_maak(self.project, {"title": "Kanaal door wand", **velden})

	def test_project_van_maakt_het_project_bij_het_eerste_gebruik(self):
		nieuwe_map = opslag.maak_map(ruimte=self.ruimte, naam="06 Varianten")["map"]
		project = issues.project_van(nieuwe_map)
		self.assertEqual((project.name, project.ruimte, project.titel), (nieuwe_map, self.ruimte, "06 Varianten"))
		self.assertEqual(issues.project_van(nieuwe_map).name, project.name)
		frappe.set_user(self.buiten)
		self.assertRaises(frappe.PermissionError, issues.project_van, nieuwe_map)

	def test_uitbreidingen_komen_uit_het_project(self):
		ext = issues.uitbreidingen(self.project)
		self.assertEqual(ext["topic_status"], ["Open", "In behandeling", "Opgelost", "Gesloten"])
		self.assertEqual(ext["topic_type"], ["Fout", "Vraag", "Opmerking", "Botsing"])
		self.assertEqual(ext["priority"], ["Laag", "Normaal", "Hoog", "Kritiek"])
		self.assertEqual((ext["stage"], ext["topic_label"]), ([], []))
		self.assertIn(self.lezer, ext["users"])
		self.assertIn("createTopic", ext["project_actions"])

	def test_topic_maken_volgt_bcf_3(self):
		t = self.topic(topic_type="Botsing", labels=["constructie"], due_date="2026-11-30", index=4)
		self.assertTrue(t["guid"])
		self.assertEqual((t["topic_status"], t["topic_type"], t["creation_author"]), ("Open", "Botsing", self.lid))
		self.assertEqual((t["labels"], t["due_date"], t["index"]), (["constructie"], "2026-11-30", 4))
		self.assertRegex(t["creation_date"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}[+-]\d\d:\d\d$")
		self.assertTrue({"update", "createComment", "createViewpoint"} <= set(t["authorization"]["topic_actions"]))
		self.assertEqual(issues.topic(t["guid"])["title"], "Kanaal door wand")
		self.assertEqual([x["guid"] for x in issues.topics(self.project)], [t["guid"]])

	def test_een_onbekende_status_wordt_geweigerd(self):
		code = foutcode(self, frappe.ValidationError, issues.topic_maak, self.project, {"title": "x", "topic_status": "Weg"})
		self.assertEqual(code, "waarde_onbekend")
		self.assertRaises(frappe.ValidationError, issues.topic_maak, self.project, {"title": "x", "priority": "Zeer"})
		self.assertRaises(frappe.ValidationError, issues.topic_maak, self.project, {"title": " "})

	def test_toewijzen_kan_alleen_aan_wie_het_project_ziet(self):
		self.assertEqual(self.topic(assigned_to=self.lezer)["assigned_to"], self.lezer)
		self.assertRaises(frappe.ValidationError, self.topic, assigned_to=self.buiten)

	def test_lezer_mag_maken_en_reageren_maar_niet_andermans_issue_wijzigen(self):
		t = self.topic()
		frappe.set_user(self.lezer)
		self.assertEqual(issues.reactie_maak(t["guid"], {"comment": "Gezien"})["author"], self.lezer)
		self.assertEqual(issues.topic(t["guid"])["authorization"]["topic_actions"], ["createComment", "createViewpoint"])
		self.assertRaises(frappe.PermissionError, issues.topic_wijzig, t["guid"], {"title": "anders"})
		self.assertRaises(frappe.PermissionError, issues.topic_verwijder, t["guid"])
		eigen = self.topic()
		self.assertEqual(issues.topic_wijzig(eigen["guid"], {"title": "Eigen"})["title"], "Eigen")

	def test_wie_het_issue_toegewezen_is_mag_het_wijzigen(self):
		t = self.topic(assigned_to=self.lezer)
		frappe.set_user(self.lezer)
		self.assertEqual(issues.topic_wijzig(t["guid"], {"topic_status": "Opgelost"})["topic_status"], "Opgelost")

	def test_een_buitenstaander_ziet_niets(self):
		t = self.topic()
		frappe.set_user(self.buiten)
		self.assertRaises(frappe.PermissionError, issues.topics, self.project)
		self.assertRaises(frappe.PermissionError, issues.topic, t["guid"])
		self.assertRaises(frappe.PermissionError, issues.reactie_maak, t["guid"], {"comment": "Hallo"})

	def test_een_verouderde_wijziging_geeft_409(self):
		t = self.topic()
		oud = t["modified_date"]
		nieuw = issues.topic_wijzig(t["guid"], {"title": "nieuw", "modified_date": oud})
		self.assertGreater(nieuw["modified_date"], oud)
		code = foutcode(self, issues.VerouderdeVersie, issues.topic_wijzig, t["guid"], {"title": "nog nieuwer", "modified_date": oud})
		self.assertEqual(code, "issue_verouderd")
		self.assertEqual(issues.VerouderdeVersie.http_status_code, 409)
		self.assertEqual(issues.topic(t["guid"])["title"], "nieuw")

	def test_in_een_gearchiveerde_ruimte_kan_niets_meer_bij(self):
		t = self.topic()
		frappe.db.set_value("Ruimte", self.ruimte, "gearchiveerd", 1)
		self.assertEqual(issues.topic(t["guid"])["authorization"]["topic_actions"], [])
		code = foutcode(self, frappe.PermissionError, issues.topic_maak, self.project, {"title": "x"})
		self.assertEqual(code, "ruimte_gearchiveerd")
		self.assertRaises(frappe.PermissionError, issues.reactie_maak, t["guid"], {"comment": "Nog iets"})

	def test_reacties_wijzigen_en_verwijderen(self):
		t = self.topic()
		frappe.set_user(self.lezer)
		r = issues.reactie_maak(t["guid"], {"comment": "Eerste"})
		self.assertEqual(issues.reactie_wijzig(t["guid"], r["guid"], {"comment": "Beter"})["comment"], "Beter")
		frappe.set_user(self.lid)
		van_lid = issues.reactie_maak(t["guid"], {"comment": "Van het lid"})
		frappe.set_user(self.lezer)
		self.assertRaises(frappe.PermissionError, issues.reactie_wijzig, t["guid"], van_lid["guid"], {"comment": "x"})
		issues.reactie_verwijder(t["guid"], r["guid"])
		self.assertEqual([x["comment"] for x in issues.reacties(t["guid"])], ["Van het lid"])

	def test_standpunt_met_snapshot_en_selectie(self):
		self.model_klaar(self.constructie)
		self.kern.elementen = {WAND: {"klasse": "IfcWall"}}
		t = self.topic()
		sp = issues.standpunt_maak(
			t["guid"],
			{
				"perspective_camera": CAMERA,
				"snapshot": {"snapshot_type": "png", "snapshot_data": PNG},
				"components": {"selection": [{"ifc_guid": WAND}, {"ifc_guid": KANAAL}]},
			},
		)
		self.assertEqual(sp["snapshot"], {"snapshot_type": "png"})
		self.assertEqual(issues.standpunt(t["guid"], sp["guid"])["perspective_camera"], CAMERA)
		inhoud, soort = issues.snapshot(t["guid"], sp["guid"])
		self.assertEqual((inhoud, soort), (base64.b64decode(PNG), "image/png"))
		elementen = frappe.get_all(
			"BIM Issue Element", {"parent": t["guid"]}, ["globalid", "bestand", "versie"], order_by="idx asc"
		)
		self.assertEqual(
			[tuple(e.values()) for e in elementen], [(WAND, self.constructie, "1"), (KANAAL, None, None)]
		)
		self.assertEqual([x["guid"] for x in issues.standpunten(t["guid"])], [sp["guid"]])
		issues.standpunt_verwijder(t["guid"], sp["guid"])
		self.assertEqual(issues.standpunten(t["guid"]), [])

	def test_een_standpunt_zonder_snapshot_mag(self):
		t = self.topic()
		sp = issues.standpunt_maak(t["guid"], {"perspective_camera": CAMERA})
		self.assertIsNone(sp["snapshot"])
		self.assertRaises(frappe.DoesNotExistError, issues.snapshot, t["guid"], sp["guid"])

	def test_een_te_grote_of_verkeerde_snapshot_wordt_geweigerd(self):
		t = self.topic()
		groot = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"0" * (5 * 1024 * 1024)).decode()
		for snapshot in (
			{"snapshot_type": "png", "snapshot_data": groot},
			{"snapshot_type": "jpg", "snapshot_data": PNG},
			{"snapshot_type": "gif", "snapshot_data": PNG},
			{"snapshot_type": "png", "snapshot_data": "geen base64!"},
		):
			code = foutcode(self, frappe.ValidationError, issues.standpunt_maak, t["guid"], {"snapshot": snapshot})
			self.assertEqual(code, "snapshot_ongeldig")

	def test_verwante_issues_en_documentverwijzingen(self):
		t, ander = self.topic(), self.topic(title="Ander")
		self.assertEqual(issues.verwante_zet(t["guid"], [ander["guid"]]), [{"related_topic_guid": ander["guid"]}])
		self.assertEqual(issues.verwante(t["guid"]), [{"related_topic_guid": ander["guid"]}])
		self.assertRaises(frappe.ValidationError, issues.verwante_zet, t["guid"], ["bestaat-niet"])
		ref = issues.documentverwijzing_maak(t["guid"], {"url": "https://voorbeeld.nl/eis.pdf", "description": "Eis"})
		self.assertTrue(ref["guid"])
		self.assertEqual(issues.documentverwijzingen(t["guid"]), [ref])
		self.assertRaises(frappe.ValidationError, issues.documentverwijzing_maak, t["guid"], {"description": "Leeg"})

	def test_topic_verwijderen_neemt_reacties_en_standpunten_mee(self):
		t = self.topic()
		sp = issues.standpunt_maak(t["guid"], {"perspective_camera": CAMERA})
		issues.reactie_maak(t["guid"], {"comment": "Bij het standpunt", "viewpoint_guid": sp["guid"]})
		issues.topic_verwijder(t["guid"])
		self.assertFalse(frappe.db.exists("BIM Issue", t["guid"]))
		self.assertEqual(frappe.db.count("BIM Reactie", {"issue": t["guid"]}), 0)
		self.assertEqual(frappe.db.count("BIM Standpunt", {"issue": t["guid"]}), 0)
		self.assertRaises(frappe.DoesNotExistError, issues.topic, t["guid"])
