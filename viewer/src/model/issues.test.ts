import { describe, expect, test } from "vitest";
import { toBcfCamera, type Topic } from "./bcf";
import { filterTopics, koppelWaarschuwing, nieuwTopic, verlorenElementen } from "./issues";

function topic(guid: string, velden: Partial<Topic>): Topic {
  return {
    guid,
    title: "",
    topic_type: null,
    topic_status: "Open",
    priority: null,
    labels: [],
    description: null,
    assigned_to: null,
    due_date: null,
    stage: null,
    index: null,
    reference_links: [],
    creation_date: "2026-10-29T10:00:00.000+01:00",
    creation_author: "a@b.nl",
    modified_date: "2026-10-29T10:00:00.000+01:00",
    modified_author: null,
    authorization: { topic_actions: [], topic_status: [] },
    ...velden,
  };
}

const TOPICS = [
  topic("t1", { title: "Kanaal door wand", topic_status: "Open", modified_date: "2026-10-29T11:00:00.000+01:00" }),
  topic("t2", { title: "Sparing kanaal", topic_status: "Gesloten" }),
  topic("t3", { title: "Leuning", description: "Het KANAAL hangt te laag", topic_status: "Open", assigned_to: "x@y.nl" }),
  topic("t4", { title: "Vloer", topic_type: "Vraag", labels: ["kanaal"], modified_date: "2026-10-29T12:00:00.000+01:00" }),
];
const CAMERA = toBcfCamera([10, 5, 3], [0, 0, 0], [0, 1, 0], 60, 1.5);
const WAND = "2O2Fr$t4X7Zf8NOew3FLOH";

describe("issues", () => {
  test("filter op status en tekst", () => {
    expect(filterTopics(TOPICS, { status: "Open", tekst: "kanaal" }).map((t) => t.guid)).toEqual(["t4", "t1", "t3"]);
    expect(filterTopics(TOPICS, { status: "Open", tekst: "wand" }).map((t) => t.guid)).toEqual(["t1"]);
  });

  test("filter op soort en toegewezen, nieuwste wijziging eerst", () => {
    expect(filterTopics(TOPICS, { soort: "Vraag" }).map((t) => t.guid)).toEqual(["t4"]);
    expect(filterTopics(TOPICS, { toegewezen: "x@y.nl" }).map((t) => t.guid)).toEqual(["t3"]);
    expect(filterTopics(TOPICS, {}).map((t) => t.guid)).toEqual(["t4", "t1", "t2", "t3"]);
  });

  test("nieuw topic neemt camera en selectie mee", () => {
    const { topic: t, standpunt } = nieuwTopic({ title: " Wand ", topic_type: "Fout", description: "" }, CAMERA, [WAND]);
    expect(t).toEqual({ title: "Wand", topic_type: "Fout" });
    expect(standpunt.perspective_camera).toEqual(CAMERA.perspective_camera);
    expect(standpunt.components?.selection).toEqual([{ ifc_guid: WAND }]);
    expect(standpunt.snapshot).toBeUndefined();
  });

  test("nieuw topic met schermafbeelding en zonder selectie", () => {
    const { standpunt } = nieuwTopic({ title: "Overzicht" }, CAMERA, [], "iVBORw0KGgo=");
    expect(standpunt.components).toBeUndefined();
    expect(standpunt.snapshot).toEqual({ snapshot_type: "png", snapshot_data: "iVBORw0KGgo=" });
  });

  test("matchrate onder de drempel geeft een waarschuwing", () => {
    expect(koppelWaarschuwing(0.85)).toBe(true);
    expect(koppelWaarschuwing(0.9)).toBe(false);
    expect(koppelWaarschuwing(null)).toBe(false);
  });

  test("elementen die niet zijn teruggevonden", () => {
    const elementen = [
      { ifc_guid: "a", bestand: "b1", versie: "2", teruggevonden: true },
      { ifc_guid: "b", bestand: "b1", versie: "1", teruggevonden: false },
    ];
    expect(verlorenElementen(topic("t", { elementen }))).toEqual([elementen[1]]);
  });
});
