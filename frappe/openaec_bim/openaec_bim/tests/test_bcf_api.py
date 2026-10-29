import frappe
from frappe.tests.test_api import make_request
from frappe.utils import get_test_client
from openaec_storage import api as opslag
from openaec_storage.tests.hulp import gebruiker

from openaec_bim import issues
from openaec_bim.tests.hulp import ProjectTest


class BcfApiTest(ProjectTest):
	"""De verzoeken lopen in een eigen thread met een eigen databaseverbinding: de opzet wordt gecommit."""

	CLIENT = get_test_client(use_cookies=False)

	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		self.extern = gebruiker("bimextern")
		self.deling = opslag.deel(
			doel_doctype="Opslagmap", doel=self.map, soort="gebruiker", gebruiker=self.extern, rechten="lezen"
		)["deling"]
		self.sleutels = {u: self.api_sleutel(u) for u in (self.lid, self.lezer, self.buiten)}
		self.token_extern = self.bearer(self.extern)
		frappe.set_user(self.lid)
		frappe.db.commit()

	def tearDown(self):
		frappe.set_user("Administrator")
		for client in frappe.get_all("OAuth Client", {"app_name": "BCF-programma"}, pluck="name"):
			frappe.db.delete("OAuth Bearer Token", {"client": client})
			frappe.db.delete("OAuth Client", client)
		super().tearDown()
		frappe.db.commit()

	def api_sleutel(self, gebruiker_):
		sleutel, geheim = frappe.generate_hash(length=15), frappe.generate_hash(length=15)
		doc = frappe.get_doc("User", gebruiker_)
		doc.api_key, doc.api_secret = sleutel, geheim
		doc.save(ignore_permissions=True)
		return f"token {sleutel}:{geheim}"

	def bearer(self, gebruiker_):
		client = frappe.db.get_value("OAuth Client", {"app_name": "BCF-programma"}, "name")
		if not client:
			client = frappe.get_doc(
				{
					"doctype": "OAuth Client",
					"app_name": "BCF-programma",
					"grant_type": "Authorization Code",
					"redirect_uris": "http://localhost",
					"default_redirect_uri": "http://localhost",
					"response_type": "Code",
					"scopes": "all openid",
					"skip_authorization": 1,
				}
			).insert(ignore_permissions=True).name
		token = frappe.generate_hash()
		frappe.get_doc(
			{
				"doctype": "OAuth Bearer Token",
				"access_token": token,
				"client": client,
				"expires_in": 3600,
				"scopes": "all openid",
				"status": "Active",
				"user": gebruiker_,
			}
		).insert(ignore_permissions=True)
		return f"Bearer {token}"

	def vraag(self, methode, pad, json=None, als=None, token=None):
		kop = token or (self.sleutels[als or self.lid] if als is not False else None)
		kwargs = {"headers": {"Authorization": kop} if kop else {}}
		if json is not None:
			kwargs["json"] = json
		frappe.db.commit()
		return make_request(target=getattr(self.CLIENT, methode.lower()), args=(pad,), kwargs=kwargs)

	def get(self, pad, **kw):
		return self.vraag("GET", pad, **kw)

	def post(self, pad, json, **kw):
		return self.vraag("POST", pad, json=json, **kw)

	def put(self, pad, json, **kw):
		return self.vraag("PUT", pad, json=json, **kw)

	def delete(self, pad, **kw):
		return self.vraag("DELETE", pad, **kw)

	@property
	def topics(self):
		return f"/bcf/3.0/projects/{self.map}/topics"


