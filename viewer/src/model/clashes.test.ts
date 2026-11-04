import { describe, expect, test } from "vitest";
import type { ModelInfo } from "../host/BimHost";
import type { Clash, ClashElement, ClashRule, ClashRound, ClashView } from "./bcf";
import {
  actieveWeergave,
  bijnaMet,
  controlesUitRegels,
  disciplineVan,
  elementNaam,
  emmerTelling,
  mmWaarde,
  facetten,
  filter,
  groepeer,
  isGevonden,
  leegFilter,
  overlapWaarschuwing,
  sneltoets,
  standaardRegels,
  teBeslissen,
  filterChips,
  filterUitWeergave,
  groepUitWeergave,
  magBeslissen,
  MAX_CONTROLES,
  nietGereed,
  nietInBeeld,
  rijActies,
  nietInBeeldTekst,
  rondeTitel,
  schoneWeergaven,
  zonderChip,
  rondeTelling,
  houdVast,
  isZichtbaar,
  sprongNaBesluit,
  GROEPSACTIE_MAX,
  REDEN_MAX,
  vorige,
  voortgangProcent,
  volgende,
  voorinstellingen,
} from "./clashes";

const element: ClashElement = { bestand: "c", versie: "1", globalid: "g", klasse: "IfcWall", naam: "Wand 1", verdieping: "00" };

function botsing(naam: string, groep: string, status: Clash["status"] = "nieuw", rest: Partial<Clash> = {}): Clash {
  return {
    naam,
    ronde: "r1",
    sleutel: naam,
    element_a: { ...element, globalid: `${naam}-a`, naam: `${naam} A` },
    element_b: { ...element, bestand: "i", versie: "2", globalid: `${naam}-b`, klasse: "IfcDuctSegment", naam: `${naam} B` },
    punt: [1, 2, 3],
    afstand: 0.05,
    status,
    issue: null,
    groep,
    soort: "hard",
    regel: null,
    emmer: "beoordelen",
    emmer_reden: null,
    ernst: "groot",
    categorie: "constructie × installaties",
    disciplines: "constructie × installaties",
    verdieping: "00",
    raster: null,
    ruimte: null,
    ontwikkeling: "nieuw",
    nummer: 1,
    reden: null,
    beoordeeld_door: null,
    beoordeeld_op: null,
    ...rest,
  };
}

const b = (naam: string, status: Clash["status"]) => botsing(naam, "G", status);

function model(rest: {
  naam?: string;
  discipline?: string;
  klassen?: Record<string, number>;
  box?: [number, number, number, number, number, number] | null;
  status?: ModelInfo["status"];
}): ModelInfo {
  const naam = rest.naam ?? "m.ifc";
  const box = rest.box;
  return {
    bron: { soort: "bestand", sleutel: naam, versie: "1" },
    naam,
    discipline: rest.discipline ?? "",
    status: rest.status ?? "klaar",
    delen: [],
    index: {
      schema: "IFC4",
      lengte_eenheid: "m",
      georeferentie: null,
      begrenzing: box ? { min: [box[0], box[1], box[2]], max: [box[3], box[4], box[5]] } : null,
      aantallen_per_klasse: rest.klassen ?? {},
      aantallen_per_verdieping: {},
      omzetter: "t",
      delen: [],
    },
  };
}

const CONSTRUCTIE = model({ naam: "con.ifc", discipline: "constructie", klassen: { IfcBeam: 4, IfcWall: 2 } });
const INSTALLATIE = model({ naam: "inst.ifc", discipline: "installaties", klassen: { IfcDuctSegment: 9, IfcPipeSegment: 3 } });

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


});

