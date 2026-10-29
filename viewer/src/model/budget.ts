import type { ModelInfo } from "../host/BimHost";

/** Estimated browser memory per byte of fragments (measured during the preliminary work). */
export const BYTES_PER_FRAGMENTS_BYTE = 18;

/** Default memory budget for loaded models: 2 GiB of estimated browser memory. */
export const DEFAULT_BUDGET = 2 * 1024 ** 3;

export function estimateBytes(m: ModelInfo): number {
  return BYTES_PER_FRAGMENTS_BYTE * m.delen.reduce((sum, deel) => sum + deel.bytes, 0);
}

/**
 * Which ready models to load at start, in the order given, within the budget. The first model that does not fit, and
 * every model after it, stays available to switch on; the first ready model is always loaded, even when it alone is
 * over the budget. Models that are not ready are in neither list.
 */
export function planLoad(models: ModelInfo[], budgetBytes: number): { load: ModelInfo[]; available: ModelInfo[] } {
  const load: ModelInfo[] = [];
  const available: ModelInfo[] = [];
  let used = 0;
  for (const model of models) {
    if (model.status !== "klaar") continue;
    const cost = estimateBytes(model);
    if (available.length === 0 && (load.length === 0 || used + cost <= budgetBytes)) {
      load.push(model);
      used += cost;
    } else {
      available.push(model);
    }
  }
  return { load, available };
}

/**
 * Models that became ready after the first plan (not in `seen`) and fit next to the models that are on, in order.
 * Models seen ready before are the user's to switch; a model that does not fit stays available to switch on.
 */
export function switchOnNewlyReady(
  models: ModelInfo[],
  on: Set<string>,
  seen: Set<string>,
  budgetBytes: number,
): ModelInfo[] {
  let used = models
    .filter((m) => m.status === "klaar" && on.has(m.bron.sleutel))
    .reduce((sum, m) => sum + estimateBytes(m), 0);
  const result: ModelInfo[] = [];
  for (const model of models) {
    if (model.status !== "klaar" || seen.has(model.bron.sleutel) || on.has(model.bron.sleutel)) continue;
    const cost = estimateBytes(model);
    if (used + cost > budgetBytes) continue;
    result.push(model);
    used += cost;
  }
  return result;
}
