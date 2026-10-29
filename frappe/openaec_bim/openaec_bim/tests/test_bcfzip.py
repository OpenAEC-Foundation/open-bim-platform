import base64
import copy
import io
import json
import os
import zipfile

import frappe
from frappe.tests import UnitTestCase
from openaec_storage import api as opslag
from openaec_storage.tests.hulp import foutcode, upload

from openaec_bim import afgeleid, bcfzip, issues
from openaec_bim.tests.hulp import ProjectTest
from openaec_bim.tests.test_issues import CAMERA, KANAAL, PNG, WAND

G1, G2 = "a0c1f6a2-5a40-4b8e-9d60-1c0f4b1c0001", "a0c1f6a2-5a40-4b8e-9d60-1c0f4b1c0002"
V1, V2 = "b0c1f6a2-5a40-4b8e-9d60-1c0f4b1c0001", "b0c1f6a2-5a40-4b8e-9d60-1c0f4b1c0002"
C1, D1, D2 = "c0c1f6a2-5a40-4b8e-9d60-1c0f4b1c0001", "d0c1f6a2-5a40-4b8e-9d60-1c0f4b1c0001", "d0c1f6a2-5a40-4b8e-9d60-1c0f4b1c0002"
PUNT = {"x": 1.5, "y": -2.0, "z": 3.25}


def standpunt(guid=V1):
	return {
		"guid": guid,
		"index": 1,
		"perspective_camera": CAMERA,
		"lines": [{"start_point": PUNT, "end_point": {"x": 2.0, "y": 0.0, "z": 0.0}}],
		"clipping_planes": [{"location": PUNT, "direction": {"x": 0.0, "y": 0.0, "z": -1.0}}],
		"components": {
			"selection": [{"ifc_guid": WAND, "originating_system": "Ontwerpprogramma", "authoring_tool_id": "123"}],
			"coloring": [{"color": "#ff0000", "components": [{"ifc_guid": KANAAL}]}],
			"visibility": {
				"default_visibility": False,
				"exceptions": [{"ifc_guid": WAND}],
				"view_setup_hints": {"spaces_visible": False, "space_boundaries_visible": False, "openings_visible": True},
			},
		},
		"snapshot": {"snapshot_type": "png", "snapshot_data": PNG},
	}


def bovenaanzicht():
	return {
		"guid": V2,
		"index": 2,
		"orthogonal_camera": {**{k: CAMERA[k] for k in CAMERA if k != "field_of_view"}, "view_to_world_scale": 25.0},
		"bitmaps": [
			{"bitmap_type": "png", "bitmap_data": PNG, "location": PUNT, "normal": PUNT, "up": PUNT, "height": 2.5}
		],
	}


def volledig_topic(guid=G1, **velden):
	return {
		"guid": guid,
		"server_assigned_id": "ISSUE-1",
		"topic_type": "Botsing",
		"topic_status": "Open",
		"reference_links": ["https://voorbeeld.nl/issue/1"],
		"title": "Kanaal door wand",
		"priority": "Hoog",
		"index": 1,
		"labels": ["constructie", "installaties"],
		"creation_date": "2026-10-20T09:00:00.000+02:00",
		"creation_author": "architect@voorbeeld.nl",
		"modified_date": "2026-10-21T10:00:00.000+02:00",
		"modified_author": "constructeur@voorbeeld.nl",
		"due_date": "2026-11-30",
		"assigned_to": "installateur@voorbeeld.nl",
		"stage": "Ontwerp",
		"description": "Het kanaal gaat door de dragende wand.",
		"bim_snippet": {
			"snippet_type": "Kostenraming",
			"is_external": True,
			"reference": "https://voorbeeld.nl/raming.xml",
			"reference_schema": "https://voorbeeld.nl/raming.xsd",
		},
		"document_references": [
			{"guid": D1, "url": "https://voorbeeld.nl/eis.pdf", "description": "Eis"},
			{"guid": D2, "document_guid": "e0c1f6a2-5a40-4b8e-9d60-1c0f4b1c0001", "description": "Intern"},
		],
		"related_topics": [{"related_topic_guid": G2}],
		"comments": [
			{
				"guid": C1,
				"date": "2026-10-21T11:00:00.000+02:00",
				"author": "constructeur@voorbeeld.nl",
				"comment": "Graag een sparing.",
				"viewpoint_guid": V1,
				"modified_date": "2026-10-21T11:30:00.000+02:00",
				"modified_author": "constructeur@voorbeeld.nl",
			}
		],
		"viewpoints": [standpunt(), bovenaanzicht()],
		**velden,
	}