describe("snelle keuzes", () => {
  const kies = (modellen: ModelInfo[], id: string) => voorinstellingen(modellen).find((v) => v.id === id)!;

  test("alle snelle keuzes hebben een vaste volgorde en id", () => {
    expect(voorinstellingen([CONSTRUCTIE, INSTALLATIE]).map((v) => v.id)).toEqual([
      "harde",
      "constructie_installaties",
      "wanden_installaties",
      "tussen_modellen",
      "bijna",
      "dubbel",
      "regels",
    ]);
  });

  test("harde botsingen: alle modellen tegen alle, hard, 0 mm", () => {
    const v = kies([CONSTRUCTIE, INSTALLATIE], "harde");
    expect(v.beschikbaar).toBe(true);
    expect(v.reden).toBeNull();
    expect(v.controles).toEqual([
      {
        set_a: [{ bestand: "con.ifc" }, { bestand: "inst.ifc" }],
        set_b: [{ bestand: "con.ifc" }, { bestand: "inst.ifc" }],
        soort: "hard",
        tolerantie: 0,
      },
    ]);
  });

  test("constructie tegen installaties is niet beschikbaar zonder installaties, met reden", () => {
    const v = kies([CONSTRUCTIE], "constructie_installaties");
    expect(v.beschikbaar).toBe(false);
    expect(v.reden).toBe("voorinstelling_reden.geen_installaties");
    const w = kies([INSTALLATIE], "wanden_installaties");
    expect(w.beschikbaar).toBe(false);
    expect(w.reden).toBe("voorinstelling_reden.geen_wanden_vloeren");
  });

  test("constructie tegen installaties met de klassen uit de spec", () => {
    const v = kies([CONSTRUCTIE, INSTALLATIE], "constructie_installaties");
    expect(v.beschikbaar).toBe(true);
    expect(v.controles).toHaveLength(1);
    expect(v.controles[0].set_a[0].klassen).toEqual([
      "IfcBeam",
      "IfcColumn",
      "IfcFooting",
      "IfcPile",
      "IfcMember",
      "IfcSlab",
      "IfcWall",
    ]);
    expect(v.controles[0].set_b[0].klassen).toEqual(["IfcDistributionElement"]);
    expect(kies([CONSTRUCTIE, INSTALLATIE], "wanden_installaties").controles[0].set_a[0].klassen).toEqual(["IfcWall", "IfcSlab"]);
  });

  test("installaties worden herkend aan bekende klassen", () => {
    const lamp = model({ naam: "l.ifc", klassen: { IfcLightFixture: 2 } });
    const wand = model({ naam: "w.ifc", klassen: { IfcWall: 2 } });
    expect(kies([wand, lamp], "constructie_installaties").beschikbaar).toBe(true);
    expect(kies([wand], "constructie_installaties").beschikbaar).toBe(false);
  });

  test("tussen modellen vraagt twee modellen", () => {
    const een = kies([CONSTRUCTIE], "tussen_modellen");
    expect(een.beschikbaar).toBe(false);
    expect(een.reden).toBe("voorinstelling_reden.een_model");
    const twee = kies([CONSTRUCTIE, INSTALLATIE], "tussen_modellen");
    expect(twee.beschikbaar).toBe(true);
    expect(twee.controles[0].alleen_tussen_modellen).toBe(true);
    expect(twee.controles[0].soort).toBe("hard");
  });

  test("bijna-botsingen zijn instelbaar, standaard 50 mm", () => {
    const v = kies([CONSTRUCTIE, INSTALLATIE], "bijna");
    expect(v.instelbaar).toBe(true);
    expect(v.controles[0]).toMatchObject({ soort: "afstand", tolerantie: 0.05, alleen_tussen_modellen: true });
    expect(bijnaMet(120, [CONSTRUCTIE, INSTALLATIE])[0].tolerantie).toBeCloseTo(0.12);
  });

  test("dubbele elementen en zonder modellen", () => {
    expect(kies([CONSTRUCTIE], "dubbel").controles[0].soort).toBe("dubbel");
    const leeg = voorinstellingen([]);
    expect(leeg.every((v) => !v.beschikbaar)).toBe(true);
    expect(leeg[0].reden).toBe("voorinstelling_reden.geen_modellen");
  });

  test("een model dat nog niet klaar is doet niet mee", () => {
    const bezig = model({ naam: "x.ifc", status: "bezig" });
    expect(kies([CONSTRUCTIE, bezig], "harde").controles[0].set_a).toEqual([{ bestand: "con.ifc" }]);
  });

  test("de telling kent concrete klassen: gangbare subklassen tellen mee", () => {
    const standaard = (klassen: Record<string, number>) => model({ naam: "s.ifc", klassen });
    for (const klasse of ["IfcWallStandardCase", "IfcWallElementedCase", "IfcSlabStandardCase", "IfcSlabElementedCase"]) {
      expect(kies([standaard({ [klasse]: 1 }), INSTALLATIE], "wanden_installaties").beschikbaar, klasse).toBe(true);
    }
    for (const klasse of ["IfcBeamStandardCase", "IfcColumnStandardCase", "IfcMemberStandardCase", "IfcWallStandardCase"]) {
      expect(kies([standaard({ [klasse]: 1 }), INSTALLATIE], "constructie_installaties").beschikbaar, klasse).toBe(true);
    }
    // A class that merely looks alike does not count, and neither does a count of zero.
    expect(kies([standaard({ IfcWallpaper: 1 }), INSTALLATIE], "wanden_installaties").beschikbaar).toBe(false);
    expect(kies([standaard({ IfcWallStandardCase: 0 }), INSTALLATIE], "wanden_installaties").beschikbaar).toBe(false);
  });

  test("meer regels dan een ronde aankan: niet beschikbaar met een eigen reden", () => {
    const disciplines = Array.from({ length: MAX_CONTROLES + 1 }, (_, i) => `d${i}`);
    const modellen = disciplines.map((d) => model({ naam: `${d}.ifc`, discipline: d }));
    const regels: ClashRule[] = disciplines.map((d) => ({ a: d, b: d, soort: "hard", mm: 0, ernst: null }));
    const teVeel = voorinstellingen(modellen, regels).find((x) => x.id === "regels")!;
    expect(teVeel.beschikbaar).toBe(false);
    expect(teVeel.reden).toBe("voorinstelling_reden.te_veel_regels");
    const precies = voorinstellingen(modellen, regels.slice(0, MAX_CONTROLES)).find((x) => x.id === "regels")!;
    expect(precies.beschikbaar).toBe(true);
    expect(precies.controles).toHaveLength(MAX_CONTROLES);
  });

  test("volgens de projectregels: niet beschikbaar zonder regels", () => {
    expect(kies([CONSTRUCTIE, INSTALLATIE], "regels").beschikbaar).toBe(false);
    expect(kies([CONSTRUCTIE, INSTALLATIE], "regels").reden).toBe("voorinstelling_reden.geen_regels");
    const regels: ClashRule[] = [{ a: "constructie", b: "installaties", soort: "hard", mm: 0, ernst: null }];
    const v = voorinstellingen([CONSTRUCTIE, INSTALLATIE], regels).find((x) => x.id === "regels")!;
    expect(v.beschikbaar).toBe(true);
    expect(v.controles).toHaveLength(1);
  });
});

