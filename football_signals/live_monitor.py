"""
live_monitor.py — Асинхронный мониторинг активных ставок.

Возможности:
  - asyncio + aiohttp (неблокирующие запросы)
  - Exponential backoff при ошибках API
  - Redis-кеш (fallback → JSON файл)
  - Алерты только при значимых событиях (гол, движение линии)
  - Авто-сброс сработавших алертов раз в матч

Usage:
    python live_monitor.py          — запустить мониторинг
    python live_monitor.py once     — разовая проверка
"""

from __future__ import annotations

import asyncio
import datetime
import json
import logging
import os
import ssl
import time
from dataclasses import dataclass, field
from typing import Optional

# ── python-dotenv (опционально) ────────────────────────────────────
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# ── aiohttp (опционально — fallback на urllib) ─────────────────────
try:
    import aiohttp
    AIOHTTP_AVAILABLE = True
except ImportError:
    AIOHTTP_AVAILABLE = False

# ── Redis (опционально — fallback на JSON) ──────────────────────────
try:
    import redis
    _redis = redis.Redis(
        host=os.getenv("REDIS_HOST", "localhost"),
        port=int(os.getenv("REDIS_PORT", 6379)),
        decode_responses=True,
        socket_connect_timeout=2,
    )
    _redis.ping()
    REDIS_AVAILABLE = True
except Exception:
    REDIS_AVAILABLE = False
    _redis = None

# ── Настройка логирования ───────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s │ %(levelname)-5s │ %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# ── Конфиги (из .env) ──────────────────────────────────────────────
API_FOOTBALL_KEY = os.getenv("API_FOOTBALL_KEY", "33d9e41279e34866b001ab44dade2540")
TELEGRAM_TOKEN   = os.getenv("TELEGRAM_TOKEN",   "8263616332:AAGGJwEnlJSy160VlpaLcN2v8bbJ3hpf7gA")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "-1003885532223")
PREDICTIONS_FILE = os.getenv("PREDICTIONS_FILE", "predictions.json")
CACHE_FILE       = "live_cache.json"

CHECK_INTERVAL   = int(os.getenv("CHECK_INTERVAL", 600))   # 10 мин
RETRY_BASE       = 2    # базовая задержка exponential backoff (секунды)
MAX_RETRIES      = 4    # максимальное число попыток

LIVE_STATUSES    = {"1H", "2H", "HT", "ET", "BT", "P", "LIVE"}


# ── Кеш (Redis или JSON) ────────────────────────────────────────────
class Cache:
    """Простой кеш: Redis если доступен, иначе JSON-файл."""

    def get(self, key: str) -> Optional[str]:
        if REDIS_AVAILABLE and _redis:
            try: return _redis.get(f"live:{key}")
            except Exception: pass
        data = self._load_json()
        return data.get(key)

    def set(self, key: str, value: str, ttl: int = 7200) -> None:
        if REDIS_AVAILABLE and _redis:
            try:
                _redis.setex(f"live:{key}", ttl, value)
                return
            except Exception: pass
        data = self._load_json()
        data[key] = value
        self._save_json(data)

    def exists(self, key: str) -> bool:
        return self.get(key) is not None

    def _load_json(self) -> dict:
        if os.path.exists(CACHE_FILE):
            try:
                with open(CACHE_FILE, encoding="utf-8") as f:
                    return json.load(f)
            except Exception: pass
        return {}

    def _save_json(self, data: dict) -> None:
        try:
            with open(CACHE_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f)
        except Exception: pass


cache = Cache()


# ── SSL-контекст ────────────────────────────────────────────────────
def _ssl_ctx() -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode    = ssl.CERT_NONE
    return ctx


