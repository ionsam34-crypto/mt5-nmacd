# Final EA: merge plan and loss review

Prepared 2026-09-25 from the v2.06 source the owner pasted
(`WEEKLY_REGIME_GATE_SMA6_M60_2Y_20260827C`, 12,143 lines, 290 inputs).
The Stage 1–8 sources, `NMACD_BT2_DecisionCore.mqh` and the indicator sources
are **not** in this repo yet, so none of this has been compiled or tested.
None of it is a promise of profit.

## 1. Why the EA loses big: what the code itself records

These come from the EA's own comments and config, not from new tests.

| # | Finding | Where in v2.06 |
|---|---|---|
| L1 | Up to **28 legs** per basket, added on every same-side M3 signal with **no spacing** (`InpMinBarsBetweenStackEntries=0`, `InpMinStackSpacingAtr=0`). Legs pile into one top or bottom. | `InpMaxStackedPositions=28`, Execution group |
| L2 | **No per-leg stop, and the equity kill switch is retired** (`InpUseCatastrophicStop=false`, `InpMaxEquityDrawdownPct=0.0`). | Trade Management and Safety groups |
| L3 | A June 2026 out-of-sample run lost **96.77% in 5 days** with 10 stacked longs while D1 lagged. The router build tested **1 pass / 4 fail** out of sample, with two drawdowns near 95%. | comments on `InpContinuationMaxStackedPositions` and `InpUseStateAwareRouter` |
| L4 | The six D1×H4×H1 entry cells **change sign between market regimes** (e.g. ESBS −$888 in the uptrend sample, +$2,541 in the downtrend sample). That is the signature of fitting to the sample, not a stable edge. | comment above `InpAllowCellESBB` |
| L5 | Trading against the weekly SMA6 slope isolated a subset with **profit factor 0.49** (about $2 lost per $1 won), while keeping 89% of gross profit. | comment on `InpUseWeeklyRegimeGate` |
| L6 | The basket profit trail gives back **95%** of peak profit before closing, so it protects almost nothing. | `InpBasketTrailGivebackPct=95.0` |
| L7 | **Two config locks disagree.** `VerifyArtifactCanonicalConfig` expects the weekly gate, BSB/SBS extreme and canonical D1 structure ON, and the basket trail, six-leg stall and session flatten OFF. The input defaults are the opposite on 9 of these. `VerifyCertifiedConfig` expects the CTX-1 matrix OFF, but its default is ON. So what actually trades depends on which `.set` file was loaded. | both `Verify*Config` functions |

## 2. Recommendations, most important first

Each is **one change, tested alone**, per the project rule.

1. **Cap the risk before touching signals.** Limit the stack (start with 3–5 legs,
   not 28), and add a basket stop and daily loss halt from `NMACD_BT2_GoldGuards.mqh`.
   The earlier Monte Carlo showed a 28-leg stack with no stop ruins a $1k account
   in 72–93% of simulated years, even with a real edge. This is the largest lever.
2. **Fewer higher timeframes, not more.** Keep one macro direction filter: the
   **weekly SMA6 slope**, which is the only layer with measured independent
   information (L5). The code notes that D1 is perfectly collinear with trade
   direction under directional admission, so it adds nothing as a second filter.
   Demote H4 from admission and cells to **logging only**. That reduces six
   cells to two directions (buy only with weekly up, sell only with weekly down).
   Fewer switches means less fitting, which is what makes results consistent.
3. **Don't block cells from one window.** No cell is negative in both regime
   samples; EBSB is the only one positive in both. With samples this short,
   per-cell blocking is noise. If step 2 is adopted, the cell question mostly
   goes away. If cells stay, judge each one on the full period with the Deflated
   Sharpe tool (`tools/audit_review.py`), not a single window.
4. **Exits: pick "fast" or "honest", and measure it.** The no-delay contract
   (`M60_NO_DELAY_EXIT_CONTRACT=true`) already forces one observation, so the
   16 per-cell delay inputs and the CTX-1 matrix are **inert** and should be
   deleted in the final EA. But "no delay" here means the EA acts on the dot of
   the **still-forming** M60 bucket (`require_source_close=false` in
   `VISUAL_EARLY`). If that dot can disappear before the hour closes, the EA
   exits on a signal the finished chart no longer shows. That makes live,
   backtest and chart disagree.
   - Add telemetry that records every forming dot that later vanishes.
   - If vanishing is common, switch to the closed M60 bar. That costs up to 60 minutes but never repaints.