describe("disciplines en regels", () => {
  test("een model zonder submap krijgt de bestandsnaam als discipline", () => {
    expect(disciplineVan(model({ naam: "woning.ifc", discipline: "" }))).toBe("woning");
    expect(disciplineVan(model({ naam: "Woning.IFC", discipline: "" }))).toBe("Woning");
    expect(disciplineVan(model({ naam: "x/y.ifc", discipline: "bouwkunde" }))).toBe("bouwkunde");
  });

  test("regels: uit en paren zonder modellen vallen af; mm wordt meter", () => {
    const regels: ClashRule[] = [
      { a: "constructie", b: "installaties", soort: "afstand", mm: 25, ernst: "kritiek" },
      { a: "constructie", b: "installaties", soort: "uit", mm: 0, ernst: null },
      { a: "constructie", b: "bouwkunde", soort: "hard", mm: 0, ernst: null },
      { a: "constructie", b: "constructie", soort: "hard", mm: 0, ernst: null },
    ];
    const controles = controlesUitRegels(regels, [CONSTRUCTIE, INSTALLATIE]);
    expect(controles).toEqual([
      {
        regel: "constructie × installaties",
        set_a: [{ bestand: "con.ifc" }],
        set_b: [{ bestand: "inst.ifc" }],
        soort: "afstand",
        tolerantie: 0.025,
        ernst: "kritiek",
      },
      {
        regel: "constructie × constructie",
        set_a: [{ bestand: "con.ifc" }],
        set_b: [{ bestand: "con.ifc" }],
        soort: "hard",
        tolerantie: 0,
        ernst: null,
      },
    ]);
  });

  test("standaardregels: hard tussen disciplines, uit binnen een discipline, bewaard gaat voor", () => {
    const bewaard: ClashRule[] = [{ a: "constructie", b: "installaties", soort: "afstand", mm: 30, ernst: "groot" }];
    const regels = standaardRegels(["installaties", "constructie", "constructie"], bewaard);
    expect(regels).toEqual([
      { a: "constructie", b: "constructie", soort: "uit", mm: 0, ernst: null },
      { a: "constructie", b: "installaties", soort: "afstand", mm: 30, ernst: "groot" },
      { a: "installaties", b: "installaties", soort: "uit", mm: 0, ernst: null },
    ]);
    expect(standaardRegels(["a", "b"], []).find((r) => r.a === "a" && r.b === "b")?.soort).toBe("hard");
  });

  test("een harde regel stuurt zijn mm ook als tolerantie", () => {
    const regels: ClashRule[] = [{ a: "constructie", b: "installaties", soort: "hard", mm: 10, ernst: null }];
    expect(controlesUitRegels(regels, [CONSTRUCTIE, INSTALLATIE])[0]).toMatchObject({ soort: "hard", tolerantie: 0.01 });
  });

  test("paren sorteren op codepunt, zoals de server", () => {
    const regels = standaardRegels(["a", "B"], [{ a: "a", b: "B", soort: "afstand", mm: 5, ernst: null }]);
    expect(regels).toContainEqual({ a: "B", b: "a", soort: "afstand", mm: 5, ernst: null });
    expect(regels.map((r) => `${r.a}|${r.b}`)).toEqual(["B|B", "B|a", "a|a"]);
  });

  test("standaardregels: bewaarde paren zonder model blijven bestaan, ook met omgedraaide namen", () => {
    const bewaard: ClashRule[] = [{ a: "x", b: "a", soort: "hard", mm: 5, ernst: null }];
    const regels = standaardRegels(["a"], bewaard);
    expect(regels).toContainEqual({ a: "a", b: "x", soort: "hard", mm: 5, ernst: null });
    expect(regels).toContainEqual({ a: "a", b: "a", soort: "uit", mm: 0, ernst: null });
  });

  test("overlapwaarschuwing met 1 m marge, en niet zonder dozen", () => {
    const a = model({ naam: "a.ifc", box: [0, 0, 0, 10, 10, 10] });
    const dichtbij = model({ naam: "b.ifc", box: [10.5, 0, 0, 20, 10, 10] });
    const ver = model({ naam: "c.ifc", box: [12, 0, 0, 20, 10, 10] });
    const zonder = model({ naam: "d.ifc", box: null });
    expect(overlapWaarschuwing([a], [dichtbij])).toBe(false);
    expect(overlapWaarschuwing([a], [ver])).toBe(true);
    expect(overlapWaarschuwing([a], [zonder])).toBe(false);
    expect(overlapWaarschuwing([a], [ver, zonder])).toBe(false);
    expect(overlapWaarschuwing([a], [ver, dichtbij])).toBe(false);
    expect(overlapWaarschuwing([], [a])).toBe(false);
  });

  test("a model is never compared with itself", () => {
    const a = model({ naam: "a.ifc", box: [0, 0, 0, 10, 10, 10] });
    const dichtbij = model({ naam: "b.ifc", box: [10.5, 0, 0, 20, 10, 10] });
    const ver = model({ naam: "c.ifc", box: [12, 0, 0, 20, 10, 10] });
    expect(new Set([a, dichtbij, ver].map((m) => m.bron.sleutel)).size).toBe(3);
    expect(overlapWaarschuwing([a, ver], [a, ver])).toBe(true);
    expect(overlapWaarschuwing([a, dichtbij], [a, dichtbij])).toBe(false);
    expect(overlapWaarschuwing([a], [a])).toBe(false);
    expect(overlapWaarschuwing([a, dichtbij, ver], [a, dichtbij, ver])).toBe(false);
  });
});

