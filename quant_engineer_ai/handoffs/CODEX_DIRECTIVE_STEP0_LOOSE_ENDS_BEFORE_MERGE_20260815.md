# CODEX DIRECTIVE — STEP 0: CLOSE ALL LOOSE ENDS BEFORE MERGE
**Date:** 2026-08-15  
**Status:** ACTIVE — takes precedence over Step 1 (Production Merge). If Step 1 was started, pause it.  
**Accepted baseline (current):** $10,629.07 — Bundle: Pullback 28 / Continuation 30 / Transition 30 — Kill switch OFF  
**This directive replaces that baseline** with a new one measured at the exact configuration that will actually deploy.

---

## Required Checkpoint Format
Each section must report back:
- Action taken
- Data observed
- Decision made (or flagged as Owner decision)
- New accepted value (if baseline changes)

---

## Section 1a — Kill Switch: Establish Baseline DD + Sweep Thresholds (HIGHEST PRIORITY)

**Why this is first:**  
Every result this campaign produced — including the accepted $10,629.07 — was measured with the kill switch OFF. Enabling it may change that number. We have no per-window max-drawdown figures for the final bundle (Pullback 28 / Continuation 30 / Transition 30). Stage 3 confirmed no catastrophic wipeout pattern but never reported the actual DD numbers. Those numbers are the input to every threshold decision below.

**Steps:**

1. Re-run the accepted bundle (Pullback 28 / Continuation 30 / Transition 30) with kill switch still OFF. This time record:
   - Max drawdown per window (absolute and %)
   - Max drawdown across the full bundle
   - Gross profit / gross loss split
   - Confirm the $10,629.07 net reproduces (within rounding)

2. Sweep candidate thresholds: **20% / 30% / 40% / 50% / 60% / 75%** of peak-leg extension. For each threshold record:
   - How many times the switch would have tripped (trip count, not just whether it ever did)
   - Net profit at that threshold
   - Max drawdown at that threshold
   - Note: "best profit" is NOT the selection criterion

3. Select the threshold using the same logic used for all other parameters in this project:  
   **"Never catastrophic anywhere"** — the threshold that bounds the worst-case loss for the least cost to net profit, not the most profitable one.

4. Re-run the bundle one final time with the switch ON at the selected threshold. The result from this run **replaces $10,629.07 as the new accepted baseline**, because this is the configuration that will actually go live.

**Watch for:** If the kill switch trips frequently, it is not a safety net — it is an active change to how the strategy trades. The baseline must be re-earned, not assumed.

---

## Section 1b — Smart Kill Switch Design Specification (NEW — from owner direction 2026-08-15)

**Concept:** Trailing profit-protection trigger armed per stack entry, referenced to 1H pivot structure detected on the 3-minute chart.

### Logic Flow

```
1H PIVOT DETECTION (on 3M chart via HTF lookup):
  - Track rolling HH / HL / LH / LL on H1 bars
  - Uptrend  = HH + HL sequence
  - Downtrend = LL + LH sequence
  - Chop     = mixed / no clear sequence

ENTRY (on 3M chart, per existing NMACD signal):
  - Buy signal: NMACD switches red → blue at 1H regime uptrend low
  - Sell signal: NMACD switches blue → red at 1H regime downtrend high
  - Each stack window (Pullback / Continuation / Transition) gets its own entry price

KILL SWITCH ARM CONDITION (per entry):
  - For BUY: switch arms when price confirms a new HH (higher than previous swing high)
  - For SELL: switch arms when price confirms a new LL (lower than previous swing low)
  - "Confirmed" = 1H bar closes above/below the prior swing extreme
  - Until that confirmation: switch is disarmed — normal trade management applies

KILL SWITCH TRIGGER (per entry, once armed):
  - For BUY: close if price retraces X% of the distance from entry to confirmed HH
  - For SELL: close if price retraces X% of the distance from entry to confirmed LL
  - X = threshold selected in Section 1a sweep (candidate: 50%)
  - Each stack entry has its own arm price and its own trigger level

EXIT RESUME:
  - After kill switch fires, the position is closed
  - New entry requires a new NMACD signal — no re-entry on the same swing leg
```

### Key Design Decisions (Owner to confirm)

| Decision | Options | Note |
|---|---|---|
| Pivot lookback | N bars on H1 | Typical: 3–10 bars left/right. Start with 5. |
| Confirmation method | H1 close vs. H1 wick | Close is safer (less noise on 3M) |
| Threshold % | 50% (candidate from sweep) | Section 1a determines this |
| Scope | Only trades in profit | Kill switch never fires if entry never went green |
| Per-entry or bundle-wide | Per-entry (owner specified) | Each stack position has its own arm/trigger |

