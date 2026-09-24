"""Statistics for reviewing NMACD BT2 audit CSVs honestly.

Standard library only, so it runs on the trading PC without installs.

The audit CSV is the one the EA writes via AppendAuditRow():
    <Common>/Files/NMACD_BT2_Telemetry/<date>_<symbol>_<period>_audit.csv

The Deflated Sharpe Ratio follows Bailey & Lopez de Prado (2014),
"The Deflated Sharpe Ratio: Correcting for Selection Bias, Backtest
Overfitting and Non-Normality". It answers: after trying N configurations,
how likely is it that this one's Sharpe is real rather than the best of N
lucky draws?
"""

from __future__ import annotations

import csv
import math
import statistics
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Tuple

EULER_GAMMA = 0.5772156649015329
_NORMAL = statistics.NormalDist()
_TIME_FORMATS = ("%Y.%m.%d %H:%M:%S", "%Y.%m.%d %H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M")


def parse_time(text: Optional[str]) -> Optional[datetime]:
    if not text:
        return None
    text = text.strip()
    for fmt in _TIME_FORMATS:
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def _float(text: Optional[str]) -> Optional[float]:
    if text is None or text.strip() == "":
        return None
    try:
        return float(text)
    except ValueError:
        return None


@dataclass
class Trade:
    entry_time: datetime
    exit_time: datetime
    direction: str
    pnl: float
    lot: float
    entry_cell: str
    trade_class: str
    exit_reason: str
    mfe_points: float
    mae_points: float
    given_back: float
    stack_depth: int

    @property
    def exit_category(self) -> str:
        return exit_category(self.exit_reason)


def exit_category(reason: str) -> str:
    """'CELL=..|EXIT|M60_CUSTOM|RED_DOT|..' -> 'M60_CUSTOM'; 'EXIT|GG_BASKET_STOP' -> 'GG_BASKET_STOP'."""
    if not reason:
        return "unknown"
    idx = reason.find("EXIT|")
    if idx >= 0:
        token = reason[idx + 5:].split("|")[0]
        return token or "unknown"
    return reason.split("|")[0] or "unknown"


def load_audit(paths: Iterable[Path]) -> Tuple[List[Trade], Dict[str, int]]:
    """Returns (closed trades sorted by exit time, rejection-reason counts)."""
    trades: List[Trade] = []
    rejections: Dict[str, int] = {}
    for path in paths:
        with open(path, newline="", encoding="utf-8-sig", errors="replace") as handle:
            for row in csv.DictReader(handle):
                accepted = (row.get("accepted") or "").strip().lower()
                if accepted == "false":
                    reason = (row.get("rejection_reason") or "unknown").split(":")[0].split(" ")[0]
                    rejections[reason] = rejections.get(reason, 0) + 1
                    continue
                pnl = _float(row.get("realized_profit"))
                entry = parse_time(row.get("bar_time"))
                exit_ = parse_time(row.get("eval_time"))
                if pnl is None or entry is None or exit_ is None:
                    continue
                trades.append(
                    Trade(
                        entry_time=entry,
                        exit_time=exit_,
                        direction=(row.get("direction") or "").strip(),
                        pnl=pnl,
                        lot=_float(row.get("lot_size")) or 0.0,
                        entry_cell=(row.get("entry_cell") or "").strip() or "-",
                        trade_class=(row.get("trade_class") or "").strip() or "-",
                        exit_reason=(row.get("exit_reason") or "").strip(),
                        mfe_points=_float(row.get("mfe_points")) or 0.0,
                        mae_points=_float(row.get("mae_points")) or 0.0,
                        given_back=_float(row.get("profit_given_back_usd")) or 0.0,
                        stack_depth=int(_float(row.get("stack_depth_at_entry")) or 0),
                    )
                )
    trades.sort(key=lambda t: (t.exit_time, t.entry_time))
    return trades, rejections


def max_drawdown(pnls: Sequence[float], start_equity: float = 0.0) -> Tuple[float, Optional[float]]:
    """Largest peak-to-trough fall of cumulative P&L. Returns (dollars, percent of peak equity or None)."""
    equity = start_equity
    peak = start_equity
    worst = 0.0
    worst_pct: Optional[float] = None
    for pnl in pnls:
        equity += pnl
        peak = max(peak, equity)
        drop = peak - equity
        if drop > worst:
            worst = drop
            if start_equity > 0 and peak > 0:
                worst_pct = drop / peak * 100.0
    return worst, worst_pct


def max_losing_streak(pnls: Sequence[float]) -> int:
    best = run = 0
    for pnl in pnls:
        run = run + 1 if pnl < 0 else 0
        best = max(best, run)
    return best


