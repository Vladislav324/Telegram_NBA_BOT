"""
╔══════════════════════════════════════════════════════════════╗
║         🧠  МОДУЛЬ САМООБУЧЕНИЯ  (learning.py)              ║
╚══════════════════════════════════════════════════════════════╝
python learning.py          — проверить завершённые матчи
python learning.py stats    — точность и ROI по рынкам
python learning.py sheets   — только синхронизация с Google Sheets
"""
import os, sys, json, ssl, time, datetime
from typing import Optional

PREDICTIONS_FILE = "predictions.json"
RESULTS_FILE     = "results.json"
TEAM_STATS_FILE  = "team_stats.json"
LEARN_RATE       = 0.15

# ── Батч-кэш результатов по дате: {date: {fixture_id: {home,away}}} ──
# Загружается один раз в run_update — экономит AF квоту
_RESULTS_BATCH_CACHE: dict = {}

def _load_batch_results(date_str: str, af_key: str, fd_key: str = "") -> dict:
    """
    Загружает ВСЕ результаты за date_str одним запросом.
    Кэширует в _RESULTS_BATCH_CACHE[date_str].
    Возвращает: {fixture_id(int): {"home": H, "away": A, "status": S}} +
                {"_by_name": {"home_lower|away_lower": same_dict}}
    """
    global _RESULTS_BATCH_CACHE
    if date_str in _RESULTS_BATCH_CACHE:
        return _RESULTS_BATCH_CACHE[date_str]

    batch = {}   # fixture_id → result dict
    by_name = {}  # "home_lower|away_lower" → result dict

    def _add(fid, hn, an, hg, ag, st, hg1=None, ag1=None, hg_full=None, ag_full=None):
        """fid=fixture_id, hg/ag=счёт 90мин, hg1/ag1=1Т, hg_full/ag_full=финал (ОТ/пен.).
        ВАЖНО: НЕ перезаписывает by_name если запись уже есть (AF > FD > SofaScore > TSDB).
        """
        r = {"home": hg, "away": ag, "status": st}
        if hg1 is not None and ag1 is not None:
            r["home_ht"] = hg1
            r["away_ht"] = ag1
        if hg_full is not None and ag_full is not None:
            r["home_full"] = hg_full
            r["away_full"] = ag_full
        if fid:
            batch[int(fid)] = r   # fixture_id всегда обновляется (точный ключ)
        # Нормализуем имена для матчинга
        def _n(s):
            s = s.lower().strip()
            for sfx in (" fc", " afc", " sc", " cf", " ac", " united", " city"):
                if s.endswith(sfx): s = s[:-len(sfx)].strip()
            return s
        for hk in (hn.lower(), _n(hn)):
            for ak in (an.lower(), _n(an)):
                key = f"{hk}|{ak}"
                if key not in by_name:   # НЕ перезаписываем — первый источник имеет приоритет
                    by_name[key] = r

    # ── Источник 1: API-Football (один запрос на всю дату) ───────
    af_loaded = 0
    if af_key:
        # FIX: убран status=FT из URL — на free-плане фильтр может не работать.
        # Вместо этого фильтруем завершённые статусы локально.
        _af_url = f"https://v3.football.api-sports.io/fixtures?date={date_str}"
        try:
            data = _get(_af_url, {"x-apisports-key": af_key}, timeout=20)
            if data is None:
                print(f"  ⚠️  AF: нет ответа за {date_str} (сетевая ошибка или недоступен)")
            elif not isinstance(data, dict):
                print(f"  ⚠️  AF: неожиданный тип ответа: {type(data)}")
            else:
                # _error — добавляется при HTTP != 200
                if "_error" in data:
                    _st = data.get("_status", "?")
                    if _st == 429:
                        print(f"  🔴 AF: квота исчерпана (429) — результаты будут из FD")
                    elif _st in (401, 403):
                        print(f"  🔴 AF: неверный ключ ({_st}) — проверь API_FOOTBALL_KEY")
                    else:
                        print(f"  ⚠️  AF HTTP {_st}: {data['_error'][:80]}")
                errors = data.get("errors", {})
                if errors and "_error" not in data:
                    err_str = str(errors)
                    if "do not have access to this date" in err_str:
                        import re as _re_af
                        _m = _re_af.search(r"try from (\S+) to (\S+)", err_str)
                        if _m:
                            print(f"  ℹ️  AF Free: {date_str} недоступна (план: {_m.group(1)}→{_m.group(2)}) — используем FD+TSDB")
                        else:
                            print(f"  ℹ️  AF Free: {date_str} недоступна по плану — используем FD+TSDB")
                    else:
                        print(f"  ⚠️  AF API ошибка: {err_str[:100]}")
                resp = data.get("response", [])
                if not resp and "_error" not in data and not errors:
                    print(f"  ⚠️  AF: пустой ответ за {date_str} — нет данных или квота")
                _FINISHED = {"FT", "AET", "PEN", "AWD"}
                for fix in resp:
                    try:
                        st = fix["fixture"]["status"]["short"]
                        if st not in _FINISHED:
                            continue
                        fid = fix["fixture"]["id"]
                        hn  = fix["teams"]["home"]["name"]
                        an  = fix["teams"]["away"]["name"]
                        sc  = fix.get("score", {})
                        # Всегда берём счёт 90 мин (fulltime) — для AET/PEN это 90 мин
                        ft  = sc.get("fulltime") or sc.get("fullTime") or {}
                        hg  = ft.get("home") if ft else None
                        ag  = ft.get("away") if ft else None
                        # fallback на goals если fulltime пустой
                        if hg is None or ag is None:
                            goals = fix.get("goals", {})
                            hg = goals.get("home")
                            ag = goals.get("away")
                        if hg is None or ag is None:
                            continue
                        _add(fid, hn, an, int(hg), int(ag), st)
                        af_loaded += 1
                    except Exception:
                        continue
        except Exception as _e:
            print(f"  ⚠️  AF исключение: {str(_e)[:80]}")
    if af_loaded:
        print(f"  📡 AF: загружено {af_loaded} результатов за {date_str}")

    # ── Источник 2: football-data.org (топ-8 лиг, работает без ключа) ──
    # Бундеслига, Серия А, Ла Лига, Лига 1, АПЛ, ЛЧ, ЛЕ, ЛКЕ
    fd_loaded = 0
    try:
        import urllib.request as _ureq
        import ssl as _ssl
        _ctx2 = _ssl.create_default_context()
        _ctx2.check_hostname = False
        _ctx2.verify_mode = _ssl.CERT_NONE
        _fd_hdrs = {"X-Auth-Token": fd_key} if fd_key else {}
        _fd_url  = (f"https://api.football-data.org/v4/matches"
                    f"?dateFrom={date_str}&dateTo={date_str}&status=FINISHED")
        _fd_req  = _ureq.Request(_fd_url, headers={"User-Agent": "Bot/1.0", **_fd_hdrs})
        with _ureq.urlopen(_fd_req, timeout=15, context=_ctx2) as _r:
            fd_data = json.load(_r)
        for m in fd_data.get("matches", []):
            try:
                hn  = (m["homeTeam"].get("shortName") or m["homeTeam"].get("name",""))
                an  = (m["awayTeam"].get("shortName") or m["awayTeam"].get("name",""))
                hn2 = m["homeTeam"].get("name","")
                an2 = m["awayTeam"].get("name","")
                if not hn2 or not an2:
                    continue
                hg  = m["score"]["fullTime"]["home"]
                ag  = m["score"]["fullTime"]["away"]
                if hg is None or ag is None:
                    continue
                _add(None, hn,  an,  int(hg), int(ag), "FT")
                _add(None, hn2, an2, int(hg), int(ag), "FT")
                fd_loaded += 1
            except Exception:
                continue
    except Exception as _fe:
        _fe_s = str(_fe)
        if "403" in _fe_s:
            print(f"  ⚠️  FD: доступ запрещён — добавь FOOTBALL_DATA_KEY в бот")
        elif "429" in _fe_s:
            print(f"  ⚠️  FD: слишком много запросов (429) — подождите минуту")
        elif "401" in _fe_s:
            print(f"  ⚠️  FD: неверный ключ (401)")
        elif "timed out" in _fe_s.lower() or "timeout" in _fe_s.lower():
            print(f"  ⚠️  FD: таймаут соединения")
        elif "10061" in _fe_s or "Connection refused" in _fe_s:
            print(f"  ⚠️  FD: сервер отклонил соединение (WinError 10061)")
            print(f"     Возможные причины: антивирус / VPN / football-data.org временно недоступен")
        elif "11001" in _fe_s or "getaddrinfo" in _fe_s.lower():
            print(f"  ⚠️  FD: DNS ошибка — нет интернета или FD недоступен")
        else:
            print(f"  ⚠️  FD недоступен: {_fe_s[:80]}")

    if fd_loaded:
        print(f"  📊 FD: загружено {fd_loaded} результатов за {date_str}")

    # ── Источник 3: SofaScore — бесплатно, без ключа, покрывает ЛЧ/ЛЕ ──
    sofa_loaded = 0
    try:
        _sofa_hdrs = {
            "User-Agent": "SofaScore/70 CFNetwork/1492.0.1 Darwin/23.3.0",
            "Referer": "https://www.sofascore.com/",
        }
        _sofa_url = f"https://api.sofascore.com/api/v1/sport/football/scheduled-events/{date_str}"
        _sofa_data = _get(_sofa_url, _sofa_hdrs, timeout=15)
        if _sofa_data and isinstance(_sofa_data, dict):
            _SOFA_DONE = {"finished", "ended", "after extra time", "after penalties"}
            for ev in (_sofa_data.get("events") or []):
                try:
                    st_type = ev.get("status", {}).get("type", "").lower()
                    st_desc = ev.get("status", {}).get("description", "").lower()
                    if st_type not in ("finished",) and st_desc not in _SOFA_DONE:
                        continue
                    hn  = ev.get("homeTeam", {}).get("name", "")
                    an  = ev.get("awayTeam", {}).get("name", "")
                    hg  = ev.get("homeScore", {}).get("current")
                    ag  = ev.get("awayScore", {}).get("current")
                    # Короткое имя как альтернатива
                    hn2 = ev.get("homeTeam", {}).get("shortName", hn)
                    an2 = ev.get("awayTeam", {}).get("shortName", an)
                    if not hn or not an or hg is None or ag is None:
                        continue
                    # SofaScore: current = финальный счёт (с ОТ/пен), normaltime = 90 мин
                    # Для проверки ставок нужен счёт 90 мин (normaltime),
                    # для отображения — финальный (current = hg_full)
                    hg_full = ag_full = None  # финальный счёт (ОТ/пен)
                    desc_lower = ev.get("status", {}).get("description", "").lower()
                    if desc_lower in ("after extra time", "after penalties", "after extra time (et)", "penalties"):
                        nt  = ev.get("homeScore", {}).get("normaltime")
                        nat = ev.get("awayScore", {}).get("normaltime")
                        if nt is not None and nat is not None:
                            hg_full, ag_full = int(hg), int(ag)  # сохраняем current как финальный
                            hg, ag = int(nt), int(nat)           # подменяем на 90 мин
                    # Счёт первого тайма из periodScores
                    hg1 = ag1 = None
                    for ps in (ev.get("homeScore", {}).get("period1"), None):
                        pass  # period1 не в homeScore
                    # SofaScore: periodScores — список по периодам
                    periods = ev.get("homeScore", {})
                    if "period1" in periods:
                        hg1 = int(periods["period1"])
                        ag1 = int(ev.get("awayScore", {}).get("period1", 0))
                    _add(ev.get("id"), hn,  an,  int(hg), int(ag), "FT", hg1, ag1, hg_full, ag_full)
                    if hn2 != hn or an2 != an:
                        _add(None, hn2, an2, int(hg), int(ag), "FT", hg1, ag1, hg_full, ag_full)
                    sofa_loaded += 1
                except Exception:
                    continue
    except Exception:
        pass

    if sofa_loaded:
        print(f"  🟢 SofaScore: загружено {sofa_loaded} результатов за {date_str}")

    # ── Источник 4: TheSportsDB — бесплатно, без ключа ───────────
    # Покрывает Чемпионшип, Эредивизи, Примейра, и другие лиги не в FD
    # Маппинг: league_name → TheSportsDB league ID
    _TSDB_IDS = {
        "Чемпионшип":     4335,  # EFL Championship
        "Эредивизи":      4337,  # Eredivisie
        "Примейра лига":  4344,  # Primeira Liga Portugal
        "Серия Б":        4336,  # Serie B Italy
        "Сегунда":        4340,  # Segunda Division
        "Лига 1 Англ":    4336,  # EFL League One (id approximation)
        "Сегунда Б":      4340,
    }
    # Запрашиваем завершённые матчи по каждой нужной дате
    # GET /api/v1/json/3/eventsday.php?d=YYYY-MM-DD&s=Soccer
    tsdb_loaded = 0
    try:
        _tsdb_url = f"https://www.thesportsdb.com/api/v1/json/3/eventsday.php?d={date_str}&s=Soccer"
        _tsdb_data = _get(_tsdb_url, timeout=15)
        if _tsdb_data and isinstance(_tsdb_data, dict):
            for ev in (_tsdb_data.get("events") or []):
                try:
                    # Только завершённые матчи
                    _tsdb_ok = {"Match Finished", "FT", "After Extra Time", "After Pens", "After Penalties", "Finished", "ended", "full-time", "Full Time"}
                    if ev.get("strStatus") not in _tsdb_ok:
                        continue
                    hn  = ev.get("strHomeTeam","")
                    an  = ev.get("strAwayTeam","")
                    hg  = ev.get("intHomeScore")
                    ag  = ev.get("intAwayScore")
                    if not hn or not an or hg is None or ag is None:
                        continue
                    _add(None, hn, an, int(hg), int(ag), "FT")
                    tsdb_loaded += 1
                except Exception:
                    continue
    except Exception:
        pass

    if tsdb_loaded:
        print(f"  🌐 TSDB: загружено {tsdb_loaded} результатов за {date_str}")


    if af_loaded == 0 and fd_loaded == 0 and tsdb_loaded == 0 and sofa_loaded == 0:
        print(f"  ⚠️  Все источники пусты за {date_str}")

    batch["_by_name"] = by_name
    _RESULTS_BATCH_CACHE[date_str] = batch
    return batch

