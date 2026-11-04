import type { ModelInfo } from "../host/BimHost";
import type {
  Clash,
  ClashBucket,
  ClashCheck,
  ClashDevelopment,
  ClashElement,
  ClashFilter,
  ClashGroupBy,
  ClashRule,
  ClashSetItem,
  ClashStatus,
} from "./bcf";

export const STATUSSEN: ClashStatus[] = ["nieuw", "actief", "bevestigd", "geaccepteerd", "genegeerd", "opgelost"];

/** Structural classes of the quick choice "construction against installations". */
const KLASSEN_CONSTRUCTIE = ["IfcBeam", "IfcColumn", "IfcFooting", "IfcPile", "IfcMember", "IfcSlab", "IfcWall"];
/** Walls and floors. */
const KLASSEN_VLAK = ["IfcWall", "IfcSlab"];
/** The class set B of the installation choices asks for; the kern includes its subtypes. */
const KLASSE_INSTALLATIES = "IfcDistributionElement";

/**
 * Installation classes as the per-class count of a model knows them (concrete classes only, so the abstract
 * `IfcDistributionElement` never shows up there).
 */
const INSTALLATIE_KLASSE =
  /^Ifc(Flow|Distribution|Duct|Pipe|Cable|Air|Light|Sanitary|Valve|Pump|Fan|Boiler|Chiller|Coil|Compressor|Condenser|Damper|Electric|Fire|Heat|Humidifier|Interceptor|Junction|Lamp|Motor|Outlet|Protective|Sensor|Space[A-Z]|Stack|Switching|Tank|Transformer|Tube|Unitary|Waste|Alarm|Actuator|Controller|Audio|Communications|Cooled|Cooling|Evaporat|Medical|Burner|Engine|Filter)/;

/** The first folder of the model folder; a model directly in the folder gets its file name without `.ifc`. */
export function disciplineVan(model: ModelInfo): string {
  const discipline = model.discipline.trim();
  if (discipline) return discipline;
  const naam = model.naam.split("/").pop() ?? model.naam;
  return naam.replace(/\.ifc$/i, "");
}

export type Voorinstelling = {
  id: string;
  controles: ClashCheck[];
  beschikbaar: boolean;
  /** Translation key of the reason why the choice is not available. */
  reden: string | null;
  /** The tolerance can be chosen (near-clashes). */
  instelbaar: boolean;
};

const REDEN = "voorinstelling_reden";

function klaar(modellen: ModelInfo[]): ModelInfo[] {
  return modellen.filter((m) => m.status === "klaar");
}

function alle(modellen: ModelInfo[]): ClashSetItem[] {
  return modellen.map((m) => ({ bestand: m.bron.sleutel }));
}

function metKlassen(modellen: ModelInfo[], klassen: string[]): ClashSetItem[] {
  return modellen.map((m) => ({ bestand: m.bron.sleutel, klassen }));
}

function telKlassen(modellen: ModelInfo[], past: (klasse: string) => boolean): boolean {
  return modellen.some((m) => Object.entries(m.index?.aantallen_per_klasse ?? {}).some(([klasse, aantal]) => aantal > 0 && past(klasse)));
}

/** Millimetres typed in a field (comma or point), 0 to 1000; null when it is not a number in that range. */
export function mmWaarde(tekst: string): number | null {
  const schoon = tekst.trim().replace(",", ".");
  if (!/^\d+(\.\d+)?$/.test(schoon)) return null;
  const mm = Number(schoon);
  return mm <= 1000 ? mm : null;
}

/** Near-clashes between models, at `mm` millimetres. */
export function bijnaMet(mm: number, modellen: ModelInfo[]): ClashCheck[] {
  const set = alle(klaar(modellen));
  return [{ set_a: set, set_b: set, soort: "afstand", tolerantie: mm / 1000, alleen_tussen_modellen: true }];
}

/** The rules as checks. Rules that are off and pairs without models are left out; millimetres become metres. */
export function controlesUitRegels(regels: ClashRule[], modellen: ModelInfo[]): ClashCheck[] {
  const gereed = klaar(modellen);
  const controles: ClashCheck[] = [];
  for (const regel of regels) {
    if (regel.soort === "uit") continue;
    const a = gereed.filter((m) => disciplineVan(m) === regel.a);
    const b = gereed.filter((m) => disciplineVan(m) === regel.b);
    if (a.length === 0 || b.length === 0) continue;
    controles.push({
      regel: `${regel.a} × ${regel.b}`,
      set_a: alle(a),
      set_b: alle(b),
      soort: regel.soort,
      tolerantie: regel.mm / 1000,
      ernst: regel.ernst ?? null,
    });
  }
  return controles;
}

