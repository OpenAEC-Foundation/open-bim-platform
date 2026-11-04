import json

import frappe
from openaec_storage import api as opslag

from openaec_bim import audit
from openaec_bim.tests.hulp import ProjectTest


def maak_issue(project, titel):
	return frappe.get_doc(
		{"doctype": "BIM Issue", "guid": frappe.generate_hash(length=32), "project": project, "titel": titel, "status": "Open"}
	).insert(ignore_permissions=True)


class TestAudit(ProjectTest):
	def regels(self, obj):
		return frappe.get_all(
			"BIM Auditregel", {"object": obj}, ["handeling", "voor", "na", "bron", "gebruiker", "project"], order_by="tijd asc, creation asc"
		)

	def test_een_issue_aanmaken_wijzigen_en_verwijderen_staat_in_het_log(self):
		issue = maak_issue(self.project, "Wand botst met kanaal")
		issue.status = "In behandeling"
		issue.save(ignore_permissions=True)
		naam = issue.name
		issue.delete(ignore_permissions=True)
		regels = self.regels(naam)
		self.assertEqual([r.handeling for r in regels], ["aangemaakt", "gewijzigd", "verwijderd"])
		self.assertEqual(json.loads(regels[1].voor), {"status": "Open"})
		self.assertEqual(json.loads(regels[1].na), {"status": "In behandeling"})
		self.assertEqual(regels[0].gebruiker, self.lid)
		self.assertEqual(regels[0].project, self.project)

	def test_opslaan_zonder_wijziging_geeft_geen_regel(self):
		issue = maak_issue(self.project, "Zonder wijziging")
		issue.labels = '["constructie"]'
		issue.vervaldatum = "2026-11-30"
		issue.save(ignore_permissions=True)
		issue = frappe.get_doc("BIM Issue", issue.name)
		issue.save(ignore_permissions=True)
		self.assertEqual([r.handeling for r in self.regels(issue.name)], ["aangemaakt", "gewijzigd"])

	def test_een_auditregel_kan_niet_gewijzigd_of_verwijderd_worden(self):
		maak_issue(self.project, "Iets")
		frappe.set_user("Administrator")
		regel = frappe.get_last_doc("BIM Auditregel")
		regel.handeling = "anders"
		self.assertRaises(frappe.PermissionError, regel.save, ignore_permissions=True)
		self.assertRaises(frappe.PermissionError, frappe.delete_doc, "BIM Auditregel", regel.name, ignore_permissions=True)

	def test_de_bron_komt_uit_de_flags(self):
		frappe.flags.bim_bron = "bcf-api"
		issue = maak_issue(self.project, "Via de API")
		self.assertEqual(self.regels(issue.name)[0].bron, "bcf-api")
		frappe.flags.bim_bron = None
		self.assertEqual(self.regels(maak_issue(self.project, "Achtergrond").name)[0].bron, "achtergrond")

	def test_een_reactie_hoort_bij_het_project_van_het_issue(self):
		issue = maak_issue(self.project, "Met reactie")
		reactie = frappe.get_doc(
			{"doctype": "BIM Reactie", "guid": frappe.generate_hash(length=32), "issue": issue.name, "tekst": "Gezien"}
		).insert(ignore_permissions=True)
		self.assertEqual(self.regels(reactie.name)[0].project, self.project)

	def test_exporteer_geeft_csv_per_project(self):
		hier = maak_issue(self.project, "In de export")
		frappe.set_user(self.lid)
		andere_map = opslag.maak_map(ruimte=self.ruimte, naam="06 Andere modellen")["map"]
		frappe.set_user("Administrator")
		ander = frappe.get_doc({"doctype": "BIM Project", "modelmap": andere_map, "ruimte": self.ruimte}).insert(
			ignore_permissions=True
		)
		elders = maak_issue(ander.name, "Elders")
		regels = audit.exporteer(self.project).splitlines()
		self.assertEqual(regels[0], "tijd,gebruiker,handeling,doctype,object,bron")
		self.assertIn(f",{self.lid},aangemaakt,BIM Issue,{hier.name},achtergrond", "\n".join(regels))
		self.assertNotIn(elders.name, "\n".join(regels))
