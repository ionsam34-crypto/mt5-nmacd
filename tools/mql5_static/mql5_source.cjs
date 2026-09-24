'use strict';
/**
 * Minimal, dependency-free MQL5 source reader for offline static checks.
 *
 * - Reads MetaEditor sources in UTF-16LE (with BOM), UTF-8 with BOM, or plain
 *   UTF-8, and remembers the encoding and line endings so edits can be
 *   written back byte-compatible.
 * - Tokenizes just enough (strings, chars, comments, identifiers, brackets)
 *   to find StringFormat/PrintFormat calls and split their arguments without
 *   being fooled by commas or parentheses inside strings.
 * - Counts printf-style specifiers so format/argument alignment can be proven.
 *
 * It is NOT a compiler. MetaEditor remains the authority on whether code builds.
 */

const crypto = require('node:crypto');
const fs = require('node:fs');

function sha256(buf) {
  return crypto.createHash('sha256').update(buf).digest('hex').toUpperCase();
}

function decodeSource(buf) {
  if (buf.length >= 2 && buf[0] === 0xff && buf[1] === 0xfe) {
    return { text: buf.subarray(2).toString('utf16le'), encoding: 'utf16le', bom: true };
  }
  if (buf.length >= 3 && buf[0] === 0xef && buf[1] === 0xbb && buf[2] === 0xbf) {
    return { text: buf.subarray(3).toString('utf8'), encoding: 'utf8', bom: true };
  }
  if (buf.includes(0x00)) {
    throw new Error('Source contains NUL bytes without a UTF-16LE BOM; refusing to guess the encoding.');
  }
  return { text: buf.toString('utf8'), encoding: 'utf8', bom: false };
}

function encodeSource(text, encoding, bom) {
  if (encoding === 'utf16le') {
    const body = Buffer.from(text, 'utf16le');
    return bom ? Buffer.concat([Buffer.from([0xff, 0xfe]), body]) : body;
  }
  const body = Buffer.from(text, 'utf8');
  return bom ? Buffer.concat([Buffer.from([0xef, 0xbb, 0xbf]), body]) : body;
}

function readSource(path) {
  const bytes = fs.readFileSync(path);
  const decoded = decodeSource(bytes);
  const eol = decoded.text.includes('\r\n') ? '\r\n' : '\n';
  return { path, bytes, sha256: sha256(bytes), eol, ...decoded };
}

/** Tokens: {type, value, start, end}; types: ws, comment, string, char, ident, number, punct. */
function tokenize(text) {
  const tokens = [];
  let i = 0;
  const n = text.length;
  while (i < n) {
    const c = text[i];
    const start = i;
    if (/\s/.test(c)) {
      while (i < n && /\s/.test(text[i])) i++;
      tokens.push({ type: 'ws', start, end: i });
    } else if (c === '/' && text[i + 1] === '/') {
      while (i < n && text[i] !== '\n') i++;
      tokens.push({ type: 'comment', start, end: i });
    } else if (c === '/' && text[i + 1] === '*') {
      const close = text.indexOf('*/', i + 2);
      i = close < 0 ? n : close + 2;
      tokens.push({ type: 'comment', start, end: i });
    } else if (c === '"' || c === "'") {
      i++;
      while (i < n && text[i] !== c) {
        if (text[i] === '\\') i++;
        if (text[i] === '\n') break; // unterminated: stop at line end
        i++;
      }
      i++;
      tokens.push({ type: c === '"' ? 'string' : 'char', start, end: Math.min(i, n) });
    } else if (/[A-Za-z_]/.test(c)) {
      while (i < n && /[A-Za-z0-9_]/.test(text[i])) i++;
      tokens.push({ type: 'ident', start, end: i });
    } else if (/[0-9]/.test(c)) {
      while (i < n && /[0-9A-Za-z_.]/.test(text[i])) i++;
      tokens.push({ type: 'number', start, end: i });
    } else {
      i++;
      tokens.push({ type: 'punct', start, end: i });
    }
  }
  for (const t of tokens) t.value = text.slice(t.start, t.end);
  return tokens;
}

function lineOf(text, offset) {
  let line = 1;
  for (let i = 0; i < offset && i < text.length; i++) if (text[i] === '\n') line++;
  return line;
}

/**
 * Finds calls to the named functions. Each call:
 * {name, start, openParen, closeParen, line, args:[{start,end,text,tokens}]}
 */
