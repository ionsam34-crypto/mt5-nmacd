# Smart Kill Switch — Research & Design
**Date:** 2026-08-15  
**Status:** Design phase — implementation pending Step 0 Section 1a sweep results  
**Symbol:** XAUUSD (strategy symbol-agnostic by design — parameters fine-tuned for XAU)  
**Chart TF:** 3-minute  
**Regime TF:** 1-hour

---

## Problem Statement

The existing strategy catches trend moves measured by NMACD transitions (red→blue / blue→red) on a 3M chart inside a 1H regime. The problem:

> Occasionally price reaches a mean-reversal point BEFORE the NMACD signal changes, wiping accumulated profit. The kill switch must protect profit at the confirmed peak of the move without interfering with trades that are simply in temporary drawdown and still inside a valid regime leg.

---

## Why 1H Pivot Structure?

The 3M chart generates frequent HH/HL/LH/LL swings that are noise at the regime level. The 1H chart's pivot structure identifies the structural turning points that the strategy is actually designed to trade. Using 1H pivots as the arm trigger means:

- The kill switch only activates when a *structural* peak or trough has been confirmed — not every 3M micro-swing
- This is consistent with the entry logic (regime is assessed on 1H, execution is on 3M)
- It avoids premature exits during normal 3M chop within an intact 1H trend leg

---

## Pivot Definitions

```
On the 1H chart, rolling over N bars (recommended start: 5 bars each side):

HH (Higher High): H1 high > previous confirmed swing high
HL (Higher Low):  H1 low  > previous confirmed swing low
LH (Lower High):  H1 high < previous confirmed swing high  
LL (Lower Low):   H1 low  < previous confirmed swing low

Uptrend:   sequence of HH + HL
Downtrend: sequence of LL + LH
Chop:      mixed / no clear directional sequence
```

**Confirmation rule (recommended):** A swing extreme is only confirmed when an H1 bar *closes* beyond the prior extreme (not just wicks through it). This reduces false triggers on the 3M chart.

---

## Kill Switch State Machine (per open position / ticket)

```
State 0: DISARMED
  - Default state at entry
  - Kill switch cannot fire
  - Normal trade management applies (NMACD exit signal, manual close, etc.)

  Transition to State 1:
    BUY position: 1H bar closes above the most recent confirmed swing HH
    SELL position: 1H bar closes below the most recent confirmed swing LL

State 1: ARMED
  - Peak/trough confirmed
  - Arm reference price = confirmed HH (for BUY) or confirmed LL (for SELL)
  - Trigger price calculated: entry + (arm_price - entry) * (1 - threshold%)
    Example (BUY, 50% threshold):
      entry = 2700, arm_price (HH) = 2750
      leg = 2750 - 2700 = 50 points
      trigger = 2750 - (50 * 0.50) = 2725

  Trigger condition:
    BUY:  bid price < trigger price → CLOSE POSITION
    SELL: ask price > trigger price → CLOSE POSITION

State 2: FIRED
  - Position closed by kill switch
  - Log: timestamp, entry price, arm price, trigger price, close price, PnL
  - Reset to DISARMED (position is closed)
  - No re-entry on same swing leg — wait for new NMACD signal
```

---

## Threshold Sweep Plan

Run against the accepted bundle (Pullback 28 / Continuation 30 / Transition 30):

| Threshold | Expected Behavior |
|---|---|
| 20% | Very tight — fires often, likely cuts many profitable trades early |
| 30% | Tighter but may preserve more winners than 20% |
| 40% | Moderate — candidate range |
| 50% | Owner's initial estimate — middle ground |
| 60% | Looser — allows more retracement before firing |
| 75% | Very loose — approaches "almost full retracement" territory |

**Selection criterion:** The threshold where the kill switch never causes a catastrophic outcome anywhere in the test data, at the minimum cost to net profit. NOT the highest net profit — the best worst-case bound.

---

## Multi-Timeframe Implementation in MT5