def summarize(trades: Sequence[Trade], start_equity: float = 0.0) -> Dict[str, float]:
    pnls = [t.pnl for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    gross_profit = sum(wins)
    gross_loss = -sum(losses)
    dd, dd_pct = max_drawdown(pnls, start_equity)
    return {
        "trades": len(pnls),
        "net": sum(pnls),
        "gross_profit": gross_profit,
        "gross_loss": gross_loss,
        "profit_factor": (gross_profit / gross_loss) if gross_loss > 0 else math.inf if gross_profit > 0 else 0.0,
        "win_rate": (len(wins) / len(pnls) * 100.0) if pnls else 0.0,
        "avg_win": statistics.fmean(wins) if wins else 0.0,
        "avg_loss": statistics.fmean(losses) if losses else 0.0,
        "expectancy": statistics.fmean(pnls) if pnls else 0.0,
        "worst_trade": min(pnls) if pnls else 0.0,
        "max_dd": dd,
        "max_dd_pct": dd_pct if dd_pct is not None else float("nan"),
        "max_losing_streak": max_losing_streak(pnls),
    }


def group_summaries(trades: Sequence[Trade], key: Callable[[Trade], str]) -> Dict[str, Dict[str, float]]:
    groups: Dict[str, List[Trade]] = {}
    for trade in trades:
        groups.setdefault(key(trade), []).append(trade)
    return {k: summarize(v) for k, v in sorted(groups.items())}


def daily_returns(trades: Sequence[Trade], start_equity: float) -> List[float]:
    """Weekday returns (realized P&L by exit date / equity at start of day), zeros included."""
    if not trades or start_equity <= 0:
        return []
    by_day: Dict[date, float] = {}
    for trade in trades:
        by_day[trade.exit_time.date()] = by_day.get(trade.exit_time.date(), 0.0) + trade.pnl
    first, last = min(by_day), max(by_day)
    equity = start_equity
    out: List[float] = []
    day = first
    while day <= last:
        if day.weekday() < 5:
            pnl = by_day.get(day, 0.0)
            out.append(pnl / equity if equity > 0 else -1.0)
            equity += pnl
        day += timedelta(days=1)
    return out


def sharpe(returns: Sequence[float]) -> float:
    """Per-period (not annualized) Sharpe ratio."""
    if len(returns) < 2:
        return 0.0
    sd = statistics.stdev(returns)
    return statistics.fmean(returns) / sd if sd > 0 else 0.0


def skewness(returns: Sequence[float]) -> float:
    n = len(returns)
    if n < 3:
        return 0.0
    mean = statistics.fmean(returns)
    m2 = sum((r - mean) ** 2 for r in returns) / n
    m3 = sum((r - mean) ** 3 for r in returns) / n
    return m3 / m2 ** 1.5 if m2 > 0 else 0.0


def kurtosis(returns: Sequence[float]) -> float:
    """Non-excess kurtosis (normal distribution = 3)."""
    n = len(returns)
    if n < 4:
        return 3.0
    mean = statistics.fmean(returns)
    m2 = sum((r - mean) ** 2 for r in returns) / n
    m4 = sum((r - mean) ** 4 for r in returns) / n
    return m4 / m2 ** 2 if m2 > 0 else 3.0


def probabilistic_sharpe(sr: float, sr_benchmark: float, n: int, skew: float, kurt: float) -> float:
    """Probability that the true Sharpe exceeds sr_benchmark, given n observations."""
    if n < 2:
        return 0.0
    denom = 1.0 - skew * sr + (kurt - 1.0) / 4.0 * sr * sr
    if denom <= 0:
        return 0.0
    return _NORMAL.cdf((sr - sr_benchmark) * math.sqrt(n - 1) / math.sqrt(denom))


def expected_max_sharpe(trial_sharpe_variance: float, n_trials: int) -> float:
    """Expected best Sharpe among n_trials skill-less configurations."""
    if n_trials <= 1 or trial_sharpe_variance <= 0:
        return 0.0
    z1 = _NORMAL.inv_cdf(1.0 - 1.0 / n_trials)
    z2 = _NORMAL.inv_cdf(1.0 - 1.0 / (n_trials * math.e))
    return math.sqrt(trial_sharpe_variance) * ((1.0 - EULER_GAMMA) * z1 + EULER_GAMMA * z2)


def deflated_sharpe(returns: Sequence[float], n_trials: int, trial_sharpe_variance: float) -> Dict[str, float]:
    sr = sharpe(returns)
    sk = skewness(returns)
    ku = kurtosis(returns)
    benchmark = expected_max_sharpe(trial_sharpe_variance, n_trials)
    return {
        "sharpe": sr,
        "skew": sk,
        "kurtosis": ku,
        "observations": len(returns),
        "expected_max_sharpe_from_luck": benchmark,
        "psr_vs_zero": probabilistic_sharpe(sr, 0.0, len(returns), sk, ku),
        "deflated_sharpe": probabilistic_sharpe(sr, benchmark, len(returns), sk, ku),
    }


def load_trials(path: Path) -> List[float]:
    """trials.csv needs a 'sharpe' column in the SAME units as daily_returns (per-day, not annualized)."""
    values: List[float] = []
    with open(path, newline="", encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            value = _float(row.get("sharpe"))
            if value is not None:
                values.append(value)
    return values


def load_news(path: Path, currency: str = "USD") -> List[datetime]:
    """Reads the CSV written by Scripts/NMACD_ExportNewsCalendar.mq5."""
    events: List[datetime] = []
    with open(path, newline="", encoding="utf-8-sig", errors="replace") as handle:
        for row in csv.reader(handle):
            if len(row) < 2 or row[1].strip() != currency:
                continue
            when = parse_time(row[0])
            if when:
                events.append(when)
    events.sort()
    return events


def near_news(when: datetime, events: Sequence[datetime], before_min: int, after_min: int) -> bool:
    lo = when - timedelta(minutes=after_min)
    hi = when + timedelta(minutes=before_min)
    # events sorted: binary search for first event >= lo
    left, right = 0, len(events)
    while left < right:
        mid = (left + right) // 2
        if events[mid] < lo:
            left = mid + 1
        else:
            right = mid
    return left < len(events) and events[left] <= hi
