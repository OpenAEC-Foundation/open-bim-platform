import { describe, expect, test } from "vitest";
import { KOPPEL_DREMPEL, fromBcfCamera, ifcToThree, threeToIfc, toBcfCamera } from "./bcf";

function normalize(v: [number, number, number]) {
  const l = Math.hypot(...v);
  return v.map((c) => c / l);
}

function close(a: number[], b: number[]) {
  expect(a.length).toBe(b.length);
  a.forEach((x, i) => expect(x).toBeCloseTo(b[i], 9));
}

describe("bcf", () => {
  test("three.js is Y-up, IFC and BCF are Z-up", () => {
    close(threeToIfc([1, 2, 3]), [1, -3, 2]);
    close(ifcToThree([1, -3, 2]), [1, 2, 3]);
  });

  test("the offset of the first loaded model is undone, both ways", () => {
    const basis: [number, number, number] = [100, 0, -200];
    close(threeToIfc([1, 2, 3], basis), [-99, -203, 2]);
    close(ifcToThree(threeToIfc([1, 2, 3], basis), basis), [1, 2, 3]);
  });

  test("measured in the viewer: That Open adds the coordinates of the first model", () => {
    // A duct at IFC (4.8, 6.0, 2.2), first model with coordinates (-4, -2.1, 0): in three.js at (0.8, 0.1, -6.0).
    close(ifcToThree([4.8, 6.0, 2.2], [-4, -2.1, 0]), [0.8, 0.1, -6.0]);
    close(threeToIfc([0.8, 0.1, -6.0], [-4, -2.1, 0]), [4.8, 6.0, 2.2]);
  });

  test("camera heen en terug", () => {
    const c = toBcfCamera([10, 5, 3], [0, 0, 0], [0, 1, 0], 60, 1.5);
    const p = c.perspective_camera;
    expect(p.camera_view_point).toEqual({ x: 10, y: -3, z: 5 });
    close([p.camera_direction.x, p.camera_direction.y, p.camera_direction.z], normalize([-10, 3, -5]));
    close([p.camera_up_vector.x, p.camera_up_vector.y, p.camera_up_vector.z], [0, 0, 1]);
    expect(p.aspect_ratio).toBe(1.5);
    expect(p.field_of_view).toBe(60);
    const terug = fromBcfCamera(c);
    close(terug.position, [10, 5, 3]);
    close(terug.up, [0, 1, 0]);
    close(normalize(terug.target.map((t, i) => t - terug.position[i]) as [number, number, number]), normalize([-10, -5, -3]));
  });

  test("a camera without a target distance looks 10 m ahead", () => {
    const terug = fromBcfCamera(toBcfCamera([0, 0, 0], [0, 0, -2], [0, 1, 0], 45, 1));
    close(terug.target, [0, 0, -10]);
  });

  test("the match rate threshold", () => {
    expect(KOPPEL_DREMPEL).toBe(0.9);
  });
});
