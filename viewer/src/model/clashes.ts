import type { Clash, ClashStatus } from "./bcf";

export const STATUSSEN: ClashStatus[] = ["nieuw", "actief", "opgelost", "genegeerd"];

/** Clashes per pair of classes (`IfcWall × IfcDuctSegment`), the largest group first, equal groups by name. */
export function groepeer(botsingen: Clash[]): { groep: string; botsingen: Clash[] }[] {
  const groepen = new Map<string, Clash[]>();
  for (const b of botsingen) groepen.set(b.groep, [...(groepen.get(b.groep) ?? []), b]);
  return [...groepen]
    .map(([groep, lijst]) => ({ groep, botsingen: lijst }))
    .sort((a, b) => b.botsingen.length - a.botsingen.length || a.groep.localeCompare(b.groep));
}

export function telStatussen(botsingen: Clash[]): Record<ClashStatus, number> {
  const tel = Object.fromEntries(STATUSSEN.map((s) => [s, 0])) as Record<ClashStatus, number>;
  for (const b of botsingen) tel[b.status] += 1;
  return tel;
}

/** Both elements of a clash, to mark in the view. */
export function elementenVan(botsing: Clash): { bestand: string; globalid: string }[] {
  return [botsing.element_a, botsing.element_b].map(({ bestand, globalid }) => ({ bestand, globalid }));
}
