import { HostError } from "../host/BimHost";

const UNITS: [string, number][] = [
  ["GB", 1024 ** 3],
  ["MB", 1024 ** 2],
  ["kB", 1024],
];

export function formatBytes(bytes: number, language: string): string {
  const number = new Intl.NumberFormat(language, { maximumFractionDigits: 1 });
  for (const [unit, size] of UNITS) if (bytes >= size) return `${number.format(bytes / size)} ${unit}`;
  return `${number.format(bytes)} B`;
}

/** A property value from the index as text: numbers in the reader's language, lists joined. */
export function formatValue(value: unknown, language: string, yes: string, no: string): string {
  if (value === null || value === undefined) return "";
  if (typeof value === "boolean") return value ? yes : no;
  if (typeof value === "number") return new Intl.NumberFormat(language, { maximumFractionDigits: 3 }).format(value);
  if (Array.isArray(value)) return value.map((v) => formatValue(v, language, yes, no)).join(", ");
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

/** The host has no model folder yet (the workspace asks for one first): a state to show, not an error. */
export function isNoFolder(error: unknown): boolean {
  return error instanceof HostError && error.fout?.error_code === "geen_map";
}

/** A readable message for an error of the host or the engine. */
export function describe(error: unknown): string {
  if (error instanceof HostError) return error.fout ? `${error.fout.melding} ${error.fout.remedie}` : error.message;
  return error instanceof Error ? error.message : String(error);
}
