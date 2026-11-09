import type { IsolateResult } from "../engine/isolate";
import type { ModelInfo } from "../host/BimHost";
import type {
  Clash,
  ClashBucket,
  ClashCheck,
  ClashDevelopment,
  ClashElement,
  ClashFilter,
  ClashGroupBy,
  ClashRound,
  ClashRule,
  ClashSetItem,
  ClashStatus,
  ClashView,
} from "./bcf";

/** Structural classes of the quick choice "construction against installations". */
const KLASSEN_CONSTRUCTIE = ["IfcBeam", "IfcColumn", "IfcFooting", "IfcPile", "IfcMember", "IfcSlab", "IfcWall"];
/** Walls and floors. */
const KLASSEN_VLAK = ["IfcWall", "IfcSlab"];
/**
 * The per-class count knows concrete classes, while the kern asks for a class with its subtypes: these common subclasses
 * of the structural classes count as the class they belong to.
 */
const SUBKLASSE = /(StandardCase|ElementedCase)$/;
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

/** The most checks one round may have, as on the server. */
export const MAX_CONTROLES = 30;

function klaar(modellen: ModelInfo[]): ModelInfo[] {
  return modellen.filter((m) => m.status === "klaar");
}

/** The names of the models that do not take part in a quick choice because they are not ready. */
export function nietGereed(modellen: ModelInfo[]): string[] {
  return modellen.filter((m) => m.status !== "klaar").map((m) => m.naam);
}

function alle(modellen: ModelInfo[]): ClashSetItem[] {
  return modellen.map((m) => ({ bestand: m.bron.sleutel }));
}

function metKlassen(modellen: ModelInfo[], klassen: string[]): ClashSetItem[] {
  return modellen.map((m) => ({ bestand: m.bron.sleutel, klassen }));
}

function basisKlasse(klasse: string): string {
  return klasse.replace(SUBKLASSE, "");
}

function telKlassen(modellen: ModelInfo[], past: (klasse: string) => boolean): boolean {
  return modellen.some((m) => Object.entries(m.index?.aantallen_per_klasse ?? {}).some(([klasse, aantal]) => aantal > 0 && past(klasse)));
}

/** Progress of a round as a whole percentage; the server sends a fraction from 0 to 1. */
export function voortgangProcent(voortgang: number): number {
  if (Number.isNaN(voortgang)) return 0;
  return Math.min(100, Math.max(0, Math.round(voortgang * 100)));
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
  const constructie = telKlassen(gereed, (k) => KLASSEN_CONSTRUCTIE.includes(basisKlasse(k)));
  const vlak = telKlassen(gereed, (k) => KLASSEN_VLAK.includes(basisKlasse(k)));
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
  // The saved rules are what the project changed; every other pair of disciplines follows the default.
  const regelControles = regels.length > 0 ? controlesUitRegels(standaardRegels(gereed.map(disciplineVan), regels), modellen) : [];

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
    keuze(
      "regels",
      regelControles,
      regelControles.length === 0 ? `${REDEN}.geen_regels` : regelControles.length > MAX_CONTROLES ? `${REDEN}.te_veel_regels` : null,
    ),
  ];
}

/** The title of a new round: the name of the choice with the date and time, in the language of the viewer. */
export function rondeTitel(naam: string, moment: Date, taal: string): string {
  return `${naam} ${new Intl.DateTimeFormat(taal, { dateStyle: "medium", timeStyle: "short" }).format(moment)}`;
}

/** Order by code point, like Python compares text; the operators of JavaScript compare UTF-16 units, which differs above U+FFFF. */
function codepunten(a: string, b: string): number {
  const x = Array.from(a, (teken) => teken.codePointAt(0) as number);
  const y = Array.from(b, (teken) => teken.codePointAt(0) as number);
  for (let i = 0; i < Math.min(x.length, y.length); i++) if (x[i] !== y[i]) return x[i] - y[i];
  return x.length - y.length;
}

/** The order of disciplines, as on the server (`_volgorde`): alphabetical without regard to case, then by code point. */
function volgorde(a: string, b: string): number {
  return codepunten(a.toLowerCase(), b.toLowerCase()) || codepunten(a, b);
}

function sorteerPaar(a: string, b: string): [string, string] {
  return volgorde(a, b) <= 0 ? [a, b] : [b, a];
}

/** The rule of a pair when the project sets none: between two disciplines a hard check, within one nothing. */
export function standaardRegel(a: string, b: string): ClashRule {
  return { a, b, soort: a === b ? "uit" : "hard", mm: 0, ernst: null };
}

/**
 * The rules to save: those that differ from the default of their pair, as the other pairs follow the default anyway. A
 * rule that is off keeps its distance, so switching it on again gives the distance back.
 */
