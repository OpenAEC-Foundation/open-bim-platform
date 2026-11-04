import { describe, expect, it } from "vitest";
import en from "./en.json";
import nl from "./nl.json";

type Tree = { [key: string]: string | Tree };

function keys(tree: Tree, prefix = ""): string[] {
  return Object.entries(tree).flatMap(([key, value]) => (typeof value === "string" ? [`${prefix}${key}`] : keys(value, `${prefix}${key}.`)));
}

describe("translations", () => {
  it("both languages have the same keys", () => {
    expect(keys(en).sort()).toEqual(keys(nl).sort());
  });
  it("every kind of round has a name", () => {
    for (const language of [nl, en] as Tree[]) {
      for (const soort of ["hard", "afstand", "dubbel", "gemengd"]) expect(language[`soort_${soort}`], soort).toBeTruthy();
    }
  });
  it("every reason why a quick choice is not available has a text", () => {
    for (const language of [nl, en]) {
      for (const reden of ["geen_modellen", "geen_constructie", "geen_installaties", "geen_wanden_vloeren", "een_model", "geen_regels", "te_veel_regels"]) {
        expect((language.voorinstelling_reden as Record<string, string>)[reden], reden).toBeTruthy();
      }
    }
  });
});
