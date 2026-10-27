import * as OBC from "@thatopen/components";
import * as FRAGS from "@thatopen/fragments";
// The fragments worker comes from the bundle, never from a CDN.
import workerUrl from "@thatopen/fragments/worker?url";
import * as THREE from "three";

type World = OBC.SimpleWorld<OBC.SimpleScene, OBC.SimpleCamera, OBC.SimpleRenderer>;

/** An element hit in the view: the engine key of its model part and its GlobalId. */
export type Pick = { key: string; globalid: string };

/** The 3D view: That Open components with one world, holding fragments models by key (sourceKey + part). */
export class FragmentsEngine {
  private readonly components = new OBC.Components();
  private readonly world: World;
  private readonly fragments: OBC.FragmentsManager;

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
    for (const model of this.fragments.list.values()) await model.resetHighlight();
    if (target) {
      const material = this.highlightMaterial();
      for (const key of target.keys) {
        const model = this.fragments.list.get(key);
        const [localId] = (await model?.getLocalIdsByGuids([target.globalid])) ?? [];
        if (model && localId != null) await model.highlight([localId], material);
      }
    }
    await this.fragments.core.update(true);
  }

  dispose(): void {
    this.components.dispose();
  }

  /** The accent colour of the active style-book theme. */
  private highlightMaterial(): FRAGS.MaterialDefinition {
    const accent = getComputedStyle(this.container).getPropertyValue("--theme-accent").trim();
    return {
      color: new THREE.Color(accent),
      renderedFaces: FRAGS.RenderedFaces.TWO,
      opacity: 1,
      transparent: false,
    };
  }
}
