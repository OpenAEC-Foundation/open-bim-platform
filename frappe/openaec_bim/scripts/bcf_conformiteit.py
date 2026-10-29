"""Conformiteitstest van de BCF-API 3.0 en de Foundation API 1.1 van een klantsite.

Draait de aanroepen uit de specificatie van buildingSMART tegen een draaiende site, met een eigen topic dat aan het
eind weer verwijderd wordt, en controleert daarna of de topics zonder verlies heen en terug gaan als .bcfzip in BCF
2.1 en 3.0. Schrijft een rapport in Markdown; de afsluitcode is 1 als een stap faalt.

    python bcf_conformiteit.py --site https://klant.example --sleutel "token <api_key>:<api_secret>" \\
        --project <id van de modelmap> [--host <sitenaam>] [--uit rapport.md]

`--sleutel` is de Authorization-kop: een API-sleutel (`token ...`) of een OAuth2-token (`Bearer ...`) van een
gebruiker met schrijfrecht op de modelmap. `--host` zet de Host-kop (een site achter een ander adres).
"""

from __future__ import annotations

import argparse
import base64
import copy
import importlib.util
import sys
import time
from datetime import datetime
from pathlib import Path

import requests

PNG = base64.b64decode(
	"iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
)
WAND, KANAAL = "2O2Fr$t4X7Zf8NOew3FLOH", "1kTvXnbbzCWw8lcMd1dR4o"
CAMERA = {
	"camera_view_point": {"x": 12.0, "y": -4.0, "z": 3.0},
	"camera_direction": {"x": -1.0, "y": 0.5, "z": -0.25},
	"camera_up_vector": {"x": 0.0, "y": 0.0, "z": 1.0},
	"field_of_view": 60.0,
	"aspect_ratio": 1.6,
}
COMPONENTEN = {
	"selection": [{"ifc_guid": WAND}],
	"coloring": [{"color": "#ff0000", "components": [{"ifc_guid": KANAAL}]}],
	"visibility": {"default_visibility": True, "exceptions": [{"ifc_guid": KANAAL}]},
}


def laad_bcfzip():
	"""bcfzip.py van de app, zonder Frappe te laden (alleen de standaardbibliotheek)."""
	pad = Path(__file__).resolve().parents[1] / "openaec_bim" / "bcfzip.py"
	spec = importlib.util.spec_from_file_location("bcfzip", pad)
	module = importlib.util.module_from_spec(spec)
	spec.loader.exec_module(module)
	return module


class Fout(Exception):
	pass


class Proef:
	def __init__(self, site: str, sleutel: str, host: str | None):
		self.site = site.rstrip("/")
		self.sessie = requests.Session()
		self.sessie.headers["Authorization"] = sleutel
		if host:
			self.sessie.headers["Host"] = host
		self.host = host
		self.stappen: list[tuple[str, bool, str]] = []

	def vraag(self, methode: str, pad: str, json=None, verwacht: int = 200, zonder_sleutel: bool = False):
		koppen = {"Authorization": ""} if zonder_sleutel else {}
		r = self.sessie.request(methode, self.site + pad, json=json, headers=koppen, timeout=60)
		if r.status_code != verwacht:
			raise Fout(f"{methode} {pad}: {r.status_code}, verwacht {verwacht}: {r.text[:200]}")
		return r

	def stap(self, naam: str, functie) -> object:
		try:
			uitkomst = functie()
		except Fout as fout:
			self.stappen.append((naam, False, str(fout)))
			return None
		except (requests.RequestException, KeyError, TypeError, ValueError, AssertionError) as fout:
			self.stappen.append((naam, False, f"{type(fout).__name__}: {fout}"))
			return None
		self.stappen.append((naam, True, ""))
		return uitkomst


def eis(voorwaarde: bool, melding: str) -> None:
	if not voorwaarde:
		raise Fout(melding)


def normaliseer(waarde):
	if isinstance(waarde, dict):
		return {k: normaliseer(v) for k, v in waarde.items() if v not in (None, [], {}) and k != "authorization"}
	if isinstance(waarde, list):
		return [normaliseer(v) for v in waarde]
	return waarde


def zonder(waarde, *sleutels):
	waarde = copy.deepcopy(waarde)

	def weg(d):
		if isinstance(d, dict):
			for s in sleutels:
				d.pop(s, None)
			for v in d.values():
				weg(v)
		elif isinstance(d, list):
			for v in d:
				weg(v)

	weg(waarde)
	return waarde


