"""Monte Carlo risk engine for a stacking basket strategy on gold.

What this CAN tell you
----------------------
* How often a basket system with a given signal quality, stack size, account
  size and guard settings ends a year in profit, and how often it is ruined.
* How much signal quality ("edge") the basket structure needs to break even
  after spread and swap.
* How much the guards change the odds, on identical price paths (common
  random numbers), so differences come from the rules, not from luck.

What this CANNOT tell you
-------------------------
* Whether NMACD BT2 itself has an edge. The EA's regime indicators are
  custom .ex5 files that aren't in the repo, so the entry/exit signal here is
  a generic stand-in whose quality you set with --accuracy. Only a backtest
  and a forward test on real, unseen XAUUSD data can show a real edge.
  `--audit` mode resamples the EA's own audit CSV for that purpose.

Model
-----
Price: hourly log returns from a GARCH(1,1) with Student-t(4) shocks
(volatility clustering and fat tails), calibrated to an annual volatility
(default 30%, gold's 2026 level), plus a hidden trend regime (Markov
up/down states) whose drift the strategy tries to follow. Weekend gaps are
drawn separately.

Signal: after each true regime change, the strategy's direction signal flips
`signal_lag_bars` later and points the right way with probability
`accuracy` (0.5 = no edge). False flips ("whipsaws") also occur at random.

Basket: a signal flip closes every leg and opens leg 1 the new way; while
the signal holds, one leg is added every `add_every_bars` up to `max_legs`.
Each 0.01-lot leg makes $1 per $1 of gold move. Spread is charged per leg,
swap per leg per day. Legs are flattened before the weekend.

Guards (optional) mirror NMACD_BT2_GoldGuards.mqh: basket stop (% balance),
daily loss halt, equity-drawdown hard halt, cooldown after a basket stop.
They are checked at bar closes, so real intrabar losses can be a little
larger than simulated.

Usage
-----
    python tools/basket_montecarlo.py grid --paths 400 --out grid.json
    python tools/basket_montecarlo.py single --accuracy 0.6 --max-legs 28 --balance 1000
    python tools/basket_montecarlo.py audit "exports/*_audit.csv" --start-equity 1000
"""

from __future__ import annotations

import argparse
import glob
import json
import math
import random
import statistics
import sys
from dataclasses import asdict, dataclass, field, replace
from multiprocessing import Pool
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))


@dataclass(frozen=True)
class Market:
    start_price: float = 4300.0
    annual_vol: float = 0.30
    garch_alpha: float = 0.05
    garch_beta: float = 0.93
    t_df: float = 4.0
    trend_strength: float = 0.10     # regime drift per bar, in units of hourly sigma
    mean_regime_bars: float = 120.0  # average trend length (~5 trading days)
    bars_per_day: int = 23
    days_per_week: int = 5
    weeks: int = 52
    weekend_gap_sigmas: float = 3.0  # weekend gap stdev, in hourly sigmas


@dataclass(frozen=True)
class Strategy:
    accuracy: float = 0.5            # P(signal points the right way after a trend change)
    signal_lag_bars: int = 3         # indicator lag after the true change
    whipsaw_every_bars: float = 60.0 # average bars between false flips (0 = none)
    whipsaw_len_bars: int = 4
    add_every_bars: int = 3
    max_legs: int = 28
    dollars_per_dollar_per_leg: float = 1.0  # 0.01 lot x 100 oz
    spread_per_leg: float = 0.30     # $ round-trip cost per 0.01 leg
    swap_per_leg_day: float = -0.30  # $ per 0.01 leg per night
    friday_flatten: bool = True


@dataclass(frozen=True)
class Guards:
    enabled: bool = False
    basket_stop_pct: float = 15.0
    daily_loss_pct: float = 20.0
    equity_dd_pct: float = 35.0
    cooldown_bars: int = 4


@dataclass(frozen=True)
class Account:
    balance: float = 1000.0
    ruin_pct: float = 20.0           # equity at or below this % of start = margin stop-out / ruin


@dataclass
class PathResult:
    final_equity: float
    return_pct: float
    max_dd_pct: float
    ruined: bool
    hard_halted: bool
    baskets: int
    guard_flattens: int = 0


def _t_shock(rng: random.Random, df: float) -> float:
    """Student-t draw scaled to unit variance."""
    z = rng.gauss(0.0, 1.0)
    chi2 = rng.gammavariate(df / 2.0, 2.0)
    return z / math.sqrt(chi2 / df) * math.sqrt((df - 2.0) / df)


