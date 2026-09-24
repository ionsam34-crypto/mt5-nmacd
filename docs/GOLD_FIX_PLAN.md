# NMACD BT2 on gold: risk fix and honest validation

This covers two things:

1. **Survival**: `mql5/Include/NMACD_BT2_GoldGuards.mqh` adds account-level loss
   limits, a relative spread guard, a rollover window and a news blackout. None
   of these existed in v2.06: `InpUseCatastrophicStop=false`,
   `InpMaxEquityDrawdownPct=0.0`, and `InpMaxSpreadPoints=500` (≈ $5 on a
   2-decimal gold quote).
2. **Proof**: `tools/audit_review.py` reads the EA's own audit CSVs and reports
   whether the result is distinguishable from luck once you count how many
   configurations were tried (Deflated Sharpe Ratio).

Neither one makes the strategy profitable. The guards cap the damage when it's
wrong, and the review tells you whether it has an edge. No code change can
guarantee profit, and anyone who says otherwise is selling something.

---

## 1. Install

Copy into your MT5 data folder (`File → Open Data Folder`):

| Repo file | MT5 location |
|---|---|
| `mql5/Include/NMACD_BT2_GoldGuards.mqh` | `MQL5/Experts/<your EA folder>/` (next to `NMACD_BT2_DecisionCore.mqh`) |
| `mql5/Scripts/NMACD_ExportNewsCalendar.mq5` | `MQL5/Scripts/` |

## 2. Wire the guards into the EA (6 small edits)

