// Split an IFC file into parts of about equal size, on the STEP index.
//
// Every product except the spatial structure (elements, spaces, ports, grids, annotations) goes into exactly one part,
// together with what belongs to it: its openings and fillings, its aggregated and nested parts, its ports. The parts
// are balanced by the bytes their products take. Every part gets the spatial structure and everything a product in it
// refers to. A relationship goes into each part with products it relates, its lists cut down to those products; an
// annotation (a styled item, a layer) goes where what it annotates went, cut down the same way.
import path from "node:path";
import {
  DANGLING,
  IN_LIST,
  Output,
  StepError,
  Stack,
  StepIndex,
  T_ELEMENT,
  T_OBJDEF,
  T_REL,
  T_ROOT,
  T_SPATIAL,
  assertComplete,
  recordEnd,
  recordId,
  scanFile,
  writeRecord,
} from "./stepindex.mjs";

// Relationships that keep their products together in one part, when a product is on the relating side.
const CLUSTERS = new Set([
  "IFCRELVOIDSELEMENT",
  "IFCRELFILLSELEMENT",
  "IFCRELAGGREGATES",
  "IFCRELNESTS",
  "IFCRELCONNECTSPORTTOELEMENT",
  "IFCRELPROJECTSELEMENT",
  "IFCRELADHERESTOELEMENT",
]);
const K_NONE = 0;
const K_ELEMENTS = 1; // a relationship with products: goes where its products go
const K_OBJECTS = 2; // a relationship with types, groups or the spatial structure only: goes where those are
const K_ROOTS = 3; // a relationship with other rooted records only (property sets): goes where those are
const K_ANNOTATION = 4; // stands alone, points at records others use: goes where those are
const F_REF = 1;
const F_OWNED = 2;

