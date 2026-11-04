import * as OBC from "@thatopen/components";
import * as FRAGS from "@thatopen/fragments";
// The fragments worker comes from the bundle, never from a CDN.
import workerUrl from "@thatopen/fragments/worker?url";
import * as THREE from "three";
import { fromBcfCamera, ifcToThree, toBcfCamera, type BcfCamera, type Vec3 } from "../model/bcf";
import { isolateRadius } from "./isolate";

/** Ghost everything but the two elements of a clash; false only marks them and moves the camera. */
export const ISOLATE_GHOST = true;
/** Opacity of the ghosted rest of the model. */
const GHOST_OPACITY = 0.12;

/** An element to act on: its model parts and GlobalId. */
export type Target = { keys: string[]; globalid: string };

type World = OBC.SimpleWorld<OBC.SimpleScene, OBC.SimpleCamera, OBC.SimpleRenderer>;

/** An element hit in the view: the engine key of its model part and its GlobalId. */
export type Pick = { key: string; globalid: string };

/** The 3D view: That Open components with one world, holding fragments models by key (sourceKey + part). */
export class FragmentsEngine {
  private readonly components = new OBC.Components();
  private readonly world: World;
  private readonly fragments: OBC.FragmentsManager;
  /** Keys of the models that the current isolation ghosted. */
  private readonly ghosted = new Set<string>();

  constructor(private readonly container: HTMLElement) {
    const worlds = this.components.get(OBC.Worlds);
    this.world = worlds.create<OBC.SimpleScene, OBC.SimpleCamera, OBC.SimpleRenderer>();
    this.world.scene = new OBC.SimpleScene(this.components);
    this.world.scene.setup();
    // No colour of our own: the canvas is transparent and shows the page background from the design tokens.
    this.world.scene.three.background = null;
    this.world.renderer = new OBC.SimpleRenderer(this.components, container);
    this.world.renderer.three.setClearAlpha(0);
    this.world.camera = new OBC.SimpleCamera(this.components);
    this.components.init();

    this.fragments = this.components.get(OBC.FragmentsManager);
    this.fragments.init(workerUrl);
    this.world.camera.controls.addEventListener("rest", () => void this.fragments.core.update(true));
  }

  /** Keys of the loaded models. */
  get loaded(): string[] {
    return [...this.fragments.list.keys()];
  }

  async load(key: string, bytes: ArrayBuffer): Promise<void> {
    if (this.fragments.list.has(key)) return;
    const model = await this.fragments.core.load(bytes, { modelId: key, camera: this.world.camera.three });
    this.world.scene.three.add(model.object);
    await this.fragments.core.update(true);
  }

  async unload(key: string): Promise<void> {
    if (!this.fragments.list.has(key)) return;
    await this.fragments.core.disposeModel(key);
    await this.fragments.core.update(true);
  }

  /** Point the camera at everything that is loaded. */
  async fit(): Promise<void> {
    if (this.fragments.list.size) await this.world.camera.fitToItems();
  }

  /** The element under a point of the screen (client coordinates), if any. */
  async pick(clientX: number, clientY: number): Promise<Pick | null> {
    const renderer = this.world.renderer;
    if (!renderer || this.fragments.list.size === 0) return null;
    const hit = await this.fragments.raycast({
      camera: this.world.camera.three,
      mouse: new THREE.Vector2(clientX, clientY),
      dom: renderer.three.domElement,
    });
    if (!hit) return null;
    const [globalid] = await hit.fragments.getGuidsByLocalIds([hit.localId]);
    return globalid ? { key: hit.fragments.modelId, globalid } : null;
  }

  /** Mark one element, looked up by GlobalId in the given model parts; null clears the marking. */
  async highlight(target: { keys: string[]; globalid: string } | null): Promise<void> {
    await this.highlightMany(target ? [target] : []);
  }

  /** Mark several elements at once (the elements of an issue, both sides of a clash); an empty list clears. */
  async highlightMany(targets: { keys: string[]; globalid: string }[]): Promise<void> {
    for (const model of this.fragments.list.values()) await model.resetHighlight();
    const material = this.highlightMaterial();
    for (const target of targets) {
      for (const key of target.keys) {
        const model = this.fragments.list.get(key);
        const [localId] = (await model?.getLocalIdsByGuids([target.globalid])) ?? [];
        if (model && localId != null) await model.highlight([localId], material);
      }
    }
    await this.fragments.core.update(true);
  }

  /**
   * Show a clash: both elements marked (A in the accent colour, B in the info colour), the rest of the models that hold
   * them ghosted, and the camera on the point. A previous isolation is cleared first.
   */
  async isolate(a: Target[], b: Target[], point: Vec3): Promise<void> {
    await this.clearIsolation();
    const found = new Map<string, { model: FRAGS.FragmentsModel; id: number; material: FRAGS.MaterialDefinition }[]>();
    const boxes: THREE.Box3[] = [];
    const sides: [Target[], FRAGS.MaterialDefinition][] = [
      [a, this.markMaterial("--theme-accent")],
      [b, this.markMaterial("--color-semantic-info")],
    ];
    for (const [targets, material] of sides) {
      for (const target of targets) {
        for (const key of target.keys) {
          const model = this.fragments.list.get(key);
          if (!model) continue;
          const [id] = (await model.getLocalIdsByGuids([target.globalid])) ?? [];
          if (id == null) continue;
          found.set(key, [...(found.get(key) ?? []), { model, id, material }]);
          boxes.push((await model.getMergedBox([id])).applyMatrix4(model.object.matrixWorld));
        }
      }
    }
    // Only models that hold one of the elements are touched; any other model stays at normal opacity.
    for (const [key, entries] of found) {
      const model = entries[0].model;
      if (ISOLATE_GHOST) {
        this.ghosted.add(key);
        await model.setOpacity(undefined, GHOST_OPACITY);
        await model.resetOpacity(entries.map((entry) => entry.id));
      }
      for (const { id, material } of entries) await model.highlight([id], material);
    }
    const size = boxes.length ? this.jointSize(boxes) : null;
    await this.focus(point, isolateRadius(size));
  }