function findCalls(text, names = ['StringFormat', 'PrintFormat'], tokens = tokenize(text)) {
  const wanted = new Set(names);
  const calls = [];
  for (let k = 0; k < tokens.length; k++) {
    const t = tokens[k];
    if (t.type !== 'ident' || !wanted.has(t.value)) continue;
    let j = k + 1;
    while (j < tokens.length && (tokens[j].type === 'ws' || tokens[j].type === 'comment')) j++;
    if (j >= tokens.length || tokens[j].value !== '(') continue;
    const open = j;
    let depth = 0;
    let argStart = tokens[open].end;
    const args = [];
    let argTokens = [];
    let close = -1;
    for (let m = open; m < tokens.length; m++) {
      const v = tokens[m].value;
      const isCode = tokens[m].type === 'punct';
      if (isCode && (v === '(' || v === '[' || v === '{')) {
        depth++;
        if (m === open) continue;
      } else if (isCode && (v === ')' || v === ']' || v === '}')) {
        depth--;
        if (depth === 0) {
          args.push({ start: argStart, end: tokens[m].start, tokens: argTokens });
          close = m;
          break;
        }
      } else if (isCode && v === ',' && depth === 1) {
        args.push({ start: argStart, end: tokens[m].start, tokens: argTokens });
        argStart = tokens[m].end;
        argTokens = [];
        continue;
      }
      if (m !== open) argTokens.push(tokens[m]);
    }
    if (close < 0) continue;
    for (const a of args) a.text = text.slice(a.start, a.end);
    calls.push({
      name: t.value,
      start: t.start,
      openParen: tokens[open].start,
      closeParen: tokens[close].start,
      line: lineOf(text, t.start),
      args,
    });
  }
  return calls;
}

/** Concatenated raw content of a format argument made only of string literals (joined by + or adjacency). */
function literalFormat(arg) {
  const parts = [];
  for (const t of arg.tokens) {
    if (t.type === 'ws' || t.type === 'comment') continue;
    if (t.type === 'string') parts.push({ token: t, raw: t.value.slice(1, -1) });
    else if (t.type === 'punct' && t.value === '+') continue;
    else return null;
  }
  if (!parts.length) return null;
  return { raw: parts.map((p) => p.raw).join(''), parts };
}

const SPEC_RE = /%(%|[-+ #0]*(\*|\d+)?(?:\.(\*|\d+))?(?:ll|l|h|I32|I64)?([cCdiouxXeEfgGaAsS]))/g;

/** Returns specifiers with the number of arguments each consumes (a '*' width/precision consumes one more). */
function specifiers(format) {
  const out = [];
  let m;
  SPEC_RE.lastIndex = 0;
  while ((m = SPEC_RE.exec(format)) !== null) {
    if (m[1] === '%') continue;
    const consumes = 1 + (m[2] === '*' ? 1 : 0) + (m[3] === '*' ? 1 : 0);
    out.push({ text: m[0], index: m.index, consumes });
  }
  return out;
}

/** Alignment check for one call. status: ok | mismatch | unknown (non-literal format). */
function checkCall(call) {
  if (!call.args.length) return { status: 'unknown', reason: 'no arguments' };
  const fmt = literalFormat(call.args[0]);
  if (!fmt) return { status: 'unknown', reason: 'format is not a string literal' };
  const specs = specifiers(fmt.raw);
  const needed = specs.reduce((s, x) => s + x.consumes, 0);
  const supplied = call.args.length - 1;
  return { status: needed === supplied ? 'ok' : 'mismatch', needed, supplied, specs, format: fmt.raw };
}

function formatAudit(text) {
  const calls = findCalls(text);
  const results = calls.map((c) => ({ line: c.line, name: c.name, ...checkCall(c) }));
  return {
    calls: results.length,
    ok: results.filter((r) => r.status === 'ok').length,
    unknown: results.filter((r) => r.status === 'unknown').length,
    mismatches: results
      .filter((r) => r.status === 'mismatch')
      .map(({ line, name, needed, supplied, format }) => ({ line, name, needed, supplied, format })),
  };
}

module.exports = {
  sha256,
  decodeSource,
  encodeSource,
  readSource,
  tokenize,
  lineOf,
  findCalls,
  literalFormat,
  specifiers,
  checkCall,
  formatAudit,
};
