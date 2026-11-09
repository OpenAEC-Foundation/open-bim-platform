import type { BimHost, ElementProperties, ModelSource } from "../host/BimHost";

/**
 * The names of an element's storey and type, looked up in the same index in one request. An id the index does not
 * know (for instance a type in an index from before types were indexed) stays as it is; a storey has no storey row.
 */
export async function relatedNames(
  host: BimHost,
  bron: ModelSource,
  element: ElementProperties,
  globalid: string,
): Promise<{ storey: string | null; type: string | null }> {
  const storeyId = element.verdieping && element.verdieping !== globalid ? element.verdieping : null;
  const ids = [storeyId, element.type].filter((id): id is string => Boolean(id));
  const found = ids.length ? await host.eigenschappen(bron, ids) : {};
  const name = (id: string | null) => (id ? (found[id]?.naam ?? id) : null);
  return { storey: name(storeyId), type: name(element.type) };
}
