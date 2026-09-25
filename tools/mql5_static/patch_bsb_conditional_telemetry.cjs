#!/usr/bin/env node
'use strict';
/**
 * One-mechanism, telemetry-only patch for the NMACD BT2 Quant OS candidate.
 *
 * Defect (handoff 2026-09-23, section 5B): the `artifact_canonical_contract`
 * start-up line prints the literal text `bsb_sbs_conditional=1`, which is NOT
 * the value of `InpUseConditionalBsbSbsH4Extreme`. This tool:
 *
 *   1. refuses to run unless the source SHA-256 is a known checkpoint
 *      (Stage 8 or Stage 7) or one you pass explicitly with --expect-sha256;
 *   2. finds exactly one StringFormat whose literal format contains
 *      `bsb_sbs_conditional=1` (0 or >1 matches: abort);
 *   3. replaces it with `bsb_sbs_conditional=%d` and inserts
 *      `InpUseConditionalBsbSbsH4Extreme?1:0` immediately after the
 *      `InpH4StableConfirmBars==1?1:0` argument;
 *   4. proves the call's specifiers and arguments still align, that the new
 *      %d lines up with the new argument, and that no other format call in
 *      the file changed its alignment;
 *   5. writes a NEW file (never overwrites; the original stays byte-identical)
 *      plus patch_report.json, and optionally copies the quoted #include files
 *      next to it with their hashes.
 *
 * No trading, visual or input behaviour changes. Compile the output in
 * MetaEditor (0 errors, 0 warnings) and record the NEW .ex5 hash.
 *
 * Usage:
 *   node tools/mql5_static/patch_bsb_conditional_telemetry.cjs \
 *     --src  "...\\stage8_ma_ribbon\\source\\NMACD_BT2_QOS_SKELETON_STAGE8_MA_RIBBON_20260922.mq5" \
 *     --out-dir "...\\stage8_ma_ribbon\\candidate_telemfix1" --copy-includes
 */

const fs = require('node:fs');
const path = require('node:path');
const src = require('./mql5_source.cjs');

const KNOWN_CHECKPOINTS = {
  '2CBEDDB3ACE23F4C5AE3BC05542E01083EE1731FDFE6399940FA9CAC3FCE9F91': 'Stage 8 MA ribbon 20260922 (handoff-verified)',
  'F886950C8B008CCA99997FAC255C0D01C23369A685155962C64C11ED80C81E64': 'Stage 7 transition M3 exit 20260922 (handoff-verified)',
};

const LITERAL_RE = /bsb_sbs_conditional=1(?![0-9])/g;
const NEW_INPUT = 'InpUseConditionalBsbSbsH4Extreme';

class PatchError extends Error {}

function compact(s) {
  return s.replace(/\s+/g, '');
}

function parseArgs(argv) {
  const out = { copyIncludes: false, suffix: '_TELEMFIX1' };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a === '--src') out.src = argv[++i];
    else if (a === '--out-dir') out.outDir = argv[++i];
    else if (a === '--expect-sha256') out.expect = String(argv[++i]).toUpperCase();
    else if (a === '--copy-includes') out.copyIncludes = true;
    else if (a === '--suffix') out.suffix = argv[++i];
    else throw new PatchError(`Unknown argument: ${a}`);
  }
  if (!out.src || !out.outDir) throw new PatchError('Required: --src <file.mq5> --out-dir <new folder>');
  return out;
}