These are written against the v2.06 source. The code has **not been compiled in
the cloud** (there's no MetaEditor there), so compile it and paste any error
back.

**a. Include**, directly under `#include "NMACD_BT2_DecisionCore.mqh"`:
```mql5
#include "NMACD_BT2_GoldGuards.mqh"
```

**b. OnInit**, just before the final `return INIT_SUCCEEDED;`:
```mql5
   if(!GG_Init(symbol,InpMagic,InpDeviationPoints))
      return INIT_FAILED;
```

**c. OnDeinit**, first line:
```mql5
   GG_Deinit();
```

**d. OnTick**, right after `UpdateAuditTracking();` (it must run every tick,
not only on new M3 bars):
```mql5
   GG_OnTick();
```

**e. ExecuteAutoTradeIfNeeded**, directly after the existing
`if(!g_risk.SpreadAllowed(symbol,InpMaxSpreadPoints)) { ... }` block. This
covers both the H1 leg-1 path and the M3 add path, because both call this
function:
```mql5
   string gg_reason="";
   if(!GG_EntryAllowed(EffectiveFixedVolume(),gg_reason))
     {
      g_logger.Write(MT5QE_INFO,"auto_trade_blocked",
                     StringFormat("signal_id=%s reason=%s",signal_id,gg_reason));
      LogAuditRejection(signal_id,wants_long,decision.setupGrade,
                        snapshot.marketTrendState,snapshot.closedBarTime,gg_reason);
      return;
     }
```

**f. EvaluateSignalWouldFire**, after its spread check, so the chart preview
never shows a leg the guards would refuse:
```mql5
   {
    string gg_reason="";
    if(!GG_EntryAllowed(EffectiveFixedVolume(),gg_reason))
      { reason=gg_reason; return false; }
   }
```

**Config lock (recommended).** In both `VerifyCertifiedConfig()` and
`VerifyArtifactCanonicalConfig()` add
`ConfigCheckInt("InpGG_Enable",InpGG_Enable?1:0,1,f);` and mint a new build tag
(for example `..._20260827C_GG1`) so a preset can't silently switch the guards off.

## 3. Choosing guard levels (from risk, never from optimization)

Guard levels are a statement of how much you are willing to lose. **Do not
optimize them in the Strategy Tester.** An optimized stop is just one more
fitted parameter.

The numbers that matter for gold right now (≈ $4,300, realized volatility ≈ 30%):

- A 1σ day is about **$81**; a 3σ day is about **$244**.
- Each 0.01 lot leg (100 oz contract; check `contract_size` in the
  `broker_symbol_spec` log line) moves **$1 per $1** of gold.

So the most legs a basket stop can carry through a normal (1σ) adverse day is
roughly:

```
max_legs ≈ balance × InpGG_BasketStopPctOfBalance% ÷ (daily σ in $ × $ per leg per $1)
```

| Balance | Basket stop | Legs that survive a 1σ day ($81) |
|---:|---:|---:|
| $1,000 | 15% | ~2 |
| $5,000 | 15% | ~9 |
| $10,000 | 15% | ~18 |
| $20,000 | 15% | ~37 |

**This is the core finding.** At 0.01 lot per leg, the certified 28-leg cap is
a $20k+ design. On a $1–3k account, either the stack cap comes down or the stop
gets hit on normal days. Set `InpGG_MaxTotalLots` (for example 0.05 on $5k) to
make the cap explicit.

Shipped defaults are deliberately loose "catastrophe only" levels. Tighten them
to your account before live use:

| Input | Default | Meaning |
|---|---:|---|
| `InpGG_BasketStopPctOfBalance` | 15 | flatten when floating loss ≥ 15% of balance, then 240 min cooldown |
| `InpGG_DailyLossPct` | 20 | flatten and stop for the day at −20% (realized + floating) |
| `InpGG_MaxEquityDrawdownPct` | 35 | flatten and stop until you reset it by hand (`InpGG_ResetHardHalt=true` for one reattach) |
| `InpGG_MaxTotalLots` | 0 (off) | total open lots cap |
| `InpGG_MaxSpreadPrice` | 0.80 | no new legs when spread > $0.80 |
| `InpGG_SpreadMedianMultiple` | 3.0 | no new legs when spread > 3× the rolling 4-hour median |
| `InpGG_RolloverBlockMinutes` | 10 | no new legs within ±10 min of server midnight |
| `InpGG_NewsBlockBefore/AfterMinutes` | 15 / 30 | no new legs around high-impact USD events |

The guards only **veto new legs** and **flatten on loss limits**. They never
change a signal, a cell, or the M60 exit.

## 4. News filter in the Strategy Tester

MT5's economic calendar is **not available in the Strategy Tester**. To backtest
with the news filter:

1. On a live or demo chart, run `Scripts → NMACD_ExportNewsCalendar` (defaults:
   2023-01-01 → 2026-12-31, USD, high impact). It writes
   `Common\Files\NMACD_news_high_impact.csv`.
2. Use **local** tester agents (cloud agents can't see the Common folder).
3. Check the tester journal for
   `component=GoldGuards event=news_source mode=tester_csv events=N`. If it says
   `NEWS_FILTER_INACTIVE`, the CSV wasn't found.

## 5. Validation protocol: decide before you look

Write these down **before** running anything, and don't change them afterwards.

**What's still untouched?** The build tag `WEEKLY_REGIME_GATE_SMA6_M60_2Y_20260827C`
suggests the weekly-gate study used data up to about **2026-08-27**. If that's
right, July–August 2026 has already been seen, and the only unseen data is
**2026-08-28 onward**. About 4 weeks can disprove the strategy but can't prove it.

**Step A: quick check on unseen data (2026-08-28 → today).**
Freeze the certified `.set` file plus the guards. Strategy Tester: *Every tick
based on real ticks*, your real deposit, 0.01 lot. One run only.

**Step B: forward test on demo, 8–12 weeks.** Same frozen config, demo account,
no parameter changes. This is the real test.

**Pass criteria** (all must hold, on A and B separately):

| Criterion | Threshold |
|---|---|
| Net profit after swap and commission | > 0 |
| Profit factor | ≥ 1.2 |
| Max equity drawdown (tester report, not closed P&L) | < `InpGG_MaxEquityDrawdownPct` and never hard-halted |
| Closed legs | ≥ 100 |
| Deflated Sharpe with the honest trial count | ≥ 95% |

If it fails, **don't re-tune it on the same data**. Every re-tune adds to the
trial count and uses up the remaining unseen data. That means either the
strategy has no edge in the current gold regime, or it needs a genuinely new
idea tested on data that hasn't been seen yet.

## 6. Running the review

Audit CSVs are in `Common\Files\NMACD_BT2_Telemetry\*_audit.csv` (the tester
writes them to the agent's Common folder when `InpUseCommonTelemetryFiles=true`).

```bash
python tools/audit_review.py "exports/*_audit.csv" --start-equity 1000 ^
    --news NMACD_news_high_impact.csv --n-trials 900 --trial-sharpe-std 0.05 ^
    --out review.md
```

- `--n-trials`: count every configuration you have ever backtested on this
  strategy (the 832-pass sweep alone is 832). If you have per-run Sharpe values,
  put them in a `trials.csv` with a `sharpe` column (per-day units) and pass
  `--trials trials.csv` instead of the two estimates.
- The report shows results by entry cell, trade class, exit reason, hour,
  month, stack depth, and inside vs outside news windows, plus the deflated
  verdict.

Tests: `python -m unittest discover -s tools/tests`.