def draai(p: Proef, project: str) -> None:
	bcf = f"/bcf/3.0/projects/{project}"
	t = {}

	def versions():
		v = {(x["api_id"], x["version_id"]): x for x in p.vraag("GET", "/foundation/versions", zonder_sleutel=True).json()["versions"]}
		eis(("bcf", "3.0") in v and ("foundation", "1.1") in v, f"versies: {sorted(v)}")
		eis(v[("bcf", "3.0")]["api_base_url"].endswith("/bcf/3.0"), "api_base_url van bcf 3.0")

	def auth():
		a = p.vraag("GET", "/foundation/1.1/auth", zonder_sleutel=True).json()
		for veld in ("oauth2_auth_url", "oauth2_token_url", "http_basic_supported", "supported_oauth2_flows"):
			eis(veld in a, f"auth mist {veld}")
		eis(set(a["supported_oauth2_flows"]) <= {"authorization_code_grant", "implicit_grant", "resource_owner_password_credentials_grant"}, "onbekende flow")

	def current_user():
		u = p.vraag("GET", "/foundation/1.1/current-user").json()
		eis(bool(u.get("id")) and "name" in u, f"current-user: {u}")

	def zonder_aanmelden():
		p.vraag("GET", "/bcf/3.0/projects", verwacht=401, zonder_sleutel=True)

	def projecten():
		lijst = p.vraag("GET", "/bcf/3.0/projects").json()
		eis(any(x["project_id"] == project for x in lijst), f"{project} niet in /projects")
		x = p.vraag("GET", bcf).json()
		eis({"project_id", "name", "authorization"} <= set(x) and "project_actions" in x["authorization"], f"project: {x}")
		eis("createTopic" in x["authorization"]["project_actions"], "createTopic ontbreekt")

	def extensions():
		e = p.vraag("GET", f"{bcf}/extensions").json()
		for veld in ("topic_type", "topic_status", "topic_label", "snippet_type", "priority", "users", "stage", "project_actions", "topic_actions", "comment_actions"):
			eis(veld in e, f"extensions mist {veld}")
		t["ext"] = e

	def topic_maken():
		e = t["ext"]
		data = {
			"title": "Conformiteit: kanaal door wand",
			"topic_type": (e["topic_type"] or [None])[0],
			"topic_status": (e["topic_status"] or [None])[0],
			"priority": (e["priority"] or [None])[0],
			"description": "Gemaakt door de conformiteitstest; wordt aan het eind verwijderd.",
			"due_date": "2030-01-31",
			"reference_links": ["https://voorbeeld.nl/issue"],
		}
		r = p.vraag("POST", f"{bcf}/topics", {k: v for k, v in data.items() if v is not None}, verwacht=201).json()
		eis(r["title"] == data["title"] and r.get("guid") and r.get("creation_date"), f"topic: {r}")
		t["topic"] = r
		t["tweede"] = p.vraag("POST", f"{bcf}/topics", {"title": "Conformiteit: verwant"}, verwacht=201).json()

	def topic_lezen():
		g = t["topic"]["guid"]
		eis(p.vraag("GET", f"{bcf}/topics/{g}").json()["guid"] == g, "GET topic")
		eis(any(x["guid"] == g for x in p.vraag("GET", f"{bcf}/topics").json()), "topic niet in de lijst")
		p.vraag("GET", f"{bcf}/topics/00000000-0000-0000-0000-000000000000", verwacht=404)

	def topic_wijzigen():
		g, oud = t["topic"]["guid"], t["topic"]["modified_date"]
		time.sleep(0.01)
		r = p.vraag("PUT", f"{bcf}/topics/{g}", {"title": "Conformiteit: kanaal door dragende wand", "modified_date": oud}).json()
		eis(r["title"].endswith("dragende wand"), "PUT topic")
		p.vraag("PUT", f"{bcf}/topics/{g}", {"title": "verouderd", "modified_date": oud}, verwacht=409)

	def reacties():
		g = t["topic"]["guid"]
		c = p.vraag("POST", f"{bcf}/topics/{g}/comments", {"comment": "Graag een sparing."}, verwacht=201).json()
		eis(c["topic_guid"] == g and c.get("author") and c.get("date"), f"comment: {c}")
		eis(p.vraag("GET", f"{bcf}/topics/{g}/comments/{c['guid']}").json()["comment"] == "Graag een sparing.", "GET comment")
		c = p.vraag("PUT", f"{bcf}/topics/{g}/comments/{c['guid']}", {"comment": "Graag een sparing van 300 mm."}).json()
		eis(c["comment"].endswith("300 mm."), "PUT comment")
		eis(len(p.vraag("GET", f"{bcf}/topics/{g}/comments").json()) == 1, "comments-lijst")
		t["reactie"] = c

	def standpunten():
		g = t["topic"]["guid"]
		vp = p.vraag(
			"POST",
			f"{bcf}/topics/{g}/viewpoints",
			{
				"index": 1,
				"perspective_camera": CAMERA,
				"clipping_planes": [{"location": {"x": 0.0, "y": 0.0, "z": 1.5}, "direction": {"x": 0.0, "y": 0.0, "z": -1.0}}],
				"snapshot": {"snapshot_type": "png", "snapshot_data": base64.b64encode(PNG).decode()},
				"components": COMPONENTEN,
			},
			verwacht=201,
		).json()
		eis(vp["snapshot"] == {"snapshot_type": "png"} and "snapshot_data" not in vp["snapshot"], "snapshot in viewpoint")
		eis(p.vraag("GET", f"{bcf}/topics/{g}/viewpoints/{vp['guid']}").json()["perspective_camera"] == CAMERA, "camera")
		s = p.vraag("GET", f"{bcf}/topics/{g}/viewpoints/{vp['guid']}/snapshot")
		eis(s.headers["Content-Type"].startswith("image/png") and s.content == PNG, "snapshot")
		basis = f"{bcf}/topics/{g}/viewpoints/{vp['guid']}"
		eis(p.vraag("GET", f"{basis}/selection").json() == {"selection": COMPONENTEN["selection"]}, "selection")
		eis(p.vraag("GET", f"{basis}/coloring").json() == {"coloring": COMPONENTEN["coloring"]}, "coloring")
		eis(p.vraag("GET", f"{basis}/visibility").json() == {"visibility": COMPONENTEN["visibility"]}, "visibility")
		t["standpunt"] = vp

	def verwante():
		g, ander = t["topic"]["guid"], t["tweede"]["guid"]
		r = p.vraag("PUT", f"{bcf}/topics/{g}/related_topics", [{"related_topic_guid": ander}]).json()
		eis(r == [{"related_topic_guid": ander}], f"related_topics: {r}")
		eis(p.vraag("GET", f"{bcf}/topics/{g}/related_topics").json() == r, "GET related_topics")

	def documentverwijzingen():
		g = t["topic"]["guid"]
		d = p.vraag("POST", f"{bcf}/topics/{g}/document_references", {"url": "https://voorbeeld.nl/eis.pdf", "description": "Eis"}, verwacht=201).json()
		d = p.vraag("PUT", f"{bcf}/topics/{g}/document_references/{d['guid']}", {"url": "https://voorbeeld.nl/eis.pdf", "description": "Eis, versie 2"}).json()
		eis(d["description"] == "Eis, versie 2", "PUT document_reference")
		eis(p.vraag("GET", f"{bcf}/topics/{g}/document_references").json() == [d], "GET document_references")

	def bcfzip_heen_en_terug():
		bcfzip = laad_bcfzip()
		g = t["topic"]["guid"]
		topic = p.vraag("GET", f"{bcf}/topics/{g}").json()
		topic["comments"] = [{k: v for k, v in c.items() if k not in ("authorization", "topic_guid")} for c in p.vraag("GET", f"{bcf}/topics/{g}/comments").json()]
		standpunten_ = []
		for vp in p.vraag("GET", f"{bcf}/topics/{g}/viewpoints").json():
			basis = f"{bcf}/topics/{g}/viewpoints/{vp['guid']}"
			vp["components"] = {
				"selection": p.vraag("GET", f"{basis}/selection").json()["selection"],
				"coloring": p.vraag("GET", f"{basis}/coloring").json()["coloring"],
				"visibility": p.vraag("GET", f"{basis}/visibility").json()["visibility"],
			}
			vp["snapshot"] = {"snapshot_type": "png", "snapshot_data": base64.b64encode(p.vraag("GET", f"{basis}/snapshot").content).decode()}
			standpunten_.append(vp)
		topic["viewpoints"] = standpunten_
		topic["related_topics"] = p.vraag("GET", f"{bcf}/topics/{g}/related_topics").json()
		topic["document_references"] = p.vraag("GET", f"{bcf}/topics/{g}/document_references").json()
		for versie, kent_niet in (("3.0", ()), ("2.1", ("aspect_ratio", "server_assigned_id"))):
			terug = bcfzip.lees(bcfzip.schrijf([topic], versie))
			eis(normaliseer(terug) == normaliseer([zonder(topic, *kent_niet)]), f"BCF {versie} heen en terug verschilt")

	def opruimen():
		g = t["topic"]["guid"]
		vp = t["standpunt"]["guid"]
		p.vraag("DELETE", f"{bcf}/topics/{g}/comments/{t['reactie']['guid']}")
		c = p.vraag("POST", f"{bcf}/topics/{g}/comments", {"comment": "Bij het standpunt", "viewpoint_guid": vp}, verwacht=201).json()
		p.vraag("DELETE", f"{bcf}/topics/{g}/viewpoints/{vp}", verwacht=409)
		p.vraag("DELETE", f"{bcf}/topics/{g}/comments/{c['guid']}")
		p.vraag("DELETE", f"{bcf}/topics/{g}/viewpoints/{vp}")
		for topic in (t["topic"], t["tweede"]):
			p.vraag("DELETE", f"{bcf}/topics/{topic['guid']}")
			p.vraag("GET", f"{bcf}/topics/{topic['guid']}", verwacht=404)

	for naam, functie in (
		("GET /foundation/versions", versions),
		("GET /foundation/1.1/auth", auth),
		("GET /foundation/1.1/current-user", current_user),
		("Zonder aanmelden: 401", zonder_aanmelden),
		("GET /projects en /projects/{id}", projecten),
		("GET /projects/{id}/extensions", extensions),
		("POST /topics", topic_maken),
		("GET /topics en /topics/{guid}, 404 voor een onbekend topic", topic_lezen),
		("PUT /topics/{guid}, 409 bij een verouderde modified_date", topic_wijzigen),
		("Comments: POST, GET, PUT", reacties),
		("Viewpoints: POST, GET, snapshot, selection, coloring, visibility", standpunten),
		("PUT en GET /related_topics", verwante),
		("Document references: POST, PUT, GET", documentverwijzingen),
		("BCF 2.1 en 3.0 heen en terug zonder verlies", bcfzip_heen_en_terug),
		("DELETE: viewpoint met reactie 409, comment, viewpoint, topics", opruimen),
	):
		p.stap(naam, functie)