5. **Make re-entry simple.** After an M60 exit, the same side stays locked
   until an M60 "reset" dot in the H1 direction appears, or for up to 160 M3
   bars (8 hours) (`InpM60ReentryLockTimeoutBars`). This, plus the basket-trail
   H1-flip lock, is the most likely reason cells look like they "don't cycle".
   Log each lock start, unlock and reason, then decide whether the lock earns
   its keep.
6. **One configuration.** The final EA gets a single config lock whose values
   equal the input defaults, so loading no `.set` file gives the approved system.

The one remaining unavoidable delay is the M3 host bar: exits are evaluated
on each closed M3 bar, so a dot is acted on up to 3 minutes after it appears.
Acting mid-bar would bring back repainting.

## 3. Final EA architecture

```
W1  SMA6 slope ........ direction filter (closed weekly bars only)
H1  NMACD regime dot .. permission cycle; confirmed dot opens leg 1
M3  NMACD entry model . adds legs in the H1 direction (capped, spaced)
M60 NMACD regime dot .. sole normal exit (no per-cell delays)
Guards ................ basket stop, daily loss, equity halt, spread,
                        rollover, news, lot cap (veto / flatten only)
D1, H4 ................ logged and drawn, not used for decisions
```

Modules (one `.mqh` each, so the main file stays small):

| Module | Kept from v2.06 | Changed |
|---|---|---|
| `Core` (signals) | NMACD entry model, lobe reset, H1/M60 dot readers, closed-bar handling | forming-vs-closed M60 choice made explicit; repaint telemetry |
| `Router` | H1 permission cycle, leg-1 on H1 dot, same-side stacking | weekly-slope admission; H4/D1 cells become log fields; 28 → capped and spaced |
| `Exit` | M60 dot exit, failed-exit retry, session flatten | delete the 16 delay inputs, CTX-1 matrix, pre-arm, PB3, CTX-2, H1 override research code |
| `Guards` | — | `NMACD_BT2_GoldGuards.mqh` from this PR |
| `Telegram` | outbound photo alerts (`sendPhoto`, extra recipients, cooldown, timeout); inbound `/status` and notes only; never runs in the Tester | unchanged behaviour; add a daily heartbeat and guard-trip alerts |
| `Visuals` | six-pane layout, regime dashboard, trade boxes, entry/exit markers, H1 scanner context panel | dashboard gains guard state, weekly slope, open legs vs cap, last exit reason |
| `Telemetry` | trade audit CSV, lifecycle log, config fingerprint | add repaint and re-entry-lock events |
| `Config` | config lock | one lock, defaults equal to the lock |

Telegram tokens and chat IDs stay **inputs only**, empty by default, and are
never committed.

## 4. Missing pieces worth adding

- A risk layer at all (L2). Nothing in v2.06 limits a single bad basket.
- Position size tied to balance (about one 0.01 leg per $4,300 of balance, per `GOLD_FIX_PLAN.md` §3) instead of a fixed 0.01 × 28.
- Restart safety: rebuild the H1 cycle, locks and guard state after a terminal restart (`RestoreH1PermissionCycleFromHistory` covers only the H1 cycle).
- A news blackout and a spread-spike guard (in the guards include).
- A broker-symbol check (the code mentions `XAUUSD_i` on one broker and Headway on another).
- Repaint and lock telemetry (§2 items 4 and 5), so behaviour can be verified, not guessed.

## 5. What's needed from the trading PC to build it

Put these in the repo (remove any bot token or chat ID first):

1. The Stage 1–8 `.mq5` sources, plus one line per stage saying which mechanism it added and whether it was approved.
2. `NMACD_BT2_DecisionCore.mqh` and every other include.
3. Indicator sources:
   - `NMACD_BT2_HTF_Regime_Visual.mq5`
   - `NMACD_BT2_Weekly_SMA6_Gate_Visual.mq5`
   - the entry-model and M60 custom indicators
4. The `.set` or `.ini` actually used on the terminal.

With those, the merged EA can be written here module by module. Compiling,
and the short "does it plot trades as intended" runs, still happen in MetaEditor
and the Strategy Tester on the trading PC.
