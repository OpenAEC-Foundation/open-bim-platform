import * as THREE from "three";
import { describe, expect, it, vi } from "vitest";
import { FragmentsEngine } from "./FragmentsEngine";

/** Only what `isolate` touches of the 3D world: one model holding one element, without a canvas. */
function engineWith(model: Record<string, unknown>) {
  const update = vi.fn(async () => undefined);
  const engine = Object.create(FragmentsEngine.prototype);
  Object.assign(engine, {
    fragments: { list: new Map([["m", model]]), core: { update } },
    ghosted: new Set<string>(),
    markMaterial: () => ({}),
    jointSize: () => [1, 1, 1],
    basis: () => [0, 0, 0],
    jump: vi.fn(async () => undefined),
  });
  return { engine: engine as { isolate: FragmentsEngine["isolate"]; ghosted: Set<string>; jump: () => Promise<void> }, update };
}

function modelFailingOn(step: string) {
  const fail = (name: string) => async () => {
    if (name === step) throw new Error(`${name} kapot`);
  };
  return {
    getLocalIdsByGuids: async () => [7],
    getMergedBox: async () => new THREE.Box3(new THREE.Vector3(0, 0, 0), new THREE.Vector3(1, 1, 1)),
    setOpacity: vi.fn(fail("setOpacity")),
    resetOpacity: vi.fn(async () => undefined),
    highlight: vi.fn(fail("highlight")),
    resetHighlight: vi.fn(async () => undefined),
  };
}

const target = { keys: ["m"], globalid: "g" };

describe("isolate", () => {
  it("leaves nothing transparent behind when marking fails, and keeps the error", async () => {
    const model = modelFailingOn("highlight");
    const { engine, update } = engineWith(model);
    await expect(engine.isolate([target], [target], [0, 0, 0])).rejects.toThrow("highlight kapot");
    expect(model.setOpacity).toHaveBeenCalled();
    expect(model.resetOpacity).toHaveBeenLastCalledWith(undefined);
    expect(engine.ghosted.size).toBe(0);
    expect(update).toHaveBeenCalledWith(true);
  });

  it("leaves nothing transparent behind when moving the camera fails", async () => {
    const model = modelFailingOn("niets");
    const { engine, update } = engineWith(model);
    engine.jump = async () => {
      throw new Error("camera kapot");
    };
    await expect(engine.isolate([target], [target], [0, 0, 0])).rejects.toThrow("camera kapot");
    expect(model.resetOpacity).toHaveBeenLastCalledWith(undefined);
    expect(model.resetHighlight).toHaveBeenCalled();
    expect(update).toHaveBeenCalledWith(true);
  });

  it("keeps the first error when going back fails too", async () => {
    const model = modelFailingOn("setOpacity");
    let calls = 0;
    const { engine } = engineWith({
      ...model,
      resetHighlight: async () => {
        // The reset at the start of `isolate` succeeds; the one after the error fails.
        if (++calls > 1) throw new Error("terug kapot");
      },
    });
    await expect(engine.isolate([target], [target], [0, 0, 0])).rejects.toThrow("setOpacity kapot");
  });

  it("keeps the marks when all goes well", async () => {
    const model = modelFailingOn("niets");
    const { engine } = engineWith(model);
    await expect(engine.isolate([target], [target], [0, 0, 0])).resolves.toEqual({ a: true, b: true });
    expect(engine.ghosted.has("m")).toBe(true);
    expect(model.highlight).toHaveBeenCalled();
  });
});
