# MQL5 static tools (offline, no dependencies)

Node ≥ 18. Nothing here compiles MQL5, runs MT5, or edits a file in place.
MetaEditor remains the authority on whether code builds.

| Tool | What it does | Writes |
|---|---|---|
| `patch_bsb_conditional_telemetry.cjs` | Handoff §5B fix: makes `artifact_canonical_contract` print the **real** `InpUseConditionalBsbSbsH4Extreme` value instead of the literal `bsb_sbs_conditional=1`. Telemetry only. | A **new** `.mq5` + `patch_report.json` in an empty folder; `--copy-includes` also copies quoted `#include` files, following nested includes, with their hashes |
| `callsite_audit.cjs` | Read-only map for handoff §8 priorities 2–3: input count, every M3-clock dependency with its enclosing function, entry-route functions and callers, routing-switch references, and whole-file format/argument alignment. | Optional JSON (refuses overwrite) |
| `mql5_source.cjs` | Shared reader: UTF-16LE/UTF-8(BOM) decoding with byte-compatible write-back, tokenizer, `StringFormat`/`PrintFormat` argument splitter, specifier counter. | – |

Tests: `node --test tools/mql5_static/mql5_static.test.cjs` (13 tests; fixture copies the
v2.06 `artifact_canonical_contract` call, which has the same defect as Stages 7/8).

## Applying the telemetry fix (on the trading PC)

Follow the handoff's evidence gate. **Only after** `STAGE8_CLOSURE_20260923_R3` has
finished and its reports are preserved, since the batch's source and EX5 are frozen:

```powershell
$base = 'C:\Users\shevi\Downloads\djfaslbj;fvb\nmacd_continuation\candidate_stage2_stacking\stage8_ma_ribbon'

# 1. Read-only map of the exact checkpoint (keep it with the checkpoint)
node tools\mql5_static\callsite_audit.cjs --src "$base\source\NMACD_BT2_QOS_SKELETON_STAGE8_MA_RIBBON_20260922.mq5" --json "$base\callsite_audit_2CBEDDB3.json"

# 2. Patch into a NEW folder (refuses unless the source hash is 2CBEDDB3…F9F91)
node tools\mql5_static\patch_bsb_conditional_telemetry.cjs `
  --src "$base\source\NMACD_BT2_QOS_SKELETON_STAGE8_MA_RIBBON_20260922.mq5" `
  --out-dir "$base\candidate_telemfix1" --copy-includes
```

The tool refuses and changes nothing if any of these hold:
- the source hash isn't the Stage 8 or Stage 7 checkpoint from the handoff (or `--expect-sha256`);
- the output folder isn't empty;
- `bsb_sbs_conditional=1` doesn't appear exactly once inside a `StringFormat` literal;
- `input bool InpUseConditionalBsbSbsH4Extreme` isn't declared;
- the call is already misaligned, or the new `%d` wouldn't consume the new argument.

After a successful run:
- the original's hash is re-checked to prove it's unchanged;
- the report shows the diff, the alignment count before and after (for example 17/17 → 18/18), and a whole-file format audit before and after.

Then, per the handoff:
1. Compile `…_TELEMFIX1.mq5` in MetaEditor: **0 errors, 0 warnings**.
2. Record the **new** `.ex5` SHA-256. Never reuse `5AA574DC…`.
3. Don't point the frozen R3 batch at it.
4. A tester run isn't needed to review this change. Runtime evidence for the gate
   (qualified / blocked / data-unavailable) is a separate, later change that
   needs its own approval.

Output file names get a `_TELEMFIX1` suffix so the new binary can't be confused with
the frozen one by program name.
