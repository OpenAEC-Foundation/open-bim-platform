/**
 * Issues and clashes as the SuperCloud gives them: the JSON of the BCF API 3.0 (topics, comments, viewpoints,
 * extensions) and the clash rounds of openaec_bim.
 *
 * Coordinates: three.js is Y-up and That Open moves the models near the origin (it adds the coordinates of the first
 * loaded model, `basis`, in three.js coordinates); IFC, BCF and the clash points of the kern are Z-up world
 * coordinates.
 * The conversion lives here and nowhere else.
 */

export type Vec3 = [number, number, number];
export type Point = { x: number; y: number; z: number };

export type PerspectiveCamera = {
  camera_view_point: Point;
  camera_direction: Point;
  camera_up_vector: Point;
  field_of_view: number;
  aspect_ratio?: number;
};

export type BcfCamera = { perspective_camera: PerspectiveCamera };

export type Component = { ifc_guid: string; originating_system?: string; authoring_tool_id?: string };

export type Components = {
  selection?: Component[];
  coloring?: { color: string; components: Component[] }[];
  visibility?: {
    default_visibility: boolean;
    exceptions?: Component[];
    view_setup_hints?: { spaces_visible?: boolean; space_boundaries_visible?: boolean; openings_visible?: boolean };
  };
};

export type Viewpoint = {
  guid?: string;
  index?: number | null;
  perspective_camera?: PerspectiveCamera;
  orthogonal_camera?: Omit<PerspectiveCamera, "field_of_view"> & { view_to_world_scale: number };
  lines?: { start_point: Point; end_point: Point }[];
  clipping_planes?: { location: Point; direction: Point }[];
  components?: Components;
  snapshot?: { snapshot_type: "png" | "jpg"; snapshot_data?: string } | null;
};

/** An element of a topic in the version the project shows, followed along the version links. */
export type TopicElement = { ifc_guid: string; bestand: string | null; versie: string | null; teruggevonden: boolean };

export type Topic = {
  guid: string;
  title: string;
  topic_type: string | null;
  topic_status: string | null;
  priority: string | null;
  labels: string[];
  description: string | null;
  assigned_to: string | null;
  due_date: string | null;
  stage: string | null;
  index: number | null;
  reference_links: string[];
  creation_date: string;
  creation_author: string;
  modified_date: string;
  modified_author: string | null;
  authorization: { topic_actions: string[]; topic_status: string[] };
  elementen?: TopicElement[];
};

/** What the viewer sends to create or change a topic. */
export type TopicInput = Partial<Omit<Topic, "authorization" | "elementen" | "creation_date" | "creation_author">>;

export type Comment = {
  guid: string;
  date: string;
  author: string;
  comment: string;
  topic_guid: string;
  viewpoint_guid: string | null;
  modified_date: string | null;
  modified_author: string | null;
  authorization: { comment_actions: string[] };
};

export type Extensions = {
  topic_type: string[];
  topic_status: string[];
  topic_label: string[];
  snippet_type: string[];
  priority: string[];
  users: string[];
  stage: string[];
  project_actions: string[];
  topic_actions: string[];
  comment_actions: string[];
};

export type ClashSetItem = { bestand: string; klassen?: string[] };

/** How a check looks for clashes: overlap, a distance, or the same element twice. */
export type ClashKind = "hard" | "afstand" | "dubbel";

/** Where a clash stands: exactly one. */
export type ClashBucket = "beoordelen" | "contact" | "aangrenzend";

export type ClashSeverity = "klein" | "groot" | "kritiek";

/** What a clash did compared to the previous round. */
export type ClashDevelopment = "nieuw" | "blijft" | "terug" | "weg" | "eerder_weg";

/** One question to the kern: set A against set B. */
export type ClashCheck = {
  regel?: string;
  set_a: ClashSetItem[];
  set_b: ClashSetItem[];
  soort: ClashKind;
  /** Metres. */
  tolerantie: number;
  ernst?: ClashSeverity | null;
  alleen_tussen_modellen?: boolean;
};

/** A project rule for a pair of disciplines (`a` sorts before `b`); `mm` is millimetres. */
export type ClashRule = { a: string; b: string; soort: "uit" | "hard" | "afstand"; mm: number; ernst: ClashSeverity | null };

export type ClashFilter = {
  emmer: ClashBucket | "weg" | null;
  ernst: ClashSeverity[];
  status: ClashStatus[];
  categorie: string[];
  disciplines: string[];
  verdieping: string[];
  ontwikkeling: ClashDevelopment[];
  tekst: string;
};

export type ClashGroupBy = "klassen" | "verdieping" | "disciplines" | "ernst" | "categorie" | "raster" | "ruimte" | "ontwikkeling";

/** A saved view of the clash list. */
export type ClashView = { naam: string; filter: ClashFilter; groep: ClashGroupBy };

export type ClashSettings = { regels: ClashRule[]; weergaven: ClashView[]; mag_wijzigen: boolean };

export type ClashSummary = {
  totaal: number;
  open: number;
  nieuw: number;
  blijft: number;
  terug: number;
  weg: number;
  per_status: Partial<Record<ClashStatus, number>>;
  per_ernst: Partial<Record<ClashSeverity, number>>;
  per_emmer: Partial<Record<ClashBucket, number>>;
  per_categorie: Record<string, number>;
  regels_gewijzigd: boolean;
};

