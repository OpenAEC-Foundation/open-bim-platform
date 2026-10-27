import * as OBC from "@thatopen/components";
// The fragments worker comes from the bundle, never from a CDN.
import workerUrl from "@thatopen/fragments/worker?url";

type World = OBC.SimpleWorld<OBC.SimpleScene, OBC.SimpleCamera, OBC.SimpleRenderer>;

/** The 3D view: That Open components with one world, holding fragments models by key (sourceKey + part). */
export class FragmentsEngine {
  private readonly components = new OBC.Components();
  private readonly world: World;
  private readonly fragments: OBC.FragmentsManager;

  constructor(container: HTMLElement) {
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

  dispose(): void {
    this.components.dispose();
  }
}