function planPatch(text) {
  if (!new RegExp(`\\binput\\s+bool\\s+${NEW_INPUT}\\b`).test(text)) {
    throw new PatchError(`Input declaration "input bool ${NEW_INPUT}" not found; wrong source?`);
  }
  const totalLiterals = (text.match(LITERAL_RE) || []).length;
  const calls = src.findCalls(text, ['StringFormat']);
  const hits = [];
  for (const call of calls) {
    const fmt = src.literalFormat(call.args[0] || { tokens: [] });
    if (!fmt) continue;
    for (const part of fmt.parts) {
      LITERAL_RE.lastIndex = 0;
      if (LITERAL_RE.test(part.token.value)) hits.push({ call, part });
    }
  }
  if (hits.length !== 1 || totalLiterals !== 1) {
    throw new PatchError(`Expected exactly 1 "bsb_sbs_conditional=1" inside a StringFormat literal; found ${hits.length} in formats and ${totalLiterals} in the file.`);
  }
  const { call, part } = hits[0];
  const before = src.checkCall(call);
  if (before.status !== 'ok') {
    throw new PatchError(`Target StringFormat at line ${call.line} is already misaligned (${before.needed} specifiers vs ${before.supplied} args); fix that first.`);
  }
  const valueArgs = call.args.slice(1);
  const h4Matches = valueArgs
    .map((a, idx) => ({ a, idx }))
    .filter(({ a }) => compact(a.text) === 'InpH4StableConfirmBars==1?1:0');
  if (h4Matches.length !== 1) {
    throw new PatchError(`Expected exactly 1 "InpH4StableConfirmBars==1?1:0" argument in the target call; found ${h4Matches.length}.`);
  }
  const h4 = h4Matches[0];
  if (valueArgs.some((a) => compact(a.text).startsWith(NEW_INPUT))) {
    throw new PatchError(`${NEW_INPUT} is already an argument of the target call; patch was probably applied.`);
  }

  // Edit 1: literal inside the specific string token.
  const tokenText = part.token.value;
  LITERAL_RE.lastIndex = 0;
  const m = LITERAL_RE.exec(tokenText);
  const literalAbs = part.token.start + m.index;
  const edits = [{ at: literalAbs, remove: 'bsb_sbs_conditional=1'.length, insert: 'bsb_sbs_conditional=%d' }];

  // Edit 2: new argument right after the H4 argument, matching its style and indentation.
  const spaced = /\?\s/.test(h4.a.text) ? `${NEW_INPUT} ? 1 : 0` : `${NEW_INPUT}?1:0`;
  const h4TextStart = h4.a.start + (h4.a.text.length - h4.a.text.trimStart().length);
  const lineStart = text.lastIndexOf('\n', h4TextStart) + 1;
  const indent = text.slice(lineStart, h4TextStart);
  const onOwnLine = /^\s*$/.test(indent);
  const eol = text.includes('\r\n') ? '\r\n' : '\n';
  const after = h4.a.end; // position of the following ',' or ')'
  if (text[after] === ',') {
    edits.push({ at: after + 1, remove: 0, insert: onOwnLine ? `${eol}${indent}${spaced},` : ` ${spaced},` });
  } else {
    edits.push({ at: after, remove: 0, insert: `, ${spaced}` });
  }
  return { call, h4Index: h4.idx, edits, before };
}

function applyEdits(text, edits) {
  let out = text;
  for (const e of [...edits].sort((x, y) => y.at - x.at)) {
    out = out.slice(0, e.at) + e.insert + out.slice(e.at + e.remove);
  }
  return out;
}

function verifyPatched(text, originalAudit, h4Index) {
  const calls = src.findCalls(text, ['StringFormat']);
  const target = calls.filter((c) => {
    const f = src.literalFormat(c.args[0] || { tokens: [] });
    return f && f.raw.includes('bsb_sbs_conditional=%d');
  });
  if (target.length !== 1) throw new PatchError('Verification failed: patched call not found exactly once.');
  const call = target[0];
  const check = src.checkCall(call);
  if (check.status !== 'ok') {
    throw new PatchError(`Verification failed: ${check.needed} specifiers vs ${check.supplied} arguments after patch.`);
  }
  // Map specifier -> argument index and prove the new %d consumes the new argument.
  const fmt = src.literalFormat(call.args[0]).raw;
  const marker = fmt.indexOf('bsb_sbs_conditional=%d') + 'bsb_sbs_conditional='.length;
  let argCursor = 0;
  let newSpecArg = -1;
  let h4SpecArg = -1;
  for (const s of check.specs) {
    const valueArg = argCursor + s.consumes - 1;
    if (s.index === marker) newSpecArg = valueArg;
    argCursor += s.consumes;
  }
  const valueArgs = call.args.slice(1);
  const newArgIdx = valueArgs.findIndex((a) => compact(a.text).startsWith(NEW_INPUT));
  h4SpecArg = valueArgs.findIndex((a) => compact(a.text) === 'InpH4StableConfirmBars==1?1:0');
  if (newArgIdx !== h4Index + 1 || h4SpecArg !== h4Index) {
    throw new PatchError('Verification failed: new argument is not immediately after the H4 argument.');
  }
  if (newSpecArg !== newArgIdx) {
    throw new PatchError(`Verification failed: bsb_sbs_conditional=%d consumes argument #${newSpecArg}, but the new input is argument #${newArgIdx}. Another specifier sits between the H4 value and bsb_sbs_conditional; review by hand.`);
  }
  const patchedAudit = src.formatAudit(text);
  const key = (r) => `${r.name}|${r.needed}|${r.supplied}|${r.format}`;
  const before = new Set(originalAudit.mismatches.map(key));
  const introduced = patchedAudit.mismatches.filter((r) => !before.has(key(r)));
  if (introduced.length) throw new PatchError(`Verification failed: patch introduced format mismatches: ${JSON.stringify(introduced)}`);
  return { call, check, patchedAudit, newArgIdx };
}

