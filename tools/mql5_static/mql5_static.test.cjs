'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

const src = require('./mql5_source.cjs');
const patcher = require('./patch_bsb_conditional_telemetry.cjs');
const callsites = require('./callsite_audit.cjs');

// Fixture: the artifact_canonical_contract call copied from the v2.06 production
// source (same defect the handoff reports in Stage 7/8), plus routing and M3
// clock code shaped like the candidate.
const FIXTURE = [
  '#property strict',
  '#include "NMACD_BT2_DecisionCore.mqh"',
  '#include <Canvas\\Canvas.mqh>',
  'input bool   InpUseArtifactCanonicalContract=false; // explicit isolated-candidate master',
  'input group "HTF"',
  'input int    InpH4StableConfirmBars=2;',
  'input bool   InpUseConditionalBsbSbsH4Extreme=false;',
  'input double InpH4TransitionExtremeLevel=1.0;',
  'input int    InpH4TransitionExtremeClosedBars=4;',
  'input bool   InpH1PermissionDotFiresLeg1=true;',
  'input int    InpExitRegimeMinutes=60;',
  'input bool   InpM60ZeroDelayExit=true;',
  'input int    InpMaxStackedPositions=28;',
  'input bool   InpUseBasketProfitTrail=true;',
  'input bool   InpUseSixLegBreakEvenStall=true;',
  'input bool   InpFlattenBeforeSessionClose=true;',
  'input bool   InpUseCanonicalD1Structure=false;',
  'input int    InpD1StructurePivotLeftBars=2;',
  'input int    InpD1StructurePivotRightBars=2;',
  'bool g_wrong_trading_period=false;',
  'bool g_h1_permission_leg1_order_inflight=false;',
  '',
  '// PERIOD_M3 mentioned in a comment must not count',
  'void UpdateFakeSignalCleanupTimeouts(void)',
  '  {',
  '   const long grace_sec=(long)5*PeriodSeconds(PERIOD_M3);',
  '   Print("PERIOD_M3 in a string, (not code), must not count");',
  '  }',
  '',
  'void ExecuteAutoTradeIfNeeded(const int x)',
  '  {',
  '   if(InpUseArtifactCanonicalContract && x==0 && !g_h1_permission_leg1_order_inflight)',
  '      return;',
  '  }',
  '',
  'bool ExecutePendingH1PermissionLeg1(void)',
  '  {',
  '   g_h1_permission_leg1_order_inflight=true;',
  '   ExecuteAutoTradeIfNeeded(1);',
  '   return true;',
  '  }',
  '',
  'void ManageBar(void)',
  '  {',
  '   string s=StringFormat("a=%s, b=(%d)", "x,(y)", MathMax(1,2));',
  '   ExecuteAutoTradeIfNeeded(0);',
  '  }',
  '',
  'int OnInit(void)',
  '  {',
  '   const string symbol=_Symbol;',
  '   string startup_fill_list="";',
  '   g_wrong_trading_period=(_Period!=PERIOD_M3);',
  '   g_logger.Write(MT5QE_INFO,',
  '                  "artifact_canonical_contract",',
  '                  StringFormat("master=%d d1_structure=%d d1_pivots=%d/%d h4_zero_added_delay=%d bbb_sss_fresh=1 bsb_sbs_conditional=1 h4_extreme_level=%.6f h4_extreme_closed_bars=%d h1_leg1=%d m3_adds=1 flat_before_reversal=1 m60_only=1 m60_minutes=%d m60_zero_delay=%d max_stack=%d basket_trail=%d six_leg_stall=%d session_flatten=%d fill_mask=%I64d execution_mode=%d fill_candidates=%s",',
  '                               InpUseArtifactCanonicalContract?1:0,',
  '                               InpUseCanonicalD1Structure?1:0,',
  '                               InpD1StructurePivotLeftBars,',
  '                               InpD1StructurePivotRightBars,',
  '                               InpH4StableConfirmBars==1?1:0,',
  '                               InpH4TransitionExtremeLevel,',
  '                               InpH4TransitionExtremeClosedBars,',
  '                               InpH1PermissionDotFiresLeg1?1:0,',
  '                               InpExitRegimeMinutes,',
  '                               InpM60ZeroDelayExit?1:0,',
  '                               InpMaxStackedPositions,',
  '                               InpUseBasketProfitTrail?1:0,',
  '                               InpUseSixLegBreakEvenStall?1:0,',
  '                               InpFlattenBeforeSessionClose?1:0,',
  '                               SymbolInfoInteger(symbol,SYMBOL_FILLING_MODE),',
  '                               (int)SymbolInfoInteger(symbol,SYMBOL_TRADE_EXEMODE),',
  '                               startup_fill_list));',
  '   return INIT_SUCCEEDED;',
  '  }',
  '',
].join('\r\n');

