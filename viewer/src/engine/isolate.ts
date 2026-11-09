/** The camera never looks from further than this around a clash, however large the elements are (metres). */
export const MAX_RADIUS = 10;
/** ...and never from closer than this. */
export const MIN_RADIUS = 0.5;

/** The size of an element's box. */
export type Size = [number, number, number];

/** What an isolation found in the view, per side of the clash. An empty box counts as not found. */
export type IsolateResult = { a: boolean; b: boolean };

/**
 * Radius of the view around a clash: half the diagonal of the smallest element that has a size, kept between the limits.
 * A small element against a large one (a baluster against a storey's ceiling finish) stays in view that way; the joint box
 * would zoom out to the large one. An element without a size does not count.
 */
export function isolateRadius(sizes: (Size | null)[]): number {
  const halves = sizes.flatMap((size) => (size ? [Math.hypot(size[0], size[1], size[2]) / 2] : [])).filter((half) => Number.isFinite(half) && half > 0);
  if (halves.length === 0) return MIN_RADIUS;
  return Math.min(MAX_RADIUS, Math.max(MIN_RADIUS, Math.min(...halves)));
}
