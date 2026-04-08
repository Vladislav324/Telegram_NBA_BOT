"""
ml_calibrate.py — Калибровка ML-модели и XGBoost второй уровень.

Функции:
  1. Platt calibration — корректирует сырые вероятности Пуассон-модели
  2. XGBoost второй уровень — дополнительный предиктор на реальных данных
  3. Метрики калибровки — Brier Score, ECE, reliability diagram
  4. Автообновление ml_weights.json

Usage:
    python ml_calibrate.py           — полная калибровка
    python ml_calibrate.py --xgb     — только XGBoost
    python ml_calibrate.py --platt   — только Platt
    python ml_calibrate.py --report  — только отчёт без обновления
"""

from __future__ import annotations

import argparse
import json
import math
import os
from collections import defaultdict
from dataclasses import dataclass
from typing import Optional

PREDICTIONS_FILE = "predictions.json"
ML_WEIGHTS_FILE  = "ml_weights.json"
MIN_SAMPLES      = 50  # минимум матчей для калибровки


# ── Структуры данных ────────────────────────────────────────────────
@dataclass
class CalibPoint:
    model_prob: float
    actual_won: int
    market:     str
    league:     str
    edge:       float
    odds:       float


# ── Загрузка данных ─────────────────────────────────────────────────
def load_calibration_data(path: str = PREDICTIONS_FILE) -> list[CalibPoint]:
    """Загружает и нормализует данные для калибровки."""
    points = []
    if not os.path.exists(path):
        return points
    with open(path, encoding="utf-8") as f:
        preds = json.load(f)
    for p in preds:
        league = p.get("league", "")
        for sig in p.get("signals", []):
            if sig.get("won") is None:
                continue
            points.append(CalibPoint(
                model_prob = float(sig.get("model_prob", 0.5)),
                actual_won = int(bool(sig.get("won"))),
                market     = sig.get("market", ""),
                league     = league,
                edge       = float(sig.get("edge", 0)),
                odds       = float(sig.get("bookmaker_odds", 2.0)),
            ))
    return points


# ── Platt Calibration ────────────────────────────────────────────────
def platt_calibrate(points: list[CalibPoint]) -> tuple[float, float]:
    """
    Логистическая регрессия: P_calibrated = 1 / (1 + exp(a * p + b)).
    Возвращает (a, b) — параметры Platt scaling.
    Использует градиентный спуск без внешних зависимостей.
    """
    if len(points) < MIN_SAMPLES:
        return 1.0, 0.0

    probs = [p.model_prob for p in points]
    y     = [p.actual_won for p in points]

    a, b = 1.0, 0.0
    lr   = 0.01
    n    = len(probs)

    for _ in range(500):
        da = db = 0.0
        for pi, yi in zip(probs, y):
            s  = 1.0 / (1.0 + math.exp(a * pi + b))
            e  = s - yi
            da += e * pi
            db += e
        a -= lr * da / n
        b -= lr * db / n

    return round(a, 4), round(b, 4)


def apply_platt(prob: float, a: float, b: float) -> float:
    """Применяет Platt calibration к вероятности."""
    try:
        return 1.0 / (1.0 + math.exp(a * prob + b))
    except (OverflowError, ZeroDivisionError):
        return prob


# ── Brier Score ──────────────────────────────────────────────────────
def brier_score(points: list[CalibPoint], a: float = 1.0, b: float = 0.0) -> float:
    """Brier Score = среднее (p_cal - y)^2. Чем меньше — тем лучше."""
    if not points:
        return 1.0
    total = sum(
        (apply_platt(p.model_prob, a, b) - p.actual_won) ** 2
        for p in points
    )
    return total / len(points)


# ── Expected Calibration Error ───────────────────────────────────────
def expected_calibration_error(
    points: list[CalibPoint],
    a: float = 1.0,
    b: float = 0.0,
    n_bins: int = 10,
) -> float:
    """ECE = взвешенное абс. отклонение вероятности от реального WR по бинам."""
    bins = defaultdict(lambda: {"count": 0, "wins": 0, "prob_sum": 0.0})
    for p in points:
        cal = apply_platt(p.model_prob, a, b)
        bin_idx = min(int(cal * n_bins), n_bins - 1)
        bins[bin_idx]["count"]    += 1
        bins[bin_idx]["wins"]     += p.actual_won
        bins[bin_idx]["prob_sum"] += cal
    n = len(points)
    if n == 0:
        return 1.0
    ece = 0.0
    for bn in bins.values():
        cnt = bn["count"]
        if cnt == 0: continue
        avg_prob = bn["prob_sum"] / cnt
        actual_wr = bn["wins"] / cnt
        ece += (cnt / n) * abs(avg_prob - actual_wr)
    return round(ece, 4)