/** The quick choices as checks, each with whether the models allow it. The "set it yourself" form is not one of them. */
export function voorinstellingen(modellen: ModelInfo[], regels: ClashRule[] = []): Voorinstelling[] {
  const gereed = klaar(modellen);
  const set = alle(gereed);
  const constructie = telKlassen(gereed, (k) => KLASSEN_CONSTRUCTIE.includes(k));
  const vlak = telKlassen(gereed, (k) => KLASSEN_VLAK.includes(k));
  const installaties = telKlassen(gereed, (k) => INSTALLATIE_KLASSE.test(k));

  const keuze = (
    id: string,
    controles: ClashCheck[],
    reden: string | null,
    instelbaar = false,
  ): Voorinstelling => {
    const bijModellen = gereed.length === 0 ? `${REDEN}.geen_modellen` : reden;
    return { id, controles, beschikbaar: bijModellen === null, reden: bijModellen, instelbaar };
  };
  const tegenInstallaties = (klassen: string[]): ClashCheck[] => [
    { set_a: metKlassen(gereed, klassen), set_b: metKlassen(gereed, [KLASSE_INSTALLATIES]), soort: "hard", tolerantie: 0 },
  ];
  const eenModel = gereed.length < 2 ? `${REDEN}.een_model` : null;
  const regelControles = controlesUitRegels(regels, modellen);

  return [
    keuze("harde", [{ set_a: set, set_b: set, soort: "hard", tolerantie: 0 }], null),
    keuze(
      "constructie_installaties",
      tegenInstallaties(KLASSEN_CONSTRUCTIE),
      !constructie ? `${REDEN}.geen_constructie` : !installaties ? `${REDEN}.geen_installaties` : null,
    ),
    keuze(
      "wanden_installaties",
      tegenInstallaties(KLASSEN_VLAK),
      !vlak ? `${REDEN}.geen_wanden_vloeren` : !installaties ? `${REDEN}.geen_installaties` : null,
    ),
    keuze("tussen_modellen", [{ set_a: set, set_b: set, soort: "hard", tolerantie: 0, alleen_tussen_modellen: true }], eenModel),
    keuze("bijna", bijnaMet(50, modellen), eenModel, true),
    keuze("dubbel", [{ set_a: set, set_b: set, soort: "dubbel", tolerantie: 0 }], null),
    keuze("regels", regelControles, regelControles.length === 0 ? `${REDEN}.geen_regels` : null),
  ];
}

/** Code-point order, like Python's `sorted` on the server. */
function codepunt(a: string, b: string): number {
  return a < b ? -1 : a > b ? 1 : 0;
}

function sorteerPaar(a: string, b: string): [string, string] {
  return codepunt(a, b) <= 0 ? [a, b] : [b, a];
}

/**
 * A rule for every pair of the disciplines: between different disciplines `hard`, within one `uit`. A saved rule goes
 * before the default; saved rules for disciplines that have no model now stay, so saving never loses them.
 */
export function standaardRegels(disciplines: string[], bewaard: ClashRule[]): ClashRule[] {
  const regels = new Map<string, ClashRule>();
  const sleutel = (a: string, b: string) => `${a}\u0000${b}`;
  for (const regel of bewaard) {
    const [a, b] = sorteerPaar(regel.a, regel.b);
    regels.set(sleutel(a, b), { ...regel, a, b });
  }
  const uniek = [...new Set(disciplines)].sort(codepunt);
  uniek.forEach((a, i) => {
    for (const b of uniek.slice(i)) {
      if (!regels.has(sleutel(a, b))) regels.set(sleutel(a, b), { a, b, soort: a === b ? "uit" : "hard", mm: 0, ernst: null });
    }
  });
  return [...regels.values()].sort((x, y) => codepunt(x.a, y.a) || codepunt(x.b, y.b));
}

/** Metres that two boxes may be apart and still count as touching. */
const OVERLAP_MARGE = 1;

/**
 * True when none of the models of set A comes near a model of set B (boxes within 1 m of each other). A model without a
 * box is unknown, so it never gives a warning.
 */
export function overlapWaarschuwing(a: ModelInfo[], b: ModelInfo[]): boolean {
  if (a.length === 0 || b.length === 0) return false;
  for (const x of a) {
    for (const y of b) {
      const dx = x.index?.begrenzing;
      const dy = y.index?.begrenzing;
      if (!dx || !dy) return false;
      const raakt = [0, 1, 2].every((as) => dx.min[as] - OVERLAP_MARGE <= dy.max[as] && dy.min[as] - OVERLAP_MARGE <= dx.max[as]);
      if (raakt) return false;
    }
  }
  return true;
}