export function split(input, groups, outdir) {
  const t0 = performance.now();
  if (!Number.isInteger(groups) || groups < 1) throw new StepError("het aantal delen moet minstens 1 zijn");
  assertComplete(input);
  const index = StepIndex.read(input);
  const { n, refs, refStart, refAttr, types } = index;
  const tflags = index.typeFlags;
  const tf = (i) => tflags[types[i]];
  const isElement = (i) => (tflags[types[i]] & T_ELEMENT) !== 0;

  // What refers to what, for the annotations.
  const flags = index.flags;
  for (let k = 0; k < index.nrefs; k++) if (refs[k] !== DANGLING) flags[refs[k]] |= F_REF;
  const annotation = (i) => !(flags[i] & F_REF) && !(tf(i) & T_ROOT);
  for (let i = 0; i < n; i++) {
    if (annotation(i)) continue;
    for (let k = refStart[i]; k < refStart[i + 1]; k++) if (refs[k] !== DANGLING) flags[refs[k]] |= F_OWNED;
  }
  const kinds = new Uint8Array(n);
  for (let i = 0; i < n; i++) kinds[i] = kindOf(index, i, annotation(i));

  // Products that stay together, by union-find.
  const uf = new Int32Array(n);
  for (let i = 0; i < n; i++) uf[i] = i;
  const find = (i) => {
    while (uf[i] !== i) {
      uf[i] = uf[uf[i]];
      i = uf[i];
    }
    return i;
  };
  const clusterTypes = new Set(index.typeNames.flatMap((name, t) => (CLUSTERS.has(name) ? [t] : [])));
  for (let i = 0; i < n; i++) {
    if (!clusterTypes.has(types[i])) continue;
    let relating = false;
    for (let k = refStart[i]; k < refStart[i + 1]; k++) {
      if (refs[k] !== DANGLING && isElement(refs[k]) && !(refAttr[k] & IN_LIST)) relating = true;
    }
    if (!relating) continue;
    let first = -1;
    for (let k = refStart[i]; k < refStart[i + 1]; k++) {
      const t = refs[k];
      if (t === DANGLING || !isElement(t)) continue;
      if (first < 0) first = find(t);
      else uf[find(t)] = first;
    }
  }

  // The spatial structure and what it refers to: in every part.
  const shared = bitset(n);
  const stack = new Stack();
  for (let i = 0; i < n; i++) {
    if (tf(i) & T_SPATIAL) {
      set(shared, i);
      stack.push(i);
    }
  }
  closure(index, shared, stack, isElement);

  // Weight of a product: the bytes of the records it is the first to refer to.
  let elementCount = 0;
  for (let i = 0; i < n; i++) if (isElement(i)) elementCount++;
  const elements = new Int32Array(elementCount);
  for (let i = 0, j = 0; i < n; i++) if (isElement(i)) elements[j++] = i;
  const weights = new Float64Array(elementCount);
  const seen = Uint8Array.from(shared);
  const length = (i) => (i + 1 < n ? index.offsets[i + 1] : index.dataEnd) - index.offsets[i];
  for (let j = 0; j < elementCount; j++) {
    const e = elements[j];
    let w = length(e);
    stack.push(e);
    while (stack.size) {
      const s = stack.pop();
      for (let k = refStart[s]; k < refStart[s + 1]; k++) {
        const t = refs[k];
        if (t === DANGLING || has(seen, t) || isElement(t)) continue;
        set(seen, t);
        w += length(t);
        stack.push(t);
      }
    }
    weights[j] = w;
  }

  // Clusters to groups, heaviest first, each to the lightest group.
  const roots = uf; // reused: root slot -> cluster
  const rootOf = new Int32Array(elementCount);
  for (let j = 0; j < elementCount; j++) rootOf[j] = find(elements[j]);
  roots.fill(-1);
  let clusterCount = 0;
  for (let j = 0; j < elementCount; j++) {
    if (roots[rootOf[j]] < 0) roots[rootOf[j]] = clusterCount++;
    rootOf[j] = roots[rootOf[j]];
  }
  const clusterOf = rootOf;
  const clusterWeight = new Float64Array(clusterCount);
  for (let j = 0; j < elementCount; j++) clusterWeight[clusterOf[j]] += weights[j];
  const order = Uint32Array.from({ length: clusterCount }, (_, c) => c).sort(
    (a, b) => clusterWeight[b] - clusterWeight[a] || a - b,
  );
  const groupOf = new Int32Array(clusterCount);
  const load = new Float64Array(groups);
  for (const c of order) {
    let g = 0;
    for (let h = 1; h < groups; h++) if (load[h] < load[g]) g = h;
    groupOf[c] = g;
    load[g] += clusterWeight[c];
  }

  // The records of each part.
  const used = [...new Set(Array.from(clusterOf, (c) => groupOf[c]))].sort((a, b) => a - b);
  if (used.length === 0) throw new StepError("het model heeft geen elementen om te verdelen");
  const parts = used.map(() => Uint8Array.from(shared));
  const partOfGroup = new Int32Array(groups).fill(-1);
  used.forEach((g, p) => {
    partOfGroup[g] = p;
  });
  for (let j = 0; j < elementCount; j++) set(parts[partOfGroup[groupOf[clusterOf[j]]]], elements[j]);
  let candidateCount = 0;
  for (let i = 0; i < n; i++) if (kinds[i] !== K_NONE) candidateCount++;
  const candidates = new Int32Array(candidateCount);
  for (let i = 0, j = 0; i < n; i++) if (kinds[i] !== K_NONE) candidates[j++] = i;
  for (const members of parts) {
    for (let j = 0; j < elementCount; j++) if (has(members, elements[j])) stack.push(elements[j]);
    closure(index, members, stack, isElement);
    for (let added = true; added; ) {
      added = false;
      for (const c of candidates) {
        if (!has(members, c) && include(index, kinds[c], c, members, flags, stack)) {
          set(members, c);
          added = true;
        }
      }
      closure(index, members, stack, isElement);
    }
  }
  const indexBytes = index.bytesUsed(
    kinds.byteLength +
      uf.byteLength +
      shared.byteLength * (2 + parts.length) +
      elements.byteLength * 2 +
      weights.byteLength +
      candidates.byteLength +
      stack.bytes,
  );

  // One pass over the file writes all parts.
  const delen = parts.map((_, p) => `deel-${p + 1}.ifc`);
  const outs = delen.map((name) => new Output(path.join(outdir, name)));
  for (const out of outs) {
    out.write(index.header, 0, index.header.length);
    out.byte(10);
  }
  let slot = 0;
  scanFile(input, (buf, s, limit) => {
    const e = recordEnd(buf, s, limit);
    if (e < 0) return -1;
    const i = slot++;
    if (recordId(buf, s) !== index.ids[i]) throw new StepError("het bestand veranderde tijdens het splitsen");
    const kind = kinds[i];
    for (let p = 0; p < parts.length; p++) {
      const members = parts[p];
      if (!has(members, i)) continue;
      const out = outs[p];
      if (kind === K_NONE) {
        out.write(buf, s, e);
      } else {
        const base = refStart[i];
        writeRecord(buf, s, out, (k) => {
          const t = refs[base + k];
          if (t === DANGLING || !(refAttr[base + k] & IN_LIST) || has(members, t)) return -1;
          return filtered(index, kind, t, flags) ? -2 : -1;
        });
      }
      out.byte(10);
    }
    return e;
  });
  for (const out of outs) {
    out.write(index.footer, 0, index.footer.length);
    out.close();
  }
  return { delen, records: n, index_bytes: indexBytes, sec: (performance.now() - t0) / 1000 };
}

