"""
run_bot.py — Единая точка запуска всех компонентов бота.

Команды:
    python run_bot.py today       — сканирование на сегодня
    python run_bot.py learn       — обновить результаты + Sheets
    python run_bot.py monitor     — live мониторинг
    python run_bot.py backtest    — анализ эффективности
    python run_bot.py calibrate   — ML калибровка
    python run_bot.py status      — статус всех компонентов
    python run_bot.py help        — справка
"""

from __future__ import annotations
import os, sys, subprocess, datetime

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


def check_status() -> None:
    """Проверяет доступность всех компонентов."""
    print("═" * 55)
    print("  STATUS — Футбольный сигнальный бот")
    print("═" * 55)

    # Конфиг
    checks = {
        "API-Football":   bool(os.getenv("API_FOOTBALL_KEY")),
        "Odds API":       bool(os.getenv("ODDS_API_KEY")),
        "Telegram":       bool(os.getenv("TELEGRAM_TOKEN")),
        "Google Sheets":  bool(os.getenv("SHEET_ID")),
        "Betfair":        bool(os.getenv("BETFAIR_USER")),
        "Proxy":          bool(os.getenv("PROXY_URL")),
    }
    print("\n  Конфигурация:")
    for name, ok in checks.items():
        print(f"    {'✅' if ok else '⚠️ '} {name}")

    # Файлы
    files = [
        ("predictions.json",   "Прогнозы"),
        ("results.json",       "Результаты"),
        ("ml_weights.json",    "ML-веса"),
        ("signals.csv",        "CSV-лог"),
        ("credentials.json",   "Google SA"),
    ]
    print("\n  Файлы:")
    for fname, desc in files:
        exists = os.path.exists(fname)
        size   = os.path.getsize(fname) if exists else 0
        print(f"    {'✅' if exists else '❌'} {desc} ({fname})"
              + (f" — {size//1024}KB" if exists else " — отсутствует"))

    # Статистика
    try:
        import json
        with open("predictions.json") as f:
            preds = json.load(f)
        sigs = [s for p in preds for s in p.get("signals", [])]
        resolved = [s for s in sigs if s.get("won") is not None]
        won = sum(1 for s in resolved if s["won"])
        dates = sorted(set(p.get("date","") for p in preds))
        print(f"\n  Статистика ({dates[0]} — {dates[-1]}):")
        print(f"    Матчей:    {len(preds)}")
        print(f"    Сигналов:  {len(sigs)} (с результатом: {len(resolved)})")
        if resolved:
            staked = sum(s.get("kelly_stake") or s.get("stake") or 10 for s in resolved)
            profit = sum(
                (s.get("kelly_stake") or s.get("stake") or 10) * (s.get("bookmaker_odds",2)-1)
                if s["won"] else
                -(s.get("kelly_stake") or s.get("stake") or 10)
                for s in resolved
            )
            print(f"    WR:        {won/len(resolved):.1%}")
            print(f"    ROI:       {profit/staked*100:+.1f}%")
            print(f"    Net:       {profit:+.0f} ед.")
    except Exception:
        pass

    print("═" * 55)


COMMANDS = {
    "today":     ("python football_bot_v3.py today",    "Скан на сегодня"),
    "scan":      ("python football_bot_v3.py today",    "Скан на сегодня"),
    "learn":     ("python learning.py",                  "Обновить результаты"),
    "sheets":    ("python learning.py sheets",           "Синхронизация с Sheets"),
    "monitor":   ("python live_monitor.py",              "Live мониторинг"),
    "backtest":  ("python backtest.py",                  "Анализ эффективности"),
    "calibrate": ("python ml_calibrate.py",              "ML калибровка"),
    "betfair":   ("python betfair_client.py",            "Тест Betfair"),
    "diag":      ("python diag_odds_sources.py",         "Диагностика коэфов"),
}


def print_help() -> None:
    print("═" * 55)
    print("  КОМАНДЫ")
    print("═" * 55)
    print()
    print("  Основные:")
    for cmd, (_, desc) in COMMANDS.items():
        print(f"    python run_bot.py {cmd:12s} — {desc}")
    print()
    print("  Расписание cron (пример):")
    print("    0  9 * * 1-5 cd /path && python run_bot.py today")
    print("    0  8 * * *   cd /path && python run_bot.py learn")
    print("    */10 * * * * cd /path && python run_bot.py monitor once")
    print()
    print("  ⚠️  Responsible gambling: не ставь больше 2-5% банка на сигнал")
    print("═" * 55)


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    if cmd == "status":
        check_status()
    elif cmd == "help":
        print_help()
    elif cmd in COMMANDS:
        shell_cmd = COMMANDS[cmd][0]
        # Передаём доп. аргументы
        extra = " ".join(sys.argv[2:])
        full_cmd = f"{shell_cmd} {extra}".strip()
        print(f"▶ {full_cmd}")
        os.system(full_cmd)
    else:
        print(f"Неизвестная команда: {cmd}")
        print_help()