function lineDiff(oldText, newText) {
  const a = oldText.split(/\r?\n/);
  const b = newText.split(/\r?\n/);
  let i = 0;
  while (i < a.length && i < b.length && a[i] === b[i]) i++;
  let ea = a.length - 1;
  let eb = b.length - 1;
  while (ea >= i && eb >= i && a[ea] === b[eb]) { ea--; eb--; }
  // Exact LCS diff of the (small) changed region, so unchanged lines between
  // the two edits are shown as context rather than as removed/added.
  const x = a.slice(i, ea + 1);
  const y = b.slice(i, eb + 1);
  const L = Array.from({ length: x.length + 1 }, () => new Array(y.length + 1).fill(0));
  for (let p = x.length - 1; p >= 0; p--) {
    for (let q = y.length - 1; q >= 0; q--) {
      L[p][q] = x[p] === y[q] ? L[p + 1][q + 1] + 1 : Math.max(L[p + 1][q], L[p][q + 1]);
    }
  }
  const hunk = [];
  let p = 0;
  let q = 0;
  while (p < x.length || q < y.length) {
    if (p < x.length && q < y.length && x[p] === y[q]) { hunk.push(`  ${x[p]}`); p++; q++; }
    else if (p < x.length && (q >= y.length || L[p + 1][q] >= L[p][q + 1])) { hunk.push(`- ${x[p]}`); p++; }
    else { hunk.push(`+ ${y[q]}`); q++; }
  }
  return {
    firstChangedLine: i + 1,
    removed: hunk.filter((l) => l.startsWith('- ')),
    added: hunk.filter((l) => l.startsWith('+ ')),
    hunk,
  };
}

function quotedIncludes(text) {
  const out = [];
  const re = /^\s*#include\s+"([^"]+)"/gm;
  let m;
  while ((m = re.exec(text)) !== null) out.push(m[1]);
  return out;
}

