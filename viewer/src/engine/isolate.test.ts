import { describe, expect, it } from "vitest";
import { isolateRadius, MAX_RADIUS, MIN_RADIUS } from "./isolate";

describe("isolateRadius", () => {
  it("is half the diagonal of the joint box", () => {
    expect(isolateRadius([6, 8, 0])).toBe(5);
  });
  it("is at most 10 m", () => {
    expect(isolateRadius([100, 100, 100])).toBe(MAX_RADIUS);
  });
  it("is at least 0.5 m, also without a box", () => {
    expect(isolateRadius([0.1, 0.1, 0.1])).toBe(MIN_RADIUS);
    expect(isolateRadius(null)).toBe(MIN_RADIUS);
    expect(isolateRadius([NaN, 1, 1])).toBe(MIN_RADIUS);
  });
});
