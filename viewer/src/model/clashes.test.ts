import { describe, expect, test } from "vitest";
import type { Clash } from "./bcf";
import { elementenVan, groepeer, telStatussen } from "./clashes";

function botsing(naam: string, groep: string, status: Clash["status"] = "nieuw"): Clash {
  return {
    naam,
    ronde: "r1",
    sleutel: naam,
    element_a: { bestand: "c", versie: "1", globalid: `${naam}-a` },
    element_b: { bestand: "i", versie: "2", globalid: `${naam}-b` },
    punt: [1, 2, 3],
    afstand: 0.05,
    status,
    issue: null,
    groep,
  };
}

const BOTSINGEN = [
  botsing("b1", "IfcSlab × IfcPipeSegment"),
  botsing("b2", "IfcWall × IfcDuctSegment", "genegeerd"),
  botsing("b3", "IfcWall × IfcDuctSegment"),
  botsing("b4", "IfcWall × IfcDuctSegment", "opgelost"),
];

describe("clashes", () => {
  test("groepeer op klassepaar, grootste groep eerst", () => {
    expect(groepeer(BOTSINGEN).map((g) => [g.groep, g.botsingen.length])).toEqual([
      ["IfcWall × IfcDuctSegment", 3],
      ["IfcSlab × IfcPipeSegment", 1],
    ]);
  });

  test("groepen van gelijke grootte op naam", () => {
    expect(groepeer([botsing("x", "B × C"), botsing("y", "A × C")]).map((g) => g.groep)).toEqual(["A × C", "B × C"]);
  });

  test("statussen tellen", () => {
    expect(telStatussen(BOTSINGEN)).toEqual({ nieuw: 2, actief: 0, opgelost: 1, genegeerd: 1 });
  });

  test("beide elementen van een botsing, met hun bestand", () => {
    expect(elementenVan(BOTSINGEN[0])).toEqual([
      { bestand: "c", globalid: "b1-a" },
      { bestand: "i", globalid: "b1-b" },
    ]);
  });
});
