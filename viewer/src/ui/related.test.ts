import { expect, test, vi } from "vitest";
import type { BimHost, ElementProperties, ModelSource } from "../host/BimHost";
import { relatedNames } from "./related";

const bron: ModelSource = { soort: "bestand", sleutel: "Constructie/a.ifc", versie: "0123456789ab" };

function element(over: Partial<ElementProperties>): ElementProperties {
  return {
    klasse: "IfcWall",
    naam: "Wand",
    type: null,
    verdieping: null,
    psets: {},
    hoeveelheden: {},
    materialen: [],
    classificaties: [],
    ...over,
  };
}

function host(names: Record<string, string>) {
  const eigenschappen = vi.fn(async (_bron: ModelSource, ids: string[]) =>
    Object.fromEntries(ids.filter((id) => id in names).map((id) => [id, element({ naam: names[id] })])),
  );
  return { host: { eigenschappen } as unknown as BimHost, eigenschappen };
}

test("looks up the names of the storey and the type in one request", async () => {
  const { host: h, eigenschappen } = host({ s1: "00 begane grond", t1: "Binnenwand 100" });
  const names = await relatedNames(h, bron, element({ verdieping: "s1", type: "t1" }), "w1");
  expect(names).toEqual({ storey: "00 begane grond", type: "Binnenwand 100" });
  expect(eigenschappen).toHaveBeenCalledTimes(1);
  expect(eigenschappen).toHaveBeenCalledWith(bron, ["s1", "t1"]);
});

test("an id that is not in the index stays as it is", async () => {
  // An index from before types were indexed knows the storey but not the type.
  const { host: h } = host({ s1: "00 begane grond" });
  expect(await relatedNames(h, bron, element({ verdieping: "s1", type: "t1" }), "w1")).toEqual({
    storey: "00 begane grond",
    type: "t1",
  });
});

test("a storey itself has no storey row, and nothing is asked without ids", async () => {
  const { host: h, eigenschappen } = host({});
  expect(await relatedNames(h, bron, element({ klasse: "IfcBuildingStorey", verdieping: "s1" }), "s1")).toEqual({
    storey: null,
    type: null,
  });
  expect(eigenschappen).not.toHaveBeenCalled();
});