function kindOf(index, i, annotation) {
  const { refs, refStart, flags } = index;
  const tflags = index.typeFlags;
  const types = index.types;
  if (tflags[types[i]] & T_REL) {
    let kind = K_NONE;
    for (let k = refStart[i]; k < refStart[i + 1]; k++) {
      const t = refs[k];
      if (t === DANGLING) continue;
      const f = tflags[types[t]];
      if (f & T_ELEMENT) return K_ELEMENTS;
      if (f & T_OBJDEF) kind = K_OBJECTS;
      else if (f & T_ROOT && kind === K_NONE) kind = K_ROOTS;
    }
    return kind;
  }
  if (annotation) {
    for (let k = refStart[i]; k < refStart[i + 1]; k++) {
      if (refs[k] !== DANGLING && flags[refs[k]] & F_OWNED) return K_ANNOTATION;
    }
  }
  return K_NONE;
}

/** Whether reference target `t` of a record of `kind` is one its lists are cut down to. */
function filtered(index, kind, t, flags) {
  const f = index.typeFlags[index.types[t]];
  if (kind === K_ELEMENTS) return (f & T_ELEMENT) !== 0;
  if (kind === K_OBJECTS) return (f & T_OBJDEF) !== 0;
  if (kind === K_ROOTS) return (f & T_ROOT) !== 0;
  return (flags[t] & F_OWNED) !== 0;
}

/**
 * Whether relationship or annotation `c` goes into the part with `members`; if so, push what it brings along. It needs
 * at least one of its targets in the part; a product or annotated record outside the part may only be left out of a
 * list, and no list of targets may end up empty.
 */
function include(index, kind, c, members, flags, stack) {
  const { refs, refStart, refAttr } = index;
  const singlesInPart = kind === K_ELEMENTS || kind === K_ANNOTATION;
  const end = refStart[c + 1];
  let any = false;
  for (let k = refStart[c]; k < end; ) {
    const a = refAttr[k];
    let targets = 0;
    let kept = 0;
    for (; k < end && refAttr[k] === a; k++) {
      const t = refs[k];
      if (t === DANGLING || !filtered(index, kind, t, flags)) {
        kept++;
        continue;
      }
      targets++;
      if (has(members, t)) {
        any = true;
        kept++;
      } else if (!(a & IN_LIST)) {
        if (singlesInPart) return false;
        kept++;
      }
    }
    if (a & IN_LIST && targets > 0 && kept === 0) return false;
  }
  if (!any) return false;
  for (let k = refStart[c]; k < end; k++) {
    const t = refs[k];
    if (t === DANGLING || has(members, t)) continue;
    if (refAttr[k] & IN_LIST && filtered(index, kind, t, flags)) continue;
    stack.push(t);
  }
  return true;
}

/** Add to `members` everything the records on the stack refer to, without entering products of other parts. */
function closure(index, members, stack, isElement) {
  const { refs, refStart } = index;
  while (stack.size) {
    const s = stack.pop();
    if (!has(members, s)) {
      if (isElement(s)) continue;
      set(members, s);
    }
    for (let k = refStart[s]; k < refStart[s + 1]; k++) {
      const t = refs[k];
      if (t === DANGLING || has(members, t) || isElement(t)) continue;
      set(members, t);
      stack.push(t);
    }
  }
}

const bitset = (n) => new Uint8Array((n >>> 3) + 1);
const has = (bits, i) => (bits[i >>> 3] & (1 << (i & 7))) !== 0;
const set = (bits, i) => {
  bits[i >>> 3] |= 1 << (i & 7);
};