```mql5
// H1 pivot detection on 3M chart — pseudocode

int pivot_bars = 5;  // bars each side for swing confirmation

double GetH1SwingHigh(string symbol, int lookback_bars) {
    double h1_highs[];
    CopyHigh(symbol, PERIOD_H1, 1, lookback_bars + pivot_bars + 1, h1_highs);
    // Find pivot high: bar where high > all pivot_bars to its left and right
    // Return most recent confirmed pivot high
}

double GetH1SwingLow(string symbol, int lookback_bars) {
    double h1_lows[];
    CopyLow(symbol, PERIOD_H1, 1, lookback_bars + pivot_bars + 1, h1_lows);
    // Find pivot low: bar where low < all pivot_bars to its left and right
    // Return most recent confirmed pivot low
}

// On each new H1 bar close (detected via iTime comparison):
//   Update swing registry
//   Check each open position's arm condition
//   If newly armed: calculate trigger price, store on ticket
//   Log arm event

// On each 3M tick:
//   For each armed position: check if trigger price hit
//   If hit: close position, log kill switch fire event
```

---

## On-Chart Dashboard Specification

**Implementation:** MT5 object labels via `ObjectCreate()` in the EA, updated in `OnTick()`.

**Panel contents:**

```
┌─────────────────────────────────┐
│  NMACD STRATEGY — XAU/USD 3M    │
├─────────────────────────────────┤
│  1H Regime:    UPTREND  ▲       │
│  NMACD State:  BLUE     ●       │
│  Spread:       1.2 pts  ✓       │
├─────────────────────────────────┤
│  KILL SWITCH                    │
│  Ticket #001: ARMED             │
│    Entry:     2700.00           │
│    Arm (HH):  2750.00           │
│    Trigger:   2725.00  (-25pts) │
│  Ticket #002: DISARMED          │
│  Ticket #003: DISARMED          │
├─────────────────────────────────┤
│  Equity:      $11,450.22        │
│  Session P/L: +$820.15          │
└─────────────────────────────────┘
```

**Notes:**
- Panel position: top-right corner, does not overlap price action
- Color coding: ARMED = amber, DISARMED = grey, FIRED = red flash then clear
- Updates on every tick (not just on bar close) so trigger price proximity is visible in real time

---

## Symbol-Agnostic Design Notes

The strategy should work on any symbol the EA is attached to. Parameters are fine-tuned for XAUUSD but the logic must not hardcode the symbol.

**Required changes to make it symbol-agnostic:**
- Replace any hardcoded "XAUUSD" string with `Symbol()` or `_Symbol`
- Replace hardcoded tick size / tick value with `SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_SIZE)` etc.
- Spread guard: 500-point threshold is XAUUSD-calibrated — expose as input parameter so it can be adjusted per symbol
- Pivot lookback: expose as input parameter
- Kill switch threshold %: expose as input parameter

**Runtime behavior:** EA runs on whatever chart it is attached to. XAUUSD-specific parameter sets are loaded via the `.set` file — other symbols get their own `.set` files.

---

## Position Sizing Test Sequence (Owner direction)

**Precondition:** Kill switch proven to work (Step 0 + Step 1 complete)

```
Block 1 (3 windows):  0.01 lot each
Block 2 (3 windows):  0.02 lot each
Block 3 (3 windows):  0.03 lot each
...continue incrementing by 0.01 per 3-window block...
Stop condition: account blown OR max drawdown reaches initial capital
Record: lot size at which catastrophic drawdown first occurs → this becomes the sizing ceiling
```

---

## Emergency Stop — Drawdown Data Collection Plan

From all completed cell tests, collect per-cell:
- Average drawdown in uptrend regime
- Average drawdown in downtrend regime  
- Average drawdown in chop regime
- Max single-drawdown observed per cell

Cross-reference to find the drawdown level at which no historical test has ever shown recovery. That level is the rational emergency stop threshold — not a round number, not an arbitrary percentage.

**Rationale (owner stated):** The strategy works. Trades that enter drawdown then recover to profit must not be closed by an overly tight stop. The stop is only justified at a level where data shows there is no historical precedent for recovery.