# ══════════════════════════════════════════════════════════════
#  📊  GOOGLE SHEETS НАСТРОЙКИ
#  Как получить SHEET_ID и credentials.json — см. инструкцию ниже
# ══════════════════════════════════════════════════════════════
SHEET_ID        = "1R6_VG3BqpJK-qW2ItBHm4Mvqpa27uheFEOXQx1IjJ80"   # ← вставь ID таблицы (из URL Google Sheets)
CREDS_FILE      = "credentials.json"  # ← файл ключа сервисного аккаунта
# Названия вкладок автоматически включают текущий месяц
# Например: "Сигналы_Март_2026", "Статистика_Март_2026"
SHEET_TAB_SIGS  = "Сигналы"    # базовое имя — месяц добавится автоматически
SHEET_TAB_STATS = "Статистика" # базовое имя — месяц добавится автоматически

_MONTH_RU = {
    1:"Январь", 2:"Февраль", 3:"Март", 4:"Апрель",
    5:"Май", 6:"Июнь", 7:"Июль", 8:"Август",
    9:"Сентябрь", 10:"Октябрь", 11:"Ноябрь", 12:"Декабрь"
}

def _monthly_tab(base: str, date_str: str = "") -> str:
    """
    Возвращает название вкладки с месяцем.
    Например: "Сигналы_Март_2026"
    date_str — дата матча (YYYY-MM-DD), если пустая — берём текущий месяц.
    """
    try:
        if date_str:
            dt = datetime.datetime.strptime(date_str[:10], "%Y-%m-%d")
        else:
            dt = datetime.datetime.now()
        month_name = _MONTH_RU.get(dt.month, str(dt.month))
        return f"{base}_{month_name}_{dt.year}"
    except Exception:
        return base

# Заголовки таблицы сигналов
HEADERS = [
    "Дата", "Время", "Матч", "Лига",
    "Счёт", "xG (прогноз)",
    "Рынок", "Выбор", "Коэф", "Валуй %",
    "Шанс %", "EV", "Уверенность",
    "✅/❌", "Записано"
]

# ──────────────────────────────────────────────────────────────
#  📂  ФАЙЛЫ
# ──────────────────────────────────────────────────────────────
def _load(path):
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {} if "stats" in path else []

def _save(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

# ──────────────────────────────────────────────────────────────
#  🔐  RSA-SHA256 — чистый Python, без внешних зависимостей
# ──────────────────────────────────────────────────────────────
def _rsa_sha256_sign(message: bytes, pem_key: str) -> bytes:
    """
    Подписывает сообщение приватным RSA ключом (PKCS#1 v1.5 + SHA-256).
    Использует только стандартные библиотеки Python — cryptography не нужна.
    """
    import base64, hashlib, re

    # ── Парсим PEM ────────────────────────────────────────────
    pem = pem_key.strip().replace("\\n", "\n")
    # Убираем заголовки и декодируем DER
    b64 = re.sub(r"-----.*?-----|\s", "", pem)
    der = base64.b64decode(b64)

    # ── Парсим DER/ASN.1 для PKCS#8 или PKCS#1 ───────────────
    def _parse_int(data, pos):
        """Читает INTEGER из ASN.1."""
        assert data[pos] == 0x02, f"Ожидался INTEGER (0x02) на позиции {pos}"
        pos += 1
        length, pos = _parse_length(data, pos)
        val = int.from_bytes(data[pos:pos+length], "big")
        return val, pos + length

    def _parse_length(data, pos):
        b = data[pos]; pos += 1
        if b < 0x80:
            return b, pos
        n = b & 0x7F
        length = int.from_bytes(data[pos:pos+n], "big")
        return length, pos + n

    def _parse_seq(data, pos):
        assert data[pos] == 0x30
        pos += 1
        length, pos = _parse_length(data, pos)
        return pos, pos + length

    # Парсим внешний SEQUENCE
    pos = 0
    inner, end = _parse_seq(der, pos)
    pos = inner

    # Читаем первый INTEGER — это version и в PKCS#8 и в PKCS#1
    _version, pos = _parse_int(der, pos)

    # Определяем формат по следующему байту:
    #   PKCS#8: 0x30 = SEQUENCE AlgorithmIdentifier (версия 0, потом OID)
    #   PKCS#1: 0x02 = INTEGER n (само большое число ключа)
    if der[pos] == 0x30:
        # PKCS#8 — пропускаем AlgorithmIdentifier
        _, pos = _parse_seq(der, pos)
        # Следующий элемент — OCTET STRING с RSAPrivateKey внутри
        assert der[pos] == 0x04, f"Ожидался OCTET STRING (0x04), получен 0x{der[pos]:02x}"
        pos += 1
        oct_len, pos = _parse_length(der, pos)
        der = der[pos:pos + oct_len]
        # Парсим вложенный RSAPrivateKey заново
        inner2, _ = _parse_seq(der, 0)
        pos = inner2
        _version2, pos = _parse_int(der, pos)  # version RSAPrivateKey

    # PKCS#1 RSAPrivateKey: n, e, d, ...
    n, pos = _parse_int(der, pos)
    _e, pos = _parse_int(der, pos)
    d, pos = _parse_int(der, pos)

    # ── SHA-256 хеш сообщения ─────────────────────────────────
    digest = hashlib.sha256(message).digest()

    # DigestInfo ASN.1 префикс для SHA-256 (RFC 3447)
    sha256_prefix = bytes([
        0x30,0x31,0x30,0x0d,0x06,0x09,0x60,0x86,0x48,0x01,0x65,
        0x03,0x04,0x02,0x01,0x05,0x00,0x04,0x20
    ])
    T = sha256_prefix + digest

    # ── PKCS#1 v1.5 паддинг ──────────────────────────────────
    k = (n.bit_length() + 7) // 8   # длина ключа в байтах
    ps_len = k - len(T) - 3
    assert ps_len >= 8, "Ключ слишком короткий"
    em = b"\x00\x01" + (b"\xff" * ps_len) + b"\x00" + T

    # ── RSA: sig = em^d mod n ─────────────────────────────────
    m = int.from_bytes(em, "big")
    s = pow(m, d, n)
    return s.to_bytes(k, "big")


# ──────────────────────────────────────────────────────────────
#  📊  GOOGLE SHEETS — API v4
# ──────────────────────────────────────────────────────────────
_TOKEN_CACHE: dict = {"token": None, "expires": 0}  # кэш токена

def _make_ssl():
    """SSL без верификации — фикс для Windows UNEXPECTED_EOF."""
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode    = ssl.CERT_NONE
    # Windows fix: игнорируем ошибки верификации
    try:
        ctx.options |= ssl.OP_IGNORE_UNEXPECTED_EOF
    except AttributeError:
        pass
    return ctx

def _http_post(url: str, body: bytes, headers: dict) -> Optional[dict]:
    """POST запрос с retry логикой и SSL фиксом."""
    import urllib.request
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, data=body, headers=headers)
            with urllib.request.urlopen(req, timeout=20, context=_make_ssl()) as r:
                return json.loads(r.read().decode())
        except Exception as e:
            err = str(e)
            if attempt < 2 and ("EOF" in err or "SSL" in err or "timeout" in err.lower()):
                time.sleep(2 * (attempt + 1))  # ждём и повторяем
                continue
            return None
    return None

