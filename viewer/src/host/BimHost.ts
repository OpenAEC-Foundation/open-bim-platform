import type {
  Clash,
  ClashRound,
  ClashSetItem,
  ClashStatus,
  Comment,
  Extensions,
  Topic,
  TopicInput,
  Viewpoint,
} from "../model/bcf";

/**
 * The host layer: everything the viewer needs from outside. Locally it is the development server (LocalHost); in the
 * workspace of the SuperCloud it becomes the message bridge of the guest page, without changes to the rest.
 */

export type ModelSource = { soort: "bestand"; sleutel: string; versie: string };

/** Identity of a model version: the same GlobalId in two sources stays two things. */
export function sourceKey(s: ModelSource): string {
  return `${s.soort}:${s.sleutel}@${s.versie}`;
}

export type ModelStatus = "wacht" | "bezig" | "klaar" | "fout";

export type KernFout = { error_code: string; melding: string; remedie: string };

export type Bounds = { min: [number, number, number]; max: [number, number, number] };

export type ModelPart = { naam: string; bytes: number };

/** index.json as written by the kern's `omzetten`. */
export type ModelIndex = {
  schema: string;
  lengte_eenheid: string | null;
  georeferentie: Record<string, number | string | null> | null;
  begrenzing: Bounds | null;
  aantallen_per_klasse: Record<string, number>;
  aantallen_per_verdieping: Record<string, number>;
  omzetter: string;
  delen: (ModelPart & { verdiepingen: string[] })[];
};

export type ModelInfo = {
  bron: ModelSource;
  naam: string;
  discipline: string;
  status: ModelStatus;
  /** Progress of the conversion, 0 to 1, while it runs (when the host knows it). */
  voortgang?: number;
  fout?: KernFout | null;
  delen: ModelPart[];
  index: ModelIndex | null;
  /** The link of this version to the previous converted one (SuperCloud); below KOPPEL_DREMPEL it is uncertain. */
  koppeling?: { vorige_versie: string; matchrate: number } | null;
};

export type Project = { project: string; werkwijze: string; modellen: ModelInfo[] };

export type Classification = { systeem: string | null; code: string; naam: string | null };

export type ElementProperties = {
  klasse: string;
  naam: string | null;
  type: string | null;
  verdieping: string | null;
  psets: Record<string, Record<string, unknown>>;
  hoeveelheden: Record<string, Record<string, unknown>>;
  materialen: string[];
  classificaties: Classification[];
};

export interface BimHost {
  project(): Promise<Project>;
  /** The bytes of one converted part (`delen[].naam`) of a model version. */
  laad(bron: ModelSource, deel: string): Promise<ArrayBuffer>;
  eigenschappen(bron: ModelSource, globalids: string[]): Promise<Record<string, ElementProperties>>;
  /** Issues (BCF 3.0) and clash rounds; only in the SuperCloud, where they are stored per project. */
  readonly coordinatie?: Coordinatie;
}

/** Issues and clashes of the open project (the model folder of the page). */
export interface Coordinatie {
  instellingen(): Promise<Extensions>;
  issues(): Promise<Topic[]>;
  /** A new topic, or with `guid` a change (409 when `modified_date` is out of date). */
  issueBewaar(topic: TopicInput): Promise<Topic>;
  issueVerwijder(guid: string): Promise<void>;
  reacties(guid: string): Promise<Comment[]>;
  reactieBewaar(guid: string, reactie: { guid?: string; comment: string; viewpoint_guid?: string | null }): Promise<Comment>;
  /** The viewpoints of a topic, without the snapshots themselves (see `snapshot`). */
  standpunten(guid: string): Promise<Viewpoint[]>;
  standpuntBewaar(guid: string, standpunt: Viewpoint): Promise<Viewpoint>;
  snapshot(guid: string, standpunt: string): Promise<{ snapshot_type: "png" | "jpg"; snapshot_data: string }>;
  bcfExport(versie: "2.1" | "3.0"): Promise<{ bestand: string }>;
  /** The guest page lets the user pick a .bcfzip in Storage; null when cancelled. */
  bcfImport(): Promise<{ nieuw: number; bijgewerkt: number } | null>;
  botsingsrondeStart(setA: ClashSetItem[], setB: ClashSetItem[], soort: "hard" | "afstand", tolerantie: number, titel?: string): Promise<{ ronde: string }>;
  botsingsrondes(): Promise<ClashRound[]>;
  botsingen(ronde: string): Promise<Clash[]>;
  botsingStatus(botsing: string, status: ClashStatus): Promise<Clash>;
  botsingNaarIssue(botsing: string): Promise<Topic>;
}

/** An error answer of the host, carrying the kern's {error_code, melding, remedie}. */
export class HostError extends Error {
  constructor(
    readonly status: number,
    readonly fout: KernFout | null,
  ) {
    super(fout?.melding ?? `HTTP ${status}`);
  }
}