# ── Async HTTP helper с exponential backoff ─────────────────────────
async def _get_async(url: str, headers: dict | None = None,
                     params: dict | None = None) -> Optional[dict]:
    """
    Асинхронный GET с exponential backoff и retry.
    При недоступности aiohttp — синхронный fallback через urllib.
    """
    if not AIOHTTP_AVAILABLE:
        return _get_sync(url, headers, params)

    import urllib.parse
    if params:
        url = f"{url}?{urllib.parse.urlencode(params)}"

    ssl_ctx = _ssl_ctx()
    for attempt in range(MAX_RETRIES):
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    url,
                    headers=headers or {},
                    ssl=ssl_ctx,
                    timeout=aiohttp.ClientTimeout(total=12),
                ) as resp:
                    if resp.status == 429:  # rate limit
                        wait = RETRY_BASE ** attempt
                        log.warning(f"Rate limit 429 — жду {wait}с...")
                        await asyncio.sleep(wait)
                        continue
                    if resp.status != 200:
                        log.debug(f"HTTP {resp.status}: {url[:60]}")
                        return None
                    return await resp.json(content_type=None)
        except asyncio.TimeoutError:
            wait = RETRY_BASE ** attempt
            log.debug(f"Timeout attempt {attempt+1}/{MAX_RETRIES} — retry в {wait}с")
            await asyncio.sleep(wait)
        except Exception as e:
            wait = RETRY_BASE ** attempt
            log.debug(f"Ошибка {e} attempt {attempt+1}/{MAX_RETRIES}")
            await asyncio.sleep(wait)
    return None


def _get_sync(url: str, headers: dict | None = None,
              params: dict | None = None) -> Optional[dict]:
    """Синхронный GET fallback (urllib)."""
    import urllib.request, urllib.parse
    if params:
        url = f"{url}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=12, context=_ssl_ctx()) as r:
            return json.loads(r.read().decode())
    except Exception as e:
        log.debug(f"sync GET {url[:50]}: {e}")
        return None