def rapport(p: Proef, project: str) -> str:
	goed = sum(ok for _n, ok, _d in p.stappen)
	regels = [
		"# Conformiteit BCF-API 3.0 en Foundation API 1.1",
		"",
		f"Site: `{p.host or p.site}` · project: `{project}` · {datetime.now().strftime('%Y-%m-%d %H:%M')}",
		"",
		f"**{goed} van {len(p.stappen)} stappen geslaagd.**",
		"",
		"| Stap | Uitslag | Toelichting |",
		"|---|---|---|",
	]
	for naam, ok, detail in p.stappen:
		regels.append(f"| {naam} | {'geslaagd' if ok else 'mislukt'} | {detail.replace('|', '/')} |")
	return "\n".join(regels) + "\n"


def main(argv=None) -> int:
	parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
	parser.add_argument("--site", required=True)
	parser.add_argument("--sleutel", required=True, help="Authorization-kop: 'token <key>:<secret>' of 'Bearer <token>'")
	parser.add_argument("--project", required=True, help="id van de modelmap (BIM Project)")
	parser.add_argument("--host", help="Host-kop, als de site achter een ander adres draait")
	parser.add_argument("--uit", help="schrijf het rapport naar dit bestand")
	args = parser.parse_args(argv)
	proef = Proef(args.site, args.sleutel, args.host)
	draai(proef, args.project)
	tekst = rapport(proef, args.project)
	if args.uit:
		Path(args.uit).write_text(tekst, encoding="utf-8")
	print(tekst)
	return 0 if all(ok for _n, ok, _d in proef.stappen) else 1


if __name__ == "__main__":
	sys.exit(main())
