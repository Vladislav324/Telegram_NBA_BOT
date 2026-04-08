"""
odds_fetcher.py — Единый модуль получения реальных коэффициентов.

Цепочка источников (приоритет по качеству данных):
  1. Pinnacle Guest API   — самый острый рынок, без регистрации
  2. The Odds API         — h2h + totals + spreads, 500 req/мес free
  3. API-Football /odds   — тот же ключ что для фикстур, Bet365/Bwin
  4. 1xBet unofficial     — без ключа, широкое покрытие рынков
  5. Fonbet               — только RU IP, подходит при VPN

Формат возврата — единый dict (bk_odds):
  "1", "X", "2"                     — 1X2
  "over_2.5", "under_2.5"           — тотал
  "over_1.5", "under_1.5"
  "over_3.5", "under_3.5"
  "btts_yes", "btts_no"             — BTTS
  "dnb_home", "dnb_away"            — DNB
  "dc_1x", "dc_12", "dc_x2"        — двойной шанс
  "eh_home_+1", "eh_away_-1", ...   — европейский гандикап
  "_source_*"                        — флаг источника

Usage:
    from odds_fetcher import OddsFetcher
    fetcher = OddsFetcher()
    odds = fetcher.get(fixture_id=12345, league_id=39,
                       home="Arsenal", away="Chelsea", date="2026-04-05")
"""

from __future__ import annotations

import json
import os
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
import logging
from dataclasses import dataclass, field
from typing import Optional

# ── Настройки ──────────────────────────────────────────────────────
logger = logging.getLogger(__name__)

# Ключи читаем из переменных окружения (python-dotenv)
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

API_FOOTBALL_KEY = os.getenv("API_FOOTBALL_KEY", "")
ODDS_API_KEY     = os.getenv("ODDS_API_KEY", "")
ODDS_API_KEY_B   = os.getenv("ODDS_API_KEY_B", "")
PROXY_URL        = os.getenv("PROXY_URL", "")

# Таймаут и паузы
REQUEST_TIMEOUT  = 12
REQUEST_DELAY    = 0.3   # пауза между запросами

# Маппинг league_id → Odds API sport_key
ODDS_SPORT_KEYS: dict[int, list[str]] = {
    39:  ["soccer_epl", "soccer_england_premier_league"],
    140: ["soccer_spain_la_liga"],
    135: ["soccer_italy_serie_a"],
    78:  ["soccer_germany_bundesliga"],
    61:  ["soccer_france_ligue_one"],
    2:   ["soccer_uefa_champs_league", "soccer_uefa_champions_league"],
    3:   ["soccer_uefa_europa_league"],
    848: ["soccer_uefa_europa_conference_league"],
    40:  ["soccer_efl", "soccer_england_championship"],
    94:  ["soccer_portugal_primeira_liga"],
    88:  ["soccer_netherlands_eredivisie"],
    144: ["soccer_belgium_first_div"],
    179: ["soccer_scotland_premiership"],
    203: ["soccer_turkey_super_league"],
    71:  ["soccer_brazil_campeonato"],
    45:  ["soccer_fa_cup"],
    48:  ["soccer_efl_cup"],
}


# ── SSL helper ─────────────────────────────────────────────────────
def _ssl_ctx() -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode    = ssl.CERT_NONE
    return ctx


def _get(url: str, headers: dict | None = None,
         params: dict | None = None, timeout: int = REQUEST_TIMEOUT) -> Optional[dict]:
    """GET-запрос с SSL-фиксом. Возвращает dict или None."""
    if params:
        url = f"{url}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers=headers or {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=_ssl_ctx()) as r:
            return json.loads(r.read().decode())
    except Exception as e:
        logger.debug(f"GET {url[:60]}: {e}")
        return None


# ── Нормализация имён ──────────────────────────────────────────────
def _norm(name: str) -> str:
    """Нормализует имя команды для fuzzy-сравнения."""
    return name.lower().replace("'", "").replace("-", " ").replace(".", "").strip()


def _match_names(a: str, b: str, threshold: int = 4) -> bool:
    """True если имена достаточно похожи (по первым N символам фамилии)."""
    na, nb = _norm(a), _norm(b)
    # Точное совпадение
    if na == nb:
        return True
    # По последнему слову (фамилия)
    parts_a = na.split(); parts_b = nb.split()
    if parts_a and parts_b:
        if parts_a[-1][:threshold] == parts_b[-1][:threshold]:
            return True
    # Одна строка содержит другую
    if na in nb or nb in na:
        return True
    return False