def normaliseer(waarde):
	"""Zonder lege waarden en `authorization`: die staan niet in een .bcfzip."""
	if isinstance(waarde, dict):
		return {k: normaliseer(v) for k, v in waarde.items() if v not in (None, [], {}) and k != "authorization"}
	if isinstance(waarde, list):
		return [normaliseer(v) for v in waarde]
	return waarde


def zonder(topic, *sleutels):
	"""Een kopie zonder de sleutels (ook in geneste standpunten), voor wat BCF 2.1 niet kent."""
	topic = copy.deepcopy(topic)

	def weg(d):
		if isinstance(d, dict):
			for s in sleutels:
				d.pop(s, None)
			for v in d.values():
				weg(v)
		elif isinstance(d, list):
			for v in d:
				weg(v)

	weg(topic)
	return topic


BCF_21_VAN_ELDERS = {
	"bcf.version": '<?xml version="1.0" encoding="UTF-8"?><Version VersionId="2.1" '
	'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"><DetailedVersion>2.1</DetailedVersion></Version>',
	f"{G1}/markup.bcf": f"""<?xml version="1.0" encoding="UTF-8"?>
<Markup xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <Topic Guid="{G1}" TopicType="Clash" TopicStatus="Active">
    <Title>Leiding door ligger</Title>
    <Labels>Constructie</Labels>
    <Labels>Werktuigbouw</Labels>
    <CreationDate>2020-01-02T10:00:00Z</CreationDate>
    <CreationAuthor>elders@voorbeeld.nl</CreationAuthor>
    <DocumentReference Guid="{D1}" isExternal="true">
      <ReferencedDocument>https://voorbeeld.nl/tekening.pdf</ReferencedDocument>
    </DocumentReference>
    <RelatedTopic Guid="{G2}"/>
  </Topic>
  <Comment Guid="{C1}">
    <Date>2020-01-02T11:00:00Z</Date>
    <Author>elders@voorbeeld.nl</Author>
    <Comment>Zie het standpunt.</Comment>
    <Viewpoint Guid="{V1}"/>
  </Comment>
  <Viewpoints Guid="{V1}">
    <Viewpoint>viewpoint.bcfv</Viewpoint>
    <Snapshot>snapshot.png</Snapshot>
  </Viewpoints>
</Markup>""",
	f"{G1}/viewpoint.bcfv": f"""<?xml version="1.0" encoding="UTF-8"?>
<VisualizationInfo Guid="{V1}">
  <Components>
    <Selection><Component IfcGuid="{WAND}"/></Selection>
    <Visibility DefaultVisibility="true"/>
    <Coloring><Color Color="FF00FF00"><Component IfcGuid="{KANAAL}"/></Color></Coloring>
  </Components>
  <PerspectiveCamera>
    <CameraViewPoint><X>1</X><Y>2</Y><Z>3</Z></CameraViewPoint>
    <CameraDirection><X>0</X><Y>1</Y><Z>0</Z></CameraDirection>
    <CameraUpVector><X>0</X><Y>0</Y><Z>1</Z></CameraUpVector>
    <FieldOfView>60</FieldOfView>
  </PerspectiveCamera>
</VisualizationInfo>""",
}


def maak_zip(bestanden: dict) -> bytes:
	buf = io.BytesIO()
	with zipfile.ZipFile(buf, "w") as z:
		for naam, inhoud in bestanden.items():
			z.writestr(naam, inhoud)
	return buf.getvalue()


