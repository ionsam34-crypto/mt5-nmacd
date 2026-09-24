#!/usr/bin/env node
'use strict';
/**
 * Read-only callsite audit for the NMACD BT2 Quant OS candidate (handoff
 * priorities 2 and 3). It never edits anything. For one source file it lists:
 *
 *  - declared inputs (count and names), to replace hard-coded input counts;
 *  - every M3-clock dependency (PERIOD_M3, PeriodSeconds(PERIOD_M3), the
 *    wrong-timeframe guard), each with its enclosing function;
 *  - entry-route and stacking functions and all of their call sites;
 *  - every reference to switches that change entry routing;
 *  - whole-file StringFormat/PrintFormat alignment problems.
 *
 * Line numbers are for the exact file hashed in the report. Re-run after any edit.
 *
 * Usage:
 *   node tools/mql5_static/callsite_audit.cjs --src <file.mq5> [--json out.json]
 */

const fs = require('node:fs');
const src = require('./mql5_source.cjs');

const ROUTE_FUNCTIONS = [
  'ExecuteAutoTradeIfNeeded',
  'ExecutePendingH1PermissionLeg1',
  'BuildStackAdmissionContext',
  'StackAdmissionAllowsNextLeg',
  'EffectiveMaxStackedPositionsForState',
  'ConditionalTransitionH4ExtremeQualified',
  'BuildStateRouterContext',
  'ApplyStateAwareRouter',
  'EvaluateSignalWouldFire',
];

const ROUTE_SWITCHES = [
  'InpUseArtifactCanonicalContract',
  'InpH1PermissionDotFiresLeg1',
  'InpUseConditionalBsbSbsH4Extreme',
  'InpAllowLong',
  'InpAllowShort',
  'InpMaxStackedPositions',
  'g_h1_permission_leg1_order_inflight',
];

const M3_PATTERNS = [
  { id: 'PERIOD_M3', re: /\bPERIOD_M3\b/ },
  { id: 'wrong_trading_period_guard', re: /\bg_wrong_trading_period\b/ },
  { id: 'M3_literal_in_code', re: /\b(?:M3|m3)_?(?:bars?|minutes?|seconds?)\b/ },
];

function codeOnlyLines(text) {
  // Blank out comments and string contents so patterns match code, not prose.
  const tokens = src.tokenize(text);
  let out = '';
  for (const t of tokens) {
    if (t.type === 'comment') out += t.value.replace(/[^\n]/g, ' ');
    else if (t.type === 'string') out += '"' + t.value.slice(1, -1).replace(/[^\n]/g, ' ') + '"';
    else out += t.value;
  }
  return out.split('\n');
}