# ── Парсеры ответов букмекеров ─────────────────────────────────────
def _parse_odds_api_event(event: dict, home: str, away: str) -> Optional[dict]:
    """
    Парсит событие из The Odds API.
    Возвращает стандартный bk_odds dict или None.
    """
    h = event.get("home_team", "")
    a = event.get("away_team", "")
    # Проверяем что это нужный матч
    if not (_match_names(h, home) and _match_names(a, away)):
        return None

    result: dict = {}
    for bookmaker in event.get("bookmakers", []):
        for market in bookmaker.get("markets", []):
            key   = market.get("key", "")
            vals  = market.get("values", [])
            if key == "h2h":
                for v in vals:
                    nm = _norm(v.get("name", ""))
                    pr = float(v.get("price", 0))
                    if _match_names(nm, home):  result["1"] = max(result.get("1", 0), pr)
                    elif _match_names(nm, away): result["2"] = max(result.get("2", 0), pr)
                    else: result["X"] = max(result.get("X", 0), pr)
            elif key == "totals":
                for v in vals:
                    pt   = float(v.get("point", 0))
                    pr   = float(v.get("price", 0))
                    side = v.get("name", "").lower()
                    k = f"over_{pt}" if "over" in side else f"under_{pt}"
                    result[k] = max(result.get(k, 0), pr)
            elif key == "spreads":
                for v in vals:
                    pt = float(v.get("point", 0))
                    pr = float(v.get("price", 0))
                    nm = _norm(v.get("name", ""))
                    if _match_names(nm, home):
                        k = f"eh_home_{'+' if pt >= 0 else ''}{pt}"
                    else:
                        k = f"eh_away_{'+' if pt >= 0 else ''}{pt}"
                    result[k] = max(result.get(k, 0), pr)

    if result.get("1"):
        result["_source_odds_api"] = True
    return result if result.get("1") else None


def _parse_af_odds(response: dict) -> dict:
    """
    Парсит ответ API-Football /odds.
    Возвращает стандартный bk_odds dict.
    """
    result: dict = {}
    bookmakers = (response.get("bookmakers") or [])
    if not bookmakers:
        return {}
    bm = bookmakers[0]
    for bet in bm.get("bets", []):
        bet_name = bet.get("name", "").lower()
        values   = bet.get("values", [])
        if "match winner" in bet_name or "1x2" in bet_name:
            for v in values:
                val = v.get("value", ""); odd = float(v.get("odd", 0))
                if val == "Home":   result["1"] = round(odd, 3)
                elif val == "Draw": result["X"] = round(odd, 3)
                elif val == "Away": result["2"] = round(odd, 3)
        elif "goals over/under" in bet_name or "total" in bet_name:
            for v in values:
                val = v.get("value", ""); odd = float(v.get("odd", 0))
                for pt in ["1.5", "2.5", "3.5"]:
                    if pt in val:
                        k = f"over_{pt}" if "over" in val.lower() else f"under_{pt}"
                        result[k] = round(odd, 3)
        elif "both teams to score" in bet_name:
            for v in values:
                val = v.get("value", ""); odd = float(v.get("odd", 0))
                if val == "Yes": result["btts_yes"] = round(odd, 3)
                elif val == "No": result["btts_no"] = round(odd, 3)
        elif "draw no bet" in bet_name:
            for v in values:
                val = v.get("value", ""); odd = float(v.get("odd", 0))
                if val == "Home": result["dnb_home"] = round(odd, 3)
                elif val == "Away": result["dnb_away"] = round(odd, 3)
        elif "double chance" in bet_name:
            for v in values:
                val = v.get("value", ""); odd = float(v.get("odd", 0))
                if val == "Home/Draw": result["dc_1x"] = round(odd, 3)
                elif val == "Home/Away": result["dc_12"] = round(odd, 3)
                elif val == "Draw/Away": result["dc_x2"] = round(odd, 3)
    if result.get("1"):
        result["_source_af_odds"] = True
    return result


