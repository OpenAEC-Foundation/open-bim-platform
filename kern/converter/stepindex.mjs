// The STEP index of an IFC file: id, type, position and references of every record in typed arrays, read straight from
// the bytes of the file in chunks. Cleaning and splitting share it. An object or a string per record costs hundreds of
// bytes (the splitter of fragments kept ~320 B per line); here a record costs a few dozen.
import { closeSync, fstatSync, openSync, readFileSync, readSync, writeSync } from "node:fs";
import * as WEBIFC from "web-ifc";

const CHUNK = 4 * 1024 * 1024;
const STEP_HEADER = "ISO-10303-21;";
const STEP_TRAILER = "END-ISO-10303-21;";
const TAIL_BYTES = 4096;
const MAX_ID = 0xffffffff;
/** A reference to an id that has no record. */
export const DANGLING = 0xffffffff;
/** Bit of the attribute byte of a reference: it sits inside a list, not directly in the attribute. */
export const IN_LIST = 0x80;

const HASH = 35; // #
const QUOTE = 39; // '
const LPAREN = 40;
const RPAREN = 41;
const STAR = 42;
const COMMA = 44;
const SLASH = 47;
const SEMI = 59;
const EQ = 61;

const isSpace = (c) => c === 32 || c === 10 || c === 13 || c === 9;
const isDigit = (c) => c >= 48 && c <= 57;
const isIdent = (c) => (c >= 65 && c <= 90) || (c >= 97 && c <= 122) || isDigit(c) || c === 95;

// Type flags.
export const T_ROOT = 1; // IfcRoot: carries a GlobalId
export const T_REL = 2; // IfcRelationship
export const T_OBJDEF = 4; // IfcObjectDefinition: objects, types, spatial structure
export const T_ELEMENT = 8; // a product placed in exactly one part when splitting
export const T_SPATIAL = 16; // spatial structure, in every part
export const T_REMOVABLE = 32; // means nothing unless something refers to it
export const T_NOMERGE = 64; // keeps its identity even when an identical record exists
export const T_COMPLEX = 128; // a complex instance #n=(A(...)B(...))

// Records that mean nothing on their own: geometry, profiles, properties, quantities, styles and units. Only these
// are removed when nothing refers to them; whatever else stands alone (an owner history, a styled item) stays.
const REMOVABLE = [
  "IFCGEOMETRICREPRESENTATIONITEM",
  "IFCTOPOLOGICALREPRESENTATIONITEM",
  "IFCMAPPEDITEM",
  "IFCREPRESENTATIONMAP",
  "IFCSHAPEMODEL",
  "IFCPRODUCTDEFINITIONSHAPE",
  "IFCOBJECTPLACEMENT",
  "IFCPROFILEDEF",
  "IFCPROPERTY",
  "IFCPROPERTYENUMERATION",
  "IFCPHYSICALQUANTITY",
  "IFCPRESENTATIONSTYLE",
  "IFCPRESENTATIONSTYLEASSIGNMENT",
  "IFCCOLOURSPECIFICATION",
  "IFCCOLOURRGBLIST",
  "IFCPREDEFINEDITEM",
  "IFCCURVESTYLEFONT",
  "IFCCURVESTYLEFONTPATTERN",
  "IFCCURVESTYLEFONTANDSCALING",
  "IFCSURFACESTYLESHADING",
  "IFCSURFACESTYLELIGHTING",
  "IFCSURFACESTYLEREFRACTION",
  "IFCSURFACESTYLEWITHTEXTURES",
  "IFCTEXTSTYLEFORDEFINEDFONT",
  "IFCTEXTSTYLETEXTMODEL",
  "IFCNAMEDUNIT",
  "IFCDERIVEDUNIT",
  "IFCDERIVEDUNITELEMENT",
  "IFCDIMENSIONALEXPONENTS",
  "IFCMEASUREWITHUNIT",
];
// Records that keep their identity: a placement, representation or context belongs to its product or project, and
// some schemas allow only one owner for them.
const NOMERGE = [
  "IFCROOT",
  "IFCREPRESENTATIONCONTEXT",
  "IFCOBJECTPLACEMENT",
  "IFCPRODUCTREPRESENTATION",
  "IFCREPRESENTATION",
];

