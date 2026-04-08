"""
config.py — Централизованная конфигурация бота.

Все секреты читаются из .env (через python-dotenv).
Не содержит хардкоженных токенов.

Usage:
    from config import cfg
    print(cfg.api_football_key)
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Optional

# Загружаем .env если есть
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


@dataclass(frozen=True)
class Config:
    """Иммутабельная конфигурация — создаётся один раз при импорте."""

    # ── API ключи ──────────────────────────────────────────────────
    api_football_key:  str = field(default_factory=lambda: os.getenv("API_FOOTBALL_KEY", ""))
    odds_api_key:      str = field(default_factory=lambda: os.getenv("ODDS_API_KEY", ""))
    odds_api_key_b:    str = field(default_factory=lambda: os.getenv("ODDS_API_KEY_B", ""))
    rapidapi_key:      str = field(default_factory=lambda: os.getenv("RAPIDAPI_KEY", ""))

    # ── Telegram ───────────────────────────────────────────────────
    telegram_token:    str = field(default_factory=lambda: os.getenv("TELEGRAM_TOKEN", ""))
    telegram_chat_id:  str = field(default_factory=lambda: os.getenv("TELEGRAM_CHAT_ID", ""))

    # ── Google Sheets ──────────────────────────────────────────────
    sheet_id:          str = field(default_factory=lambda: os.getenv("SHEET_ID", ""))
    credentials_path:  str = field(default_factory=lambda: os.getenv("GOOGLE_CREDENTIALS_PATH", "credentials.json"))

    # ── Betfair ────────────────────────────────────────────────────
    betfair_user:      str = field(default_factory=lambda: os.getenv("BETFAIR_USER", ""))
    betfair_pass:      str = field(default_factory=lambda: os.getenv("BETFAIR_PASS", ""))
    betfair_app_key:   str = field(default_factory=lambda: os.getenv("BETFAIR_APPKEY", ""))

    # ── Pinnacle ───────────────────────────────────────────────────
    pinnacle_user:     str = field(default_factory=lambda: os.getenv("PINNACLE_USER", ""))
    pinnacle_pass:     str = field(default_factory=lambda: os.getenv("PINNACLE_PASS", ""))

    # ── Прокси ────────────────────────────────────────────────────
    proxy_url:         str = field(default_factory=lambda: os.getenv("PROXY_URL", ""))

    # ── Параметры бота ─────────────────────────────────────────────
    bankroll:          float = field(default_factory=lambda: float(os.getenv("BANKROLL", "1000")))
    kelly_frac:        float = field(default_factory=lambda: float(os.getenv("KELLY_FRAC", "0.15")))
    min_edge:          float = field(default_factory=lambda: float(os.getenv("MIN_EDGE", "0.10")))
    min_prob:          float = field(default_factory=lambda: float(os.getenv("MIN_PROB", "0.54")))
    max_signals_day:   int   = field(default_factory=lambda: int(os.getenv("MAX_SIGNALS_DAY", "10")))
    check_interval:    int   = field(default_factory=lambda: int(os.getenv("CHECK_INTERVAL", "600")))

    # ── Файлы ─────────────────────────────────────────────────────
    predictions_file:  str = "predictions.json"
    results_file:      str = "results.json"
    ml_weights_file:   str = "ml_weights.json"
    signals_csv:       str = "signals.csv"

    def validate(self) -> list[str]:
        """Проверяет обязательные поля. Возвращает список предупреждений."""
        warnings = []
        if not self.api_football_key:
            warnings.append("API_FOOTBALL_KEY не задан — фикстуры через FD/TheSportsDB")
        if not self.odds_api_key:
            warnings.append("ODDS_API_KEY не задан — коэфы только расчётные")
        if not self.telegram_token:
            warnings.append("TELEGRAM_TOKEN не задан — Telegram уведомления отключены")
        if not self.sheet_id:
            warnings.append("SHEET_ID не задан — Google Sheets синхронизация отключена")
        return warnings

    def is_betfair_enabled(self) -> bool:
        return bool(self.betfair_user and self.betfair_pass)

    def is_proxy_enabled(self) -> bool:
        return bool(self.proxy_url)


# Глобальный singleton
cfg = Config()