describe("filteren en tellen", () => {
  const lijst = [
    botsing("k1", "G1", "nieuw", { ernst: "kritiek", categorie: "c1", disciplines: "d1", verdieping: "00", nummer: 1 }),
    botsing("k2", "G1", "actief", { ernst: "klein", categorie: "c1", disciplines: "d2", verdieping: "01", nummer: 2 }),
    botsing("k3", "G2", "nieuw", { ernst: "klein", categorie: "c2", disciplines: "d1", verdieping: "01", nummer: 3 }),
    botsing("k4", "G2", "nieuw", { emmer: "contact", ernst: "klein", categorie: "c2", disciplines: "d1", nummer: 4 }),
    botsing("k5", "G2", "opgelost", { ontwikkeling: "weg", nummer: 5 }),
    botsing("k6", "G2", "opgelost", { ontwikkeling: "eerder_weg", nummer: 6 }),
  ];
  const namen = (l: Clash[]) => l.map((x) => x.naam);

  test("het filter en de aantallen per waarde binnen de overige filters", () => {
    expect(namen(filter(lijst, leegFilter()))).toEqual(["k1", "k2", "k3"]);
    expect(namen(filter(lijst, { ...leegFilter(), ernst: ["klein"] }))).toEqual(["k2", "k3"]);
    expect(namen(filter(lijst, { ...leegFilter(), status: ["nieuw"], disciplines: ["d1"] }))).toEqual(["k1", "k3"]);
    expect(namen(filter(lijst, { ...leegFilter(), tekst: "K2 a" }))).toEqual(["k2"]);
    expect(namen(filter(lijst, { ...leegFilter(), tekst: "#3" }))).toEqual(["k3"]);
    expect(namen(filter(lijst, { ...leegFilter(), emmer: null }))).toEqual(["k1", "k2", "k3", "k4"]);

    const f = { ...leegFilter(), ernst: ["klein" as const], categorie: ["c1"] };
    const fac = facetten(lijst, f);
    // ernst facet: not limited by the ernst filter itself, but by categorie c1.
    expect(fac.ernst).toEqual({ kritiek: 1, klein: 1 });
    // categorie facet: limited by ernst klein.
    expect(fac.categorie).toEqual({ c1: 1, c2: 1 });
    expect(fac.status).toEqual({ actief: 1 });
    expect(fac.disciplines).toEqual({ d2: 1 });
  });

  test("de emmertelling telt alleen gevonden rijen; de som is het totaal", () => {
    const tel = emmerTelling(lijst);
    expect(tel).toEqual({ beoordelen: 3, contact: 1, aangrenzend: 0 });
    expect(tel.beoordelen + tel.contact + tel.aangrenzend).toBe(lijst.filter(isGevonden).length);
  });

  test("een rij zonder emmer telt als te beoordelen", () => {
    const oud = botsing("o", "G", "nieuw", { emmer: null, ontwikkeling: null, ernst: null });
    expect(emmerTelling([oud]).beoordelen).toBe(1);
    expect(isGevonden(oud)).toBe(true);
    expect(namen(filter([oud], leegFilter()))).toEqual(["o"]);
  });

  test("weg toont alleen ontwikkeling weg; eerder_weg alleen met het filter op ontwikkeling", () => {
    expect(namen(filter(lijst, { ...leegFilter(), emmer: "weg" }))).toEqual(["k5"]);
    expect(namen(filter(lijst, { ...leegFilter(), emmer: "beoordelen", ontwikkeling: ["eerder_weg"] }))).toEqual(["k6"]);
    expect(namen(filter(lijst, { ...leegFilter(), emmer: "weg", ontwikkeling: ["eerder_weg"] }))).toEqual(["k6"]);
    expect(isGevonden(lijst[4])).toBe(false);
    expect(isGevonden(lijst[5])).toBe(false);
  });

  test("weg of eerder_weg in het filter toont die rijen ongeacht de emmer, en de rest binnen de emmer", () => {
    const f = { ...leegFilter(), emmer: "beoordelen" as const };
    expect(namen(filter(lijst, { ...f, ontwikkeling: ["weg", "nieuw"] }))).toEqual(["k1", "k2", "k3", "k5"]);
    expect(namen(filter(lijst, { ...f, ontwikkeling: ["weg", "eerder_weg"] }))).toEqual(["k5", "k6"]);
    // A row of another bucket that is gone counts too.
    const inContact = botsing("k7", "G2", "opgelost", { emmer: "contact", ontwikkeling: "eerder_weg" });
    expect(namen(filter([...lijst, inContact], { ...f, ontwikkeling: ["eerder_weg"] }))).toEqual(["k6", "k7"]);
    // The other filters still apply.
    expect(namen(filter(lijst, { ...f, ontwikkeling: ["weg"], tekst: "k6" }))).toEqual([]);
  });

  test("de ontwikkelingsfacet telt ook weg en eerder_weg, met het huidige filter", () => {
    const f = { ...leegFilter(), emmer: "beoordelen" as const };
    const fac = facetten(lijst, f);
    expect(fac.ontwikkeling).toEqual({ nieuw: 3, weg: 1, eerder_weg: 1 });
    // The other facets keep hiding the rows that are gone...
    expect(fac.status).toEqual({ nieuw: 2, actief: 1 });
    // ...until one is chosen: then they count in the other facets too.
    expect(facetten(lijst, { ...f, ontwikkeling: ["eerder_weg"] }).status).toEqual({ opgelost: 1 });
    expect(facetten(lijst, { ...f, ontwikkeling: ["eerder_weg"] }).ontwikkeling).toEqual({ nieuw: 3, weg: 1, eerder_weg: 1 });
    // The other filters still apply.
    expect(facetten(lijst, { ...f, status: ["opgelost"] }).ontwikkeling).toEqual({ weg: 1, eerder_weg: 1 });
    // The bucket "weg" offers eerder_weg as well.
    expect(facetten(lijst, { ...f, emmer: "weg" }).ontwikkeling).toEqual({ weg: 1, eerder_weg: 1 });
  });

  test("een rij zonder lijst in een filter laat niets crashen", () => {
    const f = filterUitWeergave({ ernst: null, status: "nieuw", tekst: 3 });
    expect(namen(filter(lijst, f))).toEqual(["k1", "k2", "k3"]);
  });

  test("groeperen: grootste eerst, lege waarden samen", () => {
    const l = [
      botsing("a", "G", "nieuw", { verdieping: "01" }),
      botsing("b", "G", "nieuw", { verdieping: null }),
      botsing("c", "G", "nieuw", { verdieping: "" }),
      botsing("d", "G", "nieuw", { verdieping: "00" }),
      botsing("e", "G", "nieuw", { verdieping: "00" }),
    ];
    expect(groepeer(l, "verdieping").map((g) => [g.groep, g.botsingen.length])).toEqual([
      ["00", 2],
      [null, 2],
      ["01", 1],
    ]);
  });
});

