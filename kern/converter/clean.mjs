// Lossless cleaning of an IFC file: identical records become one, records nothing refers to are left out.
//
// Two records are identical when they have the same type and the same text apart from their id and white space, and
// refer to the same (merged) records; that is decided bottom-up, points and values first, then what refers to them.
// What keeps its identity: everything with a GlobalId, placements, representations and contexts (they belong to
// their product), records the schema allows only one referrer for (a styled item per representation item), and the
// records an annotation such as a style or a layer points at (merging those would carry the style to every user).
// Only geometry, properties, quantities, styles and units are removed when nothing refers to them.
//
// The ids of the records that stay are kept, so the cleaned file reads like the original. The record that replaces
// duplicates is the first of them in the file, and each duplicate is checked against it again while the file is
// written: byte for byte when both are in the read buffer, else with a second, independent 64-bit hash (128 bits with
// the first). A difference stops the cleaning.
import {
  DANGLING,
  IN_LIST,
  Output,
  StepError,
  Stack,
  StepIndex,
  T_NOMERGE,
  T_REMOVABLE,
  T_ROOT,
  assertComplete,
  recordEnd,
  recordId,
  scanFile,
  writeRecord,
} from "./stepindex.mjs";

const F_REACH = 1; // reachable from a record that stands on its own
const F_REF = 2; // referred to by a reachable record
const F_OWNED = 4; // referred to by a reachable record that is not an annotation
const F_PIN = 8; // keeps its identity
const F_DONE = 16; // its representative is known
const F_HASDUP = 32; // replaces duplicates
const MAX_ROUNDS = 8;

export function clean(input, output) {
  const t0 = performance.now();
  assertComplete(input);
  const index = StepIndex.read(input, { hashes: true });
  const { n, refs, refStart, flags } = index;
  const tflags = (i) => index.typeFlags[index.types[i]];

  // 1. Reachable from what stands on its own: everything but geometry, properties and the like.
  const stack = new Stack();
  for (let i = 0; i < n; i++) {
    if (!(tflags(i) & T_REMOVABLE)) {
      flags[i] |= F_REACH;
      stack.push(i);
    }
  }
  while (stack.size) {
    const i = stack.pop();
    for (let k = refStart[i]; k < refStart[i + 1]; k++) {
      const t = refs[k];
      if (t !== DANGLING && !(flags[t] & F_REACH)) {
        flags[t] |= F_REACH;
        stack.push(t);
      }
    }
  }

  // 2. What must keep its identity.
  for (let i = 0; i < n; i++) {
    if (!(flags[i] & F_REACH)) continue;
    for (let k = refStart[i]; k < refStart[i + 1]; k++) if (refs[k] !== DANGLING) flags[refs[k]] |= F_REF;
  }
  // An annotation stands on its own without a GlobalId and points at what it annotates (a styled item, a layer, a
  // material representation, an external reference). Records also used by others are its targets.
  const annotation = (i) => (flags[i] & (F_REACH | F_REF)) === F_REACH && !(tflags(i) & T_ROOT);
  for (let i = 0; i < n; i++) {
    if (!(flags[i] & F_REACH) || annotation(i)) continue;
    for (let k = refStart[i]; k < refStart[i + 1]; k++) if (refs[k] !== DANGLING) flags[refs[k]] |= F_OWNED;
  }
  for (let i = 0; i < n; i++) {
    if (!annotation(i)) continue;
    for (let k = refStart[i]; k < refStart[i + 1]; k++) {
      const t = refs[k];
      if (t !== DANGLING && flags[t] & F_OWNED) flags[t] |= F_PIN;
    }
  }
  for (const t of index.pinned) if (t !== DANGLING) flags[t] |= F_PIN;
  for (let i = 0; i < n; i++) {
    if (tflags(i) & T_NOMERGE) flags[i] |= F_PIN;
    for (let k = refStart[i]; k < refStart[i + 1]; k++) if (refs[k] === DANGLING) flags[i] |= F_PIN;
  }

  // 3. Merge bottom-up; a record that would appear twice in a SET (or LIST OF UNIQUE) keeps its identity, and then
  // the merging starts over.
  const rep = new Int32Array(n);
  const table = new Int32Array(2 * n + 16);
  let rounds = 0;
  let passes = 0;
  for (;;) {
    rounds++;
    passes += merge(index, rep, table);
    if (!pinConflicts(index, rep, table)) break;
    if (rounds === MAX_ROUNDS) throw new StepError("het samenvoegen kwam na herhaalde pogingen niet tot rust");
  }
  const peakBytes = index.bytesUsed(rep.byteLength + table.byteLength + stack.bytes);
  firstAsRepresentative(index, rep, table);

  // 4. Write what stays, with every reference to its representative; check every duplicate against it.
  const kept = (i) => flags[i] & F_REACH && rep[i] === i;
  const out = new Output(output);
  out.write(index.header, 0, index.header.length);
  out.byte(10);
  const check = new Checker(index, table);
  const counts = { merged: new Map(), orphans: new Map() };
  let slot = 0;
  let written = 0;
  scanFile(input, (buf, s, limit, offset) => {
    const e = recordEnd(buf, s, limit);
    if (e < 0) return -1;
    const i = slot++;
    if (recordId(buf, s) !== index.ids[i]) throw new StepError("het bestand veranderde tijdens het opschonen");
    if (kept(i)) {
      if (flags[i] & F_HASDUP) check.remember(buf, s, i);
      const base = refStart[i];
      writeRecord(buf, s, out, (k) => {
        const t = refs[base + k];
        return t === DANGLING ? -1 : index.ids[rep[t]];
      });
      out.byte(10);
      written++;
    } else if (flags[i] & F_REACH) {
      check.same(buf, s, offset, rep[i]);
      count(counts.merged, index.typeNames[index.types[i]]);
    } else {
      count(counts.orphans, index.typeNames[index.types[i]]);
    }
    return e;
  });
  out.write(index.footer, 0, index.footer.length);
  out.close();

  const merged = sum(counts.merged);
  return {
    in_bytes: index.dataEnd + index.footer.length,
    out_bytes: out.bytes,
    records_in: n,
    records_out: written,
    merged,
    orphans: sum(counts.orphans),
    merged_by_type: top(counts.merged),
    orphans_by_type: top(counts.orphans),
    rounds,
    passes,
    index_bytes: peakBytes,
    sec: (performance.now() - t0) / 1000,
  };
}

