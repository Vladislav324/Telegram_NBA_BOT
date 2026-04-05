#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════╗
║    ⚡  LIVE MONITOR  —  мониторинг активных ставок          ║
║  Проверяет счёт каждые 10 мин. Алертит если матч идёт       ║
║  против сигнала. Рекомендует досрочный выход.               ║
╚══════════════════════════════════════════════════════════════╝
  python live_monitor.py        — запустить мониторинг
"""
import json, time, datetime, urllib.request, urllib.parse, os, ssl, sys

# Подключаем лайв-анализ из основного бота
try:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from football_bot_v3 import analyze_live_team, format_live_analysis
    _LIVE_ANALYSIS_AVAILABLE = True
except Exception:
    _LIVE_ANALYSIS_AVAILABLE = False

API_FOOTBALL_KEY = "33d9e41279e34866b001ab44dade2540"
TELEGRAM_TOKEN   = "8263616332:AAGGJwEnlJSy160VlpaLcN2v8bbJ3hpf7gA"
TELEGRAM_CHAT_ID = "-1003885532223"
PREDICTIONS_FILE = "predictions.json"
CHECK_INTERVAL   = 600   # 10 минут

def _ssl():
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode    = ssl.CERT_NONE
    return ctx

def _tg(text: str):
    url  = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    body = json.dumps({"chat_id": TELEGRAM_CHAT_ID, "text": text,
                       "parse_mode": "HTML"}).encode()
    req  = urllib.request.Request(url, data=body,
                                   headers={"Content-Type": "application/json"})
    try:
        urllib.request.urlopen(req, timeout=10, context=_ssl())
    except Exception:
        pass

def _af(endpoint, params):
    qs  = urllib.parse.urlencode({k:v for k,v in params.items() if v})
    url = f"https://v3.football.api-sports.io/{endpoint}?{qs}"
    req = urllib.request.Request(url, headers={"x-apisports-key": API_FOOTBALL_KEY})
    try:
        with urllib.request.urlopen(req, timeout=12, context=_ssl()) as r:
            d = json.load(r)
            return d.get("response", [])
    except Exception:
        return []

def get_live_score(fixture_id: int) -> dict:
    """Текущий счёт, минута, статус."""
    resp = _af("fixtures", {"id": fixture_id})
    if not resp:
        return {}
    fix  = resp[0]
    st   = fix.get("fixture", {}).get("status", {})
    goal = fix.get("goals", {})
    return {
        "status":  st.get("short", ""),
        "elapsed": st.get("elapsed") or 0,
        "home":    goal.get("home") or 0,
        "away":    goal.get("away") or 0,
    }

def load_todays_predictions() -> list:
    """Загружает прогнозы за сегодня у которых нет результата."""
    today = datetime.date.today().isoformat()
    try:
        if not os.path.exists(PREDICTIONS_FILE):
            return []
        with open(PREDICTIONS_FILE, encoding="utf-8") as f:
            all_preds = json.load(f)
    except Exception:
        return []
    return [p for p in all_preds
            if p.get("date") == today
            and not p.get("result")
            and p.get("signals")]

def evaluate_signal_live(sig: dict, score: dict) -> str:
    """
    Оценивает сигнал по текущему счёту.
    Возвращает: "ok" / "danger" / "dead" / "pending"
    """
    market    = sig.get("market","")
    selection = sig.get("selection","")
    hg, ag    = score.get("home",0), score.get("away",0)
    elapsed   = score.get("elapsed",0)

    if score.get("status") in ("FT","AET"):
        return "finished"

    if "Исход" in market:
        if "хозяев" in selection:
            if hg > ag + 1: return "ok"
            if ag > hg:     return "danger" if elapsed < 70 else "dead"
        elif "гостей" in selection:
            if ag > hg + 1: return "ok"
            if hg > ag:     return "danger" if elapsed < 70 else "dead"
        elif "Ничья" in selection:
            if abs(hg-ag) > 1 and elapsed > 60: return "dead"

    elif "Тотал" in market:
        total = hg + ag
        if "Больше" in selection:
            line = float(selection.split()[-1])
            remaining = (90 - elapsed) / 90
            # Если нужно ещё X голов, а ожидаемый темп не позволяет
            needed = line - total
            expected_more = remaining * (line * 0.9)
            if needed > 0 and expected_more < needed * 0.6 and elapsed > 60:
                return "danger"
            if total > line: return "ok"
        elif "Меньше" in selection:
            line = float(selection.split()[-1])
            if total >= line: return "dead"
            if total == line - 1 and elapsed > 70: return "danger"

    elif "DNB" in market:
        if "Хозяева" in selection and ag > hg and elapsed > 70: return "dead"
        if "Гости" in selection and hg > ag and elapsed > 70: return "dead"

    return "pending"

def run_live_monitor():
    print("\n" + "═"*54)
    print("  ⚡ LIVE MONITOR v8.0")
    print(f"  Проверка каждые {CHECK_INTERVAL//60} мин.  |  Ctrl+C для остановки")
    print(f"  Алерты: 🚨 мёртв  ⚠️ опасность  ✅ выигрываем")
    print("═"*54)
    alerted = set()   # fixture_id + signal_key уже оповещённые

    while True:
        try:
            preds = load_todays_predictions()
            if not preds:
                print(f"  [{datetime.datetime.now().strftime('%H:%M')}] Нет активных прогнозов сегодня")
                print(f"  Запусти: python football_bot_v3.py today")
                print(f"  Следующая проверка через {CHECK_INTERVAL//60} мин.  (Ctrl+C — выход)")
                time.sleep(CHECK_INTERVAL)
                continue

            print(f"\n  [{datetime.datetime.now().strftime('%H:%M')}] Проверяю {len(preds)} матчей...")

            for pred in preds:
                fid   = pred.get("fixture_id")
                home  = pred.get("home","")
                away  = pred.get("away","")
                sigs  = pred.get("signals",[])
                if not fid or not sigs:
                    continue

                score = get_live_score(fid)
                if not score:
                    continue

                st = score.get("status","")
                el = score.get("elapsed",0)
                hg = score.get("home",0)
                ag = score.get("away",0)

                if st == "FT":
                    # Обновляем Elo после матча
                    try:
                        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
                        from football_bot_v3 import update_elo
                        update_elo(home, away, hg, ag)
                    except Exception:
                        pass
                    continue

                if st not in ("1H","2H","HT","ET","BT","P","SUSP","INT","LIVE"):
                    continue  # матч не идёт

                print(f"    ⚽ {home} {hg}:{ag} {away}  [{el}']  {st}")

                # ── ЛАЙВ-АНАЛИЗ КОМАНДЫ (каждые 15 минут) ────────
                analysis_key = f"{fid}_analysis_{el // 15}"
                if _LIVE_ANALYSIS_AVAILABLE and analysis_key not in alerted:
                    alerted.add(analysis_key)
                    xg_h = pred.get("xg_home", 1.5)
                    xg_a = pred.get("xg_away", 1.2)
                    analysis = analyze_live_team(fid, home, away, xg_h, xg_a)
                    if "error" not in analysis and el >= 15:
                        msg = format_live_analysis(analysis, home, away)
                        _tg(msg)
                        print(f"      📺 Лайв-анализ отправлен [{el}']")
                    time.sleep(6)

                for sig in sigs:
                    key = f"{fid}_{sig.get('market','')}_{sig.get('selection','')}"
                    status = evaluate_signal_live(sig, score)

                    if status == "dead" and key not in alerted:
                        alerted.add(key)
                        msg = (
                            f"🚨 <b>СИГНАЛ МЁРТВ</b>\n"
                            f"⚽ {home} {hg}:{ag} {away} [{el}']\n"
                            f"❌ [{sig['market']}] {sig['selection']}\n"
                            f"Коэф: {sig.get('bookmaker_odds','-')} | "
                            f"Валуй: {sig.get('edge',0)*100:.1f}%\n"
                            f"💡 Рассмотри частичный вывод если кэшаут доступен"
                        )
                        _tg(msg)
                        print(f"      🚨 АЛЕРТ: {sig['selection']} — мёртв")

                    elif status == "danger" and key+"_warn" not in alerted:
                        alerted.add(key+"_warn")
                        msg = (
                            f"⚠️ <b>ОПАСНОСТЬ</b>\n"
                            f"⚽ {home} {hg}:{ag} {away} [{el}']\n"
                            f"⚠️ [{sig['market']}] {sig['selection']}\n"
                            f"Матч идёт ПРОТИВ прогноза. Следи за развитием."
                        )
                        _tg(msg)
                        print(f"      ⚠️ ОПАСНОСТЬ: {sig['selection']}")

                    elif status == "ok" and key+"_ok" not in alerted:
                        alerted.add(key+"_ok")
                        _tg(
                            f"✅ <b>ВЫИГРЫВАЕМ</b>\n"
                            f"⚽ {home} {hg}:{ag} {away} [{el}']\n"
                            f"✅ [{sig['market']}] {sig['selection']} идёт по плану\n"
                            f"Коэф: {sig.get('bookmaker_odds','-')}"
                        )
                        print(f"      ✅ WINNING: {sig['selection']}")

                time.sleep(8)  # пауза между матчами (rate limit)

            # Сводка по итогам проверки
            active_count = sum(
                1 for p in preds
                if p.get("fixture_id") and p.get("signals")
            )
            print(f"  Активных матчей в эфире: {active_count} из {len(preds)}")
            print(f"  Следующая проверка через {CHECK_INTERVAL//60} мин.  (Ctrl+C — выход)")
            time.sleep(CHECK_INTERVAL)

        except KeyboardInterrupt:
            print("\n⛔ Live Monitor остановлен")
            break
        except Exception as e:
            print(f"  ⚠️ Ошибка: {e}")
            import traceback
            traceback.print_exc()
            time.sleep(60)   # при ошибке ждём минуту и пробуем снова

if __name__ == "__main__":
    run_live_monitor()