def _get_gsheet_token() -> Optional[str]:
    """
    Получает Bearer-токен для Google Sheets API через Service Account.
    Кэширует токен на 55 минут — не делает лишних запросов.
    """
    global _TOKEN_CACHE
    # Используем кэш если токен ещё действителен
    if _TOKEN_CACHE["token"] and time.time() < _TOKEN_CACHE["expires"]:
        return _TOKEN_CACHE["token"]
    if not os.path.exists(CREDS_FILE):
        return None
    try:
        import json as _j
        with open(CREDS_FILE, encoding="utf-8") as f:
            creds = _j.load(f)

        # JWT для Google OAuth2
        import base64, hashlib, struct

        def _b64url(data: bytes) -> str:
            return base64.urlsafe_b64encode(data).rstrip(b"=").decode()

        now   = int(time.time())
        claim = {
            "iss":   creds["client_email"],
            "scope": "https://www.googleapis.com/auth/spreadsheets",
            "aud":   "https://oauth2.googleapis.com/token",
            "iat":   now,
            "exp":   now + 3600,
        }
        header  = _b64url(json.dumps({"alg":"RS256","typ":"JWT"}).encode())
        payload = _b64url(json.dumps(claim).encode())
        msg     = f"{header}.{payload}".encode()

        # Подпись RSA-SHA256 — без внешних зависимостей
        sig = _rsa_sha256_sign(msg, creds["private_key"])
        jwt = f"{header}.{payload}.{_b64url(sig)}"

        # Получаем access_token
        import urllib.request, urllib.parse
        body = urllib.parse.urlencode({
            "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
            "assertion":  jwt,
        }).encode()
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode    = ssl.CERT_NONE
        req = urllib.request.Request(
            "https://oauth2.googleapis.com/token",
            data=body,
            headers={"Content-Type": "application/x-www-form-urlencoded"}
        )
        tok = _http_post(
            "https://oauth2.googleapis.com/token",
            body,
            {"Content-Type": "application/x-www-form-urlencoded"}
        )
        if tok and tok.get("access_token"):
            _TOKEN_CACHE["token"]   = tok["access_token"]
            _TOKEN_CACHE["expires"] = time.time() + 3300  # 55 минут
            return tok["access_token"]
        print(f"  [Sheets] Ошибка: Google вернул {tok}")
        return None
    except Exception as e:
        print(f"  [Sheets] Ошибка токена: {e}")
        return None

def _sheets_request(method: str, path: str, body=None,
                    _retries: int = 3) -> Optional[dict]:
    """Универсальный запрос к Google Sheets API v4 с retry."""
    import urllib.request, urllib.parse as _up

    path_enc = _up.quote(path, safe="/?=&:!.+")
    url  = f"https://sheets.googleapis.com/v4/spreadsheets/{SHEET_ID}{path_enc}"
    data = json.dumps(body).encode() if body else None

    last_err = None
    for attempt in range(_retries):
        # Берём токен каждый раз — он кэшируется внутри
        token = _get_gsheet_token()
        if not token:
            return None

        ctx = _make_ssl()
        req = urllib.request.Request(
            url, data=data, method=method,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type":  "application/json",
            }
        )
        try:
            with urllib.request.urlopen(req, timeout=25, context=ctx) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            last_err = f"HTTP {e.code}: {e.reason}"
            body = ""
            try: body = e.read().decode()[:200]
            except: pass
            if e.code == 429:  # Rate limit
                wait = 2 ** attempt
                print(f"  [Sheets] Rate limit — жду {wait}с...")
                time.sleep(wait)
                continue
            print(f"  [Sheets] Ошибка: {last_err} | {body}")
            return None
        except Exception as e:
            last_err = str(e)
            is_ssl = any(x in last_err for x in
                         ("EOF", "SSL", "TLS", "connection has been closed",
                          "UNEXPECTED_EOF", "timeout"))
            if is_ssl and attempt < _retries - 1:
                wait = 2 ** attempt
                time.sleep(wait)
                continue
            print(f"  [Sheets] Ошибка: {last_err}")
            return None
        finally:
            time.sleep(0.3)  # 300мс пауза между запросами (rate limit 100/100sec)

    print(f"  [Sheets] Не удалось после {_retries} попыток: {last_err}")
    return None

def _get_spreadsheet_info(force: bool = False) -> dict:
    """Возвращает info о таблице с кешем — делает GET только раз за сессию."""
    global _SHEET_INFO_CACHE
    if not force and _SHEET_INFO_CACHE:
        return _SHEET_INFO_CACHE
    info = _sheets_request("GET", "")
    if info:
        _SHEET_INFO_CACHE = info
    return info or {}


def _ensure_tab(tab_name: str):
    """Создаёт вкладку если её нет. Использует кеш — не делает лишние GET."""
    info = _get_spreadsheet_info()
    if not info:
        print(f"  [Sheets] Не удалось получить список вкладок — проверь credentials.json и SHEET_ID")
        return
    sheets = [s["properties"]["title"] for s in info.get("sheets", [])]
    if tab_name not in sheets:
        result = _sheets_request("POST", ":batchUpdate", {
            "requests": [{"addSheet": {"properties": {"title": tab_name}}}]
        })
        if result:
            _SHEET_INFO_CACHE.clear()  # сброс кеша после изменения
            print(f"  [Sheets] ✅ Создана вкладка '{tab_name}'")
        else:
            print(f"  [Sheets] ❌ Не удалось создать вкладку '{tab_name}'")

def _get_existing_ids(tab_name: str) -> set:
    """Возвращает set fixture_id уже записанных строк."""
    resp = _sheets_request(
        "GET", f"/values/{tab_name}!A:A"
    )
    if not resp:
        return set()
    rows = resp.get("values", [])
    ids  = set()
    for row in rows[1:]:   # пропускаем заголовок
        if row and str(row[0]).isdigit():
            ids.add(int(row[0]))
    return ids

def _append_rows(tab_name: str, rows: list):
    """Добавляет строки в конец таблицы."""
    if not rows:
        return
    _sheets_request("POST",
        f"/values/{tab_name}!A1:append?valueInputOption=USER_ENTERED&insertDataOption=INSERT_ROWS",
        {"values": rows}
    )

def _write_headers(tab_name: str):
    """Пишет заголовки если таблица пустая."""
    resp = _sheets_request("GET", f"/values/{tab_name}!A1:Z1")
    if resp and resp.get("values"):
        return   # заголовки уже есть
    # fixture_id в колонке A (скрытый ID для дедупликации)
    all_headers = ["fixture_id"] + HEADERS
    _sheets_request("PUT",
        f"/values/{tab_name}!A1?valueInputOption=USER_ENTERED",
        {"values": [all_headers]}
    )
    # Скрываем колонку fixture_id (A) — техническая
    _sheets_request("POST", ":batchUpdate", {"requests": [{
        "updateDimensionProperties": {
            "range": {"sheetId": 0, "dimension": "COLUMNS",
                      "startIndex": 0, "endIndex": 1},
            "properties": {"hiddenByUser": True},
            "fields": "hiddenByUser"
        }
    }]})
    print(f"  [Sheets] Заголовки записаны в '{tab_name}'")

def push_to_sheets(results: list):
    """
    Отправляет результаты матчей в Google Sheets.
    Каждый месяц — новый лист (Сигналы_Март_2026, Сигналы_Апрель_2026 и т.д.).
    Пропускает уже записанные матчи (дедупликация по fixture_id).
    """
    if not SHEET_ID:
        return
    if not os.path.exists(CREDS_FILE):
        print(f"  [Sheets] Нет файла {CREDS_FILE} — пропускаю")
        return

    # Группируем записи по месяцу
    by_month: dict = {}
    for r in results:
        date_str = r.get("date", "")
        tab = _monthly_tab(SHEET_TAB_SIGS, date_str)
        by_month.setdefault(tab, []).append(r)

    total_new = 0
    tabs_written = set()

    for tab_name, month_results in by_month.items():
        _ensure_tab(tab_name)
        _write_headers(tab_name)
        existing = _get_existing_ids(tab_name)

        new_rows = []
        for r in month_results:
            fid = r.get("fixture_id")
            if fid and int(fid) in existing:
                continue   # уже записано

            for sig in r.get("signals", []):
                won = sig.get("won")
                if won is None:
                    won_str = "⏳"
                elif won:
                    won_str = "✅ Да"
                else:
                    won_str = "❌ Нет"

                edge    = sig.get("edge", 0)
                prob    = sig.get("model_prob", 0)
                bk_odds = sig.get("bookmaker_odds", 0)
                ev      = round(prob * bk_odds - 1, 3) if bk_odds else ""
                win_pct = round(prob * 100) if prob else ""

                row = [
                    str(fid),
                    r.get("date", ""),
                    r.get("time",""),
                    r.get("match", ""),
                    r.get("league", ""),
                    r.get("result", ""),
                    r.get("xg_pred", ""),
                    sig.get("market", ""),
                    sig.get("selection", ""),
                    bk_odds,
                    f"{edge*100:.1f}%",
                    f"{win_pct}%",
                    ev,
                    sig.get("confidence", ""),
                    won_str,
                    r.get("logged_at", ""),
                ]
                new_rows.append(row)

        if new_rows:
            _append_rows(tab_name, new_rows)
            total_new += len(new_rows)
            tabs_written.add(tab_name)
            print(f"  [Sheets] ✅ {len(new_rows)} строк → '{tab_name}'")

    if total_new == 0:
        print(f"  [Sheets] Нет новых строк для добавления")
        print(f"  [Sheets] Возможно все {len(results)} матчей уже синхронизированы")

    # Статистика — тоже по текущему месяцу
    stats_tab = _monthly_tab(SHEET_TAB_STATS)
    _update_stats_tab(stats_tab)