# ── XGBoost второй уровень ───────────────────────────────────────────
def train_xgboost_layer(points: list[CalibPoint]) -> Optional[dict]:
    """
    Тренирует XGBoost как второй уровень поверх модели Пуассона.
    Features: model_prob, edge, odds, league_encoded, market_encoded.
    Target: won (0/1).

    Возвращает dict с параметрами для сохранения в ml_weights.json
    или None если XGBoost недоступен или мало данных.
    """
    if len(points) < MIN_SAMPLES * 2:
        print(f"  XGBoost: мало данных ({len(points)} < {MIN_SAMPLES * 2})")
        return None

    try:
        import xgboost as xgb
        import numpy as np
    except ImportError:
        print("  XGBoost: не установлен (pip install xgboost)")
        return None

    # Кодируем категориальные признаки
    leagues = sorted(set(p.league for p in points))
    markets = sorted(set(p.market for p in points))
    lg_map  = {lg: i for i, lg in enumerate(leagues)}
    mk_map  = {mk: i for i, mk in enumerate(markets)}

    X = np.array([
        [
            p.model_prob,
            p.edge,
            p.odds,
            lg_map.get(p.league, -1),
            mk_map.get(p.market, -1),
        ]
        for p in points
    ], dtype=np.float32)
    y = np.array([p.actual_won for p in points], dtype=np.float32)

    # Train / val split (80/20)
    n_train = int(len(X) * 0.8)
    X_tr, X_val = X[:n_train], X[n_train:]
    y_tr, y_val = y[:n_train], y[n_train:]

    model = xgb.XGBClassifier(
        n_estimators     = 100,
        max_depth        = 4,
        learning_rate    = 0.05,
        subsample        = 0.8,
        colsample_bytree = 0.8,
        use_label_encoder= False,
        eval_metric      = "logloss",
        verbosity        = 0,
    )
    model.fit(
        X_tr, y_tr,
        eval_set=[(X_val, y_val)],
        verbose=False,
    )

    # Качество на валидации
    preds_val = model.predict_proba(X_val)[:, 1]
    bs_val    = float(np.mean((preds_val - y_val) ** 2))
    bs_base   = float(np.mean((X_val[:, 0] - y_val) ** 2))  # Пуассон
    improvement = (bs_base - bs_val) / bs_base * 100

    print(f"  XGBoost: Brier base={bs_base:.4f} → xgb={bs_val:.4f} "
          f"(улучшение {improvement:+.1f}%)")

    # Сохраняем параметры (не саму модель — только feature importances)
    importances = model.feature_importances_.tolist()
    return {
        "type":          "xgboost",
        "n_samples":     len(points),
        "brier_base":    round(bs_base, 4),
        "brier_xgb":     round(bs_val, 4),
        "improvement_pct": round(improvement, 1),
        "feature_importances": {
            "model_prob": round(importances[0], 3),
            "edge":       round(importances[1], 3),
            "odds":       round(importances[2], 3),
            "league":     round(importances[3], 3),
            "market":     round(importances[4], 3),
        },
        "leagues": leagues,
        "markets": markets,
        "note": "XGBoost weight = 0.15 (supplement to Poisson model)",
    }


# ── Reliability diagram (текстовый) ──────────────────────────────────
def print_reliability_diagram(
    points: list[CalibPoint],
    a: float = 1.0,
    b: float = 0.0,
) -> None:
    """Текстовая версия reliability diagram."""
    bins = defaultdict(lambda: {"cnt": 0, "wins": 0, "prob": 0.0})
    for p in points:
        cal = apply_platt(p.model_prob, a, b)
        bi  = min(int(cal * 10), 9)
        bins[bi]["cnt"]  += 1
        bins[bi]["wins"] += p.actual_won
        bins[bi]["prob"] += cal

    print("  Prob range  | WR реальный | N   | Калибр?")
    print("  " + "─" * 46)
    for i in range(10):
        lo = i * 10; hi = lo + 10
        bn = bins.get(i, {"cnt": 0, "wins": 0, "prob": 0.0})
        cnt = bn["cnt"]
        if cnt == 0:
            continue
        real_wr   = bn["wins"] / cnt
        avg_prob  = bn["prob"] / cnt
        diff      = real_wr - avg_prob
        ok        = "✅" if abs(diff) < 0.05 else ("⚠️ " if abs(diff) < 0.10 else "❌")
        bar = "█" * int(real_wr * 10)
        print(f"  {lo:2d}–{hi:2d}%     | {real_wr:6.1%}       | {cnt:3d} | {ok} {diff:+.1%}  {bar}")


# ── Калибровка по рынкам ─────────────────────────────────────────────
def calibrate_by_market(points: list[CalibPoint]) -> dict:
    """
    Platt calibration отдельно для каждого рынка.
    Возвращает dict {market: (a, b, n_samples, brier)}.
    """
    by_market = defaultdict(list)
    for p in points:
        by_market[p.market].append(p)

    result = {}
    for market, mpts in by_market.items():
        if len(mpts) < 20:
            continue
        a, b  = platt_calibrate(mpts)
        brier = brier_score(mpts, a, b)
        result[market] = {
            "a": a, "b": b,
            "n": len(mpts),
            "brier": round(brier, 4),
            "wr": round(sum(p.actual_won for p in mpts) / len(mpts), 3),
        }
    return result


