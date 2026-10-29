import hashlib
import json
from unittest.mock import patch

import frappe
from openaec_storage.tests.hulp import upload

from openaec_bim import afgeleid, api, issues
from openaec_bim import koppeling as koppeling_mod
from openaec_bim.tests.hulp import ProjectTest


def uitkomst(terugval=(), niet_gevonden=(), matchrate=1.0):
	return {
		"status": "klaar",
		"voortgang": 1.0,
		"uitkomst": {
			"elementen_vorige": 100,
			"op_globalid": 80,
			"terugval": [{"van": v, "naar": n} for v, n in terugval],
			"niet_gevonden": list(niet_gevonden),
			"matchrate": matchrate,
		},
	}


class TestKoppeling(ProjectTest):
	def tweede_versie(self, bestand=None):
		"""Versie 1 omgezet, dan versie 2 in Storage en omgezet: dat start de koppeling."""
		bestand = bestand or self.constructie
		self.model_klaar(bestand, 1)
		frappe.set_user(self.lid)
		upload(self.ruimte, "constructie.ifc", b"ISO-10303-21; c2", map_naam=self.map, basis_versie=1)
		self.model_klaar(bestand, 2)
		return frappe.get_last_doc(koppeling_mod.DOCTYPE, {"bestand": bestand})

	def maak(self, van, naar, terugval=(), niet_gevonden=(), matchrate=1.0):
		return frappe.get_doc(
			{
				"doctype": koppeling_mod.DOCTYPE,
				"bestand": self.constructie,
				"van_versie": van,
				"naar_versie": naar,
				"status": "klaar",
				"matchrate": matchrate,
				"terugval": json.dumps([{"van": v, "naar": n} for v, n in terugval]),
				"niet_gevonden": json.dumps(list(niet_gevonden)),
			}
		).insert(ignore_permissions=True)

	def test_een_nieuwe_klare_versie_start_de_koppeling(self):
		k = self.tweede_versie()
		methode, pad, vraag = self.kern.verzoeken[-1]
		self.assertEqual((methode, pad), ("POST", "/v1/tools/koppelen"))
		self.assertEqual(vraag["vorige"]["sha256"], hashlib.sha256(b"SQLITE").hexdigest())
		self.assertIn("eigenschappen.sqlite", vraag["nieuwe"]["url"])
		self.assertEqual((k.van_versie, k.naar_versie, k.status), (1, 2, "wacht"))

	def test_de_eerste_versie_start_geen_koppeling(self):
		self.model_klaar(self.constructie, 1)
		self.assertNotIn("/v1/tools/koppelen", [pad for _m, pad, _j in self.kern.verzoeken])
		self.assertEqual(frappe.db.count(koppeling_mod.DOCTYPE), 0)

	def test_de_koppeling_wordt_gevolgd_tot_ze_klaar_is(self):
		k = self.tweede_versie()
		self.kern.taken[k.kern_taak] = uitkomst(terugval=[("a1", "a2")], niet_gevonden=["weg"], matchrate=0.82)
		afgeleid.volg_lopende()
		k.reload()
		self.assertEqual((k.status, k.matchrate, k.elementen_vorige, k.op_globalid), ("klaar", 0.82, 100, 80))
		self.assertEqual(json.loads(k.terugval), [{"van": "a1", "naar": "a2"}])

	def test_een_mislukte_koppeling_krijgt_de_fout(self):
		k = self.tweede_versie()
		self.kern.taken[k.kern_taak] = {"status": "fout", "fout": {"error_code": "index_ongeldig", "melding": "kapot"}}
		koppeling_mod.bijwerken(k)
		self.assertEqual((k.status, json.loads(k.fout)["error_code"]), ("fout", "index_ongeldig"))

	def test_een_koppeling_na_een_storing_van_de_kern_wordt_hersteld(self):
		from openaec_bim.kern import KernFout

		with patch("openaec_bim.kern.start_koppelen", side_effect=KernFout("kern_onbereikbaar", "weg")):
			k = self.tweede_versie()
		self.assertEqual(k.status, "fout")
		koppeling_mod.herstel(self.constructie)
		pogingen = frappe.get_all(koppeling_mod.DOCTYPE, {"bestand": self.constructie}, ["status"], order_by="creation asc")
		self.assertEqual([p.status for p in pogingen], ["fout", "wacht"])
		# Ook de tweede poging mislukt, en daarna elke nieuwe: na MAX_POGINGEN houdt het op.
		tweede = frappe.get_last_doc(koppeling_mod.DOCTYPE, {"bestand": self.constructie})
		self.kern.taken[tweede.kern_taak] = {"status": "fout", "fout": {"error_code": "interne_fout", "melding": "kapot"}}
		koppeling_mod.bijwerken(tweede)
		with patch("openaec_bim.kern.start_koppelen", side_effect=KernFout("kern_onbereikbaar", "weg")):
			for _ in range(5):
				koppeling_mod.herstel(self.constructie)
		self.assertEqual(frappe.db.count(koppeling_mod.DOCTYPE, {"bestand": self.constructie}), koppeling_mod.MAX_POGINGEN)

	def test_een_verouderde_index_wordt_opnieuw_omgezet_en_dan_gekoppeld(self):
		k = self.tweede_versie()
		self.kern.taken[k.kern_taak] = {"status": "fout", "fout": {"error_code": "vorige_index_verouderd", "melding": "oud"}}
		koppeling_mod.bijwerken(k)
		koppeling_mod.herstel(self.constructie)
		self.assertEqual(frappe.db.count(afgeleid.DOCTYPE, {"bestand": self.constructie, "versie": 1}), 2)
		koppeling_mod.herstel(self.constructie)
		self.assertEqual(frappe.db.count(koppeling_mod.DOCTYPE, {"bestand": self.constructie}), 1)
		self.model_klaar(self.constructie, 1)
		koppeling_mod.herstel(self.constructie)
		laatste = frappe.get_last_doc(koppeling_mod.DOCTYPE, {"bestand": self.constructie})
		self.assertEqual((laatste.status, laatste.van_versie, laatste.naar_versie), ("wacht", 1, 2))

	def test_huidig_volgt_de_keten(self):
		self.maak(1, 2, terugval=[("a1", "a2")])
		self.maak(2, 3, terugval=[("a2", "a3")], niet_gevonden=["b2"])
		self.assertEqual(koppeling_mod.huidig(self.constructie, "a1", 1, 3), "a3")
		self.assertEqual(koppeling_mod.huidig(self.constructie, "x", 1, 3), "x")
		self.assertIsNone(koppeling_mod.huidig(self.constructie, "b2", 2, 3))
		self.assertEqual(koppeling_mod.huidig(self.constructie, "a1", 1, 1), "a1")
		self.assertIsNone(koppeling_mod.huidig(self.constructie, "a1", 1, 4))  # versie 4 is nog niet gekoppeld

	def test_huidig_slaat_een_versie_zonder_omzetting_over(self):
		self.maak(1, 3, terugval=[("a1", "a3")])
		self.assertEqual(koppeling_mod.huidig(self.constructie, "a1", 1, 3), "a3")
		self.assertEqual(koppeling_mod.huidig(self.constructie, "a1", 2, 3), None)

	def test_project_toont_de_matchrate(self):
		k = self.tweede_versie()
		self.kern.taken[k.kern_taak] = uitkomst(matchrate=0.82)
		modellen = {m["bron"]["sleutel"]: m for m in api.project(map=self.map)["modellen"]}
		self.assertEqual(modellen[self.constructie]["koppeling"], {"vorige_versie": "1", "matchrate": 0.82})
		self.assertIsNone(modellen[self.installaties]["koppeling"])

	def test_issue_op_een_element_reist_mee_naar_de_nieuwe_versie(self):
		t = issues.topic_maak(self.project, {"title": "Wand"})
		issue = frappe.get_doc("BIM Issue", t["guid"])
		for globalid in ("a1", "weg", "zelfde"):
			issue.append("elementen", {"bestand": self.constructie, "versie": "1", "globalid": globalid})
		issue.append("elementen", {"globalid": "onbekend"})
		issue.save(ignore_permissions=True)
		self.model_klaar(self.constructie, 1)
		self.assertEqual(issues.topic(t["guid"])["elementen"][0], {"ifc_guid": "a1", "bestand": self.constructie, "versie": "1", "teruggevonden": True})
		k = self.tweede_versie()
		self.kern.taken[k.kern_taak] = uitkomst(terugval=[("a1", "a2")], niet_gevonden=["weg"])
		koppeling_mod.bijwerken(k)
		self.assertEqual(
			issues.topic(t["guid"])["elementen"],
			[
				{"ifc_guid": "a2", "bestand": self.constructie, "versie": "2", "teruggevonden": True},
				{"ifc_guid": "weg", "bestand": self.constructie, "versie": "1", "teruggevonden": False},
				{"ifc_guid": "zelfde", "bestand": self.constructie, "versie": "2", "teruggevonden": True},
				{"ifc_guid": "onbekend", "bestand": None, "versie": None, "teruggevonden": False},
			],
		)