function tmpdir() {
  return fs.mkdtempSync(path.join(os.tmpdir(), 'mql5static-'));
}

function writeFixture(dir, text = FIXTURE, encoding = 'utf8', bom = false) {
  const file = path.join(dir, 'NMACD_TEST_CANDIDATE.mq5');
  fs.writeFileSync(file, src.encodeSource(text, encoding, bom));
  fs.writeFileSync(path.join(dir, 'NMACD_BT2_DecisionCore.mqh'), '#include "QOS_MA_Ribbon_12_21_Core.mqh"\r\n// core\r\n');
  fs.writeFileSync(path.join(dir, 'QOS_MA_Ribbon_12_21_Core.mqh'), '// ribbon\r\n');
  return { file, sha: src.sha256(fs.readFileSync(file)) };
}

test('specifier counting handles %%, precision, I64 and * width', () => {
  const s = src.specifiers('a=%d 100%% b=%.6f c=%I64d d=%s e=%*d f=%-5.2f');
  assert.equal(s.length, 6);
  assert.equal(s.reduce((n, x) => n + x.consumes, 0), 7);
});

test('call splitter ignores commas and parentheses inside strings and nested calls', () => {
  const calls = src.findCalls('x=StringFormat("a=%s, b=(%d)", "x,(y)", MathMax(1,2));');
  assert.equal(calls.length, 1);
  assert.equal(calls[0].args.length, 3);
  assert.equal(src.checkCall(calls[0]).status, 'ok');
});

test('string concatenation formats and mismatches are detected', () => {
  const ok = src.findCalls('PrintFormat("a=%d "+"b=%s", 1, "x");')[0];
  assert.equal(src.checkCall(ok).status, 'ok');
  const bad = src.findCalls('PrintFormat("a=%d b=%d", 1);')[0];
  const r = src.checkCall(bad);
  assert.equal(r.status, 'mismatch');
  assert.deepEqual([r.needed, r.supplied], [2, 1]);
});

test('v2.06 artifact_canonical_contract call is aligned before patching (17/17)', () => {
  const call = src.findCalls(FIXTURE).find((c) => c.args[0].text.includes('artifact') || c.args[0].text.includes('bsb_sbs'));
  const r = src.checkCall(call);
  assert.equal(r.status, 'ok');
  assert.equal(r.needed, 17);
});

test('patch fixes the literal, inserts the argument after H4, keeps alignment and original bytes', () => {
  const dir = tmpdir();
  const { file, sha } = writeFixture(dir);
  const out = path.join(dir, 'out');
  const { report, outPath } = patcher.run(['--src', file, '--out-dir', out, '--expect-sha256', sha, '--copy-includes']);
  const text = src.readSource(outPath).text;
  assert.ok(text.includes('bsb_sbs_conditional=%d'));
  assert.ok(!/bsb_sbs_conditional=1(?![0-9])/.test(text));
  assert.ok(text.includes('InpH4StableConfirmBars==1?1:0,\r\n                               InpUseConditionalBsbSbsH4Extreme?1:0,\r\n                               InpH4TransitionExtremeLevel,'));
  assert.equal(report.alignment.after, '18 specifiers / 18 args');
  assert.equal(report.alignment.new_argument_index, report.alignment.h4_argument_index + 1);
  assert.equal(src.sha256(fs.readFileSync(file)), sha, 'original must be unchanged');
  assert.notEqual(report.output.sha256, sha);
  assert.equal(report.diff.removed.length, 1);
  assert.equal(report.diff.added.length, 2);
  assert.deepEqual(report.includes.map((i) => [i.include, i.status]), [
    ['NMACD_BT2_DecisionCore.mqh', 'copied'],
    ['QOS_MA_Ribbon_12_21_Core.mqh', 'copied'],
  ]);
  assert.ok(fs.existsSync(path.join(out, 'QOS_MA_Ribbon_12_21_Core.mqh')), 'nested include copied');
  assert.equal(report.source.eol, 'CRLF');
});

