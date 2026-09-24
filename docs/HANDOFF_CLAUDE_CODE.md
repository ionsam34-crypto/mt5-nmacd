# Handoff: NMACD BT2 / Quant OS EA (continue in Claude Code on the trading PC)

Prepared 2026-09-24 by the cloud Claude Code session. This is a continuation
checkpoint, **not** a live-trading approval. It extends the 2026-09-23 evidence
recovery handoff, which still governs. Read that one too; it's at section 2.3
below or in the user's chat history.

## 0. Rules (from the user and the earlier handoff, all still binding)

- **Goal:** a smaller, understandable EA with only the mechanisms it needs,
  improved using existing evidence.
- **Evidence first:** use saved evidence before asking for new backtests. No
  broad optimization or delay sweeps.
- **One mechanism per change.** Before each change, state what changes and what
  must stay identical, then get the user's approval.
- **Never promise profitability.** Never call the EA cleaned up, finished,
  Stage 8 closed, or ready for live money.
- **Don't touch production:** the terminal
  `C:\Users\shevi\AppData\Roaming\MetaQuotes\Terminal\37DFD387E83142603765C3D8E280A1B5`
  and the live Weekly/M60 EA. Don't stop terminals or change live settings.
- **Don't edit frozen sources** (the source or EX5 used by an active tester
  batch). Check that batch's status first.
- **Delete nothing:** no user files, tester history, logs or datasets.
- **User decision (approved):** keep the tested entry behaviour. The first leg
  can come from the H1 permission dot **or** from a valid M3 signal under
  existing H1 permission, and M3 adds stay as they are. Don't introduce an
  "H1-only first entry" rule during cleanup.
- **Secrets:** the EA has `InpTelegramBotToken` / `InpTelegramChatId` inputs, and
  recovered JSONs list "all loaded inputs". Remove tokens and chat IDs before
  pushing anything to GitHub.

## 1. Where things are

### 1.1 GitHub (cloud work)

- Repo: `ionsam34-crypto/mt5-nmacd`. Branch `claude/awesome-goodall-6krq2e`,
  draft PR **#2**, not merged.
- Pull it into a working folder that is **not** inside the MT5 data folder or
  the frozen candidate tree, for example `C:\Users\shevi\Downloads\mt5-nmacd`.

| Path | What it is | Status |
|---|---|---|
| `tools/mql5_static/patch_bsb_conditional_telemetry.cjs` | Fixes the false `bsb_sbs_conditional=1` log value (handoff §5B). Hash-locked to Stage 8 `2CBEDDB3…F9F91` / Stage 7 `F886950C…1E64`; writes a new `*_TELEMFIX1.mq5`; proves alignment. | 13 Node tests pass; **not yet run on the real source** |
| `tools/mql5_static/callsite_audit.cjs` | Read-only map: input count, M3-clock dependencies with enclosing functions, entry-route callers, routing-switch references, format/argument alignment. | tested on a fixture only |
| `tools/mql5_static/README.md` | Exact PowerShell commands for the two tools above | – |
| `tools/audit_review.py`, `tools/nmacd_stats.py` | Standard-library Python review of the EA's audit CSVs: by cell, class, exit reason, hour, month, stack depth and news window, plus a Deflated Sharpe "skill vs luck" verdict | 9 tests pass |
| `tools/basket_montecarlo.py` | Monte Carlo (GARCH-t gold at 30% volatility, trend regimes, basket mechanics, guards). The `audit` subcommand block-bootstraps real audit CSVs. | 8 tests pass |
| `mql5/Include/NMACD_BT2_GoldGuards.mqh` | Account-level guards: basket stop, daily loss, equity-drawdown halt, lot cap, spread vs median, rollover window, news blackout | **not compiled; behaviour change; not approved** |
| `mql5/Scripts/NMACD_ExportNewsCalendar.mq5` | Exports the MT5 calendar to CSV for tester news filtering | not compiled |
| `docs/GOLD_FIX_PLAN.md` | §0 scope/lineage, hook points (written for **v2.06 production lineage**, not Stage 8), leverage sizing, validation protocol, simulation results | – |

Tests: `node --test tools/mql5_static/mql5_static.test.cjs` and
`python -m unittest discover -s tools/tests`.

### 1.2 Trading PC (not in GitHub)