/** A point in the development of a series of rounds. */
export type ClashTrend = { naam: string; titel: string; gestart: string; samenvatting: ClashSummary | null };

export type ClashRound = {
  naam: string;
  titel: string;
  set_a: ClashSetItem[];
  set_b: ClashSetItem[];
  soort: ClashKind | "gemengd";
  tolerantie: number;
  status: "wacht" | "bezig" | "klaar" | "fout";
  aantal: number;
  bron_versies: Record<string, string>;
  vorige_ronde: string | null;
  gestart: string;
  gestart_door: string;
  fout: { error_code: string; melding: string } | null;
  /** The normalised checks of the round; empty for rounds from before the checks. */
  regels?: ClashCheck[] | null;
  voorinstelling?: string | null;
  reeks?: string | null;
  /** Progress while the round runs, 0 to 100. */
  voortgang?: number | null;
  samenvatting?: ClashSummary | null;
};

export type ClashElement = {
  bestand: string;
  versie: string;
  globalid: string;
  klasse: string | null;
  naam: string | null;
  verdieping: string | null;
};

export type ClashStatus = "nieuw" | "actief" | "bevestigd" | "geaccepteerd" | "genegeerd" | "opgelost";

/**
 * A clash as the server gives it. Rows from before the review work have empty fields: a missing `emmer` counts as
 * `beoordelen`, a missing `ontwikkeling` as found.
 */
export type Clash = {
  naam: string;
  ronde: string;
  sleutel: string;
  element_a: ClashElement;
  element_b: ClashElement;
  punt: Vec3;
  afstand: number;
  status: ClashStatus;
  issue: string | null;
  groep: string;
  soort: ClashKind | null;
  regel: string | null;
  emmer: ClashBucket | null;
  emmer_reden: string | null;
  ernst: ClashSeverity | null;
  categorie: string | null;
  disciplines: string | null;
  verdieping: string | null;
  raster: string | null;
  ruimte: string | null;
  ontwikkeling: ClashDevelopment | null;
  nummer: number | null;
  reden: string | null;
  beoordeeld_door: string | null;
  beoordeeld_op: string | null;
};

/** Below this share of elements found again in a new version, the viewer warns that the link is uncertain. */
export const KOPPEL_DREMPEL = 0.9;

/** Distance in front of a BCF camera where the viewer puts the target (BCF has no target). */
const TARGET_DISTANCE = 10;

const ZERO: Vec3 = [0, 0, 0];

/**
 * A point in three.js coordinates to IFC world coordinates (Z-up). That Open puts a model at its IFC position turned
 * Y-up plus `basis`, the coordinates of the first loaded model (measured in the viewer); this undoes that.
 */
export function threeToIfc(p: Vec3, basis: Vec3 = ZERO): Vec3 {
  const [x, y, z] = [p[0] - basis[0], p[1] - basis[1], p[2] - basis[2]];
  return [x, -z, y];
}

/** A point in IFC world coordinates (Z-up) to three.js coordinates: turned Y-up, plus `basis`. */
export function ifcToThree(p: Vec3, basis: Vec3 = ZERO): Vec3 {
  return [p[0] + basis[0], p[2] + basis[1], -p[1] + basis[2]];
}

/** A direction: rotated, never moved. */
function threeDirToIfc(d: Vec3): Vec3 {
  return [d[0], -d[2], d[1]];
}

function ifcDirToThree(d: Vec3): Vec3 {
  return [d[0], d[2], -d[1]];
}

function normalize(v: Vec3): Vec3 {
  const length = Math.hypot(...v) || 1;
  return [v[0] / length, v[1] / length, v[2] / length];
}

function point(v: Vec3): Point {
  return { x: v[0], y: v[1], z: v[2] };
}

function vec(p: Point): Vec3 {
  return [p.x, p.y, p.z];
}

/** The camera of the view (three.js coordinates) as a BCF perspective camera. */
export function toBcfCamera(position: Vec3, target: Vec3, up: Vec3, fovDeg: number, aspect: number, basis: Vec3 = ZERO): BcfCamera {
  const direction = normalize([target[0] - position[0], target[1] - position[1], target[2] - position[2]]);
  return {
    perspective_camera: {
      camera_view_point: point(threeToIfc(position, basis)),
      camera_direction: point(threeDirToIfc(direction)),
      camera_up_vector: point(normalize(threeDirToIfc(up))),
      field_of_view: fovDeg,
      aspect_ratio: aspect,
    },
  };
}

/** A BCF perspective camera as position, target and up in three.js coordinates. */
export function fromBcfCamera(camera: BcfCamera, basis: Vec3 = ZERO): { position: Vec3; target: Vec3; up: Vec3 } {
  const c = camera.perspective_camera;
  const position = ifcToThree(vec(c.camera_view_point), basis);
  const direction = normalize(ifcDirToThree(vec(c.camera_direction)));
  return {
    position,
    target: [
      position[0] + direction[0] * TARGET_DISTANCE,
      position[1] + direction[1] * TARGET_DISTANCE,
      position[2] + direction[2] * TARGET_DISTANCE,
    ],
    up: normalize(ifcDirToThree(vec(c.camera_up_vector))),
  };
}