const SCHEMA_TABLE = JSON.parse(readFileSync(new URL("./schema.json", import.meta.url), "utf8")).schemas;

let typeTables;

/** Every IFC type name of web-ifc with its descendants over all schemas: `name -> Set of names`, self included. */
function inheritance() {
  if (typeTables) return typeTables;
  const names = new Map(
    Object.entries(WEBIFC)
      .filter(([k, v]) => /^IFC[A-Z0-9]+$/.test(k) && typeof v === "number")
      .map(([k, v]) => [v, k]),
  );
  const below = (name) => {
    const code = WEBIFC[name];
    const found = new Set([name]);
    for (const def of Object.values(WEBIFC.InheritanceDef)) {
      for (const c of def[code] ?? []) if (names.has(c)) found.add(names.get(c));
    }
    return found;
  };
  const union = (list) => new Set(list.flatMap((n) => [...below(n)]));
  // As in the splitter of fragments: the spatial structure is shared, spaces are distributed like elements. Every
  // other product (elements, ports, grids, annotations, spatial zones) goes into exactly one part.
  const spatial = union(["IFCPROJECT", "IFCSPATIALSTRUCTUREELEMENT"]);
  spatial.delete("IFCSPACE");
  const elements = union(["IFCPRODUCT"]);
  for (const t of spatial) elements.delete(t);
  typeTables = {
    root: union(["IFCROOT"]),
    rel: union(["IFCRELATIONSHIP"]),
    objdef: union(["IFCOBJECTDEFINITION"]),
    elements,
    spatial,
    removable: union(REMOVABLE),
    nomerge: union(NOMERGE),
  };
  return typeTables;
}

function typeFlags(name) {
  if (name === "") return T_COMPLEX | T_NOMERGE;
  const t = inheritance();
  let f = 0;
  if (t.root.has(name)) f |= T_ROOT;
  if (t.rel.has(name)) f |= T_REL;
  if (t.objdef.has(name)) f |= T_OBJDEF;
  if (t.elements.has(name)) f |= T_ELEMENT;
  if (t.spatial.has(name)) f |= T_SPATIAL;
  if (t.removable.has(name)) f |= T_REMOVABLE;
  if (t.nomerge.has(name)) f |= T_NOMERGE;
  return f;
}

/** The schema table for the FILE_SCHEMA of a header; an unknown schema gets the union of all, the safe side. */
function schemaRules(schema) {
  const known = Object.keys(SCHEMA_TABLE);
  const exact = known.find((k) => k === schema);
  const family = known.filter((k) => schema.startsWith(k)).sort((a, b) => b.length - a.length)[0];
  const tables = exact || family ? [SCHEMA_TABLE[exact ?? family]] : Object.values(SCHEMA_TABLE);
  const merge = (part) => {
    const out = new Map();
    for (const table of tables) {
      for (const [name, indices] of Object.entries(table[part])) {
        const set = out.get(name) ?? new Set();
        for (const i of indices) set.add(i);
        out.set(name, set);
      }
    }
    return out;
  };
  return { singleOwner: merge("single_owner"), unique: merge("unique") };
}

/** A failure the user can act on; the message is shown as is. */
export class StepError extends Error {}

/** web-ifc reads a cut-off file without complaint, so check that the STEP envelope is complete first. */
export function assertComplete(input) {
  const size = fstatSize(input);
  const fd = openSync(input, "r");
  try {
    const head = Buffer.alloc(Math.min(size, 64));
    readSync(fd, head, 0, head.length, 0);
    const tail = Buffer.alloc(Math.min(size, TAIL_BYTES));
    readSync(fd, tail, 0, tail.length, size - tail.length);
    const start = head.toString("latin1").replace(/^\xEF\xBB\xBF/, "").trimStart();
    if (!start.startsWith(STEP_HEADER)) {
      throw new StepError(`geen IFC-bestand: het begint niet met ${STEP_HEADER}`);
    }
    if (!tail.toString("latin1").includes(STEP_TRAILER)) {
      throw new StepError(`het bestand is onvolledig (${STEP_TRAILER} ontbreekt aan het eind)`);
    }
  } finally {
    closeSync(fd);
  }
}

