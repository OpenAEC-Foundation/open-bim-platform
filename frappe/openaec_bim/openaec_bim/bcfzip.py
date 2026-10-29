"""BCF als bestand (`.bcfzip`), versie 2.1 en 3.0, van en naar de JSON-vorm van de BCF-API 3.0.

Een topic is hier de JSON van de BCF-API met daarbij `comments`, `viewpoints` (met de schermafbeelding als base64),
`related_topics` en `document_references`. De versie van een bestand staat in `bcf.version`; zonder dat bestand is
het 2.1. Verschillen tussen de versies: in 2.1 staan reacties en standpunten naast het topic in `markup.bcf`, labels
en referentielinks zonder omhullend element, en camera's zonder beeldverhouding.
"""

from __future__ import annotations

import base64
import binascii
import io
import xml.etree.ElementTree as ET
import zipfile
from typing import Literal

MAX_UITGEPAKT_BYTES = 2 * 1024**3
SNAPSHOT_EXTENSIES = {"png": "png", "jpg": "jpg", "jpeg": "jpg"}

Versie = Literal["2.1", "3.0"]


class BcfOngeldig(ValueError):
	"""Het bestand is geen leesbare .bcfzip."""


# --- XML-hulp ---


def _xml(inhoud: bytes) -> ET.Element:
	try:
		wortel = ET.fromstring(inhoud)
	except ET.ParseError as fout:
		raise BcfOngeldig(f"Geen geldige XML: {fout}") from fout
	for element in wortel.iter():
		if isinstance(element.tag, str) and "}" in element.tag:
			element.tag = element.tag.split("}", 1)[1]
	return wortel


def _tekst(element: ET.Element | None, pad: str) -> str | None:
	if element is None:
		return None
	gevonden = element.find(pad)
	return gevonden.text.strip() if gevonden is not None and gevonden.text is not None else None


def _getal(element, pad: str) -> float | None:
	tekst = _tekst(element, pad)
	return float(tekst) if tekst not in (None, "") else None


def _geheel(element, pad: str) -> int | None:
	tekst = _tekst(element, pad)
	return int(tekst) if tekst not in (None, "") else None


def _waar(tekst: str | None, standaard: bool | None = None) -> bool | None:
	return standaard if tekst is None else tekst.strip().lower() == "true"


def _sub(ouder: ET.Element, tag: str, tekst=None, **attributen) -> ET.Element:
	element = ET.SubElement(ouder, tag, {k: v for k, v in attributen.items() if v is not None})
	if tekst is not None:
		element.text = _als_tekst(tekst)
	return element


def _als_tekst(waarde) -> str:
	if isinstance(waarde, bool):
		return "true" if waarde else "false"
	return str(waarde)


def _schoon(d: dict) -> dict:
	return {k: v for k, v in d.items() if v is not None}


def _bytes(wortel: ET.Element) -> bytes:
	return ET.tostring(wortel, encoding="utf-8", xml_declaration=True)


# --- lezen ---


def _versie(z: zipfile.ZipFile) -> Versie:
	if "bcf.version" not in z.namelist():
		return "2.1"
	return "3.0" if (_xml(z.read("bcf.version")).get("VersionId") or "").startswith("3") else "2.1"


def lees(inhoud: bytes) -> list[dict]:
	try:
		z = zipfile.ZipFile(io.BytesIO(inhoud))
	except zipfile.BadZipFile as fout:
		raise BcfOngeldig("Geen zip-bestand.") from fout
	with z:
		if sum(i.file_size for i in z.infolist()) > MAX_UITGEPAKT_BYTES:
			raise BcfOngeldig("Uitgepakt groter dan toegestaan.")
		versie = _versie(z)
		namen = set(z.namelist())
		topics = []
		for naam in z.namelist():
			delen = naam.split("/")
			if len(delen) == 2 and delen[1] == "markup.bcf":
				topics.append(_lees_markup(z, namen, delen[0], _xml(z.read(naam)), versie))
		return topics


