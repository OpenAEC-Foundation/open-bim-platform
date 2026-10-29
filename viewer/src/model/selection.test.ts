import { expect, test } from "vitest";
import type { ModelSource } from "../host/BimHost";
import { selectionKey, type Selection } from "./selection";

const a: ModelSource = { soort: "bestand", sleutel: "Constructie/a.ifc", versie: "0123456789ab" };
const copy: ModelSource = { soort: "bestand", sleutel: "Constructie/kopie van a.ifc", versie: "0123456789ab" };

test("selection keys include source", () => {
  // the same GlobalId in a copied model is a different element
  const selA: Selection = { bron: a, globalid: "2O2Fr$t4X7Zf8NOew3FLOH" };
  const selB: Selection = { bron: copy, globalid: "2O2Fr$t4X7Zf8NOew3FLOH" };
  expect(selectionKey(selA)).not.toBe(selectionKey(selB));
});

test("selection keys include version", () => {
  const older: Selection = { bron: { ...a, versie: "ffffffffffff" }, globalid: "x" };
  expect(selectionKey(older)).not.toBe(selectionKey({ bron: a, globalid: "x" }));
});

test("selection key format", () => {
  expect(selectionKey({ bron: a, globalid: "g" })).toBe("bestand:Constructie/a.ifc@0123456789ab#g");
});