  /** Look at elements (the joint box of all of them) and mark them; when none is found nothing moves. */
  async focusElements(targets: Target[]): Promise<void> {
    await this.clearIsolation();
    await this.highlightMany(targets);
    const boxes: THREE.Box3[] = [];
    for (const target of targets) {
      for (const key of target.keys) {
        const model = this.fragments.list.get(key);
        const [id] = (await model?.getLocalIdsByGuids([target.globalid])) ?? [];
        if (model && id != null) boxes.push((await model.getMergedBox([id])).applyMatrix4(model.object.matrixWorld));
      }
    }
    if (!boxes.length) return;
    const joint = boxes.reduce((all, box) => all.union(box), new THREE.Box3());
    await this.focusThree(joint.getCenter(new THREE.Vector3()), isolateRadius(this.jointSize(boxes)));
  }

  /** Back to the normal view: full opacity everywhere and no marking. */
  async clearIsolation(): Promise<void> {
    for (const key of this.ghosted) {
      const model = this.fragments.list.get(key);
      if (model) await model.resetOpacity(undefined);
    }
    this.ghosted.clear();
    for (const model of this.fragments.list.values()) await model.resetHighlight();
    await this.fragments.core.update(true);
  }

  private jointSize(boxes: THREE.Box3[]): [number, number, number] {
    const size = boxes.reduce((all, box) => all.union(box), new THREE.Box3()).getSize(new THREE.Vector3());
    return [size.x, size.y, size.z];
  }

  /** The current view as a BCF perspective camera (IFC world coordinates). */
  camera(): BcfCamera {
    const three = this.world.camera.three as THREE.PerspectiveCamera;
    const position = this.world.camera.controls.getPosition(new THREE.Vector3());
    const target = this.world.camera.controls.getTarget(new THREE.Vector3());
    return toBcfCamera(position.toArray(), target.toArray(), three.up.toArray(), three.fov, three.aspect, this.basis());
  }

  /** Move the view to a BCF perspective camera. */
  async setCamera(camera: BcfCamera): Promise<void> {
    const { position, target, up } = fromBcfCamera(camera, this.basis());
    const three = this.world.camera.three as THREE.PerspectiveCamera;
    three.up.set(...up);
    this.world.camera.controls.updateCameraUp();
    if (camera.perspective_camera.field_of_view && "fov" in three) {
      three.fov = camera.perspective_camera.field_of_view;
      three.updateProjectionMatrix();
    }
    await this.world.camera.controls.setLookAt(...position, ...target, true);
    await this.fragments.core.update(true);
  }

  /** Look at a point (IFC world coordinates, such as a clash point) from a distance that fits `radius` metres. */
  async focus(point: Vec3, radius: number): Promise<void> {
    await this.focusThree(new THREE.Vector3(...ifcToThree(point, this.basis())), radius);
  }

  private async focusThree(center: THREE.Vector3, radius: number): Promise<void> {
    await this.world.camera.controls.fitToSphere(new THREE.Sphere(center, Math.max(radius, 0.5)), true);
    await this.fragments.core.update(true);
  }

  /** A PNG of the view, on the page background (the canvas itself is transparent). */
  async snapshot(): Promise<Blob> {
    const renderer = this.world.renderer;
    if (!renderer) throw new Error("No view to capture.");
    const canvas = renderer.three.domElement;
    renderer.three.render(this.world.scene.three, this.world.camera.three);
    const beeld = document.createElement("canvas");
    beeld.width = canvas.width;
    beeld.height = canvas.height;
    const context = beeld.getContext("2d");
    if (!context) throw new Error("No 2D context for the snapshot.");
    context.fillStyle = getComputedStyle(this.container).backgroundColor || "#ffffff";
    if (context.fillStyle === "rgba(0, 0, 0, 0)") context.fillStyle = "#ffffff";
    context.fillRect(0, 0, beeld.width, beeld.height);
    context.drawImage(canvas, 0, 0);
    return new Promise((klaar, mis) => beeld.toBlob((blob) => (blob ? klaar(blob) : mis(new Error("No snapshot."))), "image/png"));
  }

  dispose(): void {
    this.components.dispose();
  }

  /** The offset That Open gave the models: the coordinates of the first loaded model, in three.js coordinates. */
  private basis(): Vec3 {
    const b = this.fragments.core.baseCoordinates;
    return b && b.length >= 3 ? [b[0], b[1], b[2]] : [0, 0, 0];
  }

  /** The accent colour of the active style-book theme. */
  private highlightMaterial(): FRAGS.MaterialDefinition {
    return this.markMaterial("--theme-accent");
  }

  /** A marking material in the colour of a style-book token, read from the page at the moment of use. */
  private markMaterial(token: string): FRAGS.MaterialDefinition {
    const colour = getComputedStyle(this.container).getPropertyValue(token).trim();
    return {
      color: new THREE.Color(colour),
      renderedFaces: FRAGS.RenderedFaces.TWO,
      opacity: 1,
      transparent: false,
    };
  }
}