/** One round of merging; returns the number of passes over the records. */
function merge(index, rep, table) {
  const { n, refs, refStart, flags, types, h1, h2 } = index;
  table.fill(0);
  let pending = 0;
  for (let i = 0; i < n; i++) {
    rep[i] = i;
    if (flags[i] & F_REACH && !(flags[i] & F_PIN)) {
      flags[i] &= ~F_DONE;
      pending++;
    } else {
      flags[i] |= F_DONE;
    }
  }
  const cap = table.length;
  const same = (a, b) => {
    if (types[a] !== types[b] || h1[a] !== h1[b] || h2[a] !== h2[b]) return false;
    const ka = refStart[a];
    const kb = refStart[b];
    const len = refStart[a + 1] - ka;
    if (refStart[b + 1] - kb !== len) return false;
    for (let k = 0; k < len; k++) if (rep[refs[ka + k]] !== rep[refs[kb + k]]) return false;
    return true;
  };
  // Records are mostly written after what they refer to, sometimes before: alternate the direction until done.
  let passes = 0;
  while (pending > 0) {
    passes++;
    const forward = passes % 2 === 1;
    let progress = 0;
    for (let j = 0; j < n; j++) {
      const i = forward ? j : n - 1 - j;
      if (flags[i] & F_DONE) continue;
      let ready = true;
      let h = h1[i] ^ Math.imul(h2[i], 0x9e3779b1);
      for (let k = refStart[i]; k < refStart[i + 1]; k++) {
        const t = refs[k];
        if (!(flags[t] & F_DONE)) {
          ready = false;
          break;
        }
        h = Math.imul(h ^ rep[t], 0x01000193);
      }
      if (!ready) continue;
      h ^= h >>> 16;
      h = Math.imul(h, 0x85ebca6b);
      h ^= h >>> 13;
      let at = Math.floor(((h >>> 0) * cap) / 4294967296);
      for (;;) {
        const c = table[at];
        if (c === 0) {
          table[at] = i + 1;
          break;
        }
        if (same(c - 1, i)) {
          rep[i] = c - 1;
          break;
        }
        at = at + 1 === cap ? 0 : at + 1;
      }
      flags[i] |= F_DONE;
      progress++;
      pending--;
    }
    if (progress === 0) {
      // A cycle: what is left keeps its identity.
      for (let i = 0; i < n; i++) flags[i] |= F_DONE;
      break;
    }
  }
  return passes;
}