class TestBcfzipBestand(UnitTestCase):
	def test_3_0_heen_en_terug_zonder_verlies(self):
		topics = [volledig_topic(), volledig_topic(G2, title="Tweede", related_topics=[], viewpoints=[], comments=[])]
		inhoud = bcfzip.schrijf(topics, "3.0")
		self.assertIn('VersionId="3.0"', zipfile.ZipFile(io.BytesIO(inhoud)).read("bcf.version").decode())
		self.assertEqual(normaliseer(bcfzip.lees(inhoud)), normaliseer(topics))

	def test_2_1_heen_en_terug(self):
		topics = [volledig_topic()]
		inhoud = bcfzip.schrijf(topics, "2.1")
		self.assertIn('VersionId="2.1"', zipfile.ZipFile(io.BytesIO(inhoud)).read("bcf.version").decode())
		verwacht = zonder(topics[0], "aspect_ratio", "server_assigned_id")
		self.assertEqual(normaliseer(bcfzip.lees(inhoud)), normaliseer([verwacht]))

	def test_een_2_1_bestand_van_een_ander_programma(self):
		snapshot = base64.b64decode(PNG)
		[topic] = bcfzip.lees(maak_zip({**BCF_21_VAN_ELDERS, f"{G1}/snapshot.png": snapshot}))
		self.assertEqual((topic["title"], topic["topic_type"], topic["topic_status"]), ("Leiding door ligger", "Clash", "Active"))
		self.assertEqual(topic["labels"], ["Constructie", "Werktuigbouw"])
		self.assertEqual(topic["document_references"], [{"guid": D1, "url": "https://voorbeeld.nl/tekening.pdf"}])
		self.assertEqual(topic["related_topics"], [{"related_topic_guid": G2}])
		self.assertEqual(topic["comments"][0]["viewpoint_guid"], V1)
		[sp] = topic["viewpoints"]
		self.assertEqual(sp["snapshot"], {"snapshot_type": "png", "snapshot_data": PNG})
		self.assertEqual(sp["components"]["selection"], [{"ifc_guid": WAND}])
		self.assertEqual(sp["components"]["coloring"], [{"color": "#FF00FF00", "components": [{"ifc_guid": KANAAL}]}])
		self.assertEqual(sp["perspective_camera"]["camera_view_point"], {"x": 1.0, "y": 2.0, "z": 3.0})

	def visualisatie(self, versie, sp):
		import xml.etree.ElementTree as ET

		inhoud = bcfzip.schrijf([volledig_topic(viewpoints=[sp], comments=[])], versie)
		return ET.fromstring(zipfile.ZipFile(io.BytesIO(inhoud)).read(f"{G1}/{sp['guid']}.bcfv"))

	def test_de_onderdelen_volgen_de_xsd(self):
		sp = standpunt()
		drie = self.visualisatie("3.0", sp).find("Components")
		self.assertEqual([e.tag for e in drie], ["Selection", "Visibility", "Coloring"])
		self.assertEqual([e.tag for e in drie.find("Visibility")], ["ViewSetupHints", "Exceptions"])
		twee = self.visualisatie("2.1", sp).find("Components")
		self.assertEqual([e.tag for e in twee], ["ViewSetupHints", "Selection", "Visibility", "Coloring"])

	def test_zichtbaarheid_is_er_altijd_en_staat_standaard_aan(self):
		sp = {"guid": V1, "perspective_camera": CAMERA, "components": {"selection": [{"ifc_guid": WAND}]}}
		for versie in ("2.1", "3.0"):
			zicht = self.visualisatie(versie, sp).find("Components/Visibility")
			self.assertEqual(zicht.get("DefaultVisibility"), "true")

	def test_zonder_defaultvisibility_is_de_zichtbaarheid_uit(self):
		bestanden = dict(BCF_21_VAN_ELDERS)
		bestanden[f"{G1}/viewpoint.bcfv"] = bestanden[f"{G1}/viewpoint.bcfv"].replace('<Visibility DefaultVisibility="true"/>', "<Visibility/>")
		[topic] = bcfzip.lees(maak_zip(bestanden))
		self.assertEqual(topic["viewpoints"][0]["components"]["visibility"], {"default_visibility": False})

	def test_geen_plafond_op_het_aantal_topics(self):
		topics = [volledig_topic(f"a0c1f6a2-5a40-4b8e-9d60-{i:012d}", viewpoints=[]) for i in range(300)]
		self.assertEqual(len(bcfzip.lees(bcfzip.schrijf(topics, "3.0"))), 300)

	def test_geen_bcfzip_wordt_geweigerd(self):
		self.assertRaises(bcfzip.BcfOngeldig, bcfzip.lees, b"geen zip")
		self.assertRaises(bcfzip.BcfOngeldig, bcfzip.lees, maak_zip({f"{G1}/markup.bcf": "<Markup><Topic"}))


