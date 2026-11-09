import { sourceKey, type ModelSource } from "../host/BimHost";

/** A selected element: its GlobalId within one model version. */
export type Selection = { bron: ModelSource; globalid: string };

export function selectionKey(s: Selection): string {
  return `${sourceKey(s.bron)}#${s.globalid}`;
}