const BEOORDELEN: ClashBucket = "beoordelen";

function leeg(waarde: string | null | undefined): boolean {
  return waarde == null || waarde === "";
}

function emmerVan(b: Clash): ClashBucket {
  return b.emmer ?? BEOORDELEN;
}

/** Found in the round: new, still there or back. Rows from before the review work count as found. */
export function isGevonden(b: Clash): boolean {
  const o = b.ontwikkeling;
  return o == null || o === "nieuw" || o === "blijft" || o === "terug";
}

export function leegFilter(): ClashFilter {
  return { emmer: BEOORDELEN, ernst: [], status: [], categorie: [], disciplines: [], verdieping: [], ontwikkeling: [], tekst: "" };
}

function zoektekst(b: Clash): string {
  return [
    b.nummer == null ? "" : `#${b.nummer}`,
    elementNaam(b.element_a),
    elementNaam(b.element_b),
    b.element_a.klasse,
    b.element_b.klasse,
    b.element_a.globalid,
    b.element_b.globalid,
    b.verdieping,
    b.raster,
    b.ruimte,
    b.reden,
  ]
    .filter((deel): deel is string => !leeg(deel))
    .join(" ")
    .toLowerCase();
}

function inLijst<T>(lijst: T[], waarde: T | null | undefined): boolean {
  return lijst.length === 0 || (waarde != null && lijst.includes(waarde));
}

function past(b: Clash, f: ClashFilter, toonWeg = false): boolean {
  const ontwikkeling: ClashDevelopment | null = b.ontwikkeling;
  if (f.emmer === "weg") {
    if (ontwikkeling !== "weg") return false;
  } else if (f.emmer !== null) {
    if (!isGevonden(b) || emmerVan(b) !== f.emmer) return false;
  } else if (f.ontwikkeling.length === 0 && !toonWeg && !isGevonden(b)) {
    // Rows that are gone only show up through the filter on development.
    return false;
  }
  if (!inLijst(f.ontwikkeling, ontwikkeling ?? "blijft")) return false;
  if (!inLijst(f.ernst, b.ernst) || !inLijst(f.status, b.status)) return false;
  if (!inLijst(f.categorie, b.categorie) || !inLijst(f.disciplines, b.disciplines) || !inLijst(f.verdieping, b.verdieping)) return false;
  const tekst = f.tekst.trim().toLowerCase();
  return tekst === "" || zoektekst(b).includes(tekst);
}

export function filter(botsingen: Clash[], f: ClashFilter): Clash[] {
  return botsingen.filter((b) => past(b, f));
}

/** The filters that have a list of values (and so a count per value). */
export type Facetten = Pick<ClashFilter, "ernst" | "status" | "categorie" | "disciplines" | "verdieping" | "ontwikkeling">;

const FACET_VELDEN: (keyof Facetten)[] = ["ernst", "status", "categorie", "disciplines", "verdieping", "ontwikkeling"];

function waardeVan(b: Clash, veld: keyof Facetten): string | null {
  const waarde = veld === "ontwikkeling" ? (b.ontwikkeling ?? "blijft") : b[veld];
  return leeg(waarde) ? null : waarde;
}

/** Per filter, the number of clashes per value within all the other filters (the filter itself is left out). */
export function facetten(botsingen: Clash[], f: ClashFilter): Record<keyof Facetten, Record<string, number>> {
  const uit = {} as Record<keyof Facetten, Record<string, number>>;
  for (const veld of FACET_VELDEN) {
    const tel: Record<string, number> = {};
    // The development facet also counts rows that are gone, so their chips can be offered.
    const toonWeg = veld === "ontwikkeling";
    for (const b of botsingen.filter((x) => past(x, { ...f, [veld]: [] }, toonWeg))) {
      const waarde = waardeVan(b, veld);
      if (waarde !== null) tel[waarde] = (tel[waarde] ?? 0) + 1;
    }
    uit[veld] = tel;
  }
  return uit;
}

/** Found rows per bucket; the sum is the total of found rows. */
export function emmerTelling(botsingen: Clash[]): Record<ClashBucket, number> {
  const tel: Record<ClashBucket, number> = { beoordelen: 0, contact: 0, aangrenzend: 0 };
  for (const b of botsingen) if (isGevonden(b)) tel[emmerVan(b)] += 1;
  return tel;
}