function fstatSize(path) {
  const fd = openSync(path, "r");
  try {
    return fstatSync(fd).size;
  } finally {
    closeSync(fd);
  }
}

/** Position after the comment that starts at `p` ("/*"), or -1 when it does not end before `limit`. */
function skipComment(buf, p, limit) {
  for (let q = p + 2; q + 1 < limit; q++) {
    if (buf[q] === STAR && buf[q + 1] === SLASH) return q + 2;
  }
  return -1;
}

/** Position of the first byte at or after `p` that is not white space or a comment; -1 when more bytes are needed. */
function skipSpace(buf, p, limit) {
  while (p < limit) {
    const c = buf[p];
    if (isSpace(c)) p++;
    else if (c === SLASH) {
      if (p + 1 >= limit) return -1;
      if (buf[p + 1] !== STAR) return p;
      p = skipComment(buf, p, limit);
      if (p < 0) return -1;
    } else return p;
  }
  return -1;
}

/** Position after the ";" of the record that starts at `s` ("#"), or -1 when it does not end before `limit`. */
export function recordEnd(buf, s, limit) {
  let p = s + 1;
  while (p < limit) {
    const c = buf[p];
    if (c === QUOTE) {
      p++;
      while (p < limit && buf[p] !== QUOTE) p++;
      if (p >= limit) return -1;
    } else if (c === SLASH) {
      if (p + 1 >= limit) return -1;
      if (buf[p + 1] === STAR) {
        p = skipComment(buf, p, limit);
        if (p < 0) return -1;
        continue;
      }
    } else if (c === SEMI) {
      return p + 1;
    }
    p++;
  }
  return -1;
}

/** The id of the record at `s` ("#123=..."). */
export function recordId(buf, s) {
  let id = 0;
  for (let p = s + 1; isDigit(buf[p]); p++) id = id * 10 + (buf[p] - 48);
  return id;
}

/**
 * Read the DATA section of an IFC file record by record, in chunks. For every record `onRecord(buf, start, limit)` gets
 * the bytes from its "#" and returns the position after its ";", or -1 when the record runs past `limit`: it is then
 * called again for the same record with more bytes. Returns the header (up to and including "DATA;"), the footer
 * (from "ENDSEC;" to the end) and the schema of the file.
 */
