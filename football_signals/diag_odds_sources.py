#!/usr/bin/env python3
"""
Диагностика всех источников коэфов.
python diag_odds_sources.py
"""
import requests, urllib3, json, datetime
urllib3.disable_warnings()

TODAY = str(datetime.date.today())
ODDS_KEY = "bde9f6c40f7b65d8dbf60b2356dba4ce"

print("=" * 60)
print(f"  ДИАГНОСТИКА ИСТОЧНИКОВ КОЭФОВ — {TODAY}")
print("=" * 60)

results = {}

# 1. Pinnacle Guest API
print("\n1. Pinnacle Guest API (без регистрации):")
try:
    r = requests.get(
        "https://guest.api.arcadia.pinnacle.com/0.1/sports/29/leagues?all=false",
        headers={"User-Agent": "Mozilla/5.0", "X-Device-UUID": "abc-123"},
        timeout=10, verify=False)
    print(f"   HTTP {r.status_code} | {len(r.content)}b")
    if r.status_code == 200:
        d = r.json()
        print(f"   Лиг: {len(d)} ✅ Pinnacle Guest РАБОТАЕТ")
        results["pinnacle"] = True
    else:
        print(f"   Body: {r.text[:80]}")
        results["pinnacle"] = False
except Exception as e:
    print(f"   ERR: {str(e)[:70]}")
    results["pinnacle"] = False

# 2. The Odds API
print("\n2. The Odds API:")
try:
    r = requests.get(
        "https://api.the-odds-api.com/v4/sports/soccer_epl/odds/",
        params={"apiKey": ODDS_KEY, "regions": "eu", "markets": "h2h",
                "oddsFormat": "decimal"},
        timeout=10, verify=False)
    print(f"   HTTP {r.status_code} | quota={r.headers.get('x-requests-remaining','?')}")
    if r.status_code == 200:
        evs = r.json()
        print(f"   {len(evs)} матчей ✅ Odds API РАБОТАЕТ")
        results["odds_api"] = True
    else:
        print(f"   {r.text[:80]}")
        results["odds_api"] = False
except Exception as e:
    print(f"   ERR: {str(e)[:70]}")
    results["odds_api"] = False

# 3. SofaScore football
print("\n3. SofaScore football (бесплатно):")
for ua in [
    "SofaScore/70 CFNetwork/1492.0.1 Darwin/23.3.0",
    "okhttp/4.9.3",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
]:
    try:
        r = requests.get(
            f"https://api.sofascore.com/api/v1/sport/football/scheduled-events/{TODAY}",
            headers={"User-Agent": ua, "Referer": "https://www.sofascore.com/"},
            timeout=12, verify=False)
        evs = r.json().get("events", []) if r.status_code == 200 else []
        print(f"   {r.status_code} | {len(evs)} матчей | {ua[:35]}")
        if evs:
            results["sofascore"] = True
            break
    except Exception as e:
        print(f"   ERR | {str(e)[:50]}")
    results["sofascore"] = False

# 4. BetExplorer (unoffcial API)
print("\n4. BetExplorer:")
try:
    r = requests.get(
        f"https://www.betexplorer.com/aidpage/aidpage/soccer/?date={TODAY}",
        headers={"User-Agent": "Mozilla/5.0"},
        timeout=10, verify=False)
    print(f"   HTTP {r.status_code} | {len(r.content)}b")
    if r.status_code == 200:
        results["betexplorer"] = True
        print("   ✅ BetExplorer доступен")
    else:
        results["betexplorer"] = False
except Exception as e:
    print(f"   ERR: {str(e)[:70]}")
    results["betexplorer"] = False

# 5. 1xBet unofficial API
print("\n5. 1xBet (неофициальный API):")
try:
    r = requests.get(
        "https://1xbet.com/LineFeed/GetGameZip?id=239&lng=ru&tf=10800&tz=3&gr=35&mode=2",
        headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"},
        timeout=10, verify=False)
    print(f"   HTTP {r.status_code} | {len(r.content)}b")
    if r.status_code == 200:
        results["1xbet"] = True
        print("   ✅ 1xBet API доступен")
except Exception as e:
    print(f"   ERR: {str(e)[:70]}")
    results["1xbet"] = False

# 6. Betway API (официальный)
print("\n6. api-football.com (тот же ключ что AF):")
AF_KEY = "33d9e41279e34866b001ab44dade2540"
try:
    r = requests.get(
        "https://v3.football.api-sports.io/odds?fixture=1089695&bookmaker=5",
        headers={"x-apisports-key": AF_KEY},
        timeout=10, verify=False)
    print(f"   HTTP {r.status_code}")
    if r.status_code == 200:
        d = r.json()
        resp = d.get("response", [])
        print(f"   {len(resp)} результатов ✅ API-Football ODDS работает")
        if resp:
            bm_list = resp[0].get("bookmakers", [])
            print(f"   Букмекеров: {len(bm_list)}")
        results["api_football_odds"] = True
    else:
        print(f"   {r.text[:80]}")
        results["api_football_odds"] = False
except Exception as e:
    print(f"   ERR: {str(e)[:70]}")
    results["api_football_odds"] = False

# 7. API-Football /odds for today
print("\n7. API-Football /odds для сегодня:")
try:
    r = requests.get(
        f"https://v3.football.api-sports.io/odds?date={TODAY}&bookmaker=5&season=2025",
        headers={"x-apisports-key": AF_KEY},
        timeout=10, verify=False)
    print(f"   HTTP {r.status_code}")
    if r.status_code == 200:
        d = r.json()
        resp = d.get("response", [])
        rem = r.headers.get("x-ratelimit-requests-remaining", "?")
        print(f"   {len(resp)} матчей | quota left: {rem}")
        if resp:
            fix = resp[0]
            teams = fix.get("fixture", {}).get("teams", {})
            print(f"   Пример: {teams}")
        results["af_odds_today"] = len(resp) > 0
except Exception as e:
    print(f"   ERR: {str(e)[:70]}")
    results["af_odds_today"] = False

print()
print("=" * 60)
print("  ИТОГ:")
for src, ok in results.items():
    print(f"  {'✅' if ok else '❌'} {src}")
working = [k for k, v in results.items() if v]
print(f"\n  Работает: {len(working)}/{len(results)} источников")
if not working:
    print("  → ВСЕ ИСТОЧНИКИ НЕДОСТУПНЫ")
    print("  → Проверь VPN или сетевые настройки")
print("=" * 60)
