"""Review NMACD BT2 audit CSVs and write a markdown report.

Examples
--------
    python tools/audit_review.py exports/*_audit.csv --start-equity 1000
    python tools/audit_review.py exports/*_audit.csv --start-equity 1000 \
        --news NMACD_news_high_impact.csv --trials trials.csv --out report.md

--trials: a CSV with one row per configuration you have EVER backtested on
this strategy and a 'sharpe' column in per-day units. If you don't have one,
pass --n-trials and --trial-sharpe-std instead; be honest about the count
(the 832-pass matrix sweep alone counts as 832).
"""

from __future__ import annotations

import argparse
import glob
import math
import statistics
import sys
from pathlib import Path
from typing import Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parent))

import nmacd_stats as ns  # noqa: E402


def _fmt(value: float, digits: int = 2) -> str:
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return "∞" if value == math.inf else "–"
    if isinstance(value, int):
        return str(value)
    return f"{value:,.{digits}f}"


def _table(title: str, groups: Dict[str, Dict[str, float]]) -> List[str]:
    lines = [f"### {title}", "", "| Group | Trades | Net $ | PF | Win % | Expectancy $ | Worst $ |", "|---|---:|---:|---:|---:|---:|---:|"]
    for key, s in groups.items():
        lines.append(
            f"| {key} | {s['trades']} | {_fmt(s['net'])} | {_fmt(s['profit_factor'])} | "
            f"{_fmt(s['win_rate'], 1)} | {_fmt(s['expectancy'])} | {_fmt(s['worst_trade'])} |"
        )
    return lines + [""]