export function teBewarenRegels(regels: ClashRule[]): ClashRule[] {
  return regels.filter((r) => {
    const standaard = standaardRegel(r.a, r.b);
    return r.soort !== standaard.soort || r.mm !== standaard.mm || (r.ernst ?? null) !== standaard.ernst;
  });
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
  const uniek = [...new Set(disciplines)].sort(volgorde);
  uniek.forEach((a, i) => {
    for (const b of uniek.slice(i)) {
      if (!regels.has(sleutel(a, b))) regels.set(sleutel(a, b), standaardRegel(a, b));
    }
  });
  return [...regels.values()].sort((x, y) => volgorde(x.a, y.a) || volgorde(x.b, y.b));
}

/** Metres that two boxes may be apart and still count as touching. */
const OVERLAP_MARGE = 1;

/**
 * True when at least one pair of different models (by source key) was compared and none of those pairs comes near each
 * other (boxes within 1 m). A model is never compared with itself. A model without a box is unknown, so it never gives a
 * warning.
 */
export function overlapWaarschuwing(a: ModelInfo[], b: ModelInfo[]): boolean {
  let vergeleken = false;
  for (const x of a) {
    for (const y of b) {
      if (x.bron.sleutel === y.bron.sleutel) continue;
      const dx = x.index?.begrenzing;
      const dy = y.index?.begrenzing;
      if (!dx || !dy) return false;
      const raakt = [0, 1, 2].every((as) => dx.min[as] - OVERLAP_MARGE <= dy.max[as] && dy.min[as] - OVERLAP_MARGE <= dx.max[as]);
      if (raakt) return false;
      vergeleken = true;
    }
  }
  return vergeleken;
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
  const gevonden = isGevonden(b);
  // Rows that are gone are in no bucket: they show up through the filter on development, whatever the bucket.
  const doorFilter = !gevonden && (toonWeg || (ontwikkeling !== null && f.ontwikkeling.includes(ontwikkeling)));
  if (!doorFilter) {
    if (f.emmer === "weg") {
      if (ontwikkeling !== "weg") return false;
    } else if (!gevonden || (f.emmer !== null && emmerVan(b) !== f.emmer)) {
      return false;
    }
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
    const lijst = groepen.get(groep);
    if (lijst) lijst.push(b);
    else groepen.set(groep, [b]);
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

const TE_BEOORDELEN: ClashStatus[] = ["nieuw", "actief"];
/** Statuses that still count as open work in the summary of a round. */
const OPEN_STATUSSEN: ClashStatus[] = ["nieuw", "actief", "bevestigd"];

/** The longest reason the server accepts. */
export const REDEN_MAX = 200;
/** The most rows one group action may handle. */
export const GROEPSACTIE_MAX = 500;

/** The rows that still wait for a decision (new or active); a group action touches only these. */
export function teBeslissen(botsingen: Clash[]): Clash[] {
  return botsingen.filter((b) => TE_BEOORDELEN.includes(b.status));
}

/** Deciding is allowed: write permission, and no later round builds on this one. */
export function magBeslissen(magWijzigen: boolean, ronde: Pick<ClashRound, "heeft_opvolger">): boolean {
  return magWijzigen && !ronde.heeft_opvolger;
}

/** What can be done with a row: decide while it is open, reopen once decided; nothing on a row that was not found. */
export function rijActies(b: Clash, mag: boolean): { beslissen: boolean; heropenen: boolean } {
  const kan = mag && isGevonden(b);
  const open = TE_BEOORDELEN.includes(b.status);
  return { beslissen: kan && open, heropenen: kan && !open };
}

/** An active filter as a chip that can be clicked away. The bucket is not a chip. */
export type FilterChip = { veld: keyof Facetten | "tekst"; waarde: string };

export function filterChips(f: ClashFilter): FilterChip[] {
  const chips: FilterChip[] = [];
  for (const veld of FACET_VELDEN) for (const waarde of f[veld]) chips.push({ veld, waarde });
  if (f.tekst.trim() !== "") chips.push({ veld: "tekst", waarde: f.tekst.trim() });
  return chips;
}

export function zonderChip(f: ClashFilter, chip: FilterChip): ClashFilter {
  if (chip.veld === "tekst") return { ...f, tekst: "" };
  return { ...f, [chip.veld]: (f[chip.veld] as string[]).filter((w) => w !== chip.waarde) };
}

/** The most views a project keeps, as on the server. */
export const WEERGAVEN_MAX = 50;

/** A new view fits while there are fewer than the maximum; saving under a name that exists replaces that view. */
export function kanWeergaveBewaren(weergaven: ClashView[], naam: string): boolean {
  const schoon = naam.trim();
  return weergaven.length < WEERGAVEN_MAX || weergaven.some((w) => w.naam === schoon);
}

export const GROEPERINGEN: ClashGroupBy[] = ["klassen", "verdieping", "disciplines", "ernst", "categorie", "raster", "ruimte", "ontwikkeling"];
const EMMER_KEUZES: unknown[] = [BEOORDELEN, "contact", "aangrenzend", "weg", null];

/** The filter of a saved view, filled in from the empty filter; whatever has the wrong shape is ignored. */
export function filterUitWeergave(bewaard: unknown): ClashFilter {
  const uit = leegFilter();
  if (typeof bewaard !== "object" || bewaard === null) return uit;
  const v = bewaard as Record<string, unknown>;
  for (const veld of FACET_VELDEN) {
    const lijst = v[veld];
    if (Array.isArray(lijst)) (uit[veld] as unknown[]) = lijst.filter((w) => typeof w === "string");
  }
  if (typeof v.tekst === "string") uit.tekst = v.tekst;
  if (EMMER_KEUZES.includes(v.emmer)) uit.emmer = v.emmer as ClashFilter["emmer"];
  return uit;
}

/** The grouping of a saved view; an unknown one becomes the default. */
export function groepUitWeergave(bewaard: unknown): ClashGroupBy {
  return GROEPERINGEN.includes(bewaard as ClashGroupBy) ? (bewaard as ClashGroupBy) : "klassen";
}

/** The views as the server accepts them: an old view of the wrong shape must not block saving the others. */
export function schoneWeergaven(weergaven: ClashView[]): ClashView[] {
  return weergaven.map((v) => ({ naam: v.naam, filter: filterUitWeergave(v.filter), groep: groepUitWeergave(v.groep) }));
}

/** The chosen view, as long as the list still shows what it says. */
export function actieveWeergave(weergaven: ClashView[], naam: string | null, f: ClashFilter, groep: ClashGroupBy): ClashView | null {
  const v = weergaven.find((x) => x.naam === naam);
  if (!v || groepUitWeergave(v.groep) !== groep) return null;
  return JSON.stringify(filterUitWeergave(v.filter)) === JSON.stringify(filterUitWeergave(f)) ? v : null;
}

/** Open, new and gone rows of a round, from the rows as they are now. */
export function rondeTelling(botsingen: Clash[]): { open: number; nieuw: number; weg: number } {
  const tel = { open: 0, nieuw: 0, weg: 0 };
  for (const b of botsingen) {
    if (b.ontwikkeling === "weg") tel.weg += 1;
    if (!isGevonden(b)) continue;
    if (b.ontwikkeling === "nieuw") tel.nieuw += 1;
    if (emmerVan(b) === BEOORDELEN && OPEN_STATUSSEN.includes(b.status)) tel.open += 1;
  }
  return tel;
}

/** The shown list, plus the pinned row (one just decided) when the filters would hide it now. */
export function houdVast(getoond: Clash[], alle: Clash[], naam: string | null): Clash[] {
  if (naam === null || getoond.some((b) => b.naam === naam)) return getoond;
  const rij = alle.find((b) => b.naam === naam);
  return rij ? [...getoond, rij] : getoond;
}

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

/** The elements of a clash that an isolation could not find in the view, by name. */
export function nietInBeeld(b: Clash, uit: IsolateResult | null): string[] {
  if (!uit) return [];
  return [...(uit.a ? [] : [elementNaam(b.element_a)]), ...(uit.b ? [] : [elementNaam(b.element_b)])];
}

/** On a row that is gone the element may really have left the model; "is the model on?" would send you the wrong way. */
export function nietInBeeldTekst(b: Clash): "niet_in_beeld" | "niet_in_beeld_weg" {
  return b.ontwikkeling === "weg" || b.ontwikkeling === "eerder_weg" ? "niet_in_beeld_weg" : "niet_in_beeld";
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

/** A decision is one key press: holding the key must not decide row after row. */
const EEN_KEER: SneltoetsActie[] = ["bevestigen", "accepteren", "afwijzen"];

/** The action of a key press in the clash list; none in a field, with Ctrl, Alt or Meta, or for a held decision key. */
export function sneltoets(e: Pick<KeyboardEvent, "key" | "ctrlKey" | "altKey" | "metaKey"> & { target: unknown; repeat?: boolean }): SneltoetsActie | null {
  if (e.ctrlKey || e.altKey || e.metaKey || isVeld(e.target)) return null;
  const actie = SNELTOETSEN[e.key.toLowerCase()] ?? null;
  return actie && e.repeat && EEN_KEER.includes(actie) ? null : actie;
}

/** The selected row can be seen in the shown list (so a keypress may act on it). */
export function isZichtbaar(zichtbaar: Clash[], naam: string | null): boolean {
  return naam !== null && zichtbaar.some((b) => b.naam === naam);
}

/** Where to jump after a decision on `besloten`: nowhere when the selection has moved on meanwhile. */
export function sprongNaBesluit(zichtbaar: Clash[], besloten: string, huidige: string | null): string | null {
  if (huidige !== besloten) return null;
  const naam = volgende(zichtbaar, besloten);
  return naam === besloten ? null : naam;
}
