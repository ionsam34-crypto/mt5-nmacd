import math
import statistics
import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import basket_montecarlo as bm  # noqa: E402
import nmacd_stats as ns  # noqa: E402


class MarketTest(unittest.TestCase):
    def test_volatility_calibration(self):
        vols = []
        for seed in range(12):
            prices, _, week_starts = bm.generate_market(seed, bm.Market(trend_strength=0.0))
            starts = set(week_starts)
            rets = [math.log(prices[i] / prices[i - 1]) for i in range(1, len(prices)) if i not in starts]
            vols.append(statistics.pstdev(rets) * math.sqrt(23 * 5 * 52))
        self.assertAlmostEqual(statistics.fmean(vols), 0.30, delta=0.03)

    def test_signal_accuracy_one_tracks_regime(self):
        _, regimes, _ = bm.generate_market(3, bm.Market())
        sig = bm.generate_signal(3, regimes, bm.Strategy(accuracy=1.0, signal_lag_bars=0, whipsaw_every_bars=0))
        self.assertEqual(sig, regimes)

    def test_deterministic(self):
        args = (5, bm.Market(), bm.Strategy(accuracy=0.6), bm.Guards(enabled=True), bm.Account())
        self.assertEqual(bm.simulate(*args), bm.simulate(*args))


class StrategyTest(unittest.TestCase):
    def test_guards_reduce_ruin_on_identical_paths(self):
        m, a = bm.Market(), bm.Account(balance=1000)
        s = bm.Strategy(accuracy=0.5, max_legs=28)
        off = bm.run_config(60, m, s, bm.Guards(enabled=False), a)
        on = bm.run_config(60, m, s, bm.Guards(enabled=True), a)
        self.assertGreater(off["p_ruin"], 50.0)
        self.assertLess(on["p_ruin"], off["p_ruin"])

    def test_no_edge_no_costs_is_roughly_fair(self):
        m = bm.Market(trend_strength=0.0)
        s = bm.Strategy(accuracy=0.5, max_legs=1, spread_per_leg=0.0, swap_per_leg_day=0.0, whipsaw_every_bars=0)
        res = bm.run_config(150, m, s, bm.Guards(enabled=False), bm.Account(balance=100000))
        self.assertLess(abs(res["mean_return"]), 1.5)

    def test_losses_floor_at_zero(self):
        res = bm.run_config(40, bm.Market(), bm.Strategy(max_legs=28), bm.Guards(enabled=False), bm.Account(balance=500))
        self.assertGreaterEqual(res["p05_return"], -100.0)


class BootstrapTest(unittest.TestCase):
    def _trades(self, pnls):
        t0 = datetime(2026, 1, 5, 10, 0)
        out = []
        for i, pnl in enumerate(pnls):
            when = t0 + timedelta(days=i)
            out.append(ns.Trade(when - timedelta(hours=2), when, "BUY", pnl, 0.01, "EBBB", "CONTINUATION",
                                "EXIT|M60_CUSTOM", 0, 0, 0, 1))
        return out

    def test_bootstrap_positive_edge(self):
        trades = self._trades([30, -10, 25, -15, 40, -5, 20, -10, 35, -20] * 5)
        res = bm.bootstrap_audit(trades, 1000.0, paths=500)
        self.assertGreater(res["p_profit"], 90.0)
        self.assertEqual(res["observed_baskets"], 50)

    def test_bootstrap_groups_legs_into_baskets(self):
        trades = self._trades([10] * 12)
        trades += [ns.Trade(t.entry_time, t.exit_time, t.direction, 5.0, 0.01, "EBBB", "C", "", 0, 0, 0, 2)
                   for t in trades]
        baskets = bm.audit_baskets(trades)
        self.assertEqual(len(baskets), 12)
        self.assertTrue(all(pnl == 15.0 for _, pnl in baskets))


if __name__ == "__main__":
    unittest.main()
