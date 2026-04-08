"""
betfair_client.py — Полная интеграция с Betfair Exchange API.

Возможности:
  - Non-interactive login (сессионный токен, без сертификатов)
  - Получение коэфов на матчи (match odds, totals, corners, cards)
  - Отслеживание движения линии
  - Кеш сессии (токен живёт 8 часов)

Документация: https://docs.developer.betfair.com/

Usage:
    from betfair_client import BetfairClient
    bf = BetfairClient()
    if bf.login():
        odds = bf.get_match_odds("Arsenal", "Chelsea", "2026-04-05")
        print(odds)  # {"1": 2.10, "X": 3.50, "2": 4.20}
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

log = logging.getLogger(__name__)

# ── Константы Betfair API ───────────────────────────────────────────
BF_LOGIN_URL  = "https://identitysso.betfair.com/api/login"
BF_API_URL    = "https://api.betfair.com/exchange/betting/json-rpc/v1"
BF_APP_KEY    = os.getenv("BETFAIR_APPKEY", "")
BF_SESSION_TTL = 28800  # 8 часов

# Betfair market types
SOCCER_EVENT_TYPE = "1"
MARKET_MATCH_ODDS = "MATCH_ODDS"
MARKET_OVER_UNDER = "OVER_UNDER_{pt}"
MARKET_BOTH_TEAMS = "BOTH_TEAMS_TO_SCORE"
MARKET_CORRECT_SCORE = "CORRECT_SCORE"


def _ssl_ctx() -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode    = ssl.CERT_NONE
    return ctx


def _post(url: str, data: bytes, headers: dict) -> Optional[dict]:
    """POST запрос с SSL-фиксом."""
    req = urllib.request.Request(url, data=data, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=15, context=_ssl_ctx()) as r:
            return json.loads(r.read().decode())
    except Exception as e:
        log.debug(f"POST {url[:50]}: {e}")
        return None


@dataclass
class BetfairClient:
    """
    Клиент Betfair Exchange.

    Attributes:
        session_token: текущий токен сессии
        session_expires: время истечения токена
        _cache: кеш запросов (market_id → runners)
    """
    username:        str = field(default_factory=lambda: os.getenv("BETFAIR_USER", ""))
    password:        str = field(default_factory=lambda: os.getenv("BETFAIR_PASS", ""))
    app_key:         str = field(default_factory=lambda: BF_APP_KEY or os.getenv("BETFAIR_APPKEY", ""))
    session_token:   str = ""
    session_expires: float = 0.0
    _cache:          dict = field(default_factory=dict)

    def is_configured(self) -> bool:
        """True если логин и пароль заданы."""
        return bool(self.username and self.password)

    def is_logged_in(self) -> bool:
        """True если есть действующий токен."""
        return bool(self.session_token) and time.time() < self.session_expires

    def login(self) -> bool:
        """
        Логин на Betfair (non-interactive, без сертификатов).
        Использует Identity SSO endpoint.
        Кешируем токен на BF_SESSION_TTL секунд.
        """
        if self.is_logged_in():
            return True
        if not self.is_configured():
            log.debug("Betfair: логин/пароль не заданы")
            return False
        body = urllib.parse.urlencode({
            "username": self.username,
            "password": self.password,
        }).encode()
        resp = _post(
            BF_LOGIN_URL,
            body,
            {
                "Content-Type": "application/x-www-form-urlencoded",
                "X-Application": self.app_key or "1",
                "Accept": "application/json",
            },
        )
        if not resp:
            log.warning("Betfair: нет ответа от сервера")
            return False
        status = resp.get("status", "")
        token  = resp.get("token", "")
        if status == "SUCCESS" and token:
            self.session_token   = token
            self.session_expires = time.time() + BF_SESSION_TTL
            log.info("Betfair: ✅ авторизован")
            return True
        err = resp.get("error", status)
        log.warning(f"Betfair: ❌ {err}")
        return False

    def _api(self, method: str, params: dict) -> Optional[dict]:
        """Выполняет JSON-RPC запрос к Betfair API."""
        if not self.is_logged_in():
            if not self.login():
                return None
        payload = json.dumps([{
            "jsonrpc": "2.0",
            "method":  f"SportsAPING/v1.0/{method}",
            "params":  params,
            "id":      1,
        }]).encode()
        resp = _post(
            BF_API_URL,
            payload,
            {
                "Content-Type":  "application/json",
                "X-Application": self.app_key or "1",
                "X-Authentication": self.session_token,
            },
        )
        if not resp or not isinstance(resp, list):
            return None
        result = resp[0].get("result")
        error  = resp[0].get("error")
        if error:
            log.debug(f"Betfair API error: {error}")
        return result

    def find_event(self, home: str, away: str, date_str: str) -> Optional[str]:
        """
        Ищет event_id матча на Betfair.
        Возвращает Betfair event ID или None.
        """
        cache_key = f"event_{home}_{away}_{date_str}"
        if cache_key in self._cache:
            return self._cache[cache_key]
        events = self._api("listEvents", {
            "filter": {
                "eventTypeIds": [SOCCER_EVENT_TYPE],
                "marketStartTime": {
                    "from": f"{date_str}T00:00:00Z",
                    "to":   f"{date_str}T23:59:59Z",
                },
                "textQuery": home[:10],
            }
        })
        if not events:
            return None

        def _norm(s: str) -> str:
            return s.lower().replace("fc", "").replace("  ", " ").strip()

        hn = _norm(home); an = _norm(away)
        for ev in events:
            ev_name = _norm(ev.get("event", {}).get("name", ""))
            # Betfair format: "Arsenal v Chelsea" или "Arsenal vs Chelsea"
            if any(sep in ev_name for sep in [" v ", " vs "]):
                parts = ev_name.replace(" vs ", " v ").split(" v ", 1)
                if len(parts) == 2:
                    h_part = parts[0].strip(); a_part = parts[1].strip()
                    if hn[:5] in h_part and an[:5] in a_part:
                        eid = str(ev.get("event", {}).get("id", ""))
                        self._cache[cache_key] = eid
                        return eid
        return None

    def get_markets(self, event_id: str) -> list[dict]:
        """Получает список рынков для события."""
        cache_key = f"markets_{event_id}"
        if cache_key in self._cache:
            return self._cache[cache_key]
        markets = self._api("listMarketCatalogue", {
            "filter": {"eventIds": [event_id]},
            "marketProjection": ["MARKET_NAME", "RUNNER_DESCRIPTION"],
            "maxResults": "20",
        })
        result = markets or []
        self._cache[cache_key] = result
        return result

    def get_runner_prices(self, market_id: str) -> list[dict]:
        """Получает цены (коэфы) для рынка."""
        books = self._api("listMarketBook", {
            "marketIds": [market_id],
            "priceProjection": {
                "priceData": ["EX_BEST_OFFERS"],
                "exBestOffersOverrides": {"bestPricesDepth": 3},
            },
        })
        if not books:
            return []
        return books[0].get("runners", []) if books else []

    def get_match_odds(self, home: str, away: str, date_str: str) -> dict:
        """
        Основной метод: получает стандартный bk_odds dict.
        Ищет Match Odds рынок и возвращает Best Available цены.
        Betfair — биржа, нет маржи → идеальный no-vig источник.
        """
        result: dict = {}
        event_id = self.find_event(home, away, date_str)
        if not event_id:
            log.debug(f"Betfair: не найден {home} vs {away} {date_str}")
            return {}
        markets = self.get_markets(event_id)
        for mkt in markets:
            mkt_name = mkt.get("marketName", "").upper()
            mkt_id   = mkt.get("marketId", "")
            runners  = self.get_runner_prices(mkt_id)

            if mkt_name == "MATCH ODDS" and not result.get("1"):
                runner_names = {r.get("selectionId"): r.get("runnerName", "")
                                for r in mkt.get("runners", [])}
                for runner in runners:
                    sid   = runner.get("selectionId")
                    name  = runner_names.get(sid, "")
                    best  = runner.get("ex", {}).get("availableToBack", [])
                    price = best[0].get("price", 0) if best else 0
                    if price < 1.01: continue
                    name_lower = name.lower()
                    # Betfair runner names: "Arsenal", "Chelsea", "The Draw"
                    if "draw" in name_lower or "tie" in name_lower:
                        result["X"] = round(price, 2)
                    elif home.lower()[:5] in name_lower:
                        result["1"] = round(price, 2)
                    else:
                        result["2"] = round(price, 2)

            elif "OVER/UNDER" in mkt_name:
                pt_str = mkt_name.replace("OVER/UNDER ", "").replace(" GOALS", "").strip()
                try:
                    pt = float(pt_str)
                    for runner in runners:
                        rname = runner.get("runnerName", "").lower()
                        best  = runner.get("ex", {}).get("availableToBack", [])
                        price = best[0].get("price", 0) if best else 0
                        if price < 1.01: continue
                        if "over" in rname:
                            result[f"over_{pt}"] = round(price, 2)
                        elif "under" in rname:
                            result[f"under_{pt}"] = round(price, 2)
                except (ValueError, IndexError):
                    pass

            elif "BOTH TEAMS" in mkt_name:
                for runner in runners:
                    rname = runner.get("runnerName", "").lower()
                    best  = runner.get("ex", {}).get("availableToBack", [])
                    price = best[0].get("price", 0) if best else 0
                    if price < 1.01: continue
                    if "yes" in rname:
                        result["btts_yes"] = round(price, 2)
                    elif "no" in rname:
                        result["btts_no"]  = round(price, 2)

        if result.get("1"):
            result["_source_betfair"] = True
            log.info(f"Betfair: {home} vs {away} — "
                     f"1={result.get('1')} X={result.get('X')} 2={result.get('2')}")
        return result

    def get_live_odds(self, market_id: str) -> dict:
        """Получает текущие live-цены для отслеживания движения линии."""
        runners = self.get_runner_prices(market_id)
        result: dict = {}
        for i, runner in enumerate(runners):
            back = runner.get("ex", {}).get("availableToBack", [])
            lay  = runner.get("ex", {}).get("availableToLay", [])
            best_back = back[0].get("price", 0) if back else 0
            best_lay  = lay[0].get("price", 0) if lay else 0
            result[f"runner_{i}_back"] = best_back
            result[f"runner_{i}_lay"]  = best_lay
        return result


# ── Глобальный singleton ─────────────────────────────────────────────
_bf_client: Optional[BetfairClient] = None


def get_betfair() -> BetfairClient:
    """Возвращает глобальный экземпляр BetfairClient."""
    global _bf_client
    if _bf_client is None:
        _bf_client = BetfairClient()
    return _bf_client


def fetch_betfair_odds_new(home: str, away: str, date_str: str) -> dict:
    """
    Функция-обёртка для вызова из football_bot_v3.py.
    Автоматически логинится при первом вызове.
    """
    bf = get_betfair()
    if not bf.is_configured():
        return {}
    if not bf.is_logged_in():
        bf.login()
    return bf.get_match_odds(home, away, date_str)


if __name__ == "__main__":
    """Тест: python betfair_client.py"""
    import sys
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    bf = BetfairClient()
    print("=" * 55)
    print("  TEST betfair_client.py")
    print("=" * 55)
    if not bf.is_configured():
        print("\n⚠️  BETFAIR_USER/BETFAIR_PASS не заданы в .env")
        print("   Добавь в .env:")
        print("   BETFAIR_USER=your_username")
        print("   BETFAIR_PASS=your_password")
        sys.exit(0)
    print(f"\n1. Логин ({bf.username})...")
    ok = bf.login()
    print(f"   {'✅ OK' if ok else '❌ Ошибка'}")
    if ok:
        print("\n2. Поиск матча Arsenal vs Chelsea...")
        import datetime
        tomorrow = (datetime.date.today() + datetime.timedelta(days=1)).isoformat()
        odds = bf.get_match_odds("Arsenal", "Chelsea", tomorrow)
        if odds:
            print(f"   1={odds.get('1')} X={odds.get('X')} 2={odds.get('2')}")
        else:
            print("   Нет ближайших матчей (норма вне игрового дня)")
    print("=" * 55)
