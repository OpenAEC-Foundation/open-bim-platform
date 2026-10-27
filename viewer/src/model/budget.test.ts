import { expect, test } from "vitest";
import type { ModelInfo, ModelStatus } from "../host/BimHost";
import { DEFAULT_BUDGET, estimateBytes, planLoad } from "./budget";

let counter = 0;
function m(fragBytes: number, status: ModelStatus = "klaar", parts = 1): ModelInfo {
  counter += 1;
  return {
    bron: { soort: "bestand", sleutel: `m${counter}.ifc`, versie: "0123456789ab" },
    naam: `m${counter}`,
    discipline: "",
    status,
    delen: Array.from({ length: parts }, (_, i) => ({ naam: `deel-${i + 1}.frag`, bytes: fragBytes / parts })),
    index: null,
  };
}

test("estimate is 18 times the fragments bytes of all parts", () => {
  expect(estimateBytes(m(100e6, "klaar", 4))).toBe(1.8e9);
});

test("default budget is 2 GiB", () => expect(DEFAULT_BUDGET).toBe(2 * 1024 ** 3));

test("loads in order until budget", () => {
  // 1.8e9 + 0.18e9 fits in 2 GiB, + 0.36e9 does not
  const plan = planLoad([m(100e6), m(10e6), m(20e6)], DEFAULT_BUDGET);
  expect(plan.load).toHaveLength(2);
  expect(plan.available).toHaveLength(1);
});

test("a model that does not fit stops the loading: the ones after it wait too", () => {
  const plan = planLoad([m(10e6), m(200e6), m(1e6)], DEFAULT_BUDGET);
  expect(plan.load.map((x) => x.naam)).toEqual([plan.load[0].naam]);
  expect(plan.available).toHaveLength(2);
});

test("first model always loads", () => expect(planLoad([m(500e6)], 1).load).toHaveLength(1));

test("skips models not ready", () => {
  const plan = planLoad([m(1e6, "bezig"), m(1e6, "fout"), m(1e6, "wacht")], DEFAULT_BUDGET);
  expect(plan.load).toHaveLength(0);
  expect(plan.available).toHaveLength(0);
});

test("the first ready model always loads, even after models that are not ready", () => {
  expect(planLoad([m(1e6, "bezig"), m(500e6)], 1).load).toHaveLength(1);
});