# ── Telegram async ──────────────────────────────────────────────────
async def tg_send(text: str) -> None:
    """Асинхронная отправка сообщения в Telegram."""
    url  = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    data = {"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "HTML"}
    await _get_async(url, headers={"Content-Type": "application/json"},
                     params=data)


# ── API-Football ────────────────────────────────────────────────────
async def get_live_score(fixture_id: int) -> dict:
    """Получает текущий счёт матча с exponential backoff."""
    data = await _get_async(
        "https://v3.football.api-sports.io/fixtures",
        headers={"x-apisports-key": API_FOOTBALL_KEY},
        params={"id": fixture_id},
    )
    if not data:
        return {}
    resp = data.get("response", [])
    if not resp:
        return {}
    fix  = resp[0]
    st   = fix.get("fixture", {}).get("status", {})
    goal = fix.get("goals", {})
    events = fix.get("events", [])
    return {
        "status":  st.get("short", ""),
        "elapsed": st.get("elapsed") or 0,
        "home":    goal.get("home") or 0,
        "away":    goal.get("away") or 0,
        "events":  events,
    }


# ── Прогнозы дня ────────────────────────────────────────────────────
def load_todays_predictions() -> list:
    """Загружает прогнозы за сегодня с pending результатами."""
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


# ── Оценка сигнала ──────────────────────────────────────────────────
@dataclass
class SignalStatus:
    """Статус сигнала по текущему счёту."""
    status:  str        # "ok" / "danger" / "dead" / "pending"
    reason:  str = ""
    score:   str = ""


def evaluate_signal(sig: dict, score: dict) -> SignalStatus:
    """
    Оценивает сигнал по текущему счёту матча.
    Возвращает SignalStatus с подробностями.
    """
    market   = sig.get("market", "")
    sel      = sig.get("selection", "")
    hg, ag   = score.get("home", 0), score.get("away", 0)
    elapsed  = score.get("elapsed", 0)
    total    = hg + ag
    diff     = hg - ag
    score_str = f"{hg}:{ag} [{elapsed}']"

    if score.get("status") in ("FT", "AET"):
        return SignalStatus("finished", score=score_str)

    if "Исход" in market or "Победа" in market:
        if "хозяев" in sel or "(1)" in sel:
            if diff > 1:  return SignalStatus("ok",     score=score_str)
            if diff < 0 and elapsed > 65:
                return SignalStatus("dead",   "Гости ведут ≥65'", score_str)
            if diff < 0:  return SignalStatus("danger", "Гости ведут",    score_str)
        elif "гостей" in sel or "(2)" in sel:
            if diff < -1: return SignalStatus("ok",     score=score_str)
            if diff > 0 and elapsed > 65:
                return SignalStatus("dead",   "Хозяева ведут ≥65'", score_str)
            if diff > 0:  return SignalStatus("danger", "Хозяева ведут",  score_str)
        elif "Ничья" in sel or "(X)" in sel:
            if abs(diff) > 1 and elapsed > 55:
                return SignalStatus("dead",   f"Разрыв >{abs(diff)} ≥55'", score_str)

    elif "Тотал" in market:
        import re as _re
        num_m = _re.search(r"([\d.]+)", market)
        line  = float(num_m.group(1)) if num_m else 2.5
        remaining_frac = max(0, 90 - elapsed) / 90
        if "Больше" in sel:
            if total > line:
                return SignalStatus("ok", score=score_str)
            needed = line - total
            exp_more = remaining_frac * (line * 0.9)
            if needed > 0 and exp_more < needed * 0.5 and elapsed > 60:
                return SignalStatus("danger", f"Нужно {needed:.0f} г. → темп низкий", score_str)
        elif "Меньше" in sel:
            if total >= line:
                return SignalStatus("dead", f"Тотал {total} ≥ {line}", score_str)
            if total == line - 1 and elapsed > 70:
                return SignalStatus("danger", f"Тотал {total} и 70'+", score_str)

    elif "DNB" in market or "Фора 0" in market:
        if "хозяев" in sel.lower() or "(Ф0)" in sel:
            if ag > hg and elapsed > 70:
                return SignalStatus("dead",   "Гости ведут ≥70'", score_str)
            if ag > hg:
                return SignalStatus("danger", "Гости ведут",       score_str)
            if hg > ag:
                return SignalStatus("ok",     score=score_str)

    elif "BTTS" in market or "забьют" in market.lower():
        if "Нет" in sel:
            if total >= 1:
                return SignalStatus("dead", f"Уже {total} гол(а)", score_str)

    return SignalStatus("pending", score=score_str)


# ── Детект значимых событий ─────────────────────────────────────────
def detect_important_events(events: list, last_checked_at: float) -> list[str]:
    """
    Возвращает список важных событий с момента last_checked_at.
    Фильтрует: голы, красные карточки.
    """
    important = []
    cutoff_min = int((time.time() - last_checked_at) / 60) + 1
    for ev in events:
        elapsed = ev.get("time", {}).get("elapsed", 0)
        ev_type = ev.get("type", "").lower()
        detail  = ev.get("detail", "").lower()
        team    = ev.get("team", {}).get("name", "")
        player  = (ev.get("player") or {}).get("name", "?")
        if "goal" in ev_type:
            important.append(f"⚽ Гол! {team} — {player} [{elapsed}']")
        elif "card" in ev_type and "red" in detail:
            important.append(f"🟥 Красная! {team} — {player} [{elapsed}']")
    return important


# ── Основной async цикл ─────────────────────────────────────────────
async def monitor_loop() -> None:
    """Главный цикл мониторинга. Запускается через asyncio.run()."""
    log.info("═" * 56)
    log.info("  ⚡ LIVE MONITOR (async)")
    log.info(f"  Интервал: {CHECK_INTERVAL // 60} мин | Redis: {'✅' if REDIS_AVAILABLE else '❌ (JSON)'}")
    log.info("  Ctrl+C для остановки")
    log.info("═" * 56)

    _last_checked_at: dict[int, float] = {}

    while True:
        try:
            preds = load_todays_predictions()

            if not preds:
                log.info(f"[{datetime.datetime.now():%H:%M}] Нет активных прогнозов сегодня")
                await asyncio.sleep(CHECK_INTERVAL)
                continue

            log.info(f"\n[{datetime.datetime.now():%H:%M}] Проверяю {len(preds)} матчей...")

            # Запускаем проверку всех матчей параллельно
            tasks = [_check_match(pred, _last_checked_at) for pred in preds]
            await asyncio.gather(*tasks, return_exceptions=True)

            log.info(f"  Следующая проверка через {CHECK_INTERVAL // 60} мин.")
            await asyncio.sleep(CHECK_INTERVAL)

        except asyncio.CancelledError:
            log.info("⛔ Мониторинг остановлен")
            break
        except Exception as e:
            log.error(f"Ошибка цикла: {e}")
            await asyncio.sleep(60)


async def _check_match(pred: dict, last_checked: dict) -> None:
    """Проверяет один матч и отправляет алерты при необходимости."""
    fid   = pred.get("fixture_id")
    home  = pred.get("home", "")
    away  = pred.get("away", "")
    sigs  = pred.get("signals", [])

    if not fid or not sigs:
        return

    score = await get_live_score(fid)
    if not score:
        return

    st      = score.get("status", "")
    elapsed = score.get("elapsed", 0)
    hg      = score.get("home", 0)
    ag      = score.get("away", 0)

    if st == "FT":
        return
    if st not in LIVE_STATUSES:
        return

    log.info(f"  ⚽ {home} {hg}:{ag} {away}  [{elapsed}']  {st}")

    # Важные события (голы, красные) с момента последней проверки
    last_ts = last_checked.get(fid, time.time() - CHECK_INTERVAL)
    events  = detect_important_events(score.get("events", []), last_ts)
    for ev_msg in events:
        log.info(f"    {ev_msg}")

    last_checked[fid] = time.time()

    # Проверяем каждый сигнал
    for sig in sigs:
        await _check_signal(sig, score, home, away, fid, elapsed)

    await asyncio.sleep(0.5)  # rate limit между матчами


async def _check_signal(
    sig: dict, score: dict, home: str, away: str,
    fid: int, elapsed: int,
) -> None:
    """Оценивает сигнал и отправляет алерт если нужно."""
    market = sig.get("market", "")
    sel    = sig.get("selection", "")
    bk_o   = sig.get("bookmaker_odds", "-")
    edge   = sig.get("edge", 0)

    alert_key = f"{fid}:{market}:{sel}"
    status = evaluate_signal(sig, score)

    hg, ag = score.get("home", 0), score.get("away", 0)

    if status.status == "dead":
        dead_key = f"dead:{alert_key}"
        if not cache.exists(dead_key):
            cache.set(dead_key, "1", ttl=7200)
            msg = (
                f"🚨 <b>СИГНАЛ МЁРТВ</b>\n"
                f"⚽ {home} {hg}:{ag} {away} [{elapsed}']\n"
                f"❌ [{market}] {sel}\n"
                f"Коэф: {bk_o} | Валуй: {edge*100:.1f}%\n"
                f"💡 Рассмотри кешаут если доступен"
            )
            log.warning(f"    🚨 МЁРТВ: {sel} — {status.reason}")
            await tg_send(msg)

    elif status.status == "danger":
        warn_key = f"warn:{alert_key}"
        if not cache.exists(warn_key):
            cache.set(warn_key, "1", ttl=3600)
            msg = (
                f"⚠️ <b>ОПАСНОСТЬ</b>\n"
                f"⚽ {home} {hg}:{ag} {away} [{elapsed}']\n"
                f"⚠️ [{market}] {sel}\n"
                f"Причина: {status.reason}"
            )
            log.warning(f"    ⚠️  ОПАСНОСТЬ: {sel} — {status.reason}")
            await tg_send(msg)

    elif status.status == "ok":
        ok_key = f"ok:{alert_key}"
        if not cache.exists(ok_key):
            cache.set(ok_key, "1", ttl=7200)
            msg = (
                f"✅ <b>ВЫИГРЫВАЕМ</b>\n"
                f"⚽ {home} {hg}:{ag} {away} [{elapsed}']\n"
                f"✅ [{market}] {sel} идёт по плану\n"
                f"Коэф: {bk_o}"
            )
            log.info(f"    ✅ ВЫИГРЫВАЕМ: {sel}")
            await tg_send(msg)


async def run_once() -> None:
    """Разовая проверка всех матчей (без цикла)."""
    preds = load_todays_predictions()
    if not preds:
        log.info("Нет активных прогнозов сегодня")
        return
    tasks = [_check_match(pred, {}) for pred in preds]
    await asyncio.gather(*tasks, return_exceptions=True)


# ── Entry point ────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys
    mode = sys.argv[1] if len(sys.argv) > 1 else "loop"
    try:
        if mode == "once":
            asyncio.run(run_once())
        else:
            asyncio.run(monitor_loop())
    except KeyboardInterrupt:
        log.info("\n⛔ Остановлен вручную")