def generate_market(seed: int, m: Market) -> Tuple[List[float], List[int], List[int]]:
    """Returns (close prices per bar, true regime per bar, bar index where each new week starts)."""
    rng = random.Random(seed)
    bars_per_year = m.bars_per_day * m.days_per_week * 52
    sigma_h = m.annual_vol / math.sqrt(bars_per_year)
    target_var = sigma_h * sigma_h
    persistence = m.garch_alpha + m.garch_beta
    omega = target_var * (1.0 - persistence)
    h = target_var
    log_p = math.log(m.start_price)
    regime = 1 if rng.random() < 0.5 else -1
    switch_p = 1.0 / m.mean_regime_bars
    prices: List[float] = []
    regimes: List[int] = []
    week_starts: List[int] = []
    bars_per_week = m.bars_per_day * m.days_per_week
    for week in range(m.weeks):
        if week > 0:
            log_p += m.weekend_gap_sigmas * sigma_h * _t_shock(rng, m.t_df)
        week_starts.append(len(prices))
        for _ in range(bars_per_week):
            if rng.random() < switch_p:
                regime = -regime
            shock = math.sqrt(h) * _t_shock(rng, m.t_df)
            r = regime * m.trend_strength * sigma_h + shock
            h = omega + m.garch_alpha * shock * shock + m.garch_beta * h
            log_p += r
            prices.append(math.exp(log_p))
            regimes.append(regime)
    return prices, regimes, week_starts


def generate_signal(seed: int, regimes: Sequence[int], s: Strategy) -> List[int]:
    """Direction signal: lagged, sometimes wrong, with occasional whipsaws."""
    rng = random.Random(seed * 7919 + 17)
    n = len(regimes)
    base = [0] * n
    current = regimes[0] if rng.random() < s.accuracy else -regimes[0]
    pending: Optional[Tuple[int, int]] = None
    for i in range(n):
        if i > 0 and regimes[i] != regimes[i - 1]:
            new_dir = regimes[i] if rng.random() < s.accuracy else -regimes[i]
            pending = (i + s.signal_lag_bars, new_dir)
        if pending and i >= pending[0]:
            current = pending[1]
            pending = None
        base[i] = current
    if s.whipsaw_every_bars > 0:
        p = 1.0 / s.whipsaw_every_bars
        i = 0
        while i < n:
            if rng.random() < p:
                for j in range(i, min(n, i + s.whipsaw_len_bars)):
                    base[j] = -base[j]
                i += s.whipsaw_len_bars
            else:
                i += 1
    return base


def simulate(seed: int, m: Market, s: Strategy, g: Guards, a: Account) -> PathResult:
    prices, regimes, week_starts = generate_market(seed, m)
    signal = generate_signal(seed, regimes, s)
    week_start_set = set(week_starts)
    bars_per_week = m.bars_per_day * m.days_per_week
    k = s.dollars_per_dollar_per_leg

    balance = a.balance
    ruin_level = a.balance * a.ruin_pct / 100.0
    legs: List[Tuple[float, int]] = []   # (entry price, direction)
    leg_sum_entry = 0.0                  # sum of entry prices, for fast floating P&L
    leg_dir = 0
    bars_since_add = 10 ** 9
    peak = a.balance
    max_dd = 0.0
    baskets = 0
    guard_flattens = 0
    cooldown_until = -1
    hard_halt = False
    day_halt = False
    day_start_equity = a.balance

    def floating(price: float) -> float:
        if not legs:
            return 0.0
        return leg_dir * (price * len(legs) - leg_sum_entry) * k

    def close_all(price: float) -> None:
        nonlocal balance, legs, leg_sum_entry, leg_dir
        balance += floating(price)
        legs = []
        leg_sum_entry = 0.0
        leg_dir = 0

    def open_leg(price: float, direction: int) -> None:
        nonlocal balance, leg_sum_entry, leg_dir, bars_since_add, baskets
        if not legs:
            baskets += 1
        legs.append((price, direction))
        leg_sum_entry += price
        leg_dir = direction
        balance -= s.spread_per_leg
        bars_since_add = 0

    n = len(prices)
    for i in range(n):
        price = prices[i]
        bar_in_week = i % bars_per_week
        if i in week_start_set:
            day_halt = False
        if bar_in_week % m.bars_per_day == 0:
            day_start_equity = balance + floating(price)
            day_halt = False
        bars_since_add += 1

        # Exit on signal flip (the M60-dot analogue).
        if legs and signal[i] != leg_dir:
            close_all(price)

        trading_ok = not hard_halt and not day_halt and i >= cooldown_until
        # Friday flatten: no new legs in the last bar of the week.
        last_bar_of_week = bar_in_week == bars_per_week - 1
        if trading_ok and not last_bar_of_week:
            if not legs:
                open_leg(price, signal[i])
            elif len(legs) < s.max_legs and bars_since_add >= s.add_every_bars:
                open_leg(price, signal[i])

        equity = balance + floating(price)

        if g.enabled and legs:
            if g.basket_stop_pct > 0 and floating(price) <= -balance * g.basket_stop_pct / 100.0:
                close_all(price)
                guard_flattens += 1
                cooldown_until = i + g.cooldown_bars
            elif g.daily_loss_pct > 0 and equity <= day_start_equity * (1 - g.daily_loss_pct / 100.0):
                close_all(price)
                guard_flattens += 1
                day_halt = True
            equity = balance + floating(price)
        if g.enabled and g.equity_dd_pct > 0 and not hard_halt:
            if peak > 0 and (peak - equity) / peak * 100.0 >= g.equity_dd_pct:
                close_all(price)
                guard_flattens += 1
                hard_halt = True
                equity = balance

        peak = max(peak, equity)
        if peak > 0:
            max_dd = max(max_dd, (peak - equity) / peak * 100.0)

        if equity <= ruin_level:
            close_all(price)
            # Gaps can jump past the stop-out level; assume negative-balance protection (floor at 0).
            balance = max(0.0, balance)
            return PathResult(balance, (balance / a.balance - 1) * 100, max(max_dd, 100 - a.ruin_pct),
                              True, hard_halt, baskets, guard_flattens)

        if bar_in_week % m.bars_per_day == m.bars_per_day - 1 and legs:
            balance += s.swap_per_leg_day * len(legs)
        if last_bar_of_week and s.friday_flatten and legs:
            close_all(price)

    close_all(prices[-1])
    return PathResult(balance, (balance / a.balance - 1) * 100, max_dd, False, hard_halt, baskets, guard_flattens)