describe("groeperen van veel rijen", () => {
  test("alle rijen komen in hun groep, op volgorde", () => {
    const veel = Array.from({ length: 5000 }, (_, i) => botsing(`b${i}`, i % 2 ? "G1" : "G2"));
    const [g1, g2] = groepeer(veel);
    expect(g2.botsingen.length + g1.botsingen.length).toBe(5000);
    expect(g1.botsingen[0].naam).toBe("b1");
    expect(g1.botsingen.at(-1)?.naam).toBe("b4999");
  });
});

describe("volgende en vorige", () => {
  test("volgende springt naar de eerstvolgende te beoordelen, en rond", () => {
    const lijst = [b("a", "genegeerd"), b("b", "nieuw"), b("c", "bevestigd"), b("d", "actief")];
    expect(volgende(lijst, "b")).toBe("d");
    expect(volgende(lijst, "d")).toBe("b");
    expect(volgende([b("a", "genegeerd"), b("c", "bevestigd")], "a")).toBe("c");
    expect(volgende([b("c", "bevestigd")], "c")).toBe("c");
  });

  test("volgende zonder huidige en met een lege lijst", () => {
    const lijst = [b("a", "genegeerd"), b("b", "nieuw")];
    expect(volgende(lijst, null)).toBe("b");
    expect(volgende([b("a", "genegeerd")], null)).toBe("a");
    expect(volgende([], null)).toBeNull();
    expect(volgende([], "x")).toBeNull();
  });

  test("vorige is het spiegelbeeld", () => {
    const lijst = [b("a", "genegeerd"), b("b", "nieuw"), b("c", "bevestigd"), b("d", "actief")];
    expect(vorige(lijst, "d")).toBe("b");
    expect(vorige(lijst, "b")).toBe("d");
    expect(vorige([b("a", "genegeerd"), b("c", "bevestigd")], "c")).toBe("a");
    expect(vorige([b("c", "bevestigd")], "c")).toBe("c");
    expect(vorige([], null)).toBeNull();
  });
});