def _lees_markup(z, namen: set[str], map_: str, markup: ET.Element, versie: Versie) -> dict:
	t = markup.find("Topic")
	if t is None:
		raise BcfOngeldig(f"{map_}/markup.bcf heeft geen Topic.")
	drie = versie == "3.0"
	snippet = t.find("BimSnippet")
	topic = {
		"guid": t.get("Guid") or map_,
		"server_assigned_id": t.get("ServerAssignedId"),
		"topic_type": t.get("TopicType"),
		"topic_status": t.get("TopicStatus"),
		"reference_links": [e.text.strip() for e in t.findall("ReferenceLinks/ReferenceLink" if drie else "ReferenceLink") if e.text],
		"title": _tekst(t, "Title"),
		"priority": _tekst(t, "Priority"),
		"index": _geheel(t, "Index"),
		"labels": [e.text.strip() for e in t.findall("Labels/Label" if drie else "Labels") if e.text],
		"creation_date": _tekst(t, "CreationDate"),
		"creation_author": _tekst(t, "CreationAuthor"),
		"modified_date": _tekst(t, "ModifiedDate"),
		"modified_author": _tekst(t, "ModifiedAuthor"),
		"due_date": _tekst(t, "DueDate"),
		"assigned_to": _tekst(t, "AssignedTo"),
		"stage": _tekst(t, "Stage"),
		"description": _tekst(t, "Description"),
		"bim_snippet": _schoon(
			{
				"snippet_type": snippet.get("SnippetType"),
				"is_external": _waar(snippet.get("IsExternal", snippet.get("isExternal")), False),
				"reference": _tekst(snippet, "Reference"),
				"reference_schema": _tekst(snippet, "ReferenceSchema"),
			}
		)
		if snippet is not None
		else None,
		"document_references": [
			_lees_documentverwijzing(e, drie)
			for e in t.findall("DocumentReferences/DocumentReference" if drie else "DocumentReference")
		],
		"related_topics": [
			{"related_topic_guid": e.get("Guid")}
			for e in t.findall("RelatedTopics/RelatedTopic" if drie else "RelatedTopic")
			if e.get("Guid")
		],
		"comments": [_lees_reactie(e) for e in (t.findall("Comments/Comment") if drie else markup.findall("Comment"))],
		"viewpoints": [
			_lees_standpunt(z, namen, map_, e, versie)
			for e in (t.findall("Viewpoints/ViewPoint") if drie else markup.findall("Viewpoints"))
		],
	}
	return _schoon(topic)


def _lees_documentverwijzing(e: ET.Element, drie: bool) -> dict:
	if drie:
		return _schoon(
			{
				"guid": e.get("Guid"),
				"document_guid": _tekst(e, "DocumentGuid"),
				"url": _tekst(e, "Url"),
				"description": _tekst(e, "Description"),
			}
		)
	extern = _waar(e.get("isExternal"), False)
	document = _tekst(e, "ReferencedDocument")
	return _schoon(
		{
			"guid": e.get("Guid"),
			"url": document if extern else None,
			"document_guid": None if extern else document,
			"description": _tekst(e, "Description"),
		}
	)


def _lees_reactie(e: ET.Element) -> dict:
	standpunt = e.find("Viewpoint")
	return _schoon(
		{
			"guid": e.get("Guid"),
			"date": _tekst(e, "Date"),
			"author": _tekst(e, "Author"),
			"comment": _tekst(e, "Comment"),
			"viewpoint_guid": standpunt.get("Guid") if standpunt is not None else None,
			"modified_date": _tekst(e, "ModifiedDate"),
			"modified_author": _tekst(e, "ModifiedAuthor"),
		}
	)