def _parse_1xbet_game(game: dict, home: str, away: str) -> dict:
    """
    Парсит событие из 1xBet LineFeed.
    Типы ставок: T=1(H), T=2(D), T=3(A), T=9(over), T=10(under).
    """
    o1 = _norm(str(game.get("O1", "")))
    o2 = _norm(str(game.get("O2", "")))
    if not (_match_names(o1, home) and _match_names(o2, away)):
        return {}
    result: dict = {}
    for ev in game.get("E", []):
        t  = ev.get("T", 0)
        pt = ev.get("PT", 0)
        c  = float(ev.get("C", 0))
        if c < 1.01: continue
        if   t == 1 and pt == 1: result["1"] = round(c, 3)
        elif t == 2 and pt == 1: result["X"] = round(c, 3)
        elif t == 3 and pt == 1: result["2"] = round(c, 3)
        elif t == 9:
            for pt_line in [1.5, 2.5, 3.5]:
                if abs(pt - pt_line) < 0.05:
                    result[f"over_{pt_line}"] = round(c, 3)
        elif t == 10:
            for pt_line in [1.5, 2.5, 3.5]:
                if abs(pt - pt_line) < 0.05:
                    result[f"under_{pt_line}"] = round(c, 3)
        elif t == 17 and pt == 1: result["btts_yes"] = round(c, 3)
        elif t == 18 and pt == 1: result["btts_no"]  = round(c, 3)
        elif t == 47 and pt == 1: result["dnb_home"]  = round(c, 3)
        elif t == 48 and pt == 1: result["dnb_away"]  = round(c, 3)
        elif t == 19: result["dc_1x"] = round(c, 3)
        elif t == 20: result["dc_x2"] = round(c, 3)
        elif t == 21: result["dc_12"] = round(c, 3)
    if result.get("1"):
        result["_source_1xbet"] = True
    return result


# ── Основной класс ──────────────────────────────────────────────────
@dataclass
class OddsFetcher:
    """
    Единый интерфейс для получения коэффициентов из нескольких источников.

    Attributes:
        quota_left: остаток квоты Odds API
        cache: кэш запросов (fixture_id → bk_odds)
    """
    quota_left: int = 500
    cache: dict = field(default_factory=dict)
    _1xbet_games: list = field(default_factory=list)
    _1xbet_loaded_at: float = 0.0

    def get(
        self,
        home: str,
        away: str,
        fixture_id: int = 0,
        league_id: int  = 0,
        date: str        = "",
    ) -> dict:
        """
        Основной метод. Пробует источники по приоритету и возвращает
        первый успешный результат в стандартном формате bk_odds.

        Args:
            home:       английское название хозяев
            away:       английское название гостей
            fixture_id: ID фикстуры (для API-Football /odds)
            league_id:  ID лиги (для Odds API)
            date:       дата матча YYYY-MM-DD

        Returns:
            dict с коэфами или {} если все источники недоступны
        """
        cache_key = f"{home}|{away}|{date}"
        if cache_key in self.cache:
            return self.cache[cache_key]

        result: dict = {}

        # 1. The Odds API
        if not result and league_id and self.quota_left > 5:
            result = self._fetch_odds_api(league_id, home, away)
            if result:
                logger.info(f"  Odds API: {home} vs {away} — {len(result)} рынков")

        # 2. API-Football /odds
        if not result and fixture_id and API_FOOTBALL_KEY:
            result = self._fetch_af_odds(fixture_id)
            if result:
                logger.info(f"  AF Odds: {home} vs {away} — {len(result)} рынков")

        # 3. 1xBet unofficial
        if not result:
            result = self._fetch_1xbet(home, away)
            if result:
                logger.info(f"  1xBet: {home} vs {away} — {len(result)} рынков")

        if result:
            self.cache[cache_key] = result
        return result

    # ── Источник 1: Odds API ──────────────────────────────────────────
    def _fetch_odds_api(self, league_id: int, home: str, away: str) -> dict:
        """Получает коэфы из The Odds API."""
        sport_keys = ODDS_SPORT_KEYS.get(league_id, [])
        if not sport_keys:
            return {}
        key = ODDS_API_KEY_B if self.quota_left < 20 else ODDS_API_KEY
        if not key:
            return {}
        for sport_key in sport_keys:
            try:
                data = _get(
                    f"https://api.the-odds-api.com/v4/sports/{sport_key}/odds/",
                    params={"apiKey": key, "regions": "eu",
                            "markets": "h2h,totals,spreads",
                            "oddsFormat": "decimal"},
                )
                if not data or not isinstance(data, list):
                    continue
                # Обновляем остаток квоты
                for event in data:
                    parsed = _parse_odds_api_event(event, home, away)
                    if parsed:
                        return parsed
            except Exception as e:
                logger.debug(f"Odds API {sport_key}: {e}")
            time.sleep(REQUEST_DELAY)
        return {}

    # ── Источник 2: API-Football /odds ────────────────────────────────
    def _fetch_af_odds(self, fixture_id: int) -> dict:
        """Получает коэфы через API-Football /odds endpoint."""
        BOOKMAKER_IDS = [6, 8, 4, 5, 3]  # Bet365, 1xBet, Bwin, Unibet, William Hill
        for bm_id in BOOKMAKER_IDS:
            try:
                data = _get(
                    f"https://v3.football.api-sports.io/odds",
                    headers={"x-apisports-key": API_FOOTBALL_KEY},
                    params={"fixture": fixture_id, "bookmaker": bm_id},
                )
                resp = (data or {}).get("response", [])
                if not resp:
                    continue
                parsed = _parse_af_odds(resp[0])
                if parsed.get("1"):
                    return parsed
            except Exception as e:
                logger.debug(f"AF odds bm={bm_id}: {e}")
            time.sleep(REQUEST_DELAY)
        return {}

    # ── Источник 3: 1xBet unofficial ─────────────────────────────────
    def _fetch_1xbet(self, home: str, away: str) -> dict:
        """Получает коэфы из 1xBet без регистрации."""
        # Загружаем линию не чаще 1 раза в 5 минут
        now = time.time()
        if not self._1xbet_games or (now - self._1xbet_loaded_at) > 300:
            games = self._load_1xbet_line()
            if games:
                self._1xbet_games = games
                self._1xbet_loaded_at = now

        for game in self._1xbet_games:
            parsed = _parse_1xbet_game(game, home, away)
            if parsed.get("1"):
                return parsed
        return {}

    def _load_1xbet_line(self) -> list:
        """Загружает список матчей из 1xBet LineFeed."""
        url = (
            "https://1xbet.com/LineFeed/GetGamesList"
            "?sport=1&champ=0&count=100&lng=ru&tf=10800&tz=3&mode=2"
        )
        try:
            data = _get(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0)"})
            if data and isinstance(data.get("Value"), list):
                return data["Value"]
        except Exception as e:
            logger.debug(f"1xBet load: {e}")
        return []

    def report(self) -> str:
        """Краткий отчёт об использовании."""
        sources = set()
        for odds in self.cache.values():
            if odds.get("_source_odds_api"):  sources.add("Odds API")
            if odds.get("_source_af_odds"):   sources.add("AF Odds")
            if odds.get("_source_1xbet"):     sources.add("1xBet")
        return (f"OddsFetcher: {len(self.cache)} матчей в кэше "
                f"| источники: {', '.join(sources) or 'нет'}")


