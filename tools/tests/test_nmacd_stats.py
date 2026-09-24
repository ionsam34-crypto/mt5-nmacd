import argparse
import math
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import audit_review  # noqa: E402
import nmacd_stats as ns  # noqa: E402

# Exact header written by AuditHeaderLine() in the EA.
HEADER = ("eval_time,bar_time,ticket,signal_id,direction,grade,htf_regime,entry_price,initial_stop_price,"
          "initial_risk_points,lot_size,accepted,rejection_reason,exit_price,exit_reason,realized_profit,"
          "mfe_points,mae_points,max_floating_profit,profit_given_back_usd,d1_mother,h4_phase,h1_cycle,"
          "trade_class,exit_model,state_tag,entry_cell,exit_cell,stack_depth_at_entry,stack_limit_at_entry")


def closed_row(exit_time, entry_time, pnl, cell="EBBB", reason="CELL=D1B|EXIT|M60_CUSTOM|RED_DOT|BUY", depth=1):
    # Mirrors the FinalizeAuditExit() StringFormat column order.
    return (f"{exit_time},{entry_time},1001,XAUUSD_i_M3_x_buy,BUY,A,1,4300.00,0.00,0.00,0.01,true,,"
            f"4301.00,{reason},{pnl:.2f},100.00,50.00,5.00,1.00,1,1,1,CONTINUATION,M60,CM60,{cell},D1B,{depth},28")


def rejection_row(time, reason):
    # Mirrors LogAuditRejection(): empty ticket, accepted=false, trailing empty columns.
    return f"{time},{time},,sig,SELL,B,-1,,,,,false,{reason},,,,,,,,,,,,,,,"


class StatsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "2026-09-01_XAUUSD_i_PERIOD_M3_audit.csv"
        rows = [
            HEADER,
            closed_row("2026.09.01 10:00:00", "2026.09.01 09:00:00", 10.0),
            closed_row("2026.09.01 12:00:00", "2026.09.01 11:00:00", -5.0, cell="ESSS"),
            closed_row("2026.09.02 10:00:00", "2026.09.02 09:00:00", -10.0, reason="EXIT|GG_BASKET_STOP", depth=7),
            closed_row("2026.09.03 10:00:00", "2026.09.03 09:00:00", 20.0),
            closed_row("2026.09.04 10:00:00", "2026.09.04 09:00:00", -30.0),
            rejection_row("2026.09.01 13:00:00", "gg_news_window Nonfarm Payrolls"),
            rejection_row("2026.09.01 14:00:00", "spread_limit_exceeded"),
            rejection_row("2026.09.01 15:00:00", "setup_not_valid:blocked_weekly_regime_bear"),
        ]
        self.path.write_text("\r\n".join(rows) + "\r\n", encoding="ascii")

    def tearDown(self):
        self.tmp.cleanup()

    def test_load_audit(self):
        trades, rejections = ns.load_audit([self.path])
        self.assertEqual(len(trades), 5)
        self.assertEqual([t.pnl for t in trades], [10.0, -5.0, -10.0, 20.0, -30.0])
        self.assertEqual(rejections, {"gg_news_window": 1, "spread_limit_exceeded": 1, "setup_not_valid": 1})
        self.assertEqual(trades[1].entry_cell, "ESSS")
        self.assertEqual(trades[2].stack_depth, 7)

    def test_exit_category(self):
        self.assertEqual(ns.exit_category("CELL=D1B_H4B_H1B_CLOSE_BUY|EXIT|M60_CUSTOM|RED_DOT|BUY"), "M60_CUSTOM")
        self.assertEqual(ns.exit_category("EXIT|GG_BASKET_STOP"), "GG_BASKET_STOP")
        self.assertEqual(ns.exit_category("Bear regime exit"), "Bear regime exit")
        self.assertEqual(ns.exit_category(""), "unknown")

    def test_max_drawdown(self):
        dd, pct = ns.max_drawdown([10, -5, -10, 20, -30], start_equity=100)
        self.assertAlmostEqual(dd, 30.0)
        self.assertAlmostEqual(pct, 30.0 / 115.0 * 100.0)
        self.assertEqual(ns.max_losing_streak([1, -1, -1, 2, -1, -1, -1]), 3)

    def test_summary(self):
        trades, _ = ns.load_audit([self.path])
        s = ns.summarize(trades)
        self.assertAlmostEqual(s["net"], -15.0)
        self.assertAlmostEqual(s["profit_factor"], 30.0 / 45.0)
        self.assertAlmostEqual(s["win_rate"], 40.0)

    def test_expected_max_sharpe_matches_paper_scale(self):
        # Bailey & Lopez de Prado: ~2.53 standard deviations for 100 skill-less trials.
        self.assertAlmostEqual(ns.expected_max_sharpe(1.0, 100), 2.53, delta=0.02)
        self.assertEqual(ns.expected_max_sharpe(1.0, 1), 0.0)
        self.assertLess(ns.expected_max_sharpe(1.0, 10), ns.expected_max_sharpe(1.0, 1000))

    def test_psr_and_dsr(self):
        self.assertAlmostEqual(ns.probabilistic_sharpe(0.0, 0.0, 100, 0.0, 3.0), 0.5)
        returns = [0.004, -0.002, 0.003, 0.001, -0.001] * 40
        few = ns.deflated_sharpe(returns, n_trials=2, trial_sharpe_variance=0.01)
        many = ns.deflated_sharpe(returns, n_trials=832, trial_sharpe_variance=0.01)
        self.assertGreater(few["deflated_sharpe"], many["deflated_sharpe"])
        self.assertGreater(few["psr_vs_zero"], 0.5)

    def test_daily_returns_fill_weekdays(self):
        trades, _ = ns.load_audit([self.path])
        returns = ns.daily_returns(trades, 1000.0)
        # Tue 2026-09-01 .. Fri 2026-09-04 -> 4 weekdays.
        self.assertEqual(len(returns), 4)
        self.assertAlmostEqual(returns[0], 5.0 / 1000.0)

    def test_near_news(self):
        events = [datetime(2026, 9, 4, 15, 30)]
        self.assertTrue(ns.near_news(datetime(2026, 9, 4, 15, 20), events, 15, 30))
        self.assertTrue(ns.near_news(datetime(2026, 9, 4, 15, 59), events, 15, 30))
        self.assertFalse(ns.near_news(datetime(2026, 9, 4, 16, 1), events, 15, 30))
        self.assertFalse(ns.near_news(datetime(2026, 9, 4, 15, 14), events, 15, 30))

    def test_report_end_to_end(self):
        news = Path(self.tmp.name) / "news.csv"
        news.write_text("server_time,currency,event\n2026.09.01 09:05,USD,CPI\n", encoding="ascii")
        args = argparse.Namespace(audit=[str(self.path)], start_equity=1000.0, news=str(news), currency="USD",
                                  news_before=15, news_after=30, trials=None, n_trials=832,
                                  trial_sharpe_std=0.05, out=None)
        report = audit_review.build_report(args)
        self.assertIn("## Overall", report)
        self.assertIn("| EBBB |", report)
        self.assertIn("inside window", report)
        self.assertIn("Deflated Sharpe", report)
        self.assertIn("NOT PROVEN", report)
        self.assertFalse(math.isnan(ns.summarize(ns.load_audit([self.path])[0])["net"]))


if __name__ == "__main__":
    unittest.main()
