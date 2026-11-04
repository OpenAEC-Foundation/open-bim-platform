import json

import frappe
from openaec_storage import api as opslag
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

	def lever(self, ronde, paren, velden=None, a_bestand=None, b_bestand=None):
		"""De kern is klaar: het resultaat voor de versies van de ronde staat in de bucket. Een paar is (a, b) of
		(a, b, velden); `velden` zijn de velden van de kern per botsing, `verdieping` hoort bij element a."""
		doc = frappe.get_doc("BIM Botsingsronde", ronde)
		versies = json.loads(doc.bron_versies)
		a_bestand, b_bestand = a_bestand or self.constructie, b_bestand or self.installaties
		resultaat = []
		for paar in paren:
			a, b = paar[:2]
			extra = {**(velden or {}), **(paar[2] if len(paar) > 2 else {})}
			verdieping = extra.pop("verdieping", None)
			element_a = {"sleutel": a_bestand, "versie": versies[a_bestand], "globalid": a, "klasse": "IfcWall"}
			if verdieping:
				element_a["verdieping"] = verdieping
			resultaat.append(
				{
					"a": element_a,
					"b": {"sleutel": b_bestand, "versie": versies[b_bestand], "globalid": b, "klasse": "IfcDuctSegment"},
					"punt": [1.0, 2.0, 3.0],
					"afstand": 0.05,
					**extra,
				}
			)
		s3.zet(doc.resultaat, json.dumps(resultaat).encode())
		self.kern.taken[doc.kern_taak] = {"status": "klaar", "voortgang": 1.0, "uitkomst": {"aantal": len(paren)}}
		botsingen.bijwerken(doc)
		return ronde

	def ronde_met(self, paren, velden=None):
		return self.lever(self.start(), paren, velden)

	def rij(self, ronde, globalid):
		"""De rij van de ronde met dit element als element a."""
		for naam in frappe.get_all("BIM Botsing", {"ronde": ronde}, pluck="name"):
			doc = frappe.get_doc("BIM Botsing", naam)
			if json.loads(doc.element_a)["globalid"] == globalid:
				return doc
		raise AssertionError(f"geen rij voor {globalid}")

	def samenvatting(self, ronde):
		return json.loads(frappe.db.get_value("BIM Botsingsronde", ronde, "samenvatting"))

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

	def controle(self, **extra):
		return {
			"set_a": [{"bestand": self.constructie}],
			"set_b": [{"bestand": self.installaties}],
			"soort": "hard",
			"tolerantie": 0.0,
			**extra,
		}

	def test_een_ronde_met_voorinstelling_hoort_bij_haar_reeks(self):
		eerste = botsingen.start_controles(self.project, [self.controle()], voorinstelling="harde")
		self.lever(eerste, [("w1", "k1")])
		tweede = botsingen.start_controles(self.project, [self.controle(tolerantie=0.01)], voorinstelling="harde")
		doc = frappe.get_doc("BIM Botsingsronde", tweede)
		self.assertEqual((doc.reeks, doc.vorige_ronde, doc.voorinstelling), ("harde", eerste, "harde"))

	def test_zonder_voorinstelling_is_de_reeks_de_sets_en_de_soort(self):
		sets = ([{"bestand": self.constructie}], [{"bestand": self.installaties}])
		a = botsingen.start(self.project, *sets, "hard", 0.0)
		self.lever(a, [("w1", "k1")])
		b = botsingen.start(self.project, *sets, "hard", 0.05)
		c = botsingen.start(self.project, *sets, "afstand", 0.05)
		self.assertEqual(frappe.db.get_value("BIM Botsingsronde", b, "vorige_ronde"), a)
		self.assertTrue(frappe.db.get_value("BIM Botsingsronde", a, "reeks").startswith("sets:"))
		self.assertFalse(frappe.db.get_value("BIM Botsingsronde", c, "vorige_ronde"))

	def test_te_veel_controles_of_een_vreemd_bestand_wordt_geweigerd(self):
		with self.assertRaises(frappe.ValidationError):
			botsingen.start_controles(self.project, [self.controle()] * 31)
		with self.assertRaises(frappe.ValidationError):
			botsingen.start_controles(self.project, [])
		with self.assertRaises(frappe.ValidationError):
			botsingen.start_controles(self.project, [{**self.controle(), "set_a": [{"bestand": "bestaat-niet"}]}])
		with self.assertRaises(frappe.ValidationError):
			botsingen.start_controles(self.project, [self.controle(ernst="enorm")])
		with self.assertRaises(frappe.ValidationError):
			botsingen.start_controles(self.project, [self.controle(soort="dubbel", tolerantie=2)])

	def test_de_kern_krijgt_de_controles_met_adressen_en_versies(self):
		botsingen.start_controles(self.project, [self.controle(regel="r", ernst="kritiek", alleen_tussen_modellen=True)])
		controle = self.kern.laatste_botsingen["controles"][0]
		self.assertEqual((controle["regel"], controle["ernst"], controle["alleen_tussen_modellen"]), ("r", "kritiek", True))
		self.assertEqual((controle["set_a"][0]["sleutel"], controle["set_a"][0]["versie"]), (self.constructie, "1"))
		self.assertIn("bron", controle["set_a"][0])

	def test_soort_is_gemengd_bij_verschillende_soorten(self):
		naam = botsingen.start_controles(self.project, [self.controle(), self.controle(soort="afstand", tolerantie=0.05)])
		doc = frappe.get_doc("BIM Botsingsronde", naam)
		self.assertEqual(doc.soort, "gemengd")
		self.assertEqual(len(json.loads(doc.regels)), 2)
		self.assertEqual(len(json.loads(doc.set_a)), 1)
		dubbel = botsingen.start_controles(self.project, [self.controle(soort="dubbel")], titel=None, voorinstelling="dubbele")
		self.assertEqual(frappe.db.get_value("BIM Botsingsronde", dubbel, "soort"), "dubbel")
		self.assertTrue(frappe.db.get_value("BIM Botsingsronde", dubbel, "titel").startswith("dubbele "))

	def test_bijwerken_neemt_de_voortgang_over(self):
		ronde = self.start()
		doc = frappe.get_doc("BIM Botsingsronde", ronde)
		self.kern.taken[doc.kern_taak] = {"status": "bezig", "voortgang": 0.4}
		botsingen.bijwerken(doc)
		doc.reload()
		self.assertEqual((doc.status, doc.voortgang), ("bezig", 0.4))
		self.kern.taken[doc.kern_taak] = {"status": "bezig", "voortgang": 0.7}
		botsingen.bijwerken(doc)
		self.assertEqual(frappe.db.get_value("BIM Botsingsronde", ronde, "voortgang"), 0.7)
		json_ronde = botsingen.ronde_naar_json(frappe.get_doc("BIM Botsingsronde", ronde))
		for veld in ("regels", "voorinstelling", "reeks", "voortgang", "samenvatting"):
			self.assertIn(veld, json_ronde)
		self.assertEqual(json_ronde["voortgang"], 0.7)

	def test_ronde_start_met_de_versies_van_nu(self):
		ronde = self.start()
		doc = frappe.get_doc("BIM Botsingsronde", ronde)
		self.assertEqual(json.loads(doc.bron_versies), {self.constructie: "1", self.installaties: "1"})
		methode, pad, vraag = self.kern.verzoeken[-1]
		self.assertEqual((methode, pad), ("POST", "/v1/tools/botsingen"))
		[controle] = vraag["controles"]
		self.assertEqual([(m["sleutel"], m["versie"]) for m in controle["set_a"]], [(self.constructie, "1")])
		self.assertEqual((controle["soort"], controle["tolerantie"]), ("hard", 0.01))
		self.assertIn(f"bim/botsingen/{ronde}.json", vraag["doel"])
		# De rij botsing doet één taak tegelijk: de adressen blijven een dag geldig, ook na lang wachten.
		self.assertIn("X-Amz-Expires=86400", controle["set_a"][0]["bron"]["url"])
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

	def test_status_geaccepteerd_wordt_aanvaard_en_onbekend_geweigerd(self):
		b = self.botsing(self.ronde_met([("w1", "k1")]), "w1", "k1")
		self.assertEqual(botsingen.zet_status(b.name, "geaccepteerd")["status"], "geaccepteerd")
		self.assertRaises(frappe.ValidationError, botsingen.zet_status, b.name, "onzin")
		self.assertEqual(frappe.db.get_value("BIM Botsing", b.name, "status"), "geaccepteerd")

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

	def test_een_nieuwe_botsing_is_nieuw_met_een_nummer(self):
		ronde = self.ronde_met([("w2", "k2"), ("w1", "k1")])
		doc = self.rij(ronde, "w1")
		self.assertEqual((doc.status, doc.ontwikkeling), ("nieuw", "nieuw"))
		self.assertEqual(self.rij(ronde, "w1").nummer, 1)
		self.assertEqual(self.rij(ronde, "w2").nummer, 2)

	def test_nieuw_en_actief_worden_actief_en_blijven(self):
		self.ronde_met([("w1", "k1")])
		tweede = self.ronde_met([("w1", "k1")])
		self.assertEqual((self.rij(tweede, "w1").status, self.rij(tweede, "w1").ontwikkeling), ("actief", "blijft"))
		derde = self.ronde_met([("w1", "k1")])
		self.assertEqual((self.rij(derde, "w1").status, self.rij(derde, "w1").ontwikkeling), ("actief", "blijft"))

	def test_een_beslissing_blijft_gelijk_als_de_botsing_blijft(self):
		for status in ("bevestigd", "geaccepteerd", "genegeerd"):
			ronde = self.ronde_met([("w1", "k1")])
			frappe.db.set_value("BIM Botsing", self.rij(ronde, "w1").name, "status", status)
			volgende = self.ronde_met([("w1", "k1")])
			self.assertEqual((self.rij(volgende, "w1").status, self.rij(volgende, "w1").ontwikkeling), (status, "blijft"))

	def test_een_opgeloste_botsing_die_terugkomt_is_actief_en_terug(self):
		self.ronde_met([("w1", "k1")])
		weg = self.ronde_met([])
		self.assertEqual(self.rij(weg, "w1").status, "opgelost")
		terug = self.ronde_met([("w1", "k1")])
		self.assertEqual((self.rij(terug, "w1").status, self.rij(terug, "w1").ontwikkeling), ("actief", "terug"))
		self.assertEqual(self.samenvatting(terug)["terug"], 1)

	def test_een_botsing_die_niet_meer_gevonden_is_wordt_opgelost_en_weg(self):
		for status in ("nieuw", "bevestigd", "genegeerd"):
			ronde = self.ronde_met([("w1", "k1")])
			frappe.db.set_value("BIM Botsing", self.rij(ronde, "w1").name, "status", status)
			weg = self.ronde_met([])
			self.assertEqual((self.rij(weg, "w1").status, self.rij(weg, "w1").ontwikkeling), ("opgelost", "weg"))

	def test_een_opgeloste_botsing_die_wegblijft_is_eerder_weg_en_telt_niet_mee(self):
		self.ronde_met([("w1", "k1"), ("w2", "k2")])
		self.ronde_met([("w1", "k1")])
		derde = self.ronde_met([("w1", "k1")])
		self.assertEqual((self.rij(derde, "w2").status, self.rij(derde, "w2").ontwikkeling), ("opgelost", "eerder_weg"))
		s = self.samenvatting(derde)
		self.assertEqual((s["totaal"], s["weg"], s["per_status"]["opgelost"]), (1, 0, 1))
		self.assertEqual(frappe.db.get_value("BIM Botsingsronde", derde, "aantal"), 1)
		# En komt hij terug, dan krijgt hij zijn nummer terug.
		nummer = self.rij(derde, "w2").nummer
		vierde = self.ronde_met([("w1", "k1"), ("w2", "k2")])
		self.assertEqual((self.rij(vierde, "w2").ontwikkeling, self.rij(vierde, "w2").nummer), ("terug", nummer))

	def test_de_velden_van_de_kern_worden_ingelezen(self):
		velden = {
			"soort": "afstand",
			"regel": "Constructie × Installaties",
			"emmer": "aangrenzend",
			"emmer_reden": "vulling",
			"ernst": "klein",
			"categorie": "constructie × installaties",
			"raster": "C-4",
			"ruimte": "Gang 1",
			"verdieping": "00 begane grond",
		}
		ronde = self.ronde_met([("w1", "k1")], velden=velden)
		doc = self.rij(ronde, "w1")
		for veld, waarde in velden.items():
			self.assertEqual(doc.get(veld), waarde, veld)
		self.assertEqual(json.loads(doc.element_a)["verdieping"], "00 begane grond")
		uit = botsingen.naar_json(doc)
		self.assertEqual((uit["emmer"], uit["ontwikkeling"], uit["nummer"], uit["raster"]), ("aangrenzend", "nieuw", 1, "C-4"))

	def test_besluit_reden_en_nummer_gaan_mee(self):
		ronde = self.ronde_met([("w1", "k1"), ("w2", "k2")])
		rij = self.rij(ronde, "w1")
		frappe.db.set_value("BIM Botsing", rij.name, {"status": "genegeerd", "reden": "Is bedoeld"})
		volgende = self.ronde_met([("w1", "k1"), ("w3", "k3")])
		nu = self.rij(volgende, "w1")
		assert (nu.status, nu.reden, nu.nummer, nu.ontwikkeling) == ("genegeerd", "Is bedoeld", rij.nummer, "blijft")
		assert self.rij(volgende, "w3").nummer == 3 and self.rij(volgende, "w3").ontwikkeling == "nieuw"

	def test_weg_neemt_de_velden_over_en_telt_niet_in_de_emmers(self):
		self.ronde_met([("w1", "k1")], velden={"emmer": "contact", "ernst": "klein", "verdieping": "00"})
		volgende = self.ronde_met([])
		rij = self.rij(volgende, "w1")
		assert (rij.status, rij.ontwikkeling, rij.emmer, rij.verdieping) == ("opgelost", "weg", "contact", "00")
		s = json.loads(frappe.db.get_value("BIM Botsingsronde", volgende, "samenvatting"))
		assert s["totaal"] == 0 and sum(s["per_emmer"].values()) == 0 and s["weg"] == 1

	def test_een_lege_ronde_zonder_vorige_is_gewoon_klaar(self):
		ronde = self.ronde_met([])
		self.assertEqual(frappe.db.get_value("BIM Botsingsronde", ronde, "status"), "klaar")
		self.assertEqual(frappe.db.get_value("BIM Botsingsronde", ronde, "aantal"), 0)
		s = self.samenvatting(ronde)
		self.assertEqual((s["totaal"], s["open"], s["nieuw"], s["blijft"], s["terug"], s["weg"]), (0, 0, 0, 0, 0, 0))
		self.assertEqual(s["per_emmer"], {"beoordelen": 0, "contact": 0, "aangrenzend": 0})
		self.assertEqual((s["per_categorie"], s["per_ernst"], s["per_status"], s["regels_gewijzigd"]), ({}, {}, {}, False))

	def test_samenvatting_open_telt_alleen_de_emmer_beoordelen(self):
		paren = [
			("w1", "k1", {"emmer": "beoordelen", "ernst": "kritiek", "categorie": "a"}),
			("w2", "k2", {"emmer": "contact", "ernst": "klein", "categorie": "b"}),
			("w3", "k3", {"emmer": "beoordelen", "ernst": "groot", "categorie": "a"}),
			("w4", "k4", {"emmer": "beoordelen", "ernst": "klein", "categorie": "a"}),
			("w5", "k5", {"emmer": "aangrenzend", "ernst": "klein", "categorie": "b"}),
		]
		eerste = self.ronde_met(paren)
		frappe.db.set_value("BIM Botsing", self.rij(eerste, "w3").name, "status", "geaccepteerd")
		frappe.db.set_value("BIM Botsing", self.rij(eerste, "w4").name, "status", "bevestigd")
		tweede = self.ronde_met(paren)
		s = self.samenvatting(tweede)
		self.assertEqual((s["totaal"], s["open"]), (5, 2))
		self.assertEqual(s["per_ernst"], {"kritiek": 1, "klein": 1})
		self.assertEqual(s["per_emmer"], {"beoordelen": 3, "contact": 1, "aangrenzend": 1})
		self.assertEqual(sum(s["per_emmer"].values()), s["totaal"])
		self.assertEqual(s["per_categorie"], {"a": 3, "b": 2})
		self.assertEqual(s["per_status"], {"actief": 3, "geaccepteerd": 1, "bevestigd": 1})
		self.assertEqual((s["blijft"], s["nieuw"], s["regels_gewijzigd"]), (5, 0, False))

	def test_een_oud_resultaat_zonder_nieuwe_velden_wordt_gelezen(self):
		ronde = self.ronde_met([("w1", "k1")])
		doc = self.rij(ronde, "w1")
		self.assertEqual((doc.emmer, doc.soort, doc.ernst, doc.regel), ("beoordelen", "hard", None, None))
		self.assertEqual(self.samenvatting(ronde)["per_emmer"]["beoordelen"], 1)
		# Een vorige rij in de oude vorm: lege nieuwe velden.
		frappe.db.set_value("BIM Botsing", doc.name, {"ontwikkeling": "", "nummer": 0, "emmer": ""})
		volgende = self.ronde_met([("w1", "k1"), ("w2", "k2")])
		self.assertEqual((self.rij(volgende, "w1").status, self.rij(volgende, "w1").ontwikkeling), ("actief", "blijft"))
		self.assertEqual(sorted(self.rij(volgende, g).nummer for g in ("w1", "w2")), [1, 2])
		frappe.db.set_value("BIM Botsing", self.rij(volgende, "w1").name, "emmer", "")
		weg = self.ronde_met([])
		self.assertEqual(self.rij(weg, "w1").emmer, "beoordelen")

	def test_de_discipline_is_de_submap_of_anders_de_bestandsnaam(self):
		frappe.set_user(self.lid)
		sub = opslag.maak_map(ruimte=self.ruimte, naam="Constructie", bovenliggende=self.map)["map"]
		wand = upload(self.ruimte, "wand.ifc", b"ISO-10303-21; w", map_naam=sub)["bestand"]
		self.model_klaar(wand)
		ronde = botsingen.start(self.project, [{"bestand": wand}], [{"bestand": self.installaties}], "hard", 0.01)
		self.lever(ronde, [("w1", "k1")], a_bestand=wand)
		self.assertEqual(self.rij(ronde, "w1").disciplines, "Constructie × installaties")
		# Modellen direct in de modelmap: de bestandsnaam zonder .ifc.
		direct = self.ronde_met([("w1", "k1")])
		self.assertEqual(self.rij(direct, "w1").disciplines, "constructie × installaties")

	def test_een_issue_sluit_als_de_botsing_weg_is_en_heropent(self):
		ronde = self.ronde_met([("w1", "k1")])
		rij = self.rij(ronde, "w1")
		issue = botsingen.naar_issue(rij.name)["guid"]
		frappe.db.set_value("BIM Issue", issue, "status", "In behandeling")
		weg = self.ronde_met([])
		assert frappe.db.get_value("BIM Issue", issue, "status") == "Opgelost"
		assert self.rij(weg, "w1").issue_status_voor == "In behandeling"
		terug = self.ronde_met([("w1", "k1")])
		assert frappe.db.get_value("BIM Issue", issue, "status") == "In behandeling"
		assert self.rij(terug, "w1").ontwikkeling == "terug" and not self.rij(terug, "w1").issue_status_voor
		# beide keren een reactie
		assert frappe.db.count("BIM Reactie", {"issue": issue}) == 2
		self.assertEqual(frappe.get_last_doc("BIM Reactie", {"issue": issue}).owner, "Botsingsronde")

	def test_geen_heropening_na_een_eigen_wijziging(self):
		ronde = self.ronde_met([("w1", "k1")])
		issue = botsingen.naar_issue(self.rij(ronde, "w1").name)["guid"]
		self.ronde_met([])
		self.assertEqual(frappe.db.get_value("BIM Issue", issue, "status"), "Opgelost")
		frappe.db.set_value("BIM Issue", issue, "status", "Gesloten")
		terug = self.ronde_met([("w1", "k1")])
		self.assertEqual(frappe.db.get_value("BIM Issue", issue, "status"), "Gesloten")
		self.assertEqual(frappe.db.count("BIM Reactie", {"issue": issue}), 1)
		self.assertFalse(self.rij(terug, "w1").issue_status_voor)

	def test_een_dicht_issue_blijft_dicht_en_bewaart_niets(self):
		ronde = self.ronde_met([("w1", "k1")])
		issue = botsingen.naar_issue(self.rij(ronde, "w1").name)["guid"]
		frappe.db.set_value("BIM Issue", issue, "status", "Gesloten")
		weg = self.ronde_met([])
		self.assertEqual(frappe.db.get_value("BIM Issue", issue, "status"), "Gesloten")
		self.assertFalse(self.rij(weg, "w1").issue_status_voor)
		self.assertEqual(frappe.db.count("BIM Reactie", {"issue": issue}), 0)

	def test_een_gewijzigde_ronde_sluit_geen_issues(self):
		eerste = botsingen.start_controles(self.project, [self.controle()])
		self.lever(eerste, [("w1", "k1")])
		issue = botsingen.naar_issue(self.rij(eerste, "w1").name)["guid"]
		frappe.db.set_value("BIM Issue", issue, "status", "In behandeling")
		tweede = botsingen.start_controles(self.project, [self.controle(tolerantie=0.05)])
		self.assertEqual(frappe.db.get_value("BIM Botsingsronde", tweede, "vorige_ronde"), eerste)
		self.lever(tweede, [])
		self.assertEqual(frappe.db.get_value("BIM Issue", issue, "status"), "In behandeling")
		rij = self.rij(tweede, "w1")
		self.assertEqual((rij.status, rij.ontwikkeling, rij.issue, rij.issue_status_voor), ("opgelost", "weg", issue, None))
		self.assertTrue(self.samenvatting(tweede)["regels_gewijzigd"])
		self.assertEqual(frappe.db.count("BIM Reactie", {"issue": issue}), 0)
		# Beslissingen gaan wel mee.
		derde = botsingen.start_controles(self.project, [self.controle(tolerantie=0.1)])
		self.lever(derde, [("w1", "k1")])
		self.assertEqual(self.rij(derde, "w1").issue, issue)

	def test_zonder_status_opgelost_de_laatste_van_het_project(self):
		frappe.db.set_value("BIM Project", self.project, "statussen", "Open\nGesloten")
		ronde = self.ronde_met([("w1", "k1")])
		issue = botsingen.naar_issue(self.rij(ronde, "w1").name)["guid"]
		weg = self.ronde_met([])
		self.assertEqual(frappe.db.get_value("BIM Issue", issue, "status"), "Gesloten")
		self.assertEqual(self.rij(weg, "w1").issue_status_voor, "Open")
		self.ronde_met([("w1", "k1")])
		self.assertEqual(frappe.db.get_value("BIM Issue", issue, "status"), "Open")

	def test_een_verwijderd_issue_stopt_het_inlezen_niet(self):
		ronde = self.ronde_met([("w1", "k1")])
		issue = botsingen.naar_issue(self.rij(ronde, "w1").name)["guid"]
		frappe.db.delete("BIM Issue", {"name": issue})
		weg = self.ronde_met([])
		self.assertEqual(self.rij(weg, "w1").ontwikkeling, "weg")
		self.assertFalse(self.rij(weg, "w1").issue)