- Stage 8 candidate (current continuation lineage):
  `C:\Users\shevi\Downloads\djfaslbj;fvb\nmacd_continuation\candidate_stage2_stacking\stage8_ma_ribbon\source\NMACD_BT2_QOS_SKELETON_STAGE8_MA_RIBBON_20260922.mq5`
  - SHA-256 `2CBEDDB3ACE23F4C5AE3BC05542E01083EE1731FDFE6399940FA9CAC3FCE9F91`
  - last EX5 hash `5AA574DCD2E4514AB0213AFE596909C1A82914D9072CBD7314E4E830F056DD36`
  - 296 inputs; includes `NMACD_BT2_DecisionCore.mqh`,
    `QOS_MA_Ribbon_12_21_Core.mqh`, `QOS_ZigZag_Universal_Core.mqh`
- Stage 7 reference: `…\stage7_transition_m3exit\source\NMACD_BT2_QOS_SKELETON_STAGE7_TRANSITION_M3EXIT_20260922.mq5` (`F886950C…1E64`)
- Evidence recovery R2 (read first):
  `C:\Users\shevi\Downloads\AMD\mt5_nmacd_bt2_port\artifacts\evidence_recovery_20260923_r2\`
  - `summary.json`, `run_index.csv`, `entry_stack_reconciliation.json`, and per-run JSONs
- Offline JS evidence tools (14 tests): `C:\Users\shevi\Downloads\AMD\mt5_nmacd_bt2_port\tools\quant_evidence\`
- Active or recent batch **`STAGE8_CLOSURE_20260923_R3`**:
  `…\candidate_stage2_stacking\runs\STAGE8_CLOSURE_20260923_R3`
  - Runner: `tools\run_stage8_closure.ps1`; validator: `tools\validate_stage8_closure.cjs`
  - Portable terminal: `runtime\MT5_STAGE2_STACKING\terminal64.exe`
- Lineages are separate. Don't swap between:
  - production Weekly/M60 (`NMACD_BT2_WEEKLY_REGIME_GATE_SMA6_M60_2Y_20260827C`, v2.06)
  - the root AMD `NMACD_BT2_MT5_Strategy.mq5` (M45/RC5)
  - the Quant OS Stage 7/8 candidates

### 1.3 The 2026-09-23 evidence-recovery handoff

The user has the full text. Key facts:

- **R2 results:** 95 runs inspected. 89 reconciled, 5 conflicts, 1 blocked.
  - Conflicts: the S11/S12 March 28 vs April 1 end boundary (4 runs), and `S8B2_AUG24_MOTHER_H4`.
  - Blocked: `S8_MAY24_BASELINE` has no HTML report.
- **Baseline vs L2C** differ in exactly `InpAllowShort` and
  `InpUseConditionalBsbSbsH4Extreme`.
  - Headline net: 8 improvements, 5 ties, no deterioration.
  - The 13 windows overlap and cover only 12 unique months of 2024; they aren't independent.
- **Tested entry routes:** S7 May had 24 H1-route first entries, 106 M3-route first entries and 49 adds.
- **Permission timeframe:** `InpRegimeTimeframe` uses the custom enum
  `ENUM_NMACD_REGIME_TF` (0=M15, 1=H1, 2=H2, 3=H3, 4=H4), not `ENUM_TIMEFRAMES`.
- **M3 lock-in:** `g_wrong_trading_period=(period!=PERIOD_M3)` still forces M3,
  and there are more M3-clock dependencies. Native timeframe support needs a full design.
- **Tester end:** a native tester "end of test" close explains the one-deal
  difference. Don't add unconditional closes in `OnDeinit`.
- **Older OOS failure:** an earlier out-of-sample failure exists for another
  configuration. Locate the binding OOS evidence before any readiness claim.

## 2. Findings from the cloud session (don't re-derive)

1. **Size, not signal, decides survival.** The simulation ran 57,000 synthetic
   years at 30% gold volatility with spread and swap. With no stops on $1k, a
   28-leg stack was ruined in 72–93% of years, even with a signal right 75% of
   the time. On $10k with guards, more legs *lowered* the median return even
   with a real edge: at 70% accuracy, 3 legs gave +75% and 18 legs +18%. Rule:
   full-stack leverage ≤ ~1×, so max legs ≈ balance ÷ gold price. That's 2 legs
   on $10k, and the certified 28-leg cap needs about $120k. The L2C research
   used $10k and 28 legs.
2. **Guards prevent ruin, not losses.** With no edge, years end around −20% and
   halted instead of wiped out.
3. **A realistic edge still loses often.** With a 60%-accurate signal and
   correct sizing: 68% of years profitable, median $10k → $12.3k, about 4 of 12
   months losing, and the 10th percentile ends at $7.1k.
4. **Caveat:** these results use a stand-in signal. Only the `audit` bootstrap on
   **real** audit CSVs speaks for NMACD itself.
5. **Dead or inactive code** observed in the v2.06 production source. It was
   **not removed**; prove dependencies first, then change one thing at a time:
   - legacy M60 delay cells (inert under the no-delay contract; consistent with
     S9 equal metrics)
   - the PB3 path
   - CTX-2
   - the Option-C D1×H4 matrix
   - the confirmed-H1 override
   - the session-aware override body
   - always-false snapshot fields and pass-through `Effective*()` helpers
   - per-bar handle creation in `BuildTrendContext`
6. **Contradictions** found in v2.06; they may exist in Stage 8 too:
   - `InpUseH1ExtremeQualification`: the comment says "reverted to true" but the value is false.
   - The dashboard says "Minor Countercycle… PERMANENTLY ENABLED" while the policy is BLOCK.
   - The legacy config lock expects values different from the defaults.

## 3. Next actions, in order (stop for approval where marked)

1. **Check R3 status** from the filesystem and process list. Don't launch a
   duplicate. If it's still running, stop here and work on offline items only.
2. **Read R2** `summary.json` and `entry_stack_reconciliation.json`.
3. **Run the read-only callsite audit** on the exact Stage 8 checkpoint and save
   the output next to it (commands in `tools/mql5_static/README.md`).
   Re-locate the handoff's line hints from its output:
   - `BuildStackAdmissionContext`, `StackAdmissionAllowsNextLeg`,
     `ExecuteAutoTradeIfNeeded`, `EffectiveMaxStackedPositionsForState`
   - the H1 leg-1 path
   - the M3-clock sites
4. **Telemetry fix** (handoff §5B). This is telemetry only, but confirm with the
   user before making it:
   - Only after R3 is finished and preserved.
   - Run `patch_bsb_conditional_telemetry.cjs --copy-includes` into a new
     candidate folder.
   - Compile in MetaEditor with 0 errors and 0 warnings, and record the new EX5 hash.
   - Update the problem board.
5. **Evidence on real trades, with no new backtests:**
   - Run `python tools/audit_review.py` and
     `python tools/basket_montecarlo.py audit <csvs> --start-equity 10000` on the
     Stage 7 / L2C audit CSVs.
   - Report worst cases and the Deflated Sharpe with an honest trial count.
   - Check first that the audit CSV header matches the columns `nmacd_stats.load_audit` expects.
6. **Behaviour-preserving entry/stacking cleanup** (handoff §8, priority 2):
   - Propose it to the user and **get approval** first.
   - Route H1 first entries, M3 first entries and M3 adds through **one shared
     admission gate**, keeping decisions identical.
   - Prove parity by comparing the recovered route counts (for example S7 May
     24/106/49) with a replay or a narrowly scoped test, and only if saved
     evidence can't answer.
7. **Proposals only; each needs separate approval and its own evidence:**
   - adopt guards one at a time (drawdown halt → daily loss → basket stop → spread → rollover → news)
   - leverage-based stack cap
   - runtime evidence for the conditional H4 gate
   - native timeframe support (priority 3)
   - dead-code removal with identical-trades proof

## 4. Evidence gate for every EA change

1. Confirm the lineage, the user's approval, and that no frozen batch is using the file.
2. Checkpoint the source, includes, EX5 and configuration with hashes.
3. State one change and what must stay identical.
4. Make the smallest candidate-only edit, in a new folder with a new name suffix.
5. Compile with 0 errors and 0 warnings, and record the new EX5 hash.
6. Run static, unit and offline evidence checks first.
7. Run a narrowly scoped tester run only if saved evidence can't answer the question.
8. Save the report, logs, inputs and hashes.
9. Update the problem board as done / uncertain / blocked / not tested.
10. No deployment without explicit approval and a separate readiness gate.

## 5. Useful links (the user's private pages)

- Blueprint: what was done, target design, correct behaviour, a realistic year: https://claude.ai/artifact/RnnBPD5pH5N5g4qDhNfXo2
- Strategy explainer and simulation: https://claude.ai/artifact/WGLdBsHWCik2aHSaqVDGhZ
- Gold EA review: https://claude.ai/artifact/NhZpAwRBw2nnH48793Pe1n
- What actually works (research): https://claude.ai/artifact/FA66QXkzRGBiFTR9feaopK