def _lees_standpunt(z, namen: set[str], map_: str, e: ET.Element, versie: Versie) -> dict:
	standpunt = {"guid": e.get("Guid"), "index": _geheel(e, "Index")}
	bestand = _tekst(e, "Viewpoint")
	if bestand and f"{map_}/{bestand}" in namen:
		standpunt.update(_lees_visualisatie(z, namen, map_, _xml(z.read(f"{map_}/{bestand}")), versie))
	snapshot = _tekst(e, "Snapshot")
	if snapshot and f"{map_}/{snapshot}" in namen:
		soort = SNAPSHOT_EXTENSIES.get(snapshot.rsplit(".", 1)[-1].lower())
		if soort:
			standpunt["snapshot"] = {
				"snapshot_type": soort,
				"snapshot_data": base64.b64encode(z.read(f"{map_}/{snapshot}")).decode(),
			}
	return _schoon(standpunt)


def _punt(element: ET.Element | None) -> dict | None:
	if element is None:
		return None
	return {as_: _getal(element, as_.upper()) for as_ in ("x", "y", "z")}


def _component(e: ET.Element) -> dict:
	return _schoon(
		{
			"ifc_guid": e.get("IfcGuid"),
			"originating_system": _tekst(e, "OriginatingSystem"),
			"authoring_tool_id": _tekst(e, "AuthoringToolId"),
		}
	)


def _camera(c: ET.Element | None, extra: str) -> dict | None:
	if c is None:
		return None
	return _schoon(
		{
			"camera_view_point": _punt(c.find("CameraViewPoint")),
			"camera_direction": _punt(c.find("CameraDirection")),
			"camera_up_vector": _punt(c.find("CameraUpVector")),
			extra: _getal(c, "FieldOfView" if extra == "field_of_view" else "ViewToWorldScale"),
			"aspect_ratio": _getal(c, "AspectRatio"),
		}
	)


def _lees_visualisatie(z, namen: set[str], map_: str, vi: ET.Element, versie: Versie) -> dict:
	drie = versie == "3.0"
	uit: dict = {
		"perspective_camera": _camera(vi.find("PerspectiveCamera"), "field_of_view"),
		"orthogonal_camera": _camera(vi.find("OrthogonalCamera"), "view_to_world_scale"),
		"lines": [
			{"start_point": _punt(e.find("StartPoint")), "end_point": _punt(e.find("EndPoint"))}
			for e in vi.findall("Lines/Line")
		],
		"clipping_planes": [
			{"location": _punt(e.find("Location")), "direction": _punt(e.find("Direction"))}
			for e in vi.findall("ClippingPlanes/ClippingPlane")
		],
		"bitmaps": [
			_lees_bitmap(z, namen, map_, e, drie) for e in vi.findall("Bitmaps/Bitmap" if drie else "Bitmap")
		],
	}
	c = vi.find("Components")
	if c is not None:
		zicht = c.find("Visibility")
		hints = c.find("ViewSetupHints")
		if hints is None and zicht is not None:
			hints = zicht.find("ViewSetupHints")
		kleuren = []
		for kleur in c.findall("Coloring/Color"):
			componenten = kleur.findall("Components/Component") or kleur.findall("Component")
			kleuren.append({"color": "#" + (kleur.get("Color") or ""), "components": [_component(x) for x in componenten]})
		uit["components"] = _schoon(
			{
				"selection": [_component(x) for x in c.findall("Selection/Component")] or None,
				"coloring": kleuren or None,
				"visibility": _schoon(
					{
						# Zonder attribuut is de standaard van de XSD: uit.
						"default_visibility": _waar(zicht.get("DefaultVisibility"), False),
						"exceptions": [_component(x) for x in zicht.findall("Exceptions/Component")] or None,
						"view_setup_hints": _schoon(
							{
								"spaces_visible": _waar(hints.get("SpacesVisible")),
								"space_boundaries_visible": _waar(hints.get("SpaceBoundariesVisible")),
								"openings_visible": _waar(hints.get("OpeningsVisible")),
							}
						)
						if hints is not None
						else None,
					}
				)
				if zicht is not None
				else None,
			}
		)
	return _schoon({k: v for k, v in uit.items() if v not in ([], {})})