# ── Интеграция с football_bot_v3.py ────────────────────────────────
# Глобальный экземпляр — создаётся один раз за запуск бота
_fetcher: Optional[OddsFetcher] = None


def get_fetcher() -> OddsFetcher:
    """Возвращает глобальный экземпляр OddsFetcher (singleton)."""
    global _fetcher
    if _fetcher is None:
        _fetcher = OddsFetcher()
    return _fetcher


def fetch_real_odds(
    home: str,
    away: str,
    fixture_id: int = 0,
    league_id: int  = 0,
    date: str        = "",
) -> dict:
    """
    Удобная функция-обёртка для вызова из football_bot_v3.py.

    Вставить в run_scan() ПЕРЕД цепочкой источников:
        from odds_fetcher import fetch_real_odds
        bk_odds = fetch_real_odds(hname_en, aname_en, fid, league_id, fdate)

    Returns:
        dict с коэфами или {} при неудаче
    """
    return get_fetcher().get(
        home=home, away=away,
        fixture_id=fixture_id,
        league_id=league_id,
        date=date,
    )


if __name__ == "__main__":
    """Быстрый тест: python odds_fetcher.py"""
    import sys
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    print("=" * 55)
    print("  TEST odds_fetcher.py")
    print("=" * 55)

    fetcher = OddsFetcher()

    # Тест 1: Odds API (нужен ODDS_API_KEY)
    print("\n1. Odds API — Arsenal vs Chelsea (АПЛ):")
    r1 = fetcher._fetch_odds_api(39, "Arsenal", "Chelsea")
    if r1:
        print(f"   1={r1.get('1')} X={r1.get('X')} 2={r1.get('2')}")
        print(f"   over_2.5={r1.get('over_2.5')} under_2.5={r1.get('under_2.5')}")
    else:
        print("   ⚠️  Нет данных (Odds API недоступен или нет ближайших матчей)")

    # Тест 2: 1xBet
    print("\n2. 1xBet — любые матчи сегодня:")
    games = fetcher._load_1xbet_line()
    if games:
        print(f"   ✅ Загружено {len(games)} матчей из 1xBet")
        if games:
            g = games[0]
            print(f"   Пример: {g.get('O1')} vs {g.get('O2')}")
    else:
        print("   ⚠️  1xBet недоступен")

    print("\n3. Итог:")
    print(f"   {fetcher.report()}")
    print("=" * 55)