describe("namen en sneltoetsen", () => {
  test("een element zonder naam heet naar zijn klasse", () => {
    expect(elementNaam({ ...element, naam: null, klasse: "IfcWall" })).toBe("IfcWall");
    expect(elementNaam({ ...element, naam: "Wand 1" })).toBe("Wand 1");
    expect(elementNaam({ ...element, naam: null, klasse: null })).toBe("g");
  });

  const toets = (key: string, extra: Partial<Parameters<typeof sneltoets>[0]> = {}) =>
    sneltoets({ key, ctrlKey: false, altKey: false, metaKey: false, target: null, ...extra });

  test("geen sneltoets in een veld of met Ctrl", () => {
    const veld = { tagName: "INPUT" };
    expect(sneltoets({ key: "b", ctrlKey: false, altKey: false, metaKey: false, target: veld })).toBeNull();
    expect(sneltoets({ key: "b", ctrlKey: true, altKey: false, metaKey: false, target: null })).toBeNull();
    expect(sneltoets({ key: "x", ctrlKey: false, altKey: false, metaKey: false, target: null })).toBe("afwijzen");
  });

  test("de sneltoetsen van de spec", () => {
    expect(toets("j")).toBe("volgende");
    expect(toets("ArrowDown")).toBe("volgende");
    expect(toets("k")).toBe("vorige");
    expect(toets("ArrowUp")).toBe("vorige");
    expect(toets("b")).toBe("bevestigen");
    expect(toets("a")).toBe("accepteren");
    expect(toets("Escape")).toBe("alles_tonen");
    expect(toets("?")).toBe("hulp");
    expect(toets("q")).toBeNull();
  });

  test("een vastgehouden toets beslist niet rij na rij; doorlopen mag wel herhalen", () => {
    expect(toets("b", { repeat: true })).toBeNull();
    expect(toets("A", { repeat: true })).toBeNull();
    expect(toets("x", { repeat: true })).toBeNull();
    expect(toets("b", { repeat: false })).toBe("bevestigen");
    expect(toets("j", { repeat: true })).toBe("volgende");
    expect(toets("k", { repeat: true })).toBe("vorige");
    expect(toets("ArrowDown", { repeat: true })).toBe("volgende");
    expect(toets("ArrowUp", { repeat: true })).toBe("vorige");
  });

  test("letters ongeacht hoofdletter; alt en meta blokkeren; ook tekstvelden en bewerkbare delen", () => {
    expect(toets("J")).toBe("volgende");
    expect(toets("A", { altKey: true })).toBeNull();
    expect(toets("a", { metaKey: true })).toBeNull();
    expect(toets("a", { target: { tagName: "TEXTAREA" } })).toBeNull();
    expect(toets("a", { target: { tagName: "SELECT" } })).toBeNull();
    expect(toets("a", { target: { tagName: "DIV", isContentEditable: true } })).toBeNull();
    expect(toets("a", { target: { tagName: "BUTTON" } })).toBe("accepteren");
  });
});

describe("mmWaarde", () => {
  test("accepts numbers from 0 to 1000 with a comma or a point", () => {
    expect(mmWaarde("50")).toBe(50);
    expect(mmWaarde(" 12,5 ")).toBe(12.5);
    expect(mmWaarde("0")).toBe(0);
    expect(mmWaarde("1000")).toBe(1000);
  });

  test("refuses empty, negative, too large and non-numeric text", () => {
    for (const tekst of ["", "  ", "-1", "1000,1", "abc", "1e2", "0x10", "5 mm", "1,2,3"]) expect(mmWaarde(tekst)).toBeNull();
  });
});

describe("voortgangProcent", () => {
  test("turns a fraction into a percentage between 0 and 100", () => {
    expect(voortgangProcent(0.4)).toBe(40);
    expect(voortgangProcent(1)).toBe(100);
    expect(voortgangProcent(0)).toBe(0);
    expect(voortgangProcent(1.2)).toBe(100);
    expect(voortgangProcent(-0.1)).toBe(0);
    expect(voortgangProcent(Number.NaN)).toBe(0);
  });
});

