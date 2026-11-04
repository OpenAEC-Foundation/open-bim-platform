import type { BcfCamera, Vec3, Viewpoint } from "../model/bcf";

/** An element to mark: its file (null when unknown: then every loaded model is searched) and GlobalId. */
export type ElementRef = { bestand: string | null; globalid: string };

/** What the issue and clash panels may do with the view; the app implements it with the engine. */
export interface Weergave {
  /** The current camera, or null while nothing is loaded. */
  camera(): BcfCamera | null;
  /** The GlobalIds of the selected elements. */
  selectie(): string[];
  /** A PNG of the current view. */
  snapshot(): Promise<Blob | null>;
  /** Put the camera of a viewpoint back (if it has one) and mark the elements. */
  toon(standpunt: Viewpoint | null, elementen: ElementRef[]): Promise<void>;
  /** Look at a point in IFC world coordinates and mark the elements. */
  focus(punt: Vec3, elementen: ElementRef[]): Promise<void>;
  /** Show a clash: element A and B marked, the rest ghosted, the camera on the point. */
  isoleer(a: ElementRef, b: ElementRef, punt: Vec3): Promise<void>;
  /** Look at one element and mark it. */
  naarElement(e: ElementRef): Promise<void>;
  /** Back to the normal view. */
  herstel(): Promise<void>;
}