def _update_stats_tab(tab_name: str = None):
    if tab_name is None:
        tab_name = _monthly_tab(SHEET_TAB_STATS)
    """Обновляет вкладку Статистика — сводка по рынкам и ROI."""
    results = _load(RESULTS_FILE)
    if not isinstance(results, list) or not results:
        return

    _ensure_tab(tab_name)

    total = won = 0
    roi   = 0.0
    mkt   = {}
    by_conf = {"🔥 ВЫСОКАЯ": [0,0,0.0], "✅ СРЕДНЯЯ": [0,0,0.0], "📌 НИЗКАЯ": [0,0,0.0]}

    for r in results:
        for sig in r.get("signals", []):
            o    = sig.get("won")
            if o is None: continue
            total += 1
            m     = sig.get("market", "?")
            conf  = sig.get("confidence", "")
            try:
                odds = float(sig.get("bookmaker_odds", 2.0) or 2.0)
            except (TypeError, ValueError):
                odds = 2.0
            mkt.setdefault(m, [0, 0, 0.0])

            if o:
                won += 1; roi += (odds-1)
                mkt[m][0] += 1; mkt[m][2] += (odds-1)
                for k in by_conf:
                    if k in conf:
                        by_conf[k][0] += 1; by_conf[k][2] += (odds-1); break
            else:
                roi -= 1; mkt[m][2] -= 1
                for k in by_conf:
                    if k in conf:
                        by_conf[k][2] -= 1; break

            mkt[m][1] += 1
            for k in by_conf:
                if k in conf:
                    by_conf[k][1] += 1; break

    now_str = datetime.datetime.now().strftime("%d.%m.%Y %H:%M")
    rows = [
        ["📊 СТАТИСТИКА БОТА", f"Обновлено: {now_str}"],
        [],
        ["Всего сигналов", total],
        ["Прошло", won],
        ["Точность %", f"{won/total*100:.1f}%" if total else "—"],
        ["ROI %", f"{roi/total*100:+.1f}%" if total else "—"],
        [],
        ["По уверенности", "Прошло/Всего", "ROI %"],
    ]
    for conf, (w, t, r) in by_conf.items():
        rows.append([conf, f"{w}/{t}", f"{r/t*100:.1f}%" if t else "—"])
    rows.append([])
    rows.append(["По рынкам", "Прошло/Всего", "ROI %"])
    for name, (w, t, r) in sorted(mkt.items(), key=lambda x: x[1][2], reverse=True):
        rows.append([name, f"{w}/{t}", f"{r/t*100:.1f}%" if t else "—"])

    _sheets_request("PUT",
        f"/values/{tab_name}!A1?valueInputOption=USER_ENTERED",
        {"values": rows}
    )
    print(f"  [Sheets] ✅ Статистика обновлена")

# ──────────────────────────────────────────────────────────────
#  📝  СОХРАНЕНИЕ ПРОГНОЗА
# ──────────────────────────────────────────────────────────────
def save_prediction(fixture_id, home, away, league, date, match_time, xg_home, xg_away, signals):
    preds = _load(PREDICTIONS_FILE)
    if not isinstance(preds, list):
        preds = []
    key   = str(fixture_id)
    # Дедупликация: по fixture_id И по home+away+date (разные API дают разные ID)
    def _norm(n):
        """Нормализует имя для сравнения: lowercase, убирает суффиксы, переводит."""
        n = n.lower().strip()
        for sfx in (" fc", "fc ", " afc", "afc ", " sc", " utd"," united"," city"," town"," hotspur"," wanderers"," athletic"):
            n = n.replace(sfx, "")
        # Кросс-языковая нормализация: EN → короткое RU
        _MAP = {
            "real madrid":"реал мадрид","barcelona":"барселона","atletico madrid":"атлетико",
            "manchester city":"ман сити","manchester united":"ман юнайтед",
            "liverpool":"ливерпуль","arsenal":"арсенал","chelsea":"челси",
            "tottenham":"тоттенхэм","wolverhampton":"вулверхэмптон","wolves":"вулверхэмптон",
            "bournemouth":"борнмут","brentford":"брентфорд","everton":"эвертон","burnley":"бёрнли",
            "leeds":"лидс","sunderland":"сандерленд","sheffield wednesday":"шеффилд уэнсдей",
            "ipswich":"ипсвич","hull":"халл","getafe":"хетафе","getafe cf":"хетафе",
            "inter milan":"интер","ac milan":"милан","juventus":"ювентус","napoli":"наполи",
            "atalanta":"аталанта","roma":"рома","lazio":"лацио","fiorentina":"фиорентина",
            "bologna":"болонья","bayer leverkusen":"байер","borussia dortmund":"боруссия д",
            "paris saint-germain":"псж","psg":"псж","marseille":"марсель","monaco":"монако",
            "benfica":"бенфика","sporting cp":"спортинг","porto":"порту","ajax":"аякс",
        }
        return _MAP.get(n, n)

    def _same_match(p):
        """Проверяет совпадение матчей учитывая разные имена на EN/RU."""
        # 1. По fixture_id
        if str(p.get("fixture_id")) == key:
            return True
        # 2. По дате
        if p.get("date", "") != date:
            return False
        # 3. Нормализованные имена
        ph = _norm(p.get("home", ""))
        pa = _norm(p.get("away", ""))
        ah = _norm(home)
        aa = _norm(away)
        h_ok = ph == ah or (len(ph) >= 4 and len(ah) >= 4 and ph[:4] == ah[:4])
        a_ok = pa == aa or (len(pa) >= 4 and len(aa) >= 4 and pa[:4] == aa[:4])
        return h_ok and a_ok

    # Если матч уже есть — обновляем xG, не дублируем
    for p in preds:
        if _same_match(p):
            if not p.get("result"):  # только незавершённые
                p["xg_home"]   = round(xg_home, 3)
                p["xg_away"]   = round(xg_away, 3)
                p["fixture_id"] = fixture_id
                if signals:
                    p["signals"] = signals
            _save(PREDICTIONS_FILE, preds)
            return
    preds = [p for p in preds if not _same_match(p)]
    preds.append({
        "fixture_id": fixture_id, "home": home, "away": away,
        "league": league, "date": date, "time": match_time,
        "xg_home": round(xg_home, 3), "xg_away": round(xg_away, 3),
        "signals": signals, "result": None, "learned": False,
        "saved_at": datetime.datetime.now().isoformat(timespec="seconds"),
    })
    _save(PREDICTIONS_FILE, preds)

# ──────────────────────────────────────────────────────────────
#  🌐  HTTP
# ──────────────────────────────────────────────────────────────
def _get(url, headers={}, timeout=12, retries=2):
    """HTTP GET с диагностикой ошибок и повторными попытками."""
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode    = ssl.CERT_NONE
    last_err = None
    for attempt in range(retries):
        try:
            import requests, urllib3
            urllib3.disable_warnings()
            r = requests.get(url, headers=headers, timeout=timeout, verify=False)
            if r.status_code == 200:
                return r.json()
            # Показываем код ошибки — важно для диагностики квоты
            try:
                err_body = r.json()
                last_err = f"HTTP {r.status_code}: {err_body.get('message', err_body.get('errors', r.text[:80]))}"
            except Exception:
                last_err = f"HTTP {r.status_code}: {r.text[:80]}"
            if r.status_code in (429, 403):
                # Квота/доступ — нет смысла повторять
                return {"_error": last_err, "_status": r.status_code, "response": []}
            return None
        except ImportError:
            break
        except Exception as e:
            last_err = str(e)[:80]
            if attempt < retries - 1:
                time.sleep(3)
    import urllib.request
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Bot/1.0", **headers})
            with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
                return json.load(r)
        except Exception as e:
            last_err = str(e)[:80]
            if attempt < retries - 1:
                time.sleep(3)
    return None

