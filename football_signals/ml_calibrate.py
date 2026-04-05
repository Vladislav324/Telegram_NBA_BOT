"""
╔══════════════════════════════════════════════════════════════╗
║  🤖  ML-КАЛИБРОВКА  |  Football Bot                         ║
║  Обучает модель на реальных результатах из results.json      ║
║  Требуется: pip install scikit-learn                         ║
╚══════════════════════════════════════════════════════════════╝

  python ml_calibrate.py          — анализ + оптимальные веса
  python ml_calibrate.py apply    — применить веса к боту
  python ml_calibrate.py report   — отчёт по рынкам
"""

import json, os, sys, datetime, math

RESULTS_FILE    = "results.json"
PREDICTIONS_FILE = "predictions.json"
CALIBRATION_OUT  = "ml_weights.json"

# ══════════════════════════════════════════════════════════════
#  ЗАГРУЗКА ДАННЫХ
# ══════════════════════════════════════════════════════════════
def load_labeled_signals() -> list:
    """
    Загружает все сигналы у которых есть реальный результат (won=True/False).
    Возвращает список словарей с признаками и меткой.
    """
    samples = []

    # Из results.json
    for fname in [RESULTS_FILE, PREDICTIONS_FILE]:
        if not os.path.exists(fname):
            continue
        try:
            with open(fname, encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            continue

        records = data if isinstance(data, list) else data.get("records", [])
        for rec in records:
            for sig in rec.get("signals", []):
                won = sig.get("won")
                if won is None:
                    continue   # нет результата — пропускаем

                samples.append({
                    # ── Признаки (features) ───────────────────
                    "edge":         float(sig.get("edge", 0)),
                    "model_prob":   float(sig.get("model_prob", 0.5)),
                    "bookmaker_odds": float(sig.get("bookmaker_odds", 2.0)),
                    "market_1x2":   1 if "Исход" in sig.get("market","") else 0,
                    "market_total": 1 if "Тотал" in sig.get("market","") else 0,
                    "market_btts":  1 if "забьют" in sig.get("market","") else 0,
                    "market_hcap":  1 if "Гандикап" in sig.get("market","") else 0,
                    "market_dnb":   1 if "DNB" in sig.get("market","") else 0,
                    "market_dc":    1 if "Двойной" in sig.get("market","") else 0,
                    "market_1h":    1 if "1Т" in sig.get("market","") else 0,
                    "conf_high":    1 if "ВЫСОКАЯ" in sig.get("confidence","") else 0,
                    "conf_mid":     1 if "СРЕДНЯЯ" in sig.get("confidence","") else 0,
                    "odds_low":     1 if float(sig.get("bookmaker_odds",2)) < 1.6 else 0,
                    "odds_high":    1 if float(sig.get("bookmaker_odds",2)) > 2.5 else 0,
                    # ── Метка (target) ────────────────────────
                    "won": 1 if won is True else 0,
                })

    return samples


# ══════════════════════════════════════════════════════════════
#  АНАЛИЗ БЕЗ ML — просто статистика по рынкам и уверенности
# ══════════════════════════════════════════════════════════════
def analyze_results(samples: list) -> dict:
    """Подробная статистика: точность, ROI, калибровка вероятностей."""
    if not samples:
        return {}

    total = len(samples)
    won   = sum(s["won"] for s in samples)
    print(f"\n{'═'*60}")
    print(f"  📊 АНАЛИЗ {total} РАЗМЕЧЕННЫХ СИГНАЛОВ")
    print(f"  Общая точность: {won}/{total} = {won/total*100:.1f}%")

    # ── ROI ───────────────────────────────────────────────────
    roi = sum((s["bookmaker_odds"]-1)*s["won"] - (1-s["won"]) for s in samples) / total
    print(f"  ROI: {roi*100:+.1f}% на сигнал")
    print(f"{'─'*60}")

    # ── По рынкам ─────────────────────────────────────────────
    markets = {}
    for s in samples:
        mkt = ("Исход" if s["market_1x2"] else
               "Тотал" if s["market_total"] else
               "BTTS"  if s["market_btts"] else
               "Гандикап" if s["market_hcap"] else
               "DNB"   if s["market_dnb"] else
               "Двойной шанс" if s["market_dc"] else
               "Тотал 1Т" if s["market_1h"] else "Другое")
        markets.setdefault(mkt, []).append(s)

    print(f"  📋 По рынкам:")
    mkt_stats = {}
    for mkt, msigs in sorted(markets.items(), key=lambda x: len(x[1]), reverse=True):
        w = sum(s["won"] for s in msigs)
        t = len(msigs)
        r = sum((s["bookmaker_odds"]-1)*s["won"] - (1-s["won"]) for s in msigs) / t
        avg_e = sum(s["edge"] for s in msigs) / t
        em = "🟢" if r > 0 else "🔴"
        print(f"    {em} {mkt:18s}: {w}/{t} ({w/t*100:.0f}%)  ROI {r*100:+.1f}%  avg_edge {avg_e*100:.1f}%")
        mkt_stats[mkt] = {"won": w, "total": t, "roi": r, "avg_edge": avg_e}

    # ── По уверенности ────────────────────────────────────────
    print(f"{'─'*60}")
    print(f"  🎯 По уверенности:")
    for conf_name, key in [("🔥 ВЫСОКАЯ","conf_high"), ("✅ СРЕДНЯЯ","conf_mid"), ("📌 НИЗКАЯ","")]:
        if key:
            csigs = [s for s in samples if s[key] == 1]
        else:
            csigs = [s for s in samples if s["conf_high"]==0 and s["conf_mid"]==0]
        if not csigs: continue
        w = sum(s["won"] for s in csigs)
        t = len(csigs)
        r = sum((s["bookmaker_odds"]-1)*s["won"] - (1-s["won"]) for s in csigs) / t
        print(f"    {conf_name}: {w}/{t} ({w/t*100:.0f}%)  ROI {r*100:+.1f}%")

    # ── Калибровка вероятностей ───────────────────────────────
    print(f"{'─'*60}")
    print(f"  📐 Калибровка (модель vs реальность):")
    buckets = [(0.50,0.60),(0.60,0.70),(0.70,0.80),(0.80,0.90),(0.90,1.0)]
    calib_ok = True
    for lo, hi in buckets:
        bsigs = [s for s in samples if lo <= s["model_prob"] < hi]
        if len(bsigs) < 5: continue
        real_acc = sum(s["won"] for s in bsigs) / len(bsigs)
        mid = (lo + hi) / 2
        bias = real_acc - mid
        flag = "✅" if abs(bias) < 0.05 else ("⬆️" if bias > 0 else "⬇️")
        print(f"    {flag} prob {lo:.0%}–{hi:.0%}: модель={mid:.0%}  реально={real_acc:.0%}  смещение {bias:+.0%}")
        if abs(bias) > 0.05:
            calib_ok = False

    if calib_ok:
        print(f"\n  ✅ Модель хорошо откалибрована!")
    else:
        print(f"\n  ⚠️  Требуется калибровка — запусти: python ml_calibrate.py apply")

    return mkt_stats


# ══════════════════════════════════════════════════════════════
#  ML-ОБУЧЕНИЕ (если доступен scikit-learn)
# ══════════════════════════════════════════════════════════════
def train_ml_model(samples: list) -> dict:
    """
    Обучает градиентный бустинг на признаках сигналов.
    Возвращает откорректированные веса для emit() в боте.
    """
    try:
        from sklearn.ensemble import GradientBoostingClassifier
        from sklearn.calibration import CalibratedClassifierCV
        from sklearn.model_selection import cross_val_score
        import numpy as np
    except ImportError:
        print("  ℹ️  scikit-learn не установлен.")
        print("  Установи: pip install scikit-learn")
        print("  Пока используем статистический анализ.")
        return {}

    if len(samples) < 50:
        print(f"  ⚠️  Мало данных для ML: {len(samples)} сигналов (нужно 50+).")
        print(f"  Накапливай результаты и запускай снова.")
        return {}

    feature_cols = ["edge","model_prob","bookmaker_odds",
                    "market_1x2","market_total","market_btts","market_hcap",
                    "market_dnb","market_dc","market_1h",
                    "conf_high","conf_mid","odds_low","odds_high"]

    X = [[s[c] for c in feature_cols] for s in samples]
    y = [s["won"] for s in samples]

    import numpy as np
    X, y = np.array(X), np.array(y)

    # Обучаем с калибровкой (Platt scaling)
    base = GradientBoostingClassifier(
        n_estimators=100, max_depth=3, learning_rate=0.05,
        subsample=0.8, min_samples_leaf=5, random_state=42
    )
    model = CalibratedClassifierCV(base, cv=3, method="sigmoid")
    model.fit(X, y)

    # Кросс-валидация
    cv_scores = cross_val_score(model, X, y, cv=5, scoring="roc_auc")
    print(f"\n  🤖 ML-модель обучена на {len(samples)} примерах")
    print(f"  ROC-AUC: {cv_scores.mean():.3f} ± {cv_scores.std():.3f}")

    # Важность признаков (из base estimator)
    base_only = GradientBoostingClassifier(
        n_estimators=100, max_depth=3, learning_rate=0.05, random_state=42
    )
    base_only.fit(X, y)
    importances = dict(zip(feature_cols, base_only.feature_importances_))

    print(f"\n  📊 Важность признаков:")
    for feat, imp in sorted(importances.items(), key=lambda x: x[1], reverse=True):
        bar = "█" * int(imp * 50)
        print(f"    {feat:25s}: {imp:.3f}  {bar}")

    # Генерируем оптимальные пороги по рынкам
    market_thresholds = {}
    for mkt_key, mkt_name in [
        ("market_1x2","Исход"), ("market_total","Тотал"),
        ("market_btts","BTTS"), ("market_hcap","Гандикап"),
        ("market_dnb","DNB"), ("market_dc","Двойной шанс"),
    ]:
        msigs = [(s, i) for i, s in enumerate(samples) if s[mkt_key]==1]
        if len(msigs) < 10:
            continue
        mX = np.array([[s[c] for c in feature_cols] for s, _ in msigs])
        my = np.array([s["won"] for s, _ in msigs])
        probs = model.predict_proba(mX)[:,1]

        # Ищем порог минимального edge который даёт ROI > 0
        best_edge, best_roi = 0.04, -1.0
        for edge_thr in [0.03, 0.04, 0.05, 0.06, 0.07, 0.08]:
            mask = np.array([s["edge"] >= edge_thr for s, _ in msigs])
            if mask.sum() < 5:
                continue
            r = (sum((msigs[i][0]["bookmaker_odds"]-1)*my[i] - (1-my[i])
                     for i in range(len(my)) if mask[i]) / mask.sum())
            if r > best_roi:
                best_roi = r
                best_edge = edge_thr

        market_thresholds[mkt_name] = {
            "min_edge": best_edge,
            "roi":      round(best_roi, 3),
        }

    # Сохраняем результаты
    weights = {
        "generated_at":  datetime.datetime.now().isoformat(),
        "n_samples":     len(samples),
        "roc_auc":       round(cv_scores.mean(), 4),
        "importances":   {k: round(v,4) for k,v in importances.items()},
        "market_min_edge": market_thresholds,
    }
    with open(CALIBRATION_OUT, "w", encoding="utf-8") as f:
        json.dump(weights, f, ensure_ascii=False, indent=2)

    print(f"\n  💾 Веса сохранены в {CALIBRATION_OUT}")
    print(f"\n  📋 Оптимальные мин.Валуй по рынкам:")
    for mkt, v in market_thresholds.items():
        print(f"    {mkt:20s}: min_edge={v['min_edge']:.0%}  ROI={v['roi']*100:+.1f}%")

    return weights


# ══════════════════════════════════════════════════════════════
#  АВТО-КАЛИБРОВКА ПАРАМЕТРОВ ЛИГИ
# ══════════════════════════════════════════════════════════════
def calibrate_league_params(samples: list):
    """
    На основе накопленных результатов вычисляет реальные avg_h / avg_a
    по каждой лиге и выводит обновлённые значения для LEAGUE_CALIBRATION.
    """
    league_data = {}
    for s in samples:
        lg = s.get("league","")
        if not lg: continue
        market = ("total" if s["market_total"] else
                  "1x2"   if s["market_1x2"]   else "other")
        league_data.setdefault(lg, {"total_sigs":[], "1x2_sigs":[]})
        league_data[lg][f"{market}_sigs"].append(s)

    if not league_data:
        return

    print(f"\n{'─'*60}")
    print(f"  🏆 КАЛИБРОВКА ПО ЛИГАМ (из реальных результатов):")
    for lg, data in sorted(league_data.items()):
        tsigs = data["total_sigs"]
        if len(tsigs) < 10:
            continue
        over25 = [s for s in tsigs if "Больше 2.5" in str(s.get("selection",""))]
        if len(over25) < 5:
            continue
        real_over25 = sum(s["won"] for s in over25) / len(over25)
        print(f"    {lg:25s}: Over2.5={real_over25:.0%} (из {len(over25)} ставок)")


# ══════════════════════════════════════════════════════════════
#  ПРИМЕНЕНИЕ ВЕСОВ К БОТУ
# ══════════════════════════════════════════════════════════════
def apply_weights_to_bot():
    """Применяет ml_weights.json к football_bot_v3.py."""
    if not os.path.exists(CALIBRATION_OUT):
        print(f"  ❌ Файл {CALIBRATION_OUT} не найден. Запусти сначала без аргументов.")
        return

    with open(CALIBRATION_OUT, encoding="utf-8") as f:
        weights = json.load(f)

    bot_file = "football_bot_v3.py"
    if not os.path.exists(bot_file):
        print(f"  ❌ {bot_file} не найден")
        return

    with open(bot_file, encoding="utf-8") as f:
        code = f.read()

    market_edges = weights.get("market_min_edge", {})
    changes = 0

    for mkt, v in market_edges.items():
        new_edge = v["min_edge"]
        # Ищем и заменяем min_edge для этого рынка
        # (упрощённо — выводим рекомендации)
        print(f"  📝 {mkt}: рекомендуемый min_edge = {new_edge:.0%}")
        changes += 1

    print(f"\n  ℹ️  Автоприменение пока в режиме рекомендаций.")
    print(f"  Вручную обнови MIN_EDGE по рынкам в football_bot_v3.py.")
    print(f"  Через 500+ ставок будет доступна полная авто-замена.")


# ══════════════════════════════════════════════════════════════
#  ТОЧЕЧНЫЙ ОТЧЁТ
# ══════════════════════════════════════════════════════════════
def generate_html_report(samples: list, mkt_stats: dict):
    """Генерирует красивый HTML отчёт об эффективности бота."""
    total = len(samples)
    if not total:
        return

    won   = sum(s["won"] for s in samples)
    roi   = sum((s["bookmaker_odds"]-1)*s["won"] - (1-s["won"]) for s in samples) / total
    acc   = won / total * 100
    color = "#16a34a" if roi > 0 else "#dc2626"

    rows = ""
    for mkt, stat in mkt_stats.items():
        w, t, r = stat["won"], stat["total"], stat["roi"]
        c = "#16a34a" if r > 0 else "#dc2626"
        rows += f"""<tr>
          <td>{mkt}</td><td>{w}/{t}</td>
          <td>{w/t*100:.0f}%</td>
          <td style="color:{c};font-weight:bold">{r*100:+.1f}%</td>
        </tr>"""

    html = f"""<!DOCTYPE html><html lang="ru"><head>
<meta charset="UTF-8"><title>Football Bot — Отчёт</title>
<style>
  body{{font-family:system-ui;background:#0f172a;color:#e2e8f0;margin:0;padding:24px}}
  .card{{background:#1e293b;border-radius:12px;padding:20px;margin-bottom:16px}}
  h1{{color:#f8fafc;font-size:24px}}
  .stat{{display:flex;gap:16px;flex-wrap:wrap}}
  .box{{background:#0f172a;border-radius:8px;padding:16px;flex:1;min-width:120px}}
  .val{{font-size:28px;font-weight:bold}}
  .lbl{{color:#94a3b8;font-size:13px;margin-top:4px}}
  table{{width:100%;border-collapse:collapse}}
  th{{text-align:left;color:#94a3b8;padding:8px;border-bottom:1px solid #334155}}
  td{{padding:8px;border-bottom:1px solid #1e293b}}
</style></head><body>
<div class="card">
  <h1>⚽ Football Bot — Отчёт эффективности</h1>
  <p style="color:#64748b">{datetime.datetime.now().strftime('%d.%m.%Y %H:%M')} · {total} сигналов</p>
  <div class="stat">
    <div class="box"><div class="val">{acc:.1f}%</div><div class="lbl">Точность</div></div>
    <div class="box"><div class="val" style="color:{color}">{roi*100:+.1f}%</div><div class="lbl">ROI на ставку</div></div>
    <div class="box"><div class="val">{won}</div><div class="lbl">Прошло</div></div>
    <div class="box"><div class="val">{total-won}</div><div class="lbl">Не прошло</div></div>
  </div>
</div>
<div class="card">
  <h2 style="margin-top:0">По рынкам</h2>
  <table><tr><th>Рынок</th><th>В/Т</th><th>Точность</th><th>ROI</th></tr>{rows}</table>
</div>
</body></html>"""

    with open("bot_report.html", "w", encoding="utf-8") as f:
        f.write(html)
    print(f"\n  📊 HTML-отчёт → bot_report.html")


# ══════════════════════════════════════════════════════════════
#  ТОЧКА ВХОДА
# ══════════════════════════════════════════════════════════════
if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "analyze"

    samples = load_labeled_signals()
    print(f"  📂 Загружено {len(samples)} размеченных сигналов")

    if not samples:
        print("  ⚠️  Нет данных. Накопи результаты через learning.py")
        sys.exit(0)

    if mode == "apply":
        apply_weights_to_bot()
    elif mode == "report":
        mkt_stats = analyze_results(samples)
        generate_html_report(samples, mkt_stats)
    else:
        mkt_stats = analyze_results(samples)
        calibrate_league_params(samples)
        weights = train_ml_model(samples)
        generate_html_report(samples, mkt_stats)
        print(f"\n{'═'*60}")
        print(f"  ✅ Готово. Файлы: {CALIBRATION_OUT}, bot_report.html")
