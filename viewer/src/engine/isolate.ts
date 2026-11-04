/** The camera never looks from further than this around a clash, however large the elements are (metres). */
export const MAX_RADIUS = 10;
/** ...and never from closer than this. */
export const MIN_RADIUS = 0.5;

/** Radius of the view around two elements: half the diagonal of their joint box, kept between the limits. */
export function isolateRadius(size: [number, number, number] | null): number {
  if (!size) return MIN_RADIUS;
  const half = Math.hypot(size[0], size[1], size[2]) / 2;
  if (!Number.isFinite(half)) return MIN_RADIUS;
  return Math.min(MAX_RADIUS, Math.max(MIN_RADIUS, half));
}