function run(argv) {
  const args = parseArgs(argv);
  const original = src.readSource(args.src);
  const known = KNOWN_CHECKPOINTS[original.sha256];
  if (args.expect ? original.sha256 !== args.expect : !known) {
    throw new PatchError(`Source SHA-256 ${original.sha256} is not ${args.expect ? 'the --expect-sha256 value' : 'a known checkpoint'}. Refusing to patch an unverified source.`);
  }
  if (fs.existsSync(args.outDir) && fs.readdirSync(args.outDir).length) {
    throw new PatchError(`Output directory ${args.outDir} is not empty. Choose a new directory; nothing is overwritten.`);
  }

  const originalAudit = src.formatAudit(original.text);
  const plan = planPatch(original.text);
  const patchedText = applyEdits(original.text, plan.edits);
  const verified = verifyPatched(patchedText, originalAudit, plan.h4Index);

  const base = path.basename(args.src, path.extname(args.src));
  const outName = `${base}${args.suffix}${path.extname(args.src)}`;
  fs.mkdirSync(args.outDir, { recursive: true });
  const outPath = path.join(args.outDir, outName);
  const outBytes = src.encodeSource(patchedText, original.encoding, original.bom);
  fs.writeFileSync(outPath, outBytes, { flag: 'wx' });

  const includes = [];
  if (args.copyIncludes) {
    // Follow quoted includes recursively (e.g. DecisionCore -> ribbon/zigzag cores),
    // resolving each relative to the file that includes it.
    const srcRoot = path.dirname(path.resolve(args.src));
    const queue = quotedIncludes(original.text).map((inc) => ({ inc, dir: srcRoot }));
    const seen = new Set();
    while (queue.length) {
      const { inc, dir } = queue.shift();
      const from = path.resolve(dir, inc);
      const rel = path.relative(srcRoot, from);
      if (seen.has(from)) continue;
      seen.add(from);
      if (rel.startsWith('..') || path.isAbsolute(rel)) { includes.push({ include: inc, status: 'outside_source_dir_not_copied' }); continue; }
      if (!fs.existsSync(from)) { includes.push({ include: rel, status: 'missing_in_source_dir' }); continue; }
      const to = path.join(args.outDir, rel);
      fs.mkdirSync(path.dirname(to), { recursive: true });
      fs.copyFileSync(from, to, fs.constants.COPYFILE_EXCL);
      includes.push({ include: rel, status: 'copied', sha256: src.sha256(fs.readFileSync(to)) });
      const nested = src.readSource(from).text;
      for (const child of quotedIncludes(nested)) queue.push({ inc: child, dir: path.dirname(from) });
    }
  }

  // The original must be untouched.
  const recheck = src.sha256(fs.readFileSync(args.src));
  if (recheck !== original.sha256) throw new PatchError('Original source hash changed during the run!');

  const report = {
    tool: 'patch_bsb_conditional_telemetry',
    change: 'Telemetry only: artifact_canonical_contract now prints the real InpUseConditionalBsbSbsH4Extreme value.',
    behaviour_change: 'none (log text only)',
    source: { path: path.resolve(args.src), sha256: original.sha256, checkpoint: known || 'explicit --expect-sha256', encoding: original.encoding, bom: original.bom, eol: original.eol === '\r\n' ? 'CRLF' : 'LF' },
    output: { path: path.resolve(outPath), sha256: src.sha256(outBytes) },
    target_call_line: plan.call.line,
    alignment: { before: `${plan.before.needed} specifiers / ${plan.before.supplied} args`, after: `${verified.check.needed} specifiers / ${verified.check.supplied} args`, new_argument_index: verified.newArgIdx, h4_argument_index: plan.h4Index },
    whole_file_format_audit: { before: { calls: originalAudit.calls, mismatches: originalAudit.mismatches.length, unknown: originalAudit.unknown }, after: { calls: verified.patchedAudit.calls, mismatches: verified.patchedAudit.mismatches.length, unknown: verified.patchedAudit.unknown }, preexisting_mismatches: originalAudit.mismatches },
    diff: lineDiff(original.text, patchedText),
    includes,
    original_unchanged: true,
    next_steps: [
      'Compile the output .mq5 in MetaEditor: 0 errors, 0 warnings.',
      'Record the NEW .ex5 SHA-256; do not reuse 5AA574DC... or any older binary hash.',
      'Do not point the frozen STAGE8_CLOSURE_20260923_R3 batch at this candidate.',
      'Runtime proof of the conditional gate (qualified / blocked / data-unavailable events) is a separate, later change.',
    ],
  };
  const reportPath = path.join(args.outDir, 'patch_report.json');
  fs.writeFileSync(reportPath, JSON.stringify(report, null, 2), { flag: 'wx' });
  return { report, outPath, reportPath };
}

if (require.main === module) {
  try {
    const { report, outPath, reportPath } = run(process.argv.slice(2));
    console.log(`Patched: ${outPath}`);
    console.log(`  source ${report.source.sha256} (${report.source.checkpoint})`);
    console.log(`  output ${report.output.sha256}`);
    console.log(`  line ${report.target_call_line}: ${report.alignment.before} -> ${report.alignment.after}`);
    for (const l of report.diff.hunk) console.log(`  ${l}`);
    console.log(`Report: ${reportPath}`);
  } catch (e) {
    console.error(`REFUSED: ${e.message}`);
    process.exitCode = 1;
  }
}

module.exports = { run, planPatch, applyEdits, verifyPatched, PatchError, KNOWN_CHECKPOINTS };