def summarize(results: Sequence[PathResult]) -> Dict[str, float]:
    returns = sorted(r.return_pct for r in results)
    n = len(returns)

    def pct(q: float) -> float:
        return returns[min(n - 1, max(0, int(q * (n - 1) + 0.5)))]

    return {
        "paths": n,
        "p_profit": sum(1 for r in returns if r > 0) / n * 100,
        "p_ruin": sum(1 for r in results if r.ruined) / n * 100,
        "p_hard_halt": sum(1 for r in results if r.hard_halted) / n * 100,
        "p_dd_over_50": sum(1 for r in results if r.max_dd_pct >= 50) / n * 100,
        "mean_return": statistics.fmean(returns),
        "median_return": pct(0.5),
        "p05_return": pct(0.05),
        "p95_return": pct(0.95),
        "median_max_dd": statistics.median(r.max_dd_pct for r in results),
        "baskets_per_year": statistics.fmean(r.baskets for r in results),
    }


def _run_one(job: Tuple[int, Market, Strategy, Guards, Account]) -> PathResult:
    return simulate(*job)


def run_config(paths: int, m: Market, s: Strategy, g: Guards, a: Account, seed0: int = 1000,
               pool: Optional[Pool] = None) -> Dict[str, float]:
    jobs = [(seed0 + i, m, s, g, a) for i in range(paths)]
    results = pool.map(_run_one, jobs, chunksize=max(1, paths // 16)) if pool else [_run_one(j) for j in jobs]
    return summarize(results)


# ---------------------------------------------------------------------------
# Bootstrap from the EA's own audit CSV (the honest mode once you have data)
# ---------------------------------------------------------------------------

def audit_baskets(trades) -> List[Tuple[object, float]]:
    """Groups legs closed in the same minute on the same side into one basket."""
    baskets: Dict[Tuple[object, str], float] = {}
    for t in trades:
        key = (t.exit_time.replace(second=0, microsecond=0), t.direction)
        baskets[key] = baskets.get(key, 0.0) + t.pnl
    return sorted(((k[0], v) for k, v in baskets.items()), key=lambda kv: kv[0])


def bootstrap_audit(trades, start_equity: float, paths: int = 5000, years: float = 1.0,
                    ruin_pct: float = 20.0, block: int = 5, seed: int = 7) -> Dict[str, float]:
    """Block bootstrap of basket results: keeps short runs of consecutive baskets together
    so losing streaks are preserved instead of being shuffled away."""
    baskets = [pnl for _, pnl in audit_baskets(trades)]
    if len(baskets) < block * 2:
        raise ValueError("Not enough baskets in the audit files for a bootstrap.")
    times = [t for t, _ in audit_baskets(trades)]
    span_years = max((times[-1] - times[0]).days / 365.25, 1 / 52)
    per_year = len(baskets) / span_years
    target = max(1, int(round(per_year * years)))
    rng = random.Random(seed)
    results: List[PathResult] = []
    ruin_level = start_equity * ruin_pct / 100.0
    for _ in range(paths):
        equity = start_equity
        peak = equity
        max_dd = 0.0
        ruined = False
        drawn = 0
        while drawn < target and not ruined:
            startidx = rng.randrange(0, len(baskets) - block + 1)
            for pnl in baskets[startidx:startidx + block]:
                equity += pnl
                peak = max(peak, equity)
                max_dd = max(max_dd, (peak - equity) / peak * 100.0 if peak > 0 else 100.0)
                drawn += 1
                if equity <= ruin_level:
                    ruined = True
                    break
                if drawn >= target:
                    break
        results.append(PathResult(equity, (equity / start_equity - 1) * 100, max_dd, ruined, False, drawn))
    out = summarize(results)
    out["observed_baskets"] = len(baskets)
    out["baskets_per_year_observed"] = per_year
    return out


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

GRID_ACCURACY = (0.50, 0.55, 0.60, 0.65, 0.70, 0.75)


def grid_configs(balance: float) -> Dict[str, Tuple[Strategy, Guards]]:
    legs_sized = max(1, int(balance * 0.15 / 81.0))
    return {
        "certified_28_legs_no_stops": (Strategy(max_legs=28), Guards(enabled=False)),
        "28_legs_with_default_guards": (Strategy(max_legs=28), Guards(enabled=True)),
        f"sized_{legs_sized}_legs_with_guards": (Strategy(max_legs=legs_sized), Guards(enabled=True)),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)

    g = sub.add_parser("grid", help="configs x signal accuracy on shared price paths")
    g.add_argument("--paths", type=int, default=400)
    g.add_argument("--balance", type=float, default=1000.0)
    g.add_argument("--vol", type=float, default=0.30)
    g.add_argument("--workers", type=int, default=4)
    g.add_argument("--out")

    s1 = sub.add_parser("single", help="one configuration")
    s1.add_argument("--paths", type=int, default=400)
    s1.add_argument("--balance", type=float, default=1000.0)
    s1.add_argument("--vol", type=float, default=0.30)
    s1.add_argument("--accuracy", type=float, default=0.5)
    s1.add_argument("--max-legs", type=int, default=28)
    s1.add_argument("--guards", action="store_true")
    s1.add_argument("--workers", type=int, default=4)

    au = sub.add_parser("audit", help="block-bootstrap the EA's audit CSVs")
    au.add_argument("audit", nargs="+")
    au.add_argument("--start-equity", type=float, required=True)
    au.add_argument("--paths", type=int, default=5000)
    au.add_argument("--years", type=float, default=1.0)

    args = parser.parse_args()

    if args.cmd == "audit":
        import nmacd_stats as ns
        paths = sorted({Path(p) for pattern in args.audit for p in glob.glob(pattern)})
        trades, _ = ns.load_audit(paths)
        print(json.dumps(bootstrap_audit(trades, args.start_equity, args.paths, args.years), indent=2))
        return

    market = Market(annual_vol=args.vol)
    account = Account(balance=args.balance)
    with Pool(args.workers) as pool:
        if args.cmd == "single":
            strat = Strategy(accuracy=args.accuracy, max_legs=args.max_legs)
            print(json.dumps(run_config(args.paths, market, strat, Guards(enabled=args.guards), account, pool=pool), indent=2))
            return
        out = {"market": asdict(market), "account": asdict(account), "paths": args.paths, "results": {}}
        for name, (strat, guards) in grid_configs(args.balance).items():
            out["results"][name] = {}
            for acc in GRID_ACCURACY:
                res = run_config(args.paths, market, replace(strat, accuracy=acc), guards, account, pool=pool)
                out["results"][name][f"{acc:.2f}"] = res
                print(f"{name:32s} acc={acc:.2f}  P(profit)={res['p_profit']:5.1f}%  P(ruin)={res['p_ruin']:5.1f}%  "
                      f"P(halt)={res['p_hard_halt']:5.1f}%  "
                      f"median={res['median_return']:8.1f}%  p05={res['p05_return']:8.1f}%", flush=True)
    if args.out:
        Path(args.out).write_text(json.dumps(out, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