def _lees_bitmap(z, namen: set[str], map_: str, e: ET.Element, drie: bool) -> dict:
	referentie = _tekst(e, "Reference")
	data = z.read(f"{map_}/{referentie}") if referentie and f"{map_}/{referentie}" in namen else b""
	return _schoon(
		{
			"bitmap_type": (_tekst(e, "Format" if drie else "Bitmap") or "").lower() or None,
			"bitmap_data": base64.b64encode(data).decode(),
			"location": _punt(e.find("Location")),
			"normal": _punt(e.find("Normal")),
			"up": _punt(e.find("Up")),
			"height": _getal(e, "Height"),
		}
	)


# --- schrijven ---


def schrijf(topics: list[dict], versie: Versie, uitbreidingen: dict | None = None) -> bytes:
	if versie not in ("2.1", "3.0"):
		raise ValueError(f"Onbekende BCF-versie {versie}")
	buf = io.BytesIO()
	with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
		z.writestr("bcf.version", _versiebestand(versie))
		if versie == "3.0" and uitbreidingen:
			z.writestr("extensions.xml", _uitbreidingenbestand(uitbreidingen))
		for topic in topics:
			map_ = topic["guid"]
			markup, bijlagen = _markup(topic, versie)
			z.writestr(f"{map_}/markup.bcf", markup)
			for naam, inhoud in bijlagen:
				z.writestr(f"{map_}/{naam}", inhoud)
	return buf.getvalue()


def _versiebestand(versie: Versie) -> bytes:
	wortel = ET.Element("Version", {"VersionId": versie})
	if versie == "2.1":
		_sub(wortel, "DetailedVersion", "2.1")
	return _bytes(wortel)


def _uitbreidingenbestand(u: dict) -> bytes:
	wortel = ET.Element("Extensions")
	for groep, element, sleutel in (
		("TopicTypes", "TopicType", "topic_type"),
		("TopicStatuses", "TopicStatus", "topic_status"),
		("Priorities", "Priority", "priority"),
		("TopicLabels", "TopicLabel", "topic_label"),
		("Users", "User", "users"),
		("SnippetTypes", "SnippetType", "snippet_type"),
		("Stages", "Stage", "stage"),
	):
		if u.get(sleutel):
			ouder = _sub(wortel, groep)
			for waarde in u[sleutel]:
				_sub(ouder, element, waarde)
	return _bytes(wortel)