# ──────────────────────────────────────────────────────────────
#  📡  РЕЗУЛЬТАТЫ МАТЧЕЙ
# ──────────────────────────────────────────────────────────────
def fetch_result(fixture_id, af_key, fd_key):
    """
    Получает результат матча из API-Football с двойной верификацией.
    ВНИМАНИЕ: football-data.org НЕ используется как fallback — у них
    разные системы ID, что приводит к возврату счёта чужого матча.
    """
    def _af_fetch(fid):
        """Запрос к API-Football с retry."""
        for attempt in range(3):
            try:
                data = _get(
                    f"https://v3.football.api-sports.io/fixtures?id={fid}",
                    {"x-apisports-key": af_key}, timeout=15
                )
                if data and isinstance(data, dict):
                    return data.get("response", [])
            except Exception:
                pass
            if attempt < 2:
                time.sleep(3)
        return []

    # Запрос 1
    resp = _af_fetch(fixture_id)
    if not resp:
        return None

    fix = resp[0]
    st  = fix.get("fixture", {}).get("status", {}).get("short", "")

    # Матч ещё не завершён
    if st in ("NS","TBD","PST","SUSP","INT","BT"):
        return None

    # Матч отменён/не состоится
    if st in ("CANC","ABD","WO","AWD"):
        return None

    if st not in ("FT","AET","PEN"):
        return None   # неизвестный статус — не берём

    # Читаем голы
    g  = fix.get("goals", {})
    hg = g.get("home")
    ag = g.get("away")

    # Санитарная проверка — голы должны быть числами ≥ 0
    if hg is None or ag is None:
        print(f"  ⚠️ ID {fixture_id}: голы = None при статусе {st} — пропускаю")
        return None
    try:
        hg, ag = int(hg), int(ag)
    except (TypeError, ValueError):
        print(f"  ⚠️ ID {fixture_id}: некорректные голы {hg}:{ag} — пропускаю")
        return None

    # Проверка на разумность счёта (хоккей не берём сюда)
    if hg < 0 or ag < 0 or hg > 20 or ag > 20:
        print(f"  ⚠️ ID {fixture_id}: подозрительный счёт {hg}:{ag} — пропускаю")
        return None

    # ── Верификация через score.fulltime (90 минут) ─────────────
    # ВАЖНО: для AET/PEN матчей goals содержит голы включая ДОП,
    # но ставки 1X2/тотал считаются по результату 90 минут.
    # Поэтому ВСЕГДА берём score.fulltime как основной источник.
    score_ft = fix.get("score", {}).get("fullTime", fix.get("score", {}).get("fulltime", {}))
    hg_ft    = score_ft.get("home")
    ag_ft    = score_ft.get("away")
    if hg_ft is not None and ag_ft is not None:
        try:
            hg_ft, ag_ft = int(hg_ft), int(ag_ft)
            if (hg_ft, ag_ft) != (hg, ag):
                if st in ("AET", "PEN"):
                    # Для ДОП/пенальти — берём 90 мин счёт (fulltime)
                    print(f"  ℹ️ ID {fixture_id}: {st} матч, голы={hg}:{ag}, "
                          f"счёт 90мин={hg_ft}:{ag_ft} — использую 90мин для ставок")
                    hg, ag = hg_ft, ag_ft
                elif st == "FT":
                    # Расхождение на FT — тоже берём fulltime
                    print(f"  ⚠️ ID {fixture_id}: goals={hg}:{ag} ≠ fulltime={hg_ft}:{ag_ft}"
                          f" — использую fulltime")
                    hg, ag = hg_ft, ag_ft
        except (TypeError, ValueError):
            pass

    return {"home": hg, "away": ag, "status": st}

# ──────────────────────────────────────────────────────────────
#  🎯  ПРОВЕРКА СИГНАЛА
# ──────────────────────────────────────────────────────────────
def check_signal(sig, hg, ag, hg1=None, ag1=None):
    """Проверяет сигнал по финальному счёту.
    hg/ag    — голы за основное время (90 мин).
    hg1/ag1  — голы за 1-й тайм (если доступны).
    """
    market = sig.get("market", "")
    sel    = sig.get("selection", "")
    total  = hg + ag
    if market == "Исход":
        if "хозяев" in sel or "(1)" in sel:  return hg > ag
        if "гостей" in sel or "(2)" in sel:  return ag > hg
        if "Ничья"  in sel or "(X)" in sel:  return hg == ag
    elif market == "Тотал":
        try:
            line = float(sel.split()[-1])
            if "Больше" in sel: return total > line
            if "Меньше" in sel: return total < line
        except ValueError:
            pass
    elif market == "Обе забьют":
        btts = hg > 0 and ag > 0
        if "Да"  in sel: return btts
        if "Нет" in sel: return not btts
    elif market in ("Евр.Гандикап", "Гандикап", "Фора"):
        try:
            import re as _re
            nums = _re.findall(r"[+-]?\d+(?:\.\d+)?", sel)
            if not nums:
                return None
            hcap = float(nums[-1])
            if hcap == int(hcap):
                hcap = int(hcap)
                if "хозяев" in sel.lower() or "хозяева" in sel.lower():
                    adj = (hg + hcap) - ag
                    return True if adj > 0 else (None if adj == 0 else False)
                if "гост" in sel.lower():
                    adj = (ag + (-hcap)) - hg
                    return True if adj > 0 else (None if adj == 0 else False)
            else:
                if "хозяев" in sel.lower() or "хозяева" in sel.lower():
                    return (hg + hcap) > ag
                if "гост" in sel.lower():
                    return (ag - hcap) > hg
        except Exception:
            pass
    elif "двойной" in market.lower() or market.upper() in ("DC", "1X", "X2", "12"):
        sel_l = sel.lower()
        if "1x" in sel_l or "хозяева или ничья" in sel_l:
            return hg >= ag
        if "x2" in sel_l or "гости или ничья" in sel_l:
            return ag >= hg
        if "12" in sel_l or "не ничья" in sel_l:
            return hg != ag
    elif "ит хозяев" in market.lower() or "ит хозяева" in market.lower():
        try:
            import re as _re
            nums = _re.findall(r"[\d.]+", sel)
            if not nums: return None
            line = float(nums[-1])
            if "больше" in sel.lower(): return hg > line
            if "меньше" in sel.lower(): return hg < line
        except Exception:
            pass
    elif "ит гостей" in market.lower() or "ит гости" in market.lower():
        try:
            import re as _re
            nums = _re.findall(r"[\d.]+", sel)
            if not nums: return None
            line = float(nums[-1])
            if "больше" in sel.lower(): return ag > line
            if "меньше" in sel.lower(): return ag < line
        except Exception:
            pass
    # ── Инд. тотал хозяев (ИТ Хозяева / ИТ хозяев / ИТ Х) ─
    elif market in ("ИТ Хозяева", "ИТ хозяев", "ИТ Х"):
        try:
            import re as _re
            nums = _re.findall(r"[\d.]+", sel)
            if not nums: return None
            line = float(nums[-1])
            if "больше" in sel.lower(): return hg > line
            if "меньше" in sel.lower(): return hg < line
        except Exception:
            pass
    # ── Инд. тотал гостей (ИТ Гости / ИТ Г) ─────────────
    elif market in ("ИТ Гости", "ИТ гостей", "ИТ Г"):
        try:
            import re as _re
            nums = _re.findall(r"[\d.]+", sel)
            if not nums: return None
            line = float(nums[-1])
            if "больше" in sel.lower(): return ag > line
            if "меньше" in sel.lower(): return ag < line
        except Exception:
            pass
    # ── Тотал 1-го тайма ──────────────────────────────────
    elif market in ("Тотал 1Т", "Тотал 1T"):
        if hg1 is None or ag1 is None:
            return None  # нет данных 1Т
        total_1t = hg1 + ag1
        try:
            import re as _re
            nums = _re.findall(r"[\d.]+", sel)
            if not nums: return None
            line = float(nums[-1])
            if "больше" in sel.lower(): return total_1t > line
            if "меньше" in sel.lower(): return total_1t < line
        except Exception:
            pass
    # ── Исход 1-го тайма ─────────────────────────────────
    elif market in ("Исход 1Т", "Исход 1T"):
        if hg1 is None or ag1 is None:
            return None
        if "хозяев" in sel.lower(): return hg1 > ag1
        if "гостей" in sel.lower(): return ag1 > hg1
        if "ничья"  in sel.lower(): return hg1 == ag1
    # ── Двойной шанс ────────────────────────────────────────
    elif market in ("Двойной шанс", "DC"):
        if "1X" in sel:   return hg >= ag
        if "X2" in sel:   return ag >= hg
        if "12" in sel:   return hg != ag
    # ── Забьёт в 1 тайме ──────────────────────────────────
    elif "забьёт в 1" in market.lower() or "забьет в 1" in market.lower():
        if hg1 is None or ag1 is None:
            return None
        sel_l = sel.lower()
        if "хозяев" in sel_l or "хозяева" in sel_l:
            if "да"  in sel_l: return hg1 > 0
            if "нет" in sel_l: return hg1 == 0
        if "гост" in sel_l:
            if "да"  in sel_l: return ag1 > 0
            if "нет" in sel_l: return ag1 == 0
    # ── Оба тайма (победа в обоих таймах) ─────────────────
    elif "оба тайма" in market.lower():
        if hg1 is None or ag1 is None:
            return None
        # Считаем 2-й тайм как: FT голы минус 1Т голы
        hg2 = max(0, hg - hg1)
        ag2 = max(0, ag - ag1)
        sel_l = sel.lower()
        if "хозяев" in sel_l or "хозяева" in sel_l:
            return hg1 > ag1 and hg2 > ag2   # победа в каждом тайме
        if "гост" in sel_l:
            return ag1 > hg1 and ag2 > hg2
    # ── DNB (Draw No Bet) ──────────────────────────────────
    elif market.upper() in ("DNB", "ФОРА 0") or "draw no bet" in market.lower() or "фора 0" in market.lower():
        if "хозяев" in sel.lower() or "хозяева" in sel.lower():
            if hg == ag: return None   # возврат ставки
            return hg > ag
        if "гост" in sel.lower():
            if hg == ag: return None
            return ag > hg
    # ── Забьёт в 1 тайме ──────────────────────────────────
    elif "забьёт в 1" in market.lower() or "забьет в 1" in market.lower():
        return None   # нет данных 1Т
    # ── Оба тайма (оба тайма выиграет и т.п.) ─────────────
    elif "оба тайма" in market.lower():
        return None   # нет данных 1Т
    # ── Лайв рынки ────────────────────────────────────────
    elif "(лайв)" in market.lower():
        # Результат лайв — используем финальный счёт как лучшее приближение
        if "исход" in market.lower():
            if "хозяев" in sel.lower(): return hg > ag
            if "гостей" in sel.lower(): return ag > hg
            if "ничья" in sel.lower():  return hg == ag
        elif "тотал" in market.lower():
            try:
                import re as _re
                nums = _re.findall(r"[\d.]+", sel)
                if not nums: return None
                line = float(nums[-1])
                if "больше" in sel.lower(): return total > line
                if "меньше" in sel.lower(): return total < line
            except Exception:
                pass
    return None

