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

export type ClashRound = {
  naam: string;
  titel: string;
  set_a: ClashSetItem[];
  set_b: ClashSetItem[];
  soort: "hard" | "afstand";
  tolerantie: number;
  status: "wacht" | "bezig" | "klaar" | "fout";
  aantal: number;
  bron_versies: Record<string, string>;
  vorige_ronde: string | null;
  gestart: string;
  gestart_door: string;
  fout: { error_code: string; melding: string } | null;
};

export type ClashElement = { bestand: string; versie: string; globalid: string };

export type ClashStatus = "nieuw" | "actief" | "opgelost" | "genegeerd";

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
