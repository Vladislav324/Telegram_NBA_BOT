"""
backtest.py — Бэктест и полные метрики эффективности бота.

Метрики:
  - ROI, Yield, Hit Rate
  - Max Drawdown, Sharpe Ratio
  - CLV (Closing Line Value)
  - По рынкам, лигам, диапазонам edge

Usage:
    python backtest.py                    # полный отчёт
    python backtest.py --market "Тотал"  # фильтр по рынку
    python backtest.py --league "АПЛ"    # фильтр по лиге
    python backtest.py --since 2026-03-01
"""

from __future__ import annotations

import argparse
import json
import math
import os
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Optional

PREDICTIONS_FILE = "predictions.json"
RESULTS_FILE     = "results.json"


@dataclass
class BetRecord:
    date:       str
    match:      str
    league:     str
    market:     str
    selection:  str
    odds:       float
    stake:      float
    edge:       float
    model_prob: float
    won:        Optional[bool] = None

    @property
    def profit(self) -> float:
        if self.won is None: return 0.0
        return self.stake * (self.odds - 1) if self.won else -self.stake


@dataclass
class BacktestResult:
    records:      list[BetRecord] = field(default_factory=list)

    # ── Общие метрики ──────────────────────────────────────────────
    @property
    def resolved(self) -> list[BetRecord]:
        return [r for r in self.records if r.won is not None]

    @property
    def n(self) -> int: return len(self.resolved)

    @property
    def wins(self) -> int: return sum(1 for r in self.resolved if r.won)

    @property
    def hit_rate(self) -> float:
        return self.wins / self.n if self.n else 0.0

    @property
    def total_staked(self) -> float:
        return sum(r.stake for r in self.resolved)

    @property
    def total_profit(self) -> float:
        return sum(r.profit for r in self.resolved)

    @property
    def roi(self) -> float:
        return self.total_profit / self.total_staked if self.total_staked else 0.0

    @property
    def yield_(self) -> float:
        """Yield = прибыль / ставок * 100%"""
        return self.roi * 100

    @property
    def avg_odds(self) -> float:
        odds = [r.odds for r in self.resolved]
        return sum(odds) / len(odds) if odds else 0.0

    # ── Drawdown ────────────────────────────────────────────────────
    @property
    def max_drawdown(self) -> float:
        """Максимальная просадка в единицах стейка."""
        cumul = 0.0; peak = 0.0; max_dd = 0.0
        for r in sorted(self.resolved, key=lambda x: x.date):
            cumul += r.profit
            if cumul > peak: peak = cumul
            dd = peak - cumul
            if dd > max_dd: max_dd = dd
        return max_dd

    # ── Sharpe Ratio ────────────────────────────────────────────────
    @property
    def sharpe_ratio(self) -> float:
        """
        Sharpe = среднее (profit/stake) / std_dev.
        Нормированное по ставке — не зависит от размера банка.
        """
        if self.n < 2: return 0.0
        returns = [r.profit / r.stake if r.stake else 0.0 for r in self.resolved]
        mean   = sum(returns) / len(returns)
        var    = sum((x - mean) ** 2 for x in returns) / (len(returns) - 1)
        std    = math.sqrt(var) if var > 0 else 0.0
        return mean / std if std > 0 else 0.0

    # ── CLV (Closing Line Value) ─────────────────────────────────────
    def clv(self) -> float:
        """
        CLV = среднее по: (наша_цена / closing_price - 1).
        Положительный CLV → мы ставим до движения линии (умные деньги).
        Требует наличия closing_odds в записях (из line_history.json).
        """
        clv_values = []
        for r in self.resolved:
            closing = getattr(r, "closing_odds", None)
            if closing and closing > 1.01:
                clv_values.append(r.odds / closing - 1.0)
        if not clv_values:
            return float("nan")
        return sum(clv_values) / len(clv_values)

    # ── Разбивки ────────────────────────────────────────────────────
    def by_market(self) -> dict:
        groups = defaultdict(list)
        for r in self.resolved:
            groups[f"{r.market} {r.selection}"].append(r)
        return dict(groups)

    def by_league(self) -> dict:
        groups = defaultdict(list)
        for r in self.resolved:
            groups[r.league].append(r)
        return dict(groups)

    def by_edge_range(self) -> dict:
        buckets = {
            "<5%":    [],
            "5–10%":  [],
            "10–15%": [],
            "15–20%": [],
            ">20%":   [],
        }
        for r in self.resolved:
            e = r.edge * 100
            if   e < 5:   buckets["<5%"].append(r)
            elif e < 10:  buckets["5–10%"].append(r)
            elif e < 15:  buckets["10–15%"].append(r)
            elif e < 20:  buckets["15–20%"].append(r)
            else:         buckets[">20%"].append(r)
        return buckets

    def by_date(self) -> dict:
        groups = defaultdict(list)
        for r in self.resolved:
            groups[r.date].append(r)
        return dict(groups)