# ──────────────────────────────────────────────────────────────
#  🧠  ОБНОВЛЕНИЕ СТАТИСТИКИ КОМАНДЫ
# ──────────────────────────────────────────────────────────────
def update_team(team, is_home, scored, conceded):
    stats = _load(TEAM_STATS_FILE)
    if not isinstance(stats, dict):
        stats = {}
    key = team.lower().strip()
    for sfx in [" fc"," afc"," sc"," bc"," cf"]:
        key = key.replace(sfx, "").strip()
    if key not in stats:
        stats[key] = {"h_gs":1.55,"h_gc":1.25,"a_gs":1.25,"a_gc":1.55,"matches":0,"updated":""}
    e  = stats[key]
    lr = max(0.07, LEARN_RATE / (1 + e["matches"] * 0.03))
    if is_home:
        e["h_gs"] = round(e["h_gs"]*(1-lr) + scored*lr,   3)
        e["h_gc"] = round(e["h_gc"]*(1-lr) + conceded*lr, 3)
    else:
        e["a_gs"] = round(e["a_gs"]*(1-lr) + scored*lr,   3)
        e["a_gc"] = round(e["a_gc"]*(1-lr) + conceded*lr, 3)
    e["matches"] += 1
    e["updated"]  = datetime.date.today().isoformat()
    stats[key] = e
    _save(TEAM_STATS_FILE, stats)
    return e

# ──────────────────────────────────────────────────────────────
#  🔄  ГЛАВНАЯ: проверить завершённые матчи
# ──────────────────────────────────────────────────────────────

# ── Обновление Elo-рейтингов ──────────────────────────────
import base64 as _b64

def _elo_update_from_results():
    """Пересчитывает Elo по всем результатам в results.json."""
    ELO_FILE = "elo_ratings.json"
    ELO_BASE = 1500
    K = 32
    elo = {}
    try:
        if os.path.exists(ELO_FILE):
            with open(ELO_FILE, encoding="utf-8") as f:
                elo = json.load(f)
    except Exception:
        pass

    if not os.path.exists("results.json"):
        return
    try:
        with open("results.json", encoding="utf-8") as f:
            results = json.load(f)
    except Exception:
        return

    for r in results:
        res = r.get("result","")
        if ":" not in res:
            continue
        try:
            import re as _re
            parts = _re.match(r"(\d+):(\d+)", res.strip())
            if not parts:
                continue
            hg, ag = int(parts.group(1)), int(parts.group(2))
        except Exception:
            continue
        home = r.get("home","").lower()
        away = r.get("away","").lower()
        rh = elo.get(home, ELO_BASE) + 100
        ra = elo.get(away, ELO_BASE)
        exp_h = 1.0 / (1.0 + 10**((ra-rh)/400.0))
        sh = 1.0 if hg>ag else (0.5 if hg==ag else 0.0)
        sa = 1.0 - sh
        elo[home] = round(elo.get(home, ELO_BASE) + K*(sh-exp_h), 1)
        elo[away] = round(elo.get(away, ELO_BASE) + K*(sa-(1-exp_h)), 1)

    with open(ELO_FILE, "w", encoding="utf-8") as f:
        json.dump(elo, f, ensure_ascii=False, indent=2)
    print(f"  📊 Elo обновлён для {len(elo)} команд → {ELO_FILE}")

def verify_results(af_key: str):
    """
    Перепроверяет ВСЕ сохранённые результаты в results.json через API.
    Исправляет неверные счёты и обновляет Google Sheets.
    Запуск: python learning.py verify
    """
    if not os.path.exists(RESULTS_FILE):
        print("  ℹ️  results.json не найден.")
        return

    results = _load(RESULTS_FILE)
    if not isinstance(results, list):
        print("  ℹ️  results.json пустой.")
        return

    print(f"\n🔍 Верифицирую {len(results)} результатов...")
    fixed = 0

    for r in results:
        fid      = r.get("fixture_id")
        old_res  = r.get("result","")
        match_lbl= r.get("match","")
        if not fid or not old_res or ":" not in old_res:
            continue

        # Пропускаем матчи старше 30 дней (API может не иметь данных)
        try:
            match_date = datetime.date.fromisoformat(r.get("date","")[:10])
            if (datetime.date.today() - match_date).days > 30:
                continue
        except Exception:
            continue

        real = fetch_result(fid, af_key, "")
        if not real:
            print(f"  ❓ {match_lbl} — API не вернул результат")
            time.sleep(2)
            continue

        real_str = f"{real['home']}:{real['away']}"
        time.sleep(2)

        if real_str != old_res:
            print(f"  🔧 ИСПРАВЛЕНИЕ: {match_lbl}")
            print(f"     Было:  {old_res}")
            print(f"     Стало: {real_str}")
            r["result"] = real_str

            # Пересчитываем won/lost для сигналов
            hg, ag = real["home"], real["away"]
            for sig in r.get("signals", []):
                sig["won"] = check_signal(sig, hg, ag)

            fixed += 1
        else:
            print(f"  ✅ {match_lbl}  {old_res}  — верно")

    if fixed:
        _save(RESULTS_FILE, results)
        print(f"\n  💾 Исправлено {fixed} результатов → results.json")

        # Синхронизируем исправления в Google Sheets
        print(f"  📊 Обновляю Google Sheets...")
        push_to_sheets(results)
        print(f"  ✅ Sheets обновлён")
    else:
        print(f"\n  ✅ Все результаты верны — исправлений не нужно")


def _norm_league(name: str) -> str:
    """
    Нормализует название лиги для единообразного хранения в results.json.
    Убирает дубликаты типа "Ла Лига" vs "Ла Лига (Испания)" → единое имя.
    """
    if not name:
        return ""
    name = " ".join(name.split())
    # Полный маппинг — все варианты написания → каноническое имя
    _MAP = {
        # Английский → рус
        "Premier League": "Премьер-лига",
        "La Liga": "Ла Лига",
        "Bundesliga": "Бундеслига",
        "Serie A": "Серия А",
        "Ligue 1": "Лига 1",
        "Eredivisie": "Эредивизи",
        "Primeira Liga": "Примейра-лига",
        "Championship": "Чемпионшип",
        "Champions League": "Лига Чемпионов",
        "UEFA Champions League": "Лига Чемпионов",
        "Europa League": "Лига Европы",
        "Conference League": "Лига Конференций",
        # Сокращения
        "РПЛ": "Лига ПАРИ (РПЛ)",
        "ФНЛ": "Первая лига России (ФНЛ)",
        "АПЛ": "Премьер-лига",
        "EPL": "Премьер-лига",
        "UCL": "Лига Чемпионов",
        "UEL": "Лига Европы",
        "UECL": "Лига Конференций",
        # Варианты с указанием страны → без страны
        "Ла Лига (Испания)": "Ла Лига",
        "Серия А (Италия)": "Серия А",
        "Бундеслига (Германия)": "Бундеслига",
        "Лига 1 (Франция)": "Лига 1",
        "Эредивизи (Нидерланды)": "Эредивизи",
        "Примейра-лига (Португалия)": "Примейра-лига",
        "Чемпионшип (Англия Д2)": "Чемпионшип",
        "Премьер-лига (Англия)": "Премьер-лига",
    }
    return _MAP.get(name, name)


def _ru_to_en_name(ru_name: str) -> str:
    """Конвертирует RU имя команды в EN.
    Сначала пробует TEAM_NAMES_RU из football_bot_v3,
    потом встроенный словарь топ-команд.
    """
    _BUILTIN = {
        # ЛЧ / ЛЕ
        "пСЖ": "Paris Saint-Germain", "пари сен-жермен": "Paris Saint-Germain",
        "псж": "Paris Saint-Germain",
        "реал мадрид": "Real Madrid", "реал": "Real Madrid",
        "манчестер сити": "Manchester City", "ман сити": "Manchester City",
        "челси": "Chelsea",
        "барселона": "Barcelona",
        "бавария": "Bayern Munich", "байер": "Bayer Leverkusen",
        "ливерпуль": "Liverpool",
        "арсенал": "Arsenal",
        "атлетико": "Atletico Madrid", "атлетико мадрид": "Atletico Madrid",
        "интер": "Inter Milan", "интер милан": "Inter Milan",
        "ювентус": "Juventus",
        "боруссия д": "Borussia Dortmund", "боруссия дортмунд": "Borussia Dortmund",
        "боруссия м": "Borussia Monchengladbach",
        "милан": "AC Milan", "ак милан": "AC Milan",
        "спортинг": "Sporting CP", "спортинг лисабон": "Sporting CP",
        "бенфика": "Benfica",
        "порту": "Porto",
        "аякс": "Ajax",
        "псв": "PSV", "псв эйндховен": "PSV Eindhoven",
        "фенербахче": "Fenerbahce",
        "галатасарай": "Galatasaray",
        "рбулль": "RB Leipzig", "рб лейпциг": "RB Leipzig",
        "селтик": "Celtic",
        "рейнджерс": "Rangers",
        "фкбодо": "Bodo/Glimt", "бодо глимт": "Bodo/Glimt", "fk bodø": "Bodo/Glimt",
        # Чемпионшип
        "мидлсбро": "Middlesbrough",
        "вест бромвич": "West Bromwich Albion", "вест бром": "West Brom",
        "норвич": "Norwich City",
        "шеффилд юнайтед": "Sheffield United", "шефф юн": "Sheffield United",
        "оксфорд": "Oxford United",
        "блэкберн": "Blackburn Rovers",
        "бирмингем": "Birmingham City",
        "кпр": "QPR", "куинз парк рейнджерс": "QPR",
        "ковентри": "Coventry City",
        "престон": "Preston North End",
        "чарльтон": "Charlton Athletic",
        "саутгемптон": "Southampton",
    }
    ru_low = ru_name.lower().strip()
    # Встроенный словарь
    en = _BUILTIN.get(ru_low)
    if en:
        return en.lower()
    # Пробуем через football_bot_v3
    try:
        from football_bot_v3 import TEAM_NAMES_RU as _TNRU
        _rev = {v.lower(): k.lower() for k, v in _TNRU.items()}
        return _rev.get(ru_low, ru_low)
    except Exception:
        return ru_low