### MT5 Implementation Notes
- H1 pivots are detectable on a 3M chart using `CopyHigh(symbol, PERIOD_H1, ...)` and `CopyLow(symbol, PERIOD_H1, ...)`
- The EA must maintain a rolling pivot register (last N H1 bars) updated on each new H1 bar close
- The kill switch arm flag is per-ticket, stored in the position's internal state
- On-chart dashboard (see Section 5) should display: arm status, current trigger level, distance to trigger

### MT5 On-Chart Dashboard (Owner requested)
A small HUD panel on the chart showing:
- Current 1H regime (UPTREND / DOWNTREND / CHOP)
- Current NMACD state (BLUE / RED)
- Kill switch status per open position (ARMED / DISARMED + trigger price)
- Account equity vs. session open equity

**Feasibility:** Yes — MT5 supports `ObjectCreate(OBJECT_LABEL)` overlays driven from `OnChartEvent()` and `OnTick()`. This is standard EA HUD practice.

---

## Section 2 — Matrix Value Mismatches (Legacy)

**Two Transition-cell inputs load as 1 and 10. Config lock expects 0 and 0.**

For each mismatch:
1. Trace the value back to its source: Was it swept and selected, or inherited from an untested default?
2. If swept: show the sweep result that produced it, confirm lock value should be updated to match
3. If inherited default: treat as EBSS-class trap — run a targeted sweep and pick the right value
4. Make the source value and the lock value agree on one number

**Watch for:** Same untested-inherited-default pattern that EBSS was stuck in. A value that "came from somewhere" but can't be traced is not a decided value.

---

## Section 3 — Spread Guard

**Confirm the 500-point spread filter is active in the current build.**

1. Locate the spread-guard logic in the EA source
2. Confirm it is enabled (not commented out, not bypassed by a parameter default)
3. Report the exact parameter name and its current value in the deployed build
4. If it is off: flag as a live-trading gap to close before merge

---

## Section 4 — Broker Symbol Spec (Tester-side only — do NOT touch live terminal)

**Pull the real XAUUSD contract details from the portable tester.**

Report:
- Tick size and tick value
- Volume step (minimum lot increment)
- Stop level (minimum SL/TP distance in points)
- Filling mode (IOC / FOK / Return)
- Whether these match the assumptions baked into position sizing calculations

**Constraint:** Do not connect to or modify the live terminal. Tester-side only.

---

## Section 5 — Position Sizing (Owner decision — do not pick)

**Report what lot size every backtest actually used.**  
Then present both live-sizing options without selecting one:

| Option | Description | Implication |
|---|---|---|
| Fixed lot | Same lot size every trade regardless of equity | Predictable risk per trade; doesn't compound |
| Proportional to equity | Lot size = f(current equity) | Compounds gains and losses; drawdown % stays stable but absolute $ swings grow |

**After kill switch is proven to work, owner-directed test sequence:**
- Run 3 windows at 0.01
- Next 3 windows at 0.02
- Increase by 0.01 per 3-window block
- Continue until account blown OR max drawdown hits initial capital
- Report the lot size at which catastrophic drawdown occurs — that becomes the ceiling

---

## Section 6 — Emergency Stop Procedure Document

**A plain, written document. Exact MT5 steps only. No ambiguity.**

Contents required:
1. How to disable auto-trading in MT5 (button location, confirmation state)
2. How to close all open positions manually (sequence, confirm each closed)
3. How to confirm nothing is left open (Positions tab check)
4. How to disable the EA on the chart without closing MT5
5. Who to contact / what to log when the stop is executed

**Drawdown context for stop-level decisions:**  
Collect the average drawdown each cell experienced across uptrend / downtrend / chop regimes from all completed tests. Cross-reference to find the level at which there is no historical precedent for recovery. That level — not a round number — is the rational emergency-stop trigger.  

**Note from owner:** The strategy works. A stop-loss kill switch set too tight will close trades that are in temporary DD and would have recovered. The stop level should only be triggered at a point where historical data shows no return has ever occurred.

---

## Explicitly Excluded from Step 0

- **Swing-structure regime detector** (HH/HL/LH/LL as a standalone module) — confirmed not to exist anywhere in this project. New research, not a loose end. Parked for post-live track.
- **Two blocked Minor Countercycle cells** — parked. Not part of the pre-live path.

---

## What Comes Next (Do NOT start until Step 0 closes)

**Step 1 — Production Merge** (`CODEX_DIRECTIVE_STEP1_PRODUCTION_MERGE_20260815.md`)  
Takes every research-only value (exit delays, three stack caps, cap-freeze fix) and merges them into the file that would run a live account. Must reproduce the new accepted baseline (from Section 1a above) exactly. If it doesn't reproduce cleanly, stop — do not move forward on a merge that doesn't match.

After Step 1: Code audit → Out-of-sample test → Live readiness review.