class TestBcfImportExport(ProjectTest):
	def bcfzip(self, topics, naam="issues.bcfzip", versie="3.0"):
		frappe.set_user(self.lid)
		return upload(self.ruimte, naam, bcfzip.schrijf(topics, versie), map_naam=self.map)["bestand"]

	def test_import_maakt_nieuwe_issues_en_werkt_bestaande_bij(self):
		topic = volledig_topic(assigned_to=self.lezer, labels=[], stage=None, topic_status="In behandeling")
		uit = issues.importeer(self.project, self.bcfzip([topic]))
		self.assertEqual((uit["nieuw"], uit["bijgewerkt"]), (1, 0))
		t = issues.topic(G1)
		self.assertEqual((t["title"], t["creation_author"], t["assigned_to"]), (topic["title"], "architect@voorbeeld.nl", self.lezer))
		self.assertTrue(t["creation_date"].startswith("2026-10-20"))
		self.assertEqual([r["comment"] for r in issues.reacties(G1)], ["Graag een sparing."])
		self.assertEqual(issues.reacties(G1)[0]["author"], "constructeur@voorbeeld.nl")
		self.assertEqual([s["guid"] for s in issues.standpunten(G1)], [V1, V2])
		self.assertEqual(issues.snapshot(G1, V1)[0], base64.b64decode(PNG))
		self.assertEqual(issues.documentverwijzingen(G1), topic["document_references"])
		self.assertIn(WAND, frappe.get_all("BIM Issue Element", {"parent": G1}, pluck="globalid"))
		self.assertTrue(frappe.db.exists("BIM Auditregel", {"handeling": "geïmporteerd", "object": G1}))

		gewijzigd = {**topic, "title": "Kanaal door wand, aangepast", "modified_date": "2099-01-01T10:00:00.000+01:00"}
		uit = issues.importeer(self.project, self.bcfzip([gewijzigd], "nieuw.bcfzip"))
		self.assertEqual((uit["nieuw"], uit["bijgewerkt"]), (0, 1))
		self.assertEqual(issues.topic(G1)["title"], "Kanaal door wand, aangepast")
		self.assertEqual(len(issues.reacties(G1)), 1)

	def test_een_import_overschrijft_geen_nieuwere_wijziging(self):
		topic = volledig_topic(viewpoints=[], assigned_to=None)
		issues.importeer(self.project, self.bcfzip([topic]))
		issues.topic_wijzig(G1, {"topic_status": "Gesloten", "title": "Na de export gewijzigd"})
		uit = issues.importeer(self.project, self.bcfzip([topic], "terug.bcfzip"))
		self.assertEqual((uit["bijgewerkt"], uit["verouderd"]), (0, 1))
		self.assertEqual((issues.topic(G1)["topic_status"], issues.topic(G1)["title"]), ("Gesloten", "Na de export gewijzigd"))
		nieuwer = {**topic, "title": "Later gewijzigd in het andere programma", "modified_date": "2099-01-01T10:00:00.000+01:00"}
		uit = issues.importeer(self.project, self.bcfzip([nieuwer], "nieuwer.bcfzip"))
		self.assertEqual((uit["bijgewerkt"], uit["verouderd"]), (1, 0))
		self.assertEqual(issues.topic(G1)["title"], "Later gewijzigd in het andere programma")

	def test_een_import_zoekt_de_elementen_in_een_keer_op(self):
		self.model_klaar(self.constructie)
		self.kern.elementen = {WAND: {"klasse": "IfcWall"}, KANAAL: {"klasse": "IfcDuctSegment"}}
		topics = [
			volledig_topic(G1, viewpoints=[{**standpunt(V1), "components": {"selection": [{"ifc_guid": WAND}]}}], comments=[]),
			volledig_topic(G2, viewpoints=[{**standpunt(V2), "components": {"selection": [{"ifc_guid": KANAAL}]}}], comments=[]),
		]
		issues.importeer(self.project, self.bcfzip(topics))
		vragen = [p for _m, p, _j in self.kern.verzoeken if p == "/v1/tools/eigenschappen"]
		self.assertEqual(len(vragen), 1)
		self.assertEqual(frappe.get_all("BIM Issue Element", {"parent": G2}, pluck="bestand"), [self.constructie])

	def test_verwante_issues_uit_hetzelfde_bestand(self):
		topics = [volledig_topic(viewpoints=[], comments=[]), volledig_topic(G2, title="Tweede", viewpoints=[], comments=[])]
		issues.importeer(self.project, self.bcfzip(topics))
		self.assertEqual(issues.verwante(G1), [{"related_topic_guid": G2}])

	def test_import_vult_onbekende_waarden_aan_en_logt_dat(self):
		topic = volledig_topic(topic_status="Wacht op architect", topic_type="Clash", priority="Hoog", viewpoints=[])
		uit = issues.importeer(self.project, self.bcfzip([topic]))
		self.assertEqual(uit["nieuw"], 1)
		project = frappe.get_doc("BIM Project", self.project)
		self.assertIn("Wacht op architect", project.statussen.splitlines())
		self.assertIn("Clash", project.soorten.splitlines())
		self.assertEqual(project.labels or "", "")  # een lege lijst laat alles toe en blijft leeg
		regel = frappe.get_all(
			"BIM Auditregel", {"handeling": "instellingen aangevuld", "project": self.project}, ["voor", "na"]
		)[0]
		self.assertNotIn("Wacht op architect", json.loads(regel.voor)["statussen"])
		self.assertIn("Wacht op architect", json.loads(regel.na)["statussen"])

	def test_een_toewijzing_aan_wie_het_project_niet_ziet_vervalt(self):
		uit = issues.importeer(self.project, self.bcfzip([volledig_topic(viewpoints=[])]))
		self.assertEqual(uit["toewijzingen_vervallen"], 1)
		self.assertIsNone(issues.topic(G1)["assigned_to"])

	def test_alleen_een_schrijver_mag_importeren(self):
		bestand = self.bcfzip([volledig_topic()])
		frappe.set_user(self.lezer)
		self.assertRaises(frappe.PermissionError, issues.importeer, self.project, bestand)

	def test_import_in_een_ander_project_maakt_kopieen(self):
		bestand = self.bcfzip([volledig_topic(viewpoints=[standpunt()]), volledig_topic(G2, title="Tweede", viewpoints=[], comments=[])])
		issues.importeer(self.project, bestand)
		frappe.set_user(self.lid)
		andere_map = opslag.maak_map(ruimte=self.ruimte, naam="06 Kopie")["map"]
		ander = issues.project_van(andere_map)
		uit = issues.importeer(ander, bestand)
		self.assertEqual((uit["nieuw"], uit["gekopieerd"], uit["overgeslagen"]), (2, 2, 0))
		kopieen = {t["title"]: t for t in issues.topics(ander)}
		self.assertEqual(set(kopieen), {"Kanaal door wand", "Tweede"})
		kopie = kopieen["Kanaal door wand"]
		self.assertNotIn(kopie["guid"], (G1, G2))
		self.assertEqual([r["comment"] for r in issues.reacties(kopie["guid"])], ["Graag een sparing."])
		[sp] = issues.standpunten(kopie["guid"])
		self.assertNotEqual(sp["guid"], V1)
		self.assertEqual(issues.reacties(kopie["guid"])[0]["viewpoint_guid"], sp["guid"])
		self.assertEqual(issues.verwante(kopie["guid"]), [{"related_topic_guid": kopieen["Tweede"]["guid"]}])
		self.assertEqual(len(issues.topics(self.project)), 2)

	def test_een_kapot_bestand_geeft_een_foutcode(self):
		bestand = upload(self.ruimte, "kapot.bcfzip", b"geen zip", map_naam=self.map)["bestand"]
		code = foutcode(self, frappe.ValidationError, issues.importeer, self.project, bestand)
		self.assertEqual(code, "bcfzip_ongeldig")

	def test_export_zet_een_bcfzip_in_de_modelmap(self):
		t = issues.topic_maak(self.project, {"title": "Voor de export", "topic_type": "Vraag"})
		issues.reactie_maak(t["guid"], {"comment": "Antwoord volgt"})
		issues.standpunt_maak(t["guid"], {"perspective_camera": CAMERA, "snapshot": {"snapshot_type": "png", "snapshot_data": PNG}})
		uit = issues.exporteer_zip(self.project, "3.0")
		bestand = frappe.db.get_value("Opslagbestand", uit["bestand"], ["naam", "map"], as_dict=True)
		self.assertTrue(bestand.naam.startswith("05 BIM-modellen issues ") and bestand.naam.endswith(".bcfzip"))
		self.assertEqual(bestand.map, self.map)
		[topic] = bcfzip.lees(self.inhoud(uit["bestand"]))
		self.assertEqual((topic["title"], topic["topic_type"]), ("Voor de export", "Vraag"))
		self.assertEqual(topic["comments"][0]["comment"], "Antwoord volgt")
		self.assertEqual(topic["viewpoints"][0]["snapshot"]["snapshot_data"], PNG)

	def test_een_export_groter_dan_1_mib_past_ook(self):
		t = issues.topic_maak(self.project, {"title": "Grote schermafbeelding"})
		groot = base64.b64encode(b"\x89PNG\r\n\x1a\n" + os.urandom(1536 * 1024)).decode()
		issues.standpunt_maak(t["guid"], {"snapshot": {"snapshot_type": "png", "snapshot_data": groot}})
		uit = issues.exporteer_zip(self.project, "2.1")
		[topic] = bcfzip.lees(self.inhoud(uit["bestand"]))
		self.assertEqual(topic["viewpoints"][0]["snapshot"]["snapshot_data"], groot)

	def inhoud(self, bestand):
		versie = frappe.db.get_value("Opslagbestand", bestand, "huidige_versie")
		sleutel = frappe.db.get_value("Bestandsversie", {"bestand": bestand, "volgnummer": versie}, "s3_sleutel")
		return afgeleid.lees_object(sleutel)