def _find_in_batch(batch: dict, fixture_id, home_name: str, away_name: str) -> dict:
    """
    Ищет результат в батч-кэше.
    Сначала по fixture_id, потом по имени команд (RU и EN).
    """
    # 1. По fixture_id
    fid = int(fixture_id) if fixture_id else 0
    if fid and fid in batch:
        return batch[fid]

    # 2. По именам команд
    by_name = batch.get("_by_name", {})
    if not by_name:
        return None

    def _norm(n):
        n = n.lower().strip()
        for sfx in (" fc", " afc", " sc", " cf", " ac", " united", " city", " town"):
            if n.endswith(sfx): n = n[:-len(sfx)].strip()
        return n

    h_en = _ru_to_en_name(home_name)
    a_en = _ru_to_en_name(away_name)

    h_vars = {home_name.lower(), _norm(home_name), h_en, _norm(h_en)}
    a_vars = {away_name.lower(), _norm(away_name), a_en, _norm(a_en)}

    # Точное совпадение
    for hv in h_vars:
        for av in a_vars:
            if f"{hv}|{av}" in by_name:
                return by_name[f"{hv}|{av}"]

    # Fuzzy: первые 4 символа или пересечение слов
    _STOP = {"fc","sc","ac","cf","afc","the","de","fk","1."}
    for hv in h_vars:
        for av in a_vars:
            hw = set(hv.split()) - _STOP
            aw = set(av.split()) - _STOP
            if not hw or not aw:
                continue
            for k, v in by_name.items():
                kh, ka = k.split("|", 1)
                kh_w = set(kh.split()) - _STOP
                ka_w = set(ka.split()) - _STOP
                if len(hw & kh_w) >= 1 and len(aw & ka_w) >= 1:
                    return v

    # Substring: первые 5 символов
    for hv in h_vars:
        for av in a_vars:
            if len(hv) < 4 or len(av) < 4:
                continue
            for k, v in by_name.items():
                kh, ka = k.split("|", 1)
                if hv[:5] in kh and av[:5] in ka:
                    return v

    # Последний шанс: 4 символа (для очень коротких имён типа "Bodo")
    for hv in h_vars:
        for av in a_vars:
            if len(hv) < 4 or len(av) < 4:
                continue
            for k, v in by_name.items():
                kh, ka = k.split("|", 1)
                # Слабый матч: хотя бы 4 символа в начале совпадают
                if kh[:4] == hv[:4] and ka[:4] == av[:4]:
                    return v

    return None


def _sofa_search_result(home_ru: str, away_ru: str, date_str: str) -> dict:
    """
    Ищет результат матча через SofaScore API по именам команд.
    Используется как последний fallback когда батч-кэш не нашёл матч.
    """
    try:
        _hdrs = {
            "User-Agent": "SofaScore/70 CFNetwork/1492.0.1 Darwin/23.3.0",
            "Referer": "https://www.sofascore.com/",
        }
        # Берём данные за дату из SofaScore
        url = f"https://api.sofascore.com/api/v1/sport/football/scheduled-events/{date_str}"
        data = _get(url, _hdrs, timeout=12)
        if not data or not isinstance(data, dict):
            return None

        h_en = _ru_to_en_name(home_ru).lower()
        a_en = _ru_to_en_name(away_ru).lower()
        h_ru = home_ru.lower()
        a_ru = away_ru.lower()

        def _norm4(s): return s.lower().replace(" fc","").replace(" cf","").strip()

        _SOFA_DONE = {"finished"}
        for ev in (data.get("events") or []):
            if ev.get("status", {}).get("type", "").lower() not in _SOFA_DONE:
                continue
            hn = ev.get("homeTeam", {}).get("name", "").lower()
            an = ev.get("awayTeam", {}).get("name", "").lower()
            hn2 = ev.get("homeTeam", {}).get("shortName", hn).lower()
            an2 = ev.get("awayTeam", {}).get("shortName", an).lower()

            # Сравниваем: EN или RU имя с именем из SofaScore
            h_match = (h_en[:5] in hn or h_en[:5] in hn2 or
                       h_ru[:5] in hn or h_ru[:5] in hn2 or
                       hn[:5] in h_en or hn2[:5] in h_en)
            a_match = (a_en[:5] in an or a_en[:5] in an2 or
                       a_ru[:5] in an or a_ru[:5] in an2 or
                       an[:5] in a_en or an2[:5] in a_en)

            if h_match and a_match:
                hg = ev.get("homeScore", {}).get("current")
                ag = ev.get("awayScore", {}).get("current")
                if hg is None or ag is None:
                    continue
                # Счёт 90 мин при ОТ
                desc = ev.get("status", {}).get("description", "").lower()
                if "extra time" in desc or "penalties" in desc:
                    nt = ev.get("homeScore", {}).get("normaltime")
                    nat = ev.get("awayScore", {}).get("normaltime")
                    if nt is not None and nat is not None:
                        hg, ag = nt, nat
                return {"home": int(hg), "away": int(ag), "status": "FT"}
    except Exception:
        pass
    return None


def run_update(af_key, fd_key):
    preds = _load(PREDICTIONS_FILE)
    if not isinstance(preds, list) or not preds:
        print("📭 Прогнозов нет — сначала запусти scan.")
        return

    # Дедупликация
    _seen_matches = set()
    deduped = []
    for p in preds:
        _key = (p.get("home","")[:6].lower(), p.get("away","")[:6].lower(), p.get("date",""))
        if _key not in _seen_matches:
            _seen_matches.add(_key)
            deduped.append(p)
    if len(deduped) != len(preds):
        preds = deduped
        _save(PREDICTIONS_FILE, preds)

    pending = [p for p in preds if not p.get("learned")]
    print(f"\n🔄 Непроверенных прогнозов: {len(pending)}\n")

    # ── Определяем даты для батч-загрузки ────────────────────────
    today_str = datetime.date.today().isoformat()
    dates_needed = sorted(set(
        p["date"][:10] for p in pending
        if p.get("date","")[:10] < today_str   # только завершённые дни
    ))
    # FIX: также включаем вчера полностью даже если матч поздно начался
    yesterday_str = (datetime.date.today() - datetime.timedelta(days=1)).isoformat()

    # ── Батч-загрузка результатов (1 запрос на дату, не 1/матч) ──
    if dates_needed:
        print(f"  📥 Загружаю результаты за {len(dates_needed)} дат(ы): {dates_needed}")
        for d in dates_needed:
            _load_batch_results(d, af_key, fd_key)
            time.sleep(1)   # уважаем rate limit
    print()

    won = lost = updated = 0
    new_results = []

    for pred in preds:
        if pred.get("learned"):
            continue

        pred_date = pred.get("date","")[:10]
        pred_time = pred.get("time") or "23:59"

        # ── FIX: пропуск time-check если дата строго раньше сегодня ──
        # Матч 2026-03-08 → сегодня 2026-03-09 → точно завершён
        if pred_date >= today_str:
            print(f"  ⏳ {pred['home']} vs {pred['away']} ({pred_date}) — ещё сегодня, пропускаем")
            continue

        # Для ВЧЕРАШНИХ матчей — проверяем по времени (могли быть поздно)
        if pred_date == yesterday_str:
            try:
                mt = datetime.datetime.fromisoformat(pred_date + "T" + pred_time)
                # Если матч начался меньше 3 часов назад — ещё не завершён
                if datetime.datetime.now() < mt + datetime.timedelta(hours=3):
                    print(f"  ⏳ {pred['home']} vs {pred['away']} ({pred_date} {pred_time}) — ещё не завершён")
                    continue
            except Exception:
                pass   # не можем распарсить время — пробуем получить результат

        # ── Ищем результат в батч-кэше (0 доп запросов) ─────────
        batch = _RESULTS_BATCH_CACHE.get(pred_date, {})
        result_data = None

        if batch:
            result_data = _find_in_batch(batch, pred.get("fixture_id", 0),
                                          pred.get("home",""), pred.get("away",""))

        # Fallback: индивидуальный запрос (если дата не была в батче)
        if not result_data and pred.get("fixture_id"):
            try:
                result_data = fetch_result(pred["fixture_id"], af_key, fd_key)
            except Exception as e:
                print(f"  ⚠️ {pred['home']} vs {pred['away']} — ошибка: {str(e)[:60]}")
                continue

        # ── Дополнительный fallback: SofaScore поиск по имени ────
        if not result_data:
            result_data = _sofa_search_result(pred.get("home",""), pred.get("away",""), pred_date)

        if not result_data:
            print(f"  ❓ {pred['home']} vs {pred['away']} ({pred_date}) — результат не найден")
            continue

        hg, ag = result_data["home"], result_data["away"]
        st_label = result_data.get("status", "FT")
        # Финальный счёт (если был ОТ/пен — показываем оба)
        hg_full = result_data.get("home_full")
        ag_full = result_data.get("away_full")
        if hg_full is not None and ag_full is not None:
            # Ставки закрывались по 90 мин = hg:ag, финал = hg_full:ag_full
            score_label = f"{hg_full}:{ag_full} (90′ {hg}:{ag})"
        else:
            score_label = f"{hg}:{ag}"
            if st_label == "AET": score_label += " (ДОП)"
            elif st_label == "PEN": score_label += " (пен.)"

        pred["result"] = score_label
        hg1 = result_data.get("home_ht")
        ag1 = result_data.get("away_ht")
        for sig in pred.get("signals", []):
            o = check_signal(sig, hg, ag, hg1, ag1)
            sig["won"] = o
            if o is True:  won  += 1
            if o is False: lost += 1

        update_team(pred["home"], True,  hg, ag)
        update_team(pred["away"], False, ag, hg)

        # FIX: восстанавливаем kelly_stake если отсутствует (старые predictions)
        _sigs_enriched = []
        for _s in pred.get("signals", []):
            _s2 = dict(_s)
            _ks = float(_s2.get("kelly_stake") or 0)
            if _ks == 0:
                # Пересчитываем Kelly на месте
                _prob = float(_s2.get("model_prob") or 0.55)
                _odds = float(_s2.get("bookmaker_odds") or 2.0)
                if _odds > 1.01 and _prob > 0:
                    _b = _odds - 1
                    _k = max(0.0, min((_b * _prob - (1 - _prob)) / _b, 0.50))
                    _ks = round(_k * 0.25 * 1000 * 0.05, 2)  # KELLY_FRAC=0.25, BANKROLL=1000, cap=5%
                    _s2["kelly_stake"] = _ks
            _sigs_enriched.append(_s2)

        log_entry = {
            "fixture_id": pred.get("fixture_id", 0),
            "match":      f"{pred['home']} vs {pred['away']}",
            "league":     _norm_league(pred.get("league","")),  # нормализация имени лиги
            "date":       pred["date"],
            "time":       pred.get("time",""),
            "result":     score_label,
            "xg_pred":    f"{pred.get('xg_home',0):.2f}:{pred.get('xg_away',0):.2f}",
            "signals":    _sigs_enriched,
            "logged_at":  datetime.datetime.now().isoformat(timespec="seconds"),
        }
        log = _load(RESULTS_FILE)
        if not isinstance(log, list): log = []
        log.append(log_entry)
        _save(RESULTS_FILE, log)
        new_results.append(log_entry)

        pred["learned"] = True
        sigs_str = " ".join(
            "✅" if s.get("won") else ("❌" if s.get("won") is False else "❓")
            for s in pred.get("signals",[])
        )
        print(f"  ⚽ {pred['home']} vs {pred['away']}  ({pred_date})")
        print(f"     Счёт: {hg}:{ag}  |  xG: {pred.get('xg_home',0):.2f}:{pred.get('xg_away',0):.2f}")
        print(f"     Сигналы: {sigs_str or '—'}")
        print()
        updated += 1

    _save(PREDICTIONS_FILE, preds)
    _elo_update_from_results()

    print("-"*50)
    print(f"  Обработано: {updated} матчей")
    if won + lost:
        print(f"  Сигналы: {won}W/{lost}L ({won/(won+lost)*100:.1f}%)")

    if new_results and SHEET_ID:
        print(f"\n📊 Синхронизирую с Google Sheets...")
        push_to_sheets(new_results)
    elif not SHEET_ID:
        print(f"\n  ℹ️  Google Sheets не настроен (SHEET_ID пустой)")
    print()