describe("werklijst", () => {
  test("alleen nieuw en actief moet nog beslist worden", () => {
    const rijen = [b("1", "nieuw"), b("2", "actief"), b("3", "bevestigd"), b("4", "geaccepteerd"), b("5", "genegeerd"), b("6", "opgelost")];
    expect(teBeslissen(rijen).map((x) => x.naam)).toEqual(["1", "2"]);
  });

  test("de grenzen van de server", () => {
    expect(REDEN_MAX).toBe(200);
    expect(GROEPSACTIE_MAX).toBe(500);
  });

  test("chips uit een filter, zonder de emmer", () => {
    const f = { ...leegFilter(), ernst: ["groot" as const, "kritiek" as const], verdieping: ["00"], tekst: " muur " };
    expect(filterChips(f)).toEqual([
      { veld: "ernst", waarde: "groot" },
      { veld: "ernst", waarde: "kritiek" },
      { veld: "verdieping", waarde: "00" },
      { veld: "tekst", waarde: "muur" },
    ]);
    expect(filterChips(leegFilter())).toEqual([]);
  });

  test("een chip weghalen laat de rest en de emmer staan", () => {
    const f = { ...leegFilter(), emmer: "contact" as const, ernst: ["groot" as const, "kritiek" as const], tekst: "muur" };
    expect(zonderChip(f, { veld: "ernst", waarde: "groot" })).toEqual({ ...f, ernst: ["kritiek"] });
    expect(zonderChip(f, { veld: "tekst", waarde: "muur" })).toEqual({ ...f, tekst: "" });
  });

  test("open, nieuw en weg van een ronde", () => {
    const rijen = [
      botsing("1", "G", "nieuw", { ontwikkeling: "nieuw" }),
      botsing("2", "G", "bevestigd", { ontwikkeling: "blijft" }),
      botsing("3", "G", "geaccepteerd", { ontwikkeling: "blijft" }),
      botsing("4", "G", "nieuw", { ontwikkeling: "blijft", emmer: "contact" }),
      botsing("5", "G", "actief", { ontwikkeling: "weg" }),
      botsing("6", "G", "nieuw", { ontwikkeling: null, emmer: null }),
    ];
    expect(rondeTelling(rijen)).toEqual({ open: 3, nieuw: 1, weg: 1 });
  });

  test("een zojuist besliste rij blijft in de lijst staan", () => {
    const alle = [b("1", "nieuw"), b("2", "nieuw"), b("3", "genegeerd")];
    const getoond = [alle[0], alle[1]];
    expect(houdVast(getoond, alle, "3").map((x) => x.naam)).toEqual(["1", "2", "3"]);
    expect(houdVast(getoond, alle, "2")).toBe(getoond);
    expect(houdVast(getoond, alle, null)).toBe(getoond);
    expect(houdVast(getoond, alle, "onbekend")).toBe(getoond);
  });

  test("een rij is zichtbaar als ze in de getoonde lijst staat", () => {
    const lijst = [b("1", "nieuw"), b("2", "nieuw")];
    expect(isZichtbaar(lijst, "2")).toBe(true);
    expect(isZichtbaar(lijst, "3")).toBe(false);
    expect(isZichtbaar(lijst, null)).toBe(false);
  });

  test("na een besluit springt alleen door wie nog op die rij staat", () => {
    const lijst = [b("1", "nieuw"), b("2", "nieuw"), b("3", "nieuw")];
    expect(sprongNaBesluit(lijst, "1", "1")).toBe("2");
    expect(sprongNaBesluit(lijst, "1", "3")).toBeNull();
    expect(sprongNaBesluit(lijst, "1", null)).toBeNull();
    expect(sprongNaBesluit([lijst[0]], "1", "1")).toBeNull();
  });
});

describe("een model dat nog niet klaar is", () => {
  test("de modellen die niet meedoen, bij naam", () => {
    const bezig = model({ naam: "x.ifc", status: "bezig" });
    const wacht = model({ naam: "y.ifc", status: "wacht" });
    const fout = model({ naam: "z.ifc", status: "fout" });
    expect(nietGereed([CONSTRUCTIE, INSTALLATIE])).toEqual([]);
    expect(nietGereed([CONSTRUCTIE, bezig, wacht, fout])).toEqual(["x.ifc", "y.ifc", "z.ifc"]);
    expect(nietGereed([])).toEqual([]);
  });
});

describe("wie mag beslissen", () => {
  const ronde = (heeft_opvolger?: boolean) => ({ heeft_opvolger }) as Pick<ClashRound, "heeft_opvolger">;

  test("schrijfrecht en geen opvolger", () => {
    expect(magBeslissen(true, ronde(false))).toBe(true);
    expect(magBeslissen(true, ronde(undefined))).toBe(true);
    expect(magBeslissen(true, ronde(true))).toBe(false);
    expect(magBeslissen(false, ronde(false))).toBe(false);
  });

  test("beslisknoppen op open rijen, heropenen op besliste; niets op rijen die niet gevonden zijn", () => {
    expect(rijActies(b("1", "nieuw"), true)).toEqual({ beslissen: true, heropenen: false });
    expect(rijActies(b("1", "actief"), true)).toEqual({ beslissen: true, heropenen: false });
    for (const status of ["bevestigd", "geaccepteerd", "genegeerd", "opgelost"] as const) {
      expect(rijActies(b("1", status), true)).toEqual({ beslissen: false, heropenen: true });
    }
    for (const ontwikkeling of ["weg", "eerder_weg"] as const) {
      expect(rijActies(botsing("1", "G", "opgelost", { ontwikkeling }), true)).toEqual({ beslissen: false, heropenen: false });
      expect(rijActies(botsing("1", "G", "actief", { ontwikkeling }), true)).toEqual({ beslissen: false, heropenen: false });
    }
    expect(rijActies(b("1", "nieuw"), false)).toEqual({ beslissen: false, heropenen: false });
    expect(rijActies(b("1", "genegeerd"), false)).toEqual({ beslissen: false, heropenen: false });
    // A row from before the review work counts as found.
    expect(rijActies(botsing("1", "G", "nieuw", { ontwikkeling: null }), true)).toEqual({ beslissen: true, heropenen: false });
  });
});