test('UTF-16LE (MetaEditor Unicode) sources are patched and written back as UTF-16LE', () => {
  const dir = tmpdir();
  const { file, sha } = writeFixture(dir, FIXTURE, 'utf16le', true);
  const { outPath } = patcher.run(['--src', file, '--out-dir', path.join(dir, 'out'), '--expect-sha256', sha]);
  const bytes = fs.readFileSync(outPath);
  assert.deepEqual([bytes[0], bytes[1]], [0xff, 0xfe]);
  assert.ok(src.decodeSource(bytes).text.includes('bsb_sbs_conditional=%d'));
});

test('refuses an unverified source hash', () => {
  const dir = tmpdir();
  const { file } = writeFixture(dir);
  assert.throws(() => patcher.run(['--src', file, '--out-dir', path.join(dir, 'out')]), /not a known checkpoint/);
});

test('refuses a non-empty output directory', () => {
  const dir = tmpdir();
  const { file, sha } = writeFixture(dir);
  const out = path.join(dir, 'out');
  fs.mkdirSync(out);
  fs.writeFileSync(path.join(out, 'keep.txt'), 'x');
  assert.throws(() => patcher.run(['--src', file, '--out-dir', out, '--expect-sha256', sha]), /not empty/);
});

test('refuses when the literal appears more than once', () => {
  const dir = tmpdir();
  const text = FIXTURE.replace('   return INIT_SUCCEEDED;', '   Print(StringFormat("bsb_sbs_conditional=1 x=%d",1));\r\n   return INIT_SUCCEEDED;');
  const { file, sha } = writeFixture(dir, text);
  assert.throws(() => patcher.run(['--src', file, '--out-dir', path.join(dir, 'out'), '--expect-sha256', sha]), /exactly 1/);
});

test('refuses when the input is not declared (wrong source)', () => {
  const dir = tmpdir();
  const { file, sha } = writeFixture(dir, FIXTURE.replace('input bool   InpUseConditionalBsbSbsH4Extreme=false;', ''));
  assert.throws(() => patcher.run(['--src', file, '--out-dir', path.join(dir, 'out'), '--expect-sha256', sha]), /not found/);
});

test('refuses to re-patch an already patched file', () => {
  const dir = tmpdir();
  const { file, sha } = writeFixture(dir);
  const { outPath, report } = patcher.run(['--src', file, '--out-dir', path.join(dir, 'a'), '--expect-sha256', sha]);
  assert.throws(() => patcher.run(['--src', outPath, '--out-dir', path.join(dir, 'b'), '--expect-sha256', report.output.sha256]), /exactly 1/);
});

test('refuses when another specifier sits between the H4 value and the literal', () => {
  const dir = tmpdir();
  const text = FIXTURE
    .replace('h4_zero_added_delay=%d bbb_sss_fresh=1', 'h4_zero_added_delay=%d extra=%d bbb_sss_fresh=1')
    .replace('                               InpH4TransitionExtremeLevel,', '                               InpH4TransitionExtremeClosedBars,\r\n                               InpH4TransitionExtremeLevel,');
  const { file, sha } = writeFixture(dir, text);
  assert.equal(src.formatAudit(text).mismatches.length, 0, 'fixture variant itself must be aligned');
  assert.throws(() => patcher.run(['--src', file, '--out-dir', path.join(dir, 'out'), '--expect-sha256', sha]), /consumes argument/);
});

test('callsite audit finds inputs, M3 clock code (not comments/strings) and entry routes', () => {
  const dir = tmpdir();
  const { file } = writeFixture(dir);
  const r = callsites.audit(file);
  assert.equal(r.inputs.count, 15);
  const m3 = r.m3_clock_dependencies.filter((d) => d.pattern === 'PERIOD_M3');
  assert.deepEqual(m3.map((d) => d.function), ['UpdateFakeSignalCleanupTimeouts', 'OnInit']);
  assert.deepEqual(r.entry_route_functions.ExecuteAutoTradeIfNeeded.call_sites.map((c) => c.from), ['ExecutePendingH1PermissionLeg1', 'ManageBar']);
  assert.equal(r.route_switch_references.InpUseArtifactCanonicalContract.length, 3);
  assert.equal(r.format_alignment.mismatches.length, 0);
});