def _markup(topic: dict, versie: Versie) -> tuple[bytes, list[tuple[str, bytes]]]:
	drie = versie == "3.0"
	markup = ET.Element("Markup")
	t = _sub(
		markup,
		"Topic",
		Guid=topic["guid"],
		ServerAssignedId=topic.get("server_assigned_id") if drie else None,
		TopicType=topic.get("topic_type"),
		TopicStatus=topic.get("topic_status"),
	)
	links = topic.get("reference_links") or []
	if links:
		ouder = _sub(t, "ReferenceLinks") if drie else t
		for link in links:
			_sub(ouder, "ReferenceLink", link)
	_sub(t, "Title", topic.get("title") or "")
	for tag, sleutel in (("Priority", "priority"), ("Index", "index")):
		if topic.get(sleutel) is not None:
			_sub(t, tag, topic[sleutel])
	labels = topic.get("labels") or []
	if labels:
		if drie:
			ouder = _sub(t, "Labels")
			for label in labels:
				_sub(ouder, "Label", label)
		else:
			for label in labels:
				_sub(t, "Labels", label)
	for tag, sleutel in (
		("CreationDate", "creation_date"),
		("CreationAuthor", "creation_author"),
		("ModifiedDate", "modified_date"),
		("ModifiedAuthor", "modified_author"),
		("DueDate", "due_date"),
		("AssignedTo", "assigned_to"),
		("Stage", "stage"),
		("Description", "description"),
	):
		if topic.get(sleutel) is not None:
			_sub(t, tag, topic[sleutel])
	snippet = topic.get("bim_snippet")
	if snippet:
		extern = {"IsExternal" if drie else "isExternal": _als_tekst(bool(snippet.get("is_external")))}
		s = _sub(t, "BimSnippet", SnippetType=snippet.get("snippet_type"), **extern)
		_sub(s, "Reference", snippet.get("reference") or "")
		if snippet.get("reference_schema"):
			_sub(s, "ReferenceSchema", snippet["reference_schema"])
	verwijzingen = topic.get("document_references") or []
	if verwijzingen:
		ouder = _sub(t, "DocumentReferences") if drie else t
		for v in verwijzingen:
			if drie:
				d = _sub(ouder, "DocumentReference", Guid=v.get("guid"))
				if v.get("document_guid"):
					_sub(d, "DocumentGuid", v["document_guid"])
				else:
					_sub(d, "Url", v.get("url") or "")
			else:
				extern = not v.get("document_guid")
				d = _sub(ouder, "DocumentReference", Guid=v.get("guid"), isExternal=_als_tekst(extern))
				_sub(d, "ReferencedDocument", v.get("url") if extern else v["document_guid"])
			if v.get("description"):
				_sub(d, "Description", v["description"])
	verwant = topic.get("related_topics") or []
	if verwant:
		ouder = _sub(t, "RelatedTopics") if drie else t
		for r in verwant:
			_sub(ouder, "RelatedTopic", Guid=r["related_topic_guid"])

	reacties = topic.get("comments") or []
	if reacties:
		ouder = _sub(t, "Comments") if drie else markup
		for r in reacties:
			c = _sub(ouder, "Comment", Guid=r["guid"])
			_sub(c, "Date", r.get("date") or "")
			_sub(c, "Author", r.get("author") or "")
			_sub(c, "Comment", r.get("comment") or "")
			if r.get("viewpoint_guid"):
				_sub(c, "Viewpoint", Guid=r["viewpoint_guid"])
			for tag, sleutel in (("ModifiedDate", "modified_date"), ("ModifiedAuthor", "modified_author")):
				if r.get(sleutel):
					_sub(c, tag, r[sleutel])

	bijlagen: list[tuple[str, bytes]] = []
	standpunten = topic.get("viewpoints") or []
	if standpunten:
		ouder = _sub(t, "Viewpoints") if drie else markup
		for sp in standpunten:
			v = _sub(ouder, "ViewPoint" if drie else "Viewpoints", Guid=sp["guid"])
			_sub(v, "Viewpoint", f"{sp['guid']}.bcfv")
			snapshot = sp.get("snapshot") or {}
			if snapshot.get("snapshot_data"):
				soort = SNAPSHOT_EXTENSIES.get(str(snapshot.get("snapshot_type")).lower(), "png")
				_sub(v, "Snapshot", f"{sp['guid']}.{soort}")
				bijlagen.append((f"{sp['guid']}.{soort}", _b64(snapshot["snapshot_data"])))
			if sp.get("index") is not None:
				_sub(v, "Index", sp["index"])
			visualisatie, bitmaps = _visualisatie(sp, drie)
			bijlagen.append((f"{sp['guid']}.bcfv", visualisatie))
			bijlagen.extend(bitmaps)
	return _bytes(markup), bijlagen


def _b64(tekst: str) -> bytes:
	try:
		return base64.b64decode(tekst, validate=True)
	except (binascii.Error, ValueError) as fout:
		raise BcfOngeldig("Geen geldige base64.") from fout


def _zet_punt(ouder: ET.Element, tag: str, punt: dict | None) -> None:
	if punt:
		p = _sub(ouder, tag)
		for as_ in ("x", "y", "z"):
			_sub(p, as_.upper(), punt.get(as_, 0.0))


def _zet_component(ouder: ET.Element, component: dict) -> None:
	c = _sub(ouder, "Component", IfcGuid=component.get("ifc_guid"))
	for tag, sleutel in (("OriginatingSystem", "originating_system"), ("AuthoringToolId", "authoring_tool_id")):
		if component.get(sleutel):
			_sub(c, tag, component[sleutel])