describe("de melding als een element niet in beeld is", () => {
  test("op een rij die weg is, kan het element echt verdwenen zijn", () => {
    expect(nietInBeeldTekst(botsing("1", "G", "opgelost", { ontwikkeling: "weg" }))).toBe("niet_in_beeld_weg");
    expect(nietInBeeldTekst(botsing("1", "G", "opgelost", { ontwikkeling: "eerder_weg" }))).toBe("niet_in_beeld_weg");
  });
  test("op een gevonden rij staat het model uit", () => {
    for (const ontwikkeling of ["nieuw", "blijft", "terug", null] as const) {
      expect(nietInBeeldTekst(botsing("1", "G", "actief", { ontwikkeling }))).toBe("niet_in_beeld");
    }
  });
});

describe("de titel van een ronde", () => {
  const moment = new Date(2026, 10, 4, 14, 32);

  test("de naam met datum en tijd, in de taal van de viewer", () => {
    // The form, not the exact text: the punctuation differs per version of the ICU data ("4 nov 2026" or "4 nov. 2026").
    expect(rondeTitel("Harde botsingen", moment, "nl")).toMatch(/^Harde botsingen 4 nov\.? 2026,? 14[:.]32$/);
    expect(rondeTitel("Hard clashes", moment, "en")).toMatch(/^Hard clashes Nov 4, 2026,? (at )?2:32\sPM$/);
  });

  test("twee rondes op een ander moment heten anders", () => {
    expect(rondeTitel("Harde botsingen", moment, "nl")).not.toBe(rondeTitel("Harde botsingen", new Date(2026, 10, 4, 14, 33), "nl"));
  });
});

describe("weergaven", () => {
  const v = (rest: Partial<ClashView> = {}): ClashView => ({ naam: "N", filter: { ...leegFilter(), ernst: ["kritiek"] }, groep: "verdieping", ...rest });

  test("een oude, foute weergave wordt aangevuld vanuit het lege filter", () => {
    expect(filterUitWeergave({ ernst: null, status: "nieuw", categorie: ["a", 3], tekst: 7, emmer: "onzin", vreemd: [] })).toEqual({
      ...leegFilter(),
      categorie: ["a"],
    });
    expect(filterUitWeergave({ ernst: ["groot"], tekst: "wand", emmer: "weg" })).toEqual({ ...leegFilter(), ernst: ["groot"], tekst: "wand", emmer: "weg" });
    expect(filterUitWeergave({ emmer: null }).emmer).toBeNull();
    for (const geen of [null, undefined, "tekst", 3, []]) expect(filterUitWeergave(geen)).toEqual(leegFilter());
  });

  test("een onbekende groepering wordt klassen", () => {
    expect(groepUitWeergave("verdieping")).toBe("verdieping");
    for (const geen of [null, undefined, "onzin", 3]) expect(groepUitWeergave(geen)).toBe("klassen");
  });

  test("de gekozen weergave telt zolang filter en groepering kloppen", () => {
    const lijst = [v(), v({ naam: "Ander" })];
    const f = lijst[0].filter;
    expect(actieveWeergave(lijst, "N", f, "verdieping")?.naam).toBe("N");
    expect(actieveWeergave(lijst, "N", { ...f, ernst: [] }, "verdieping")).toBeNull();
    expect(actieveWeergave(lijst, "N", f, "klassen")).toBeNull();
    expect(actieveWeergave(lijst, null, f, "verdieping")).toBeNull();
    expect(actieveWeergave(lijst, "Weg", f, "verdieping")).toBeNull();
    // A partial saved filter counts as the same filled-in filter.
    const deels = { naam: "D", filter: { ernst: ["kritiek"] }, groep: "verdieping" } as unknown as ClashView;
    expect(actieveWeergave([deels], "D", f, "verdieping")?.naam).toBe("D");
  });

  test("bewaren herstelt oude foute weergaven, zodat de server ze aanneemt", () => {
    const fout = { naam: "Oud", filter: { ernst: null }, groep: null } as unknown as ClashView;
    expect(schoneWeergaven([fout, v()])).toEqual([{ naam: "Oud", filter: leegFilter(), groep: "klassen" }, v()]);
  });
});

describe("wat niet in beeld te vinden is", () => {
  const rij = botsing("r", "G");
  test("noemt de elementen die niet gevonden zijn, bij naam", () => {
    expect(nietInBeeld(rij, null)).toEqual([]);
    expect(nietInBeeld(rij, { a: true, b: true })).toEqual([]);
    expect(nietInBeeld(rij, { a: false, b: true })).toEqual(["r A"]);
    expect(nietInBeeld(rij, { a: true, b: false })).toEqual(["r B"]);
    expect(nietInBeeld(rij, { a: false, b: false })).toEqual(["r A", "r B"]);
  });
});