function functionIndex(lines) {
  // Top-level function definitions: a column-0 signature line followed (same or next lines) by '{'.
  const defs = [];
  const sig = /^(?:static\s+|const\s+|virtual\s+)*[A-Za-z_][\w<>:*&\s]*?\s+[*&]?([A-Za-z_]\w*)\s*\(/;
  for (let i = 0; i < lines.length; i++) {
    const l = lines[i];
    if (!l || /^\s/.test(l) || /^#/.test(l)) continue;
    const m = sig.exec(l);
    if (!m) continue;
    if (/^(?:if|for|while|switch|return|else|input|sinput|struct|class|enum)\b/.test(l.trim())) continue;
    let j = i;
    let seenBrace = false;
    while (j < Math.min(lines.length, i + 8)) {
      if (lines[j].includes(';') && !lines[j].includes('{')) break;
      if (lines[j].includes('{')) { seenBrace = true; break; }
      j++;
    }
    if (seenBrace) defs.push({ name: m[1], line: i + 1 });
  }
  return defs;
}

function enclosing(defs, line) {
  let best = null;
  for (const d of defs) if (d.line <= line) best = d; else break;
  return best ? best.name : '(global)';
}

function audit(path) {
  const s = src.readSource(path);
  const code = codeOnlyLines(s.text);
  const raw = s.text.split('\n');
  const defs = functionIndex(code);

  const inputs = [];
  code.forEach((l, i) => {
    const m = /^\s*(?:input|sinput)\s+(?!group\b)[\w:<>]+\s+([A-Za-z_]\w*)/.exec(l);
    if (m) inputs.push({ name: m[1], line: i + 1 });
  });

  const m3 = [];
  code.forEach((l, i) => {
    for (const p of M3_PATTERNS) {
      if (p.re.test(l)) m3.push({ pattern: p.id, line: i + 1, function: enclosing(defs, i + 1), code: raw[i].trim() });
    }
  });

  const routes = {};
  for (const fn of ROUTE_FUNCTIONS) {
    const def = defs.find((d) => d.name === fn);
    const re = new RegExp(`\\b${fn}\\s*\\(`);
    const calls = [];
    code.forEach((l, i) => {
      if (re.test(l) && !(def && def.line === i + 1)) calls.push({ line: i + 1, from: enclosing(defs, i + 1) });
    });
    routes[fn] = { defined_at: def ? def.line : null, call_sites: calls };
  }

  const switches = {};
  for (const sw of ROUTE_SWITCHES) {
    const re = new RegExp(`\\b${sw}\\b`);
    switches[sw] = [];
    code.forEach((l, i) => {
      if (re.test(l)) switches[sw].push({ line: i + 1, function: enclosing(defs, i + 1), code: raw[i].trim() });
    });
  }

  return {
    source: { path, sha256: s.sha256, encoding: s.encoding, bom: s.bom, lines: raw.length },
    inputs: { count: inputs.length, names: inputs },
    functions_found: defs.length,
    m3_clock_dependencies: m3,
    entry_route_functions: routes,
    route_switch_references: switches,
    format_alignment: src.formatAudit(s.text),
  };
}

function summary(r) {
  const out = [];
  out.push(`Source ${r.source.path}`);
  out.push(`  SHA-256 ${r.source.sha256}  (${r.source.encoding}${r.source.bom ? ' BOM' : ''}, ${r.source.lines} lines)`);
  out.push(`  inputs declared: ${r.inputs.count}   functions indexed: ${r.functions_found}`);
  out.push(`  M3-clock dependencies: ${r.m3_clock_dependencies.length}`);
  for (const d of r.m3_clock_dependencies) out.push(`    L${d.line} [${d.pattern}] in ${d.function}: ${d.code}`);
  out.push('  entry-route functions:');
  for (const [fn, v] of Object.entries(r.entry_route_functions)) {
    out.push(`    ${fn}: defined L${v.defined_at ?? '-'}; called from ${v.call_sites.map((c) => `${c.from}@L${c.line}`).join(', ') || '(none)'}`);
  }
  const fa = r.format_alignment;
  out.push(`  format calls: ${fa.calls} (ok ${fa.ok}, non-literal ${fa.unknown}, MISALIGNED ${fa.mismatches.length})`);
  for (const m of fa.mismatches) out.push(`    L${m.line} ${m.name}: ${m.needed} specifiers vs ${m.supplied} args`);
  return out.join('\n');
}

if (require.main === module) {
  const argv = process.argv.slice(2);
  const i = argv.indexOf('--src');
  if (i < 0) { console.error('Usage: callsite_audit.cjs --src <file.mq5> [--json out.json]'); process.exit(2); }
  const report = audit(argv[i + 1]);
  const j = argv.indexOf('--json');
  if (j >= 0) {
    if (fs.existsSync(argv[j + 1])) { console.error(`REFUSED: ${argv[j + 1]} exists`); process.exit(1); }
    fs.writeFileSync(argv[j + 1], JSON.stringify(report, null, 2), { flag: 'wx' });
  }
  console.log(summary(report));
}

module.exports = { audit, summary, functionIndex };
