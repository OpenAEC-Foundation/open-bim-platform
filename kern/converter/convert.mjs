// IFC converter run as a subprocess by openbim_kern.converter.
//   node convert.mjs frag  <in.ifc> <out.frag>   -> stdout: {"in_bytes","out_bytes","sec"}
//   node convert.mjs split <in.ifc> <n> <outdir> -> stdout: {"delen": ["deel-1.ifc", ...]}
// On failure the exit code is 1 and the last stderr line is a short message for the user (Dutch where it is ours).
import {
  closeSync,
  createWriteStream,
  mkdirSync,
  openSync,
  readSync,
  renameSync,
  statSync,
  writeFileSync,
} from "node:fs";
import path from "node:path";
import { Writable } from "node:stream";
import { fileURLToPath } from "node:url";
import * as FRAGS from "@thatopen/fragments";
import * as WEBIFC from "web-ifc";
import { readLines } from "./lines.mjs";

const here = path.dirname(fileURLToPath(import.meta.url));
const CHUNK = 1024 * 1024;
const STEP_HEADER = "ISO-10303-21;";
const STEP_TRAILER = "END-ISO-10303-21;";
const TAIL_BYTES = 4096;

// web-ifc reads a cut-off file without complaint, so check that the STEP envelope is complete first.
function assertComplete(input) {
  const size = statSync(input).size;
  const fd = openSync(input, "r");
  try {
    const head = Buffer.alloc(Math.min(size, 64));
    readSync(fd, head, 0, head.length, 0);
    const tail = Buffer.alloc(Math.min(size, TAIL_BYTES));
    readSync(fd, tail, 0, tail.length, size - tail.length);
    const start = head.toString("latin1").replace(/^\xEF\xBB\xBF/, "").trimStart();
    if (!start.startsWith(STEP_HEADER)) {
      throw new Error(`geen IFC-bestand: het begint niet met ${STEP_HEADER}`);
    }
    if (!tail.toString("latin1").includes(STEP_TRAILER)) {
      throw new Error(`het bestand is onvolledig (${STEP_TRAILER} ontbreekt aan het eind)`);
    }
  } finally {
    closeSync(fd);
  }
}

async function frag(input, output) {
  const t0 = performance.now();
  assertComplete(input);
  const inBytes = statSync(input).size;
  const importer = new FRAGS.IfcImporter();
  importer.wasm = { path: path.join(here, "node_modules", "web-ifc") + path.sep, absolute: true };
  const fd = openSync(input, "r");
  const buf = new Uint8Array(CHUNK);
  const readCallback = (offset) => {
    const n = readSync(fd, buf, 0, CHUNK, offset);
    return buf.slice(0, n);
  };
  let bytes;
  try {
    bytes = await importer.process({ readFromCallback: true, readCallback, raw: false });
  } finally {
    closeSync(fd);
  }
  writeFileSync(output, bytes);
  const sec = (performance.now() - t0) / 1000;
  console.log(JSON.stringify({ in_bytes: inBytes, out_bytes: bytes.byteLength, sec }));
}

// IO over node:fs for the splitter: it reads lines without their line ending and writes text that already
// carries its own line endings.
const io = {
  async readableStream(p) {
    return readLines(p);
  },
  async writableStream(p) {
    return Writable.toWeb(createWriteStream(p, { encoding: "utf8" }));
  },
};

// The default type lists of the splitter know only part of the IFC4 and IFC4X3 types (not IfcDuctSegment, say). A
// type it does not know is copied into every part and loses its storey, so take every IfcElement subtype and every
// spatial structure type of every schema from web-ifc.
function splitterConfig() {
  const names = new Map(
    Object.entries(WEBIFC)
      .filter(([k, v]) => /^IFC[A-Z0-9]+$/.test(k) && typeof v === "number")
      .map(([k, v]) => [v, k]),
  );
  const subtypes = (code) =>
    Object.values(WEBIFC.InheritanceDef).flatMap((def) => (def[code] ?? []).map((c) => names.get(c)).filter(Boolean));
  const spatial = new Set([...FRAGS.SPATIAL_TYPES, ...subtypes(WEBIFC.IFCSPATIALSTRUCTUREELEMENT)]);
  spatial.delete("IFCSPACE"); // spaces are distributed like elements, as in the defaults
  const elements = new Set([...FRAGS.ELEMENT_TYPES, ...subtypes(WEBIFC.IFCELEMENT)]);
  for (const t of spatial) elements.delete(t);
  return { elementTypes: [...elements], spatialTypes: [...spatial] };
}

async function split(input, n, outdir) {
  const groups = Number.parseInt(n, 10);
  assertComplete(input);
  mkdirSync(outdir, { recursive: true });
  const tmp = (id) => path.join(outdir, `.groep-${id}.ifc`);
  const splitter = new FRAGS.IfcSplitter(io, splitterConfig());
  const written = await splitter.split(input, groups, tmp);
  const ids = [...written.keys()].sort((a, b) => a - b);
  const delen = ids.map((id, i) => {
    const name = `deel-${i + 1}.ifc`;
    renameSync(written.get(id).path, path.join(outdir, name));
    return name;
  });
  console.log(JSON.stringify({ delen }));
}

function fail(e) {
  if (e?.stack) console.error(e.stack);
  console.error(e instanceof Error ? e.message : String(e));
  process.exit(1);
}

process.on("uncaughtException", fail);
process.on("unhandledRejection", fail);

const [mode, ...args] = process.argv.slice(2);
try {
  if (mode === "frag" && args.length === 2) await frag(args[0], args[1]);
  else if (mode === "split" && args.length === 3) await split(args[0], args[1], args[2]);
  else throw new Error("usage: convert.mjs frag <in> <out> | split <in> <n> <outdir>");
} catch (e) {
  fail(e);
}
process.exit(0);