# ──────────────────────────────────────────────────────────────
#  📊  СТАТИСТИКА
# ──────────────────────────────────────────────────────────────
def run_stats():
    results    = _load(RESULTS_FILE)
    team_stats = _load(TEAM_STATS_FILE)
    if not isinstance(results, list) or not results:
        print("\n📭 Нет данных. Запусти update после нескольких матчей.\n")
        return
    total = won = 0
    roi   = 0.0
    mkt   = {}
    for r in results:
        for sig in r.get("signals",[]):
            o = sig.get("won")
            if o is None: continue
            total += 1
            m     = sig.get("market","?")
            try:
                odds = float(sig.get("bookmaker_odds", 2.0) or 2.0)
            except (TypeError, ValueError):
                odds = 2.0
            mkt.setdefault(m, {"won":0,"total":0,"roi":0.0})
            mkt[m]["total"] += 1
            if o:
                won += 1; roi += (odds-1)
                mkt[m]["won"] += 1; mkt[m]["roi"] += (odds-1)
            else:
                roi -= 1; mkt[m]["roi"] -= 1
    sep = "="*55
    print(f"\n{sep}")
    print("  📊 СТАТИСТИКА САМООБУЧЕНИЯ")
    print(sep)
    print(f"  Матчей в базе:    {len(results)}")
    print(f"  Сигналов всего:   {total}")
    if total:
        print(f"  Прошло:           {won} ({won/total*100:.1f}%)")
        print(f"  ROI:              {roi/total*100:+.1f}% на сигнал")
        print(f"\n  {'─'*50}")
        for name, st in sorted(mkt.items(), key=lambda x: x[1]["roi"], reverse=True):
            a = st["won"]/st["total"]*100 if st["total"] else 0
            r = st["roi"]/st["total"]*100 if st["total"] else 0
            print(f"  {'🟢' if r>0 else '🔴'} {name:<22} {st['won']}/{st['total']} ({a:.0f}%)  ROI {r:+.1f}%")
    if isinstance(team_stats, dict) and team_stats:
        print(f"\n  🧠 ОБУЧЕННЫХ КОМАНД: {len(team_stats)}")
        for name, st in sorted(team_stats.items(), key=lambda x: x[1].get("matches",0), reverse=True)[:5]:
            print(f"    {name.title():<24} {st['matches']} матч  h:{st['h_gs']:.2f}/{st['h_gc']:.2f}  a:{st['a_gs']:.2f}/{st['a_gc']:.2f}")
    print(f"{sep}\n")

# ──────────────────────────────────────────────────────────────
#  🏁  ТОЧКА ВХОДА
# ──────────────────────────────────────────────────────────────
def run_retro():
    """
    Ретроспективно пересчитывает won=None сигналы в уже learned матчах.
    Запускать: python learning.py retro
    """
    preds = _load(PREDICTIONS_FILE)
    results_log = _load(RESULTS_FILE)
    if not isinstance(preds, list):
        print("📭 Нет данных predictions.json"); return

    fixed = 0
    for pred in preds:
        if not pred.get("learned"): continue
        result = pred.get("result", "")
        if not result or ":" not in result: continue
        # Берём счёт 90 мин: "2:1 (ДОП)" → "2:1", "3:2 (90′ 1:1)" → "1:1"
        r_for_check = result
        if "(90′" in result:
            # Формат "X:Y (90′ A:B)" — для ставок используем A:B
            try:
                r_for_check = result.split("90′")[-1].strip().rstrip(")").strip()
            except Exception:
                pass
        try:
            hg, ag = int(r_for_check.split(":")[0].strip()), int(r_for_check.split(":")[1].strip().split()[0])
        except Exception:
            continue

        changed = False
        for sig in pred.get("signals", []):
            if sig.get("won") is not None: continue
            new_w = check_signal(sig, hg, ag)
            if new_w is not None:
                sig["won"] = new_w
                fixed += 1
                changed = True

        if changed:
            # Обновляем results_log
            if isinstance(results_log, list):
                for entry in results_log:
                    if (entry.get("match","") == f"{pred['home']} vs {pred['away']}" and
                        entry.get("date","")[:10] == pred.get("date","")[:10]):
                        for es in entry.get("signals",[]):
                            for ps in pred.get("signals",[]):
                                if (es.get("market") == ps.get("market") and
                                    es.get("selection") == ps.get("selection")):
                                    es["won"] = ps.get("won")
                        break

    _save(PREDICTIONS_FILE, preds)
    if isinstance(results_log, list):
        _save(RESULTS_FILE, results_log)
    print(f"\n✅ Ретро-пересчёт: исправлено {fixed} сигналов")
    if fixed:
        run_stats()


if __name__ == "__main__":
    try:
        sys.path.insert(0, ".")
        from football_bot_v3 import API_FOOTBALL_KEY, FOOTBALL_DATA_KEY
    except ImportError:
        API_FOOTBALL_KEY  = input("API-Football ключ: ").strip()
        FOOTBALL_DATA_KEY = input("Football-Data.org ключ: ").strip()

    # ── Диагностика ключей ──────────────────────────────────────
    _af_ok = bool(API_FOOTBALL_KEY and len(API_FOOTBALL_KEY) > 10)
    _fd_ok = bool(FOOTBALL_DATA_KEY and len(FOOTBALL_DATA_KEY) > 10)
    if not _af_ok:
        print("  ⚠️  API_FOOTBALL_KEY не задан — используем FD + TheSportsDB")
    if not _fd_ok:
        print("  ℹ️  FOOTBALL_DATA_KEY не задан — FD работает в публичном режиме (топ-8 лиг)")
    print(f"  📡 Источники: {'AF ✅' if _af_ok else 'AF ❌'} | FD {'✅' if _fd_ok else '(публично)'} | TheSportsDB ✅ | SofaScore ✅")

    # ── Проверка AF квоты перед началом ────────────────────────
    if _af_ok:
        _quota_check = _get(
            "https://v3.football.api-sports.io/status",
            {"x-apisports-key": API_FOOTBALL_KEY}, timeout=10
        )
        if _quota_check and isinstance(_quota_check, dict):
            # AF /status: response — это list[dict], не dict
            _resp = _quota_check.get("response", {})
            if isinstance(_resp, list) and _resp:
                _resp = _resp[0]
            if isinstance(_resp, dict):
                _reqs = _resp.get("requests", {})
                if _reqs:
                    _used = _reqs.get("current", 0)
                    _lim  = _reqs.get("limit_day", 100)
                    _rem  = _lim - _used
                    _icon = "✅" if _rem > 20 else ("⚠️" if _rem > 5 else "🔴")
                    print(f"  {_icon} AF квота: {_used}/{_lim} использовано, осталось {_rem}")
                    if _rem < 2:
                        print("  🔴 AF квота исчерпана — результаты только из FD (топ-8 лиг)")
        elif _quota_check and "_error" in _quota_check:
            print(f"  ⚠️  AF статус: {_quota_check['_error'][:80]}")
    print()

    mode = sys.argv[1] if len(sys.argv) > 1 else "update"

    if mode == "stats":
        run_stats()
    elif mode == "sheets":
        results = _load(RESULTS_FILE)
        if isinstance(results, list) and results:
            print(f"\n📊 Синхронизирую {len(results)} матчей с Google Sheets...")
            push_to_sheets(results)
        else:
            print("📭 Нет данных в results.json")
    elif mode == "verify":
        verify_results(API_FOOTBALL_KEY)
    elif mode == "retro":
        run_retro()
    else:
        run_update(API_FOOTBALL_KEY, FOOTBALL_DATA_KEY)