/**
 * Pin the records that the merging put twice into one SET or LIST OF UNIQUE of a record that stays (the points of an
 * IfcPolyLoop, the properties of a property set). Returns whether there were any; `table` serves as scratch space.
 */
function pinConflicts(index, rep, table) {
  const { n, refs, refStart, refAttr, flags, types } = index;
  const seen = table.subarray(0, n); // per representative: the group it was last seen in
  const first = table.subarray(n, 2 * n); // and the record it stood for
  seen.fill(0);
  let group = 0;
  let found = false;
  for (let i = 0; i < n; i++) {
    const unique = index.uniqueAttrs[types[i]];
    if (unique === null || !(flags[i] & F_REACH) || rep[i] !== i) continue;
    let k = refStart[i];
    const end = refStart[i + 1];
    while (k < end) {
      const a = refAttr[k];
      group++;
      const check = a & IN_LIST && unique[a & ~IN_LIST] === 1;
      for (; k < end && refAttr[k] === a; k++) {
        if (!check) continue;
        const t = refs[k];
        if (t === DANGLING) continue;
        const r = rep[t];
        if (seen[r] === group && first[r] !== t) {
          flags[t] |= F_PIN;
          found = true;
        } else if (seen[r] !== group) {
          seen[r] = group;
          first[r] = t;
        }
      }
    }
  }
  return found;
}

/**
 * Make the first record of every set of duplicates its representative, so it is written before the duplicates are
 * checked against it, and mark it. `table` serves as scratch space.
 */
function firstAsRepresentative(index, rep, table) {
  const { n, flags } = index;
  const first = table.subarray(0, n);
  for (let i = 0; i < n; i++) first[i] = i;
  for (let i = 0; i < n; i++) if (i < first[rep[i]]) first[rep[i]] = i;
  for (let i = 0; i < n; i++) rep[i] = first[rep[i]];
  for (let i = 0; i < n; i++) if (rep[i] !== i) flags[rep[i]] |= F_HASDUP;
}

/** Checks each duplicate against its representative, which was written before it. */
class Checker {
  constructor(index, table) {
    this.index = index;
    this.hashes = table; // per representative: two 32-bit hashes, at [r] and [n + r]
    this.a = Buffer.allocUnsafe(64 * 1024);
    this.b = Buffer.allocUnsafe(64 * 1024);
  }

  masked(buf, s, which) {
    const e = recordEnd(buf, s, buf.length);
    if (this[which].length < e - s) this[which] = Buffer.allocUnsafe(e - s);
    return StepIndex.masked(buf, s, this[which]);
  }

  remember(buf, s, r) {
    const m = this.masked(buf, s, "a");
    const [x, y] = verifyHash(this.a, m);
    this.hashes[r] = x;
    this.hashes[this.index.n + r] = y;
  }

  same(buf, s, offset, r) {
    const { offsets, n, ids } = this.index;
    const la = this.masked(buf, s, "a");
    const bufStart = offset - s; // file offset of buf[0]
    let equal;
    if (offsets[r] >= bufStart) {
      const lb = this.masked(buf, offsets[r] - bufStart, "b");
      equal = la === lb && this.a.compare(this.b, 0, lb, 0, la) === 0;
    } else {
      const [x, y] = verifyHash(this.a, la);
      equal = this.hashes[r] === x && this.hashes[n + r] === y;
    }
    if (!equal) {
      throw new StepError(`samenvoegen afgebroken: #${recordId(buf, s)} en #${ids[r]} bleken niet gelijk`);
    }
  }
}

/** Two 32-bit hashes, independent of those of the index (other seeds and multipliers). */
function verifyHash(bytes, m) {
  let x = 0x2545f491 ^ m;
  let y = 0x6a09e667 ^ Math.imul(m, 0x27d4eb2f);
  for (let k = 0; k < m; k++) {
    const c = bytes[k];
    x = Math.imul(x ^ c, 0x2c1b3c6d) + 0x297a2d39;
    x ^= x >>> 12;
    y = Math.imul(y + c, 0x165667b1);
    y ^= y >>> 15;
  }
  return [Math.imul(x ^ (x >>> 16), 0x7feb352d), Math.imul(y ^ (y >>> 13), 0x846ca68b) ^ (y >>> 16)];
}

function count(map, key) {
  map.set(key, (map.get(key) ?? 0) + 1);
}

function sum(map) {
  let total = 0;
  for (const v of map.values()) total += v;
  return total;
}

function top(map, n = 15) {
  return Object.fromEntries([...map].sort((a, b) => b[1] - a[1]).slice(0, n));
}
