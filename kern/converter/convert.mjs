// IFC converter run as a subprocess by openbim_kern.converter.
//   node convert.mjs clean <in.ifc> <out.ifc>    -> stdout: {"in_bytes","out_bytes","records_in","records_out",...}
//   node convert.mjs split <in.ifc> <n> <outdir> -> stdout: {"delen": ["deel-1.ifc", ...], ...}
//   node convert.mjs frag  <in.ifc> <out.frag>   -> stdout: {"in_bytes","out_bytes","sec"}
// Every report also has "max_rss", the peak memory of the process in bytes.
// On failure the exit code is 1 and the last stderr line is a short message for the user (Dutch where it is ours).
import { closeSync, mkdirSync, openSync, readSync, statSync, writeFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { clean } from "./clean.mjs";
import { split } from "./split.mjs";
import { StepError, assertComplete } from "./stepindex.mjs";

const here = path.dirname(fileURLToPath(import.meta.url));
const CHUNK = 1024 * 1024;

/** The report on stdout, with the peak memory of this process: the watchdog only samples it twice a second. */
function report(fields) {
  console.log(JSON.stringify({ ...fields, max_rss: process.resourceUsage().maxRSS * 1024 }));
}

// The watchdog (converter.py) reads the progress of a conversion from this file, as a fraction.
function progressWriter(file) {
  let last = -1;
  return (fraction) => {
    const percent = Math.floor(fraction * 100);
    if (!file || percent === last) return;
    last = percent;
    writeFileSync(file, String(fraction));
  };
}

async function frag(input, output) {
  const t0 = performance.now();
  assertComplete(input);
  // Loaded here only: cleaning and splitting do without fragments and three.js.
  const FRAGS = await import("@thatopen/fragments");
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
    bytes = await importer.process({
      readFromCallback: true,
      readCallback,
      raw: false,
      progressCallback: progressWriter(process.env.OPENBIM_VOORTGANG_BESTAND),
    });
  } finally {
    closeSync(fd);
  }
  writeFileSync(output, bytes);
  const sec = (performance.now() - t0) / 1000;
  report({ in_bytes: inBytes, out_bytes: bytes.byteLength, sec });
}

function fail(e) {
  if (e?.stack && !(e instanceof StepError)) console.error(e.stack);
  console.error(e instanceof Error ? e.message : String(e));
  process.exit(1);
}

process.on("uncaughtException", fail);
process.on("unhandledRejection", fail);

const [mode, ...args] = process.argv.slice(2);
try {
  if (mode === "frag" && args.length === 2) await frag(args[0], args[1]);
  else if (mode === "clean" && args.length === 2) report(clean(args[0], args[1]));
  else if (mode === "split" && args.length === 3) {
    mkdirSync(args[2], { recursive: true });
    report(split(args[0], Number.parseInt(args[1], 10), args[2]));
  } else throw new Error("usage: convert.mjs clean <in> <out> | split <in> <n> <outdir> | frag <in> <out>");
} catch (e) {
  fail(e);
}
process.exit(0);