export function scanFile(path, onRecord, onHeader = () => {}) {
  const fd = openSync(path, "r");
  try {
    const size = fstatSync(fd).size;
    let buf = Buffer.allocUnsafe(Math.max(1, Math.min(CHUNK, size)));
    let base = 0; // file offset of buf[0]
    let end = 0;
    let pos = 0;
    let eof = size === 0;
    // Keep buf[keep..end), read more after it; grow the buffer when a single item fills it.
    const more = (keep) => {
      if (eof) throw new StepError("het bestand is onvolledig (het eindigt midden in een record)");
      if (keep === 0 && end === buf.length) {
        const bigger = Buffer.allocUnsafe(buf.length * 2);
        buf.copy(bigger, 0, 0, end);
        buf = bigger;
      } else if (keep > 0) {
        buf.copy(buf, 0, keep, end);
        base += keep;
        end -= keep;
        pos -= keep;
      }
      const n = readSync(fd, buf, end, buf.length - end, base + end);
      end += n;
      if (base + end >= size || n === 0) eof = true;
    };
    more(0);

    // Header: up to the keyword DATA; outside strings and comments.
    let headerEnd = findData(buf, 0, end);
    while (headerEnd < 0) {
      if (eof) throw new StepError("geen DATA-sectie gevonden");
      more(0);
      headerEnd = findData(buf, 0, end);
    }
    const header = Buffer.from(buf.subarray(0, headerEnd));
    const schema = /FILE_SCHEMA\s*\(\s*\(\s*'([^']*)'/i.exec(header.toString("latin1"))?.[1]?.toUpperCase() ?? "";
    onHeader(header, schema);
    pos = headerEnd;

    for (;;) {
      const q = skipSpace(buf, pos, end);
      if (q < 0) {
        more(pos);
        continue;
      }
      pos = q;
      if (buf[pos] === HASH) {
        const e = onRecord(buf, pos, end, base + pos);
        if (e < 0) {
          more(pos);
          continue;
        }
        pos = e;
      } else if (buf[pos] === 69) {
        // "E": ENDSEC; the footer is the rest of the file, verbatim.
        if (end - pos < 7 && !eof) {
          more(pos);
          continue;
        }
        if (buf.toString("latin1", pos, pos + 6) !== "ENDSEC") {
          throw new StepError(`onverwachte tekst in de DATA-sectie bij byte ${base + pos}`);
        }
        const rest = Buffer.allocUnsafe(size - (base + pos));
        readSync(fd, rest, 0, rest.length, base + pos);
        if (/\bDATA\s*[;(]/.test(rest.toString("latin1"))) {
          throw new StepError("het bestand heeft meer dan één DATA-sectie; dat wordt niet ondersteund");
        }
        return { header, footer: rest, schema, dataEnd: base + pos };
      } else {
        throw new StepError(`onverwachte tekst in de DATA-sectie bij byte ${base + pos}`);
      }
    }
  } finally {
    closeSync(fd);
  }
}

/** Position after "DATA;" (or "DATA(...);") outside strings and comments; -1 when more bytes are needed. */
function findData(buf, p, limit) {
  while (p < limit) {
    const c = buf[p];
    if (c === QUOTE) {
      p++;
      while (p < limit && buf[p] !== QUOTE) p++;
      if (p >= limit) return -1;
      p++;
    } else if (c === SLASH) {
      if (p + 1 >= limit) return -1;
      if (buf[p + 1] === STAR) {
        p = skipComment(buf, p, limit);
        if (p < 0) return -1;
      } else p++;
    } else if (c === 68 && (p === 0 || !isIdent(buf[p - 1]))) {
      // "D"
      if (p + 4 >= limit) return -1;
      if (buf[p + 1] === 65 && buf[p + 2] === 84 && buf[p + 3] === 65 && !isIdent(buf[p + 4])) {
        let q = skipSpace(buf, p + 4, limit);
        if (q < 0) return -1;
        if (buf[q] === LPAREN) {
          q = recordEnd(buf, q, limit); // DATA(...); of edition 3
          return q;
        }
        if (buf[q] === SEMI) return q + 1;
      }
      p++;
    } else {
      p++;
    }
  }
  return -1;
}

/** A typed array that grows by half when full. */
function grow(array, needed) {
  if (needed <= array.length) return array;
  const bigger = new array.constructor(Math.max(needed, Math.ceil(array.length * 1.5)));
  bigger.set(array);
  return bigger;
}

/**
 * The index of a file. Per record (slot, in file order): `ids`, `types` (index into `typeNames`), `offsets`, and its
 * references `refs[refStart[i]..refStart[i+1])` as slots (DANGLING for an id without a record), with per reference the
 * attribute it sits in (`refAttr`: index, plus IN_LIST inside a list). With `hashes`, `h1`/`h2` hold a 64-bit hash of
 * the record without its id, white space and the ids it refers to (each reference is a bare "#"): two records are
 * identical when type, hash and the records they refer to are.
 */
export class StepIndex {
  static read(path, { hashes = false } = {}) {
    const index = new StepIndex(fstatSize(path), hashes);
    const { header, footer, schema, dataEnd } = scanFile(
      path,
      (buf, s, limit, offset) => index.add(buf, s, limit, offset),
      (_, fileSchema) => {
        index.rules = schemaRules(fileSchema);
      },
    );
    index.header = header;
    index.footer = footer;
    index.schema = schema;
    index.dataEnd = dataEnd;
    index.finish();
    return index;
  }

  constructor(size, hashes) {
    // Most IFC records take 40-60 bytes. Pages that are never written do not count as memory in use.
    const records = Math.ceil(size / 32) + 1024;
    this.n = 0;
    this.ids = new Uint32Array(records);
    this.types = new Uint16Array(records);
    this.offsets = new Float64Array(records);
    this.refStart = new Uint32Array(records + 1);
    this.nrefs = 0;
    this.refs = new Uint32Array(Math.ceil(size / 10) + 4096);
    this.refAttr = new Uint8Array(this.refs.length);
    this.hashes = hashes;
    if (hashes) {
      this.h1 = new Int32Array(records);
      this.h2 = new Int32Array(records);
    }
    this.scratch = Buffer.allocUnsafe(CHUNK);
    this.typeNames = [];
    this.typeFlags = [];
    this.typeIndex = new Map();
    this.pinnedIds = new Uint32Array(1024);
    this.npinned = 0;
    this.schema = "";
    this.rules = schemaRules(""); // replaced by the rules of the schema in the header, before the first record
    this.ownerAttrs = []; // per type: Uint8Array(128), 1 where a reference makes the record the single owner
    this.uniqueAttrs = []; // per type: Uint8Array(128), 1 for a SET or a LIST OF UNIQUE
  }

  /** Index of a type name, with its flags and attribute rules. */
  intern(name) {
    let t = this.typeIndex.get(name);
    if (t !== undefined) return t;
    const upper = name.toUpperCase();
    t = this.typeIndex.get(upper);
    if (t === undefined) {
      t = this.typeNames.length;
      if (t > 0xffff) throw new StepError("het bestand heeft meer dan 65535 verschillende typen");
      this.typeNames.push(upper);
      this.typeFlags.push(typeFlags(upper));
      this.ownerAttrs.push(attrTable(this.rules.singleOwner, upper));
      this.uniqueAttrs.push(attrTable(this.rules.unique, upper));
      this.typeIndex.set(upper, t);
    }
    this.typeIndex.set(name, t);
    return t;
  }

  /** Reads the record at `s` into the index; returns the position after it or -1 (see scanFile). */
  add(buf, s, limit, offset) {
    if (this.scratch.length < limit - s) this.scratch = Buffer.allocUnsafe(limit - s);
    const scratch = this.scratch;
    let p = s + 1;
    let id = 0;
    let digits = 0;
    while (p < limit && isDigit(buf[p])) {
      id = id * 10 + (buf[p] - 48);
      p++;
      digits++;
    }
    if (p >= limit) return -1;
    if (digits === 0 || digits > 10 || id > MAX_ID) throw this.bad(offset, "ongeldige id");
    p = skipSpace(buf, p, limit);
    if (p < 0) return -1;
    if (buf[p] !== EQ) throw this.bad(offset, "'=' ontbreekt");
    p = skipSpace(buf, p + 1, limit);
    if (p < 0) return -1;
    let m = 0;
    let type;
    if (isIdent(buf[p])) {
      const t0 = p;
      while (p < limit && isIdent(buf[p])) {
        const c = buf[p++];
        scratch[m++] = c >= 97 && c <= 122 ? c - 32 : c;
      }
      if (p >= limit) return -1;
      type = this.intern(buf.toString("latin1", t0, p));
    } else if (buf[p] === LPAREN) {
      type = this.intern("");
    } else {
      throw this.bad(offset, "type ontbreekt");
    }
    const owner = this.ownerAttrs[type];
    const r0 = this.nrefs;
    const p0 = this.npinned;
    let depth = 0;
    let attr = 0;
    for (;;) {
      if (p >= limit) {
        this.nrefs = r0;
        this.npinned = p0;
        return -1;
      }
      const c = buf[p];
      if (c === QUOTE) {
        // A string, '' included: everything in it counts, white space too.
        scratch[m++] = c;
        p++;
        while (p < limit && buf[p] !== QUOTE) scratch[m++] = buf[p++];
        if (p >= limit) {
          this.nrefs = r0;
          this.npinned = p0;
          return -1;
        }
        scratch[m++] = QUOTE;
        p++;
        continue;
      }
      if (isSpace(c)) {
        p++;
        continue;
      }
      if (c === HASH) {
        p++;
        let ref = 0;
        let d = 0;
        while (p < limit && isDigit(buf[p])) {
          ref = ref * 10 + (buf[p] - 48);
          p++;
          d++;
        }
        if (p >= limit) {
          this.nrefs = r0;
          this.npinned = p0;
          return -1;
        }
        if (d === 0 || d > 10 || ref > MAX_ID) throw this.bad(offset, "ongeldige verwijzing");
        if (this.nrefs === this.refs.length) {
          this.refs = grow(this.refs, this.nrefs + 1);
          this.refAttr = grow(this.refAttr, this.refs.length);
        }
        const a = attr < 127 ? attr : 127;
        this.refs[this.nrefs] = ref;
        this.refAttr[this.nrefs++] = depth > 1 ? a | IN_LIST : a;
        if (owner !== null && owner[a] === 1) {
          if (this.npinned === this.pinnedIds.length) this.pinnedIds = grow(this.pinnedIds, this.npinned + 1);
          this.pinnedIds[this.npinned++] = ref;
        }
        scratch[m++] = HASH;
        continue;
      }
      if (c === SLASH && (p + 1 >= limit || buf[p + 1] === STAR)) {
        const q = p + 1 >= limit ? -1 : skipComment(buf, p, limit);
        if (q < 0) {
          this.nrefs = r0;
          this.npinned = p0;
          return -1;
        }
        p = q;
        continue;
      }
      if (c === SEMI) break;
      if (c === LPAREN) depth++;
      else if (c === RPAREN) depth--;
      else if (c === COMMA && depth === 1) attr++;
      scratch[m++] = c;
      p++;
    }
    const i = this.n;
    if (i === this.ids.length) this.growRecords(i + 1);
    this.ids[i] = id;
    this.types[i] = type;
    this.offsets[i] = offset;
    this.refStart[i + 1] = this.nrefs;
    if (this.hashes) {
      // Two 32-bit hashes of the masked record (FNV-1a and a multiply-xorshift), with its length.
      let a = 0x811c9dc5 ^ m;
      let b = 0x9e3779b9 ^ Math.imul(m, 0x85ebca6b);
      for (let k = 0; k < m; k++) {
        const x = scratch[k];
        a = Math.imul(a ^ x, 0x01000193);
        b = Math.imul(b ^ x, 0x5bd1e995);
        b ^= b >>> 15;
      }
      this.h1[i] = fmix(a);
      this.h2[i] = fmix(b ^ type);
    }
    this.n = i + 1;
    return p + 1;
  }

  /** The masked bytes of the record at `s` (as hashed), into `out`; returns their length. For checking a merge. */
  static masked(buf, s, out) {
    let p = s + 1;
    while (isDigit(buf[p])) p++;
    p = skipSpace(buf, p, buf.length);
    p = skipSpace(buf, p + 1, buf.length);
    let m = 0;
    while (isIdent(buf[p])) {
      const c = buf[p++];
      out[m++] = c >= 97 && c <= 122 ? c - 32 : c;
    }
    for (;;) {
      const c = buf[p];
      if (c === QUOTE) {
        out[m++] = c;
        p++;
        while (buf[p] !== QUOTE) out[m++] = buf[p++];
        out[m++] = QUOTE;
        p++;
        continue;
      }
      if (isSpace(c)) {
        p++;
        continue;
      }
      if (c === HASH) {
        p++;
        while (isDigit(buf[p])) p++;
        out[m++] = HASH;
        continue;
      }
      if (c === SLASH && buf[p + 1] === STAR) {
        p = skipComment(buf, p, buf.length);
        continue;
      }
      if (c === SEMI) return m;
      out[m++] = c;
      p++;
    }
  }

  bad(offset, what) {
    return new StepError(`ongeldig record bij byte ${offset}: ${what}`);
  }

  growRecords(needed) {
    this.ids = grow(this.ids, needed);
    this.types = grow(this.types, this.ids.length);
    this.offsets = grow(this.offsets, this.ids.length);
    this.refStart = grow(this.refStart, this.ids.length + 1);
    if (this.hashes) {
      this.h1 = grow(this.h1, this.ids.length);
      this.h2 = grow(this.h2, this.ids.length);
    }
  }

  /** Replace the ids in `refs` by slots and resolve the records that must keep their identity. */
  finish() {
    const n = this.n;
    let maxId = 0;
    for (let i = 0; i < n; i++) if (this.ids[i] > maxId) maxId = this.ids[i];
    const slotOf = new IdTable(maxId, n);
    for (let i = 0; i < n; i++) {
      if (!slotOf.set(this.ids[i], i)) {
        throw new StepError(`de id #${this.ids[i]} komt meer dan eens voor`);
      }
    }
    this.flags = new Uint8Array(n);
    const refs = this.refs;
    for (let k = 0; k < this.nrefs; k++) {
      const slot = slotOf.get(refs[k]);
      refs[k] = slot < 0 ? DANGLING : slot;
    }
    this.pinned = new Uint32Array(this.npinned);
    for (let k = 0; k < this.npinned; k++) {
      const slot = slotOf.get(this.pinnedIds[k]);
      this.pinned[k] = slot < 0 ? DANGLING : slot;
    }
    this.pinnedIds = null;
    this.idTableBytes = slotOf.bytes;
    this.scratch = null;
  }

  /** Bytes the index uses per record, in its arrays as far as they are filled (for the measurements). */
  bytesUsed(extra = 0) {
    const perRecord = 4 + 2 + 8 + 4 + 1 + (this.hashes ? 8 : 0);
    return this.n * perRecord + this.nrefs * 5 + this.pinned.length * 4 + this.idTableBytes + extra;
  }
}

function attrTable(map, name) {
  const indices = map.get(name);
  if (!indices) return null;
  const table = new Uint8Array(128);
  for (const i of indices) table[i < 127 ? i : 127] = 1;
  return table;
}

function fmix(h) {
  h ^= h >>> 16;
  h = Math.imul(h, 0x85ebca6b);
  h ^= h >>> 13;
  h = Math.imul(h, 0xc2b2ae35);
  h ^= h >>> 16;
  return h;
}

/** id -> slot: a flat table when the ids are dense enough, else open addressing. */
class IdTable {
  constructor(maxId, n) {
    if (maxId + 1 <= 4 * n + 65536) {
      this.flat = new Int32Array(maxId + 1).fill(-1);
      this.bytes = this.flat.byteLength;
    } else {
      this.cap = 2 * n + 16;
      this.keys = new Uint32Array(this.cap);
      this.vals = new Int32Array(this.cap).fill(-1);
      this.bytes = this.keys.byteLength + this.vals.byteLength;
    }
  }

  slotOfKey(id) {
    let h = fmix(id) >>> 0;
    h = Math.floor((h * this.cap) / 4294967296);
    while (this.vals[h] !== -1 && this.keys[h] !== id) h = h + 1 === this.cap ? 0 : h + 1;
    return h;
  }

  set(id, slot) {
    if (this.flat) {
      if (this.flat[id] !== -1) return false;
      this.flat[id] = slot;
      return true;
    }
    const h = this.slotOfKey(id);
    if (this.vals[h] !== -1) return false;
    this.keys[h] = id;
    this.vals[h] = slot;
    return true;
  }

  get(id) {
    if (this.flat) return id < this.flat.length ? this.flat[id] : -1;
    return this.vals[this.slotOfKey(id)];
  }
}

/** Buffered output to a file, written with writeSync: the passes over a file of GBs run without awaiting. */
export class Output {
  constructor(path) {
    this.fd = openSync(path, "w");
    this.buf = Buffer.allocUnsafe(1024 * 1024);
    this.used = 0;
    this.bytes = 0;
  }

  room(n) {
    if (this.used + n > this.buf.length) {
      this.flush();
      if (n > this.buf.length) this.buf = Buffer.allocUnsafe(n);
    }
  }

  write(src, s, e) {
    this.room(e - s);
    src.copy(this.buf, this.used, s, e);
    this.used += e - s;
  }

  byte(c) {
    if (this.used === this.buf.length) this.flush();
    this.buf[this.used++] = c;
  }

  /** "#" and the digits of `id`. */
  ref(id) {
    this.room(11);
    this.buf[this.used++] = HASH;
    if (id === 0) {
      this.buf[this.used++] = 48;
      return;
    }
    let digits = 0;
    for (let v = id; v > 0; v = Math.floor(v / 10)) digits++;
    let at = this.used + digits;
    this.used = at;
    for (let v = id; v > 0; v = Math.floor(v / 10)) this.buf[--at] = 48 + (v % 10);
  }

  flush() {
    let off = 0;
    while (off < this.used) off += writeSync(this.fd, this.buf, off, this.used - off);
    this.bytes += this.used;
    this.used = 0;
  }

  close() {
    this.flush();
    closeSync(this.fd);
  }
}

/**
 * Write the record at `s` to `out` with its references changed: `mapRef(k)` gives for the k-th reference the id to
 * write, -1 to keep it as it is, or -2 to leave it out of its list (with one comma). Returns the position after ";".
 */
export function writeRecord(buf, s, out, mapRef) {
  let p = s;
  let k = 0;
  let from = s; // start of the bytes not yet written
  for (;;) {
    const c = buf[p];
    if (c === QUOTE) {
      p++;
      while (buf[p] !== QUOTE) p++;
      p++;
      continue;
    }
    if (c === SLASH && buf[p + 1] === STAR) {
      p = skipComment(buf, p, buf.length);
      continue;
    }
    if (c === HASH && p > s) {
      let q = p + 1;
      while (isDigit(buf[q])) q++;
      const to = mapRef(k++);
      if (to === -1) {
        p = q;
        continue;
      }
      if (to === -2) {
        // Leave out "#n" with the comma after it, or else the comma before it.
        out.write(buf, from, p);
        let r = q;
        while (isSpace(buf[r])) r++;
        if (buf[r] === COMMA) {
          r++;
          while (isSpace(buf[r])) r++;
          from = r;
        } else {
          dropLastComma(out);
          from = q;
        }
        p = from;
        continue;
      }
      out.write(buf, from, p);
      out.ref(to);
      from = q;
      p = q;
      continue;
    }
    if (c === SEMI) {
      out.write(buf, from, p + 1);
      return p + 1;
    }
    p++;
  }
}

/** Remove the last comma written to `out` (and the white space after it). */
function dropLastComma(out) {
  let i = out.used - 1;
  while (i >= 0 && isSpace(out.buf[i])) i--;
  if (i >= 0 && out.buf[i] === COMMA) out.used = i;
}

/** A stack of slots in a typed array. */
export class Stack {
  constructor() {
    this.items = new Int32Array(1 << 16);
    this.size = 0;
    this.bytes = this.items.byteLength;
  }

  push(v) {
    if (this.size === this.items.length) {
      const bigger = new Int32Array(this.items.length * 2);
      bigger.set(this.items);
      this.items = bigger;
      this.bytes = Math.max(this.bytes, bigger.byteLength);
    }
    this.items[this.size++] = v;
  }

  pop() {
    return this.items[--this.size];
  }
}