function groepWaarde(b: Clash, op: ClashGroupBy): string | null {
  const waarde = op === "klassen" ? b.groep : b[op];
  return leeg(waarde) ? null : waarde;
}

/**
 * Clashes per value of `op`, the largest group first, equal groups by name. Rows without a value come together in the
 * group `null`, which comes last among equal ones; the screens name it.
 */
export function groepeer(botsingen: Clash[], op: ClashGroupBy = "klassen"): { groep: string | null; botsingen: Clash[] }[] {
  const groepen = new Map<string | null, Clash[]>();
  for (const b of botsingen) {
    const groep = groepWaarde(b, op);
    groepen.set(groep, [...(groepen.get(groep) ?? []), b]);
  }
  return [...groepen]
    .map(([groep, lijst]) => ({ groep, botsingen: lijst }))
    .sort(
      (a, b) =>
        b.botsingen.length - a.botsingen.length ||
        (a.groep === null ? 1 : 0) - (b.groep === null ? 1 : 0) ||
        (a.groep ?? "").localeCompare(b.groep ?? ""),
    );
}

export function telStatussen(botsingen: Clash[]): Record<ClashStatus, number> {
  const tel = Object.fromEntries(STATUSSEN.map((s) => [s, 0])) as Record<ClashStatus, number>;
  for (const b of botsingen) tel[b.status] += 1;
  return tel;
}

const TE_BEOORDELEN: ClashStatus[] = ["nieuw", "actief"];

/** Moves through the shown list: to the next one still to judge (round, not onto itself), else the neighbour. */
function sprong(lijst: Clash[], huidige: string | null, richting: 1 | -1): string | null {
  if (lijst.length === 0) return null;
  const n = lijst.length;
  const teBeoordelen = (b: Clash) => TE_BEOORDELEN.includes(b.status);
  const i = lijst.findIndex((b) => b.naam === huidige);
  if (i < 0) {
    const volgorde = richting === 1 ? lijst : [...lijst].reverse();
    return (volgorde.find(teBeoordelen) ?? volgorde[0]).naam;
  }
  for (let stap = 1; stap < n; stap += 1) {
    const kandidaat = lijst[(((i + richting * stap) % n) + n) % n];
    if (teBeoordelen(kandidaat)) return kandidaat.naam;
  }
  return (lijst[i + richting] ?? lijst[i]).naam;
}

/** The next clash to judge after `huidige` within the shown list; after the end, from the start again. */
export function volgende(lijst: Clash[], huidige: string | null): string | null {
  return sprong(lijst, huidige, 1);
}

/** The same the other way round. */
export function vorige(lijst: Clash[], huidige: string | null): string | null {
  return sprong(lijst, huidige, -1);
}

/** The name of an element, or its class when it has no name, or its GlobalId. */
export function elementNaam(e: ClashElement): string {
  return !leeg(e.naam) ? (e.naam as string) : !leeg(e.klasse) ? (e.klasse as string) : e.globalid;
}

/** Both elements of a clash, to mark in the view. */
export function elementenVan(botsing: Clash): { bestand: string; globalid: string }[] {
  return [botsing.element_a, botsing.element_b].map(({ bestand, globalid }) => ({ bestand, globalid }));
}

export type SneltoetsActie = "volgende" | "vorige" | "bevestigen" | "accepteren" | "afwijzen" | "alles_tonen" | "hulp";

const SNELTOETSEN: Record<string, SneltoetsActie> = {
  j: "volgende",
  arrowdown: "volgende",
  k: "vorige",
  arrowup: "vorige",
  b: "bevestigen",
  a: "accepteren",
  x: "afwijzen",
  escape: "alles_tonen",
  "?": "hulp",
};

function isVeld(target: unknown): boolean {
  if (typeof target !== "object" || target === null) return false;
  const { tagName, isContentEditable } = target as { tagName?: unknown; isContentEditable?: unknown };
  return tagName === "INPUT" || tagName === "TEXTAREA" || tagName === "SELECT" || isContentEditable === true;
}

/** The action of a key press in the clash list; none in a field or with Ctrl, Alt or Meta. */
export function sneltoets(e: Pick<KeyboardEvent, "key" | "ctrlKey" | "altKey" | "metaKey"> & { target: unknown }): SneltoetsActie | null {
  if (e.ctrlKey || e.altKey || e.metaKey || isVeld(e.target)) return null;
  return SNELTOETSEN[e.key.toLowerCase()] ?? null;
}
