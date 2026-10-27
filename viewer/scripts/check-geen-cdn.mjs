// Fails when the build refers to a CDN: the fragments worker and the WASM must come from the bundle itself.
import { readdirSync, readFileSync, statSync } from "node:fs";
import path from "node:path";

const FORBIDDEN = ["unpkg.com", "thatopen.github.io", "cdn.jsdelivr.net"];
const root = process.argv[2] ?? "dist";

function* files(dir) {
  for (const name of readdirSync(dir)) {
    const full = path.join(dir, name);
    if (statSync(full).isDirectory()) yield* files(full);
    else yield full;
  }
}

const hits = [];
for (const file of files(root)) {
  const text = readFileSync(file, "latin1");
  for (const host of FORBIDDEN) if (text.includes(host)) hits.push(`${path.relative(root, file)}: ${host}`);
}
if (hits.length) {
  console.error(`Verwijzingen naar een CDN in ${root}:\n  ${hits.join("\n  ")}`);
  process.exit(1);
}
console.log(`Geen verwijzingen naar een CDN in ${root}.`);