# ── Сохранение весов ─────────────────────────────────────────────────
def save_weights(platt_a: float, platt_b: float,
                 market_calib: dict,
                 xgb_info: Optional[dict],
                 ece: float, brier: float) -> None:
    """Обновляет ml_weights.json."""
    existing = {}
    if os.path.exists(ML_WEIGHTS_FILE):
        try:
            with open(ML_WEIGHTS_FILE, encoding="utf-8") as f:
                existing = json.load(f)
        except Exception:
            pass

    existing.update({
        "platt_a":      platt_a,
        "platt_b":      platt_b,
        "ece":          ece,
        "brier_score":  brier,
        "market_calib": market_calib,
        "xgboost":      xgb_info,
        "updated_at":   __import__("datetime").datetime.now().isoformat(),
    })
    with open(ML_WEIGHTS_FILE, "w", encoding="utf-8") as f:
        json.dump(existing, f, ensure_ascii=False, indent=2)
    print(f"  ✅ {ML_WEIGHTS_FILE} обновлён")


# ── Main ─────────────────────────────────────────────────────────────
def main(run_xgb: bool = True, run_platt: bool = True,
         report_only: bool = False) -> None:
    sep = "═" * 58
    print(f"\n{sep}")
    print("  ML CALIBRATE")
    print(sep)

    points = load_calibration_data()
    print(f"\n  Загружено точек: {len(points)}")
    if len(points) < MIN_SAMPLES:
        print(f"  Недостаточно данных (нужно ≥{MIN_SAMPLES})")
        return

    wins = sum(p.actual_won for p in points)
    print(f"  WR базовый:  {wins / len(points):.1%}  ({wins}W / {len(points) - wins}L)")

    # ── Platt calibration ──────────────────────────────────────────
    a, b = 1.0, 0.0
    if run_platt:
        print(f"\n  ── Platt calibration ─────────────────────────────")
        a, b = platt_calibrate(points)
        brier_before = brier_score(points, 1.0, 0.0)
        brier_after  = brier_score(points, a, b)
        ece_before   = expected_calibration_error(points, 1.0, 0.0)
        ece_after    = expected_calibration_error(points, a, b)
        print(f"  Platt: a={a}  b={b}")
        print(f"  Brier: {brier_before:.4f} → {brier_after:.4f}  "
              f"({'улучш' if brier_after < brier_before else 'ухудш'})")
        print(f"  ECE:   {ece_before:.4f} → {ece_after:.4f}")
        print(f"\n  Reliability diagram (после калибровки):")
        print_reliability_diagram(points, a, b)
    else:
        brier_after = brier_score(points)
        ece_after   = expected_calibration_error(points)

    # ── По рынкам ──────────────────────────────────────────────────
    print(f"\n  ── Калибровка по рынкам ──────────────────────────")
    market_calib = calibrate_by_market(points)
    for mkt, mc in sorted(market_calib.items(), key=lambda x: -x[1]["n"]):
        print(f"  {mkt:32s}  n={mc['n']:3d}  WR={mc['wr']:.0%}  "
              f"a={mc['a']:.2f}  b={mc['b']:.2f}  Brier={mc['brier']:.4f}")

    # ── XGBoost ────────────────────────────────────────────────────
    xgb_info = None
    if run_xgb:
        print(f"\n  ── XGBoost второй уровень ────────────────────────")
        xgb_info = train_xgboost_layer(points)
        if xgb_info:
            print(f"  Feature importances:")
            for feat, imp in xgb_info["feature_importances"].items():
                bar = "█" * int(imp * 20)
                print(f"    {feat:15s} {imp:.3f}  {bar}")

    # ── Рекомендации ───────────────────────────────────────────────
    print(f"\n  ── Рекомендации ──────────────────────────────────")
    for mkt, mc in sorted(market_calib.items(), key=lambda x: -x[1]["n"]):
        wr = mc["wr"]
        if wr < 0.45 and mc["n"] >= 20:
            print(f"  ⚠️  {mkt}: WR={wr:.0%} — рассмотри увеличение min_edge")
        elif wr > 0.65 and mc["n"] >= 10:
            print(f"  ✅ {mkt}: WR={wr:.0%} — можно снизить порог")

    # ── Сохраняем ─────────────────────────────────────────────────
    if not report_only:
        print(f"\n  ── Сохранение ───────────────────────────────────")
        save_weights(a, b, market_calib, xgb_info, ece_after, brier_after)

    print(f"\n{sep}")
    print(f"  Готово. Перезапусти football_bot_v3.py для применения.")
    print(f"  Следующая калибровка: через 2 недели или при WR<50% 5 дней.")
    print(sep)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="ML calibration")
    parser.add_argument("--xgb",    action="store_true", help="Только XGBoost")
    parser.add_argument("--platt",  action="store_true", help="Только Platt")
    parser.add_argument("--report", action="store_true", help="Только отчёт")
    args = parser.parse_args()

    main(
        run_xgb    = args.xgb or (not args.platt and not args.report),
        run_platt  = args.platt or (not args.xgb and not args.report),
        report_only= args.report,
    )
