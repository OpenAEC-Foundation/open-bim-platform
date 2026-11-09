import { describe, expect, it } from "vitest";
import { isolateRadius, MAX_RADIUS, MIN_RADIUS } from "./isolate";

describe("isolateRadius", () => {
  it("is half the diagonal of the element", () => {
    expect(isolateRadius([[6, 8, 0]])).toBe(5);
  });
  it("follows the smallest element: a small element against a large one", () => {
    // A baluster against the ceiling finish of a whole storey.
    expect(isolateRadius([[0.04, 0.04, 0.9], [40, 30, 0.02]])).toBe(MIN_RADIUS);
    expect(isolateRadius([[40, 30, 0.02], [0.3, 0.4, 2]])).toBeCloseTo(Math.hypot(0.3, 0.4, 2) / 2);
    expect(isolateRadius([[6, 8, 0], [12, 16, 0]])).toBe(5);
  });
  it("uses the other element when one is empty", () => {
    expect(isolateRadius([null, [6, 8, 0]])).toBe(5);
    expect(isolateRadius([[6, 8, 0], null])).toBe(5);
    expect(isolateRadius([[0, 0, 0], [6, 8, 0]])).toBe(5);
    expect(isolateRadius([[NaN, 1, 1], [6, 8, 0]])).toBe(5);
  });
  it("is at most 10 m", () => {
    expect(isolateRadius([[100, 100, 100], [200, 200, 200]])).toBe(MAX_RADIUS);
  });
  it("is at least 0.5 m, also without a box", () => {
    expect(isolateRadius([[0.1, 0.1, 0.1]])).toBe(MIN_RADIUS);
    expect(isolateRadius([null, null])).toBe(MIN_RADIUS);
    expect(isolateRadius([])).toBe(MIN_RADIUS);
    expect(isolateRadius([[NaN, 1, 1]])).toBe(MIN_RADIUS);
  });
});