class TestBcfApi(BcfApiTest):
	def test_versions_noemt_bcf_3_0_en_foundation_1_1(self):
		r = self.get("/foundation/versions", als=False)
		self.assertEqual(r.status_code, 200)
		versies = {(v["api_id"], v["version_id"]): v for v in r.json["versions"]}
		self.assertIn(("foundation", "1.1"), versies)
		self.assertTrue(versies[("bcf", "3.0")]["api_base_url"].endswith("/bcf/3.0"))

	def test_auth_noemt_de_oauth2_adressen_van_de_site(self):
		r = self.get("/foundation/1.1/auth", als=False)
		self.assertEqual(r.status_code, 200)
		self.assertTrue(r.json["oauth2_auth_url"].endswith("/api/method/frappe.integrations.oauth2.authorize"))
		self.assertTrue(r.json["oauth2_token_url"].endswith("/api/method/frappe.integrations.oauth2.get_token"))
		self.assertEqual(r.json["supported_oauth2_flows"], ["authorization_code_grant"])

	def test_current_user_met_sleutel_en_met_token(self):
		self.assertEqual(self.get("/foundation/1.1/current-user").json["id"], self.lid)
		self.assertEqual(self.get("/foundation/1.0/current-user", token=self.token_extern).json["id"], self.extern)

	def test_zonder_inloggen_401(self):
		self.assertEqual(self.get("/bcf/3.0/projects", als=False).status_code, 401)
		self.assertEqual(self.get("/foundation/1.1/current-user", als=False).status_code, 401)
		self.assertEqual(self.get("/bcf/3.0/projects", token="Bearer verkeerd").status_code, 401)

	def test_projecten_zijn_de_modelmappen_met_leesrecht(self):
		self.assertEqual([p["project_id"] for p in self.get("/bcf/3.0/projects").json], [self.map])
		self.assertEqual(self.get("/bcf/3.0/projects", als=self.buiten).json, [])
		p = self.get(f"/bcf/3.0/projects/{self.map}").json
		self.assertEqual(p["name"], "05 BIM-modellen")
		self.assertIn("createTopic", p["authorization"]["project_actions"])
		self.assertEqual(self.get(f"/bcf/3.0/projects/{self.map}", als=self.buiten).status_code, 403)
		self.assertEqual(self.get("/bcf/3.0/projects/bestaat-niet").status_code, 404)
		ext = self.get(f"/bcf/3.0/projects/{self.map}/extensions").json
		self.assertEqual(ext["topic_status"], ["Open", "In behandeling", "Opgelost", "Gesloten"])

	def test_projectnaam_wijzigen_vraagt_schrijfrecht(self):
		r = self.put(f"/bcf/3.0/projects/{self.map}", {"name": "Coördinatie"})
		self.assertEqual((r.status_code, r.json["name"]), (200, "Coördinatie"))
		self.assertEqual(self.put(f"/bcf/3.0/projects/{self.map}", {"name": "x"}, als=self.lezer).status_code, 403)

	def test_topic_aanmaken_lezen_en_lijst(self):
		r = self.post(self.topics, {"title": "Via de API", "topic_type": "Vraag"})
		self.assertEqual(r.status_code, 201)
		guid = r.json["guid"]
		self.assertEqual(self.get(f"{self.topics}/{guid}").json["title"], "Via de API")
		self.assertNotIn("elementen", self.get(f"{self.topics}/{guid}").json)
		self.assertEqual([t["guid"] for t in self.get(self.topics).json], [guid])
		self.assertEqual(frappe.get_last_doc("BIM Auditregel", {"object": guid}).bron, "bcf-api")

	def test_een_ongeldig_topic_geeft_400(self):
		r = self.post(self.topics, {"title": "x", "topic_status": "Weg"})
		self.assertEqual(r.status_code, 400)
		self.assertIn("message", r.json)
		self.assertEqual(self.post(self.topics, ["geen", "object"]).status_code, 400)

	def test_topic_wijzigen_en_verwijderen(self):
		guid = self.post(self.topics, {"title": "Eerst"}).json["guid"]
		r = self.put(f"{self.topics}/{guid}", {"title": "Daarna", "topic_status": "Opgelost"})
		self.assertEqual((r.status_code, r.json["title"], r.json["topic_status"]), (200, "Daarna", "Opgelost"))
		self.assertEqual(self.delete(f"{self.topics}/{guid}", als=self.lezer).status_code, 403)
		self.assertEqual(self.delete(f"{self.topics}/{guid}").status_code, 200)
		self.assertEqual(self.get(f"{self.topics}/{guid}").status_code, 404)

	def test_een_topic_van_een_ander_project_is_hier_onbekend(self):
		frappe.set_user(self.lid)
		andere_map = opslag.maak_map(ruimte=self.ruimte, naam="06 Varianten")["map"]
		t = issues.topic_maak(issues.project_van(andere_map), {"title": "Elders"})
		self.assertEqual(self.get(f"{self.topics}/{t['guid']}").status_code, 404)

	def test_reactie_via_de_api(self):
		guid = self.post(self.topics, {"title": "Met reactie"}).json["guid"]
		r = self.post(f"{self.topics}/{guid}/comments", {"comment": "Akkoord"}, als=self.lezer)
		self.assertEqual((r.status_code, r.json["author"]), (201, self.lezer))
		reactie = r.json["guid"]
		self.assertEqual(self.put(f"{self.topics}/{guid}/comments/{reactie}", {"comment": "Akkoord, met opmerking"}, als=self.lezer).json["comment"], "Akkoord, met opmerking")
		self.assertEqual([c["comment"] for c in self.get(f"{self.topics}/{guid}/comments").json], ["Akkoord, met opmerking"])
		self.assertEqual(self.get(f"{self.topics}/{guid}/comments/{reactie}").json["topic_guid"], guid)
		self.assertEqual(self.delete(f"{self.topics}/{guid}/comments/{reactie}", als=self.lezer).status_code, 200)
		self.assertEqual(self.get(f"{self.topics}/{guid}/comments").json, [])

	def test_zonder_toegang_tot_de_modelmap_403_ook_met_token(self):
		self.assertEqual(self.get(self.topics, token=self.token_extern).status_code, 200)
		frappe.set_user("Administrator")
		opslag.trek_in(deling=self.deling)
		frappe.db.commit()
		self.assertEqual(self.get(self.topics, token=self.token_extern).status_code, 403)
		self.assertEqual(self.get("/bcf/3.0/projects", token=self.token_extern).json, [])

	def test_verouderde_wijziging_409(self):
		t = self.post(self.topics, {"title": "Gelijktijdig"}).json
		self.assertEqual(self.put(f"{self.topics}/{t['guid']}", {"title": "Eerste", "modified_date": t["modified_date"]}).status_code, 200)
		r = self.put(f"{self.topics}/{t['guid']}", {"title": "Tweede", "modified_date": t["modified_date"]})
		self.assertEqual(r.status_code, 409)
		self.assertEqual(self.get(f"{self.topics}/{t['guid']}").json["title"], "Eerste")

	def test_een_onbekend_pad_geeft_404(self):
		self.assertEqual(self.get(f"/bcf/3.0/projects/{self.map}/onbekend").status_code, 404)
		self.assertEqual(self.vraag("PATCH", self.topics).status_code, 404)
