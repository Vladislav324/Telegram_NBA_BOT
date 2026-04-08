"""
logger.py — Настройка логирования для всех модулей бота.

Форматы:
  - Консоль: цветной вывод с уровнем и временем
  - Файл: полный JSON-лог (ротация 5MB × 3 файла)

Usage:
    from logger import get_logger
    log = get_logger(__name__)
    log.info("Сканирую матчи...")
    log.warning("API недоступен")
    log.error("Критическая ошибка", exc_info=True)
"""

from __future__ import annotations

import logging
import logging.handlers
import os
import sys
from typing import Optional

# ── Цвета для консоли ───────────────────────────────────────────────
_COLORS = {
    "DEBUG":    "\033[36m",   # cyan
    "INFO":     "\033[32m",   # green
    "WARNING":  "\033[33m",   # yellow
    "ERROR":    "\033[31m",   # red
    "CRITICAL": "\033[35m",   # magenta
}
_RESET = "\033[0m"
_BOLD  = "\033[1m"


class _ColorFormatter(logging.Formatter):
    """Форматтер с цветами для консольного вывода."""

    FMT = "{time} │ {level} │ {msg}"

    def format(self, record: logging.LogRecord) -> str:
        color = _COLORS.get(record.levelname, "")
        level = f"{color}{record.levelname:5s}{_RESET}"
        time  = self.formatTime(record, "%H:%M:%S")
        msg   = record.getMessage()
        if record.exc_info:
            msg += "\n" + self.formatException(record.exc_info)
        return f"{time} │ {level} │ {msg}"


class _JsonFormatter(logging.Formatter):
    """JSON-форматтер для файлового лога."""

    def format(self, record: logging.LogRecord) -> str:
        import json, datetime
        entry = {
            "ts":      datetime.datetime.fromtimestamp(record.created).isoformat(),
            "level":   record.levelname,
            "module":  record.name,
            "msg":     record.getMessage(),
        }
        if record.exc_info:
            entry["exc"] = self.formatException(record.exc_info)
        return json.dumps(entry, ensure_ascii=False)


# ── Инициализация ───────────────────────────────────────────────────
_LOG_DIR  = os.getenv("LOG_DIR", "logs")
_LOG_FILE = os.path.join(_LOG_DIR, "football_bot.log")
_LOG_LEVEL_CONSOLE = os.getenv("LOG_LEVEL", "INFO").upper()
_LOG_LEVEL_FILE    = "DEBUG"

_initialized = False


def _init() -> None:
    global _initialized
    if _initialized:
        return

    os.makedirs(_LOG_DIR, exist_ok=True)

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)

    # Консоль
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(getattr(logging, _LOG_LEVEL_CONSOLE, logging.INFO))
    ch.setFormatter(_ColorFormatter())
    root.addHandler(ch)

    # Файл с ротацией
    try:
        fh = logging.handlers.RotatingFileHandler(
            _LOG_FILE, maxBytes=5 * 1024 * 1024, backupCount=3,
            encoding="utf-8",
        )
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(_JsonFormatter())
        root.addHandler(fh)
    except Exception:
        pass  # если нет прав — только консоль

    # Подавляем шум от сторонних библиотек
    for noisy in ("urllib3", "aiohttp", "asyncio"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    _initialized = True


def get_logger(name: str = "football_bot") -> logging.Logger:
    """Возвращает настроенный logger для модуля."""
    _init()
    return logging.getLogger(name)


# Корневой логгер для обратной совместимости
log = get_logger("football_bot")