def build_report(args: argparse.Namespace) -> str:
    paths = sorted({Path(p) for pattern in args.audit for p in glob.glob(pattern)})
    if not paths:
        raise SystemExit("No audit CSV files matched.")
    trades, rejections = ns.load_audit(paths)
    if not trades:
        raise SystemExit("Audit files contain no closed trades.")

    out: List[str] = ["# NMACD BT2 audit review", ""]
    out.append(f"Files: {len(paths)} · closed legs: {len(trades)} · "
               f"{trades[0].entry_time:%Y-%m-%d} → {trades[-1].exit_time:%Y-%m-%d}")
    out.append("")

    s = ns.summarize(trades, args.start_equity)
    out += ["## Overall", "",
            "| Metric | Value |", "|---|---:|",
            f"| Net P&L $ | {_fmt(s['net'])} |",
            f"| Profit factor | {_fmt(s['profit_factor'])} |",
            f"| Win rate % | {_fmt(s['win_rate'], 1)} |",
            f"| Avg win / avg loss $ | {_fmt(s['avg_win'])} / {_fmt(s['avg_loss'])} |",
            f"| Expectancy per leg $ | {_fmt(s['expectancy'])} |",
            f"| Worst single leg $ | {_fmt(s['worst_trade'])} |",
            f"| Max drawdown (closed P&L) $ | {_fmt(s['max_dd'])} |",
            f"| Max drawdown % of peak | {_fmt(s['max_dd_pct'], 1)} |",
            f"| Longest losing streak (legs) | {s['max_losing_streak']} |",
            ""]
    out.append("> Drawdown here uses closed-leg P&L only. Floating drawdown of an open stack is larger; "
               "use the Strategy Tester's equity drawdown for the true figure.")
    out.append("")

    out += _table("By entry cell (D1/H4/H1)", ns.group_summaries(trades, lambda t: t.entry_cell))
    out += _table("By trade class", ns.group_summaries(trades, lambda t: t.trade_class))
    out += _table("By exit reason", ns.group_summaries(trades, lambda t: t.exit_category))
    out += _table("By entry hour (server time)", ns.group_summaries(trades, lambda t: f"{t.entry_time.hour:02d}"))
    out += _table("By month", ns.group_summaries(trades, lambda t: f"{t.exit_time:%Y-%m}"))
    out += _table("By stack depth at entry", ns.group_summaries(
        trades, lambda t: "1" if t.stack_depth <= 1 else "2-5" if t.stack_depth <= 5 else "6-10" if t.stack_depth <= 10 else "11+"))

    if args.news:
        events = ns.load_news(Path(args.news), args.currency)
        flags = [ns.near_news(t.entry_time, events, args.news_before, args.news_after) for t in trades]
        near = [t for t, f in zip(trades, flags) if f]
        far = [t for t, f in zip(trades, flags) if not f]
        out += _table(f"Entries inside the news window ({args.news_before} min before / {args.news_after} min after, {len(events)} events)",
                      {"inside window": ns.summarize(near), "outside window": ns.summarize(far)})

    if rejections:
        out += ["### Rejected signals by reason", "", "| Reason | Count |", "|---|---:|"]
        out += [f"| {k} | {v} |" for k, v in sorted(rejections.items(), key=lambda kv: -kv[1])]
        out.append("")

    if args.start_equity > 0:
        returns = ns.daily_returns(trades, args.start_equity)
        if args.trials:
            trial_srs = ns.load_trials(Path(args.trials))
            n_trials = len(trial_srs)
            variance = statistics.variance(trial_srs) if n_trials > 1 else 0.0
        else:
            n_trials = args.n_trials
            variance = args.trial_sharpe_std ** 2
        d = ns.deflated_sharpe(returns, n_trials, variance)
        out += ["## Is it skill or luck?", "",
                "| Metric | Value |", "|---|---:|",
                f"| Daily Sharpe (not annualized) | {_fmt(d['sharpe'], 3)} |",
                f"| Annualized (×√252, for reference) | {_fmt(d['sharpe'] * math.sqrt(252), 2)} |",
                f"| Trading days | {d['observations']} |",
                f"| Skew / kurtosis | {_fmt(d['skew'], 2)} / {_fmt(d['kurtosis'], 2)} |",
                f"| Configurations tried | {n_trials} |",
                f"| Best daily Sharpe expected from luck alone | {_fmt(d['expected_max_sharpe_from_luck'], 3)} |",
                f"| P(true Sharpe > 0) | {_fmt(d['psr_vs_zero'] * 100, 1)} % |",
                f"| **Deflated Sharpe (P(real edge) after {n_trials} tries)** | **{_fmt(d['deflated_sharpe'] * 100, 1)} %** |",
                ""]
        verdict = ("PASS: evidence of an edge beyond selection luck (≥ 95%)." if d["deflated_sharpe"] >= 0.95
                   else "NOT PROVEN: this result is within what the number of configurations tried could produce by luck.")
        out += [f"**Verdict:** {verdict}", ""]
        if n_trials <= 1:
            out += ["> Warning: no trial count supplied, so this is not deflated. Pass --trials or --n-trials.", ""]

    return "\n".join(out)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("audit", nargs="+", help="audit CSV paths or glob patterns")
    parser.add_argument("--start-equity", type=float, default=0.0, help="account size at the start of the period")
    parser.add_argument("--news", help="CSV from Scripts/NMACD_ExportNewsCalendar.mq5")
    parser.add_argument("--currency", default="USD")
    parser.add_argument("--news-before", type=int, default=15)
    parser.add_argument("--news-after", type=int, default=30)
    parser.add_argument("--trials", help="CSV of every configuration tried, with a per-day 'sharpe' column")
    parser.add_argument("--n-trials", type=int, default=1)
    parser.add_argument("--trial-sharpe-std", type=float, default=0.0, help="std-dev of per-day Sharpe across trials")
    parser.add_argument("--out", help="write the markdown report here instead of stdout")
    args = parser.parse_args()
    report = build_report(args)
    if args.out:
        Path(args.out).write_text(report, encoding="utf-8")
        print(f"Wrote {args.out}")
    else:
        print(report)


if __name__ == "__main__":
    main()