def _visualisatie(sp: dict, drie: bool) -> tuple[bytes, list[tuple[str, bytes]]]:
	vi = ET.Element("VisualizationInfo", {"Guid": sp["guid"]})
	componenten = sp.get("components")
	if componenten:
		c = _sub(vi, "Components")
		# Visibility is verplicht; zonder zichtbaarheid in het standpunt is alles zichtbaar.
		zicht = componenten.get("visibility") or {"default_visibility": True}
		hints = zicht.get("view_setup_hints")

		def zet_hints(ouder: ET.Element) -> None:
			_sub(
				ouder,
				"ViewSetupHints",
				SpacesVisible=_als_tekst(bool(hints.get("spaces_visible"))),
				SpaceBoundariesVisible=_als_tekst(bool(hints.get("space_boundaries_visible"))),
				OpeningsVisible=_als_tekst(bool(hints.get("openings_visible"))),
			)

		# BCF 2.1: ViewSetupHints als eerste onder Components; BCF 3.0: binnen Visibility, voor Exceptions.
		if hints and not drie:
			zet_hints(c)
		if componenten.get("selection"):
			s = _sub(c, "Selection")
			for x in componenten["selection"]:
				_zet_component(s, x)
		z = _sub(c, "Visibility", DefaultVisibility=_als_tekst(bool(zicht.get("default_visibility", True))))
		if hints and drie:
			zet_hints(z)
		if zicht.get("exceptions"):
			e = _sub(z, "Exceptions")
			for x in zicht["exceptions"]:
				_zet_component(e, x)
		if componenten.get("coloring"):
			k = _sub(c, "Coloring")
			for kleur in componenten["coloring"]:
				col = _sub(k, "Color", Color=str(kleur.get("color") or "").lstrip("#"))
				ouder = _sub(col, "Components") if drie else col
				for x in kleur.get("components") or []:
					_zet_component(ouder, x)
	for tag, sleutel, extra, extra_tag in (
		("OrthogonalCamera", "orthogonal_camera", "view_to_world_scale", "ViewToWorldScale"),
		("PerspectiveCamera", "perspective_camera", "field_of_view", "FieldOfView"),
	):
		camera = sp.get(sleutel)
		if camera:
			c = _sub(vi, tag)
			_zet_punt(c, "CameraViewPoint", camera.get("camera_view_point"))
			_zet_punt(c, "CameraDirection", camera.get("camera_direction"))
			_zet_punt(c, "CameraUpVector", camera.get("camera_up_vector"))
			_sub(c, extra_tag, camera.get(extra, 1.0))
			if drie and camera.get("aspect_ratio") is not None:
				_sub(c, "AspectRatio", camera["aspect_ratio"])
	if sp.get("lines"):
		lijnen = _sub(vi, "Lines")
		for lijn in sp["lines"]:
			l_ = _sub(lijnen, "Line")
			_zet_punt(l_, "StartPoint", lijn.get("start_point"))
			_zet_punt(l_, "EndPoint", lijn.get("end_point"))
	if sp.get("clipping_planes"):
		vlakken = _sub(vi, "ClippingPlanes")
		for vlak in sp["clipping_planes"]:
			v = _sub(vlakken, "ClippingPlane")
			_zet_punt(v, "Location", vlak.get("location"))
			_zet_punt(v, "Direction", vlak.get("direction"))
	bitmaps: list[tuple[str, bytes]] = []
	if sp.get("bitmaps"):
		ouder = _sub(vi, "Bitmaps") if drie else vi
		for i, bitmap in enumerate(sp["bitmaps"]):
			soort = str(bitmap.get("bitmap_type") or "png").lower()
			naam = f"{sp['guid']}-bitmap-{i}.{soort}"
			b = _sub(ouder, "Bitmap")
			_sub(b, "Format" if drie else "Bitmap", soort if drie else soort.upper())
			_sub(b, "Reference", naam)
			for tag, sleutel in (("Location", "location"), ("Normal", "normal"), ("Up", "up")):
				_zet_punt(b, tag, bitmap.get(sleutel))
			_sub(b, "Height", bitmap.get("height", 1.0))
			bitmaps.append((naam, _b64(bitmap.get("bitmap_data") or "")))
	return _bytes(vi), bitmaps