def _sub_stats(records: list[BetRecord]) -> str:
    """Однострочная сводка для подгруппы."""
    n = len(records)
    if not n: return "n=0"
    wins  = sum(1 for r in records if r.won)
    staked = sum(r.stake for r in records)
    profit = sum(r.profit for r in records)
    roi    = profit / staked * 100 if staked else 0
    return (f"n={n:3d}  W={wins:3d}  HR={wins/n:.0%}  "
            f"ROI={roi:+.1f}%  Net={profit:+.0f}")


def load_predictions(
    path: str         = PREDICTIONS_FILE,
    market_filter: str = "",
    league_filter: str = "",
    since: str         = "",
) -> BacktestResult:
    """Загружает predictions.json и строит BacktestResult."""
    result = BacktestResult()
    if not os.path.exists(path):
        return result
    with open(path, encoding="utf-8") as f:
        preds = json.load(f)

    for p in preds:
        date   = p.get("date", "")
        if since and date < since:
            continue
        league = p.get("league", "")
        if league_filter and league_filter.lower() not in league.lower():
            continue
        match  = f"{p.get('home','')} vs {p.get('away','')}"

        for sig in p.get("signals", []):
            mkt = sig.get("market", "")
            sel = sig.get("selection", "")
            if market_filter and market_filter.lower() not in mkt.lower():
                continue
            rec = BetRecord(
                date       = date,
                match      = match,
                league     = league,
                market     = mkt,
                selection  = sel,
                odds       = sig.get("bookmaker_odds", 0.0),
                stake      = sig.get("kelly_stake") or sig.get("stake") or 10.0,
                edge       = sig.get("edge", 0.0),
                model_prob = sig.get("model_prob", 0.0),
                won        = sig.get("won"),
            )
            result.records.append(rec)
    return result


def print_report(bt: BacktestResult, title: str = "ПОЛНЫЙ БЭКТЕСТ") -> None:
    """Печатает форматированный отчёт в консоль."""
    sep = "═" * 62
    print(f"\n{sep}")
    print(f"  {title}")
    print(sep)
    print(f"  Сигналов всего:    {len(bt.records)}")
    print(f"  С результатом:     {bt.n}")
    print(f"  Pending:           {len(bt.records) - bt.n}")
    if bt.n == 0:
        print("  Нет данных для расчёта")
        return

    print(f"\n  ── Основные метрики ─────────────────────────────────")
    print(f"  Hit Rate:          {bt.hit_rate:.1%}  ({bt.wins}W / {bt.n - bt.wins}L)")
    print(f"  ROI:               {bt.roi:+.2%}")
    print(f"  Yield:             {bt.yield_:+.1f}%")
    print(f"  Net profit:        {bt.total_profit:+.0f} ед.")
    print(f"  Total staked:      {bt.total_staked:.0f} ед.")
    print(f"  Avg odds:          {bt.avg_odds:.2f}")
    print(f"  Max Drawdown:      {bt.max_drawdown:.0f} ед.")
    print(f"  Sharpe Ratio:      {bt.sharpe_ratio:.2f}")
    clv = bt.clv()
    if not math.isnan(clv):
        print(f"  CLV:               {clv:+.2%}")
    else:
        print(f"  CLV:               — (нет closing odds)")

    # По рынкам
    print(f"\n  ── По рынкам ────────────────────────────────────────")
    for mkt, recs in sorted(bt.by_market().items(),
                             key=lambda x: -len(x[1]))[:12]:
        print(f"  {mkt[:35]:35s}  {_sub_stats(recs)}")

    # По лигам
    print(f"\n  ── По лигам ─────────────────────────────────────────")
    for league, recs in sorted(bt.by_league().items(),
                                key=lambda x: -len(x[1]))[:10]:
        print(f"  {league[:35]:35s}  {_sub_stats(recs)}")

    # По edge
    print(f"\n  ── По диапазонам edge ───────────────────────────────")
    for bucket, recs in bt.by_edge_range().items():
        if recs:
            print(f"  edge {bucket:8s}  {_sub_stats(recs)}")

    # Кумулятивная кривая (последние 10 дней)
    by_d = bt.by_date()
    if by_d:
        print(f"\n  ── Последние дни ────────────────────────────────────")
        cumul = 0.0
        for date in sorted(by_d.keys())[-10:]:
            recs   = by_d[date]
            day_p  = sum(r.profit for r in recs)
            cumul += day_p
            bar = "▓" * min(20, int(abs(cumul) / 20))
            sign = "+" if cumul >= 0 else ""
            print(f"  {date}  {day_p:+6.0f}  cumul={sign}{cumul:.0f}  {bar}")

    print(f"\n{sep}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Betting bot backtest")
    parser.add_argument("--market",  default="", help="Фильтр по рынку")
    parser.add_argument("--league",  default="", help="Фильтр по лиге")
    parser.add_argument("--since",   default="", help="С даты YYYY-MM-DD")
    parser.add_argument("--file",    default=PREDICTIONS_FILE)
    args = parser.parse_args()

    bt = load_predictions(
        path           = args.file,
        market_filter  = args.market,
        league_filter  = args.league,
        since          = args.since,
    )

    title = "ПОЛНЫЙ БЭКТЕСТ"
    if args.market: title += f" | рынок: {args.market}"
    if args.league: title += f" | лига: {args.league}"
    if args.since:  title += f" | с {args.since}"

    print_report(bt, title)
