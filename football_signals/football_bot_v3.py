"""
╔══════════════════════════════════════════════════════════════╗
║       ⚽  FOOTBALL BETTING SIGNAL BOT  v9.0                 ║
║  Рынки  : 1X2·Тотал·Фора·ИТ·DNB·DC·Тайм·report·live      ║
║  Данные : Elo·xG·Streak·Sharp·Betfair·TM·News·Live·Report  ║
║  Сезон  : автоопределение 2025→2024 фоллбэк                 ║
╚══════════════════════════════════════════════════════════════╝

  python football_bot_v3.py demo        — тест без API
  python football_bot_v3.py today       — матчи СЕГОДНЯ
  python football_bot_v3.py scan        — ближайшие 3 дня
  python football_bot_v3.py scan 7      — ближайшие 7 дней
  python football_bot_v3.py schedule    — авто каждые 12ч
  python ml_calibrate.py               — ML-анализ + оптимальные веса
  python ml_calibrate.py report        — HTML отчёт эффективности
  python live_monitor.py               — live-мониторинг матчей
"""

import os, sys, json, math, csv, ssl, time, datetime
import urllib.request, urllib.parse, urllib.error

# ══════════════════════════════════════════════════════════════
#  🕐  ЧАСОВОЙ ПОЯС
# ══════════════════════════════════════════════════════════════
def _utc_to_local(utc_str: str) -> tuple[str, str]:
    """
    Конвертирует UTC время из API в локальное по UTC_OFFSET_HOURS.
    Форматы: "2026-02-27T19:45:00+00:00"  или  "2026-02-27T19:45:00Z"
    """
    try:
        s = utc_str.replace("Z", "+00:00").replace(" ", "T")
        dt_utc = datetime.datetime.fromisoformat(s)
        # Переводим в чистый UTC (убираем timezone info)
        if dt_utc.tzinfo is not None:
            dt_utc = dt_utc.utctimetuple()
            dt_utc = datetime.datetime(*dt_utc[:6])
        # Прибавляем наш UTC_OFFSET_HOURS
        dt_local = dt_utc + datetime.timedelta(hours=UTC_OFFSET_HOURS)
        return dt_local.strftime("%Y-%m-%d"), dt_local.strftime("%H:%M")
    except Exception:
        # Фоллбэк — берём как есть без конвертации
        parts = utc_str.replace("Z","").replace("+00:00","")
        if "T" in parts:
            date_part, time_part = parts.split("T", 1)
            return date_part, time_part[:5]
        return parts[:10], ""

def _fmt_date(date_str: str) -> str:
    """Конвертирует YYYY-MM-DD → DD.MM.YYYY для отображения."""
    try:
        parts = date_str.split("-")
        if len(parts) == 3:
            return f"{parts[2]}.{parts[1]}.{parts[0]}"
    except Exception:
        pass
    return date_str

# Самообучение — подгружаем если есть рядом
try:
    from learning import save_prediction as _save_pred, TEAM_STATS_FILE as _TS_FILE
    _LEARNING = True
except ImportError:
    _LEARNING = False

def _load_team_stats() -> dict:
    """Обученные параметры команд из learning.py (приоритет над TEAM_DB)."""
    if not _LEARNING:
        return {}
    try:
        with open(_TS_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

_LEARNED_STATS: dict = _load_team_stats()
from dataclasses import dataclass, field, asdict
from typing import Optional

# ══════════════════════════════════════════════════════════════
#  🔑  КЛЮЧИ
# ══════════════════════════════════════════════════════════════
API_FOOTBALL_KEY  = "33d9e41279e34866b001ab44dade2540"
FOOTBALL_DATA_KEY = "71fbcbe6dec84c59816a159ceaf4cf5d"
ODDS_API_KEY      = "ddf0e115efd4891c1ef2853afc297f2b"        # the-odds-api.com ключ 1
ODDS_API_KEY2     = ""   # резервный (пустой)
_ODDS_KEY_IDX     = 0
_ODDS_KEYS_LIST   = [k for k in [ODDS_API_KEY, ODDS_API_KEY2] if k]
PINNACLE_USER     = "FLASH2001"
PINNACLE_PASS     = "FLASH2001"
BETFAIR_USER      = ""   # логин Betfair (оставь пустым если нет)
BETFAIR_PASS      = ""   # пароль Betfair
BETFAIR_KEY       = ""   # App Key из личного кабинета Betfair
TELEGRAM_TOKEN    = "8263616332:AAGGJwEnlJSy160VlpaLcN2v8bbJ3hpf7gA"
TELEGRAM_CHAT_ID  = "-1003885532223"

# ══════════════════════════════════════════════════════════════
#  ⚙️  НАСТРОЙКИ
# ══════════════════════════════════════════════════════════════
MIN_EDGE     = 0.07  # КАЛИБРОВКА: повышен 0.03→0.07 (edge 3-5% давал ROI=-19%)
MIN_PROB     = 0.54  # КАЛИБРОВКА: повышен 0.52→0.54
KELLY_FRAC   = 0.15   # снижено 0.25→0.15: меньше дисперсия, ROI тот же
BANKROLL     = 1000
TOTAL_LINES  = [1.5, 2.5, 3.5]
EH_LINES     = [-2, -1, 1, 2]  # Европейский гандикап: -2 -1 +1 +2

# Часовой пояс: Москва/Минск = 3, Варшава зима = 1, лето = 2
UTC_OFFSET_HOURS = 3   # Московское время (UTC+3)

# API-Football: текущий сезон и фоллбэк
CURRENT_SEASON  = 2025   # 2025/26 — пробуем первым
FALLBACK_SEASON = 2024   # 2024/25 — если 2025 закрыт

# Лиги: AF league_id → название
LEAGUES = {
    # ── Топ-5 лиг ──────────────────────────────────────────
    39:  "Премьер-лига (Англия)",
    140: "Ла Лига (Испания)",
    135: "Серия А (Италия)",
    78:  "Бундеслига (Германия)",
    61:  "Лига 1 (Франция)",
    # ── Еврокубки ──────────────────────────────────────────
    2:   "Лига Чемпионов",
    3:   "Лига Европы",
    848: "Лига Конференций",
    # 531: "Суперкубок УЕФА",    # ОТКЛЮЧЁН: разовые матчи
    # ── Национальные кубки ─────────────────────────────────
    45:  "Кубок Англии (FA Cup)",
    48:  "Кубок Лиги Англии (EFL)",
    137: "Кубок Испании (Copa del Rey)",
    9:   "Кубок Италии (Coppa Italia)",
    81:  "Кубок Германии (DFB Pokal)",
    65:  "Кубок Франции",
    276: "Кубок России (Фонбет)",
    560: "Кубок Португалии",
    # 241: "Суперкубок России",  # ОТКЛЮЧЁН: 1 матч
    # ── Россия / СНГ ───────────────────────────────────────
    235: "Лига ПАРИ (РПЛ)",
    370: "Первая лига России (ФНЛ)",
    13:  "Copa Libertadores",
    11:  "Copa Sudamericana",
    # ── Западная Европа ────────────────────────────────────
    88:  "Эредивизи (Нидерланды)",
    94:  "Примейра-лига (Португалия)",
    141: "Сегунда (Испания Д2)",
    179: "Шотл. Премьершип",
    144: "Жюпиле Про Лига (Бельгия)",
    40:  "Чемпионшип (Англия Д2)",
    207: "Суперлига Швейцарии",
    218: "Австрийская Бундеслига",
    # ── Еврокубки — команды без топ-5 лиг ────────────────────────────
    # ЛЕ/ЛК участники: gs_home, gc_home, gs_away, gc_away
    "panathinaikos":      (1.50, 1.15, 1.20, 1.45),   # Греция, ЛЕ 2025-26
    "genk":               (1.85, 1.30, 1.55, 1.55),   # Бельгия, ЛЕ
    "midtjylland":        (1.70, 1.25, 1.45, 1.50),   # Дания, ЛЕ
    "ferencvaros":        (1.80, 1.20, 1.50, 1.50),   # Венгрия, ЛЕ
    "lech poznan":        (1.60, 1.30, 1.35, 1.55),   # Польша, ЛК
    "lech":               (1.60, 1.30, 1.35, 1.55),   # алиас
    "shakhtar donetsk":   (1.90, 1.10, 1.65, 1.30),   # Украина, ЛК/ЛЕ
    "shakhtar":           (1.90, 1.10, 1.65, 1.30),
    "rijeka":             (1.55, 1.30, 1.25, 1.55),   # Хорватия, ЛК
    "samsunspor":         (1.55, 1.40, 1.30, 1.60),   # Турция Д2, ЛК
    "aek larnaca":        (1.50, 1.30, 1.20, 1.55),   # Кипр, ЛК
    "sigma olomouc":      (1.40, 1.30, 1.15, 1.55),   # Чехия, ЛК
    "sigma":              (1.40, 1.30, 1.15, 1.55),
    "rakow czestochowa":  (1.55, 1.25, 1.30, 1.50),   # Польша, ЛК
    "rakow":              (1.55, 1.25, 1.30, 1.50),
    "celje":              (1.45, 1.35, 1.15, 1.60),   # Словения, ЛК
    "aek athens":         (1.65, 1.30, 1.35, 1.55),   # Греция, ЛЕ/ЛК
    "aek":                (1.65, 1.30, 1.35, 1.55),
    "sparta prague":      (1.75, 1.15, 1.50, 1.40),   # Чехия, ЛЕ
    "sparta":             (1.75, 1.15, 1.50, 1.40),
        # ── Турция ─────────────────────────────────────────────
    203: "Суперлига Турции",
    204: "Первая лига Турции",
    210: "Кубок Турции",
    # ── Скандинавия ────────────────────────────────────────
    103: "Элитесерен (Норвегия)",
    113: "Аллсвенскан (Швеция)",
    # ── Южная и Восточная Европа ───────────────────────────
    197: "Суперлига Сербии",
    172: "Экстраклаза (Польша)",
    167: "Чешская Первая лига",
    333: "Греческая Суперлига",
    271: "Датская Суперлига",
    # ── Азия / Ближний Восток / Африка ─────────────────────
    307: "Про-лига Саудовской Аравии",
    98:  "Ж-лига (Япония)",
    292: "К-лига 1 (Корея)",
    169: "Китайская Суперлига",
}

# ── Лиги с плохой историей сигналов (min_edge повышен) ─────────────────
# Раскомментируй лигу чтобы полностью исключить её из сканирования
LEAGUES_SKIP = set([
    # Лиги с подтверждённым отрицательным ROI по статистике
    # Добавляй сюда league_id после анализа signals_verified.csv
    333,  # Греческая Суперлига — ROI -51%
    271,  # Датская Суперлига — нет Understat
    197,  # Сербия — нет данных
    169,  # Китай — ненадёжные данные
    292,  # К-лига — нет Understat
    98,   # Япония — UTC+9
    13,   # Copa Libertadores — нет данных о ЮА командах (фантомные сигналы)
    11,   # Copa Sudamericana — аналогично
    88,   # Эредивизи — WR=0%, ROI=-100% (нет Understat)
    94,   # Примейра-лига — хронический ROI=-47%
])



# Нормализация лиговых имён (FD и AF дают разные строки → объединяем)
_LEAGUE_NAME_NORM: dict = {
    "Бундеслига":          "Бундеслига (Германия)",
    "Ла Лига":             "Ла Лига (Испания)",
    "Серия А":             "Серия А (Италия)",
    "Лига 1":              "Лига 1 (Франция)",
    "Эредивизи":           "Эредивизи (Нидерланды)",
    "Примейра-лига":       "Примейра-лига (Португалия)",
    "Чемпионшип":          "Чемпионшип (Англия Д2)",
}
def _norm_league_name(name: str) -> str:
    return _LEAGUE_NAME_NORM.get(name, name)

# football-data.org: код → AF league_id
FD_CODE_TO_LEAGUE = {
    "PL":  39,   "PD":  140,  "SA":  135,
    "BL1": 78,   "FL1": 61,   "CL":   2,
    "EL":   3,   "ECL": 848,  "DED":  88,
    "PPL": 94,   "SPL": 179,  "BSA": 144,
    "ELC": 40,   "TL1": 203,
    # Кубки (FD платный план — если есть доступ)
    "FAC": 45,   "EFL": 48,   "CDR": 137,
    "CIT": 9,    "DFB": 81,   "CDF": 65,
}
# Лиги доступные на бесплатном плане FD
FD_FREE_COMPETITIONS = {"PL", "PD", "SA", "BL1", "FL1", "CL", "EL", "ECL"}

# ══════════════════════════════════════════════════════════════
#  📊  БАЗА СТАТИСТИКИ КОМАНД — сезон 2025/26
#  Формат: "название_нижний_регистр": (scored_home, conc_home, scored_away, conc_away)
#  Источник: фактическая статистика первой половины сезона 2025/26
# ══════════════════════════════════════════════════════════════

# ══════════════════════════════════════════════════════════════
#  🇷🇺  РУССКИЕ НАЗВАНИЯ КОМАНД  (EN → RU)
#  FlashScore / официальные русскоязычные трансляции
# ══════════════════════════════════════════════════════════════
TEAM_NAMES_RU: dict = {
    # АПЛ
    "Arsenal":"Арсенал","Chelsea":"Челси","Liverpool":"Ливерпуль",
    "Manchester City":"Ман Сити","Manchester United":"Ман Юнайтед",
    "Tottenham Hotspur":"Тоттенхэм","Tottenham":"Тоттенхэм",
    "Newcastle United":"Ньюкасл","Newcastle":"Ньюкасл",
    "Aston Villa":"Астон Вилла","Brighton":"Брайтон",
    "Brighton & Hove Albion":"Брайтон",
    "West Ham United":"Вест Хэм","West Ham":"Вест Хэм",
    "Brentford":"Брентфорд","Fulham":"Фулхэм",
    "Crystal Palace":"Кристал Пэлас",
    "Wolverhampton Wanderers":"Вулверхэмптон","Wolverhampton":"Вулверхэмптон",
    "Everton":"Эвертон","Nottingham Forest":"Ноттингем","Nottingham":"Ноттингем",
    "Bournemouth":"Борнмут","AFC Bournemouth":"Борнмут",
    "Luton Town":"Лутон","Luton":"Лутон","Burnley":"Бёрнли",
    "Sheffield United":"Шеффилд Юнайтед",
    "Leicester City":"Лестер","Leicester":"Лестер",
    "Ipswich Town":"Ипсвич","Ipswich":"Ипсвич",
    "Southampton":"Саутгемптон","Sunderland":"Сандерленд",
    # Ла Лига
    "Real Madrid":"Реал Мадрид","Barcelona":"Барселона",
    "Atletico Madrid":"Атлетико","Atlético Madrid":"Атлетико",
    "Sevilla":"Севилья","Real Sociedad":"Реал Сосьедад",
    "Athletic Club":"Атлетик Бильбао","Athletic Bilbao":"Атлетик Бильбао",
    "Valencia":"Валенсия","Villarreal":"Вильярреал",
    "Real Betis":"Бетис","Betis":"Бетис","Osasuna":"Осасуна",
    "Getafe":"Хетафе","Celta Vigo":"Сельта","Celta":"Сельта",
    "Girona":"Жирона","Rayo Vallecano":"Райо Вальекано",
    "Mallorca":"Мальорка","Almeria":"Альмерия","Almería":"Альмерия",
    "Cadiz":"Кадис","Cádiz":"Кадис","Granada":"Гранада",
    "Las Palmas":"Лас-Пальмас","Alaves":"Алавес",
    "Deportivo Alaves":"Алавес","Espanyol":"Эспаньол",
    "Leganes":"Леганес","Leganés":"Леганес","Valladolid":"Вальядолид",
    # Серия А
    "Inter Milan":"Интер","Inter":"Интер","Napoli":"Наполи",
    "Juventus":"Ювентус","AC Milan":"Милан","Milan":"Милан",
    "Atalanta":"Аталанта","Roma":"Рома","AS Roma":"Рома",
    "Lazio":"Лацио","SS Lazio":"Лацио","Fiorentina":"Фиорентина",
    "Bologna":"Болонья","Torino":"Торино","Udinese":"Удинезе",
    "Genoa":"Дженоа","Como":"Комо","Lecce":"Лечче",
    "Cagliari":"Кальяри","Venezia":"Венеция","Monza":"Монца",
    "Parma":"Парма","Hellas Verona":"Верона","Verona":"Верона",
    "Pisa":"Пиза","Empoli":"Эмполи","Salernitana":"Салернитана",
    "Cremonese":"Кремонезе","Spezia":"Специя","Sassuolo":"Сассуоло",
    # Бундеслига
    "Bayern Munich":"Бавария","FC Bayern":"Бавария",
    "Bayer Leverkusen":"Байер","Bayer 04 Leverkusen":"Байер",
    "Borussia Dortmund":"Боруссия Д","RB Leipzig":"РБ Лейпциг",
    "Eintracht Frankfurt":"Айнтрахт","VfB Stuttgart":"Штутгарт","Stuttgart":"Штутгарт",
    "Wolfsburg":"Вольфсбург","VfL Wolfsburg":"Вольфсбург",
    "Freiburg":"Фрайбург","SC Freiburg":"Фрайбург",
    "Hoffenheim":"Хоффенхайм","TSG Hoffenheim":"Хоффенхайм",
    "Borussia Monchengladbach":"Боруссия М","Borussia Mönchengladbach":"Боруссия М",
    "Union Berlin":"Унион Берлин","1. FC Union Berlin":"Унион Берлин",
    "Werder Bremen":"Вердер","SV Werder Bremen":"Вердер",
    "Augsburg":"Аугсбург","FC Augsburg":"Аугсбург",
    "Mainz":"Майнц","1. FSV Mainz 05":"Майнц",
    "Cologne":"Кёльн","1. FC Koln":"Кёльн","Koln":"Кёльн",
    "Heidenheim":"Хайденхайм","1. FC Heidenheim":"Хайденхайм",
    "Holstein Kiel":"Киль","St. Pauli":"Санкт-Паули","FC St. Pauli":"Санкт-Паули",
    # Лига 1
    "Paris Saint-Germain":"ПСЖ","PSG":"ПСЖ",
    "Marseille":"Марсель","Olympique Marseille":"Марсель",
    "Monaco":"Монако","AS Monaco":"Монако",
    "Lyon":"Лион","Olympique Lyonnais":"Лион",
    "Lille":"Лилль","LOSC Lille":"Лилль",
    "Nice":"Ницца","OGC Nice":"Ницца",
    "Lens":"Ланс","RC Lens":"Ланс",
    "Rennes":"Ренн","Stade Rennais":"Ренн",
    "Nantes":"Нант","FC Nantes":"Нант",
    "Montpellier":"Монпелье","Strasbourg":"Страсбур",
    "Toulouse":"Тулуза","Brest":"Брест","Stade Brestois":"Брест",
    "Le Havre":"Гавр","Reims":"Реймс","Stade de Reims":"Реймс",
    "Lorient":"Лорьян","Clermont":"Клермон","Metz":"Мец",
    "Saint-Etienne":"Сент-Этьен","Auxerre":"Осер","Angers":"Анже",
    # Примейра-лига
    "Benfica":"Бенфика","SL Benfica":"Бенфика",
    "Sporting CP":"Спортинг","Sporting":"Спортинг",
    "Porto":"Порту","FC Porto":"Порту","Braga":"Брага","SC Braga":"Брага",
    "Vitoria Guimaraes":"Витория","Vitoria":"Витория",
    "Famalicao":"Фамаликан","Moreirense":"Морейренсе",
    "Gil Vicente":"Жил Висенте","Estoril":"Эшторил",
    "Arouca":"Ароука","Casa Pia":"Каза Пия","Rio Ave":"Рио Аве",
    "Pacos Ferreira":"Пасуш Феррейра","Nacional":"Насьонал",
    "Santa Clara":"Санта Клара","Boavista":"Боавишта",
    # Эредивизи
    "Ajax":"Аякс","PSV Eindhoven":"ПСВ","PSV":"ПСВ",
    "Feyenoord":"Фейеноорд","AZ Alkmaar":"АЗ","AZ":"АЗ",
    "FC Utrecht":"Утрехт","Utrecht":"Утрехт",
    "FC Twente":"Твенте","Twente":"Твенте",
    "NEC Nijmegen":"НЕК","NEC":"НЕК",
    "Sparta Rotterdam":"Спарта Роттердам",
    # Чемпионшип (АПЛ-2)
    "Leeds United":"Лидс","Leeds":"Лидс",
    "Hull City":"Халл","Hull":"Халл",
    "Middlesbrough":"Мидлсбро","Middlesbrough FC":"Мидлсбро",
    "Birmingham City":"Бирмингем","Birmingham":"Бирмингем",
    "Sheffield Wednesday":"Шеффилд Уэнсдей",
    "Millwall":"Миллуолл","Cardiff City":"Кардифф","Cardiff":"Кардифф",
    "Preston North End":"Престон","Preston":"Престон",
    "Swansea City":"Суонси","Swansea":"Суонси",
    "Coventry City":"Ковентри","Coventry":"Ковентри",
    "Stoke City":"Сток","Stoke":"Сток",
    "Norwich City":"Норвич","Norwich":"Норвич",
    "Watford":"Уотфорд","QPR":"КПР","Queens Park Rangers":"КПР",
    "Derby County":"Дерби","Derby":"Дерби",
    "Bristol City":"Бристоль","Bristol":"Бристоль",
    "Oxford United":"Оксфорд","Oxford":"Оксфорд",
    "Plymouth Argyle":"Плимут","Plymouth":"Плимут",
    "Portsmouth":"Портсмут","Portsmouth FC":"Портсмут",
    "Blackburn Rovers":"Блэкберн","Blackburn":"Блэкберн",
    "Sunderland":"Сандерленд","Sunderland AFC":"Сандерленд",
    "West Bromwich Albion":"Вест Бромвич","West Brom":"Вест Бромвич",
    # Шотландия
    "Dundee United":"Данди Юнайтед","Dundee Utd":"Данди Юнайтед",
    "Dundee FC":"Данди","Dundee":"Данди",
    "St Mirren":"Сент-Мирен","ST Mirren":"Сент-Мирен","St. Mirren":"Сент-Мирен",
    "Aberdeen":"Абердин","Aberdeen FC":"Абердин",
    "Hearts":"Харт оф Мидлотиан","Heart of Midlothian":"Харт оф Мидлотиан",
    "Hibernian":"Хайберниан","Hibs":"Хайберниан",
    "Motherwell":"Мазервелл",
    "Ross County":"Росс Каунти",
    "Livingston":"Ливингстон",
    "Kilmarnock":"Килмарнок",
    "St Johnstone":"Сент-Джонстон","St. Johnstone":"Сент-Джонстон",
    "Rangers":"Рейнджерс","Glasgow Rangers":"Рейнджерс",
    "Celtic":"Селтик","Glasgow Celtic":"Селтик",
    # Бельгия (Жюпиле Про Лига)
    "Club Brugge":"Брюгге","Club Brugge KV":"Брюгге",
    "Anderlecht":"Андерлехт","RSC Anderlecht":"Андерлехт",
    "Gent":"Гент","KAA Gent":"Гент",
    "Union Saint-Gilloise":"Юнион","Royale Union SG":"Юнион",
    "Antwerp":"Антверп","Royal Antwerp":"Антверп",
    "Standard Liege":"Стандард","Standard Liège":"Стандард",
    "Genk":"Генк","KRC Genk":"Генк",
    "OH Leuven":"Левен","OHL":"Левен",
    "Westerlo":"Вестерло","Cercle Brugge":"Серкль Брюгге",
    "Beerschot":"Бирсхот","Charleroi":"Шарлеруа",
    "Mechelen":"Мехелен","KV Mechelen":"Мехелен",
    "Kortrijk":"Кортрейк","KV Kortrijk":"Кортрейк",
    # Турция
    "Galatasaray":"Галатасарай",
    "Fenerbahce":"Фенербахче","Fenerbahçe":"Фенербахче",
    "Besiktas":"Бешикташ","Beşiktaş":"Бешикташ",
    "Trabzonspor":"Трабзонспор",
    "Basaksehir":"Башакшехир","İstanbul Başakşehir":"Башакшехир",
    "Sivasspor":"Сивасспор",
    "Konyaspor":"Коньяспор",
    "Gaziantep FK":"Газиантеп",
    "Kayserispor":"Кайсериспор",
    "Adana Demirspor":"Адана",
    # Бундеслига 2
    "Hamburger SV":"Гамбург","Hamburg":"Гамбург",
    "Schalke 04":"Шальке","Schalke":"Шальке","FC Schalke 04":"Шальке",
    "Hannover 96":"Ганновер","Hannover":"Ганновер",
    "Fortuna Dusseldorf":"Фортуна","Fortuna Düsseldorf":"Фортуна",
    "SpVgg Greuther Furth":"Фюрт","Greuther Furth":"Фюрт",
    "SSV Ulm":"Ульм",
    # Испания Б
    "Real Oviedo":"Реал Овьедо","Oviedo":"Реал Овьедо",
    "Rayo Vallecano":"Райо Вальекано",
    # Wolves алиас
    "Wolves":"Вулверхэмптон",
    # Команды без полного названия (алиасы)
    "Mirren":"Сент-Мирен",
    "Utd":"Юнайтед",    # ── Турция (доп.) ─────────────────────────────────────────
    "Trabzonspor":"Трабзонспор","Sivasspor":"Сивасспор",
    "Konyaspor":"Коньяспор","Rizespor":"Ризеспор",
    "Antalyaspor":"Анталиаспор","Kayserispor":"Кайсериспор",
    "Kasimpasa":"Касымпаша","Kasımpaşa":"Касымпаша",
    "Alanyaspor":"Аланьяспор","Adana Demirspor":"Адана Демирспор",
    "Istanbul Basaksehir":"Баскакшехир","İstanbul Başakşehir":"Баскакшехир",
    "Samsunspor":"Самсунспор","Eyupspor":"Эйюпспор","Eyüpspor":"Эйюпспор",
    "Hatayspor":"Хатайспор","Pendikspor":"Пендикспор",
    # ── Кубок Испании (Copa del Rey) доп. ─────────────────
    "CD Leganes":"Леганес","UD Las Palmas":"Лас-Пальмас",
    "RCD Mallorca":"Мальорка","Rayo Vallecano":"Райо Вальекано",
    "Girona FC":"Жирона",
    # ── Кубок Италии (Coppa Italia) доп. ──────────────────
    "Bologna":"Болонья","Bologna FC":"Болонья",
    "Torino":"Торино","Torino FC":"Торино",
    "Empoli":"Эмполи","Empoli FC":"Эмполи",
    "Hellas Verona":"Верона","Monza":"Монца",
    "Genoa":"Генуя","Genoa CFC":"Генуя",
    "Venezia":"Венеция","Venezia FC":"Венеция",
    "Cagliari":"Кальяри","Cagliari Calcio":"Кальяри",
    "Parma":"Парма","Parma Calcio":"Парма",
    "Como":"Комо","Como 1907":"Комо",
    "Lecce":"Лечче","US Lecce":"Лечче",
    "Udinese":"Удинезе","Udinese Calcio":"Удинезе",
    # ── Кубок России (Фонбет) ──────────────────────────────
    "CSKA Moscow":"ЦСКА","Lokomotiv Moscow":"Локомотив",
    "Spartak Moscow":"Спартак","Zenit":"Зенит","Zenit St. Petersburg":"Зенит",
    "Dynamo Moscow":"Динамо","Dynamo":"Динамо",
    "Krasnodar":"Краснодар","Akhmat Grozny":"Ахмат",
    "Rubin Kazan":"Рубин","Ural Yekaterinburg":"Урал",
    "Rostov":"Ростов","FK Rostov":"Ростов",
    "Torpedo Moscow":"Торпедо","Fakel Voronezh":"Факел",
    "Khimki":"Химки","FK Khimki":"Химки",
    "Orenburg":"Оренбург","FK Orenburg":"Оренбург",
    "Sochi":"Сочи","FK Sochi":"Сочи",
    "Pari Nizhny Novgorod":"Пари НН",
    # FIX: дополнительные варианты написания команд РПЛ из API-Football
    "Krylia Sovetov":"Крылья Советов",
    "Krylia Sovetov Samara":"Крылья Советов",
    "Krylya Sovetov Samara":"Крылья Советов",
    "CSKA":"ЦСКА",
    "Torpedo":"Торпедо",
    "Fakel":"Факел",
    "Akhmat":"Ахмат",
    "Nizhny Novgorod":"Пари НН",
    # ── ФНЛ (Первая лига России) ────────────────────────────
    "Baltika Kaliningrad":"Балтика","Baltika":"Балтика",
    "Shinnik Yaroslavl":"Шинник","Shinnik":"Шинник",
    "Tyumen":"Тюмень","FK Tyumen":"Тюмень",
    "Rodina Moscow":"Родина","Rodina":"Родина",
    "Sokol Saratov":"Сокол","Sokol":"Сокол",
    "SKA-Khabarovsk":"СКА-Хабаровск","SKA Khabarovsk":"СКА-Хабаровск",
    "Neftekhimik Nizhnekamsk":"Нефтехимик","Neftekhimik":"Нефтехимик",
    "Akron Togliatti":"Акрон","Akron":"Акрон",
    "Enisey Krasnoyarsk":"Енисей","Enisey":"Енисей",
    "Alania Vladikavkaz":"Алания","Alania":"Алания",
    "Chertanovo Moscow":"Чертаново","Chertanovo":"Чертаново",
    "Makhachkala":"Махачкала","FK Makhachkala":"Махачкала",
    "Arsenal Tula":"Арсенал Тула","Arsenal Tula FC":"Арсенал Тула",
    "Spartak-2 Moscow":"Спартак-2","Spartak 2":"Спартак-2",
    "CSKA-2 Moscow":"ЦСКА-2","CSKA 2":"ЦСКА-2",
    "Krasnodar-2":"Краснодар-2",
    "Tekstilshchik Ivanovo":"Текстильщик","Tekstilshchik":"Текстильщик",
    "Tambov":"Тамбов","FK Tambov":"Тамбов",
    "Volga Ulyanovsk":"Волга","Volga":"Волга",
    "Yenisey Krasnoyarsk":"Енисей",
    "Metallurg Lipetsk":"Металлург Липецк","Metallurg":"Металлург Липецк",
    "Ryazan":"Рязань","FK Ryazan":"Рязань",
    "Chayka Peschanokopskoye":"Чайка","Chayka":"Чайка",
    "Tom Tomsk":"Томь","Tom":"Томь",
    "Sakhalin":"Сахалин","FK Sakhalin":"Сахалин",
    "Khimki-M":"Химки-М",
    # ── РПЛ доп. варианты имён ─────────────────────────────
    "Lokomotiv":"Локомотив","PFC Lokomotiv Moscow":"Локомотив",
    "CSKA":"ЦСКА","PFC CSKA Moscow":"ЦСКА",
    "Spartak":"Спартак","FC Spartak Moscow":"Спартак",
    "Zenit Saint Petersburg":"Зенит","FC Zenit":"Зенит",
    "FK Dynamo Moscow":"Динамо","FC Dynamo Moscow":"Динамо",
    "FC Krasnodar":"Краснодар","FK Krasnodar":"Краснодар",
    "FC Rostov":"Ростов","PFC Rostov":"Ростов",
    "FC Akhmat Grozny":"Ахмат","PFC Akhmat":"Ахмат",
    "Rubin":"Рубин","FC Rubin Kazan":"Рубин",
    "FC Sochi":"Сочи","FK Sochi":"Сочи",
    "FC Orenburg":"Оренбург",
    "FC Khimki":"Химки",
    "FC Fakel Voronezh":"Факел","PFC Fakel":"Факел",
    "FC Torpedo Moscow":"Торпедо",
    "FC Ural Yekaterinburg":"Урал","FC Ural":"Урал",
    "Krylia Sovetov":"Крылья Советов","Krylia Sovetov Samara":"Крылья Советов",
    "Krylya Sovetov":"Крылья Советов",
    # ── Скандинавия / Восточная Европа ─────────────────────
    "Legia Warsaw":"Легия","Lech Poznan":"Лех","Rakow Czestochowa":"Ракув",
    "Slavia Prague":"Славия Прага","Sparta Prague":"Спарта Прага",
    "Red Star Belgrade":"Црвена звезда","Partizan":"Партизан",
    "AEK Athens":"АЕК Афины","Olympiacos":"Олимпиакос",
    "Panathinaikos":"Панатинаикос","PAOK":"ПАОК",
    "Rosenborg":"Русенборг","Bodo/Glimt":"Буде/Глимт",
    "Malmo FF":"Мальмё","IF Malmo":"Мальмё",
    "Copenhagen":"Копенгаген","FC Copenhagen":"Копенгаген",
    "Midtjylland":"Мидтьюлланд","FC Midtjylland":"Мидтьюлланд",
    # ── Португалия ─────────────────────────────────────────
    "Benfica":"Бенфика","SL Benfica":"Бенфика",
    "Porto":"Порто","FC Porto":"Порто",
    "Sporting CP":"Спортинг","Braga":"Брага","SC Braga":"Брага",
    # ── Нидерланды ─────────────────────────────────────────
    "Ajax":"Аякс","PSV Eindhoven":"ПСВ","PSV":"ПСВ",
    "Feyenoord":"Фейеноорд","AZ Alkmaar":"АЗ","AZ":"АЗ",
    "Utrecht":"Утрехт","FC Utrecht":"Утрехт",
    "Twente":"Твенте","FC Twente":"Твенте",
    # ── Азия / Ближний Восток ──────────────────────────────
    "Al Hilal":"Аль-Хиляль","Al Nassr":"Аль-Насcр",
    "Al Ittihad":"Аль-Иттихад","Al Ahli":"Аль-Ахли",
    "Urawa Red Diamonds":"Урава","Yokohama F Marinos":"Иокогама",
    "Jeonbuk":"Чонбук","Ulsan Hyundai":"Ульсан",

}

def _ru(name: str) -> str:
    """Переводит название команды на русский с несколькими уровнями поиска."""
    if not name:
        return name
    # 1. Точное совпадение
    if name in TEAM_NAMES_RU:
        return TEAM_NAMES_RU[name]
    nl = name.lower().strip()
    # 2. Case-insensitive точное
    for en, ru in TEAM_NAMES_RU.items():
        if en.lower() == nl:
            return ru
    # 3. Нормализованное совпадение (убираем FC/AFC/SC/City/United)
    def _norm(n):
        n = n.lower()
        for s in (" fc", "fc ", " afc", "afc ", " sc", " city", " united", " town",
                  " hotspur", " wanderers", " rovers", " athletic"):
            n = n.replace(s, "")
        return n.strip()
    nl_norm = _norm(nl)
    for en, ru in TEAM_NAMES_RU.items():
        if _norm(en.lower()) == nl_norm:
            return ru
    # 4. Частичное совпадение — берём наиболее длинное
    best, best_len = name, 0
    for en, ru in TEAM_NAMES_RU.items():
        enl = en.lower()
        if len(enl) >= 4 and (enl in nl or nl in enl):
            if len(enl) > best_len:
                best, best_len = ru, len(enl)
    if best_len >= 4:
        return best
    # 5. Возвращаем оригинал (не переводим незнакомые команды)
    return name

TEAM_DB: dict[str, tuple] = {
    # ── PREMIER LEAGUE ────────────────────────────────────────
    "liverpool":              (2.45, 0.80, 2.00, 1.00),
    "arsenal":                (2.10, 0.85, 1.65, 1.10),
    "chelsea":                (2.00, 1.10, 1.70, 1.30),
    "manchester city":        (1.80, 1.10, 1.55, 1.30),
    "manchester united":      (1.30, 1.60, 1.00, 1.75),
    "tottenham":              (1.80, 1.40, 1.50, 1.60),
    "newcastle":              (1.70, 1.10, 1.30, 1.30),
    "aston villa":            (1.70, 1.20, 1.40, 1.40),
    "brighton":               (1.60, 1.20, 1.40, 1.40),
    "west ham":               (1.30, 1.50, 1.10, 1.70),
    "brentford":              (1.50, 1.40, 1.20, 1.60),
    "fulham":                 (1.40, 1.20, 1.20, 1.40),
    "wolverhampton":          (1.10, 1.70, 0.90, 1.80),
    "everton":                (1.10, 1.50, 0.90, 1.70),
    "crystal palace":         (1.20, 1.30, 1.00, 1.50),
    "nottingham forest":      (1.30, 1.10, 1.00, 1.30),
    "bournemouth":            (1.50, 1.30, 1.30, 1.50),
    "leicester":              (1.20, 1.80, 1.00, 2.00),
    "ipswich":                (1.00, 1.80, 0.80, 2.00),
    "southampton":            (0.90, 2.00, 0.70, 2.20),
    "sunderland":             (1.40, 1.30, 1.20, 1.50),
    # ── LA LIGA ───────────────────────────────────────────────
    "real madrid":            (2.30, 0.85, 1.90, 1.00),
    "barcelona":              (2.45, 0.90, 2.10, 1.10),
    "atletico madrid":        (1.55, 0.72, 1.20, 0.90),
    "athletic bilbao":        (1.70, 1.00, 1.30, 1.20),
    "real sociedad":          (1.50, 1.10, 1.20, 1.30),
    "villarreal":             (1.60, 1.20, 1.30, 1.40),
    "real betis":             (1.50, 1.20, 1.20, 1.40),
    "sevilla":                (1.40, 1.30, 1.10, 1.50),
    "valencia":               (1.20, 1.60, 0.90, 1.80),
    "getafe":                 (1.10, 1.30, 0.90, 1.50),
    "osasuna":                (1.30, 1.30, 1.00, 1.50),
    "rayo vallecano":         (1.20, 1.40, 1.00, 1.60),
    "mallorca":               (1.10, 1.20, 0.90, 1.40),
    "celta vigo":             (1.40, 1.50, 1.10, 1.70),
    # ── SERIE A ───────────────────────────────────────────────
    "inter milan":            (2.00, 0.75, 1.70, 0.95),
    "napoli":                 (2.00, 0.90, 1.70, 1.10),
    "atalanta":               (2.25, 1.10, 1.85, 1.25),
    "juventus":               (1.60, 1.00, 1.30, 1.20),
    "milan":                  (1.80, 1.10, 1.50, 1.30),
    "ac milan":               (1.80, 1.10, 1.50, 1.30),
    "roma":                   (1.70, 1.20, 1.40, 1.40),
    "lazio":                  (1.70, 1.20, 1.40, 1.40),
    "fiorentina":             (1.70, 1.20, 1.40, 1.40),
    "torino":                 (1.30, 1.30, 1.10, 1.50),
    "bologna":                (1.50, 1.20, 1.30, 1.40),
    "genoa":                  (1.10, 1.60, 0.90, 1.80),
    "como":                   (1.10, 1.70, 0.90, 1.90),
    "lecce":                  (1.00, 1.80, 0.80, 2.00),
    "cagliari":               (1.10, 1.60, 0.90, 1.80),
    "venezia":                (0.90, 1.90, 0.70, 2.10),
    "monza":                  (1.00, 1.60, 0.80, 1.80),
    "udinese":                (1.20, 1.40, 1.00, 1.60),
    "parma":                  (1.10, 1.60, 0.90, 1.80),
    "hellas verona":          (1.20, 1.70, 1.00, 1.90),
    "pisa":                    (1.35, 1.35, 1.15, 1.50),
    "empoli":                  (1.20, 1.50, 1.00, 1.65),
    "salernitana":             (1.05, 1.70, 0.90, 1.80),
    "cremonese":               (1.10, 1.55, 0.95, 1.65),
    "spezia":                  (1.15, 1.55, 0.95, 1.65),
    "inter":                   (2.20, 0.80, 1.80, 1.00),
    # ── PRIMEIRA LIGA ─────────────────────────────────────────
    "benfica":                 (2.20, 0.90, 1.90, 1.10),
    "sporting cp":             (2.10, 0.95, 1.80, 1.15),
    "sporting":                (2.10, 0.95, 1.80, 1.15),
    "porto":                   (2.00, 1.00, 1.75, 1.20),
    "fc porto":                (2.00, 1.00, 1.75, 1.20),
    "braga":                   (1.65, 1.20, 1.40, 1.35),
    "vitoria guimaraes":       (1.40, 1.30, 1.20, 1.45),
    "vitoria":                 (1.40, 1.30, 1.20, 1.45),
    "famalicao":               (1.20, 1.50, 1.00, 1.60),
    "moreirense":              (1.15, 1.50, 0.95, 1.60),
    "gil vicente":             (1.15, 1.50, 0.95, 1.60),
    "estoril":                 (1.20, 1.55, 1.00, 1.65),
    "arouca":                  (1.15, 1.50, 0.95, 1.60),
    "casa pia":                (1.15, 1.50, 0.95, 1.60),
    "rio ave":                 (1.20, 1.45, 1.00, 1.55),
    "pacos ferreira":          (1.15, 1.55, 0.95, 1.65),
    "nacional":                (1.10, 1.60, 0.90, 1.70),
    "santa clara":             (1.15, 1.55, 0.95, 1.65),
    # ── BUNDESLIGA ────────────────────────────────────────────
    "bayer leverkusen":       (2.30, 0.90, 1.90, 1.10),
    "borussia dortmund":      (2.00, 1.20, 1.70, 1.40),
    "fc bayern":              (2.60, 1.00, 2.20, 1.20),
    "bayern munich":          (2.60, 1.00, 2.20, 1.20),
    "rb leipzig":             (2.00, 1.10, 1.70, 1.30),
    "eintracht frankfurt":    (1.70, 1.30, 1.40, 1.50),
    "wolfsburg":              (1.50, 1.30, 1.20, 1.50),
    "freiburg":               (1.40, 1.20, 1.10, 1.40),
    "borussia monchengladbach":(1.50, 1.40, 1.20, 1.60),
    "union berlin":           (1.20, 1.50, 0.90, 1.70),
    "werder bremen":          (1.40, 1.40, 1.10, 1.60),
    "hoffenheim":             (1.40, 1.50, 1.10, 1.70),
    "augsburg":               (1.20, 1.50, 1.00, 1.70),
    "mainz":                  (1.30, 1.30, 1.00, 1.50),
    "vfb stuttgart":          (1.70, 1.20, 1.40, 1.40),
    "heidenheim":             (1.20, 1.50, 1.00, 1.70),
    "st. pauli":              (1.10, 1.60, 0.90, 1.80),
    "holstein kiel":          (0.90, 2.00, 0.70, 2.20),
    # ── LIGUE 1 ───────────────────────────────────────────────
    "psg":                    (2.80, 0.80, 2.40, 1.00),
    "paris saint-germain":    (2.80, 0.80, 2.40, 1.00),
    "marseille":              (1.80, 1.10, 1.50, 1.30),
    "monaco":                 (2.00, 1.10, 1.70, 1.30),
    "lyon":                   (1.60, 1.20, 1.30, 1.40),
    "lille":                  (1.60, 1.10, 1.30, 1.30),
    "nice":                   (1.50, 1.00, 1.20, 1.20),
    "lens":                   (1.40, 1.20, 1.10, 1.40),
    "rennes":                 (1.40, 1.30, 1.10, 1.50),
    "strasbourg":             (1.30, 1.40, 1.00, 1.60),
    "brest":                  (1.50, 1.30, 1.20, 1.50),
    # ── CHAMPIONS LEAGUE (дополнительно) ──────────────────────
    "benfica":                (2.10, 1.10, 1.70, 1.30),
    "porto":                  (1.90, 1.00, 1.60, 1.20),
    "sporting cp":            (1.90, 1.00, 1.60, 1.20),
    "celtic":                 (1.80, 0.90, 1.50, 1.10),
    "rangers":                (1.60, 1.00, 1.30, 1.20),
    "ajax":                   (2.00, 1.10, 1.70, 1.30),
    "psv":                    (2.20, 0.90, 1.80, 1.10),
    "galatasaray":            (2.00, 1.20, 1.70, 1.40),
    "fenerbahce":             (1.80, 1.10, 1.50, 1.30),
    "besiktas":               (1.60, 1.30, 1.30, 1.50),
    "ac bruges":              (1.70, 1.00, 1.40, 1.20),
    "club brugge":            (1.70, 1.00, 1.40, 1.20),
    "anderlecht":             (1.60, 1.20, 1.30, 1.40),
    "shakhtar donetsk":       (1.70, 1.10, 1.40, 1.30),
    "dinamo zagreb":          (1.60, 1.10, 1.30, 1.30),
    "red bull salzburg":      (1.80, 1.10, 1.50, 1.30),
    "bsc young boys":         (1.50, 1.20, 1.20, 1.40),
    "slavia prague":          (1.60, 1.00, 1.30, 1.20),
    "sparta prague":          (1.60, 1.00, 1.30, 1.20),
    # ── EREDIVISIE ────────────────────────────────────────────
    "feyenoord":              (2.10, 1.00, 1.80, 1.20),
    "az alkmaar":             (1.90, 1.00, 1.60, 1.20),
    "utrecht":                (1.60, 1.20, 1.30, 1.40),
    "twente":                 (1.70, 1.10, 1.40, 1.30),
    "go ahead eagles":        (1.40, 1.40, 1.10, 1.60),
    "nec nijmegen":           (1.30, 1.40, 1.00, 1.60),
    "heerenveen":             (1.40, 1.50, 1.10, 1.70),
    "groningen":              (1.20, 1.60, 1.00, 1.80),
    "sparta rotterdam":       (1.30, 1.40, 1.00, 1.60),
    "roda":                   (1.10, 1.60, 0.90, 1.80),
    # ── РПЛ (Лига ПАРИ) — сезон 2024/25 ──────────────────────
    "zenit":                  (2.10, 0.75, 1.80, 0.95),
    "zenit st. petersburg":   (2.10, 0.75, 1.80, 0.95),
    "krasnodar":              (1.85, 0.90, 1.60, 1.10),
    "cska moscow":            (1.70, 0.95, 1.45, 1.15),
    "spartak moscow":         (1.65, 1.05, 1.40, 1.25),
    "lokomotiv moscow":       (1.55, 1.10, 1.30, 1.30),
    "dynamo moscow":          (1.60, 1.00, 1.35, 1.20),
    "rostov":                 (1.50, 1.10, 1.25, 1.30),
    "rubin kazan":            (1.35, 1.20, 1.10, 1.40),
    "krylia sovetov":         (1.30, 1.25, 1.05, 1.45),
    "krylya sovetov":         (1.30, 1.25, 1.05, 1.45),
    "akhmat grozny":          (1.30, 1.30, 1.05, 1.50),
    "torpedo moscow":         (1.25, 1.35, 1.00, 1.55),
    "fakel voronezh":         (1.20, 1.35, 0.95, 1.55),
    "khimki":                 (1.20, 1.40, 0.95, 1.60),
    "orenburg":               (1.25, 1.30, 1.00, 1.50),
    "sochi":                  (1.30, 1.25, 1.05, 1.45),
    "ural yekaterinburg":     (1.20, 1.40, 0.95, 1.60),
    "pari nizhny novgorod":   (1.25, 1.35, 1.00, 1.55),
    "nizhny novgorod":        (1.25, 1.35, 1.00, 1.55),  # FIX: альт. имя
    "torpedo moscow":         (1.25, 1.35, 1.00, 1.55),  # FIX: дублируем
    # Команды ФНЛ 2025/26 которых нет в TEAM_DB
    "tyumen":                 (1.20, 1.35, 0.95, 1.55),
    "rodina":                 (1.15, 1.40, 0.90, 1.60),
    "rodina moscow":          (1.15, 1.40, 0.90, 1.60),
    "enisey":                 (1.20, 1.40, 0.95, 1.60),
    "enisey krasnoyarsk":     (1.20, 1.40, 0.95, 1.60),
    "chertanovo":             (1.15, 1.45, 0.90, 1.65),
    "makhachkala":            (1.30, 1.30, 1.05, 1.50),
    "neftekhimik":            (1.20, 1.40, 0.95, 1.60),
    "ska-khabarovsk":         (1.15, 1.50, 0.90, 1.65),
    "ska khabarovsk":         (1.15, 1.50, 0.90, 1.65),
    # ── ФНЛ (Первая лига России) — сезон 2024/25 ──────────────
    "baltika kaliningrad":    (1.35, 1.20, 1.10, 1.40),
    "baltika":                (1.35, 1.20, 1.10, 1.40),
    "arsenal tula":           (1.30, 1.20, 1.05, 1.40),
    "shinnik yaroslavl":      (1.20, 1.35, 0.95, 1.55),
    "shinnik":                (1.20, 1.35, 0.95, 1.55),
    "akron togliatti":        (1.40, 1.15, 1.15, 1.35),
    "akron":                  (1.40, 1.15, 1.15, 1.35),
    "alania vladikavkaz":     (1.35, 1.25, 1.10, 1.45),
    "alania":                 (1.35, 1.25, 1.10, 1.45),
    "sokol saratov":          (1.25, 1.30, 1.00, 1.50),
    "sokol":                  (1.25, 1.30, 1.00, 1.50),
    "tyumen":                 (1.20, 1.35, 0.95, 1.55),
    "rodina moscow":          (1.20, 1.35, 0.95, 1.55),
    "rodina":                 (1.20, 1.35, 0.95, 1.55),
    "neftekhimik":            (1.15, 1.40, 0.90, 1.60),
    "enisey krasnoyarsk":     (1.15, 1.40, 0.90, 1.60),
    "enisey":                 (1.15, 1.40, 0.90, 1.60),
    "ska-khabarovsk":         (1.10, 1.45, 0.85, 1.65),
    "chertanovo moscow":      (1.15, 1.40, 0.90, 1.60),
    "makhachkala":            (1.20, 1.35, 0.95, 1.55),
    "tom tomsk":              (1.20, 1.30, 0.95, 1.50),
    "tom":                    (1.20, 1.30, 0.95, 1.50),
    "ryazan":                 (1.15, 1.35, 0.90, 1.55),
    "metallurg lipetsk":      (1.10, 1.45, 0.85, 1.65),
    "tekstilshchik":          (1.10, 1.45, 0.85, 1.65),
    "tambov":                 (1.10, 1.50, 0.85, 1.70),
    "volga":                  (1.15, 1.40, 0.90, 1.60),
    "sakhalin":               (1.05, 1.55, 0.80, 1.75),
    "chayka":                 (1.10, 1.50, 0.85, 1.70),
    "spartak-2 moscow":       (1.30, 1.30, 1.05, 1.50),
    "spartak 2":              (1.30, 1.30, 1.05, 1.50),
    "krasnodar-2":            (1.35, 1.20, 1.10, 1.40),
}


# ═══════════════════════════════════════════════════════════════
#  📈  ФОРМА КОМАНД — последние 5 матчей (W=1, D=0.4, L=0)
#  Обновляется автоматически через learning.py
#  Формат: "название": [результаты], где 1=победа, 0.5=ничья, 0=поражение
# ═══════════════════════════════════════════════════════════════
FORM_DB: dict[str, list] = {
    # PREMIER LEAGUE
    "liverpool":           [1,1,1,0.5,1],   # горячая форма
    "arsenal":             [1,1,0.5,1,1],
    "chelsea":             [1,0.5,1,1,0],
    "manchester city":     [0.5,1,0,1,1],
    "manchester united":   [0,0,0.5,1,0],   # плохая форма
    "tottenham":           [1,0,1,0,0.5],
    "newcastle":           [1,1,0.5,0.5,1],
    "aston villa":         [0.5,1,1,0,1],
    "wolverhampton":       [0,0,0.5,0,0],   # кризис
    "nottingham forest":   [1,1,0.5,1,0.5],
    "bournemouth":         [1,0.5,1,0,1],
    "brighton":            [0.5,1,0,1,0.5],
    "brentford":           [0,1,0.5,1,0],
    "fulham":              [1,0.5,0.5,0,1],
    "crystal palace":      [0,0.5,1,0,0.5],
    "everton":             [0,0.5,0,0,1],
    "west ham":            [0.5,0,0,1,0.5],
    "ipswich":             [0,0,0,0.5,0],
    "leicester":           [0,0,0.5,0,0],
    "southampton":         [0,0,0,0,0.5],
    "sunderland":          [1,0.5,1,0.5,1],
    # LA LIGA
    "barcelona":           [1,1,1,0.5,1],
    "real madrid":         [1,0.5,1,1,1],
    "atletico madrid":     [1,1,0.5,1,0.5],
    "athletic bilbao":     [1,1,0,1,0.5],
    "real sociedad":       [0.5,0,1,0.5,1],
    "villarreal":          [1,0.5,0,1,1],
    "real betis":          [0.5,1,0.5,0,1],
    "sevilla":             [0,0.5,1,0.5,0],
    # SERIE A
    "napoli":              [1,1,0.5,1,1],
    "inter milan":         [1,1,1,0.5,0.5],
    "atalanta":            [1,1,0.5,1,0],
    "juventus":            [0.5,1,0.5,0,0.5],
    "milan":               [0.5,0,1,0.5,0],
    "lazio":               [1,0.5,1,0,1],
    "fiorentina":          [1,0.5,0.5,1,0],
    "roma":                [0.5,0,0.5,1,0.5],
    # BUNDESLIGA
    "bayer leverkusen":    [1,1,0.5,1,1],
    "fc bayern":           [1,1,1,0.5,1],
    "bayern munich":       [1,1,1,0.5,1],
    "borussia dortmund":   [0.5,1,0,1,0.5],
    "rb leipzig":          [1,0.5,1,0,1],
    "vfb stuttgart":       [1,1,0.5,0,1],
    "eintracht frankfurt": [0.5,1,0.5,1,0],
    # LIGUE 1
    "psg":                 [1,1,1,1,0.5],
    "paris saint-germain": [1,1,1,1,0.5],
    "monaco":              [1,0.5,1,0,1],
    "marseille":           [0.5,1,0.5,1,0],
    "lille":               [1,0.5,1,0.5,0],
    "nice":                [1,1,0,0.5,1],
    # CL/EL
    "galatasaray":         [1,1,0.5,1,0],
    "benfica":             [1,0.5,1,1,0.5],
    "ajax":                [1,1,0.5,0.5,1],
    "psv":                 [1,1,1,0.5,1],
    "feyenoord":           [0.5,1,1,0,1],
    "sporting cp":         [1,1,0.5,1,0],
    "porto":               [1,0.5,0.5,1,1],
    # ── РПЛ (Лига ПАРИ) ────────────────────────────────────
    "zenit":               [1,1,1,0.5,1],
    "krasnodar":           [1,1,0.5,1,1],
    "cska moscow":         [1,0.5,1,1,0.5],
    "spartak moscow":      [0.5,1,0,1,1],
    "lokomotiv moscow":    [1,0.5,1,0,1],
    "dynamo moscow":       [1,1,0.5,0,1],
    "rostov":              [0.5,1,1,0,0.5],
    "rubin kazan":         [0,0.5,1,0.5,0],
    "akhmat grozny":       [0.5,0,0.5,1,0],
    "torpedo moscow":      [0,0.5,0,0.5,1],
    "fakel voronezh":      [0,0,0.5,0,0.5],
    "khimki":              [0.5,0,0,0.5,0],
    "orenburg":            [0.5,1,0,0.5,0],
    "sochi":               [0,0.5,1,0,0.5],
    "krylia sovetov":      [0.5,0,1,0.5,0],
    "krylya sovetov":      [0.5,0,1,0.5,0],
    "pari nizhny novgorod":[0.5,1,0,0,0.5],
    "ural yekaterinburg":  [0,0.5,0,0.5,0],
    # ── ФНЛ (Первая лига) ──────────────────────────────────
    "baltika":             [1,0.5,1,0.5,1],
    "baltika kaliningrad": [1,0.5,1,0.5,1],
    "arsenal tula":        [1,1,0.5,0,1],
    "akron":               [1,0.5,1,0.5,0],
    "akron togliatti":     [1,0.5,1,0.5,0],
    "alania":              [0.5,1,0.5,1,0],
    "alania vladikavkaz":  [0.5,1,0.5,1,0],
    "shinnik":             [0.5,0,1,0.5,0],
    "sokol":               [0.5,1,0,0.5,0],
    "sokol saratov":       [0.5,1,0,0.5,0],
    "tyumen":              [0,0.5,0.5,0,1],
    "rodina":              [0,0.5,1,0,0.5],
    "enisey":              [0.5,0,0.5,0,0],
    "makhachkala":         [0.5,0.5,0,0.5,0],
    "tom":                 [0,0.5,0,0,0.5],
    "neftekhimik":         [0,0,0.5,0,0],
    "ska-khabarovsk":      [0,0,0,0.5,0],
    "chertanovo moscow":   [0.5,0,0,0.5,0],
}


def calc_streak_factor(results: list) -> float:
    """
    Бонус/штраф за серию последних матчей.
    Серия 3+ побед → +5%, серия 3+ поражений → -5%.
    """
    if not results or len(results) < 3:
        return 1.0
    last = results[-3:]
    if all(r >= 0.6 for r in last):   return 1.05   # серия побед
    if all(r <= 0.2 for r in last):   return 0.95   # серия поражений
    return 1.0

def _calc_form(name: str) -> tuple[float, float, float]:
    """
    Считает три показателя формы по последним 5 матчам:
    - form_rating:  общий рейтинг 0.6–1.4
    - attack_trend: тренд атаки (последние 2 vs предыдущие 3)
    - defense_trend: тренд обороны

    Возвращает (form_rating, attack_trend, defense_trend)
    """
    key = name.lower().strip()
    for sfx in [" fc"," afc"," sc"," cf"," bc"]:
        key = key.replace(sfx,"").strip()

    # Ищем в FORM_DB (точное + частичное)
    results = None
    if key in FORM_DB:
        results = FORM_DB[key]
    else:
        kw = set(key.split()) - {"city","united","the","de"}
        for db_key, vals in FORM_DB.items():
            db_words = set(db_key.split())
            if len(kw & db_words) >= 1:
                results = vals
                break

    # Пробуем загрузить из файла обучения (актуальная форма)
    try:
        import json as _j, os as _os
        if _os.path.exists("team_stats.json"):
            with open("team_stats.json") as f:
                ts = _j.load(f)
            if key in ts and "form" in ts[key]:
                results = ts[key]["form"]
    except Exception:
        pass

    if not results or len(results) < 3:
        return 1.0, 1.0, 1.0, 1.0   # нет данных — нейтральная форма

    r = results[-5:]  # последние 5
    avg = sum(r) / len(r)

    # form_rating: 0.4/матч = нейтраль, масштабируем к 0.7–1.3
    form_rating = 0.70 + avg * 1.50
    form_rating = max(0.70, min(1.40, form_rating))

    # Тренд: последние 2 матча vs предыдущие
    recent = sum(r[-2:]) / 2
    older  = sum(r[:-2]) / max(len(r)-2, 1)
    trend  = 1.0 + (recent - older) * 0.3
    trend  = max(0.85, min(1.20, trend))

    streak = calc_streak_factor(results)
    return round(form_rating, 3), round(trend, 3), round(2.0 - trend, 3), round(streak, 4)

LEAGUE_DEFAULTS = {
    39:  {"h_gs":1.62,"h_gc":1.22,"a_gs":1.21,"a_gc":1.61},  # АПЛ
    140: {"h_gs":1.55,"h_gc":1.10,"a_gs":1.10,"a_gc":1.55},  # Ла Лига
    135: {"h_gs":1.51,"h_gc":1.18,"a_gs":1.18,"a_gc":1.51},  # Серия А
    78:  {"h_gs":1.65,"h_gc":1.30,"a_gs":1.30,"a_gc":1.65},  # Бундеслига
    61:  {"h_gs":1.48,"h_gc":1.20,"a_gs":1.20,"a_gc":1.48},  # Лига 1
    2:   {"h_gs":1.82,"h_gc":1.25,"a_gs":1.25,"a_gc":1.82},  # ЛЧ
    3:   {"h_gs":1.70,"h_gc":1.30,"a_gs":1.30,"a_gc":1.70},  # ЛЕ
    848: {"h_gs":1.65,"h_gc":1.25,"a_gs":1.25,"a_gc":1.65},  # ЛКЕ
    # Кубки — более голевые (плей-офф, нет ничьих в большинстве раундов)
    45:  {"h_gs":1.65,"h_gc":1.30,"a_gs":1.30,"a_gc":1.65},  # FA Cup
    48:  {"h_gs":1.65,"h_gc":1.30,"a_gs":1.30,"a_gc":1.65},  # EFL Cup
    137: {"h_gs":1.60,"h_gc":1.20,"a_gs":1.20,"a_gc":1.60},  # Copa del Rey
    9:   {"h_gs":1.55,"h_gc":1.20,"a_gs":1.20,"a_gc":1.55},  # Coppa Italia
    81:  {"h_gs":1.65,"h_gc":1.30,"a_gs":1.30,"a_gc":1.65},  # DFB Pokal
    65:  {"h_gs":1.55,"h_gc":1.25,"a_gs":1.25,"a_gc":1.55},  # Кубок Франции
    276: {"h_gs":1.50,"h_gc":1.30,"a_gs":1.30,"a_gc":1.50},  # Кубок России
    210: {"h_gs":1.60,"h_gc":1.35,"a_gs":1.35,"a_gc":1.60},  # Кубок Турции
    # Другие лиги
    88:  {"h_gs":1.80,"h_gc":1.40,"a_gs":1.40,"a_gc":1.80},  # Эредивизи
    94:  {"h_gs":1.55,"h_gc":1.20,"a_gs":1.20,"a_gc":1.55},  # Примейра
    203: {"h_gs":1.60,"h_gc":1.35,"a_gs":1.35,"a_gc":1.60},  # Турция
    204: {"h_gs":1.55,"h_gc":1.35,"a_gs":1.35,"a_gc":1.55},  # Турция Д2
    235: {"h_gs":1.55,"h_gc":1.30,"a_gs":1.30,"a_gc":1.55},  # РПЛ
    370: {"h_gs":1.45,"h_gc":1.30,"a_gs":1.30,"a_gc":1.45},  # ФНЛ
    141: {"h_gs":1.45,"h_gc":1.20,"a_gs":1.20,"a_gc":1.45},  # Сегунда
    179: {"h_gs":1.55,"h_gc":1.30,"a_gs":1.30,"a_gc":1.55},  # Шотландия
    144: {"h_gs":1.75,"h_gc":1.40,"a_gs":1.40,"a_gc":1.75},  # Бельгия
    40:  {"h_gs":1.55,"h_gc":1.30,"a_gs":1.30,"a_gc":1.55},  # Чемпионшип
    207: {"h_gs":1.65,"h_gc":1.30,"a_gs":1.30,"a_gc":1.65},  # Швейцария
    218: {"h_gs":1.70,"h_gc":1.35,"a_gs":1.35,"a_gc":1.70},  # Австрия
    172: {"h_gs":1.50,"h_gc":1.25,"a_gs":1.25,"a_gc":1.50},  # Польша
    167: {"h_gs":1.50,"h_gc":1.25,"a_gs":1.25,"a_gc":1.50},  # Чехия
    333: {"h_gs":1.55,"h_gc":1.35,"a_gs":1.35,"a_gc":1.55},  # Греция
    197: {"h_gs":1.60,"h_gc":1.35,"a_gs":1.35,"a_gc":1.60},  # Сербия
    271: {"h_gs":1.60,"h_gc":1.30,"a_gs":1.30,"a_gc":1.60},  # Дания
    307: {"h_gs":1.70,"h_gc":1.30,"a_gs":1.30,"a_gc":1.70},  # Саудовская Аравия
}

def _lookup_team(name: str, is_home: bool, league_id: int) -> tuple:
    """
    Приоритет: 1) Обученные данные (team_stats.json)
               2) Встроенная TEAM_DB
               3) Средние по лиге
    """
    key = name.lower().strip()
    for sfx in [" fc", " cf", " sc", " afc", " bc", " fk", " sk", " ac"]:
        key = key.replace(sfx, "").strip()

    # Приоритет 0: обученные данные из learning.py
    if _LEARNED_STATS and key in _LEARNED_STATS:
        st = _LEARNED_STATS[key]
        gs = st["h_gs"] if is_home else st["a_gs"]
        gc = st["h_gc"] if is_home else st["a_gc"]
        m  = st.get("matches", 0)
        return gs, gc, True  # помечаем как найденное

    # Приоритет 1: встроенная база TEAM_DB
    if key in TEAM_DB:
        gs_h, gc_h, gs_a, gc_a = TEAM_DB[key]
        gs = gs_h if is_home else gs_a
        gc = gc_h if is_home else gc_a
        return gs, gc, True

    # Частичное: ищем по словам (минимум 1 значимое слово)
    key_words = set(key.split()) - {"city", "united", "the", "of", "de", "fc"}
    best_match, best_score = None, 0
    for db_key in TEAM_DB:
        db_words = set(db_key.split())
        common   = len(key_words & db_words)
        if common > best_score and common >= 1:
            best_score  = common
            best_match  = db_key
    if best_match and best_score >= 1:
        gs_h, gc_h, gs_a, gc_a = TEAM_DB[best_match]
        gs = gs_h if is_home else gs_a
        gc = gc_h if is_home else gc_a
        return gs, gc, True

    # Средние по лиге
    ld = LEAGUE_DEFAULTS.get(league_id, {"h_gs":1.55,"h_gc":1.25,"a_gs":1.25,"a_gc":1.55})
    gs = ld["h_gs"] if is_home else ld["a_gs"]
    gc = ld["h_gc"] if is_home else ld["a_gc"]
    return gs, gc, False


# ══════════════════════════════════════════════════════════════
#  📦  СТРУКТУРЫ
# ══════════════════════════════════════════════════════════════

# ══════════════════════════════════════════════════════════════
#  📈  СТАТИЧЕСКАЯ БАЗА ФОРМЫ  (form_rating, atk_trend, def_trend)
#  Обновлять вручную по ходу сезона или через team_stats.json
#  Формат: "ключ": (form_rating, attack_trend, defense_trend)
#  1.15 = топ-форма | 1.0 = средняя | 0.85 = плохая форма
# ══════════════════════════════════════════════════════════════
FORM_DB: dict = {
    # АПЛ
    "arsenal":           (1.10, 1.10, 1.05),
    "manchester city":   (1.05, 1.05, 1.00),
    "liverpool":         (1.15, 1.15, 1.05),
    "chelsea":           (1.00, 1.00, 1.00),
    "tottenham":         (0.95, 0.95, 0.95),
    "newcastle":         (1.05, 1.05, 1.00),
    "aston villa":       (1.00, 1.00, 1.00),
    "manchester united": (0.90, 0.90, 0.90),
    "west ham":          (0.95, 0.95, 0.95),
    "brighton":          (1.00, 1.00, 1.00),
    "fulham":            (1.00, 1.00, 1.00),
    "brentford":         (0.95, 0.95, 1.00),
    "nottingham forest": (1.05, 1.00, 1.05),
    "crystal palace":    (0.95, 0.90, 1.00),
    "everton":           (0.95, 0.90, 1.00),
    "wolverhampton":     (0.90, 0.90, 0.95),
    "bournemouth":       (1.00, 1.00, 1.00),
    "ipswich":           (0.85, 0.85, 0.85),
    "leicester":         (0.85, 0.85, 0.85),
    "southampton":       (0.80, 0.80, 0.85),
    "sunderland":        (1.00, 1.00, 1.00),
    # Ла Лига
    "real madrid":       (1.10, 1.10, 1.05),
    "barcelona":         (1.10, 1.15, 1.00),
    "atletico madrid":   (1.05, 1.00, 1.10),
    "athletic bilbao":   (1.05, 1.05, 1.05),
    "real sociedad":     (1.00, 1.00, 1.00),
    "girona":            (1.00, 1.00, 1.00),
    "villarreal":        (1.00, 1.00, 1.00),
    "betis":             (1.00, 1.00, 1.00),
    "sevilla":           (0.90, 0.90, 0.90),
    "osasuna":           (1.00, 1.00, 1.00),
    "getafe":            (0.95, 0.90, 1.00),
    "celta":             (0.95, 0.95, 0.95),
    "valencia":          (0.90, 0.90, 0.90),
    "mallorca":          (0.95, 0.90, 1.00),
    "rayo vallecano":    (0.95, 0.95, 0.95),
    "espanyol":          (0.90, 0.90, 0.90),
    "leganes":           (0.90, 0.90, 0.95),
    "alaves":            (0.90, 0.90, 0.90),
    "las palmas":        (0.90, 0.90, 0.90),
    "valladolid":        (0.85, 0.85, 0.85),
    # Серия А
    "inter":             (1.10, 1.10, 1.10),
    "napoli":            (1.10, 1.10, 1.05),
    "atalanta":          (1.10, 1.15, 1.05),
    "juventus":          (1.00, 0.95, 1.05),
    "milan":             (0.95, 0.95, 1.00),
    "fiorentina":        (1.05, 1.05, 1.00),
    "lazio":             (1.00, 1.00, 1.00),
    "roma":              (0.95, 0.95, 0.95),
    "bologna":           (1.00, 1.00, 1.00),
    "torino":            (1.00, 1.00, 1.00),
    "udinese":           (0.95, 0.95, 0.95),
    "genoa":             (0.90, 0.90, 0.90),
    "pisa":              (1.00, 1.00, 1.00),
    "empoli":            (0.95, 0.95, 0.95),
    "cagliari":          (0.90, 0.90, 0.90),
    "como":              (0.90, 0.90, 0.90),
    "lecce":             (0.85, 0.85, 0.85),
    "venezia":           (0.85, 0.85, 0.85),
    "monza":             (0.90, 0.90, 0.90),
    "verona":            (0.90, 0.90, 0.90),
    # Еврокубки — команды не из топ-5 лиг (ЛЕ/ЛК март 2026)
    "panathinaikos":     (1.05, 1.00, 0.98),
    "genk":              (1.05, 1.05, 1.00),
    "midtjylland":       (1.00, 1.00, 1.00),
    "ferencvaros":       (1.10, 1.05, 0.98),
    "lech":              (1.00, 1.00, 1.00),
    "shakhtar":          (1.05, 1.05, 1.00),
    "rijeka":            (0.98, 0.95, 1.02),
    "samsunspor":        (0.98, 1.00, 1.00),
    "aek larnaca":       (1.00, 1.00, 0.98),
    "sigma":             (1.00, 1.00, 1.00),
    "rakow":             (1.00, 1.00, 1.00),
    "celje":             (1.00, 0.95, 1.02),
    "aek":               (1.05, 1.00, 1.00),
    "sparta":            (1.10, 1.05, 1.00),
    # Бундеслига
    "bayer leverkusen":  (1.10, 1.10, 1.05),
    "bayern munich":     (1.10, 1.10, 1.05),
    "borussia dortmund": (1.00, 1.00, 1.00),
    "rb leipzig":        (1.05, 1.05, 1.00),
    "eintracht frankfurt":(1.00, 1.00, 1.00),
    "stuttgart":         (1.00, 1.00, 1.00),
    "freiburg":          (1.00, 1.00, 1.05),
    "wolfsburg":         (0.95, 0.95, 0.95),
    "hoffenheim":        (0.95, 0.95, 0.95),
    "union berlin":      (0.90, 0.90, 0.90),
    "augsburg":          (0.95, 0.95, 0.95),
    "mainz":             (1.00, 1.00, 1.00),
    "werder bremen":     (1.00, 1.00, 1.00),
    "heidenheim":        (0.95, 0.95, 0.95),
    "st. pauli":         (0.90, 0.85, 0.95),
    "kiel":              (0.80, 0.80, 0.80),
    # Лига 1
    "paris saint-germain": (1.15, 1.15, 1.10),
    "psg":               (1.15, 1.15, 1.10),
    "monaco":            (1.10, 1.10, 1.05),
    "marseille":         (1.05, 1.05, 1.00),
    "lyon":              (1.00, 1.00, 1.00),
    "lille":             (1.05, 1.00, 1.05),
    "nice":              (1.00, 1.00, 1.00),
    "lens":              (0.95, 0.95, 0.95),
    "brest":             (1.00, 1.00, 1.00),
    "rennes":            (0.95, 0.95, 0.95),
    "toulouse":          (0.95, 0.95, 0.95),
    "nantes":            (0.90, 0.90, 0.90),
    "reims":             (0.95, 0.95, 0.95),
    "saint-etienne":     (0.90, 0.90, 0.90),
    # Примейра
    "benfica":           (1.10, 1.10, 1.05),
    "sporting cp":       (1.10, 1.10, 1.05),
    "porto":             (1.05, 1.05, 1.00),
    "braga":             (1.00, 1.00, 1.00),
    # Эредивизи
    "psv":               (1.15, 1.15, 1.05),
    "ajax":              (1.05, 1.05, 1.00),
    "feyenoord":         (1.05, 1.05, 1.00),
    "az":                (1.00, 1.00, 1.00),
}

def _form_from_db(name: str) -> Optional[tuple]:
    """Берёт форму из статической базы FORM_DB."""
    key = name.lower().strip()
    for sfx in [" fc", " sc", " ac", " cf", " afc"]:
        key = key.replace(sfx, "").strip()
    # Точное совпадение
    if key in FORM_DB:
        return FORM_DB[key]
    # Частичное
    for db_key in FORM_DB:
        if db_key in key or key in db_key:
            return FORM_DB[db_key]
    return None

@dataclass
class TeamStats:
    name: str
    team_id: int
    avg_goals_scored: float
    avg_goals_conceded: float
    home_advantage: float  = 0.07
    form_rating:    float  = 1.0    # < 1.0 плохая форма, > 1.0 хорошая
    attack_trend:   float  = 1.0    # тренд атаки последних 5 матчей
    defense_trend:  float  = 1.0    # тренд обороны последних 5 матчей
    # Домашняя / выездная форма — отдельно (ключевое улучшение)
    home_form:      float  = 1.0    # форма только в домашних матчах
    away_form:      float  = 1.0    # форма только в выездных матчах
    home_gs:        float  = 0.0    # среднее голов дома (0 = не известно)
    away_gs:        float  = 0.0    # среднее голов в гостях
    home_gc:        float  = 0.0    # среднее пропущенных дома
    away_gc:        float  = 0.0    # среднее пропущенных в гостях

@dataclass
class Match:
    fixture_id: int
    home: TeamStats
    away: TeamStats
    league: str
    date: str
    time: str = ""
    bookmaker_odds: dict = field(default_factory=dict)
    data_quality: float = 0.50   # 0.35=TEAM_DB static, 0.50=AF/learned, 0.60=Understat xG

@dataclass
class Signal:
    match: str
    league: str
    date: str
    time: str
    market: str
    selection: str
    model_prob: float
    bookmaker_odds: float
    implied_prob: float
    edge: float
    kelly_stake: float
    confidence: str
    score: float = 0.0          # комплексный скор для ранжирования
    timestamp: str = field(
        default_factory=lambda: datetime.datetime.now().isoformat(timespec="seconds")
    )
def _enrich_teamstats(ts: TeamStats, name: str,
                      real_form: Optional[tuple] = None) -> TeamStats:
    """
    Обогащает TeamStats данными формы.
    real_form — приоритетные данные из API (форма_рейтинг, атк_тренд, деф_тренд).
    Если None — используем FORM_DB.
    """
    if real_form and len(real_form) == 3:
        if len(real_form) >= 4:
            ts.form_rating, ts.attack_trend, ts.defense_trend, streak_f = real_form
            ts._streak_factor = streak_f
        else:
            ts.form_rating, ts.attack_trend, ts.defense_trend = real_form[:3]
            ts._streak_factor = 1.0
    else:
        fr, at, dt, streak = _calc_form(name)
        ts.form_rating   = fr
        ts.attack_trend  = at * streak   # серия влияет на атаку
        ts.defense_trend = dt
    return ts

# ══════════════════════════════════════════════════════════════
#  🌐  HTTP — SSL фикс + авто-retry
# ══════════════════════════════════════════════════════════════
def _ssl():
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode    = ssl.CERT_NONE
    ctx.options |= ssl.OP_NO_SSLv2 if hasattr(ssl, "OP_NO_SSLv2") else 0
    ctx.options |= ssl.OP_NO_SSLv3 if hasattr(ssl, "OP_NO_SSLv3") else 0
    # Windows fix: игнорируем неожиданный EOF в TLS
    try: ctx.options |= ssl.OP_IGNORE_UNEXPECTED_EOF
    except AttributeError: pass
    return ctx

# ── HTTP через urllib3 напрямую (обход Windows SSL) ────────────
import urllib3, ssl as _ssl_mod, http.client, socket

# ── Главный фикс Windows SSL: OP_IGNORE_UNEXPECTED_EOF ─────────
# Эта опция появилась в Python 3.11.3 специально для данной ошибки.
# Говорит OpenSSL не падать когда сервер резко закрывает TLS сессию.
def _make_ssl_ctx():
    ctx = _ssl_mod.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode    = _ssl_mod.CERT_NONE
    # ключевая строка:
    if hasattr(_ssl_mod, "OP_IGNORE_UNEXPECTED_EOF"):
        ctx.options |= _ssl_mod.OP_IGNORE_UNEXPECTED_EOF
    ctx.set_ciphers("DEFAULT:@SECLEVEL=0")
    return ctx

# urllib3 с кастомным SSL-контекстом
urllib3.disable_warnings()
_pool = urllib3.PoolManager(
    num_pools=10,
    maxsize=5,
    retries=urllib3.Retry(
        total=3,
        backoff_factor=1.5,          # 0с → 1.5с → 3с
        status_forcelist={500, 502, 503, 504},
        allowed_methods={"GET"},
        raise_on_status=False,
    ),
    timeout=urllib3.Timeout(connect=20, read=40),
    ssl_context=_make_ssl_ctx(),
)

def _http(url: str, headers: dict = {}, timeout: int = 35, silent: bool = False):
    global _odds_api_remaining   # объявляем сразу — используется в нескольких местах функции
    hdrs = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/json",
        "Accept-Encoding": "gzip, deflate",
        "Connection": "keep-alive",
        **headers
    }
    last_err = None
    for attempt in range(4):
        try:
            r = _pool.request("GET", url, headers=hdrs, timeout=timeout)
            if r.status == 200:
                # Читаем остаток кредитов Odds API из заголовков
                if "the-odds-api.com" in url:
                    pass  # global уже объявлен выше
                    _rem = r.headers.get("X-Requests-Remaining")
                    if _rem is not None:
                        try:
                            _odds_api_remaining = int(_rem)
                        except (ValueError, TypeError):
                            pass
                raw = r.data
                try:
                    text = raw.decode("utf-8")
                except UnicodeDecodeError:
                    text = raw.decode("latin-1")
                if not text.strip():
                    return None
                try:
                    parsed = json.loads(text.strip())
                    # Odds API может вернуть 200 с error внутри (quota exhausted)
                    if isinstance(parsed, dict) and "error_code" in parsed:
                        ec = parsed.get("error_code","")
                        if "USAGE" in ec or "REQUEST" in ec or "QUOTA" in ec:
                            _odds_api_remaining = 0
                            return parsed   # вернём dict — обработается в fetch_odds_api
                    return parsed
                except json.JSONDecodeError:
                    return None
            if r.status == 429:
                wait = min(int(r.headers.get("Retry-After", 15)), 20)
                time.sleep(wait)
                continue
            if r.status in (401, 403, 422):
                if "the-odds-api.com" in url:
                    # Читаем body — OUT_OF_USAGE vs INVALID_KEY
                    try:
                        _body = json.loads(r.data.decode("utf-8","ignore"))
                        _ec   = _body.get("error_code","")
                        _msg  = _body.get("message","")
                    except Exception:
                        _ec, _msg = "", ""
                    if "USAGE" in _ec or "OUT_OF" in _ec or "quota" in _msg.lower() or "out of" in _msg.lower():
                        _odds_api_remaining = 0
                        return {"error_code": "OUT_OF_USAGE", "message": _msg}
                    # Реальный невалидный ключ
                    return None
                else:
                    if not silent:
                        print(f"  🔑 Ошибка авторизации ({r.status}) — проверь API ключ: {url[:60]}")
                    return None
            body = r.data.decode("utf-8", errors="ignore")[:120]
            print(f"  [HTTP {r.status}] {url[:60]}  {body}")
            return None
        except Exception as e:
            last_err = e
            err_str = str(e)
            # SSL/Connection ошибки — ждём и пробуем снова
            retryable = any(x in err_str for x in (
                "SSL", "TLS", "EOF", "ConnectionReset", "RemoteDisconnected",
                "timeout", "timed out", "ConnectTimeout", "ReadTimeout",
                "NewConnectionError", "MaxRetry"
            ))
            if retryable and attempt < 3:
                wait = 3 * (attempt + 1)  # 3, 6, 9 сек
                time.sleep(wait)
                continue
            break
    if last_err:
        err_s = str(last_err)
        # Не показываем JSON/decode ошибки — они не сетевые
        if not silent and "Expecting value" not in err_s and "JSONDecodeError" not in err_s:
            print(f"  [NET ERR] {err_s[:100]}")
    return None
# ══════════════════════════════════════════════════════════════
#  📡  API-FOOTBALL (прямой ключ)
# ══════════════════════════════════════════════════════════════
_af_quota_ok = True   # False если лимит исчерпан
_af_quota_rem = 100   # остаток дневной квоты
_AF_BUDGET_PER_MATCH = 3  # максимум AF запросов на матч
_AF_ECONOMY_MODE = False  # включается автоматически при quota < 20

# Rate limiter: не более 8 запросов в минуту (лимит 10 — оставляем запас)
_af_last_calls: list = []   # timestamps последних запросов
_AF_MAX_PER_MIN = 8         # безопасный лимит

def _af_rate_wait():
    """Ждёт если за последнюю минуту уже было 8+ запросов."""
    now = time.time()
    # Оставляем только запросы последней минуты
    _af_last_calls[:] = [t for t in _af_last_calls if now - t < 62]
    if len(_af_last_calls) >= _AF_MAX_PER_MIN:
        oldest  = _af_last_calls[0]
        wait    = 63 - (now - oldest)
        if wait > 0:
            time.sleep(wait)   # тихое ожидание лимита
        _af_last_calls[:] = [t for t in _af_last_calls if time.time() - t < 62]
    _af_last_calls.append(time.time())

def _af(endpoint: str, params: dict) -> Optional[dict]:
    global _af_quota_ok, _af_quota_rem

    # ── Проверяем дисковый кэш ПЕРЕД проверкой квоты ──────────
    # Кэшированные ответы не тратят квоту и работают даже при quota=False
    _cache_key = f"{endpoint}|{__import__('json').dumps(params, sort_keys=True)}"
    if _cache_key in _AF_DISK_CACHE:
        return _AF_DISK_CACHE[_cache_key]

    if not _af_quota_ok:
        return None
    global _AF_ECONOMY_MODE
    if _af_quota_rem <= 2:
        print("  ⛔ Квота AF исчерпана на сегодня")
        _af_quota_ok = False
        return None
    if _af_quota_rem <= 40 and not _AF_ECONOMY_MODE:
        _AF_ECONOMY_MODE = True
        print(f"  ⚠️  Режим экономии AF: осталось {_af_quota_rem} запросов")

    _af_rate_wait()   # ← соблюдаем 10 req/min
    _af_quota_rem = max(0, _af_quota_rem - 1)

    qs   = urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
    url  = f"https://v3.football.api-sports.io/{endpoint}?{qs}"
    data = _http(url, {"x-apisports-key": API_FOOTBALL_KEY})
    if not isinstance(data, dict):
        return data
    errs = data.get("errors", {})
    if isinstance(errs, dict) and errs:
        msg = str(list(errs.values())[0])
        # НЕ блокируем quota по ошибкам endpoint /status — там часто
        # приходят предупреждения в errors{} при валидных данных в response{}
        if endpoint == "status":
            pass   # статус читаем из response{}, ошибки игнорируем
        elif "request limit" in msg.lower() or "quota" in msg.lower():
            # Блокируем только если нет данных И quota уже <= 5
            # (AF часто шлёт quota warning в errors при нормальной работе)
            if _af_quota_rem <= 5:
                print(f"  ⛔ API-Football: квота исчерпана")
                _af_quota_ok = False
            else:
                # Quota warning но данные есть — продолжаем, обновим после статуса
                pass
        elif "rate" in msg.lower():
            time.sleep(65)
            _af_last_calls.clear()
            return _af(endpoint, params)
        elif "Free plans" not in msg and "season" not in msg.lower():
            pass   # не спамим мелкими предупреждениями
    return data

def _af_resp(endpoint: str, params: dict) -> list:
    data = _af(endpoint, params)
    if not isinstance(data, dict):
        return []
    return data.get("response", [])

# ══════════════════════════════════════════════════════════════
#  💾  DAILY CACHE — кэшируем AF запросы на 24ч (экономия квоты)
#  Файл: af_cache_YYYY-MM-DD.json
#  При повторном запуске в тот же день = читаем файл
# ══════════════════════════════════════════════════════════════
import hashlib as _hashlib

_AF_DISK_CACHE: dict = {}
_AF_DISK_CACHE_FILE = f"af_cache_{datetime.date.today().isoformat()}.json"

def _cleanup_old_caches():
    """Удаляем кэш-файлы старше 2 дней."""
    try:
        today = datetime.date.today()
        for f in os.listdir("."):
            if f.startswith("af_cache_") and f.endswith(".json"):
                try:
                    date_str = f[9:19]
                    file_date = datetime.date.fromisoformat(date_str)
                    if (today - file_date).days > 2:
                        os.remove(f)
                except Exception:
                    pass
    except Exception:
        pass

def _load_af_disk_cache():
    """Загружаем дневной кэш из файла при старте."""
    global _AF_DISK_CACHE
    try:
        if os.path.exists(_AF_DISK_CACHE_FILE):
            with open(_AF_DISK_CACHE_FILE, encoding="utf-8") as f:
                _AF_DISK_CACHE = json.load(f)
            print(f"  💾 Кэш AF загружен: {len(_AF_DISK_CACHE)} запросов из {_AF_DISK_CACHE_FILE}")
    except Exception:
        _AF_DISK_CACHE = {}

def _save_af_disk_cache():
    """Сохраняем кэш после каждого нового запроса."""
    try:
        with open(_AF_DISK_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(_AF_DISK_CACHE, f, ensure_ascii=False)
    except Exception:
        pass

def _af_cached(endpoint: str, params: dict) -> Optional[dict]:
    """
    Обёртка над _af() с дисковым кэшем.
    Одинаковые запросы в тот же день не тратят квоту.
    """
    key = f"{endpoint}|{json.dumps(params, sort_keys=True)}"
    if key in _AF_DISK_CACHE:
        return _AF_DISK_CACHE[key]
    result = _af(endpoint, params)
    if result is not None:
        _AF_DISK_CACHE[key] = result
        _save_af_disk_cache()
    return result

def _af_resp_cached(endpoint: str, params: dict) -> list:
    """_af_resp с кэшем."""
    data = _af_cached(endpoint, params)
    if not isinstance(data, dict):
        return []
    return data.get("response", [])




# ══════════════════════════════════════════════════════════════
#  📐  UNDERSTAT.COM — реальный xG (топ-6 лиг)
#  Бесплатно, без ключа. Самый точный источник xG в мире.
#  Лиги: EPL, La_liga, Bundesliga, Serie_A, Ligue_1, RFPL
# ══════════════════════════════════════════════════════════════
_understat_cache: dict = {}

# Маппинг league_id → название лиги в Understat
_UNDERSTAT_LEAGUES = {
    39:  "EPL",
    140: "La_liga",
    78:  "Bundesliga",
    135: "Serie_A",
    61:  "Ligue_1",
    235: "RFPL",        # Российская ПЛ
}

def _fetch_understat_league(league_name: str) -> dict:
    """
    Загружает xG всех команд лиги за текущий сезон с Understat.
    Возвращает dict: {"team_name": {"xg": 1.45, "xga": 1.12, "matches": 20}}
    """
    cache_key = f"us_{league_name}"
    if cache_key in _understat_cache:
        return _understat_cache[cache_key]

    year = datetime.date.today().year
    # Understat использует год начала сезона
    if datetime.date.today().month < 7:
        year -= 1

    url  = f"https://understat.com/league/{league_name}/{year}"
    html = _http_raw(url)
    if not html:
        return {}

    # Данные Understat зашиты в JS переменную teamsData
    import re
    m = re.search(r"teamsData\s*=\s*JSON\.parse\('(.+?)'\)", html)
    if not m:
        _understat_cache[cache_key] = {}
        return {}

    try:
        raw   = m.group(1).encode().decode("unicode_escape")
        teams = json.loads(raw)
    except Exception:
        return {}

    result = {}
    for tid, tdata in teams.items():
        name  = tdata.get("title", "").lower().strip()
        hist  = tdata.get("history", [])
        if not hist:
            continue
        # Последние 6 матчей для формы
        recent = hist[-6:]
        xg_list  = [float(m.get("xG", 0))  for m in recent]
        xga_list = [float(m.get("xGA", 0)) for m in recent]
        # Сезонные данные
        all_xg  = sum(float(m.get("xG",  0)) for m in hist)
        all_xga = sum(float(m.get("xGA", 0)) for m in hist)
        n = len(hist)
        result[name] = {
            "xg_per_game":   round(all_xg  / n, 3) if n else 1.3,
            "xga_per_game":  round(all_xga / n, 3) if n else 1.3,
            "recent_xg":     round(sum(xg_list)  / len(xg_list),  3) if xg_list  else 1.3,
            "recent_xga":    round(sum(xga_list) / len(xga_list), 3) if xga_list else 1.3,
            "matches":       n,
            # Тренд: последние 3 vs предыдущие 3
            "xg_trend":      round(sum(xg_list[-3:]) / 3 / max(sum(xg_list[:3]) / 3, 0.1), 3)
                             if len(xg_list) >= 4 else 1.0,
        }
    _understat_cache[cache_key] = result
    print(f"   📐 Understat [{league_name}]: {len(result)} команд загружено")
    return result

def _http_raw(url: str) -> str:
    """Загружает HTML страницу как текст."""
    hdrs = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) "
                      "Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "en-US,en;q=0.9",
    }
    try:
        r = _pool.request("GET", url, headers=hdrs, timeout=20)
        if r.status == 200:
            return r.data.decode("utf-8", errors="ignore")
    except Exception as e:
        print(f"  [HTTP_RAW] {str(e)[:80]}")
    return ""

def fetch_understat_team(team_name: str, league_id: int) -> Optional[dict]:
    """
    Ищет команду в Understat по названию.
    Возвращает xG данные или None если лига не поддерживается.
    """
    league_name = _UNDERSTAT_LEAGUES.get(league_id)
    if not league_name:
        return None

    data = _fetch_understat_league(league_name)
    if not data:
        return None

    # Нормализуем имя для поиска
    def _norm(s):
        return s.lower().strip().replace("-", " ").replace(".", "")

    name_norm = _norm(team_name)
    # Убираем стандартные суффиксы
    for sfx in [" fc", " afc", " sc", " cf", " united", " city", " town"]:
        name_norm = name_norm.replace(sfx, "").strip()

    # Точное совпадение
    for db_name, vals in data.items():
        db_norm = _norm(db_name)
        for sfx in [" fc", " afc", " sc", " cf", " united", " city", " town"]:
            db_norm = db_norm.replace(sfx, "").strip()
        if name_norm == db_norm:
            return vals

    # Частичное — хотя бы 1 значимое слово
    name_words = set(name_norm.split()) - {"the", "de", "fc", "sc"}
    best_score, best_val = 0, None
    for db_name, vals in data.items():
        db_norm  = _norm(db_name)
        db_words = set(db_norm.split()) - {"the", "de", "fc", "sc"}
        score    = len(name_words & db_words)
        if score > best_score:
            best_score, best_val = score, vals

    return best_val if best_score >= 1 else None


# ══════════════════════════════════════════════════════════════
#  🦅  SOFASCORE — травмы и форма команд (бесплатно, без ключа)
#  Покрывает 1000+ лиг включая ЛЧ, ЛЕ, все национальные
# ══════════════════════════════════════════════════════════════
_sofa_cache: dict = {}
_SOFA_HEADERS = {
    "User-Agent":  "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                   "AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
    "Accept":      "application/json",
    "Referer":     "https://www.sofascore.com/",
    "Origin":      "https://www.sofascore.com",
    "Cache-Control": "no-cache",
}

_sofa_blocked: bool = False   # True если SofaScore блокирует нас

def _sofa(path: str) -> Optional[dict]:
    """SofaScore неофициальный API — быстрый таймаут, 2 попытки."""
    global _sofa_blocked
    if _sofa_blocked:
        return None
    # Пробуем 2 агента — быстро, без лишних задержек
    _AGENTS = [
        "SofaScore/70 CFNetwork/1492.0.1 Darwin/23.3.0",
        "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15",
    ]
    for agent in _AGENTS:
        url = f"https://api.sofascore.com/api/v1{path}"
        try:
            r = _pool.request("GET", url, headers={
                "User-Agent": agent,
                "Referer": "https://www.sofascore.com/",
                "Accept": "application/json",
            }, timeout=6)   # 6 сек максимум — раньше 15
            if r.status == 200:
                return json.loads(r.data.decode("utf-8"))
            if r.status == 403:
                time.sleep(0.5)   # раньше 1.5 сек
                continue
            if r.status in (429, 503):
                _sofa_blocked = True
                return None
        except Exception:
            pass
    return None

def fetch_sofa_event_id(home: str, away: str, date_str: str) -> Optional[int]:
    """
    Ищет event_id матча в SofaScore по именам команд и дате.
    Event_id нужен для получения деталей матча.
    """
    # Пробуем через поиск событий по дате
    # Пробуем текущую дату и ±1 день
    import datetime as _dt3
    data = None
    try:
        target_dt = _dt3.date.fromisoformat(date_str)
        for delta in [0, 1, -1]:
            d_try = (target_dt + _dt3.timedelta(days=delta)).isoformat()
            data = _sofa(f"/sport/football/scheduled-events/{d_try}")
            if data and data.get("events"):
                break
    except Exception:
        data = _sofa(f"/sport/football/scheduled-events/{date_str}")
    if not data:
        return None
    events = data.get("events", [])

    def _norm(s):
        return s.lower().strip().replace("-"," ").replace("."," ")

    h_norm = _norm(home)
    a_norm = _norm(away)
    h_words = set(h_norm.split()) - {"fc","sc","cf","afc","the"}
    a_words = set(a_norm.split()) - {"fc","sc","cf","afc","the"}

    for ev in events:
        th = _norm(ev.get("homeTeam", {}).get("name", ""))
        ta = _norm(ev.get("awayTeam", {}).get("name", ""))
        th_words = set(th.split()) - {"fc","sc","cf","afc","the"}
        ta_words = set(ta.split()) - {"fc","sc","cf","afc","the"}
        score = len(h_words & th_words) + len(a_words & ta_words)
        if score >= 2:
            return ev.get("id")
    return None

def fetch_sofa_injuries(home: str, away: str, date_str: str) -> tuple[float, float]:
    """
    Возвращает (injury_factor_home, injury_factor_away).
    1.0 = все здоровы, 0.80 = серьёзные потери.
    Не тратит квоту API-Football.
    """
    cache_key = f"sofa_inj_{home}_{away}_{date_str}"
    if cache_key in _sofa_cache:
        return _sofa_cache[cache_key]

    event_id = fetch_sofa_event_id(home, away, date_str)
    if not event_id:
        return 1.0, 1.0

    data = _sofa(f"/event/{event_id}/lineups")
    if not data:
        return 1.0, 1.0

    _ROLE_IMPACT = {
        "G": 0.05,   # вратарь
        "D": 0.04,   # защитник
        "M": 0.06,   # полузащитник
        "F": 0.09,   # нападающий
    }

    def _calc_penalty(players: list) -> float:
        pen = 1.0
        for p in players:
            if p.get("missedEventReason") in (
                "injured", "suspended", "illness", "doubtful"
            ):
                pos = p.get("position", "M")
                pen = max(0.72, pen - _ROLE_IMPACT.get(pos, 0.05))
        return round(pen, 3)

    home_players = data.get("home", {}).get("missingPlayers", [])
    away_players = data.get("away", {}).get("missingPlayers", [])
    h_pen = _calc_penalty(home_players)
    a_pen = _calc_penalty(away_players)

    result = (h_pen, a_pen)
    _sofa_cache[cache_key] = result
    return result

def fetch_sofa_form(home: str, away: str, date_str: str) -> tuple[Optional[tuple], Optional[tuple]]:
    """
    Возвращает (form_home, form_away) из последних матчей SofaScore.
    Каждый элемент — (form_rating, attack_trend, defense_trend) или None.
    """
    event_id = fetch_sofa_event_id(home, away, date_str)
    if not event_id:
        return None, None

    results = []
    for side, team_name in [("home", home), ("away", away)]:
        data = _sofa(f"/event/{event_id}/h2h")
        # Берём последние матчи команды из секции teamDuel
        matches = []
        if data:
            for ev in data.get("previousEvents", [])[:6]:
                try:
                    ht = ev.get("homeTeam", {}).get("name","").lower()
                    at = ev.get("awayTeam", {}).get("name","").lower()
                    hs = ev.get("homeScore", {}).get("current", 0)
                    as_ = ev.get("awayScore", {}).get("current", 0)
                    name_l = team_name.lower()
                    if name_l in ht:
                        gf, ga = hs, as_
                    elif name_l in at:
                        gf, ga = as_, hs
                    else:
                        continue
                    if gf > ga:   res = 1.0
                    elif gf == ga: res = 0.5
                    else:          res = 0.0
                    matches.append((res, gf, ga))
                except Exception:
                    continue

        if len(matches) >= 3:
            r_list = [m[0] for m in matches]
            g_list = [m[1] for m in matches]
            c_list = [m[2] for m in matches]
            avg_r  = sum(r_list) / len(r_list)
            fr     = max(0.70, min(1.40, 0.70 + avg_r * 1.40))
            if len(g_list) >= 4:
                atk = max(0.80, min(1.25, 1.0 + (sum(g_list[-2:])/2 - sum(g_list[:-2])/max(len(g_list)-2,1)) * 0.15))
                dft = max(0.80, min(1.25, 1.0 - (sum(c_list[-2:])/2 - sum(c_list[:-2])/max(len(c_list)-2,1)) * 0.15))
            else:
                atk, dft = 1.0, 1.0
            results.append((round(fr,3), round(atk,3), round(dft,3)))
        else:
            results.append(None)

    return results[0] if len(results) > 0 else None, results[1] if len(results) > 1 else None


# ══════════════════════════════════════════════════════════════
#  ⚔️  H2H — ИСТОРИЯ ЛИЧНЫХ ВСТРЕЧ
# ══════════════════════════════════════════════════════════════
_h2h_cache: dict = {}

def fetch_h2h(home_id: int, away_id: int, home_name: str, away_name: str) -> dict:
    """
    Берёт последние 8 личных встреч команд.
    Возвращает: {
      "h2h_home_win_rate": 0.625,   # % побед хозяина в личных встречах
      "h2h_avg_total": 2.4,          # среднее голов в личных встречах
      "h2h_btts_rate": 0.5,          # % матчей обе забили
      "h2h_factor": 1.08,            # корректировка xG для расчёта
      "matches": 8,                  # сколько матчей нашли
      "note": "Атлетик побеждает в 7/8 личных встреч"  # текст для Telegram
    }
    """
    cache_key = f"h2h_{home_id}_{away_id}"
    if cache_key in _h2h_cache:
        return _h2h_cache[cache_key]

    result = {
        "h2h_home_win_rate": 0.5, "h2h_avg_total": 2.6,
        "h2h_btts_rate": 0.5, "h2h_factor": 1.0,
        "matches": 0, "note": ""
    }

    if not _af_quota_ok or not home_id or not away_id:
        return result

    resp = _af_resp("fixtures/headtohead", {
        "h2h": f"{home_id}-{away_id}", "last": 8
    })
    if not resp or not isinstance(resp, list):
        _h2h_cache[cache_key] = result
        return result

    h_wins = 0; a_wins = 0; draws = 0
    totals = []; btts = 0; played = 0

    for fix in resp:
        try:
            st = fix.get("fixture", {}).get("status", {}).get("short", "")
            if st not in ("FT","AET","PEN"):
                continue
            goals  = fix.get("goals", {})
            teams  = fix.get("teams", {})
            hg = int(goals.get("home") or 0)
            ag = int(goals.get("away") or 0)
            # Кто был хозяином в той встрече
            this_home_id = teams.get("home", {}).get("id")

            # Переводим к текущему распределению: home_id играет как хозяин сейчас
            if this_home_id == home_id:
                cur_hg, cur_ag = hg, ag
            else:
                cur_hg, cur_ag = ag, hg

            if cur_hg > cur_ag:   h_wins += 1
            elif cur_ag > cur_hg: a_wins += 1
            else:                 draws  += 1

            totals.append(cur_hg + cur_ag)
            if cur_hg > 0 and cur_ag > 0:
                btts += 1
            played += 1
        except Exception:
            continue

    if played < 2:
        _h2h_cache[cache_key] = result
        return result

    h_wr   = h_wins / played
    avg_t  = sum(totals) / len(totals) if totals else 2.6
    btts_r = btts / played

    # H2H фактор: насколько хозяин доминирует/проигрывает исторически
    # Нейтральный = 0.5 побед (1.0 фактор)
    # Доминирует  = 0.75+ побед → фактор 1.10 (на 10% увеличиваем его xG)
    # Проигрывает = 0.25- побед → фактор 0.90
    h2h_factor = max(0.88, min(1.12, 1.0 + (h_wr - 0.5) * 0.40))

    # Формируем читаемый комментарий
    if h_wins > a_wins and h_wins >= played * 0.6:
        note = f"⚔️ H2H: {home_name} выиграл {h_wins}/{played} личных встреч"
    elif a_wins > h_wins and a_wins >= played * 0.6:
        note = f"⚔️ H2H: {away_name} выиграл {a_wins}/{played} личных встреч"
    elif avg_t >= 3.2:
        note = f"⚔️ H2H: результативные встречи, ср.тотал {avg_t:.1f}"
    elif avg_t <= 1.8:
        note = f"⚔️ H2H: низкий тотал в личных встречах ({avg_t:.1f})"
    else:
        note = ""

    result = {
        "h2h_home_win_rate": round(h_wr, 3),
        "h2h_avg_total":     round(avg_t, 2),
        "h2h_btts_rate":     round(btts_r, 3),
        "h2h_factor":        round(h2h_factor, 3),
        "matches":           played,
        "note":              note,
    }
    _h2h_cache[cache_key] = result
    return result


# ══════════════════════════════════════════════════════════════
#  🥇  ПЕРВАЯ НОГА ПЛЕЙ-ОФФ — контекст для 2-й ноги
# ══════════════════════════════════════════════════════════════
_first_leg_cache: dict = {}

def fetch_first_leg(home_id: int, away_id: int,
                    league_id: int, match_date: str) -> dict:
    """
    Ищет результат первой ноги плей-офф для текущей пары.
    Логика: последний завершённый матч этих команд в текущем сезоне
    в той же лиге (ЛЧ/ЛЕ/ЛК) ДО даты текущего матча.

    Возвращает dict:
      is_second_leg   : bool   — это 2-я нога?
      home_score_1    : int    — голы хозяина 1-й ноги (тогда гость)
      away_score_1    : int    — голы гостя 1-й ноги (тогда хозяин)
      agg_home        : int    — агрегат текущего хозяина
      agg_away        : int    — агрегат текущего гостя
      context         : str    — «ведут», «отстают», «равно»
      pressure_h      : float  — коэф давления для xG хозяев (0.85–1.20)
      pressure_a      : float  — коэф давления для xG гостей
      note            : str    — текст для Telegram
    """
    _NULL = {"is_second_leg": False, "note": ""}
    if league_id not in (2, 3, 848):
        return _NULL

    cache_key = f"fl_{home_id}_{away_id}_{league_id}"
    if cache_key in _first_leg_cache:
        return _first_leg_cache[cache_key]

    if not _af_quota_ok or not home_id or not away_id:
        _first_leg_cache[cache_key] = _NULL
        return _NULL

    try:
        resp = _af_resp("fixtures/headtohead", {
            "h2h": f"{home_id}-{away_id}",
            "league": league_id,
            "season": CURRENT_SEASON,
            "last": 4,
            "status": "FT-AET-PEN",
        })
        if not resp or not isinstance(resp, list):
            _first_leg_cache[cache_key] = _NULL
            return _NULL

        # Ищем матч ДО текущей даты — это первая нога
        first_leg_fix = None
        for fix in resp:
            st  = fix.get("fixture", {}).get("status", {}).get("short", "")
            if st not in ("FT", "AET", "PEN"):
                continue
            fdate = fix.get("fixture", {}).get("date", "")[:10]
            if fdate >= match_date:
                continue   # это или текущий матч или будущий
            first_leg_fix = fix
            break   # берём самый свежий перед текущей датой

        if not first_leg_fix:
            _first_leg_cache[cache_key] = _NULL
            return _NULL

        goals  = first_leg_fix.get("goals", {})
        teams  = first_leg_fix.get("teams", {})
        hg1    = int(goals.get("home") or 0)
        ag1    = int(goals.get("away") or 0)
        leg1_home_id = teams.get("home", {}).get("id")

        # Переводим голы к текущему распределению команд
        if leg1_home_id == home_id:
            # В 1-й ноге текущий хозяин был ДОМА → он забил hg1
            agg_h = hg1   # голы текущего хозяина в 1-й ноге
            agg_a = ag1   # голы текущего гостя в 1-й ноге
            leg1_str = f"{hg1}:{ag1}"
        else:
            # В 1-й ноге текущий хозяин был В ГОСТЯХ → он забил ag1
            agg_h = ag1
            agg_a = hg1
            leg1_str = f"{ag1}:{hg1}"   # с точки зрения текущего хозяина

        # Агрегатный контекст (после 1-й ноги, 2-я нога = 0:0 пока)
        diff = agg_h - agg_a   # положительный = хозяин ведёт по агрегату

        # ── Коэффициенты давления ──────────────────────────────────
        # Команда, которая ОТСТАЁТ → атакует активнее (+xG атаки)
        # Команда, которая ВЕДЁТ  → может позволить играть осторожнее (-xG атаки)
        # Но при этом открывается сзади → (+xG соперника)
        if diff > 1:
            # Хозяин ведёт на 2+ гола — может играть от счёта
            pressure_h = 0.90   # хозяин чуть осторожнее
            pressure_a = 1.18   # гость ОБЯЗАН атаковать
            context    = f"хозяева ведут {agg_h}:{agg_a} по агрегату"
        elif diff == 1:
            # Хозяин ведёт на 1 гол — любой гол гостя выравнивает
            pressure_h = 0.93
            pressure_a = 1.12
            context    = f"хозяева ведут {agg_h}:{agg_a} (1 гол преимущества)"
        elif diff == 0:
            # Равно — решают голы в этом матче (или буллиты)
            pressure_h = 1.05   # оба немного активнее обычного
            pressure_a = 1.05
            context    = f"агрегат равный {agg_h}:{agg_a}"
        elif diff == -1:
            # Хозяин отстаёт на 1 гол — ОБЯЗАН атаковать
            pressure_h = 1.15
            pressure_a = 0.92
            context    = f"хозяева отстают {agg_h}:{agg_a} (нужен гол)"
        else:
            # Хозяин отстаёт на 2+ — нужен камбэк
            pressure_h = 1.22
            pressure_a = 0.88
            context    = f"хозяева отстают {agg_h}:{agg_a} (нужен камбэк)"

        # ── Telegram-нота ─────────────────────────────────────────
        emoji = "⚖️" if diff == 0 else ("🔝" if diff > 0 else "🔻")
        note = (
            f"{emoji} 2-я нога | 1-я нога: {leg1_str} | "
            f"Агрегат {agg_h}:{agg_a} — {context}"
        )

        result = {
            "is_second_leg": True,
            "home_score_1":  agg_h,
            "away_score_1":  agg_a,
            "agg_home":      agg_h,
            "agg_away":      agg_a,
            "diff":          diff,
            "context":       context,
            "pressure_h":    pressure_h,
            "pressure_a":    pressure_a,
            "leg1_str":      leg1_str,
            "note":          note,
        }
        _first_leg_cache[cache_key] = result
        return result

    except Exception:
        _first_leg_cache[cache_key] = _NULL
        return _NULL



# ══════════════════════════════════════════════════════════════
#  🏠🚌  ДОМАШНЯЯ / ВЫЕЗДНАЯ ФОРМА
# ══════════════════════════════════════════════════════════════
_venue_cache: dict = {}

def fetch_venue_form(team_id: int, team_name: str,
                     league_id: int, is_home: bool) -> dict:
    """
    Отдельная форма команды дома и в гостях за последние 8 матчей.
    Возвращает: {
      "venue_form":  1.12,   # форм-рейтинг на конкретном поле
      "venue_gs":    1.85,   # средние голы в этом контексте
      "venue_gc":    0.92,   # средние пропущенные
    }
    """
    venue = "home" if is_home else "away"
    cache_key = f"venue_{team_id}_{league_id}_{venue}"
    if cache_key in _venue_cache:
        return _venue_cache[cache_key]

    default = {"venue_form": 1.0, "venue_gs": 0.0, "venue_gc": 0.0}

    if not _af_quota_ok or not team_id:
        return default

    resp = _af_resp_cached("fixtures", {
        "team": team_id, "last": 10, "league": league_id,
        "season": CURRENT_SEASON, "venue": venue
    })
    if not resp:
        resp = _af_resp("fixtures", {
            "team": team_id, "last": 8, "league": league_id,
            "season": FALLBACK_SEASON, "venue": venue
        })
    if not resp or not isinstance(resp, list):
        _venue_cache[cache_key] = default
        return default

    results = []; gf_list = []; ga_list = []

    for fix in resp[-8:]:
        try:
            st = fix.get("fixture", {}).get("status", {}).get("short", "")
            if st not in ("FT","AET","PEN"):
                continue
            goals = fix.get("goals", {})
            teams = fix.get("teams", {})
            this_home_id = teams.get("home", {}).get("id")
            hg = int(goals.get("home") or 0)
            ag = int(goals.get("away") or 0)
            if this_home_id == team_id:
                gf, ga = hg, ag
            else:
                gf, ga = ag, hg

            if gf > ga:   results.append(1.0)
            elif gf == ga: results.append(0.5)
            else:          results.append(0.0)
            gf_list.append(gf); ga_list.append(ga)
        except Exception:
            continue

    if len(results) < 3:
        _venue_cache[cache_key] = default
        return default

    avg_res  = sum(results) / len(results)
    v_form   = max(0.70, min(1.40, 0.70 + avg_res * 1.40))
    v_gs     = round(sum(gf_list) / len(gf_list), 3) if gf_list else 0.0
    v_gc     = round(sum(ga_list) / len(ga_list), 3) if ga_list else 0.0

    res = {"venue_form": round(v_form, 3), "venue_gs": v_gs, "venue_gc": v_gc}
    _venue_cache[cache_key] = res
    return res


# ══════════════════════════════════════════════════════════════
#  📌  PINNACLE DIRECT API — прямое подключение
#  Самые острые линии в мире, без маржи как эталон
# ══════════════════════════════════════════════════════════════
_pin_cache: dict = {}
_PIN_BASE  = "https://api.ps3838.com"
_PIN_MIRRORS = ["https://api.ps3838.com", "https://api.pinnacle.com", "https://api.pinnaclesports.com"]
_PIN_SPORT = 29   # Football / Soccer

def _pin_headers() -> dict:
    import base64
    creds = base64.b64encode(
        f"{PINNACLE_USER}:{PINNACLE_PASS}".encode()
    ).decode()
    return {
        "Authorization": f"Basic {creds}",
        "Accept":        "application/json",
        "Content-Type":  "application/json",
    }

def _pin(path: str, params: dict = None):
    """Pinnacle API с автоперебором зеркал."""
    cache_key = f"pin_{path}_{params}"
    if cache_key in _pin_cache:
        return _pin_cache[cache_key]
    global _PIN_BASE
    qs = ("?" + urllib.parse.urlencode(params)) if params else ""
    mirrors = list(_PIN_MIRRORS)
    if _PIN_BASE in mirrors:
        mirrors = [_PIN_BASE] + [m for m in mirrors if m != _PIN_BASE]
    for mirror in mirrors:
        try:
            url = f"{mirror}{path}{qs}"
            r = _pool.request("GET", url, headers=_pin_headers(),
                              timeout=urllib3.Timeout(connect=8, read=20))
            if r.status == 200:
                try:
                    data = json.loads(r.data.decode("utf-8"))
                except json.JSONDecodeError:
                    continue
                _pin_cache[cache_key] = data
                if _PIN_BASE != mirror:
                    _PIN_BASE = mirror
                return data
            elif r.status in (401, 403):
                # Ошибка авторизации - зеркала не помогут
                return None
        except Exception:
            pass
    return None


def fetch_pinnacle_odds(home: str, away: str, date_str: str) -> dict:
    """
    Берёт линию Pinnacle напрямую.
    Возвращает {1: odds, X: odds, 2: odds, over_2.5: odds, ...}
    Используется как ЭТАЛОН для расчёта Валуя.
    """
    cache_key = f"pin_odds_{home}_{away}_{date_str}"
    if cache_key in _pin_cache:
        return _pin_cache[cache_key]

    # 1. Получаем список лиг Pinnacle для футбола
    leagues = _pin("/v1/leagues", {"sportId": _PIN_SPORT})
    if not leagues:
        return {}

    # 2. Ищем матч в ближайших событиях
    # Используем фикстуры сегодня/завтра
    fixtures = _pin("/v1/fixtures", {
        "sportId": _PIN_SPORT,
        "since":   0,
    })
    if not fixtures:
        return {}

    def _norm(s):
        return s.lower().strip().replace("-"," ").replace("."," ")

    h_norm = _norm(home)
    a_norm = _norm(away)
    h_words = set(h_norm.split()) - {"fc","sc","cf","the","de","afc"}
    a_words = set(a_norm.split()) - {"fc","sc","cf","the","de","afc"}

    event_id = None
    league_id = None
    for league in fixtures.get("league", []):
        for ev in league.get("events", []):
            # Проверяем дату
            ev_date = ev.get("starts", "")[:10]
            if ev_date != date_str:
                continue
            th = _norm(ev.get("home", ""))
            ta = _norm(ev.get("away", ""))
            th_words = set(th.split()) - {"fc","sc","cf","the","de"}
            ta_words = set(ta.split()) - {"fc","sc","cf","the","de"}
            score = len(h_words & th_words) + len(a_words & ta_words)
            if score >= 2:
                event_id  = ev.get("id")
                league_id = league.get("id")
                break
        if event_id:
            break

    if not event_id:
        _pin_cache[cache_key] = {}
        return {}

    # 3. Берём коэффициенты матча
    odds_data = _pin("/v1/odds", {
        "sportId":  _PIN_SPORT,
        "leagueIds": league_id,
        "eventIds":  event_id,
        "oddsFormat": "Decimal",
    })
    if not odds_data:
        _pin_cache[cache_key] = {}
        return {}

    result = {}
    for league in odds_data.get("leagues", []):
        for ev in league.get("matchups", []):
            if ev.get("id") != event_id:
                continue
            for period in ev.get("periods", []):
                if period.get("number") != 0:  # 0 = full match
                    continue
                # 1X2
                ml = period.get("moneyline", {})
                if ml:
                    result["1"] = round(float(ml.get("home", 0) or 0), 3)
                    result["X"] = round(float(ml.get("draw", 0) or 0), 3)
                    result["2"] = round(float(ml.get("away", 0) or 0), 3)
                # Тотал
                for tot in period.get("totals", []):
                    pts = tot.get("points", 0)
                    ov  = tot.get("over",  0)
                    un  = tot.get("under", 0)
                    if ov: result[f"over_{pts}"]  = round(float(ov), 3)
                    if un: result[f"under_{pts}"] = round(float(un), 3)
                # Азиатский гандикап → европейский
                for hc in period.get("spreads", []):
                    hdp = hc.get("hdp", 0)
                    if hdp and abs(float(hdp)) <= 1.5:
                        result[f"hcap_{hdp}_home"] = round(float(hc.get("home", 0) or 0), 3)
                        result[f"hcap_{hdp}_away"] = round(float(hc.get("away", 0) or 0), 3)

    if result:
        print(f"      📌 Pinnacle прямой: {len(result)} рынков")

    _pin_cache[cache_key] = result
    return result


# ════════════════════════════════════════════════════════════
#  🎯  PINNACLE GUEST API — без депозита, без авторизации
#  guest.api.arcadia.pinnacle.com — публичный эндпоинт
#  Это официальная линия Pinnacle (та же что на сайте).
#  Используют OddsPortal, BetBrain, Betegy и все odds trackers.
#  Лимиты: ~1 запрос в 3 сек, кэш обязателен.
# ════════════════════════════════════════════════════════════
_PIN_GUEST_BASE   = "https://guest.api.arcadia.pinnacle.com"
_PIN_GUEST_CACHE: dict = {}
_PIN_GUEST_TS:    float = 0.0
_PIN_GUEST_SPORT  = 29   # Soccer

def _pin_guest(path: str, params: dict = None) -> Optional[dict]:
    """
    Запрос к публичному Pinnacle Guest API.
    Не требует авторизации — доступен всем без аккаунта.
    Rate limit: не более 1 запроса в 3 сек.
    """
    ck = f"pg_{path}_{params}"
    if ck in _PIN_GUEST_CACHE:
        cached = _PIN_GUEST_CACHE[ck]
        if time.time() - cached[0] < 120:   # кэш 2 минуты
            return cached[1]
    global _PIN_GUEST_TS
    gap = time.time() - _PIN_GUEST_TS
    if gap < 3.0:
        time.sleep(3.0 - gap)
    _PIN_GUEST_TS = time.time()

    qs = ("?" + urllib.parse.urlencode(params)) if params else ""
    url = f"{_PIN_GUEST_BASE}{path}{qs}"
    headers = {
        "User-Agent":  "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept":      "application/json",
        "Origin":      "https://www.pinnacle.com",
        "Referer":     "https://www.pinnacle.com/",
        "x-api-key":   "CmX2KcMrXuFmNg6YFbmTxE0y9CIrOi0R",
    }
    try:
        r = _pool.request("GET", url, headers=headers,
                          timeout=urllib3.Timeout(connect=10, read=20))
        if r.status == 200:
            data = json.loads(r.data.decode("utf-8"))
            _PIN_GUEST_CACHE[ck] = (time.time(), data)
            return data
        elif r.status == 429:
            time.sleep(6)
        return None
    except Exception:
        return None


def fetch_pinnacle_guest_odds(home: str, away: str, date_str: str) -> dict:
    """
    Получает реальную линию Pinnacle через публичный Guest API.
    БЕЗ депозита, БЕЗ аккаунта — работает сразу.
    Возвращает {"1": 2.10, "X": 3.40, "2": 3.20, "over_2.5": 1.85, ...}
    + флаг "_source_pinnacle": True для emit()
    """
    ck = f"pg_odds_{home}_{away}_{date_str}"
    if ck in _PIN_GUEST_CACHE:
        cached = _PIN_GUEST_CACHE[ck]
        if time.time() - cached[0] < 120:
            return cached[1]

    # Алиасы: сокращённое имя → официальное для поиска в Pinnacle/SofaScore
    _ALIASES = {
        "man united":"manchester united","man utd":"manchester united",
        "man city":"manchester city","man u":"manchester united",
        "spurs":"tottenham","wolves":"wolverhampton",
        "wolverhampton wanderers":"wolverhampton","nott'm forest":"nottingham forest",
        "brighton & hove albion":"brighton","brighton hove albion":"brighton",
        "newcastle united":"newcastle","west ham united":"west ham",
        "afc bournemouth":"bournemouth","leicester city":"leicester",
        "atletico madrid":"atletico","atletico de madrid":"atletico",
        "real madrid cf":"real madrid","fc barcelona":"barcelona",
        "borussia dortmund":"dortmund","bayer leverkusen":"leverkusen",
        "rb leipzig":"leipzig","paris saint germain":"psg","paris sg":"psg",
        "inter milan":"inter","ac milan":"milan","as roma":"roma",
    }
    def _norm(s):
        s2 = s.lower().strip().replace("-"," ").replace("."," ")
        return _ALIASES.get(s2, s2)

    h_n = _norm(home); a_n = _norm(away)
    STOP_WORDS = {"fc","sc","cf","the","de","afc","hfc","1","0","united","city",
                   "real","athletic","sporting","dynamo","dinamo"}
    h_w = set(h_n.split()) - STOP_WORDS
    a_w = set(a_n.split()) - STOP_WORDS
    # Добавляем только длинные слова (4+ символа) как ключевые
    h_key = {w for w in h_w if len(w) >= 4}
    a_key = {w for w in a_w if len(w) >= 4}

    # 1. Загружаем события футбола
    matchups = _pin_guest(f"/0.1/sports/{_PIN_GUEST_SPORT}/matchups",
                          {"withSpecials": "false", "brandId": "0"})
    if not matchups or not isinstance(matchups, list):
        return {}

    event_id = None
    best_score = 0
    best_ev_id = None

    for ev in matchups:
        # Ищем в диапазоне ±1 день (время могло отличаться)
        ev_dt = ev.get("startTime", "")[:10]
        import datetime as _dt2
        try:
            ev_date = _dt2.date.fromisoformat(ev_dt)
            target  = _dt2.date.fromisoformat(date_str)
            if abs((ev_date - target).days) > 1:
                continue
        except Exception:
            if ev_dt != date_str:
                continue

        p = ev.get("participants", [])
        if len(p) < 2:
            continue
        h_ev = _norm(p[0].get("name", ""))
        a_ev = _norm(p[1].get("name", ""))
        h_ew = set(h_ev.split()) - STOP_WORDS
        a_ew = set(a_ev.split()) - STOP_WORDS
        h_ek = {w for w in h_ew if len(w) >= 4}
        a_ek = {w for w in a_ew if len(w) >= 4}

        # Мягкое совпадение: ищем подстроку тоже
        def _fuzzy(w_set, text):
            return any(w in text or text.startswith(w[:4]) for w in w_set)

        h_match = (len(h_key & h_ek) > 0) or (h_key and _fuzzy(h_key, h_ev)) or                   (h_n in h_ev or h_ev in h_n)
        a_match = (len(a_key & a_ek) > 0) or (a_key and _fuzzy(a_key, a_ev)) or                   (a_n in a_ev or a_ev in a_n)

        score = (2 if len(h_key & h_ek) > 0 else (1 if h_match else 0)) +                 (2 if len(a_key & a_ek) > 0 else (1 if a_match else 0))

        if score > best_score:
            best_score = score
            best_ev_id = ev.get("id")
        if score >= 3:
            event_id = ev.get("id")
            break

    # Используем лучший матч даже с score=2
    if not event_id and best_score >= 2:
        event_id = best_ev_id

    if not event_id:
        # Диагностика: показываем ближайшие матчи для отладки
        if matchups:
            _sample = [ev.get("participants",[{}]*2) for ev in matchups
                       if ev.get("startTime","")[:10] == date_str][:3]
            if _sample:
                _names = [(p[0].get("name","?"), p[1].get("name","?")) for p in _sample if len(p)>=2]
                print(f"      ℹ️  Pinnacle {date_str}: не найдено '{home}' vs '{away}'")
                print(f"         Ближайшие: {_names[:2]}")
        _PIN_GUEST_CACHE[ck] = (time.time(), {})
        return {}

    # 2. Берём markets для этого события
    odds_data = _pin_guest(f"/0.1/sports/{_PIN_GUEST_SPORT}/events/{event_id}/markets",
                           {"primaryOnly": "false"})
    if not odds_data or not isinstance(odds_data, list):
        _PIN_GUEST_CACHE[ck] = (time.time(), {})
        return {}

    result = {"_source_pinnacle": True}
    for market in odds_data:
        mkey  = market.get("key", "")
        prices = {p.get("designation", ""): p.get("price", 0)
                  for p in market.get("prices", []) if p.get("price")}

        if mkey == "s;0;m":          # 1X2
            if prices.get("home"):  result["1"] = round(float(prices["home"]), 3)
            if prices.get("draw"):  result["X"] = round(float(prices["draw"]), 3)
            if prices.get("away"):  result["2"] = round(float(prices["away"]), 3)
        elif mkey.startswith("s;0;ou;"):   # Тотал
            try:
                line = float(mkey.split(";")[3])
                if prices.get("over"):  result[f"over_{line}"]  = round(float(prices["over"]), 3)
                if prices.get("under"): result[f"under_{line}"] = round(float(prices["under"]), 3)
            except (IndexError, ValueError): pass
        elif mkey.startswith("s;0;s;"):    # Гандикап
            try:
                hdp = float(mkey.split(";")[3])
                if abs(hdp) <= 2.0:
                    if prices.get("home"): result[f"ah_home_{hdp:+.2f}"] = round(float(prices["home"]), 3)
                    if prices.get("away"): result[f"ah_away_{hdp:+.2f}"] = round(float(prices["away"]), 3)
            except (IndexError, ValueError): pass
        elif mkey == "s;0;tt":       # BTTS
            if prices.get("yes"): result["btts_yes"] = round(float(prices["yes"]), 3)
            if prices.get("no"):  result["btts_no"]  = round(float(prices["no"]), 3)
        elif mkey == "s;0;dnb":      # DNB
            if prices.get("home"): result["dnb_home"] = round(float(prices["home"]), 3)
            if prices.get("away"): result["dnb_away"] = round(float(prices["away"]), 3)
        elif mkey == "s;0;dc":       # Двойной шанс
            if prices.get("1x"):  result["dc_1x"] = round(float(prices["1x"]), 3)
            if prices.get("12"):  result["dc_12"] = round(float(prices["12"]), 3)
            if prices.get("x2"):  result["dc_x2"] = round(float(prices["x2"]), 3)
        elif mkey == "s;1;m":        # 1Т исход
            if prices.get("home"):  result["1h_home"] = round(float(prices["home"]), 3)
            if prices.get("draw"):  result["1h_draw"] = round(float(prices["draw"]), 3)
            if prices.get("away"):  result["1h_away"] = round(float(prices["away"]), 3)
        elif mkey.startswith("s;1;ou;"):   # Тотал 1Т
            try:
                line = float(mkey.split(";")[3])
                if prices.get("over"):  result[f"1h_over_{line}"]  = round(float(prices["over"]), 3)
                if prices.get("under"): result[f"1h_under_{line}"] = round(float(prices["under"]), 3)
            except (IndexError, ValueError): pass

    if result.get("1"):
        n = len([k for k in result if not k.startswith("_")])
        print(f"      📌 Pinnacle Guest: {n} рынков ✅")
        _PIN_GUEST_CACHE[ck] = (time.time(), result)
        return result

    _PIN_GUEST_CACHE[ck] = (time.time(), {})
    return {}


def test_pinnacle_guest() -> bool:
    """Проверяет доступ к Pinnacle Guest API (без регистрации)."""
    data = _pin_guest(f"/0.1/sports/{_PIN_GUEST_SPORT}/matchups",
                      {"withSpecials": "false", "brandId": "0"})
    if data and isinstance(data, list):
        print(f"  ✅ Pinnacle Guest API: {len(data)} событий — работает (без аккаунта)")
        return True
    print("  ❌ Pinnacle Guest API: нет доступа (проверь интернет/VPN)")
    return False

def test_pinnacle_connection() -> bool:
    """Проверяет подключение к Pinnacle API."""
    data = _pin("/v1/sports")
    if data and isinstance(data, list):
        print("  ✅ Pinnacle API: подключение успешно")
        return True
    print("  ❌ Pinnacle API: нет подключения")
    return False

# ══════════════════════════════════════════════════════════════
#  🔵  BETFAIR EXCHANGE — биржа без маржи, фильтр сигналов
#  Бесплатный API. Если Betfair против нас — убираем сигнал.
# ══════════════════════════════════════════════════════════════
_bf_cache: dict = {}
_bf_token: str  = ""
_bf_token_ts    = 0.0

BETFAIR_USER = ""   # заполняется пользователем
BETFAIR_PASS = ""   # заполняется пользователем
BETFAIR_KEY  = ""   # App Key из личного кабинета

def _bf_login() -> str:
    """Получает session token Betfair. Кэшируется на 3 часа."""
    global _bf_token, _bf_token_ts
    if _bf_token and (time.time() - _bf_token_ts) < 10800:
        return _bf_token
    if not BETFAIR_USER or not BETFAIR_PASS:
        return ""
    try:
        url  = "https://identitysso.betfair.com/api/login"
        body = urllib.parse.urlencode({"username": BETFAIR_USER, "password": BETFAIR_PASS}).encode()
        req  = urllib.request.Request(url, data=body, headers={
            "X-Application": BETFAIR_KEY or "1",
            "Content-Type":  "application/x-www-form-urlencoded",
            "Accept":        "application/json",
        })
        with urllib.request.urlopen(req, timeout=10, context=_ssl()) as r:
            d = json.load(r)
            if d.get("status") == "SUCCESS":
                _bf_token    = d.get("token","")
                _bf_token_ts = time.time()
                return _bf_token
    except Exception as e:
        pass
    return ""

def _bf_api(method: str, params: dict) -> Optional[dict]:
    """Вызов Betfair JSON API."""
    token = _bf_login()
    if not token:
        return None
    cache_key = f"bf_{method}_{json.dumps(params, sort_keys=True)}"
    if cache_key in _bf_cache:
        return _bf_cache[cache_key]
    try:
        body = json.dumps([{"jsonrpc":"2.0","method":f"SportsAPING/v1.0/{method}","params":params,"id":1}]).encode()
        req  = urllib.request.Request(
            "https://api.betfair.com/exchange/betting/json-rpc/v1",
            data=body, headers={
                "X-Authentication": token,
                "X-Application":    BETFAIR_KEY or "1",
                "Content-Type":     "application/json",
                "Accept":           "application/json",
            })
        with urllib.request.urlopen(req, timeout=12, context=_ssl()) as r:
            resp = json.load(r)
            result = resp[0].get("result") if resp else None
            _bf_cache[cache_key] = result
            return result
    except Exception:
        return None

def fetch_betfair_odds(home: str, away: str, date_str: str) -> dict:
    """
    Берёт коэффициенты с Betfair Exchange.
    Возвращает {"1": 2.10, "X": 3.50, "2": 4.20} — без маржи.
    Если логин не задан — возвращает {} тихо.
    """
    if not BETFAIR_USER:
        return {}
    cache_key = f"bf_odds_{home}_{away}_{date_str}"
    if cache_key in _bf_cache:
        return _bf_cache[cache_key]

    # Ищем событие по дате
    events = _bf_api("listEvents", {
        "filter": {
            "eventTypeIds": ["1"],  # Soccer
            "marketStartTime": {
                "from":  f"{date_str}T00:00:00Z",
                "to":    f"{date_str}T23:59:59Z",
            },
        }
    })
    if not events:
        _bf_cache[cache_key] = {}
        return {}

    def _norm(s):
        return s.lower().strip().replace("-"," ").replace("."," ")

    h_words = set(_norm(home).split()) - {"fc","sc","the","de","cf"}
    a_words = set(_norm(away).split()) - {"fc","sc","the","de","cf"}

    event_id = None
    for ev in events:
        name = _norm(ev.get("event",{}).get("name",""))
        words = set(name.replace(" v "," vs ").split())
        if len(h_words & words) >= 1 and len(a_words & words) >= 1:
            event_id = ev.get("event",{}).get("id")
            break

    if not event_id:
        _bf_cache[cache_key] = {}
        return {}

    # Берём рынок Match Odds
    markets = _bf_api("listMarketCatalogue", {
        "filter": {"eventIds": [event_id], "marketTypeCodes": ["MATCH_ODDS"]},
        "maxResults": 1,
        "marketProjection": ["RUNNER_DESCRIPTION"],
    })
    if not markets:
        _bf_cache[cache_key] = {}
        return {}

    mid = markets[0].get("marketId","")
    runners = markets[0].get("runners",[])

    books = _bf_api("listMarketBook", {
        "marketIds": [mid],
        "priceProjection": {"priceData": ["EX_BEST_OFFERS"]},
    })
    if not books:
        _bf_cache[cache_key] = {}
        return {}

    result = {}
    runner_map = {r.get("selectionId"): r.get("runnerName","") for r in runners}

    for book in books:
        for runner in book.get("runners",[]):
            sid  = runner.get("selectionId")
            name = runner_map.get(sid,"").lower()
            best_back = runner.get("ex",{}).get("availableToBack",[])
            if not best_back:
                continue
            price = float(best_back[0].get("price",0))
            if price <= 1.0:
                continue
            if "draw" in name or "ничья" in name:
                result["X"] = round(price, 2)
            elif any(w in name for w in home.lower().split()[:2]):
                result["1"] = round(price, 2)
            else:
                result["2"] = round(price, 2)

    if result:
        print(f"      🔵 Betfair: {result}")
    _bf_cache[cache_key] = result
    return result

def betfair_consensus_filter(signals: list, bf_odds: dict, pin_odds: dict) -> list:
    """
    Если Betfair (острый рынок без маржи) даёт implied << нашей модели →
    рынок против нас → убираем сигнал.
    Порог 12%: если рынок считает вероятность на 12% ниже нашей оценки.
    Расширено: работает для 1X2 + тоталов.
    """
    if not bf_odds:
        return signals

    # Маппинг: selection → ключ в bf_odds
    _S2K = {
        "Победа хозяев (1)": "1",
        "Ничья (X)":         "X",
        "Победа гостей (2)": "2",
    }
    kept = []
    for s in signals:
        # 1X2
        sk = _S2K.get(s.selection)
        if not sk:
            # Тоталы: "Больше 2.5" → ключ "over_2.5"
            import re as _re
            if "Больше" in s.selection:
                _nums = _re.findall(r"[\d.]+", s.selection)
                sk = f"over_{_nums[0]}" if _nums else None
            elif "Меньше" in s.selection:
                _nums = _re.findall(r"[\d.]+", s.selection)
                sk = f"under_{_nums[0]}" if _nums else None

        if not sk:
            kept.append(s)
            continue

        bf      = bf_odds.get(sk, 0)
        pin     = pin_odds.get(sk, 0) if pin_odds else 0
        our_imp = 1.0 / s.bookmaker_odds
        bf_imp  = 1.0 / bf  if bf  > 1.01 else 0
        pin_imp = 1.0 / pin if pin > 1.01 else 0

        # Консенсус ПРОТИВ: оба острых рынка дают implied < нашей на 12%+
        if bf_imp > 0 and pin_imp > 0:
            threshold = our_imp * 0.88
            if bf_imp < threshold and pin_imp < threshold:
                print(f"      🔵 BF+PIN консенсус ПРОТИВ: [{s.market}] {s.selection} → убран")
                continue
        # Только Betfair (нет Pinnacle) — более мягкий порог
        elif bf_imp > 0 and bf_imp < our_imp * 0.82:
            print(f"      🔵 Betfair ПРОТИВ (−18%+): [{s.market}] {s.selection} → убран")
            continue

        kept.append(s)
    return kept


# ══════════════════════════════════════════════════════════════
#  💰  TRANSFERMARKT — стоимость состава команды
#  Дорогой состав vs дешёвый = дополнительный фактор силы
# ══════════════════════════════════════════════════════════════
_tm_cache: dict = {}

_TM_HEADERS = {
    "User-Agent":      "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                       "AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept":          "text/html,application/xhtml+xml",
    "Referer":         "https://www.transfermarkt.com/",
}

def fetch_squad_value(team_name: str, league_id: int) -> Optional[float]:
    """
    Возвращает рыночную стоимость состава в млн евро.
    Используется для корректировки xG в матчах с большой разницей классов.
    """
    cache_key = f"tm_{team_name}_{league_id}"
    if cache_key in _tm_cache:
        return _tm_cache[cache_key]

    # Нормализуем имя для поиска
    search = team_name.replace(" ", "+").replace("&", "and")
    url = f"https://www.transfermarkt.com/schnellsuche/ergebnis/schnellsuche?query={search}"
    try:
        r = _pool.request("GET", url, headers=_TM_HEADERS, timeout=12)
        if r.status != 200:
            _tm_cache[cache_key] = None
            return None
        html = r.data.decode("utf-8", errors="ignore")

        # Ищем ссылку на команду и её стоимость
        import re
        # Паттерн: ищем строки типа "€125.00m" или "€1.23bn"
        values = re.findall(r'€\s*([\d,.]+)\s*(m|bn|k)', html)
        if not values:
            _tm_cache[cache_key] = None
            return None

        # Берём первое значение (обычно суммарная стоимость клуба)
        raw, unit = values[0]
        raw = float(raw.replace(",", ""))
        if unit == "bn": raw *= 1000
        elif unit == "k": raw /= 1000

        _tm_cache[cache_key] = raw
        return raw
    except Exception:
        _tm_cache[cache_key] = None
        return None

def squad_value_factor(val_home: Optional[float], val_away: Optional[float]) -> float:
    """
    Корректировка xG хозяев при большой разнице стоимости составов.
    Лимит: max ±5% — не хотим перегружать модель одним фактором.
    """
    # Минимальный порог: оба клуба должны быть оценены >= €10m
    if not val_home or not val_away or val_home < 10 or val_away < 10:
        return 1.0
    ratio = val_home / max(val_away, 1)
    if ratio >= 4.0:   return 1.05   # хозяин в 4x+ дороже → +5%
    elif ratio >= 2.5: return 1.03   # хозяин в 2.5x дороже → +3%
    elif ratio <= 0.25: return 0.95  # хозяин в 4x+ дешевле → -5%
    elif ratio <= 0.40: return 0.97  # хозяин в 2.5x дешевле → -3%
    return 1.0


# ══════════════════════════════════════════════════════════════
#  📈  WHOSCORED — детальная статистика (xG по таймам, прессинг)
# ══════════════════════════════════════════════════════════════
_ws_cache: dict = {}

def fetch_whoscored_stats(home: str, away: str) -> dict:
    """
    Детальная статистика команд с WhoScored.
    Возвращает: {
      "home_xg_1h":  0.85,   # xG первый тайм за последние 5 матчей
      "home_xg_2h":  0.92,
      "away_xg_1h":  0.45,
      "away_xg_2h":  0.61,
      "home_press":  68.5,   # PPDA (давление)
      "away_press":  72.1,
      "note": ""
    }
    """
    cache_key = f"ws_{home}_{away}"
    if cache_key in _ws_cache:
        return _ws_cache[cache_key]

    default = {
        "home_xg_1h": 0, "home_xg_2h": 0,
        "away_xg_1h": 0, "away_xg_2h": 0,
        "home_press": 0, "away_press": 0, "note": ""
    }

    # WhoScored ищем через Google (без прямого API)
    import re
    try:
        query = urllib.parse.quote(f"{home} {away} site:whoscored.com")
        search_url = f"https://www.google.com/search?q={query}&num=3"
        r = _pool.request("GET", search_url, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                          "AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
            "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
        }, timeout=10)
        if r.status != 200:
            _ws_cache[cache_key] = default
            return default
        html = r.data.decode("utf-8", errors="ignore")

        # Ищем ссылку на матч на WhoScored
        urls = re.findall(r'href="(https://www\.whoscored\.com/Matches/\d+[^"]+)"', html)
        if not urls:
            _ws_cache[cache_key] = default
            return default

        # Загружаем страницу матча
        match_url = urls[0]
        r2 = _pool.request("GET", match_url, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                          "AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
            "Referer": "https://www.whoscored.com/",
        }, timeout=15)
        if r2.status != 200:
            _ws_cache[cache_key] = default
            return default

        html2 = r2.data.decode("utf-8", errors="ignore")

        # Извлекаем xG по таймам из JavaScript данных
        xg_matches = re.findall(r'"xg"\s*:\s*\[([\d.,\s]+)\]', html2)
        stats_note = ""
        if xg_matches:
            try:
                vals = [float(v.strip()) for v in xg_matches[0].split(",") if v.strip()]
                if len(vals) >= 4:
                    default["home_xg_1h"] = round(vals[0], 2)
                    default["home_xg_2h"] = round(vals[1], 2)
                    default["away_xg_1h"] = round(vals[2], 2)
                    default["away_xg_2h"] = round(vals[3], 2)
                    stats_note = f"WS xG 1H: {vals[0]:.2f}/{vals[2]:.2f}"
            except Exception:
                pass

        default["note"] = stats_note
        _ws_cache[cache_key] = default
        return default
    except Exception:
        _ws_cache[cache_key] = default
        return default


# ══════════════════════════════════════════════════════════════
#  📰  НОВОСТНОЙ ФИЛЬТР — проверка травм перед матчем
#  Ищет последние новости о командах через Google News
# ══════════════════════════════════════════════════════════════
_news_cache: dict = {}

def fetch_team_news(team_name: str, date_str: str) -> dict:
    """
    Проверяет последние новости о команде.
    Возвращает: {
      "injury_alert": True/False,  # найдены ключевые слова о травмах
      "suspension_alert": True/False,
      "coach_change": True/False,
      "note": "⚠️ Предупреждение: новости о травмах в составе",
    }
    """
    cache_key = f"news_{team_name}_{date_str}"
    if cache_key in _news_cache:
        return _news_cache[cache_key]

    default = {"injury_alert": False, "suspension_alert": False,
               "coach_change": False, "note": ""}

    import re
    try:
        # Google News RSS — бесплатно, без ключа
        query = urllib.parse.quote(f"{team_name} injury suspended")
        url   = f"https://news.google.com/rss/search?q={query}&hl=en&gl=US&ceid=US:en"
        r = _pool.request("GET", url, headers={
            "User-Agent": "Mozilla/5.0 (compatible; Googlebot/2.1)"
        }, timeout=8)
        if r.status != 200:
            _news_cache[cache_key] = default
            return default

        xml = r.data.decode("utf-8", errors="ignore").lower()

        # Ключевые слова
        injury_kw    = ["injury","injured","out for","ruled out","fitness doubt",
                        "unavailable","hamstring","ankle","knee","suspended","ban"]
        coach_kw     = ["sacked","fired","new manager","new coach","interim"]

        injury_found = any(k in xml for k in injury_kw[:8])
        suspend_found= any(k in xml for k in ["suspended","ban","red card"])
        coach_found  = any(k in xml for k in coach_kw)

        note = ""
        if injury_found:   note += "⚠️ Новости о травмах  "
        if suspend_found:  note += "🟥 Дисквалификации  "
        if coach_found:    note += "👔 Смена тренера  "

        result = {
            "injury_alert":     injury_found,
            "suspension_alert": suspend_found,
            "coach_change":     coach_found,
            "note":             note.strip(),
        }
        _news_cache[cache_key] = result
        return result
    except Exception:
        _news_cache[cache_key] = default
        return default


# ══════════════════════════════════════════════════════════════
#  ⭐  СКОРИНГ СИГНАЛОВ — комплексная оценка качества
#  Учитывает все факторы вместе, не только edge
# ══════════════════════════════════════════════════════════════
def _best_candidate(match, lh: float, la: float, odds: dict) -> tuple:
    """
    Возвращает (market, selection, odds, prob, edge) лучшего кандидата
    даже если он ниже порога сигнала. Используется для информирования.
    """
    candidates = []
    total = lh + la
    # Тотал — простейший рынок
    for line in [1.5, 2.5, 3.5]:
        import math
        # P(total > line) из Пуассона
        p_over = 0.0
        for g1 in range(0, 12):
            for g2 in range(0, 12):
                if g1 + g2 > line:
                    p1 = math.exp(-lh) * lh**g1 / math.factorial(g1)
                    p2 = math.exp(-la) * la**g2 / math.factorial(g2)
                    p_over += p1 * p2
        key_o = f"over_{line}"
        key_u = f"under_{line}"
        bk_o = odds.get(key_o)
        bk_u = odds.get(key_u)
        if bk_o and bk_o > 1.05:
            imp = 1/bk_o
            edge = p_over - imp
            candidates.append(("Тотал", f"Больше {line}", bk_o, p_over, edge))
        if bk_u and bk_u > 1.05:
            p_under = 1 - p_over
            imp = 1/bk_u
            edge = p_under - imp
            candidates.append(("Тотал", f"Меньше {line}", bk_u, p_under, edge))
    # Исходы
    for key, sel in [("1","Победа хозяев"), ("X","Ничья"), ("2","Победа гостей")]:
        bk = odds.get(key)
        if bk and bk > 1.05:
            bk1 = odds.get("1"); bkx = odds.get("X"); bk2 = odds.get("2")
            if bk1 and bkx and bk2:
                tot3 = 1/bk1 + 1/bkx + 1/bk2
                imp = (1/bk) / tot3
            else:
                imp = 1/bk * 0.93
            # Используем xG для вероятности
            if key == "1":   prob = min(0.95, lh / (lh + la + 0.3))
            elif key == "2": prob = min(0.95, la / (lh + la + 0.3))
            else:            prob = max(0.05, 1 - lh/(lh+la+0.3) - la/(lh+la+0.3))
            candidates.append(("Исход", sel, bk, prob, prob - imp))
    if not candidates:
        return None
    best = max(candidates, key=lambda x: x[4])   # лучший по edge
    return best if best[4] > -0.20 else None      # не показываем если совсем плохо


def score_signal(
    s,
    h2h: dict      = None,
    wx: dict       = None,
    bf_odds: dict  = None,
    rest_h: int    = 99,
    rest_a: int    = 99,
    sv_factor: float = 1.0,
    news_h: dict   = None,
    news_a: dict   = None,
) -> float:
    """
    Комплексная оценка качества сигнала от 0 до 100.
    Используется для ранжирования и фильтрации.

    Факторы:
    + Edge от Pinnacle (главный фактор)
    + Вероятность модели
    + H2H поддерживает прогноз
    + Betfair согласен (линия близкая)
    + Хорошая погода
    + Нормальный отдых команд
    - Новости о травмах
    - Движение линии против нас
    """
    score = 0.0

    # ── Базовый скор от edge и вероятности ─────────────────
    score += min(s.edge * 300, 35)          # до 35 очков за edge
    score += min((s.model_prob - 0.5) * 80, 20)  # до 20 очков за prob

    # ── Уверенность ────────────────────────────────────────
    if "ВЫСОКАЯ" in s.confidence:  score += 15
    elif "СРЕДНЯЯ" in s.confidence: score += 8

    # ── H2H поддерживает прогноз ───────────────────────────
    if h2h and h2h.get("matches", 0) >= 3:
        factor    = h2h.get("h2h_factor", 1.0)
        btts_rate = h2h.get("h2h_btts_rate", 0.5)
        if s.selection in ("Победа хозяев (1)",) and factor > 1.03:
            score += 8   # H2H за хозяев
        elif s.selection in ("Победа гостей (2)",) and factor < 0.97:
            score += 8
        # H2H бонус для BTTS
        if s.market == "Обе забьют":
            if s.selection == "Да"  and btts_rate > 0.60: score += 6
            if s.selection == "Нет" and btts_rate < 0.40: score += 6
        # H2H бонус для тоталов — исторический средний тотал
        if s.market == "Тотал":
            h2h_avg_t = h2h.get("h2h_avg_total", 0)
            if h2h_avg_t > 0 and "Больше" in s.selection:
                import re as _re2
                nums = _re2.findall(r"[0-9.]+", s.selection)
                if nums and h2h_avg_t > float(nums[0]):
                    score += 5

    # ── Betfair близко к нашей оценке ──────────────────────
    if bf_odds:
        KEY_MAP = {"Победа хозяев (1)":"1","Ничья (X)":"X","Победа гостей (2)":"2"}
        sk = KEY_MAP.get(s.selection)
        if sk and bf_odds.get(sk):
            bf_imp = 1.0 / bf_odds[sk]
            our_imp = 1.0 / s.bookmaker_odds
            diff = abs(bf_imp - our_imp)
            if diff < 0.03:   score += 10   # Betfair согласен
            elif diff < 0.06: score += 5

    # ── Погода нейтральная ─────────────────────────────────
    if wx and wx.get("total_factor", 1.0) >= 0.98:
        score += 3

    # ── Отдых команд достаточный ───────────────────────────
    if rest_h >= 3 and rest_a >= 3:
        score += 4

    # ── Стоимость состава поддерживает сигнал ──────────────
    if sv_factor > 1.03 and s.selection in ("Победа хозяев (1)",):
        score += 5
    elif sv_factor < 0.97 and s.selection in ("Победа гостей (2)",):
        score += 5

    # ── Штрафы ─────────────────────────────────────────────
    if news_h and news_h.get("injury_alert"):   score -= 8
    if news_a and news_a.get("injury_alert"):   score -= 5
    if news_h and news_h.get("coach_change"):   score -= 6
    if (rest_h == 1 or rest_a == 1):            score -= 7
    if wx and wx.get("total_factor", 1.0) < 0.90: score -= 5

    return round(max(0.0, min(score, 100.0)), 1)



# ══════════════════════════════════════════════════════════════
#  🤖  ML-ВЕСА — загружаем из ml_weights.json если есть
# ══════════════════════════════════════════════════════════════
_ML_MARKET_EDGES: dict = {}   # min_edge по рынкам из ML-калибровки

def _load_ml_weights():
    """Загружает ML-оптимизированные пороги валуя по рынкам."""
    global _ML_MARKET_EDGES
    if not os.path.exists("ml_weights.json"):
        return
    try:
        with open("ml_weights.json", encoding="utf-8") as f:
            w = json.load(f)
        _ML_MARKET_EDGES = w.get("market_min_edge", {})
        if _ML_MARKET_EDGES:
            print(f"  🤖 ML-веса загружены ({len(_ML_MARKET_EDGES)} рынков)")
    except Exception:
        pass

# ══ PLATT CALIBRATION ══════════════════════════════════════════
# Из анализа 403 сигналов:
# prob 80%+ → факт WR=63%  (переоценка)
# prob 60-70% → факт WR=53%  (переоценка)
# Применяем sigmoid-калибровку: p_cal = 1/(1+exp(-(A*logit(p)+B)))
# Параметры подобраны по реальным данным бота:
_PLATT_A = 0.82   # <1 = сжимаем крайние значения
_PLATT_B = -0.06  # небольшой отрицательный bias

def _platt_calibrate(p: float) -> float:
    """Platt scaling калибровка вероятности."""
    import math
    p = max(0.01, min(0.99, p))
    logit = math.log(p / (1 - p))
    cal   = 1.0 / (1.0 + math.exp(-(_PLATT_A * logit + _PLATT_B)))
    return round(cal, 4)

def _ml_min_edge(market: str, base: float) -> float:
    """Возвращает ML-откорректированный мин.валуй для рынка."""
    return _ML_MARKET_EDGES.get(market, {}).get("min_edge", base)


# ══════════════════════════════════════════════════════════════
#  📺  ЛАЙВ-АНАЛИЗ КОМАНДЫ
#  Загружает live-статистику и строит прогноз оставшегося времени
# ══════════════════════════════════════════════════════════════
def get_live_team_stats(fixture_id: int) -> dict:
    """
    Получает live-статистику матча из API-Football.
    Возвращает: {
      "home_shots": 8, "away_shots": 3,
      "home_shots_on": 4, "away_shots_on": 1,
      "home_possession": 62, "away_possession": 38,
      "home_corners": 5, "away_corners": 1,
      "home_xg_live": 1.2, "away_xg_live": 0.4,  # расчётный
      "elapsed": 55,
      "home_goals": 1, "away_goals": 0,
    }
    """
    resp = _af_resp("fixtures/statistics", {"fixture": fixture_id})
    if not resp or len(resp) < 2:
        return {}

    def _parse_team_stats(team_data: dict) -> dict:
        stats = {}
        for item in team_data.get("statistics", []):
            t = item.get("type", "").lower()
            v = item.get("value")
            if v is None or v == "None": v = 0
            try: v = float(str(v).replace("%", ""))
            except: v = 0
            if "total shots" in t or "shots total" in t: stats["shots"] = v
            elif "shots on goal" in t or "shots on target" in t: stats["shots_on"] = v
            elif "ball possession" in t or "possession" in t: stats["possession"] = v
            elif "corner kicks" in t or "corners" in t: stats["corners"] = v
            elif "dangerous attacks" in t: stats["dangerous"] = v
            elif "passes accurate" in t: stats["passes_acc"] = v
        return stats

    h_stats = _parse_team_stats(resp[0])
    a_stats = _parse_team_stats(resp[1])

    # Расчётный xG на основе статистики
    # Формула: shots_on * 0.33 + shots_off * 0.08 + corners * 0.04
    def _calc_live_xg(s: dict) -> float:
        shots_on  = s.get("shots_on", 0)
        shots_off = max(0, s.get("shots", 0) - shots_on)
        corners   = s.get("corners", 0)
        danger    = s.get("dangerous", 0)
        xg = shots_on * 0.33 + shots_off * 0.07 + corners * 0.04 + danger * 0.02
        return round(xg, 2)

    h_xg = _calc_live_xg(h_stats)
    a_xg = _calc_live_xg(a_stats)

    # Текущий счёт из основного запроса
    score = {}
    resp2 = _af_resp("fixtures", {"id": fixture_id})
    if resp2:
        fix   = resp2[0]
        goals = fix.get("goals", {})
        st    = fix.get("fixture", {}).get("status", {})
        score["elapsed"]    = st.get("elapsed") or 0
        score["home_goals"] = goals.get("home") or 0
        score["away_goals"] = goals.get("away") or 0

    return {
        "home_shots":     h_stats.get("shots", 0),
        "away_shots":     a_stats.get("shots", 0),
        "home_shots_on":  h_stats.get("shots_on", 0),
        "away_shots_on":  a_stats.get("shots_on", 0),
        "home_possession":h_stats.get("possession", 50),
        "away_possession":a_stats.get("possession", 50),
        "home_corners":   h_stats.get("corners", 0),
        "away_corners":   a_stats.get("corners", 0),
        "home_dangerous": h_stats.get("dangerous", 0),
        "away_dangerous": a_stats.get("dangerous", 0),
        "home_xg_live":   h_xg,
        "away_xg_live":   a_xg,
        **score,
    }


def analyze_live_team(fixture_id: int, home: str, away: str,
                      xg_pre_h: float, xg_pre_a: float) -> dict:
    """
    Анализ команды в лайв-режиме.
    Комбинирует предматчевый прогноз с реальной live-статистикой.

    Возвращает словарь с оценкой каждой команды и сигналами для лайв-ставок.
    """
    stats = get_live_team_stats(fixture_id)
    if not stats:
        return {"error": "нет live данных"}

    elapsed     = stats.get("elapsed", 0)
    home_goals  = stats.get("home_goals", 0)
    away_goals  = stats.get("away_goals", 0)
    remaining   = max(1, 90 - elapsed) / 90   # доля оставшегося времени

    # Темп голов: голы в минуту × оставшееся время = ожидаемые голы
    # Если прошло < 15 минут — доверяем предматчевому прогнозу
    if elapsed >= 15:
        h_rate = stats["home_xg_live"] / max(elapsed, 1) * 90
        a_rate = stats["away_xg_live"] / max(elapsed, 1) * 90
        # Блендируем предматчевый и лайв (вес лайв растёт со временем)
        live_weight = min(0.7, elapsed / 90)
        pre_weight  = 1.0 - live_weight
        h_xg_proj = xg_pre_h * pre_weight + h_rate * live_weight
        a_xg_proj = xg_pre_a * pre_weight + a_rate * live_weight
    else:
        h_xg_proj = xg_pre_h
        a_xg_proj = xg_pre_a

    # Ожидаемые голы ЗА ОСТАВШЕЕСЯ время
    h_xg_rem = round(h_xg_proj * remaining, 2)
    a_xg_rem = round(a_xg_proj * remaining, 2)
    total_rem = round(h_xg_rem + a_xg_rem, 2)

    # Оценка давления команды (0–100)
    def _pressure_score(shots_on, shots, possession, dangerous, corners) -> float:
        score = (shots_on * 15 + (shots - shots_on) * 5 +
                 (possession - 50) * 0.5 + dangerous * 3 + corners * 2)
        return round(min(100, max(0, score)), 1)

    h_pressure = _pressure_score(
        stats["home_shots_on"], stats["home_shots"],
        stats["home_possession"], stats["home_dangerous"], stats["home_corners"]
    )
    a_pressure = _pressure_score(
        stats["away_shots_on"], stats["away_shots"],
        stats["away_possession"], stats["away_dangerous"], stats["away_corners"]
    )

    # Сигналы для лайв-ставок
    live_signals = []

    # Тотал больше
    current_total = home_goals + away_goals
    if total_rem >= 0.9:
        live_signals.append({
            "market":    "Тотал (лайв)",
            "selection": f"Больше {current_total + 0.5}",
            "reason":    f"Ожидается ещё {total_rem:.1f} гол(а) за {int(remaining*90)}мин",
            "confidence": "🔥" if total_rem >= 1.3 else "✅",
        })

    # Следующий гол забьёт...
    if h_pressure > a_pressure + 20 and h_xg_rem > 0.5:
        live_signals.append({
            "market":    "Следующий гол",
            "selection": f"{home} (давление {h_pressure:.0f}/100)",
            "reason":    f"Преимущество хозяев: {stats['home_shots_on']} удара в створ, {stats['home_possession']:.0f}% мяч",
            "confidence": "✅",
        })
    elif a_pressure > h_pressure + 20 and a_xg_rem > 0.5:
        live_signals.append({
            "market":    "Следующий гол",
            "selection": f"{away} (давление {a_pressure:.0f}/100)",
            "reason":    f"Давление гостей: {stats['away_shots_on']} удара в створ",
            "confidence": "✅",
        })

    # Команда не проигрывает
    if home_goals > away_goals and h_pressure >= a_pressure and elapsed >= 60:
        live_signals.append({
            "market":    "Исход (лайв)",
            "selection": f"{home} не проиграет (DNB лайв)",
            "reason":    f"Ведут {home_goals}:{away_goals} @ {elapsed}', давление {h_pressure:.0f}",
            "confidence": "🔥" if (home_goals - away_goals) >= 2 else "✅",
        })

    return {
        "elapsed":      elapsed,
        "score":        f"{home_goals}:{away_goals}",
        "home_xg_live": stats["home_xg_live"],
        "away_xg_live": stats["away_xg_live"],
        "home_xg_rem":  h_xg_rem,
        "away_xg_rem":  a_xg_rem,
        "total_rem":    total_rem,
        "home_pressure": h_pressure,
        "away_pressure": a_pressure,
        "home_shots":   f"{stats['home_shots_on']}/{stats['home_shots']}",
        "away_shots":   f"{stats['away_shots_on']}/{stats['away_shots']}",
        "home_poss":    stats["home_possession"],
        "live_signals": live_signals,
    }


def format_live_analysis(analysis: dict, home: str, away: str) -> str:
    """Форматирует лайв-анализ для Telegram."""
    if "error" in analysis:
        return f"⚠️ {analysis['error']}"

    el  = analysis["elapsed"]
    sc  = analysis["score"]
    hp  = analysis["home_pressure"]
    ap  = analysis["away_pressure"]
    hbar = "█" * int(hp / 10)
    abar = "█" * int(ap / 10)

    lines = [
        f"📺 <b>ЛАЙВ-АНАЛИЗ</b>  [{el}']  {sc}",
        f"",
        f"<b>{home}</b>",
        f"  🎯 xG лайв: {analysis['home_xg_live']}  |  Ост.: {analysis['home_xg_rem']}",
        f"  👟 Удары: {analysis['home_shots']} (в створ/всего)",
        f"  ⚡ Давление: {hp:.0f}/100  {hbar}",
        f"",
        f"<b>{away}</b>",
        f"  🎯 xG лайв: {analysis['away_xg_live']}  |  Ост.: {analysis['away_xg_rem']}",
        f"  👟 Удары: {analysis['away_shots']}",
        f"  ⚡ Давление: {ap:.0f}/100  {abar}",
        f"",
        f"🔮 Тотал за остаток: <b>{analysis['total_rem']:.1f}</b> голов",
    ]

    if analysis["live_signals"]:
        lines.append("")
        lines.append("💡 <b>ЛАЙВ-СИГНАЛЫ:</b>")
        for sig in analysis["live_signals"]:
            lines.append(
                f"  {sig['confidence']} [{sig['market']}] {sig['selection']}"
            )
            lines.append(f"     {sig['reason']}")

    return "\n".join(lines)


# ══════════════════════════════════════════════════════════════
#  🎰  PARI.RU — время матчей и коэффициенты
# ══════════════════════════════════════════════════════════════
_pari_cache: dict = {}   # "home_away" → {time, odds}

def _fetch_pari_events(date_str: str) -> list:
    """Pari.ru отключён — блокирует запросы из нероссийских IP."""
    return []


def _match_pari(home_name: str, away_name: str, date_str: str) -> Optional[dict]:
    """
    Ищет матч на Pari по именам команд.
    Возвращает dict с ключами time, odds или None.
    """
    events = _fetch_pari_events(date_str)
    if not events:
        return None

    def _norm(s: str) -> set:
        s = s.lower().strip()
        for sfx in [" fc"," afc"," sc"," cf"," fk"," sk"]:
            s = s.replace(sfx,"")
        # Убираем транслит-артикли
        words = s.split()
        stop  = {"the","de","fc","sc","af"}
        return set(w for w in words if w not in stop and len(w) > 1)

    h_words = _norm(home_name)
    a_words = _norm(away_name)

    best_score = 0
    best_ev    = None

    for ev in events:
        eh = _norm(ev["home"])
        ea = _norm(ev["away"])
        score = len(h_words & eh) + len(a_words & ea)
        if score > best_score:
            best_score = score
            best_ev    = ev

    # Минимум 1 слово совпало для каждой команды
    if best_ev and best_score >= 2:
        return best_ev
    return None



# ══════════════════════════════════════════════════════════════
#  🎰  FONBET — реальные коэффициенты (fonbet.ru)
#  Публичный API без ключа. Работает из RU IP.
#  Покрывает: все лиги Фонбета включая Кубок России, РПЛ,
#             Ла Лига, АПЛ, Серия А, Бундеслига и др.
# ══════════════════════════════════════════════════════════════

_fonbet_events_cache: dict = {}   # date_str → list[event_dict]
_fonbet_odds_cache:   dict = {}   # event_id  → odds_dict
_fonbet_unavailable: bool = False  # True если все хосты недоступны (нет RU IP)

# Маппинг factorId Фонбет → наш внутренний ключ
_FONBET_FACTOR_MAP: dict = {
    # 1X2
    1:    "1",
    2:    "X",
    3:    "2",
    # Фора (европейский гандикап)
    # Фора 0: 7=хоз, 8=гость
    7:    "eh_home_0",
    8:    "eh_away_0",
    # Фора -1 / +1
    921:  "eh_home_-1",
    922:  "eh_draw_-1",
    923:  "eh_away_-1",
    924:  "eh_home_+1",
    925:  "eh_draw_+1",
    926:  "eh_away_+1",
    # Фора -2 / +2
    927:  "eh_home_-2",
    928:  "eh_draw_-2",
    929:  "eh_away_-2",
    930:  "eh_home_+2",
    931:  "eh_draw_+2",
    932:  "eh_away_+2",
    # Тоталы
    9:    "over_0.5",
    10:   "under_0.5",
    1050: "over_1.5",
    1051: "under_1.5",
    1048: "over_2.5",
    1049: "under_2.5",
    1052: "over_3.5",
    1053: "under_3.5",
    1054: "over_4.5",
    1055: "under_4.5",
    # DNB (Победа без ничьей)
    47:   "dnb_home",
    48:   "dnb_away",
    # Двойной шанс
    19:   "dc_1x",
    20:   "dc_x2",
    21:   "dc_12",
    # ИТ хозяин
    1180: "it_h_over_0.5",
    1181: "it_h_under_0.5",
    1182: "it_h_over_1.5",
    1183: "it_h_under_1.5",
    1184: "it_h_over_2.5",
    1185: "it_h_under_2.5",
    # ИТ гость
    1186: "it_a_over_0.5",
    1187: "it_a_under_0.5",
    1188: "it_a_over_1.5",
    1189: "it_a_under_1.5",
    1190: "it_a_over_2.5",
    1191: "it_a_under_2.5",
    # 1-й тайм тоталы
    68:   "1h_over_0.5",
    69:   "1h_under_0.5",
    72:   "1h_over_1.5",
    73:   "1h_under_1.5",
    # 1-й тайм исход
    34:   "1h_1",
    35:   "1h_x",
    36:   "1h_2",
}

def _fetch_fonbet_events(date_str: str) -> list:
    """
    Загружает все футбольные события Фонбет на указанную дату.
    Возвращает список словарей: {id, home, away, date, league, factors}.
    Работает через публичный API line.fonbet.ru (только из RU IP).
    """
    global _fonbet_unavailable

    # Если уже знаем что недоступен — не пытаемся снова
    if _fonbet_unavailable:
        return []

    if date_str in _fonbet_events_cache:
        return _fonbet_events_cache[date_str]

    _FB_HOSTS = [
        "line.fonbet.ru",
        "line2.fonbet.ru",
        "fon-line.ru",
    ]
    _FB_HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36",
        "Accept": "application/json",
        "Accept-Language": "ru-RU,ru;q=0.9",
        "Referer": "https://fonbet.ru/",
        "Origin": "https://fonbet.ru",
    }

    data = None
    _failed = 0
    for host in _FB_HOSTS:
        for url in [
            f"https://{host}/api/v2/events?sportId=1&lang=ru",
            f"https://{host}/api/v2/events?sportId=1&lang=ru&date={date_str}",
            f"https://{host}/api/v2/sport?sportIds=1&lang=ru",
            f"https://{host}/api/v2/sport/events?sportId=1&lang=ru",
            f"https://{host}/api/v2/line/events?sportId=1",
        ]:
            try:
                data = _http(url, _FB_HEADERS, silent=True)
            except Exception:
                data = None
            if isinstance(data, dict) and ("events" in data or "e" in data or "data" in data):
                # Normalize: некоторые версии API оборачивают в "data"
                if "data" in data and isinstance(data["data"], dict):
                    data = data["data"]
                break
            _failed += 1
            data = None
        if data:
            break

    if not isinstance(data, dict):
        # Все хосты недоступны → отключаем Fonbet на весь скан
        _fonbet_unavailable = True
        _fonbet_events_cache[date_str] = []
        print(f"   ℹ️  Fonbet недоступен (нет RU IP) — используем расчётные коэф")
        return []

    # Нормализуем ответ — Fonbet меняет структуру
    raw_events = data.get("events") or data.get("e") or []
    raw_factors = data.get("factors") or data.get("f") or []

    # Индекс коэффициентов по event_id
    factors_by_event: dict = {}
    for fac in raw_factors:
        eid = fac.get("e") or fac.get("eventId")
        fid = fac.get("f") or fac.get("factorId")
        val = fac.get("v") or fac.get("value")
        if eid and fid and val:
            try:
                factors_by_event.setdefault(int(eid), {})[int(fid)] = float(val)
            except (ValueError, TypeError):
                pass

    result = []
    for ev in raw_events:
        try:
            # Пропускаем не-матчи (live, групповые события)
            kind = ev.get("kind") or ev.get("type") or ""
            if kind not in ("", "match", 0, 1, None):
                continue

            eid   = ev.get("id") or ev.get("eventId")
            sport = ev.get("sportId") or ev.get("sport")
            if sport and str(sport) not in ("1", "football"):
                continue

            # Имена команд
            h = (ev.get("team1") or ev.get("h") or ev.get("home") or
                 ev.get("t1") or "").strip()
            a = (ev.get("team2") or ev.get("a") or ev.get("away") or
                 ev.get("t2") or "").strip()
            if not h or not a:
                continue

            # Дата начала
            dt_raw = (ev.get("startTime") or ev.get("startDate") or
                      ev.get("date") or ev.get("dt") or "")
            dt_str = str(dt_raw)[:10] if dt_raw else ""

            # Лига
            league = (ev.get("leagueName") or ev.get("league") or
                      ev.get("competition") or ev.get("l") or "")

            # Коэффициенты этого события
            facs = {}
            if eid and int(eid) in factors_by_event:
                facs = factors_by_event[int(eid)]
            elif ev.get("factors"):
                for f in ev["factors"]:
                    try:
                        facs[int(f.get("f") or f.get("factorId"))] = float(f.get("v") or f.get("value"))
                    except Exception:
                        pass

            result.append({
                "id":      eid,
                "home":    h,
                "away":    a,
                "date":    dt_str,
                "league":  league,
                "factors": facs,
            })
        except Exception:
            continue

    _fonbet_events_cache[date_str] = result
    if result:
        print(f"   🎰 Fonbet: загружено {len(result)} событий")
    return result


def _fonbet_factors_to_odds(factors: dict) -> dict:
    """Конвертирует factorId: value → наш формат odds dict."""
    odds = {}
    for fid, val in factors.items():
        key = _FONBET_FACTOR_MAP.get(int(fid))
        if key and val and float(val) > 1.01:
            odds[key] = round(float(val), 2)
    return odds


def _fonbet_norm(s: str) -> str:
    """Нормализация имени команды для сравнения."""
    s = s.lower().strip()
    for sfx in [" фк", " фc", " fc", " sc", " аф", " фк.", " 1.", " 2."]:
        if s.endswith(sfx): s = s[:-len(sfx)].strip()
    # Транслит-замены для русских названий
    _TR = {
        "арсенал": "arsenal", "челси": "chelsea", "ливерпуль": "liverpool",
        "манчестер сити": "man city", "манчестер юнайтед": "man utd",
        "тоттенхэм": "tottenham", "барселона": "barcelona",
        "реал мадрид": "real madrid", "атлетико": "atletico",
        "атлетик бильбао": "athletic", "ювентус": "juventus",
        "милан": "milan", "интер": "inter", "наполи": "napoli",
        "рома": "roma", "лацио": "lazio", "аталанта": "atalanta",
        "боруссия дортмунд": "dortmund", "боруссия дорт": "dortmund", "бавария": "bayern",
        "лейпциг": "leipzig", "леверкузен": "leverkusen", "байер": "leverkusen",
        "гамбург": "hamburg", "фрайбург": "freiburg", "штутгарт": "stuttgart",
        "кельн": "koln", "майнц": "mainz", "аугсбург": "augsburg",
        "боруссия м": "monchengladbach", "гладбах": "monchengladbach",
        "вердер": "werder", "хоффенхайм": "hoffenheim", "айнтрахт": "eintracht",
        "вольфсбург": "wolfsburg", "юнион берлин": "union berlin",
        "герта": "hertha",
        "зенит": "zenit", "спартак": "spartak", "цска": "cska",
        "локомотив": "lokomotiv", "динамо": "dynamo",
        "краснодар": "krasnodar", "ахмат": "akhmat",
        "рубин": "rubin", "ростов": "rostov",
        "пари нн": "pari nn", "оренбург": "orenburg",
    }
    return _TR.get(s, s)


def _fonbet_match(a: str, b: str) -> bool:
    """Нечёткое сравнение двух названий команд."""
    na, nb = _fonbet_norm(a), _fonbet_norm(b)
    if na == nb: return True
    # Пересечение слов (минимум 1 значимое слово)
    _stop = {"fc", "sc", "city", "united", "the", "de", "1.", "2."}
    wa = set(na.split()) - _stop
    wb = set(nb.split()) - _stop
    if wa and wb and len(wa & wb) >= 1: return True
    if len(na) >= 5 and (na in nb or nb in na): return True
    return False


def fetch_fonbet_odds(home_name: str, away_name: str,
                      date_str: str, league_name: str = "") -> dict:
    """
    Ищет матч на Фонбет и возвращает коэффициенты в нашем формате.
    home_name, away_name — английские названия команд.
    Возвращает dict или {} если не нашёл.
    """
    # Быстрая проверка — если Fonbet недоступен, не тратим время
    if _fonbet_unavailable:
        return {}

    # Загружаем события (кэш общий — второй вызов бесплатный)
    events = _fetch_fonbet_events(date_str)
    if not events and not _fonbet_unavailable:
        # Пробуем соседние дни (матчи в UTC±)
        for _delta in [1, -1]:
            _d2 = (datetime.date.fromisoformat(date_str) + datetime.timedelta(days=_delta)).isoformat()
            if _d2 not in _fonbet_events_cache:
                events = _fetch_fonbet_events(_d2)
                if events: break

    if not events:
        return {}

    best_ev, best_score = None, 0
    for ev in events:
        score = 0
        if _fonbet_match(home_name, ev["home"]): score += 2
        if _fonbet_match(away_name, ev["away"]): score += 2
        # Бонус за совпадение лиги
        if league_name and ev.get("league"):
            ln_kw = set(league_name.lower().split()) - {"лига","кубок","чемпионат","первая"}
            ev_kw = set(ev["league"].lower().split()) - {"лига","кубок","чемпионат","первая"}
            if ln_kw & ev_kw: score += 1
        if score > best_score:
            best_score = score
            best_ev = ev

    if best_score < 3:
        return {}  # нужно минимум home+away совпадение

    odds = _fonbet_factors_to_odds(best_ev["factors"])

    if odds.get("1"):
        odds["_source_fonbet"] = True
        odds["_fonbet_event_id"] = best_ev["id"]
        odds["_fonbet_home"] = best_ev["home"]
        odds["_fonbet_away"] = best_ev["away"]
        return odds

    return {}


# ══════════════════════════════════════════════════════════════
#  🏆  OPENLIGADB — Бундеслига (бесплатно, без ключа)
#  Покрывает: BL1 (Bundesliga), BL2, BL3
#  Использование: как fallback для AF для Бундеслиги
# ══════════════════════════════════════════════════════════════
_openliga_cache: dict = {}

def fetch_openligadb(date_str: str) -> list:
    """
    Матчи Бундеслиги из OpenLigaDB на указанную дату.
    Возвращает список в стандартном формате бота.
    """
    if date_str in _openliga_cache:
        return _openliga_cache[date_str]

    result = []
    try:
        # Получаем матчи текущего тура
        url = f"https://api.openligadb.de/getmatchdata/bl1/2025"
        data = _http(url)
        if not isinstance(data, list):
            _openliga_cache[date_str] = []
            return []

        for match in data:
            try:
                match_dt = match.get("matchDateTimeUTC", "")
                if not match_dt:
                    continue
                m_date = match_dt[:10]   # YYYY-MM-DD
                if m_date != date_str:
                    continue

                hn = match.get("team1", {}).get("teamName", "")
                an = match.get("team2", {}).get("teamName", "")
                if not hn or not an:
                    continue

                result.append({
                    "fixture": {
                        "id": match.get("matchID", 0),
                        "date": match_dt
                    },
                    "teams": {
                        "home": {"id": match.get("team1", {}).get("teamId", 0), "name": hn},
                        "away": {"id": match.get("team2", {}).get("teamId", 0), "name": an},
                    },
                    "_league_id":   78,
                    "_league_name": "Бундеслига",
                    "_source":      "openligadb",
                })
            except Exception:
                continue

        if result:
            print(f"  🏆 OpenLigaDB: {len(result)} матчей Бундеслиги ({date_str})")

    except Exception as e:
        print(f"  ⚠️  OpenLigaDB: {str(e)[:60]}")

    _openliga_cache[date_str] = result
    return result

# ══════════════════════════════════════════════════════════════
#  📅  ИСТОЧНИК 1: football-data.org — по ДАТЕ (все лиги сразу)
# ══════════════════════════════════════════════════════════════
_fd_cache: dict = {}   # date_key → list[fixture]

def fetch_all_by_date_fd(date_from: str, date_to: str) -> list[dict]:
    """
    Один запрос → все матчи периода из всех лиг бесплатного плана.
    Endpoint: /v4/matches?dateFrom=...&dateTo=...
    """
    key = f"{date_from}|{date_to}"
    if key in _fd_cache:
        return _fd_cache[key]

    url  = (f"https://api.football-data.org/v4/matches"
            f"?dateFrom={date_from}&dateTo={date_to}")
    data = _http(url, {"X-Auth-Token": FOOTBALL_DATA_KEY})

    if not isinstance(data, dict) or "matches" not in data:
        _fd_cache[key] = []
        return []

    result = []
    for m in data["matches"]:
        try:
            comp_code = m.get("competition", {}).get("code", "")
            comp_name = m.get("competition", {}).get("name", "")
            league_id = FD_CODE_TO_LEAGUE.get(comp_code, 0)

            hn = m["homeTeam"]["name"]
            an = m["awayTeam"]["name"]
            for s in [" FC", "FC ", " AFC", " SC"]:
                hn = hn.replace(s, "").strip()
                an = an.replace(s, "").strip()

            result.append({
                "fixture":  {"id": m["id"], "date": m["utcDate"]},
                "teams": {
                    "home": {"id": m["homeTeam"].get("id", 0), "name": hn},
                    "away": {"id": m["awayTeam"].get("id", 0), "name": an},
                },
                "_league_id":   league_id,
                "_league_name": LEAGUES.get(league_id, comp_name),
                "_comp_code":   comp_code,
            })
        except (KeyError, TypeError):
            continue

    if result:
        print(f"  📅 football-data.org: найдено {len(result)} матчей ({date_from} → {date_to})")
    else:
        # FD бесплатно покрывает только АПЛ/Ла Лига/Серия А/Бундеслига/Лига 1/ЛЧ
        # Если там нет матчей — это нормально, идём к AF
        pass
    _fd_cache[key] = result
    return result

def get_fixtures_fd_for_league(league_id: int,
                               date_from: str, date_to: str) -> list[dict]:
    """Фильтруем общий кэш по нужной лиге."""
    all_m = fetch_all_by_date_fd(date_from, date_to)
    return [m for m in all_m if m.get("_league_id") == league_id]

# ══════════════════════════════════════════════════════════════
#  📅  ИСТОЧНИК 2: API-Football — с авто-сезоном
# ══════════════════════════════════════════════════════════════
_af_season_ok: dict[int, int] = {}   # league_id → рабочий сезон

def fetch_all_by_date_af(date_from: str, date_to: str) -> list[dict]:
    """
    API-Football → все матчи наших лиг за период.
    Стратегия: массовый запрос ?date= + fallback по отдельным лигам для кубков.
    При quota=0 — ищем в дисковом кэше прошлого запроса.
    """
    cache_key = f"af_all_{date_from}_{date_to}"
    if cache_key in _fd_cache:
        return _fd_cache[cache_key]

    league_ids_set = set(LEAGUES.keys())

    # ── Шаг 1: массовый запрос по дате ─────────────────────
    # (дисковый кэш проверяется внутри _af_resp автоматически)
    params = {"date": date_from} if date_from == date_to else {
        "from": date_from, "to": date_to
    }
    resp = _af_resp("fixtures", params)
    time.sleep(1)
    result = []
    found_ids = set()

    if resp and isinstance(resp, list):
        for fix in resp:
            try:
                lid = fix.get("league", {}).get("id", 0)
                if lid not in league_ids_set:
                    continue
                fix["_league_id"]   = lid
                fix["_league_name"] = LEAGUES.get(lid, fix.get("league",{}).get("name","?"))
                fid = fix.get("fixture",{}).get("id",0)
                if fid not in found_ids:
                    result.append(fix)
                    found_ids.add(fid)
            except Exception:
                continue

    # ── Шаг 2: fallback — отдельные запросы для кубков/доп. лиг ──
    # Делаем только если массовый не вернул эти лиги (нет матчей)
    # Кубки часто не попадают в ?date= массовый запрос
    found_league_ids = set(f.get("_league_id",0) for f in result)
    CUP_LEAGUES = {
        # FIX: Еврокубки — плей-офф раунды часто не попадают в ?date= массовый
        2:   "Лига Чемпионов",
        3:   "Лига Европы",
        848: "Лига Конференций",
        # FIX: РПЛ и ФНЛ ПЕРВЫМИ — они часто не попадают в ?date= массовый запрос
        235: "Лига ПАРИ (РПЛ)",
        370: "Первая лига России (ФНЛ)",
        276: "Кубок России (Фонбет)",
        # Далее остальные кубки/лиги
        137: "Кубок Испании (Copa del Rey)",
        9:   "Кубок Италии (Coppa Italia)",
        81:  "Кубок Германии (DFB Pokal)",
        45:  "Кубок Англии (FA Cup)",
        48:  "Кубок Лиги Англии (EFL)",
        65:  "Кубок Франции",
        210: "Кубок Турции",
        560: "Кубок Португалии",
        203: "Суперлига Турции",
        204: "Первая лига Турции",
    }
    # Cup fallback — только если достаточно квоты
    # FIX: увеличен budget до 10 (был 6), РПЛ/ФНЛ теперь первыми в очереди
    cup_budget = min(13, max(0, _af_quota_rem - 10))  # +3 для ЛЧ/ЛЕ/ЛК
    cup_count = 0
    for cup_id, cup_name in CUP_LEAGUES.items():
        if cup_count >= cup_budget:
            break
        if cup_id in found_league_ids:
            continue   # уже есть в результате
        if _af_quota_rem < 5:
            break
        try:
            cup_fixes = get_fixtures_af(cup_id, date_from, date_to)
            cup_count += 1
            if cup_fixes:
                for fix in cup_fixes:
                    fid = fix.get("fixture",{}).get("id",0)
                    if fid not in found_ids:
                        fix["_league_id"]   = cup_id
                        fix["_league_name"] = cup_name
                        result.append(fix)
                        found_ids.add(fid)
                print(f"   🏆 {cup_name}: +{len(cup_fixes)} матчей")
        except Exception:
            pass

    _fd_cache[cache_key] = result
    return result

def get_fixtures_af(league_id: int, date_from: str, date_to: str) -> list[dict]:
    """Пробуем season 2025, потом 2024."""
    if not _af_quota_ok:
        # FIX: endpoint/params не определены в этой функции — используем правильные ключи
        # Проверяем дисковый кэш по корректным ключам для данной лиги
        import json as _cj
        for _season in (CURRENT_SEASON, FALLBACK_SEASON):
            for _params_try in [
                {"league": league_id, "season": _season, "from": date_from, "to": date_to},
                {"league": league_id, "season": _season, "next": 10},
            ]:
                _ck = f"fixtures|{_cj.dumps(_params_try, sort_keys=True)}"
                _cached = _AF_DISK_CACHE.get(_ck)
                if _cached and isinstance(_cached, dict):
                    _resp = _cached.get("response", [])
                    if _resp:
                        # Фильтруем по дате
                        _filtered = [f for f in _resp
                                     if f.get("fixture", {}).get("date", "")[:10] >= date_from]
                        if _filtered:
                            return _filtered
        return []

    for season in (CURRENT_SEASON, FALLBACK_SEASON):
        # Пропускаем если уже знаем что этот сезон не работает для этой лиги
        if _af_season_ok.get(league_id, season) != season:
            continue

        resp = _af_resp("fixtures", {
            "league": league_id, "season": season,
            "from": date_from, "to": date_to
        })

        if resp:
            _af_season_ok[league_id] = season
            return resp

        # Попробуем через next= если диапазон дат не работает
        resp2 = _af_resp("fixtures", {
            "league": league_id, "season": season, "next": 10
        })
        # FIX: строгая фильтрация по league_id и диапазону дат
        filtered = [
            f for f in resp2
            if date_from <= f.get("fixture", {}).get("date", "")[:10] <= date_to
            and f.get("league", {}).get("id", 0) == league_id
        ]
        if filtered:
            _af_season_ok[league_id] = season
            return filtered

    return []

# ══════════════════════════════════════════════════════════════
#  🎯  ГЛАВНАЯ ФУНКЦИЯ — получить матчи
# ══════════════════════════════════════════════════════════════
# Лиги НЕ доступные на бесплатном football-data.org → сразу в API-Football
_FD_PAID = {2, 3, 848, 88, 203}   # ЛЧ, ЛЕ, ЛКЕ, Эредивизи, Турция

def get_fixtures(league_id: int, date_from: str, date_to: str) -> list[dict]:
    # 1. football-data.org (бесплатно, не тратит AF-квоту)
    if league_id not in _FD_PAID:
        fixes = get_fixtures_fd_for_league(league_id, date_from, date_to)
        if fixes:
            return fixes

    # 2. Массовый AF кэш (если уже загружен)
    mass_key = f"af_all_{date_from}_{date_to}"
    if mass_key in _fd_cache:
        cached = _fd_cache[mass_key]
        fixes = [f for f in cached if f.get("_league_id") == league_id]
        if fixes:
            return fixes
        # Массовый кэш загружен → лиги нет → не делаем лишний AF запрос.
        # ИСКЛЮЧЕНИЕ: кубковые лиги — их массовый ?date= часто пропускает.
        # FIX: добавлены 235 (РПЛ) и 370 (ФНЛ) — они тоже требуют отдельного AF запроса
        _CUP_IDS = {2, 3, 848, 9, 45, 48, 65, 81, 137, 210, 235, 276, 370, 560}  # добавлены ЛЧ(2), ЛЕ(3), ЛК(848)
        if league_id not in _CUP_IDS:
            return []   # ← лига не требует отдельного запроса — экономим квоту

    # 3. Отдельный AF запрос только для кубков или если кэш не загружен
    if _af_quota_ok:
        fixes = get_fixtures_af(league_id, date_from, date_to)
        if fixes:
            return fixes
    return []

# ══════════════════════════════════════════════════════════════
#  📊  СТАТИСТИКА КОМАНД (API-Football)
# ══════════════════════════════════════════════════════════════
_stats_cache: dict = {}

def _lookup_team_id(name: str) -> int:
    """Ищем AF team_id по названию команды."""
    resp = _af_resp("teams", {"search": name[:25]})
    time.sleep(7)
    if not resp:
        return 0
    # Ищем точное или частичное совпадение
    name_l = name.lower()
    for t in resp:
        tname = t.get("team", {}).get("name", "").lower()
        tid   = t.get("team", {}).get("id", 0)
        if name_l in tname or tname in name_l:
            return tid
    return resp[0]["team"]["id"] if resp else 0

def fetch_team_stats(team_id: int, team_name: str,
                     league_id: int) -> Optional[TeamStats]:
    """Статистика команды, автопоиск team_id если = 0."""
    cache_key = f"{team_id}|{team_name}|{league_id}"
    if cache_key in _stats_cache:
        return _stats_cache[cache_key]

    # Если нет team_id — ищем по имени
    if not team_id and team_name:
        team_id = _lookup_team_id(team_name)
    if not team_id:
        return None

    # Для ЛЧ/ЛЕ/ЛК — статистика у AF по национальной лиге точнее
    # (команда играет 6-8 еврокубков vs 38 матчей в чемпионате)
    _EURO_TO_NATIONAL = {
        # Для основных клубов — AF вернёт данные по нац. лиге
        # league_id=2(ЛЧ),3(ЛЕ),848(ЛК) → используем national fallback
    }
    _query_leagues = [league_id]
    if league_id in (2, 3, 848):
        # Добавляем национальные лиги как fallback
        _query_leagues += [39, 140, 135, 78, 61, 94, 88, 203, 144, 179, 235, 172, 167]

    # Пробуем сезон 2025, потом 2024
    for season in (CURRENT_SEASON, FALLBACK_SEASON):
        if not _af_quota_ok:
            break
        # Сначала пробуем целевую лигу, потом нац. лиги как fallback
        _checked_leagues = _query_leagues if league_id in (2,3,848) else [league_id]
        for _lid in _checked_leagues:
            resp = _af_resp_cached("teams/statistics", {
                "team": team_id, "league": _lid, "season": season
            })
            if resp:
                league_id = _lid   # нашли — используем эту лигу
                break
        if not resp:
            continue

        r = resp if isinstance(resp, dict) else (resp[0] if resp else None)
        if not r or not isinstance(r, dict) or "goals" not in r:
            continue

        try:
            gs = float(r["goals"]["for"]["average"]["total"]     or 1.3)
            gc = float(r["goals"]["against"]["average"]["total"] or 1.3)
            try:
                hgs = float(r["goals"]["for"]["average"]["home"] or gs)
                ags = float(r["goals"]["for"]["average"]["away"] or gs)
                ha  = max(0.0, (hgs - ags) / max(hgs, 0.01) * 0.12)
            except Exception:
                ha = 0.07
            ts = TeamStats(
                name=r["team"]["name"],
                team_id=team_id,
                avg_goals_scored=max(0.65, gs),
                avg_goals_conceded=max(0.3, gc),
                home_advantage=round(ha, 3),
            )
            _stats_cache[cache_key] = ts
            return ts
        except (KeyError, TypeError):
            continue

    return None


# ══════════════════════════════════════════════════════════════
#  📈  РЕАЛЬНАЯ ФОРМА ИЗ API-FOOTBALL
# ══════════════════════════════════════════════════════════════
_form_cache: dict = {}

def fetch_team_form(team_id: int, team_name: str, league_id: int) -> Optional[tuple]:
    """
    Берёт последние 5 матчей команды из API-Football.
    Возвращает (form_rating, attack_trend, defense_trend) или None.
    Расходует 1 запрос из 100/день — вызывается только если есть квота.
    """
    if not _af_quota_ok or not team_id:
        return None

    cache_key = f"form_{team_id}_{league_id}"
    if cache_key in _form_cache:
        return _form_cache[cache_key]

    resp = _af_resp("fixtures", {
        "team": team_id, "last": 6,
        "league": league_id, "season": CURRENT_SEASON
    })
    if not resp:
        resp = _af_resp("fixtures", {
            "team": team_id, "last": 6,
            "league": league_id, "season": FALLBACK_SEASON
        })
    if not resp or not isinstance(resp, list):
        return None

    results      = []
    goals_scored = []
    goals_conceded = []

    for fix in resp[-5:]:   # последние 5
        try:
            teams  = fix["teams"]
            goals  = fix["goals"]
            is_home = teams["home"].get("id") == team_id
            team_won = teams["home"].get("winner") if is_home else teams["away"].get("winner")
            gf = (goals.get("home") or 0) if is_home else (goals.get("away") or 0)
            ga = (goals.get("away") or 0) if is_home else (goals.get("home") or 0)

            if team_won is True:    results.append(1.0)
            elif team_won is False: results.append(0.0)
            else:                   results.append(0.5)   # ничья или None

            goals_scored.append(gf)
            goals_conceded.append(ga)
        except Exception:
            continue

    if len(results) < 3:
        return None

    # form_rating: среднее из побед/ничьих/поражений → 0.70–1.40
    avg_res     = sum(results) / len(results)
    form_rating = max(0.70, min(1.40, 0.70 + avg_res * 1.40))

    # attack_trend: последние 2 матча vs предыдущие
    if len(goals_scored) >= 4:
        recent_g  = sum(goals_scored[-2:])  / 2
        older_g   = sum(goals_scored[:-2])  / max(len(goals_scored)-2, 1)
        atk_trend = max(0.80, min(1.25, 1.0 + (recent_g - older_g) * 0.15))
    else:
        atk_trend = 1.0

    # defense_trend: меньше пропустил = лучше (инвертируем)
    if len(goals_conceded) >= 4:
        recent_c  = sum(goals_conceded[-2:]) / 2
        older_c   = sum(goals_conceded[:-2]) / max(len(goals_conceded)-2, 1)
        def_trend = max(0.80, min(1.25, 1.0 - (recent_c - older_c) * 0.15))
    else:
        def_trend = 1.0

    result = (round(form_rating, 3), round(atk_trend, 3), round(def_trend, 3))
    _form_cache[cache_key] = result

    # Обновляем FORM_DB и team_stats.json для будущих запусков
    _update_form_cache(team_name, results, goals_scored, goals_conceded)

    return result

def _update_form_cache(name: str, results: list, scored: list, conceded: list):
    """Сохраняем реальную форму в team_stats.json."""
    if not name:
        return
    key = name.lower().strip()
    for sfx in [" fc"," afc"," sc"," cf"," bc"]:
        key = key.replace(sfx,"").strip()
    try:
        import os as _os
        ts = {}
        if _os.path.exists("team_stats.json"):
            with open("team_stats.json", encoding="utf-8") as f:
                ts = json.load(f)
        if not isinstance(ts, dict):
            ts = {}
        if key not in ts:
            ts[key] = {"h_gs":1.55,"h_gc":1.25,"a_gs":1.25,"a_gc":1.55,"matches":0,"updated":""}
        ts[key]["form"]         = results[-5:]
        ts[key]["form_scored"]  = scored[-5:]
        ts[key]["form_conceded"]= conceded[-5:]
        ts[key]["form_updated"] = datetime.date.today().isoformat()
        with open("team_stats.json", "w", encoding="utf-8") as f:
            json.dump(ts, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

# ══════════════════════════════════════════════════════════════
#  💰  КОЭФФИЦИЕНТЫ (API-Football /odds)
# ══════════════════════════════════════════════════════════════
# Кэш спортивных ключей Odds API
_odds_sports_cache: list = []
_odds_api_auth_ok: bool  = True   # False при 401 ошибке
_odds_api_remaining: int  = -1    # -1 = неизвестно, 0+ = остаток кредитов

def _get_odds_sports() -> list:
    """Список активных футбольных ключей в The Odds API."""
    global _odds_sports_cache, _odds_api_auth_ok
    if _odds_sports_cache:
        return _odds_sports_cache
    if not _odds_api_auth_ok:
        return []
    for _k in [k for k in [ODDS_API_KEY, ODDS_API_KEY2 if ODDS_API_KEY2 else None] if k]:
        data = _http(f"https://api.the-odds-api.com/v4/sports/?apiKey={_k}&all=true")
        if isinstance(data, list):
            _odds_sports_cache = [s["key"] for s in data
                                  if s.get("active") and "soccer" in s.get("key","")]
            print(f"   📋 Odds API: {len(_odds_sports_cache)} рынков активно")
            return _odds_sports_cache
        if data is None:
            # 401 или сеть — отключаем Odds API
            _odds_api_auth_ok = False
            print(f"   🔑 Odds API: ключ недействителен — используем расчётные коэф")
            return []
        if isinstance(data, dict):
            msg = data.get("message", str(data)[:60])
            if "401" in msg or "unauthorized" in msg.lower() or "invalid" in msg.lower():
                _odds_api_auth_ok = False
                print(f"   🔑 Odds API: ключ недействителен")
                return []
    return []

# Маппинг league_id → ключ Odds API (пробуем по порядку)
ODDS_SPORT_KEYS = {
    # ── Топ-5 лиг ──────────────────────────────────────────
    39:  ["soccer_england_premier_league", "soccer_epl",
          "soccer_england_league_cup", "soccer_uk_premiership"],
    140: ["soccer_spain_la_liga", "soccer_spain_primera_division"],
    135: ["soccer_italy_serie_a"],
    78:  ["soccer_germany_bundesliga", "soccer_germany_bundesliga1"],
    61:  ["soccer_france_ligue_one", "soccer_france_ligue_1"],
    # ── Еврокубки ──────────────────────────────────────────
    2:   ["soccer_uefa_champs_league", "soccer_uefa_champions_league"],
    3:   ["soccer_uefa_europa_league"],
    848: ["soccer_uefa_europa_conference_league"],
    # ── Кубки ──────────────────────────────────────────────
    45:  ["soccer_fa_cup", "soccer_england_fa_cup"],
    48:  ["soccer_league_cup", "soccer_efl_cup", "soccer_england_league_cup"],
    137: ["soccer_spain_copa_del_rey", "soccer_copa_del_rey"],
    9:   ["soccer_italy_coppa_italia", "soccer_coppa_italia"],
    81:  ["soccer_germany_dfb_pokal", "soccer_dfb_pokal"],
    65:  ["soccer_france_coupe_de_france", "soccer_coupe_de_france"],
    276: ["soccer_russia_premier_league"],   # Кубок России (ключ совпадает с РПЛ в Odds API)
    210: ["soccer_turkey_cup"],
    560: ["soccer_portugal_cup"],
    # ── Другие лиги ────────────────────────────────────────
    88:  ["soccer_netherlands_eredivisie"],
    94:  ["soccer_portugal_primeira_liga"],
    203: ["soccer_turkey_super_league", "soccer_turkey_super_lig"],
    235: ["soccer_russia_premier_league"],
    # 370 (ФНЛ): нет ключа в Odds API — это Д2, не покрывается → используются расчётные коэф
    141: ["soccer_spain_segunda_division", "soccer_spain_segunda"],
    179: ["soccer_scotland_premiership"],
    144: ["soccer_belgium_first_div", "soccer_belgium_pro_league"],
    40:  ["soccer_england_championship"],
    207: ["soccer_switzerland_super_league"],
    172: ["soccer_poland_ekstraklasa"],
    333: ["soccer_greece_super_league"],
    197: ["soccer_serbia_superliga"],
    271: ["soccer_denmark_superliga"],
    307: ["soccer_saudi_premier_league"],
}

def fetch_odds_api(league_id: int, home_name: str, away_name: str) -> dict:
    """
    Коэффициенты через The Odds API.
    Возвращает dict с ключами: "1","X","2","over_2.5","under_2.5","eh_home_+1" и др.
    При неудаче — пустой dict.
    """
    candidates = ODDS_SPORT_KEYS.get(league_id, [])
    if not candidates:
        return {}                     # лига не поддерживается Odds API

    # ── Получаем список активных спортов ───────────────────────────
    available = _get_odds_sports()
    if available is None:
        available = []

    # Подбираем sport_key: сначала ищем в активных, потом пробуем любой кандидат
    sport_key = next((k for k in candidates if k in available), None)
    if not sport_key:
        # Не нашли в available — попробуем первый кандидат напрямую
        sport_key = candidates[0]

    markets_to_try = ["h2h,totals,spreads", "h2h,totals", "h2h"]
    data = None

    global _odds_api_auth_ok
    if not _odds_api_auth_ok:
        return {}   # ключ уже проверен — не тратим запросы

    for api_key in [k for k in [ODDS_API_KEY, ODDS_API_KEY2 if ODDS_API_KEY2 else None] if k]:
        if data:
            break
        _key_failed = False
        for mset in markets_to_try:
            if _key_failed:
                break
            url = (f"https://api.the-odds-api.com/v4/sports/{sport_key}/odds/"
                   f"?apiKey={api_key}&regions=eu,uk&markets={mset}"
                   f"&oddsFormat=decimal&dateFormat=iso")
            resp = _http(url)

            if isinstance(resp, list):
                data = resp
                break

            if resp is None:
                # _http вернул None — вероятно 401 или сеть
                # Проверим статус через быстрый запрос к /sports
                _test = _http(f"https://api.the-odds-api.com/v4/sports/?apiKey={api_key}")
                if _test is None:
                    # 401 или сеть — прекращаем пробовать этот ключ
                    if _odds_api_auth_ok:
                        print(f"  🔑 Odds API ключ недействителен — используем расчётные коэф")
                        _odds_api_auth_ok = False
                    return {}
                _key_failed = True
                continue

            if isinstance(resp, dict):
                code = resp.get("error_code", "")
                msg  = resp.get("message", "")
                if code in ("INVALID_KEY", "UNAUTHORIZED"):
                    _odds_api_auth_ok = False
                    print(f"  🔑 Odds API: неверный ключ — используем расчётные коэф")
                    return {}
                if "QUOTA_EXCEEDED" in code or "quota" in msg.lower():
                    print(f"  ⚠️  Odds API: квота исчерпана")
                    return {}
                if "INVALID_MARKET" in code or "not supported" in msg.lower():
                    continue
                continue

    if not isinstance(data, list) or not data:
        return {}

    # ── Нормализация имён ──────────────────────────────────────────
    _ALIAS = {
        "wolverhampton wanderers":"wolverhampton","wolves":"wolverhampton",
        "tottenham hotspur":"tottenham","spurs":"tottenham",
        "manchester city":"man city","manchester united":"man utd",
        "newcastle united":"newcastle","west ham united":"west ham",
        "nottingham forest":"nottingham","brighton & hove albion":"brighton",
        "afc bournemouth":"bournemouth","sheffield united":"sheffield utd",
        "sheffield wednesday":"sheffield wed","leeds united":"leeds",
        "hull city":"hull","sunderland afc":"sunderland",
        "athletic club":"athletic bilbao",
        "atletico madrid":"atletico","atlético madrid":"atletico",
        "borussia dortmund":"dortmund","bayer leverkusen":"leverkusen",
        "bayer 04 leverkusen":"leverkusen","rb leipzig":"leipzig",
        "eintracht frankfurt":"frankfurt","vfb stuttgart":"stuttgart",
        "sv werder bremen":"werder","fc augsburg":"augsburg",
        "1. fsv mainz 05":"mainz","hamburger sv":"hamburg",
        "paris saint-germain":"psg","paris sg":"psg",
        "olympique marseille":"marseille","olympique lyonnais":"lyon",
        "losc lille":"lille","stade rennais":"rennes",
        "sl benfica":"benfica","sporting cp":"sporting","fc porto":"porto",
        "psv eindhoven":"psv","az alkmaar":"az","fc twente":"twente",
        "fc utrecht":"utrecht","nec nijmegen":"nec",
        "inter milan":"inter","ac milan":"milan","ss lazio":"lazio",
        "as roma":"roma","hellas verona":"verona",
        "real sociedad":"sociedad","real betis":"betis",
        "celta vigo":"celta","rayo vallecano":"rayo",
        "dundee united":"dundee utd","dundee fc":"dundee",
        "st mirren":"st mirren","bristol city":"bristol",
        "queens park rangers":"qpr","preston north end":"preston",
        "coventry city":"coventry","stoke city":"stoke",
        "birmingham city":"birmingham","norwich city":"norwich",
        "swansea city":"swansea","cardiff city":"cardiff",
        "middlesbrough fc":"middlesbrough",
        "cska moscow":"cska","lokomotiv moscow":"lokomotiv",
        "spartak moscow":"spartak","dynamo moscow":"dynamo",
        "zenit st. petersburg":"zenit","rubin kazan":"rubin",
        "ural yekaterinburg":"ural","fk rostov":"rostov",
    }
    _STOP = {"fc","sc","afc","cf","city","united","the","de","real","1.","sv","as","ss","vfl","tsg","vfb","1.fc"}

    def _norm(s: str) -> str:
        s = s.lower().strip()
        for sfx in [" fc"," cf"," sc"," afc"," bc"," sv"," ac"," 1."]:
            if s.endswith(sfx):
                s = s[:-len(sfx)].strip()
        return _ALIAS.get(s, s)

    def _words(s: str) -> set:
        return set(_norm(s).split()) - _STOP

    def _match(a: str, b: str) -> bool:
        na, nb = _norm(a), _norm(b)
        if na == nb:
            return True
        wa, wb = _words(a), _words(b)
        if wa and wb and len(wa & wb) >= 1:
            return True
        if len(na) >= 5 and (na in nb or nb in na):
            return True
        return False

    hn = home_name.lower()
    an = away_name.lower()

    for event in data:
        eh = event.get("home_team", "")
        ea = event.get("away_team", "")
        if _match(hn, eh) and _match(an, ea):
            return _parse_odds_api(event)
        if _match(hn, ea) and _match(an, eh):
            return _parse_odds_api(event)   # перевёрнутый порядок

    return {}


def _parse_odds_api(event: dict) -> dict:
    """
    Парсим ответ The Odds API в наш формат.
    Берём МАКСИМАЛЬНЫЙ коэффициент из всех букмекеров —
    это реальный «лучший доступный» рынок.
    """
    pinnacle: dict = {}   # линия Pinnacle — эталон
    best:     dict = {}   # лучший коэф среди всех букмекеров

    home_team = event.get("home_team", "")
    away_team = event.get("away_team", "")

    for bk in event.get("bookmakers", []):
        is_pin = bk.get("key", "") == "pinnacle"
        for market in bk.get("markets", []):
            key      = market.get("key", "")
            outcomes = market.get("outcomes", [])

            if key == "h2h":
                for o in outcomes:
                    p = _f(o.get("price"))
                    n = o.get("name", "")
                    if not p: continue
                    if n == home_team:
                        k = "1"
                    elif n == "Draw":
                        k = "X"
                    elif n == away_team:
                        k = "2"
                    else:
                        continue
                    best[k] = _max(best.get(k), p)
                    if is_pin:
                        pinnacle[k] = p

            elif key == "totals":
                for o in outcomes:
                    p  = _f(o.get("price"))
                    nm = o.get("name", "")
                    pt = str(o.get("point", ""))
                    if not p or not pt: continue
                    k = f"over_{pt}" if nm == "Over" else f"under_{pt}" if nm == "Under" else None
                    if not k: continue
                    best[k] = _max(best.get(k), p)
                    if is_pin:
                        pinnacle[k] = p

            elif key == "btts":
                for o in outcomes:
                    p = _f(o.get("price"))
                    n = o.get("name", "").strip()
                    if not p: continue
                    if n in ("Yes", "Both Teams To Score"):
                        k = "btts_yes"
                    elif n in ("No", "One or Neither"):
                        k = "btts_no"
                    else:
                        k = None
                    if not k: continue
                    best[k] = _max(best.get(k), p)
                    if is_pin: pinnacle[k] = p

            # ── УГЛОВЫЕ ────────────────────────────────────────
            elif key in ("alternate_totals", "totals") and "corner" in key.lower():
                for o in outcomes:
                    p  = _f(o.get("price"))
                    nm = o.get("name", "")
                    pt = str(o.get("point", ""))
                    if not p or not pt: continue
                    k = f"corners_over_{pt}" if nm=="Over" else f"corners_under_{pt}" if nm=="Under" else None
                    if k:
                        best[k] = _max(best.get(k), p)
                        if is_pin: pinnacle[k] = p

            # ── ЖЁЛТЫЕ КАРТОЧКИ ────────────────────────────────
            elif "card" in key.lower():
                for o in outcomes:
                    p  = _f(o.get("price"))
                    nm = o.get("name", "")
                    pt = str(o.get("point", ""))
                    if not p or not pt: continue
                    # home/away cards
                    if home_team.lower() in nm.lower():
                        base_k = "yc_h"
                    elif away_team.lower() in nm.lower():
                        base_k = "yc_a"
                    else:
                        base_k = "yc"
                    k = f"{base_k}_over_{pt}" if nm.endswith("Over") else f"{base_k}_under_{pt}" if nm.endswith("Under") else None
                    if k:
                        best[k] = _max(best.get(k), p)

            elif key == "spreads":
                # Asian + European Handicap от Odds API
                for o in outcomes:
                    p  = _f(o.get("price"))
                    nm = o.get("name", "")
                    pt = o.get("point")
                    if not p or pt is None: continue
                    try:
                        hdp = float(pt)
                    except (TypeError, ValueError):
                        continue
                    # Сторона
                    hn_l = home_team.lower(); an_l = away_team.lower(); nm_l = nm.lower()
                    if nm == home_team or nm_l in hn_l or (len(nm_l)>=4 and nm_l in hn_l):
                        side = "home"
                    elif nm == away_team or nm_l in an_l or (len(nm_l)>=4 and nm_l in an_l):
                        side = "away"
                    else:
                        side = "home" if o.get("name","").lower() not in an_l else "away"
                    # Азиатский гандикап (дробные)
                    if abs(hdp) in (0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 1.75, 2.0, 2.25, 2.5):
                        sign = f"{hdp:+.2f}".replace(".00","").replace("+0.","0.")
                        if side == "home":
                            k = f"ah_home_{sign}"
                        else:
                            k = f"ah_away_{sign}"
                        best[k] = _max(best.get(k), p)
                        if is_pin: pinnacle[k] = p
                    # Европейский гандикап (целые) — расчёт вероятностей
                    if hdp == float(int(hdp)) and abs(hdp) in (1.0, 2.0):
                        hcp_i = int(hdp)
                        sign_s = f"+{hcp_i}" if hcp_i > 0 else str(hcp_i)
                        # home с гандикапом hcp_i → если side="home", hdp<0 означает фора гостей
                        if side == "home":
                            k_eh = f"eh_home_{sign_s}"
                        else:
                            k_eh = f"eh_away_{sign_s}"
                        best[k_eh] = _max(best.get(k_eh), p)
                        if is_pin: pinnacle[k_eh] = p

            elif key == "draw_no_bet":
                for o in outcomes:
                    p = _f(o.get("price"))
                    n = o.get("name", "").lower()
                    if not p: continue
                    # name = имя команды (хозяин или гость)
                    if _event_home and any(w in n for w in _event_home.lower().split()[:2]):
                        k = "dnb_home"
                    elif _event_away and any(w in n for w in _event_away.lower().split()[:2]):
                        k = "dnb_away"
                    else:
                        k = None
                    if k:
                        best[k] = _max(best.get(k), p)
                        if is_pin: pinnacle[k] = p

            elif key == "double_chance":
                for o in outcomes:
                    p = _f(o.get("price"))
                    n = o.get("name", "")
                    if not p: continue
                    k = ("dc_1x" if n in ("Home/Draw","1X") else
                         "dc_12" if n in ("Home/Away","12") else
                         "dc_x2" if n in ("Draw/Away","X2") else None)
                    if k:
                        best[k] = _max(best.get(k), p)
                        if is_pin: pinnacle[k] = p

    # Приоритет: если Pinnacle есть — используем его линию для расчёта валуя.
    # Pinnacle не держит мусора, его линия = реальная рыночная вероятность.
    # При этом в качестве коэффициента для ставки берём ЛУЧШИЙ из всех букмекеров.
    if pinnacle:
        # Возвращаем: ключи из Pinnacle (как базовые вероятности),
        # но ставочный коэф — максимальный доступный
        merged = {}
        for k, pin_odds in pinnacle.items():
            # Для расчёта edge используем Pinnacle (честная линия)
            # Для фактической ставки — лучший коэф
            merged[k] = pin_odds          # базовая линия (edge от неё)
            best_k = best.get(k, pin_odds)
            if best_k > pin_odds:
                # Лучший коэф лучше Pinnacle — это дополнительный бонус
                merged[f"best_{k}"] = best_k
        return merged
    # Pinnacle недоступен — берём лучший коэф из всех
    return best

def fetch_odds(fixture_id: int, league_id: int = 0,
               home_name: str = "", away_name: str = "") -> dict:
    """
    Коэффициенты (приоритет):
    1) Pinnacle Guest API — острая линия, без депозита
    2) The Odds API — лучший коэф из нескольких букмекеров
    3) API-Football — если есть квота AF
    """
    date_str = datetime.date.today().isoformat()

    # ── 0. Ручные коэфы (если введены через 'manual') ───────────
    if home_name and away_name:
        manual = match_manual_odds(home_name, away_name)
        if manual and manual.get("1"):
            print(f"      ✋ Ручные коэфы: 1={manual.get('1')} X={manual.get('X')} 2={manual.get('2')}")
            return manual

    # ── 1. Pinnacle Guest (ЭТАЛОН — без регистрации) ─────────
    if home_name and away_name:
        pg = fetch_pinnacle_guest_odds(home_name, away_name, date_str)
        if pg and pg.get("1"):
            return pg

    # ── 2. The Odds API ───────────────────────────────────────
    if league_id and home_name and away_name:
        odds = fetch_odds_api(league_id, home_name, away_name)
        if odds:
            return odds

    # ── 2б. SofaScore odds (Pinnacle/bet365 — бесплатно!) ─────
    if home_name and away_name:
        sf = fetch_sofascore_odds(home_name, away_name, date_str)
        if sf and sf.get("1"):
            print(f"      📊 SofaScore: 1={sf.get('1')} X={sf.get('X')} 2={sf.get('2')}")
            return sf

    # ── 3. API-Football (расходует квоту) ─────────────────────
    if _af_quota_ok:
        for params in ({"fixture": fixture_id, "bookmaker": 8},
                       {"fixture": fixture_id}):
            resp = _af_resp("odds", params)
            time.sleep(6)
            if resp:
                return _parse_odds(resp)
    return {}

def _parse_odds(resp: list) -> dict:
    odds = {}
    for item in resp:
        for bk in item.get("bookmakers", []):
            for bet in bk.get("bets", []):
                n = bet.get("name", "")
                v = bet.get("values", [])
                # 1X2
                if any(x in n for x in ("Match Winner","1X2","Home/Draw/Away")):
                    for b in v:
                        p = _f(b.get("odd"))
                        val = b.get("value","")
                        if p:
                            if val in ("Home","1"):    odds["1"] = _max(odds.get("1"), p)
                            elif val in ("Draw","X"):  odds["X"] = _max(odds.get("X"), p)
                            elif val in ("Away","2"):  odds["2"] = _max(odds.get("2"), p)
                # Тотал
                elif any(x in n for x in ("Goals Over/Under","Total Goals","Over/Under")):
                    for b in v:
                        raw = b.get("value",""); p = _f(b.get("odd"))
                        if p and raw:
                            if "Over" in raw:
                                ln = raw.replace("Over","").strip()
                                try: float(ln); odds[f"over_{ln}"] = _max(odds.get(f"over_{ln}"), p)
                                except: pass
                            elif "Under" in raw:
                                ln = raw.replace("Under","").strip()
                                try: float(ln); odds[f"under_{ln}"] = _max(odds.get(f"under_{ln}"), p)
                                except: pass
                # BTTS
                elif any(x in n for x in ("Both Teams","BTTS","both_teams")):
                    for b in v:
                        p   = _f(b.get("price") or b.get("odd"))
                        val = b.get("name","") or b.get("value","")
                        if p:
                            if val in ("Yes","Да"):   odds["btts_yes"] = _max(odds.get("btts_yes"), p)
                            elif val in ("No","Нет"): odds["btts_no"]  = _max(odds.get("btts_no"),  p)
                # Фора 0
                elif "Фора 0" in n or "Фора 0" in n:
                    for b in v:
                        p = _f(b.get("price") or b.get("odd"))
                        val = (b.get("value","") or b.get("name",""))
                        if not p: continue
                        if val in ("Home","1","Home Team"):
                            odds["dnb_home"] = _max(odds.get("dnb_home"), p)
                        elif val in ("Away","2","Away Team"):
                            odds["dnb_away"] = _max(odds.get("dnb_away"), p)
                # Двойной шанс
                elif any(x in n for x in ("Double Chance",)):
                    for b in v:
                        p   = _f(b.get("price") or b.get("odd"))
                        val = (b.get("name","") or b.get("value",""))
                        if not p: continue
                        if val in ("1X","Home/Draw"):   odds["dc_1x"] = _max(odds.get("dc_1x"), p)
                        elif val in ("12","Home/Away"): odds["dc_12"] = _max(odds.get("dc_12"), p)
                        elif val in ("X2","Draw/Away"): odds["dc_x2"] = _max(odds.get("dc_x2"), p)
                # Индивидуальный тотал команды
                elif any(x in n for x in ("Player Goals","Team Goals","To Score","Goals",
                                          "Total Goals Home","Total Goals Away")):
                    for b in v:
                        raw = str(b.get("value","") or b.get("name","") or ""); p = _f(b.get("price") or b.get("odd"))
                        if not p or not raw: continue
                        raw_l = raw.lower()
                        # Определяем команду и линию
                        try:
                            # Формат: "Home Over 1.5", "Away Under 0.5" и т.д.
                            parts = raw.split()
                            if "Home" in parts or "home" in raw_l:
                                side = "h"
                            elif "Away" in parts or "away" in raw_l:
                                side = "a"
                            else:
                                continue
                            if "Over" in raw or "over" in raw_l:
                                direction = "over"
                            elif "Under" in raw or "under" in raw_l:
                                direction = "under"
                            else:
                                continue
                            # Ищем число
                            nums = [x for x in parts if x.replace(".","").isdigit()]
                            if not nums: continue
                            ln = float(nums[-1])
                            if ln not in (0.5, 1.5, 2.5): continue
                            key = f"iteam_{side}_{direction}_{ln}"
                            odds[key] = _max(odds.get(key), p)
                        except Exception: pass

                # Забьёт в первом тайме / оба тайма
                elif any(x in n for x in ("To Score in 1st Half","Score First Half",
                                          "Both Halves","Score in Both")):
                    for b in v:
                        p = _f(b.get("price") or b.get("odd"))
                        nm = (b.get("value","") or b.get("name","")).lower()
                        if not p: continue
                        if "home" in nm or "1" == nm:
                            if "both" in n.lower():
                                odds["both_halves_h"] = _max(odds.get("both_halves_h"), p)
                            else:
                                k = "score_1h_h_yes" if any(x in nm for x in ("yes","to score","да")) else "score_1h_h_no"
                                odds[k] = _max(odds.get(k), p)
                        elif "away" in nm or "2" == nm:
                            if "both" in n.lower():
                                odds["both_halves_a"] = _max(odds.get("both_halves_a"), p)
                            else:
                                k = "score_1h_a_yes" if any(x in nm for x in ("yes","to score","да")) else "score_1h_a_no"
                                odds[k] = _max(odds.get(k), p)

                # Тотал первого тайма
                elif any(x in n for x in ("1st Half","Half Time Total","First Half")):
                    for b in v:
                        raw = (b.get("name","") or b.get("value","")); p = _f(b.get("price") or b.get("odd"))
                        if p and raw:
                            if "Over" in raw or "Больше" in raw:
                                ln = raw.replace("Over","").replace("Больше","").strip()
                                try: odds[f"1h_over_{float(ln)}"] = _max(odds.get(f"1h_over_{float(ln)}"), p)
                                except: pass
                            elif "Under" in raw or "Меньше" in raw:
                                ln = raw.replace("Under","").replace("Меньше","").strip()
                                try: odds[f"1h_under_{float(ln)}"] = _max(odds.get(f"1h_under_{float(ln)}"), p)
                                except: pass
                # Исход первого тайма
                elif any(x in n for x in ("1st Half Result","HT Result","Half Time Result")):
                    ht = ""
                    at = ""
                    for b in v:
                        p   = _f(b.get("price") or b.get("odd"))
                        val = (b.get("name","") or b.get("value",""))
                        if not p: continue
                        if val in ("Home","1"):    odds["1h_home"] = _max(odds.get("1h_home"), p)
                        elif val in ("Draw","X"):  odds["1h_draw"] = _max(odds.get("1h_draw"), p)
                        elif val in ("Away","2"):  odds["1h_away"] = _max(odds.get("1h_away"), p)
                # Гандикап / Spreads
                elif any(x in n for x in ("Spread","Handicap","Asian","European")):
                    home_team = ""
                    away_team = ""
                    for b in v:
                        # Формат Odds API: {"name": "Team Name", "point": -1.5, "price": 1.85}
                        team_raw = b.get("name","").lower()
                        raw_val  = b.get("value","")
                        p        = _f(b.get("price") or b.get("odd"))
                        point    = b.get("point")
                        if not p:
                            continue
                        try:
                            # Определяем гандикап
                            if point is not None:
                                hcap_f = float(point)
                            elif raw_val:
                                parts  = raw_val.split()
                                hcap_f = float(parts[-1]) if parts else 0
                            else:
                                continue
                            # Только целые линии (-2,-1,+1,+2) для Фораа
                            hcap = int(hcap_f)
                            if hcap not in (-2,-1,1,2) or hcap_f != hcap:
                                continue
                            sign = f"+{hcap}" if hcap>0 else str(hcap)
                            # Определяем сторону по имени команды
                            if team_raw and home_team:
                                # Ищем совпадение хотя бы одного слова
                                t_words = set(team_raw.split()) - {"fc","sc","cf","the","de"}
                                h_words = set(home_team.split()) - {"fc","sc","cf","the","de"}
                                a_words = set(away_team.split()) - {"fc","sc","cf","the","de"}
                                if t_words & h_words:
                                    side = "home"
                                elif t_words & a_words:
                                    side = "away"
                                else:
                                    # Фоллбэк по порядку
                                    idx = list(v).index(b) if b in v else -1
                                    side = "home" if idx == 0 else "away"
                            else:
                                idx = list(v).index(b) if b in v else -1
                                side = "home" if idx == 0 else "away"
                            if side == "home":   odds[f"eh_home_{sign}"] = _max(odds.get(f"eh_home_{sign}"), p)
                            elif side == "away": odds[f"eh_away_{sign}"] = _max(odds.get(f"eh_away_{sign}"), p)
                            elif side == "draw": odds[f"eh_draw_{sign}"] = _max(odds.get(f"eh_draw_{sign}"), p)
                        except Exception:
                            pass
    return odds

def _f(v) -> Optional[float]:
    try: f = float(v); return f if f > 1.01 else None
    except: return None
def _max(a, b): return b if a is None else max(a, b)



# ══════════════════════════════════════════════════════════════
#  📈  ОТКРЫТИЕ ЛИНИИ — обнаружение умных денег
#  Сохраняем первый коэф и сравниваем с текущим.
#  Линия упала К НАМ (+0.10) = sharp money за нас → бонус
#  Линия выросла ПРОТИВ нас (-0.12) = sharp money против → фильтр
# ══════════════════════════════════════════════════════════════
OPENING_ODDS_FILE = "opening_odds.json"
_opening_odds_db: dict = {}

def _load_opening_odds():
    global _opening_odds_db
    try:
        if os.path.exists(OPENING_ODDS_FILE):
            with open(OPENING_ODDS_FILE, encoding="utf-8") as f:
                _opening_odds_db = json.load(f)
    except Exception:
        pass

def save_opening_odds(fixture_id: int, match_name: str, odds: dict):
    """
    Сохраняет открывающий коэффициент:
    1) В _opening_odds_db (RAM) — для текущего скана
    2) В файл line_history.json — для сравнения между запусками
    BUGFIX: было два дублирующихся определения функции.
    Python использует последнее → get_line_movement не видел запись в RAM.
    """
    key = str(fixture_id)
    if key in _opening_odds_db:
        return   # уже сохранён в этом запуске
    _opening_odds_db[key] = {
        "match":     match_name,
        "odds":      odds,
        "saved_at":  datetime.datetime.now().isoformat(timespec="minutes"),
    }
    # Записываем в RAM-файл (быстро)
    try:
        with open(OPENING_ODDS_FILE, "w", encoding="utf-8") as f:
            json.dump(_opening_odds_db, f, ensure_ascii=False, indent=2)
    except Exception:
        pass
    # Также в line_history.json для межсессионного отслеживания
    try:
        hist = {}
        if os.path.exists(_LINE_FILE):
            with open(_LINE_FILE, encoding="utf-8") as f:
                hist = json.load(f)
        if key not in hist:
            hist[key] = {
                "match":   match_name,
                "opening": odds,
                "saved_at": datetime.datetime.now().isoformat(timespec="seconds"),
            }
            with open(_LINE_FILE, "w", encoding="utf-8") as f:
                json.dump(hist, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

def get_line_movement(fixture_id: int, current_odds: dict) -> dict:
    """
    Сравнивает текущие коэф с открытием.
    diff < 0 → коэф упал → умные деньги ЗА этот исход (sharp money).
    BUGFIX: раньше был дубль функции — Python брал последний, который
    читал файл. Теперь: читаем из RAM (_opening_odds_db), fallback → файл.
    """
    key      = str(fixture_id)
    # 1. Пробуем RAM (быстро, текущий скан)
    opening  = _opening_odds_db.get(key, {}).get("odds", {})
    # 2. Fallback: файл (межсессионное движение)
    if not opening and os.path.exists(_LINE_FILE):
        try:
            with open(_LINE_FILE, encoding="utf-8") as f:
                hist = json.load(f)
            opening = hist.get(key, {}).get("opening", {})
        except Exception:
            pass
    if not opening:
        return {}
    movements = {}
    for k, curr in current_odds.items():
        if k.startswith("best_"):
            continue
        op = opening.get(k)
        if op and curr and abs(curr - op) >= 0.03:   # снизили с 0.05 до 0.03
            movements[k] = round(curr - op, 3)
    return movements

def sharp_money_bonus(movements: dict, signal_key: str) -> float:
    """
    Если линия УПАЛА к нашему сигналу (умные деньги за нас) →
    возвращает бонус к edge (до +0.03).
    """
    mv = movements.get(signal_key, 0)
    if mv <= -0.15:   return 0.030   # сильное движение за нас
    elif mv <= -0.08: return 0.015
    return 0.0

# ══════════════════════════════════════════════════════════════
#  🏥  ТРАВМЫ И ДИСКВАЛИФИКАЦИИ
# ══════════════════════════════════════════════════════════════
# Важность игроков по позиции (снижение xG при отсутствии)
_POSITION_IMPACT = {
    "Goalkeeper": 0.05,   # отсутствие вратаря: +5% голов пропустят
    "Defender":   0.04,
    "Midfielder": 0.06,
    "Attacker":   0.09,   # нападающий = самый критичный
}

_injury_cache: dict = {}

def fetch_injuries(fixture_id: int, team_id: int) -> float:
    """
    Возвращает коэффициент штрафа за травмы (0.75–1.0).
    1.0 = все здоровы, 0.80 = ключевые игроки травмированы.
    Расходует 1 запрос.
    """
    if not _af_quota_ok or not fixture_id or not team_id:
        return 1.0

    cache_key = f"inj_{fixture_id}_{team_id}"
    if cache_key in _injury_cache:
        return _injury_cache[cache_key]

    resp = _af_resp("injuries", {"fixture": fixture_id, "team": team_id})
    if not resp or not isinstance(resp, list):
        return 1.0

    penalty = 1.0
    for player in resp:
        try:
            pos    = player.get("player", {}).get("type", "")   # "Goalkeeper" / "Midfielder" etc
            reason = player.get("player", {}).get("reason", "")
            # Пропускаем сомнительные — учитываем только точные
            if reason in ("Missing Fixture", "Suspended", "Injured"):
                impact  = _POSITION_IMPACT.get(pos, 0.04)
                penalty = max(0.72, penalty - impact)
        except Exception:
            continue

    _injury_cache[cache_key] = round(penalty, 3)
    return round(penalty, 3)


# ══════════════════════════════════════════════════════════════
#  📊  ELO-РЕЙТИНГ КОМАНД
#  Классический Elo с поправкой на результат и xG.
#  Стартовый рейтинг 1500, K=32, обновляется из results.json.
# ══════════════════════════════════════════════════════════════
ELO_FILE = "elo_ratings.json"
_ELO: dict = {}
_ELO_K     = 32    # коэффициент обновления
_ELO_BASE  = 1500  # стартовый рейтинг

def _load_elo() -> dict:
    try:
        if os.path.exists(ELO_FILE):
            with open(ELO_FILE, encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return {}

def _save_elo(ratings: dict):
    try:
        with open(ELO_FILE, "w", encoding="utf-8") as f:
            json.dump(ratings, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


# ══════════════════════════════════════════════════════════════
#  ⭐  CLUBELO.COM — автообновление Elo рейтингов
#  Бесплатно, без ключа. Обновляется после каждого тура.
#  API: http://clubelo.com/API/today
#  Формат CSV: Rank,Club,Country,Level,Elo,From,To
# ══════════════════════════════════════════════════════════════
_CLUBELO_LAST_UPDATE = ""   # дата последнего обновления

def fetch_clubelo_ratings() -> bool:
    """
    Скачивает актуальные Elo с ClubElo.com и сохраняет в elo_ratings.json.
    Вызывается раз в неделю (при запуске бота).
    Возвращает True если успешно обновил.
    """
    global _ELO, _CLUBELO_LAST_UPDATE

    today = datetime.date.today().isoformat()
    if _CLUBELO_LAST_UPDATE == today:
        return True   # уже обновляли сегодня

    try:
        # ClubElo отдаёт CSV — пробуем urllib3, fallback → _http_raw
        text = ""
        try:
            r = _pool.request(
                "GET", "http://clubelo.com/API/today",
                headers={"User-Agent": "Mozilla/5.0", "Accept": "text/csv,text/plain,*/*"},
                timeout=urllib3.Timeout(connect=10, read=20),
            )
            if r.status == 200:
                text = r.data.decode("utf-8", errors="ignore")
        except Exception:
            pass
        # Fallback: HTTPS зеркало
        if not text or len(text) < 200:
            text = _http_raw("https://api.clubelo.com/today") or ""
        if not text or len(text) < 200:
            return False

        # Парсим CSV: Rank,Club,Country,Level,Elo,From,To
        lines = text.strip().split("\n")
        if len(lines) < 10:
            return False

        new_elo = {}
        for line in lines[1:]:   # пропускаем заголовок
            parts = line.strip().split(",")
            if len(parts) < 5:
                continue
            try:
                club = parts[1].strip().lower()
                elo_val = float(parts[4].strip())
                if 1000 <= elo_val <= 2200:   # разумный диапазон
                    new_elo[club] = round(elo_val, 0)
            except (ValueError, IndexError):
                continue

        if len(new_elo) < 100:   # должно быть 600+ клубов
            return False

        # Обновляем глобальный _ELO и сохраняем
        _ELO.update(new_elo)
        _save_elo(_ELO)
        _CLUBELO_LAST_UPDATE = today
        print(f"  ⭐ ClubElo: обновлено {len(new_elo)} рейтингов (всего {len(_ELO)})")
        return True

    except Exception as e:
        print(f"  ⚠️  ClubElo: {str(e)[:60]} — используем локальный elo_ratings.json")
        return False

def _elo_expected(ra: float, rb: float) -> float:
    """Ожидаемый результат для команды A против B."""
    return 1.0 / (1.0 + 10 ** ((rb - ra) / 400.0))

def update_elo(home: str, away: str, hg: int, ag: int,
               home_adv: float = 100.0):
    """
    Обновляет Elo после матча.
    home_adv = бонус хозяину (обычно 50-100 очков).
    """
    global _ELO
    rh = _ELO.get(home.lower(), _ELO_BASE) + home_adv
    ra = _ELO.get(away.lower(), _ELO_BASE)

    exp_h = _elo_expected(rh, ra)
    exp_a = 1.0 - exp_h

    if hg > ag:   sh, sa = 1.0, 0.0
    elif hg == ag: sh, sa = 0.5, 0.5
    else:          sh, sa = 0.0, 1.0

    _ELO[home.lower()] = round(_ELO.get(home.lower(), _ELO_BASE) + _ELO_K * (sh - exp_h), 1)
    _ELO[away.lower()] = round(_ELO.get(away.lower(), _ELO_BASE) + _ELO_K * (sa - exp_a), 1)
    _save_elo(_ELO)

def elo_win_prob(home: str, away: str) -> tuple:
    """
    Возвращает (p_home_win, p_draw, p_away_win) на основе Elo.
    Ничья моделируется через нормальное распределение разницы.
    """
    global _ELO
    if not _ELO:
        _ELO = _load_elo()

    rh = _ELO.get(home.lower(), _ELO_BASE) + 100   # бонус хозяину
    ra = _ELO.get(away.lower(), _ELO_BASE)
    exp_h = _elo_expected(rh, ra)

    # Моделируем ничью: вероятность зависит от близости рейтингов
    diff = abs(rh - ra)
    p_draw = max(0.20, min(0.30, 0.27 - diff * 0.0001))
    p_home = exp_h * (1 - p_draw)
    p_away = (1 - exp_h) * (1 - p_draw)

    # Нормализация
    total = p_home + p_draw + p_away
    return (round(p_home/total, 4),
            round(p_draw/total, 4),
            round(p_away/total, 4))

def elo_factor(home: str, away: str) -> float:
    """
    Корректировочный множитель для xG хозяев на основе Elo.
    Сильная команда дома против слабой = больший xG.
    """
    global _ELO
    if not _ELO:
        _ELO = _load_elo()
    rh = _ELO.get(home.lower(), _ELO_BASE)
    ra = _ELO.get(away.lower(), _ELO_BASE)
    diff = rh - ra
    # Каждые 100 очков разницы = ~3% к xG
    factor = 1.0 + diff * 0.0003
    return round(max(0.85, min(factor, 1.18)), 4)

def get_elo_str(team: str) -> str:
    """Строка с рейтингом для отображения."""
    r = _ELO.get(team.lower(), _ELO_BASE)
    return f"Elo:{r:.0f}"


# ══════════════════════════════════════════════════════════════
#  ⚙️  КАЛИБРОВКА МОДЕЛИ ПО ЛИГАМ
#  Серия А != Бундеслига. Разные пороги, разные AVG_H/AVG_A.
# ══════════════════════════════════════════════════════════════
LEAGUE_CALIBRATION = {
    # league_id: {avg_h, avg_a, min_edge, calib_w, home_adv, over25_base}
    # calib_w = вес модели Пуассона (1-calib_w = вес рынка/no-vig)
    # min_edge 0.06: без Pinnacle рынок мягче — можно брать +6% вместо +8%
    39:  {"avg_h":1.62,"avg_a":1.21,"min_edge":0.04,"calib_w":0.50,"home_adv":0.07,"over25":0.56},  # АПЛ
    140: {"avg_h":1.55,"avg_a":1.10,"min_edge":0.04,"calib_w":0.50,"home_adv":0.08,"over25":0.55},  # Ла Лига
    135: {"avg_h":1.51,"avg_a":1.18,"min_edge":0.07,"calib_w":0.48,"home_adv":0.06,"over25":0.50},  # Серия А — КАЛИБРОВКА (ROI=-20%)
    78:  {"avg_h":1.65,"avg_a":1.30,"min_edge":0.04,"calib_w":0.52,"home_adv":0.07,"over25":0.60},  # Бундеслига
    61:  {"avg_h":1.48,"avg_a":1.20,"min_edge":0.07,"calib_w":0.50,"home_adv":0.06,"over25":0.53},  # Лига 1 — КАЛИБРОВКА (ROI=-18%)
    2:   {"avg_h":1.82,"avg_a":1.25,"min_edge":0.05,"calib_w":0.52,"home_adv":0.05,"over25":0.60},  # ЛЧ
    3:   {"avg_h":1.70,"avg_a":1.30,"min_edge":0.05,"calib_w":0.50,"home_adv":0.06,"over25":0.58},  # ЛЕ
    88:  {"avg_h":1.80,"avg_a":1.40,"min_edge":0.10,"calib_w":0.52,"home_adv":0.07,"over25":0.62},  # Эредивизи
    94:  {"avg_h":1.55,"avg_a":1.20,"min_edge":0.13,"calib_w":0.50,"home_adv":0.07,"over25":0.54},  # Примейра — КАЛИБРОВКА min_edge повышен (ROI=-42%)
    203: {"avg_h":1.60,"avg_a":1.35,"min_edge":0.04,"calib_w":0.50,"home_adv":0.08,"over25":0.55},  # Турция
    848: {"avg_h":1.65,"avg_a":1.25,"min_edge":0.05,"calib_w":0.50,"home_adv":0.06,"over25":0.57},  # ЛКЕ
    45:  {"avg_h":1.58,"avg_a":1.22,"min_edge":0.04,"calib_w":0.55,"home_adv":0.07,"over25":0.55},
    48:  {"avg_h":1.60,"avg_a":1.25,"min_edge":0.04,"calib_w":0.55,"home_adv":0.07,"over25":0.56},
    137: {"avg_h":1.65,"avg_a":1.20,"min_edge":0.04,"calib_w":0.55,"home_adv":0.08,"over25":0.57},
    9:   {"avg_h":1.55,"avg_a":1.20,"min_edge":0.04,"calib_w":0.55,"home_adv":0.07,"over25":0.52},
    81:  {"avg_h":1.68,"avg_a":1.28,"min_edge":0.04,"calib_w":0.55,"home_adv":0.07,"over25":0.58},
    65:  {"avg_h":1.50,"avg_a":1.22,"min_edge":0.04,"calib_w":0.55,"home_adv":0.06,"over25":0.53},
    276: {"avg_h":1.52,"avg_a":1.18,"min_edge":0.04,"calib_w":0.58,"home_adv":0.09,"over25":0.51},
    235: {"avg_h":1.55,"avg_a":1.20,"min_edge":0.04,"calib_w":0.58,"home_adv":0.09,"over25":0.52},
    204: {"avg_h":1.55,"avg_a":1.30,"min_edge":0.04,"calib_w":0.52,"home_adv":0.08,"over25":0.54},
    141: {"avg_h":1.52,"avg_a":1.18,"min_edge":0.04,"calib_w":0.52,"home_adv":0.08,"over25":0.53},
    307: {"avg_h":1.70,"avg_a":1.35,"min_edge":0.04,"calib_w":0.55,"home_adv":0.10,"over25":0.58},
    370: {"avg_h":1.45,"avg_a":1.15,"min_edge":0.08,"calib_w":0.58,"home_adv":0.10,"over25":0.48},  # ФНЛ Первая лига
    # FIX: добавлены лиги без калибровки (использовали _DEFAULT_CALIB)
    40:  {"avg_h":1.55,"avg_a":1.25,"min_edge":0.12,"calib_w":0.52,"home_adv":0.07,"over25":0.55},  # Чемпионшип — min_edge повышен (WR=39%,ROI=-33%)
    144: {"avg_h":1.75,"avg_a":1.40,"min_edge":0.04,"calib_w":0.52,"home_adv":0.08,"over25":0.62},  # Бельгия
    172: {"avg_h":1.50,"avg_a":1.25,"min_edge":0.04,"calib_w":0.52,"home_adv":0.08,"over25":0.52},  # Польша
    167: {"avg_h":1.50,"avg_a":1.25,"min_edge":0.04,"calib_w":0.52,"home_adv":0.07,"over25":0.52},  # Чехия
    179: {"avg_h":1.55,"avg_a":1.30,"min_edge":0.04,"calib_w":0.52,"home_adv":0.08,"over25":0.54},  # Шотландия
    197: {"avg_h":1.60,"avg_a":1.35,"min_edge":0.04,"calib_w":0.52,"home_adv":0.09,"over25":0.56},  # Сербия
    207: {"avg_h":1.65,"avg_a":1.30,"min_edge":0.04,"calib_w":0.52,"home_adv":0.07,"over25":0.57},  # Швейцария
    218: {"avg_h":1.70,"avg_a":1.35,"min_edge":0.04,"calib_w":0.52,"home_adv":0.08,"over25":0.59},  # Австрия
    271: {"avg_h":1.60,"avg_a":1.30,"min_edge":0.04,"calib_w":0.52,"home_adv":0.08,"over25":0.56},  # Дания
    333: {"avg_h":1.55,"avg_a":1.35,"min_edge":0.04,"calib_w":0.52,"home_adv":0.09,"over25":0.55},  # Греция
    210: {"avg_h":1.60,"avg_a":1.35,"min_edge":0.04,"calib_w":0.54,"home_adv":0.09,"over25":0.55},  # Кубок Турции
    560: {"avg_h":1.52,"avg_a":1.20,"min_edge":0.04,"calib_w":0.55,"home_adv":0.07,"over25":0.52},  # Кубок Португалии
}

_DEFAULT_CALIB = {"avg_h":1.55,"avg_a":1.20,"min_edge":0.04,"calib_w":0.50,"home_adv":0.07,"over25":0.55}

def get_league_calib(league_id: int) -> dict:
    return LEAGUE_CALIBRATION.get(league_id, _DEFAULT_CALIB)


# ══════════════════════════════════════════════════════════════
#  🔲  УГЛОВЫЕ — СТАТИСТИКА И МОДЕЛЬ
# ══════════════════════════════════════════════════════════════
# Средние угловые по лигам (сезон 2025/26)
CORNERS_AVG = {
    39:  {"home": 5.4, "away": 5.1, "total": 10.5},  # АПЛ
    140: {"home": 5.0, "away": 4.8, "total": 9.8},   # Ла Лига
    135: {"home": 4.7, "away": 4.5, "total": 9.2},   # Серия А
    78:  {"home": 5.6, "away": 5.4, "total": 11.0},  # Бундеслига
    61:  {"home": 4.9, "away": 4.6, "total": 9.5},   # Лига 1
    2:   {"home": 5.2, "away": 5.0, "total": 10.2},  # ЛЧ
    3:   {"home": 5.0, "away": 4.8, "total": 9.8},   # ЛЕ
    848: {"home": 4.8, "away": 4.6, "total": 9.4},   # Лига Конференций
    40:  {"home": 5.2, "away": 5.0, "total": 10.2},  # Чемпионшип
    144: {"home": 5.3, "away": 5.1, "total": 10.4},  # Бельгия
    235: {"home": 4.5, "away": 4.3, "total": 8.8},   # РПЛ
    203: {"home": 5.0, "away": 4.8, "total": 9.8},   # Турция
}
_DEFAULT_CORNERS = {"home": 5.0, "away": 4.8, "total": 9.8}

# Корреляция xG → угловые (коэффициент через регрессию)
# expected_corners_h ≈ xG_h * 3.0 + base_h * 0.6
# expected_corners_a ≈ xG_a * 3.0 + base_a * 0.6
CORNERS_XG_COEFF = 3.0
CORNERS_BASE_W   = 0.60   # вес базовой статистики лиги

def expected_corners(xg_h: float, xg_a: float, league_id: int,
                      atk_h: float = 1.0, atk_a: float = 1.0) -> dict:
    """
    Рассчитывает ожидаемые угловые.
    Использует нормализованную атакующую силу + базу лиги.
    
    atk_h, atk_a — TeamStats.h_gs / AVG_H (нормализованная сила атаки)
    Формула: corners_h = base_h * atk_h^0.60  (субlinear от атаки)
    
    Если xg_h/xg_a заданы — используем их как прокси силы:
    atk_proxy = xg / avg_league_xg
    """
    CORNERS_TOTAL = CORNERS_AVG.get(league_id, _DEFAULT_CORNERS)["total"]
    base_h = CORNERS_TOTAL * 0.52
    base_a = CORNERS_TOTAL * 0.48

    # Атакующая сила: приоритет atk_h/atk_a, иначе из xG
    calib = CORNERS_AVG.get(league_id, _DEFAULT_CORNERS)
    avg_xg_league = 1.55   # средний xG команды в топ лигах
    if atk_h == 1.0 and xg_h > 0:
        atk_h = xg_h / avg_xg_league
    if atk_a == 1.0 and xg_a > 0:
        atk_a = xg_a / avg_xg_league

    # Субlinear зависимость corners от силы атаки
    lam_h = base_h * max(0.5, min(atk_h, 2.5)) ** 0.60
    lam_a = base_a * max(0.5, min(atk_a, 2.5)) ** 0.60

    return {"lam_h": round(lam_h, 2), "lam_a": round(lam_a, 2),
            "lam_total": round(lam_h + lam_a, 2)}


def prob_corners_over(lam_total: float, line: float) -> float:
    """P(corners > line) через Пуассон."""
    k_max = int(line + 0.5)   # floor(line + 0.5) = порог
    p_under = sum(
        math.exp(-lam_total) * lam_total**k / math.factorial(k)
        for k in range(k_max + 1)
    )
    return round(1.0 - p_under, 4)


# Линии угловых для анализа
CORNER_LINES = [8.5, 9.5, 10.5, 11.5]


# ══════════════════════════════════════════════════════════════
#  🟨  ЖЁЛТЫЕ КАРТОЧКИ — СТАТИСТИКА И МОДЕЛЬ
# ══════════════════════════════════════════════════════════════
# Средние ЖК по лигам + типичные линии букмекеров
YELLOW_CARDS_AVG = {
    39:  {"avg": 3.8, "home": 1.9, "away": 1.9, "line": 3.5},  # АПЛ
    140: {"avg": 4.8, "home": 2.4, "away": 2.4, "line": 4.5},  # Ла Лига — высокая
    135: {"avg": 4.2, "home": 2.1, "away": 2.1, "line": 3.5},  # Серия А
    78:  {"avg": 3.5, "home": 1.8, "away": 1.7, "line": 3.5},  # Бундеслига — низкая
    61:  {"avg": 4.0, "home": 2.0, "away": 2.0, "line": 3.5},  # Лига 1
    2:   {"avg": 3.2, "home": 1.6, "away": 1.6, "line": 2.5},  # ЛЧ
    3:   {"avg": 3.5, "home": 1.8, "away": 1.7, "line": 3.5},  # ЛЕ
    203: {"avg": 5.2, "home": 2.6, "away": 2.6, "line": 4.5},  # Турция
    40:  {"avg": 4.5, "home": 2.3, "away": 2.2, "line": 3.5},  # Чемпионшип
    235: {"avg": 4.3, "home": 2.2, "away": 2.1, "line": 3.5},  # РПЛ
    144: {"avg": 3.8, "home": 1.9, "away": 1.9, "line": 3.5},  # Бельгия
}
_DEFAULT_YC = {"avg": 3.9, "home": 2.0, "away": 1.9, "line": 3.5}

# Лиги где ЖК рынок надёжен (P(>line) > 58% → есть перевес)
YC_TRUSTED_LEAGUES = {140, 203, 40, 135}  # Ла Лига, Турция, Чемпионшип, Серия А

def expected_yellow_cards(league_id: int, ref_cards_per_game: float = 0,
                            is_derby: bool = False,
                            is_relegation: bool = False,
                            is_high_stakes: bool = False) -> dict:
    """
    Рассчитывает ожидаемые ЖК с учётом:
    - базы лиги (60% вес)
    - статистики судьи (40% вес если есть)
    - дерби / матч за выживание (+18%)
    - важный матч / кубок (+10%)
    """
    base = YELLOW_CARDS_AVG.get(league_id, _DEFAULT_YC)

    # Блендинг лига + судья
    if ref_cards_per_game > 0:
        lam = base["avg"] * 0.60 + ref_cards_per_game * 0.40
    else:
        lam = base["avg"]

    # Контекстные множители
    if is_derby:          lam *= 1.18   # дерби: +18%
    if is_relegation:     lam *= 1.12   # борьба за выживание: +12%
    if is_high_stakes:    lam *= 1.08   # важный матч: +8%

    # Сигнал только если P(>line) ≥ 60% — иначе нет смысла
    line = base["line"]
    has_edge = (lam >= line * 1.15)   # lambda должен быть на 15% выше линии

    return {
        "lam":       round(lam, 2),
        "lam_home":  round(lam * base["home"] / base["avg"], 2),
        "lam_away":  round(lam * base["away"] / base["avg"], 2),
        "line":      line,
        "has_edge":  has_edge,  # True = генерировать сигнал
    }


def prob_yc_over(lam: float, line: float) -> float:
    """P(total_yc > line) через Пуассон."""
    k_max = int(line + 0.5)
    p_under = sum(
        math.exp(-lam) * lam**k / math.factorial(k)
        for k in range(k_max + 1)
    )
    return round(1.0 - p_under, 4)


def prob_yc_team_over(lam_team: float, line: float) -> float:
    """P(team_yc > line) — индивидуальный тотал команды."""
    return prob_yc_over(lam_team, line)

# ══════════════════════════════════════════════════════════════
#  🎲  МОДЕЛЬ ПУАССОНА
# ══════════════════════════════════════════════════════════════
class Poisson:
    AVG_H = 1.55
    AVG_A = 1.15
    N     = 11

    @staticmethod
    def _p(lam, k):
        return (lam**k) * math.exp(-lam) / math.factorial(k)

    def lambdas(self, h: TeamStats, a: TeamStats, h2h: dict = None,
                league_id: int = 39, first_leg: dict = None):
        """
        Расчёт ожидаемых голов с учётом:
        1. Базовой статистики атаки/обороны
        2. Домашнего преимущества (лига-специфично)
        3. Формы + тренда (домашней/выездной)
        4. H2H истории личных встреч
        5. Elo-рейтинга команд  ← НОВОЕ
        6. Лига-специфичной калибровки  ← НОВОЕ
        """
        calib = get_league_calib(league_id)
        AVG_H = calib["avg_h"]
        AVG_A = calib["avg_a"]
        # Нейтральное среднее лиги — база для расчёта силы команд
        # Устраняет систематический bias: AVG_H > AVG_A не означает
        # что хозяева лучше — это просто исторический эффект поля
        AVG_N = (AVG_H + AVG_A) / 2.0

        # ── БАЗОВЫЕ xG ────────────────────────────────────────
        # Берём ЛУЧШУЮ доступную статистику для каждой роли
        # home_gs/away_gs из TEAM_DB уже разделены по домашним/выездным
        h_gs = h.home_gs if h.home_gs > 0.1 else h.avg_goals_scored
        h_gc = h.home_gc if h.home_gc > 0.1 else h.avg_goals_conceded
        a_gs = a.away_gs if a.away_gs > 0.1 else a.avg_goals_scored
        a_gc = a.away_gc if a.away_gc > 0.1 else a.avg_goals_conceded

        ha = calib.get("home_adv", h.home_advantage)
        # В плей-офф еврокубков (ЛЧ/ЛЕ/ЛК) домашнее преимущество меньше
        if league_id in (2, 3, 848):
            ha = min(ha, 0.03)

        # ── ИНДЕКСЫ СИЛЫ ОТНОСИТЕЛЬНО НЕЙТРАЛЬНОГО СРЕДНЕГО ──
        # Ключевое изменение: используем AVG_N вместо AVG_H/AVG_A
        # → гость, который забивает 1.6/игру в гостях, получает atk_a=1.14
        #   раньше давал atk_a=1.6/1.21=1.32 (завышено из-за AVG_A малого)
        # Диапазоны кэпа — предотвращают экстремальные xG
        atk_h = max(0.45, min(h_gs / AVG_N, 1.90))   # атака хозяев
        def_a = max(0.65, min(a_gc / AVG_N, 1.40))   # оборона гостей
        atk_a = max(0.45, min(a_gs / AVG_N, 1.90))   # атака гостей ← теперь та же шкала
        def_h = max(0.65, min(h_gc / AVG_N, 1.40))   # оборона хозяев

        # Базовые xG: обе команды считаются через одну и ту же AVG_N
        # home_adv (ha) добавляется ТОЛЬКО хозяину — явный эффект поля
        lh = atk_h * def_a * AVG_N * (1.0 + ha)
        la = atk_a * def_h * AVG_N                   # гость без бонуса поля

        # ── ELO-КОРРЕКТИРОВКА (20% вес) ───────────────────────
        ef = elo_factor(h.name, a.name)
        if ef != 1.0:
            lh = round(lh * (1.0 + (ef - 1.0) * 0.40), 4)  # КАЛИБРОВКА: снижен с 0.50→0.40
            la = round(la * (1.0 - (ef - 1.0) * 0.40), 4)  # КАЛИБРОВКА: симметрично с 0.30→0.40

        # ── ФОРМА — берём venue_form если есть ────────────────
        # Домашняя форма хозяина важнее общей
        h_form = h.home_form if h.home_form != 1.0 else h.form_rating
        a_form = a.away_form if a.away_form != 1.0 else a.form_rating

        lh *= h_form * h.attack_trend
        la *= a_form * a.attack_trend
        lh *= a.defense_trend
        la *= h.defense_trend

        # ── H2H — корректировка историей встреч ───────────────
        if h2h and h2h.get("matches", 0) >= 3:
            factor = h2h["h2h_factor"]
            # Применяем частично (50%) — не хотим переоценивать историю
            h2h_adj = 1.0 + (factor - 1.0) * 0.5
            lh *= h2h_adj
            la /= max(h2h_adj, 0.92)   # инверсия для гостей

        # ── ПЕРВАЯ НОГА ПЛЕЙ-ОФФ — контекст 2-й ноги ───────────
        # Команда, которая отстаёт → атакует агрессивнее → +xG
        # Команда, которая ведёт  → может играть осторожнее → -xG
        # Это самый важный фактор в плей-офф матчах!
        if first_leg and first_leg.get("is_second_leg"):
            ph = first_leg.get("pressure_h", 1.0)
            pa = first_leg.get("pressure_a", 1.0)
            lh = round(lh * ph, 4)
            la = round(la * pa, 4)
            _diff = first_leg.get("diff", 0)
            # Дополнительная корректировка тотала:
            # При равном агрегате оба атакуют → тотал выше
            if _diff == 0:
                lh = round(lh * 1.03, 4)
                la = round(la * 1.03, 4)

            # Корректировка тотала по историческому среднему
            hist_total = h2h.get("h2h_avg_total", 0)
            if hist_total > 0:
                cur_total = lh + la
                # Тянем 20% к историческому тоталу
                adj = (hist_total - cur_total) * 0.20
                if abs(adj) > 0.05:
                    lh += adj * 0.55   # хозяин забивает чуть больше
                    la += adj * 0.45

        # ── REGULARIZATION: тянем к нейтральному среднему лиги ──
        # Используем AVG_N (нейтральное) вместо AVG_H/AVG_A
        # Это устраняет третий слой bias: было AVG_H > AVG_A → lh всегда выше
        # Теперь оба тянутся к одному и тому же значению → равные шансы
        lh = lh * 0.90 + AVG_N * 0.10
        la = la * 0.90 + AVG_N * 0.10
        return max(0.30, min(lh, 2.5)), max(0.25, min(la, 2.2))  # FIX: реалист. cap

    def _dixon_coles(self, lh: float, la: float, i: int, j: int,
                       league_id: int = 39) -> float:
        """
        Поправка Dixon-Coles для счётов 0:0, 1:0, 0:1, 1:1.
        rho зависит от ожидаемых голов в матче:
        - Высокозабивные (lh+la > 3.0): rho = -0.10
        - Стандартные (lh+la 2.0-3.0):  rho = -0.13
        - Защитные (lh+la < 2.0):        rho = -0.16
        """
        total_xg = lh + la
        if total_xg > 3.0:
            rho = -0.10   # много голов → 0:0 ещё реже
        elif total_xg < 2.0:
            rho = -0.16   # мало голов → 0:0/1:1 встречаются чаще
        else:
            rho = -0.13   # стандарт
        if i == 0 and j == 0:
            return 1.0 - lh * la * rho
        elif i == 1 and j == 0:
            return 1.0 + la * rho
        elif i == 0 and j == 1:
            return 1.0 + lh * rho
        elif i == 1 and j == 1:
            return 1.0 - rho
        return 1.0

    def matrix(self, lh, la, league_id: int = 39):
        """Матрица вероятностей с поправкой Dixon-Coles (лига-специфично)."""
        raw = [[self._p(lh,i) * self._p(la,j) for j in range(self.N)]
               for i in range(self.N)]
        for i in range(min(2, self.N)):
            for j in range(min(2, self.N)):
                raw[i][j] *= self._dixon_coles(lh, la, i, j, league_id)
        total = sum(p for row in raw for p in row)
        return [[p/total for p in row] for row in raw]

    def prob_1x2(self, m):
        ph=pd=pa=0.0
        for i,row in enumerate(m):
            for j,p in enumerate(row):
                if i>j: ph+=p
                elif i==j: pd+=p
                else: pa+=p
        return ph, pd, pa

    def prob_total(self, m, line):
        po=pu=0.0
        for i,row in enumerate(m):
            for j,p in enumerate(row):
                t=i+j
                if t>line: po+=p
                elif t<line: pu+=p
                else: po+=p*0.5; pu+=p*0.5
        return po, pu

    def prob_btts(self, m):
        """Обе забьют: оба голозащита > 0."""
        py=pn=0.0
        for i,row in enumerate(m):
            for j,p in enumerate(row):
                # BUGFIX: было мёртвое выражение `(py if … else pn)` без += p
                if i>0 and j>0: py+=p
                else: pn+=p
        return py, pn

    def prob_eh(self, m, hcap):
        ph=pd=pa=0.0
        for i,row in enumerate(m):
            for j,p in enumerate(row):
                adj=(i+hcap)-j
                if adj>0: ph+=p
                elif adj==0: pd+=p
                else: pa+=p
        return ph, pd, pa

    def prob_dnb(self, m):
        """Фора 0: победа или возврат при ничье."""
        ph=pa=0.0
        for i,row in enumerate(m):
            for j,p in enumerate(row):
                if i>j: ph+=p
                elif i<j: pa+=p
                # ничья = возврат, не считаем
        total = ph + pa
        if total < 0.01: return 0.5, 0.5
        return ph/total, pa/total

    def prob_dc(self, m):
        """Двойной шанс: 1X, 12, X2."""
        ph=pd=pa=0.0
        for i,row in enumerate(m):
            for j,p in enumerate(row):
                if i>j:  ph+=p   # хозяин выиграл
                elif i==j: pd+=p # ничья
                else:    pa+=p   # гость выиграл
        p1x = ph+pd
        p12 = ph+pa
        px2 = pd+pa
        return round(p1x,4), round(p12,4), round(px2,4)

    def prob_asian(self, m, hcap: float):
        """
        Азиатский гандикап с дробными линиями (0.25, 0.5, 0.75).
        0.25 = половина ставки на 0, половина на 0.5
        0.75 = половина на 0.5, половина на 1.0
        """
        if hcap == int(hcap):
            # Целая линия = стандартный EH без ничьей
            ph=pa=0.0
            for i,row in enumerate(m):
                for j,p in enumerate(row):
                    adj=(i+hcap)-j
                    if adj>0: ph+=p
                    elif adj<0: pa+=p
                    # adj==0 = push (возврат)
            total=ph+pa
            if total<0.01: return 0.5,0.5
            return round(ph/total,4), round(pa/total,4)
        elif (hcap*2) == int(hcap*2):
            # Четвертная линия: среднее двух ближних целых
            lo = math.floor(hcap)
            hi = math.ceil(hcap)
            ph_lo,pa_lo = self.prob_asian(m, float(lo))
            ph_hi,pa_hi = self.prob_asian(m, float(hi))
            return round((ph_lo+ph_hi)/2, 4), round((pa_lo+pa_hi)/2, 4)
        return 0.5, 0.5

    def prob_1h_total(self, lh: float, la: float, line: float):
        """Тотал первого тайма: xG делим ~55% от матча."""
        lh1 = lh * 0.47   # статистически 47% голов в 1-м тайме
        la1 = la * 0.47
        m1  = self.matrix(lh1, la1)
        return self.prob_total(m1, line)

    def prob_1h_1x2(self, lh: float, la: float):
        """Исход первого тайма."""
        lh1 = lh * 0.47
        la1 = la * 0.47
        m1  = self.matrix(lh1, la1)
        return self.prob_1x2(m1)

    def prob_team_total(self, lam: float, line: float) -> tuple:
        """
        Индивидуальный тотал команды.
        lam — ожидаемые голы этой команды (lh или la).
        Возвращает (prob_over, prob_under).
        Пример: lh=1.8, line=1.5 → вероятность забить 2+
        """
        import math
        p_over = 0.0
        for k in range(0, 12):
            p_k = math.exp(-lam) * (lam ** k) / math.factorial(k)
            if k > line:
                p_over += p_k
        p_under = 1.0 - p_over
        return round(p_over, 4), round(p_under, 4)

    def prob_team_score_1h(self, lam: float) -> float:
        """
        Вероятность что команда ЗАБЬЁТ хотя бы 1 гол в первом тайме.
        lam — ожидаемые голы команды за матч.
        """
        import math
        lam1h = lam * 0.47   # ~47% голов в первом тайме
        # P(забьёт 1+) = 1 - P(не забьёт) = 1 - e^(-lam1h)
        p_score = 1.0 - math.exp(-lam1h)
        return round(p_score, 4)

    def prob_team_score_both_halves(self, lam: float) -> float:
        """
        Вероятность что команда забьёт в ОБОИХ таймах.
        """
        import math
        lam1h = lam * 0.47
        lam2h = lam * 0.53
        p1 = 1.0 - math.exp(-lam1h)
        p2 = 1.0 - math.exp(-lam2h)
        return round(p1 * p2, 4)

    def analyze(self, match: Match, h2h: dict = None, wx_factor: float = 1.0,
                league_id: int = 39, first_leg: dict = None) -> tuple:
        lh, la = self.lambdas(match.home, match.away, h2h,
                              league_id=league_id, first_leg=first_leg)
        # Погода снижает тотал — уменьшаем оба xG пропорционально
        if wx_factor < 0.99:
            lh = round(lh * wx_factor, 3)
            la = round(la * wx_factor, 3)
        m      = self.matrix(lh, la, league_id)
        odds   = match.bookmaker_odds
        label  = f"{_ru(match.home.name)} vs {_ru(match.away.name)}"
        calib  = get_league_calib(league_id)
        sigs   = []

        # Elo-вероятности как второй слой
        elo_ph, elo_pd, elo_pa = elo_win_prob(match.home.name, match.away.name)

        def emit(market, sel, raw_prob, key, elo_prob: float = 0.0, min_edge_override: float = 0.0):
            bk = odds.get(key)
            if not bk or bk <= 1.01:
                return
            bk_best = odds.get(f"best_{key}", bk)
            if not bk_best or bk_best <= 1.01:
                bk_best = bk
            imp = 1.0 / bk

            # ── No-vig цена: убираем маржу букмекера ───────────────
            # Для 1X2: no-vig = imp_i / sum(imp_j)  — нормализация
            # Для тоталов/BTTS: приближение через 2-way маржу ~4.5%
            bk1  = odds.get("1");  bkx = odds.get("X");  bk2 = odds.get("2")
            if bk1 and bkx and bk2 and key in ("1","X","2"):
                total_imp_3 = 1/bk1 + 1/bkx + 1/bk2
                no_vig = imp / total_imp_3   # истинная цена без маржи
            elif key.startswith("over_") or key.startswith("under_"):
                # Тотал: пара over/under, маржа ~4%
                twin = key.replace("over_","under_") if "over_" in key else key.replace("under_","over_")
                bk_twin = odds.get(twin)
                if bk_twin and bk_twin > 1.01:
                    total_imp_2 = imp + 1/bk_twin
                    no_vig = imp / total_imp_2
                else:
                    no_vig = imp * 0.92   # Odds API маржа ~8-9% на тоталах/BTTS
            else:
                no_vig = imp * 0.93   # маржа ~7% общий случай

            # ── Калибровка: Пуассон + Elo + no-vig рынок ──────────
            # calib_w = 0.50: рынок несёт инфо о травмах/форме/новостях
            # Если нет Pinnacle (основной острый рынок) → повышаем вес модели
            _has_sharp = bool(odds.get("_source_pinnacle"))
            _is_calc_now = bool(odds.get("_calc_1x2"))   # FIX: ранняя проверка
            # FIX: при calc_odds no_vig тоже из Poisson → не повышать вес модели
            if _has_sharp:
                CALIB_W = calib["calib_w"]
            elif _is_calc_now:
                CALIB_W = calib["calib_w"]   # оба из одной модели → базовый вес
            else:
                # FIX: CALIB_W зависит от качества данных матча
                # data_quality: 0.60=Understat, 0.50=AF, 0.40=только TEAM_DB static
                _dq = getattr(match, "data_quality", 0.50)
                CALIB_W = min(calib["calib_w"] * _dq / 0.50, 0.58)
            ELO_W    = 0.12 if elo_prob > 0 else 0.0   # Elo теперь работает → +вес
            MARKET_W = max(0.20, 1.0 - CALIB_W - ELO_W)

            # Применяем Platt calibration к сырой вероятности модели
            raw_cal = _platt_calibrate(raw_prob)
            if elo_prob > 0:
                prob = raw_cal * CALIB_W + elo_prob * ELO_W + no_vig * MARKET_W
            else:
                prob = raw_cal * CALIB_W + no_vig * (1 - CALIB_W)

            # edge от NO-VIG цены — это реальное преимущество над рынком
            edge = prob - no_vig

            # ── Sharp money бонус к edge ──────────────────────────
            # Если умные деньги двигают линию В НАШУ СТОРОНУ — усиливаем сигнал
            # FIX: dir() неверен для локальных переменных — используем locals()
            sharp_bonus = sharp_money_bonus(locals().get("movements") or {}, key)
            edge = round(edge + sharp_bonus, 5)

            # ── Лига-специфичный порог ─────────────────────────────
            # min_edge = минимальное реальное превышение над no-vig ценой
            # Базовое = 8% (= calib min_edge, обновлено в LEAGUE_CALIBRATION)
            # Для фаворитов (bk<1.60) чуть выше — там рынок точнее
            base_e = calib["min_edge"]
            # Без Pinnacle рынок мягче → снижаем порог
            if not _has_sharp:
                base_e = max(0.025, base_e - 0.015)
            # Повышаем порог только для сверхкоротких коэф (рынок очень острый)
            if bk < 1.30:   min_e = base_e + 0.040   # FIX: рынок очень точен
            elif bk < 1.50: min_e = base_e + 0.025   # FIX: короткий коэф
            elif bk < 1.70: min_e = base_e + 0.015   # FIX: расширен диапазон
            else:           min_e = base_e            # bk>=1.70: базовый порог

            # Источник коэффициента
            if odds.get("_source_fonbet"):  _odds_src = "Fonbet"
            elif odds.get("_source_pinnacle"): _odds_src = "Pinnacle"
            elif odds.get("_calc_1x2"):     _odds_src = "⚙️модель"
            else:                            _odds_src = "Odds API"

            # Рассчётные рынки (нет реального букмекера)
            _calc_markets = ("ИТ Хозяева", "ИТ Гости", "Забьёт в 1Т", "Оба тайма")
            _is_calc_odds = bool(odds.get("_calc_1x2"))   # весь dict расчётный
            if market in _calc_markets:
                min_e = min_e + 0.015   # чуть выше для ИТ
            elif _is_calc_odds:
                min_e = max(0.03, min_e - 0.01)  # чуть мягче - без реального рынка
            # BTTS/DNB/DC — меньший порог (рынок реальный, маржа 4-6%)
            elif market in ("Фора 0", "Двойной шанс"):
                # ФИКС: без реальных данных о команде DNB = фантом
                _dq_match = getattr(match, "data_quality", 0.50)
                if _dq_match < 0.45:
                    return   # нет данных в TEAM_DB → пропускаем DNB/DC
                min_e = max(0.040, min_e + 0.010)   # ФИКС: +0.01 (было -0.01)
            # BTTS убран
            elif market in ("Фора", "Тотал 1Т", "Исход 1Т"):
                min_e = max(0.025, min_e - 0.010)

            # ML-калибровка
            min_e = _ml_min_edge(market, min_e)

            # min_prob: модель должна превышать NO-VIG цену на GAP
            # no_vig = честная цена без маржи букмекера (~8% для Odds API)
            # GAP = 6% — минимальное реальное преимущество модели
            # Для рынков с высокой маржей (DNB/DC) — gap чуть выше
            # gap зависит от вероятности фаворита:
            # Высокий no_vig → меньший gap нужен (рынок и так точен)
            # _gap: насколько модель должна превышать no-vig цену
            # Без Pinnacle (Odds API) рынок мягче → меньший gap нужен
            _no_sharp = not _has_sharp
            if market in ("Фора 0", "Двойной шанс"):
                _gap = 0.030 if _no_sharp else 0.040
            elif no_vig > 0.68:   _gap = 0.020 if _no_sharp else 0.030  # фаворит
            elif no_vig > 0.55:   _gap = 0.025 if _no_sharp else 0.035  # средний
            elif no_vig > 0.40:   _gap = 0.030 if _no_sharp else 0.040  # равная игра
            else:                  _gap = 0.035 if _no_sharp else 0.045  # аутсайдер
            min_p = max(0.51, no_vig + _gap)

            # Проверка ликвидности: коэф < 1.05 или > 15.0 — мусор
            if bk < 1.05 or bk > 15.0:
                return
            if prob >= min_p and edge >= min_e:
                _sig = Signal(
                    match=label, league=match.league,
                    date=match.date, time=match.time,
                    market=market, selection=sel,
                    model_prob=round(prob, 4),
                    bookmaker_odds=round(bk_best, 2),
                    implied_prob=round(imp, 4),
                    edge=round(edge, 4),
                    kelly_stake=_kelly(prob, bk_best),
                    confidence=_conf(edge, prob, bk),
                )
                # Прикрепляем источник коэффициента (динамический атрибут)
                _sig._odds_source = _odds_src
                sigs.append(_sig)

        ph,pd,pa = self.prob_1x2(m)
        # Объявляем _xg_h/_xg_a заранее — используются в нескольких местах
        # lh/la = ожидаемые голы (xG) из модели Пуассона
        _xg_h = lh   # xG хозяев
        _xg_a = la   # xG гостей
        # Для исходов передаём Elo как дополнительную оценку
        # Хозяева и так перегружены сигналами — базовый порог
        emit("Исход", "Победа хозяев (1)", ph, "1", elo_prob=elo_ph, min_edge_override=+0.005)
        # КАЛИБРОВКА: ничья — динамический порог
        _draw_override = -0.010
        if abs(_xg_h - _xg_a) < 0.25:
            _draw_override = -0.020  # команды равны по xG → ничья вероятнее → −2%
        emit("Исход", "Ничья (X)", pd, "X", elo_prob=elo_pd, min_edge_override=_draw_override)
        # КАЛИБРОВКА: гости недооценены — динамический порог
        # _xg_h/_xg_a уже объявлены выше
        _away_override = -0.015
        if _xg_a > _xg_h + 0.5:
            _away_override = -0.030  # гости явно сильнее по xG → −3%
        elif _xg_a > _xg_h + 0.2:
            _away_override = -0.020  # гости немного сильнее → −2%
        emit("Исход", "Победа гостей (2)", pa, "2", elo_prob=elo_pa, min_edge_override=_away_override)
        for line in TOTAL_LINES:
            po,pu = self.prob_total(m, line)
            # FIX: Больше 2.5 исторически WR=45% → повышен порог
            # КАЛИБРОВКА: Больше 2.5 WR=44% ROI=-23% → raise edge hard
            _over_ov = 0.0
            if line == 1.5:  _over_ov = 0.04   # Больше 1.5: ROI=-20% → +4%
            elif line == 2.5: _over_ov = 0.06  # Больше 2.5: ROI=-23% → +6%
            elif line == 3.5: _over_ov = 0.05  # Больше 3.5: ROI=-100% → +5%
            emit("Тотал", f"Больше {line}", po, f"over_{line}", min_edge_override=_over_ov)
            # КАЛИБРОВКА: Меньше X WR=72% ROI=+52% → снижаем min_edge
            _under_ov = -0.01 if line in (2.5, 3.5) else 0.0
            emit("Тотал", f"Меньше {line}", pu, f"under_{line}", min_edge_override=_under_ov)
        # ── ОБЕ ЗАБЬЮТ (BTTS) ───────────────────────────────
        py_btts, pn_btts = self.prob_btts(m)
        emit("Обе забьют", "Да",  py_btts, "btts_yes")
        # BTTS НЕТ: только в лигах где исторически проходит (WR>58%)
        if league_id in (78, 135, 39, 144, 203, 40):  # BTTS НЕТ по лигам
            emit("Обе забьют", "Нет", pn_btts, "btts_no", min_edge_override=-0.010)
        else:
            emit("Обе забьют", "Нет", pn_btts, "btts_no")

        # ── УГЛОВЫЕ ────────────────────────────────────────────
        try:
            # lh/la уже вычислены в analyze() через self.lambdas()
            # Используем их как xG прогноз для угловых
            _lid = league_id
            if lh > 0 or la > 0:
                _crn = expected_corners(lh, la, _lid)
                _lam_c = _crn["lam_total"]
                for _cl in CORNER_LINES:
                    _po_c = prob_corners_over(_lam_c, _cl)
                    _pu_c = 1.0 - _po_c
                    # Генерируем только сильные сигналы (p >= 60%)
                    # Угловые — min_edge ниже (мягкий рынок)
                    if _po_c >= 0.57:
                        emit("Угловые", f"Больше {_cl}", _po_c, f"corners_over_{_cl}",
                             min_edge_override=-0.012)
                    if _pu_c >= 0.57:
                        emit("Угловые", f"Меньше {_cl}", _pu_c, f"corners_under_{_cl}",
                             min_edge_override=-0.012)
                # Индивидуальные угловые хозяев/гостей
                for _cl_ind in [4.5, 5.5]:
                    _po_h = prob_corners_over(_crn["lam_h"], _cl_ind)
                    _po_a = prob_corners_over(_crn["lam_a"], _cl_ind)
                    emit("Угловые хозяев", f"Больше {_cl_ind}", _po_h, f"corners_h_over_{_cl_ind}",
                         min_edge_override=-0.005)
                    emit("Угловые гостей", f"Больше {_cl_ind}", _po_a, f"corners_a_over_{_cl_ind}",
                         min_edge_override=-0.005)
        except Exception:
            pass

        # ── ЖЁЛТЫЕ КАРТОЧКИ ────────────────────────────────────
        try:
            _lid_yc = league_id  # league_id из параметра analyze()
            # Только в лигах с надёжной статистикой ЖК
            if league_id in YC_TRUSTED_LEAGUES:
                _ref   = getattr(match, 'referee_stats', {}) or {}
                _ref_c = _ref.get('cards_per_game', 0) if _ref else 0
                _derby = getattr(match, 'is_derby', False)
                # Контекст матча из объекта match (Match датакласс)
                _is_cup     = getattr(match, 'is_cup', False) or getattr(match, 'is_playoff', False)
                _relegation = getattr(match, 'is_relegation_match', False)
                _yc = expected_yellow_cards(_lid_yc, _ref_c, _derby, _relegation, _is_cup)
                _lam_yc  = _yc["lam"]
                _line_yc = _yc["line"]
                # Только если есть реальный перевес (lambda >> line)
                if _yc["has_edge"]:
                    _po_yc = prob_yc_over(_lam_yc, _line_yc)
                    _pu_yc = 1.0 - _po_yc
                    emit("Жёлтые карточки", f"Больше {_line_yc}", _po_yc,
                         f"yc_over_{_line_yc}", min_edge_override=0.0)
                    # Меньше только если lambda явно ниже линии
                    if _lam_yc < _line_yc * 0.85:
                        emit("Жёлтые карточки", f"Меньше {_line_yc}", _pu_yc,
                             f"yc_under_{_line_yc}", min_edge_override=0.0)
                # Индивидуальные ЖК команды — независимо от has_edge
                _lines_ind = [1.5]
                for _yl in _lines_ind:
                    _po_yh = prob_yc_team_over(_yc["lam_home"], _yl)
                    _po_ya = prob_yc_team_over(_yc["lam_away"], _yl)
                    if _po_yh >= 0.62:   # минимум 62% для индивидуального
                        emit("ЖК хозяев", f"Больше {_yl}", _po_yh,
                             f"yc_h_over_{_yl}", min_edge_override=0.0)
                    if _po_ya >= 0.62:
                        emit("ЖК гостей", f"Больше {_yl}", _po_ya,
                             f"yc_a_over_{_yl}", min_edge_override=0.0)
                # Индивидуальные ЖК команды (хозяева / гости)
                _lines_ind = [1.5]
                for _yl in _lines_ind:
                    _po_yh = prob_yc_team_over(_yc["lam_home"], _yl)
                    _po_ya = prob_yc_team_over(_yc["lam_away"], _yl)
                    emit("ЖК хозяев", f"Больше {_yl}", _po_yh,
                         f"yc_h_over_{_yl}", min_edge_override=0.0)
                    emit("ЖК гостей", f"Больше {_yl}", _po_ya,
                         f"yc_a_over_{_yl}", min_edge_override=0.0)
        except Exception:
            pass

        # ── DNB (ПОБЕДА БЕЗ НИЧЬЕЙ) ─────────────────────────
        ph_dnb, pa_dnb = self.prob_dnb(m)
        emit("Фора 0", "Хозяева (Ф0)", ph_dnb, "dnb_home")
        emit("Фора 0", "Гости (Ф0)",   pa_dnb, "dnb_away")

        # ── ДВОЙНОЙ ШАНС ─────────────────────────────────────
        p1x, p12, px2 = self.prob_dc(m)
        emit("Двойной шанс", "1X", p1x, "dc_1x")
        emit("Двойной шанс", "12", p12, "dc_12")
        emit("Двойной шанс", "X2", px2, "dc_x2")

        # ── ТОТАЛ 1-ГО ТАЙМА ────────────────────────────────────
        for line1h in [0.5, 1.5]:
            po1, pu1 = self.prob_1h_total(lh, la, line1h)
            emit("Тотал 1Т", f"Больше {line1h}", po1, f"1h_over_{line1h}")
            emit("Тотал 1Т", f"Меньше {line1h}", pu1, f"1h_under_{line1h}")

        # ── ИСХОД 1-ГО ТАЙМА ────────────────────────────────────
        ph1,pd1,pa1 = self.prob_1h_1x2(lh, la)
        emit("Исход 1Т", "Хозяева (1Т)", ph1, "1h_home")
        emit("Исход 1Т", "Ничья (1Т)",   pd1, "1h_draw")
        emit("Исход 1Т", "Гости (1Т)",   pa1, "1h_away")

        # ── ИНДИВИДУАЛЬНЫЙ ТОТАЛ ХОЗЯЕВ ─────────────────────────
        for it_line in [0.5, 1.5, 2.5]:
            po_h, pu_h = self.prob_team_total(lh, it_line)
            po_a, pu_a = self.prob_team_total(la, it_line)
            sign = str(it_line)
            emit("ИТ Хозяева", f"Хозяева Больше {sign}", po_h, f"iteam_h_over_{sign}")
            emit("ИТ Хозяева", f"Хозяева Меньше {sign}", pu_h, f"iteam_h_under_{sign}")
            emit("ИТ Гости",   f"Гости Больше {sign}",   po_a, f"iteam_a_over_{sign}")
            emit("ИТ Гости",   f"Гости Меньше {sign}",   pu_a, f"iteam_a_under_{sign}")

        # ── ЗАБЬЁТ В ПЕРВОМ ТАЙМЕ ────────────────────────────────
        p_h_score_1h = self.prob_team_score_1h(lh)
        p_a_score_1h = self.prob_team_score_1h(la)
        p_h_no_1h    = 1.0 - p_h_score_1h
        p_a_no_1h    = 1.0 - p_a_score_1h
        emit("Забьёт в 1Т", f"Хозяева забьют в 1Т — Да",  p_h_score_1h, "score_1h_h_yes")
        emit("Забьёт в 1Т", f"Хозяева забьют в 1Т — Нет", p_h_no_1h,   "score_1h_h_no")
        emit("Забьёт в 1Т", f"Гости забьют в 1Т — Да",    p_a_score_1h, "score_1h_a_yes")
        emit("Забьёт в 1Т", f"Гости забьют в 1Т — Нет",   p_a_no_1h,   "score_1h_a_no")

        # ── КОМАНДА ЗАБЬЁТ В ОБОИХ ТАЙМАХ ───────────────────────
        p_h_both = self.prob_team_score_both_halves(lh)
        p_a_both = self.prob_team_score_both_halves(la)
        emit("Оба тайма", f"Хозяева в обоих таймах", p_h_both, "both_halves_h")
        emit("Оба тайма", f"Гости в обоих таймах",   p_a_both, "both_halves_a")

        return lh, la, sigs

# ══════════════════════════════════════════════════════════════
#  🧮  УТИЛИТЫ
# ══════════════════════════════════════════════════════════════
# Динамический Kelly: снижается при просадке, растёт при серии
_KELLY_MULTIPLIER = 1.0   # обновляется из results.json

def _update_kelly_multiplier():
    """Анализирует последние 20 ставок и корректирует размер."""
    global _KELLY_MULTIPLIER
    try:
        if not os.path.exists(RESULTS_FILE):
            return
        with open(RESULTS_FILE, encoding="utf-8") as f:
            results = json.load(f)
        recent = []
        for r in reversed(results):
            for s in reversed(r.get("signals",[])):
                if s.get("won") is not None:
                    recent.append(s.get("won"))
                if len(recent) >= 20:
                    break
            if len(recent) >= 20:
                break
        if len(recent) < 5:
            return
        acc = sum(recent) / len(recent)
        if acc >= 0.70:     _KELLY_MULTIPLIER = 1.25   # горячая серия
        elif acc >= 0.60:   _KELLY_MULTIPLIER = 1.10
        elif acc >= 0.50:   _KELLY_MULTIPLIER = 1.00   # норма
        elif acc >= 0.40:   _KELLY_MULTIPLIER = 0.75   # лёгкая просадка
        else:               _KELLY_MULTIPLIER = 0.50   # стоп-лосс режим
    except Exception:
        pass

def _kelly(prob, odds):
    b = odds - 1
    if b <= 0:
        return 0.0
    k = (b * prob - (1 - prob)) / b
    k = max(0.0, min(k, 0.50))   # FIX: Kelly fraction > 50% = баг в модели
    base   = k * KELLY_FRAC * BANKROLL
    capped = min(base * _KELLY_MULTIPLIER, BANKROLL * 0.05)
    capped = min(capped, BANKROLL * 0.05)   # FIX: двойной cap
    return round(capped, 2)

def _conf(edge: float, prob: float, odds: float = 2.0) -> str:
    """
    Уровень уверенности сигнала.
    🔥 ВЫСОКАЯ: prob > 68% И edge > 14%
    ✅ СРЕДНЯЯ:  prob > 60% И edge > 9%
    📌 НИЗКАЯ:  prob > 54% И edge > 6%
    (сигналы ниже этих порогов не должны доходить сюда)
    """
    ev = edge * odds
    # Уровень определяется комбинацией уверенности модели и размера валуя
    if prob > 0.70 and edge > 0.12: return "🔥 ВЫСОКАЯ"
    if prob > 0.62 and edge > 0.09: return "✅ СРЕДНЯЯ"
    if prob > 0.58 and edge > 0.07: return "✅ СРЕДНЯЯ"
    return "📌 НИЗКАЯ"


def _win_chance(prob: float, edge: float, confidence: str) -> int:
    """
    Вероятность исхода по модели в %.
    Показываем честную вероятность, не скорректированный win rate.
    """
    return round(prob * 100)

def _print_sig(s: Signal):
    win_pct = _win_chance(s.model_prob, s.edge, s.confidence)
    _src = getattr(s, "_odds_source", None)
    _is_model_only = (_src == "⚙️модель") or (s.bookmaker_odds < 1.02)

    print(f"  {s.confidence}  [{s.market}]  ➜  {s.selection}")

    if _is_model_only:
        print(f"     Коэф: {s.bookmaker_odds:.2f} [расч.]  |  Шанс: {win_pct}%  |  Валуй: {s.edge:+.1%}")
    else:
        ev = round(s.model_prob * s.bookmaker_odds - 1.0, 3)
        print(f"     Коэф: {s.bookmaker_odds:.2f} [{_src}]  |  Шанс: {win_pct}%  |  "
              f"Валуй: {s.edge:+.1%}  |  EV: {ev:+.3f}")


# ══════════════════════════════════════════════════════════════
#  ✅  АВТО-ВЕРИФИКАЦИЯ РЕЗУЛЬТАТОВ  (для ML накопления данных)
#  Каждый запуск проверяет вчерашние сигналы через football-data.org
#  и записывает W/L/PUSH в signals_verified.csv
# ══════════════════════════════════════════════════════════════

def _verify_signal_result(selection: str, market: str,
                          home_score: int, away_score: int,
                          ht_home: int = -1, ht_away: int = -1) -> str:
    """
    Проверяет прошёл ли сигнал по итогам матча.
    ht_home/ht_away: счёт 1-го тайма (-1 = неизвестен).
    Возвращает: 'W' / 'L' / 'P' (возврат) / '?' (неизвестно)
    """
    import re as _re
    h, a = home_score, away_score
    diff  = h - a
    sel = selection.lower()
    mkt = market.lower()
    try:
        if mkt == "исход":
            if "хозяев" in sel or sel == "1":
                return "W" if diff > 0 else "L"   # FIX: ничья = L для победы хозяев
            if "ничья" in sel or sel == "x":
                return "W" if diff == 0 else "L"
            if "гостей" in sel or sel == "2":
                return "W" if diff < 0 else "L"   # FIX: ничья = L для победы гостей
        if mkt == "тотал":
            total = h + a
            nums = _re.findall(r"[\d.]+", sel)
            if not nums: return "?"
            line = float(nums[-1])
            if "больше" in sel: return "W" if total > line else ("P" if total == line else "L")
            if "меньше" in sel: return "W" if total < line else ("P" if total == line else "L")
        if "фора" in mkt or "евр.гандикап" in mkt:
            nums = _re.findall(r"[+-]?[0-9]+", sel)
            if not nums: return "?"
            hcap = int(nums[-1])
            if "хозяев" in sel or "хозяева" in sel:
                adj = diff + hcap
                return "W" if adj > 0 else ("P" if adj == 0 else "L")
            if "гостей" in sel or "гости" in sel:
                adj = -diff + hcap
                return "W" if adj > 0 else ("P" if adj == 0 else "L")
        if mkt in ("dnb", "победа без ничьей"):
            # "Хозяева (Ф0)" → выигрыш если победа хозяев, возврат при ничье
            if "хозяев" in sel or "хозяева" in sel or "(dnb)" in sel.lower() and diff > 0:
                return "W" if diff > 0 else ("P" if diff == 0 else "L")
            if "гостей" in sel or "гости" in sel:
                return "W" if diff < 0 else ("P" if diff == 0 else "L")
        if "двойной" in mkt:
            if "1x" in sel: return "W" if diff >= 0 else "L"
            if "x2" in sel: return "W" if diff <= 0 else "L"
            if "12" in sel: return "W" if diff != 0 else "L"
        if "обе забьют" in mkt or "btts" in mkt:
            both = h > 0 and a > 0
            if "да" in sel: return "W" if both else "L"
            if "нет" in sel: return "W" if not both else "L"
        if "тотал 1" in mkt or ("1т" in mkt and "тотал" in mkt):
            if ht_home < 0 or ht_away < 0: return "?"
            ht_total = ht_home + ht_away
            nums = _re.findall(r"[\d.]+", sel)
            if not nums: return "?"
            line = float(nums[-1])
            if "больше" in sel: return "W" if ht_total > line else ("P" if ht_total == line else "L")
            if "меньше" in sel: return "W" if ht_total < line else ("P" if ht_total == line else "L")
        if "исход 1" in mkt:
            if ht_home < 0 or ht_away < 0: return "?"
            ht_diff = ht_home - ht_away
            if "хозяева" in sel: return "W" if ht_diff > 0 else "L"
            if "ничья" in sel:   return "W" if ht_diff == 0 else "L"
            if "гости" in sel:   return "W" if ht_diff < 0 else "L"
        if "ит хозяева" in mkt or "ит гости" in mkt:
            nums = _re.findall(r"[\d.]+", sel)
            if not nums: return "?"
            line = float(nums[-1])
            tg = h if "хозяева" in mkt else a
            if "больше" in sel: return "W" if tg > line else ("P" if tg == line else "L")
            if "меньше" in sel: return "W" if tg < line else ("P" if tg == line else "L")
    except Exception:
        pass
    return "?"


def verify_yesterday_signals(csv_path: str = "signals.csv",
                              out_path: str = "signals_verified.csv") -> int:
    """
    Берёт вчерашние сигналы из csv_path,
    ищет результаты через football-data.org,
    дописывает в out_path строки с колонкой result (W/L/P/?).
    Возвращает количество верифицированных сигналов.
    """
    import csv, os, datetime

    if not os.path.exists(csv_path):
        return 0

    yesterday = (datetime.date.today() - datetime.timedelta(days=1)).isoformat()

    # Читаем все сигналы из CSV
    try:
        with open(csv_path, encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
    except Exception:
        return 0

    # Отбираем вчерашние непроверенные
    to_check = [r for r in rows if r.get("date","")[:10] == yesterday
                and r.get("result","") == ""]
    if not to_check:
        return 0

    # Загружаем результаты с football-data.org за вчера
    _fd_url = (f"https://api.football-data.org/v4/matches"
               f"?dateFrom={yesterday}&dateTo={yesterday}&status=FINISHED")
    _fd_headers = {"X-Auth-Token": FOOTBALL_DATA_KEY}
    _fd_data = _http(_fd_url, _fd_headers, silent=True)

    if not isinstance(_fd_data, dict):
        return 0

    fd_matches = _fd_data.get("matches", [])
    if not fd_matches:
        return 0

    # Индекс: "home_name|away_name" → (home_score, away_score)
    results_idx: dict = {}
    for m in fd_matches:
        try:
            hn = (m["homeTeam"]["shortName"] or m["homeTeam"]["name"]).lower()
            an = (m["awayTeam"]["shortName"] or m["awayTeam"]["name"]).lower()
            hs = m["score"]["fullTime"]["home"]
            as_ = m["score"]["fullTime"]["away"]
            if hs is not None and as_ is not None:
                _ht = m.get("score", {}).get("halfTime", {})
                ht_h = int(_ht.get("home") or -1) if isinstance(_ht, dict) and _ht.get("home") is not None else -1
                ht_a = int(_ht.get("away") or -1) if isinstance(_ht, dict) and _ht.get("away") is not None else -1
                results_idx[f"{hn}|{an}"] = (int(hs), int(as_), ht_h, ht_a)
                hn2 = m["homeTeam"]["name"].lower()
                an2 = m["awayTeam"]["name"].lower()
                results_idx[f"{hn2}|{an2}"] = (int(hs), int(as_), ht_h, ht_a)
        except Exception:
            continue

    def _find_result(match_str: str):
        """Ищем матч в results_idx по нечёткому совпадению."""
        # match_str вида "Ман Сити vs Ноттингем" или "Man City vs Nottingham"
        parts = match_str.lower().replace(" vs ", "|").split("|")
        if len(parts) < 2:
            return None
        h_query, a_query = parts[0].strip(), parts[1].strip()

        # Точное совпадение
        key = f"{h_query}|{a_query}"
        if key in results_idx:
            return results_idx[key]

        # Нечёткое — первые 5 символов
        for k, v in results_idx.items():
            kh, ka = k.split("|", 1)
            if h_query[:5] in kh and a_query[:5] in ka:
                return v
            if kh[:5] in h_query and ka[:5] in a_query:
                return v

        return None

    # Обогащаем строки результатом
    verified_count = 0
    enriched = []
    for row in to_check:
        match_str  = row.get("match", "")
        market     = row.get("market", "")
        selection  = row.get("selection", "")

        score = _find_result(match_str)
        if score:
            _ht_h = score[2] if len(score) > 2 else -1
            _ht_a = score[3] if len(score) > 3 else -1
            result = _verify_signal_result(selection, market, score[0], score[1],
                                           ht_home=_ht_h, ht_away=_ht_a)
            row["result"]   = result
            row["home_score"] = score[0]
            row["away_score"] = score[1]
            verified_count += 1
        else:
            row["result"]   = "?"
            row["home_score"] = ""
            row["away_score"] = ""
        enriched.append(row)

    if not enriched:
        return 0

    # Дописываем в signals_verified.csv
    _fields = list(enriched[0].keys())
    out_exists = os.path.exists(out_path)
    try:
        with open(out_path, "a", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=_fields, extrasaction="ignore")
            if not out_exists:
                w.writeheader()
            w.writerows(enriched)
    except Exception:
        return 0

    found = sum(1 for r in enriched if r.get("result") in ("W","L","P"))
    if found > 0:
        wins = sum(1 for r in enriched if r.get("result") == "W")
        total_wl = sum(1 for r in enriched if r.get("result") in ("W","L"))
        pct = f"{wins/total_wl*100:.0f}%" if total_wl else "n/a"
        print(f"  ✅ Верификация вчера: {found} матчей | {wins}W / {total_wl-wins}L | {pct} проходимость")
        print(f"     → Сохранено в {out_path}")

    return verified_count


def print_ml_stats(path: str = "signals_verified.csv") -> None:
    """Статистика по верифицированным сигналам: ROI по лигам, рынкам, уверенности."""
    import csv, os, collections
    if not os.path.exists(path):
        return
    try:
        with open(path, encoding="utf-8") as f:
            rows = [r for r in csv.DictReader(f) if r.get("result") in ("W","L","P")]
    except Exception:
        return
    if not rows:
        return

    total = len(rows)
    wins  = sum(1 for r in rows if r["result"] == "W")
    wl    = sum(1 for r in rows if r["result"] in ("W","L"))
    pct   = wins/wl*100 if wl else 0
    print(f"  📊 ML база: {total} сигналов | {wins}W/{wl-wins}L | {pct:.0f}% проходимость")

    if total >= 30:
        # ── ROI по рынкам ─────────────────────────────────────
        by_mkt: dict = {}
        for r in rows:
            mkt = r.get("market","?")
            if mkt not in by_mkt: by_mkt[mkt] = {"W":0,"L":0,"P":0,"ev":0.0}
            by_mkt[mkt][r["result"]] += 1
            try: by_mkt[mkt]["ev"] += float(r.get("bookmaker_odds",2)) - 1 if r["result"]=="W" else -1 if r["result"]=="L" else 0
            except: pass
        print("  📈 ROI по рынкам:")
        for mkt, d in sorted(by_mkt.items(), key=lambda x: x[1]["ev"], reverse=True)[:6]:
            wl_ = d["W"]+d["L"]
            if wl_ < 5: continue
            roi = d["ev"]/wl_*100
            icon = "✅" if roi > 0 else "🔴"
            print(f"     {icon} {mkt:<22} {d['W']}W/{d['L']}L  ROI={roi:+.0f}%")

        # ── ROI по лигам ──────────────────────────────────────
        if total >= 50:
            by_league: dict = {}
            for r in rows:
                lg = r.get("league","?")
                if lg not in by_league: by_league[lg] = {"W":0,"L":0,"P":0,"ev":0.0}
                by_league[lg][r["result"]] += 1
                try: by_league[lg]["ev"] += float(r.get("bookmaker_odds",2)) - 1 if r["result"]=="W" else -1 if r["result"]=="L" else 0
                except: pass
            print("  🏆 ROI по лигам (мин. 10 сигналов):")
            bad_leagues = []
            for lg, d in sorted(by_league.items(), key=lambda x: x[1]["ev"], reverse=True):
                wl_ = d["W"]+d["L"]
                if wl_ < 10: continue
                roi = d["ev"]/wl_*100
                icon = "✅" if roi > 0 else ("⚠️" if roi > -15 else "🔴")
                print(f"     {icon} {lg[:30]:<32} {d['W']}W/{d['L']}L  ROI={roi:+.0f}%")
                if roi < -20:
                    bad_leagues.append(lg)
            if bad_leagues:
                print(f"  ⚠️  Рекомендую добавить в LEAGUES_SKIP: {bad_leagues}")

        # ── ROI по уверенности ────────────────────────────────
        by_conf: dict = {}
        for r in rows:
            c = r.get("confidence","?")[:6]
            if c not in by_conf: by_conf[c] = {"W":0,"L":0,"ev":0.0}
            by_conf[c][r["result"]] = by_conf[c].get(r["result"],0) + 1
            try: by_conf[c]["ev"] += float(r.get("bookmaker_odds",2)) - 1 if r["result"]=="W" else -1 if r["result"]=="L" else 0
            except: pass
        print("  🎯 ROI по уверенности:")
        for c, d in sorted(by_conf.items()):
            wl_ = d["W"]+d.get("L",0)
            if wl_ < 5: continue
            roi = d["ev"]/wl_*100
            print(f"     {'✅' if roi>0 else '🔴'} {c:<10} {d['W']}W/{d.get('L',0)}L  ROI={roi:+.0f}%")

    if total >= 50:
        print(f"  🤖 ML готов к первому запуску! (накоплено {total}/200 нужных)")
    else:
        print(f"  🤖 ML: нужно ещё {200-total} сигналов для первого обучения")

def save_csv(signals: list, path="signals.csv"):
    """Сохраняет сигналы в CSV с дедупликацией по (match, market, selection, date)."""
    if not signals:
        return
    # FIX: читаем уже записанные ключи
    existing_keys: set = set()
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as _f:
                for _row in csv.DictReader(_f):
                    existing_keys.add((
                        _row.get("match","").strip(),
                        _row.get("market","").strip(),
                        _row.get("selection","").strip(),
                        _row.get("date","").strip(),
                    ))
        except Exception:
            pass
    new_signals = [s for s in signals
                   if (s.match.strip(), s.market.strip(), s.selection.strip(), s.date.strip())
                   not in existing_keys]
    skipped = len(signals) - len(new_signals)
    if skipped > 0:
        print(f"  ⏭  Пропущено дублей: {skipped}")
    if not new_signals:
        return
    exists = os.path.exists(path)
    with open(path, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(asdict(new_signals[0]).keys()))
        if not exists:
            w.writeheader()
        for s in new_signals:
            w.writerow(asdict(s))
    print(f"  💾 {len(new_signals)} сигналов → {path}")



# ══════════════════════════════════════════════════════════════
#  🏆  КОНТЕКСТ МАТЧА — турнирная ситуация
# ══════════════════════════════════════════════════════════════
def get_match_context(fixture_id: int, home_id: int, away_id: int,
                      league_id: int) -> dict:
    """
    Проверяем турнирную ситуацию через standings API.
    Если команда уже чемпион или уже вылетела — снижаем вес матча.
    Возвращает {"home_motivation": 1.0, "away_motivation": 1.0, "note": ""}
    """
    result = {"home_motivation": 1.0, "away_motivation": 1.0, "note": ""}

    # УЛУЧШЕНИЕ: standings дёшевые (1 запрос на лигу, кэш 6ч) — не экономим
    if not league_id:
        return result

    cache_key = f"standings_{league_id}"
    if cache_key in _form_cache:
        standings = _form_cache[cache_key]
    else:
        # Дисковый кэш на 24 часа (таблица меняется раз в тур)
        _st_disk_key = f"standings_{league_id}_{datetime.date.today().isoformat()}"
        _st_cached   = _AF_DISK_CACHE.get(_st_disk_key)
        if _st_cached and isinstance(_st_cached, dict):
            standings = _st_cached.get("response", [])
        elif _af_quota_ok:
            resp = _af_resp("standings", {
                "league": league_id, "season": CURRENT_SEASON
            })
            if not resp:
                # Пробуем прошлый сезон
                resp = _af_resp("standings", {
                    "league": league_id, "season": FALLBACK_SEASON
                })
            if not resp:
                return result
            standings = resp
            _AF_DISK_CACHE[_st_disk_key] = {"response": standings}
            _save_af_disk_cache()
        else:
            return result
        _form_cache[cache_key] = standings

    try:
        # Парсим таблицу
        table = []
        for group in standings:
            for entry in group.get("league", {}).get("standings", [[]]):
                for row in entry:
                    table.append({
                        "team_id": row["team"]["id"],
                        "rank":    row["rank"],
                        "played":  row["all"]["played"],
                        "pts":     row["points"],
                        "form":    row.get("form", ""),
                    })

        total = len(table)
        notes = []

        for team_id, side in [(home_id, "home"), (away_id, "away")]:
            row = next((r for r in table if r["team_id"] == team_id), None)
            if not row:
                continue
            rank   = row["rank"]
            played = row["played"]
            if played < 10:
                continue  # слишком мало матчей для выводов

            # Топ команда — высокая мотивация в борьбе за чемпионство
            if rank <= 3:
                result[f"{side}_motivation"] = 1.05
                notes.append(f"{'Хозяева' if side=='home' else 'Гости'} ТОП-{rank} 🔝")
            # Зона вылета — паника или борьба
            elif rank >= total - 2:
                result[f"{side}_motivation"] = 1.05
                notes.append(f"{'Хозяева' if side=='home' else 'Гости'} зона вылета ⚠️")
            # Середина — меньше мотивации в конце сезона
            elif rank > total // 2 and played > 25:
                result[f"{side}_motivation"] = 0.95
                notes.append(f"{'Хозяева' if side=='home' else 'Гости'} без задач 💤")

        result["note"] = " | ".join(notes)

    except Exception:
        pass

    return result

# ══════════════════════════════════════════════════════════════
#  📉  ЗАКРЫТИЕ ЛИНИИ — отслеживаем движение коэффициентов
# ══════════════════════════════════════════════════════════════
_LINE_FILE = "line_history.json"

# BUGFIX: дублирующийся save_opening_odds удалён — функция объединена выше
# (строка ~4373: пишет в _opening_odds_db RAM + line_history.json)

# BUGFIX: дублирующийся get_line_movement удалён — функция объединена выше
# (строка ~4389: читает из RAM + fallback файл)

def line_movement_signal(movements: dict, signals: list) -> list:
    """
    Усиливаем или ослабляем сигналы на основе движения линии.
    Логика: если коэф НА НАШ СИГНАЛ падает (книга принимает деньги туда же)
    → это подтверждение → повышаем confidence.
    Если растёт → возможно "умные деньги" против нас → снижаем.
    """
    KEY_MAP = {
        "Победа хозяев (1)": "1", "Ничья (X)": "X", "Победа гостей (2)": "2",
    }
    enhanced = []
    for s in signals:
        s_key = KEY_MAP.get(s.selection)
        if not s_key:
            # Для тоталов
            if "Больше" in s.selection:
                parts = s.selection.split()
                s_key = f"over_{parts[-1]}" if len(parts) > 1 else None
            elif "Меньше" in s.selection:
                parts = s.selection.split()
                s_key = f"under_{parts[-1]}" if len(parts) > 1 else None

        move = movements.get(s_key, 0) if s_key else 0

        if move < -0.05:
            # Коэф упал — деньги идут туда же куда наш сигнал → подтверждение
            if "НИЗКАЯ" in s.confidence:
                s = s.__class__(**{**s.__dict__, "confidence": "✅ СРЕДНЯЯ"})
            elif "СРЕДНЯЯ" in s.confidence:
                s = s.__class__(**{**s.__dict__, "confidence": "🔥 ВЫСОКАЯ"})
            enhanced.append((s, f"📉 линия -{abs(move):.2f}"))
        elif move > 0.08:
            # Коэф вырос — осторожно, возможно умные деньги против
            enhanced.append((s, f"⚠️ линия +{move:.2f}"))
        else:
            enhanced.append((s, None))

    return enhanced

# ══════════════════════════════════════════════════════════════
#  📤  TELEGRAM
# ══════════════════════════════════════════════════════════════
_TG_CHAT_CONFIRMED = None  # кэш рабочего chat_id

def _tg(text: str, reply_markup: dict = None):
    """
    Отправляет сообщение в Telegram.
    Режим 1: parse_mode=HTML с правильным escaping.
    Режим 2: plain text — без ключа parse_mode (не null!).
    """
    import re as _re
    global _TG_CHAT_CONFIRMED

    text = _re.sub(r"\n{3,}", "\n\n", text.strip())
    if not text:
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"

    # Обрезка: Telegram лимит 4096 символов
    if len(text) > 4000:
        text = text[:3997] + "..."

    def _esc(t: str) -> str:
        """Экранирует &<> НО сохраняет разрешённые Telegram теги."""
        _SAFE = _re.compile(r'(</?(?:b|i|u|s|code|pre)>)')
        parts = _SAFE.split(t)
        out = []
        for part in parts:
            if _SAFE.fullmatch(part):
                out.append(part)
            else:
                part = part.replace("&", "&amp;")
                part = part.replace("<", "&lt;")
                part = part.replace(">", "&gt;")
                out.append(part)
        return "".join(out)

    def _strip(t: str) -> str:
        """Убирает все теги для plain text."""
        t = _re.sub(r"<[^>]+>", "", t)
        return t.replace("&amp;","&").replace("&lt;","<").replace("&gt;",">")

    # chat_id: только правильный формат
    raw = str(TELEGRAM_CHAT_ID).strip()
    if _TG_CHAT_CONFIRMED:
        chat_ids = [_TG_CHAT_CONFIRMED]
    else:
        chat_ids = [raw]
        if raw.startswith("-") and not raw.startswith("-100") and len(raw) > 10:
            chat_ids.append("-100" + raw.lstrip("-"))

    _RETRY = ("EOF","SSL","TLS","Remote end","Connection","reset","closed","timed out","10053","10054","10061","WinError")

    for chat_id in chat_ids:
        # Попытка 1: HTML
        for use_html in (True, False):
            if use_html:
                send_text = _esc(text)
                payload = {
                    "chat_id":  chat_id,
                    "text":     send_text,
                    "parse_mode": "HTML",
                    "disable_web_page_preview": True,
                }
            else:
                send_text = _strip(text)
                payload = {
                    "chat_id":  chat_id,
                    "text":     send_text,
                    # НАМЕРЕННО нет parse_mode — null вызывает ошибку Telegram
                    "disable_web_page_preview": True,
                }
            if reply_markup and use_html:
                payload["reply_markup"] = reply_markup

            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            req  = urllib.request.Request(
                url, data=body,
                headers={"Content-Type": "application/json; charset=utf-8"}
            )
            try:
                for _attempt in range(4):
                    try:
                        urllib.request.urlopen(req, timeout=25, context=_ssl())
                        break
                    except Exception as _e:
                        if _attempt < 3 and any(x in str(_e) for x in _RETRY):
                            time.sleep(3 * (_attempt + 1))
                            continue
                        raise
                if _TG_CHAT_CONFIRMED != chat_id:
                    _TG_CHAT_CONFIRMED = chat_id
                    if chat_id != raw:
                        print(f"  [Telegram] ✅ chat_id подтверждён: {chat_id}")
                return

            except urllib.error.HTTPError as e:
                body_err = ""
                try: body_err = e.read().decode()
                except: pass
                err_data = {}
                try: err_data = json.loads(body_err)
                except: pass
                desc = err_data.get("description", body_err[:120])

                if e.code == 400 and use_html:
                    # HTML не прошёл (неверные теги или parse error) → пробуем plain
                    continue
                if e.code == 400:
                    print(f"  [Telegram] ⚠️ chat_id={chat_id}: {desc}")
                    break  # этот chat_id не работает
                if e.code == 403:
                    print(f"  [Telegram] 🚫 Бот не добавлен в чат {chat_id}")
                    print(f"             Добавь бота администратором канала!")
                    return
                if e.code == 429:
                    wait = int(err_data.get("parameters",{}).get("retry_after", 30))
                    print(f"  [Telegram] ⏳ Flood limit — жду {wait}с")
                    time.sleep(wait + 1)
                    continue
                print(f"  [Telegram] HTTP {e.code}: {desc}")
                return

            except Exception as e:
                err_s = str(e)
                if any(x in err_s for x in ("Name or service","Errno -3","Errno 11001")):
                    print(f"  [Telegram] ⚠️ Нет интернета — сигнал сохранён локально")
                elif any(x in err_s for x in ("10053","10054","10061","WinError","Aborted","forcibly")):
                    # WinError 10053/10054: Windows оборвал соединение (VPN/брандмауэр)
                    time.sleep(5)
                    try:
                        urllib.request.urlopen(req, timeout=30, context=_ssl())
                        return   # ✅ повтор сработал
                    except Exception:
                        print("  [Telegram] ⚠️ Соединение прервано (WinError) — сигнал в signals.csv")
                        pass  # не вышло — продолжаем
                else:
                    print(f"  [Telegram] {err_s[:80]}")
                return

    print(f"  [Telegram] ❌ Не удалось отправить (chat_id={TELEGRAM_CHAT_ID})")
    print(f"             Убедись что бот добавлен в канал администратором")


def _tg_buttons(fixture_id: int, signals_count: int) -> dict:
    """Inline-кнопки ✅/❌ для быстрой обратной связи по матчу."""
    return {
        "inline_keyboard": [[
            {"text": f"✅ Зашло",   "callback_data": f"win_{fixture_id}"},
            {"text": f"❌ Не зашло","callback_data": f"loss_{fixture_id}"},
            {"text": f"⏳ Жду",     "callback_data": f"skip_{fixture_id}"},
        ]]
    }

def tg_match(signals: list, lh: float, la: float,
             movements: dict = None, fixture_id: int = 0,
             h2h: dict = None, wx: dict = None, rest_h: int = 99,
             rest_a: int = 99, ref: dict = None,
             news_h: dict = None, news_a: dict = None,
             yc_h: dict = None, yc_a: dict = None,
             first_leg: dict = None):
    if not signals: return
    s0 = signals[0]

    # Определяем общую уверенность по лучшему сигналу
    best_edge = max(s.edge for s in signals)
    best_prob = max(s.model_prob for s in signals)

    # Шанс выигрыша — взвешенная вероятность лучшего сигнала
    win_chance = round(best_prob * 100)

    lines = [
        f"⚽ <b>{s0.match}</b>",
        f"🏟 {s0.league}  |  🕐 {s0.time}  |  📅 {_fmt_date(s0.date)}",
        f"📊 xG → H:<b>{lh:.2f}</b>  A:<b>{la:.2f}</b>  Tot:<b>{lh+la:.2f}</b>",
        f"🎲 Шанс лучшего сигнала: <b>{win_chance}%</b>",
        *([ f"⚔️ {h2h['note']}" ]         if h2h and h2h.get("note") else []),
        *([ f"{wx['note']}" ]              if wx  and wx.get("note")  else []),
        *([ f"😴 Короткий отдых хозяев ({rest_h}д)" ] if 0 < rest_h <= 2 else []),
        *([ f"😴 Короткий отдых гостей ({rest_a}д)" ] if 0 < rest_a <= 2 else []),
        *([ f"{ref['note']}" ] if ref and ref.get("note") else []),
        *([ f"📰 {news_h['note']}" ] if news_h and news_h.get("note") else []),
        *([ f"📰 {news_a['note']}" ] if news_a and news_a.get("note") else []),
        *([ f"{yc_h['note']}" ]  if yc_h and yc_h.get("note")  else []),
        *([ f"{yc_a['note']}" ]  if yc_a and yc_a.get("note")  else []),
        "━━━━━━━━━━━━━━━━━━━━━━━━━",
    ]
    for s in signals:
        # Движение линии для этого сигнала
        move_str = ""
        if movements:
            key_map = {"Победа хозяев (1)":"1","Ничья (X)":"X","Победа гостей (2)":"2"}
            sk = key_map.get(s.selection)
            if not sk and "Больше" in s.selection:
                sk = f"over_{s.selection.split()[-1]}"
            elif not sk and "Меньше" in s.selection:
                sk = f"under_{s.selection.split()[-1]}"
            mv = movements.get(sk, 0)
            if mv < -0.05:  move_str = f"  📉 линия {mv:+.2f}"
            elif mv > 0.08: move_str = f"  ⚠️ линия +{mv:.2f}"

        win_pct  = _win_chance(s.model_prob, s.edge, s.confidence)
        _src     = getattr(s, "_odds_source", None)
        _is_calc = (_src == "⚙️модель") or (s.bookmaker_odds < 1.02)
        if _is_calc:
            lines += [
                f"\n{s.confidence}  <b>{s.market}</b>{move_str}",
                f"   🎯 <b>{s.selection}</b>",
                f"   Коэф: <b>{s.bookmaker_odds:.2f}</b> [расч.]  |  Шанс: <b>{win_pct}%</b>  |  Валуй: <b>{s.edge:+.1%}</b>",
            ]
        else:
            ev     = round(s.model_prob * s.bookmaker_odds - 1.0, 3)
            ev_str = f"EV: <b>{ev:+.3f}</b>"
            lines += [
                f"\n{s.confidence}  <b>{s.market}</b>{move_str}",
                f"   🎯 <b>{s.selection}</b>",
                f"   Коэф: <b>{s.bookmaker_odds:.2f}</b> [{_src}]  |  Шанс: <b>{win_pct}%</b>",
                f"   Валуй: <b>{s.edge:+.1%}</b>  |  {ev_str}",
            ]
    lines.append(f"\n⏰ {datetime.datetime.now().strftime('%d.%m.%Y  %H:%M')}")

    buttons = _tg_buttons(fixture_id, len(signals)) if fixture_id else None
    _tg("\n".join(lines), reply_markup=buttons)

def tg_top(signals: list) -> None:
    """Топ сигналов — отдельное Telegram-сообщение."""
    if not signals:
        return
    lines = ["\U0001f3c6 <b>ТОП СИГНАЛЫ ДНЯ — по проходимости</b>\n"]
    for i, s in enumerate(signals, 1):
        _wc = _win_chance(s.model_prob, s.edge, s.confidence)
        _src = getattr(s, "_odds_source", "⚙️модель")
        if _src != "⚙️модель" and s.bookmaker_odds >= 1.02:
            _sig_line = f"   🎯 Коэф: <b>{s.bookmaker_odds:.2f}</b>  |  Шанс: <b>{_wc}%</b>  |  Валуй: <b>{s.edge:+.1%}</b>"
        else:
            _sig_line = f"   Шанс: <b>{_wc}%</b>  |  Валуй: <b>{s.edge:+.1%}</b>"
        lines.append(
            f"{i}. {s.confidence}\n"
            f"   <b>{s.match}</b>\n"
            f"   {_fmt_date(s.date)} {s.time} | {s.league}\n"
            f"   [{s.market}] \u27a1 <b>{s.selection}</b>\n"
            f"{_sig_line}\n"
        )
    lines.append(f"\u23f0 {datetime.datetime.now().strftime('%d.%m.%Y %H:%M')}")
    _tg("\n".join(lines))

def tg_summary(signals: list, n_leagues: int, n_fix: int):
    hi = sum(1 for s in signals if "ВЫСОКАЯ" in s.confidence)
    me = sum(1 for s in signals if "СРЕДНЯЯ" in s.confidence)
    lo = sum(1 for s in signals if "НИЗКАЯ"  in s.confidence)
    if signals:
        # Статистика источников коэффициентов
        pin_cnt  = sum(1 for s in signals if getattr(s, "_odds_source", "") in ("Pinnacle", "Pinnacle Guest"))
        calc_cnt = sum(1 for s in signals if getattr(s, "_odds_source", "") == "⚙️модель")
        src_str  = f"📌 Pinnacle: {pin_cnt}" if pin_cnt else ""
        if calc_cnt: src_str += f"  ⚙️ Расч: {calc_cnt}"
        _tg(
            f"📋 <b>Итоги сканирования</b>\n"
            f"Лиг: {n_leagues}  |  Матчей: {n_fix}  |  Сигналов: <b>{len(signals)}</b>\n"
            f"  🔥 {hi}  ✅ {me}  📌 {lo}\n"
            + (f"{src_str}\n" if src_str else "") +
            f"⏰ {datetime.datetime.now().strftime('%d.%m.%Y  %H:%M')}"
        )
    else:
        _tg(f"📭 Сигналов нет. Матчей: {n_fix} | Лиг: {n_leagues}\n"
            f"⏰ {datetime.datetime.now().strftime('%d.%m.%Y  %H:%M')}")



# ══════════════════════════════════════════════════════════════
#  🌧️  ПОГОДА — Open-Meteo API (бесплатно, без ключа)
#  Дождь/ветер снижают тотал на 0.3–0.5 гола
# ══════════════════════════════════════════════════════════════
# Координаты стадионов по league_id (центр города лиги)
_LEAGUE_COORDS = {
    39:  (51.5, -0.1),    # АПЛ — Лондон
    140: (40.4, -3.7),    # Ла Лига — Мадрид
    135: (45.5, 9.2),     # Серия А — Милан
    78:  (52.5, 13.4),    # Бундеслига — Берлин
    61:  (48.9, 2.3),     # Лига 1 — Париж
    88:  (52.4, 4.9),     # Эредивизи — Амстердам
    94:  (38.7, -9.1),    # Примейра — Лиссабон
    235: (55.7, 37.6),    # РПЛ (Лига ПАРИ) — Москва
    370: (55.7, 37.6),    # ФНЛ (Первая лига) — Москва (усреднено)
    2:   (51.5, -0.1),    # ЛЧ — усредн.
    3:   (51.5, -0.1),    # ЛЕ — усредн.
}
_weather_cache: dict = {}

def fetch_weather(league_id: int, date_str: str, hour: int = 17) -> dict:
    """
    Погода в день матча через Open-Meteo.
    Возвращает: {
      "rain_mm": 3.2,        # осадки мм/ч
      "wind_kmh": 28.0,      # скорость ветра км/ч
      "total_factor": 0.92,  # корректировка тотала (1.0 = норма)
      "note": "🌧️ Дождь 3.2мм, ветер 28км/ч → тотал -8%"
    }
    """
    cache_key = f"wx_{league_id}_{date_str}_{hour}"
    if cache_key in _weather_cache:
        return _weather_cache[cache_key]

    default = {"rain_mm": 0, "wind_kmh": 0, "total_factor": 1.0, "note": ""}
    coords  = _LEAGUE_COORDS.get(league_id)
    if not coords:
        return default

    lat, lon = coords
    url = (
        f"https://api.open-meteo.com/v1/forecast"
        f"?latitude={lat}&longitude={lon}"
        f"&hourly=precipitation,wind_speed_10m"
        f"&start_date={date_str}&end_date={date_str}"
        f"&timezone=auto&wind_speed_unit=kmh"
    )
    data = _http(url)
    if not data or not isinstance(data, dict):
        _weather_cache[cache_key] = default
        return default

    try:
        hourly = data.get("hourly", {})
        times  = hourly.get("time", [])
        rain   = hourly.get("precipitation", [])
        wind   = hourly.get("wind_speed_10m", [])

        # Берём час матча ± 1 час
        target = f"{date_str}T{hour:02d}:00"
        idx = None
        for i, t in enumerate(times):
            if t == target:
                idx = i
                break
        if idx is None and times:
            idx = min(hour, len(times) - 1)

        r = float(rain[idx]) if idx is not None and idx < len(rain) else 0
        w = float(wind[idx]) if idx is not None and idx < len(wind) else 0

        # Рассчитываем влияние на тотал
        # Сильный дождь (>2мм) снижает тотал
        # Сильный ветер (>30км/ч) снижает тотал
        rain_pen = 0.0
        wind_pen = 0.0
        note_parts = []

        if r >= 5.0:
            rain_pen = 0.10
            note_parts.append(f"🌧️ Сильный дождь {r:.1f}мм")
        elif r >= 2.0:
            rain_pen = 0.06
            note_parts.append(f"🌦️ Дождь {r:.1f}мм")
        elif r >= 0.5:
            rain_pen = 0.03

        if w >= 40:
            wind_pen = 0.08
            note_parts.append(f"💨 Сильный ветер {w:.0f}км/ч")
        elif w >= 28:
            wind_pen = 0.05
            note_parts.append(f"🌬️ Ветер {w:.0f}км/ч")
        elif w >= 20:
            wind_pen = 0.02

        factor = max(0.80, 1.0 - rain_pen - wind_pen)
        note   = ""
        if note_parts and factor < 0.97:
            note = " | ".join(note_parts) + f" → тотал -{(1-factor)*100:.0f}%"

        result = {
            "rain_mm":      round(r, 1),
            "wind_kmh":     round(w, 1),
            "total_factor": round(factor, 3),
            "note":         note,
        }
        _weather_cache[cache_key] = result
        return result
    except Exception:
        _weather_cache[cache_key] = default
        return default


# ══════════════════════════════════════════════════════════════
#  😴  ДНИ ОТДЫХА — усталость между матчами
# ══════════════════════════════════════════════════════════════
_rest_cache: dict = {}

def fetch_rest_days(team_id: int, match_date: str) -> int:
    """
    Считает дней отдыха с последнего матча команды.
    Менее 3 дней = усталость → штраф к xG атаки.
    Возвращает количество дней (99 = нет данных).
    """
    if not team_id or not _af_quota_ok:
        return 99
    cache_key = f"rest_{team_id}_{match_date}"
    if cache_key in _rest_cache:
        return _rest_cache[cache_key]

    resp = _af_resp("fixtures", {"team": team_id, "last": 2,
                                  "season": CURRENT_SEASON})
    if not resp:
        _rest_cache[cache_key] = 99
        return 99

    try:
        target = datetime.date.fromisoformat(match_date)
        days   = 99
        for fix in resp:
            st = fix.get("fixture", {}).get("status", {}).get("short", "")
            if st not in ("FT", "AET", "PEN"):
                continue
            dt_str = fix.get("fixture", {}).get("date", "")[:10]
            if not dt_str:
                continue
            prev = datetime.date.fromisoformat(dt_str)
            diff = (target - prev).days
            if 0 < diff < days:
                days = diff
        _rest_cache[cache_key] = days
        return days
    except Exception:
        _rest_cache[cache_key] = 99
        return 99

def rest_factor(days: int) -> float:
    """
    Штраф к xG атаки при коротком отдыхе.
    3+ дней = норма (1.0)
    2 дня   = лёгкая усталость (-5%)
    1 день  = сильная усталость (-10%)
    0 дней  = невозможно, но на случай ошибки (-15%)
    """
    if days <= 0: return 0.85
    if days == 1: return 0.90
    if days == 2: return 0.95
    return 1.0


# ══════════════════════════════════════════════════════════════
#  🔗  ФИЛЬТР КОРРЕЛЯЦИЙ — лучший сигнал из каждой группы
# ══════════════════════════════════════════════════════════════
# Рынки которые коррелируют между собой (не стоит ставить на оба)
_CORR_GROUPS = [
    # ИСХОД: 3 исхода взаимоисключают друг друга — оставляем лучший
    {"Исход Победа хозяев (1)", "Исход Ничья (X)", "Исход Победа гостей (2)"},
    # DNB и Исход: DNB хозяев включает победу хозяев → дубль риска
    {"Исход Победа хозяев (1)", "DNB Хозяева (DNB)"},
    {"Исход Победа гостей (2)", "DNB Гости (DNB)"},
    # ТОТАЛ по одной линии: Больше X и Меньше X взаимоисключают → лучший EV
    {"Тотал Больше 1.5", "Тотал Меньше 1.5"},
    {"Тотал Больше 2.5", "Тотал Меньше 2.5"},
    {"Тотал Больше 3.5", "Тотал Меньше 3.5"},
    # BUGFIX: убрали группу "все Больше вместе" — 1.5/2.5/3.5 это РАЗНЫЕ рынки,
    # можно ставить параллельно (разные вероятности, разный риск)
    # ТОТАЛ 1Т: аналогично — Больше/Меньше одной линии взаимоисключают
    {"Тотал 1Т Больше 0.5", "Тотал 1Т Меньше 0.5"},
    {"Тотал 1Т Больше 1.5", "Тотал 1Т Меньше 1.5"},
    # Азиат. и Евр. гандикап на одну сторону (высокая корреляция)
    {"Фора Хозяева -1", "Азиат.Гандикап Хозяева -0.75"},
    {"Фора Гости -1",   "Азиат.Гандикап Гости -0.75"},
]
# НЕ коррелируют (ставить параллельно можно):
# "Обе забьют Да" + "Тотал Больше 2.5" — разные механики
# "Тотал Больше 1.5" + "Тотал Больше 2.5" — разные линии, разный риск


def filter_diverse(signals: list, max_per_type: float = 0.45) -> list:
    """
    Ограничивает долю одного типа сигналов в итоговом списке.
    По умолчанию: не более 45% от одного рынка/направления.
    
    Пример: если 80% сигналов — Победа хозяев — обрезаем до 45%.
    Оставляем лучшие по edge из каждого типа.
    """
    if not signals:
        return signals
    
    from collections import defaultdict
    by_type = defaultdict(list)
    for s in signals:
        key = f"{s.market}_{s.selection}"
        by_type[key].append(s)
    
    total = len(signals)
    max_per = max(1, int(total * max_per_type))
    
    result = []
    for key, group in by_type.items():
        # Берём лучшие по edge, но не более max_per
        sorted_group = sorted(group, key=lambda x: -x.edge)
        result.extend(sorted_group[:max_per])
    
    # Сортируем обратно по edge
    result.sort(key=lambda x: -x.edge)
    return result


def filter_correlated(signals: list) -> list:
    """
    Из каждой группы коррелирующих ставок оставляет только
    сигнал с наибольшим EV. Остальные убирает.
    Независимые сигналы (разные группы) сохраняются все.
    """
    if len(signals) <= 1:
        return signals

    def _ev(s):
        return s.model_prob * s.bookmaker_odds - 1.0

    def _sig_key(s):
        return f"{s.market} {s.selection}"

    kept   = []
    removed_keys = set()

    # Для каждой группы корреляций
    for group in _CORR_GROUPS:
        # Находим сигналы из этой группы
        in_group = [s for s in signals if _sig_key(s) in group]
        if len(in_group) <= 1:
            continue
        # Лучший по EV
        best = max(in_group, key=_ev)
        # Остальные помечаем на удаление
        for s in in_group:
            if s is not best:
                removed_keys.add(_sig_key(s))

    # Собираем итог
    for s in signals:
        if _sig_key(s) not in removed_keys:
            kept.append(s)
        else:
            ev = _ev(s)
            print(f"      🔗 Фильтр корреляций: убран [{s.market}] {s.selection} "
                  f"(коррелирует с лучшим сигналом, EV={ev:+.3f})")

    return kept

# ══════════════════════════════════════════════════════════════
#  🔔  ОБРАБОТКА КНОПОК TELEGRAM (polling)
# ══════════════════════════════════════════════════════════════
_last_update_id = 0

def process_tg_callbacks():
    """
    Опрашивает Telegram на предмет нажатий кнопок ✅/❌.
    Результаты сохраняет в feedback.json для learning.py.
    Вызывается один раз после каждого скана.
    """
    global _last_update_id
    url  = (f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates"
            f"?offset={_last_update_id+1}&timeout=2&allowed_updates=callback_query")
    data = _http(url)
    if not data or not isinstance(data, dict):
        return

    for upd in data.get("result", []):
        _last_update_id = upd["update_id"]
        cb = upd.get("callback_query", {})
        if not cb:
            continue

        cdata = cb.get("data", "")
        parts = cdata.split("_", 1)
        if len(parts) != 2:
            continue

        action, fixture_id = parts[0], parts[1]
        if action not in ("win", "loss", "skip"):
            continue

        # Сохраняем фидбэк
        try:
            fb = []
            if os.path.exists("feedback.json"):
                with open("feedback.json", encoding="utf-8") as f:
                    fb = json.load(f)
            fb.append({
                "fixture_id": fixture_id,
                "result":     action,
                "by":         cb.get("from", {}).get("username", "user"),
                "at":         datetime.datetime.now().isoformat(timespec="seconds"),
            })
            with open("feedback.json", "w", encoding="utf-8") as f:
                json.dump(fb, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

        # Отвечаем на кнопку
        emoji = "✅" if action=="win" else ("❌" if action=="loss" else "⏳")
        try:
            ack_url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/answerCallbackQuery"
            ack_body = json.dumps({
                "callback_query_id": cb["id"],
                "text": f"{emoji} Записано!",
                "show_alert": False,
            }).encode()
            ack_req = urllib.request.Request(
                ack_url, data=ack_body,
                headers={"Content-Type": "application/json"}
            )
            urllib.request.urlopen(ack_req, timeout=5, context=_ssl())
        except Exception:
            pass


# ══════════════════════════════════════════════════════════════
#  👮  СТАТИСТИКА СУДЬИ
# ══════════════════════════════════════════════════════════════
_referee_cache: dict = {}

def fetch_referee_stats(fixture_id: int) -> dict:
    """
    Берёт статистику судьи назначенного на матч.
    Влияет на тотал (строгие судьи = больше остановок = меньше голов)
    и на рынок карточек.
    """
    default = {"name": "", "cards_per_game": 3.5, "pen_per_game": 0.2,
               "strict": False, "soft": False, "note": ""}
    if not _af_quota_ok or not fixture_id:
        return default

    cache_key = f"ref_{fixture_id}"
    if cache_key in _referee_cache:
        return _referee_cache[cache_key]

    resp = _af_resp("fixtures", {"id": fixture_id})
    if not resp:
        _referee_cache[cache_key] = default
        return default

    try:
        ref_name = resp[0].get("fixture", {}).get("referee", "") or ""
        if not ref_name:
            _referee_cache[cache_key] = default
            return default

        # Ищем историю судьи
        ref_resp = _af_resp("fixtures", {
            "referee": ref_name.split(" ")[0],  # только фамилия
            "last": 20,
            "season": CURRENT_SEASON,
        })
        if not ref_resp:
            _referee_cache[cache_key] = {**default, "name": ref_name}
            return _referee_cache[cache_key]

        yellow = red = pens = games = 0
        for fix in ref_resp:
            st = fix.get("fixture", {}).get("status", {}).get("short", "")
            if st not in ("FT", "AET", "PEN"):
                continue
            stats = fix.get("statistics", [])
            for team_stat in stats:
                for s in team_stat.get("statistics", []):
                    t = s.get("type", "")
                    v = s.get("value") or 0
                    if t == "Yellow Cards":  yellow += int(v)
                    elif t == "Red Cards":   red    += int(v)
            # Пенальти
            ev = fix.get("events", [])
            pens += sum(1 for e in ev if e.get("type") == "Goal"
                        and "Penalty" in str(e.get("detail", "")))
            games += 1

        if games < 3:
            _referee_cache[cache_key] = {**default, "name": ref_name}
            return _referee_cache[cache_key]

        cpg = round((yellow + red * 2) / games, 2)
        ppg = round(pens / games, 2)

        strict = cpg >= 5.5   # строгий судья
        soft   = cpg <= 2.5   # мягкий судья

        note = ""
        if strict:
            note = f"👮 Строгий судья {ref_name.split(',')[0]} ({cpg:.1f} карт/игра)"
        elif soft:
            note = f"👮 Мягкий судья {ref_name.split(',')[0]} ({cpg:.1f} карт/игра)"
        if ppg >= 0.4:
            note += f"  🥅 Любит назначать пенальти ({ppg:.1f}/игра)"

        result = {
            "name":           ref_name,
            "cards_per_game": cpg,
            "pen_per_game":   ppg,
            "strict":         strict,
            "soft":           soft,
            # Строгий судья = больше остановок = чуть меньше голов
            "total_factor":   0.96 if strict else (1.02 if soft else 1.0),
            "note":           note,
        }
        _referee_cache[cache_key] = result
        return result
    except Exception:
        _referee_cache[cache_key] = default
        return default

# ══════════════════════════════════════════════════════════════
#  🚫  ЖЁСТКИЙ ФИЛЬТР ДВИЖЕНИЯ ЛИНИИ
# ══════════════════════════════════════════════════════════════
def filter_line_movement(signals: list, movements: dict) -> list:
    """
    Убирает сигналы против которых идут деньги (линия растёт).
    Если Pinnacle поднял коэф против нашего сигнала на 0.12+ —
    значит профессионалы ставят ПРОТИВ нас → пропускаем.
    """
    if not movements:
        return signals

    KEY_MAP = {
        "Победа хозяев (1)": "1",
        "Ничья (X)":         "X",
        "Победа гостей (2)": "2",
    }
    kept = []
    for s in signals:
        sk = KEY_MAP.get(s.selection)
        if not sk:
            if "Больше" in s.selection:
                sk = f"over_{s.selection.split()[-1]}"
            elif "Меньше" in s.selection:
                sk = f"under_{s.selection.split()[-1]}"

        mv = movements.get(sk, 0) if sk else 0

        if mv >= 0.12:
            # Коэф вырос на 0.12+ — умные деньги против нас
            print(f"      🚫 Убран [{s.market}] {s.selection} "
                  f"(линия +{mv:.2f}, умные деньги ПРОТИВ)")
        else:
            kept.append(s)

    return kept


# ══════════════════════════════════════════════════════════════
#  📊  HTML ДАШБОРД — красивый отчёт по всем сигналам
#  Генерируется командой: python football_bot_v3.py report
# ══════════════════════════════════════════════════════════════
def generate_html_report():
    """
    Генерирует красивый HTML-отчёт из results.json.
    Содержит: ROI по лигам, рынкам, уверенности + таблица всех матчей.
    """
    results = _load_results()
    if not results:
        print("  ❌ results.json пуст — запусти learning.py сначала")
        return

    # Сбор статистики
    total_w = total_l = total_skip = 0
    roi_total = 0.0
    by_market  = {}
    by_league  = {}
    by_conf    = {"🔥 ВЫСОКАЯ": [0,0,0.0], "✅ СРЕДНЯЯ": [0,0,0.0], "📌 НИЗКАЯ": [0,0,0.0]}
    rows_html  = []
    by_month   = {}

    for r in results:
        for sig in r.get("signals", []):
            won  = sig.get("won")
            if won is None: total_skip += 1; continue
            odds = float(sig.get("bookmaker_odds", 2.0))
            mkt  = sig.get("market", "?")
            lg   = r.get("league", "?")
            conf = sig.get("confidence", "?")
            month = r.get("date","")[:7]
            roi_delta = (odds - 1) if won else -1

            if won: total_w += 1
            else:   total_l += 1
            roi_total += roi_delta

            by_market.setdefault(mkt,  [0,0,0.0])
            by_league.setdefault(lg,   [0,0,0.0])
            by_month.setdefault(month, [0,0,0.0])
            by_market[mkt][1]  += 1; by_market[mkt][2]  += roi_delta; by_market[mkt][0]  += int(won)
            by_league[lg][1]   += 1; by_league[lg][2]   += roi_delta; by_league[lg][0]   += int(won)
            by_month[month][1] += 1; by_month[month][2] += roi_delta; by_month[month][0] += int(won)
            for k in by_conf:
                if k in conf:
                    by_conf[k][1] += 1; by_conf[k][2] += roi_delta; by_conf[k][0] += int(won)

            color = "#22c55e" if won else "#ef4444"
            rows_html.append(
                f"<tr><td>{r.get('date','')}</td>"
                f"<td>{r.get('match','')}</td>"
                f"<td>{lg}</td>"
                f"<td>{mkt}</td>"
                f"<td>{sig.get('selection','')}</td>"
                f"<td>{odds}</td>"
                f"<td style=\'color:{color}\'><b>{'✅' if won else '❌'}</b></td>"
                f"<td style=\'color:{color}\'>{roi_delta:+.2f}</td></tr>"
            )

    total = total_w + total_l
    if total == 0: print("  ❌ Нет завершённых сигналов"); return

    acc     = total_w / total * 100
    roi_pct = roi_total / total * 100

    def table_rows(d, sort_key=2):
        out = ""
        for name, (w,t,r) in sorted(d.items(), key=lambda x: x[1][sort_key], reverse=True):
            if t == 0: continue
            color = "#22c55e" if r > 0 else "#ef4444"
            out += (f"<tr><td>{name}</td><td>{w}/{t} ({w/t*100:.0f}%)</td>"
                    f"<td style='color:{color}'>{r/t*100:+.1f}%</td></tr>")
        return out

    month_chart = ""
    for m, (w,t,r) in sorted(by_month.items()):
        if t == 0: continue
        bar_val = int(min(abs(r/t*100), 40))
        bar_col = "#22c55e" if r > 0 else "#ef4444"
        month_chart += f"<div style='display:flex;align-items:center;gap:8px;margin:4px 0'><span style='width:60px;font-size:12px'>{m}</span><div style='width:{bar_val*4}px;height:18px;background:{bar_col};border-radius:3px'></div><span style='font-size:12px'>{r/t*100:+.1f}%</span></div>"

    html = f"""<!DOCTYPE html>
<html lang="ru">
<head><meta charset="UTF-8"><title>Football Bot Analytics</title>
<style>
  body {{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:#0f172a;color:#e2e8f0;margin:0;padding:20px}}
  .header {{background:linear-gradient(135deg,#1e40af,#7c3aed);padding:24px;border-radius:12px;margin-bottom:20px}}
  h1 {{margin:0;font-size:24px}} h2 {{color:#94a3b8;font-size:14px;font-weight:normal;margin:4px 0 0 0}}
  .kpi-grid {{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:20px}}
  .kpi {{background:#1e293b;border-radius:10px;padding:16px;text-align:center}}
  .kpi-val {{font-size:28px;font-weight:700;margin:4px 0}}
  .kpi-label {{font-size:12px;color:#94a3b8}}
  .green {{color:#22c55e}} .red {{color:#ef4444}} .blue {{color:#60a5fa}}
  .grid2 {{display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-bottom:20px}}
  .card {{background:#1e293b;border-radius:10px;padding:16px}}
  .card h3 {{margin:0 0 12px 0;font-size:14px;color:#94a3b8;text-transform:uppercase;letter-spacing:.5px}}
  table {{width:100%;border-collapse:collapse;font-size:13px}}
  th {{background:#0f172a;padding:8px;text-align:left;color:#64748b;font-weight:500}}
  td {{padding:7px 8px;border-bottom:1px solid #1e293b}}
  tr:hover td {{background:#1e293b}}
  .results-table {{max-height:400px;overflow-y:auto}}
  .badge {{background:#1e40af;color:#93c5fd;padding:2px 8px;border-radius:4px;font-size:11px}}
</style></head>
<body>
<div class="header">
  <h1>⚽ Football Bot Analytics</h1>
  <h2>Сгенерировано: {datetime.datetime.now().strftime('%d.%m.%Y %H:%M')}</h2>
</div>
<div class="kpi-grid">
  <div class="kpi"><div class="kpi-val blue">{total}</div><div class="kpi-label">Всего ставок</div></div>
  <div class="kpi"><div class="kpi-val {'green' if acc >= 50 else 'red'}">{acc:.1f}%</div><div class="kpi-label">Точность</div></div>
  <div class="kpi"><div class="kpi-val {'green' if roi_pct >= 0 else 'red'}">{roi_pct:+.1f}%</div><div class="kpi-label">ROI на ставку</div></div>
  <div class="kpi"><div class="kpi-val {'green' if roi_total >= 0 else 'red'}">{roi_total:+.2f}</div><div class="kpi-label">Итог (ед.)</div></div>
</div>
<div class="grid2">
  <div class="card"><h3>📈 ROI по месяцам</h3>{month_chart}</div>
  <div class="card"><h3>🎯 По уверенности</h3>
    <table><tr><th>Уровень</th><th>Точность</th><th>ROI</th></tr>{table_rows({{k:v for k,v in by_conf.items()}})}</table>
  </div>
</div>
<div class="grid2">
  <div class="card"><h3>🎰 По рынкам</h3>
    <table><tr><th>Рынок</th><th>Точность</th><th>ROI</th></tr>{table_rows(by_market)}</table>
  </div>
  <div class="card"><h3>🏆 По лигам</h3>
    <table><tr><th>Лига</th><th>Точность</th><th>ROI</th></tr>{table_rows(by_league)}</table>
  </div>
</div>
<div class="card"><h3>📋 Все ставки</h3>
  <div class="results-table">
  <table><tr><th>Дата</th><th>Матч</th><th>Лига</th><th>Рынок</th><th>Выбор</th><th>Коэф</th><th>Рез.</th><th>ROI</th></tr>
  {''.join(reversed(rows_html))}
  </table></div>
</div>
</body></html>"""

    fname = f"analytics_{datetime.datetime.now().strftime('%Y%m%d_%H%M')}.html"
    with open(fname, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"  ✅ Отчёт создан: {fname}")
    print(f"  📊 Открой в браузере: {os.path.abspath(fname)}")
    return fname

# ══════════════════════════════════════════════════════════════
#  📊  ЕЖЕНЕДЕЛЬНЫЙ ОТЧЁТ + АЛЕРТ ПРОСАДКИ
# ══════════════════════════════════════════════════════════════
RESULTS_FILE = "results.json"

def _load_results() -> list:
    try:
        if os.path.exists(RESULTS_FILE):
            with open(RESULTS_FILE, encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return []

def send_weekly_report():
    """
    Формирует и отправляет еженедельный отчёт в Telegram.
    Вызывать каждое воскресенье вечером.
    """
    results = _load_results()
    if not results:
        return

    # Берём матчи за последние 7 дней
    week_ago = (datetime.date.today() - datetime.timedelta(days=7)).isoformat()
    week_res = [r for r in results if r.get("date", "") >= week_ago]
    if not week_res:
        return

    total = won = 0
    roi   = 0.0
    mkt   = {}
    conf_stats = {"🔥 ВЫСОКАЯ": [0,0,0.0], "✅ СРЕДНЯЯ": [0,0,0.0], "📌 НИЗКАЯ": [0,0,0.0]}

    for r in week_res:
        for sig in r.get("signals", []):
            o = sig.get("won")
            if o is None: continue
            total += 1
            m    = sig.get("market", "?")
            odds = float(sig.get("bookmaker_odds", 2.0))
            conf = sig.get("confidence", "")
            mkt.setdefault(m, [0, 0, 0.0])
            if o:
                won += 1; roi += (odds - 1)
                mkt[m][0] += 1; mkt[m][2] += (odds - 1)
            else:
                roi -= 1; mkt[m][2] -= 1
            mkt[m][1] += 1
            for k in conf_stats:
                if k in conf:
                    conf_stats[k][1] += 1
                    if o: conf_stats[k][0] += 1; conf_stats[k][2] += (odds-1)
                    else: conf_stats[k][2] -= 1
                    break

    if not total:
        return

    acc  = won / total * 100
    roi_pct = roi / total * 100
    emoji = "🟢" if roi_pct > 0 else "🔴"

    d_from = week_ago[5:].replace("-", ".")
    d_to   = datetime.date.today().strftime("%d.%m")

    lines = [
        f"📊 <b>ЕЖЕНЕДЕЛЬНЫЙ ОТЧЁТ {d_from}–{d_to}</b>",
        f"{'─'*30}",
        f"Сигналов: <b>{total}</b>  |  Прошло: <b>{won}</b> ({acc:.1f}%)",
        f"{emoji} ROI: <b>{roi_pct:+.1f}%</b> на сигнал",
        "",
        "<b>По уверенности:</b>",
    ]
    for conf, (w, t, r) in conf_stats.items():
        if t > 0:
            lines.append(f"  {conf}: {w}/{t} ({w/t*100:.0f}%)  ROI {r/t*100:+.1f}%")

    lines.append("")
    lines.append("<b>По рынкам:</b>")
    for name, (w, t, r) in sorted(mkt.items(), key=lambda x: x[1][2], reverse=True):
        if t > 0:
            em = "🟢" if r > 0 else "🔴"
            lines.append(f"  {em} {name}: {w}/{t}  ROI {r/t*100:+.1f}%")

    ts = datetime.datetime.now().strftime('%d.%m.%Y %H:%M')
    lines.append(f"\n⏰ {ts}")
    _tg("\n".join(lines))
    print("  📊 Еженедельный отчёт отправлен")

def check_drawdown_alert():
    """
    Алерт просадки: последние 10 < 40% — снизить ставки.
    Горячая серия: последние 10 >= 75% — модель в форме.
    """
    results = _load_results()
    if not results:
        return
    recent_sigs = []
    for r in reversed(results):
        for sig in reversed(r.get("signals", [])):
            if sig.get("won") is not None:
                recent_sigs.append(sig)
            if len(recent_sigs) >= 10:
                break
        if len(recent_sigs) >= 10:
            break
    if len(recent_sigs) < 10:
        return
    won = sum(1 for s in recent_sigs if s.get("won") is True)
    acc = won / len(recent_sigs)
    ts  = datetime.datetime.now().strftime("%d.%m.%Y %H:%M")
    if acc < 0.40:
        parts = ["⚠️ <b>АЛЕРТ ПРОСАДКИ</b>",
                 f"Последние 10: {won}/10 ({acc*100:.0f}%)",
                 "Снизьте ставки до восстановления формы.",
                 f"⏰ {ts}"]
        _tg("\n".join(parts))
        print(f"  ⚠️ Просадка {won}/10 — алерт отправлен")
    elif acc >= 0.75 and won >= 8:
        parts = ["🔥 <b>ГОРЯЧАЯ СЕРИЯ!</b>",
                 f"Последние 10: {won}/10 ({acc*100:.0f}%)",
                 "Модель в отличной форме 🎯",
                 f"⏰ {ts}"]
        _tg("\n".join(parts))
        print(f"  🔥 Горячая серия {won}/10!")


# ══════════════════════════════════════════════════════════════
#  🟨  УГРОЗА ДИСКВАЛИФИКАЦИИ — игроки под угрозой
#  4+ жёлтых карточки в лиге = пропускает следующий матч
# ══════════════════════════════════════════════════════════════
_susp_cache: dict = {}

def fetch_yellow_card_risk(team_id: int, team_name: str,
                            fixture_id: int) -> dict:
    """
    Проверяет игроков с накопленными жёлтыми карточками.
    В большинстве лиг: 4 жёлтых = дисквалификация.
    Возвращает: {
      "risk_players": ["Роналду (3 ж.к.)", "Бензема (3 ж.к.)"],
      "xg_penalty": 0.05,   # снижение xG если ключевые игроки на грани
      "note": "⚠️ Роналду (3 ж.к.) — под угрозой дисквалификации"
    }
    """
    cache_key = f"yc_{team_id}_{fixture_id}"
    if cache_key in _susp_cache:
        return _susp_cache[cache_key]
    default = {"risk_players": [], "xg_penalty": 1.0, "note": ""}
    if not _af_quota_ok or not team_id:
        _susp_cache[cache_key] = default
        return default
    try:
        resp = _af_resp("players", {
            "team": team_id, "season": CURRENT_SEASON
        })
        if not resp:
            _susp_cache[cache_key] = default
            return default
        risk = []
        for p in resp:
            stats_list = p.get("statistics", [])
            if not stats_list:
                continue
            st = stats_list[0]
            yellow = st.get("cards", {}).get("yellow", 0) or 0
            pos    = st.get("games", {}).get("position", "")
            name   = p.get("player", {}).get("name", "")
            # 3 жёлтых = следующая = дисквалификация в большинстве лиг
            if yellow >= 3:
                risk.append((name, yellow, pos))
        if not risk:
            _susp_cache[cache_key] = default
            return default
        # Penalty: атакующие под угрозой = больший штраф
        penalty = 1.0
        notes_list = []
        for name, yc, pos in risk[:3]:
            impact = 0.06 if pos in ("Attacker","Forward") else 0.03
            penalty -= impact
            notes_list.append(f"{name} ({yc} ж.к.)")
        penalty = max(0.82, penalty)
        note = f"🟨 Под угрозой: {', '.join(notes_list)}" if notes_list else ""
        result = {
            "risk_players": notes_list,
            "xg_penalty":   round(penalty, 3),
            "note":         note
        }
        _susp_cache[cache_key] = result
        return result
    except Exception:
        _susp_cache[cache_key] = default
        return default

# ══════════════════════════════════════════════════════════════
#  🚀  СКАНЕР
# ══════════════════════════════════════════════════════════════

def _best_info_signal(lh: float, la: float, match, league_id: int, 
                       bk_odds: dict = None) -> "Signal | None":
    """
    Генерирует ИНФОРМАЦИОННЫЙ сигнал когда нет value-ставок.
    Показывает лучший рынок по модели без минимального edge.
    Гарантирует хоть какой-то вывод для каждого матча.
    """
    bk = bk_odds or {}
    label = f"{_ru(match.home.name)} vs {_ru(match.away.name)}"

    # Строим матрицу вероятностей
    engine = Poisson()
    m = engine.matrix(lh, la, league_id)

    best = None
    best_edge = -999.0

    candidates = []

    # 1. Исходы 1X2
    ph, pd, pa = engine.prob_1x2(m)
    for prob, sel, key in [(ph,"Победа хозяев","1"),(pd,"Ничья","X"),(pa,"Победа гостей","2")]:
        bk_val = bk.get(key)
        if bk_val and bk_val > 1.01:
            imp = 1.0 / bk_val
            bk1 = bk.get("1"); bkx = bk.get("X"); bk2 = bk.get("2")
            if bk1 and bkx and bk2:
                no_vig = imp / (1/bk1 + 1/bkx + 1/bk2)
            else:
                no_vig = imp * 0.93
            edge = round(prob - no_vig, 4)
            candidates.append(("Исход", sel, round(prob,4), bk_val, edge))

    # 2. Тоталы
    for line in [1.5, 2.5, 3.5]:
        po, pu = engine.prob_total(m, line)
        for prob, sel, key in [(po, f"Больше {line}", f"over_{line}"),
                               (pu, f"Меньше {line}", f"under_{line}")]:
            bk_val = bk.get(key)
            if bk_val and bk_val > 1.01:
                twin = key.replace("over_","under_") if "over_" in key else key.replace("under_","over_")
                bk_t = bk.get(twin)
                if bk_t and bk_t > 1.01:
                    no_vig = (1/bk_val) / (1/bk_val + 1/bk_t)
                else:
                    no_vig = (1/bk_val) * 0.92
                edge = round(prob - no_vig, 4)
                candidates.append(("Тотал", sel, round(prob,4), bk_val, edge))

    # 3. DNB
    ph_d, pa_d = engine.prob_dnb(m)
    for prob, sel, key in [(ph_d,"Хозяева (Ф0)","dnb_home"),(pa_d,"Гости (Ф0)","dnb_away")]:
        bk_val = bk.get(key)
        if bk_val and bk_val > 1.01:
            no_vig = (1/bk_val) * 0.93
            edge = round(prob - no_vig, 4)
            candidates.append(("Фора 0", sel, round(prob,4), bk_val, edge))

    if not candidates:
        # Нет котировок — показываем топ прогноз по xG
        ph, pd, pa = engine.prob_1x2(m)
        # Показываем ВСЕ три исхода как информацию
        outcomes = [("Победа хозяев", ph), ("Ничья", pd), ("Победа гостей", pa)]
        best_sel, best_prob = max(outcomes, key=lambda x: x[1])
        # Добавляем тотал прогноз если высокий
        po25, _ = engine.prob_total(m, 2.5)
        po15, _ = engine.prob_total(m, 1.5)
        if po25 > best_prob:
            best_sel = f"Больше 2.5 ({po25:.0%})"
            best_prob = po25
        elif po15 > best_prob:
            best_sel = f"Больше 1.5 ({po15:.0%})"
            best_prob = po15
        return Signal(
            match=label, league=match.league,
            date=match.date, time=match.time,
            market="📊 xG прогноз",
            selection=f"{best_sel}  |  xG {lh:.1f}:{la:.1f}",
            model_prob=round(best_prob, 4),
            bookmaker_odds=0.0,
            implied_prob=round(best_prob, 4),
            edge=0.0,
            kelly_stake=0.0,
            confidence="📊 ИНФО",
        )

    # Выбираем кандидата с лучшим edge (даже отрицательным)
    best = max(candidates, key=lambda x: x[4])
    market, sel, prob, bk_val, edge = best
    return Signal(
        match=label, league=match.league,
        date=match.date, time=match.time,
        market=market, selection=sel,
        model_prob=prob,
        bookmaker_odds=bk_val,
        implied_prob=round(1.0/bk_val, 4),
        edge=edge,
        kelly_stake=0.0,
        confidence="📊 ИНФО",
    )


def run_scan(days_ahead: int = 3, today_only: bool = False):
    # ── Сброс состояния при каждом запуске ──────────────────────
    global _af_quota_ok, _af_quota_rem, _AF_ECONOMY_MODE, _fonbet_unavailable, _odds_api_auth_ok
    _af_quota_ok       = True
    _af_quota_rem      = 100
    _AF_ECONOMY_MODE   = False
    _fonbet_unavailable = False
    _odds_api_auth_ok  = True   # пересбрасываем при каждом запуске
    global _sofa_blocked
    _sofa_blocked = False

    # ── Авто-верификация вчерашних сигналов ─────────────────────
    try:
        verify_yesterday_signals()
        print_ml_stats()
    except Exception:
        pass
    _load_af_disk_cache()            # ← ПЕРВЫМ: кэш нужен до любых AF запросов
    _load_ml_weights()               # подгружаем ML-пороги
    global _LEARNED_STATS, _ELO
    _LEARNED_STATS = _load_team_stats()   # обновляем перед каждым сканом
    if _LEARNED_STATS:
        print(f"  🧠 Загружено обученных команд: {len(_LEARNED_STATS)}")
    _ELO = _load_elo()
    if _ELO:
        print(f"  📊 Elo-рейтингов загружено: {len(_ELO)}")
    else:
        # ELO не загружен — попробуем сразу (fetch_clubelo_ratings вызывается ниже)
        print("  ⚠️  Elo: файл не найден — загружу с ClubElo.com при запуске")
    _load_opening_odds()
    if _opening_odds_db:
        print(f"  📈 Исторических линий: {len(_opening_odds_db)} матчей")
    _update_kelly_multiplier()
    if _KELLY_MULTIPLIER != 1.0:
        mode = "🔥 горячая" if _KELLY_MULTIPLIER > 1 else "⚠️ просадка"
        print(f"  💰 Kelly × {_KELLY_MULTIPLIER} ({mode})")
    engine  = Poisson()
    all_sig = []
    n_fix   = 0
    _scanned_fids: set[int] = set()   # FIX: дедупликация fixture_id

    today  = datetime.date.today()
    d_from = today.isoformat()
    # Загружаем актуальные Elo с ClubElo.com — 1 запрос на весь скан
    try:
        fetch_clubelo_ratings()
    except Exception:
        pass
    # today_only: берём сегодня + завтра (UTC±3 поправка)
    if today_only:
        d_from_fetch = d_from          # начинаем с сегодня
        d_to   = (today + datetime.timedelta(days=1)).isoformat()
    else:
        d_from_fetch = d_from
        d_to   = (today + datetime.timedelta(days=days_ahead)).isoformat()

    print(f"\n{'═'*62}")
    print(f"  ⚽  FOOTBALL BOT v3  |  {datetime.datetime.now().strftime('%d.%m.%Y  %H:%M')}")
    print(f"{'═'*62}")
    # Сначала проверяем Guest API (без аккаунта) — затем обычный
    if not test_pinnacle_guest():
        test_pinnacle_connection()

    # ── Проверка Odds API: ключ + остаток квоты ─────────────────
    if ODDS_API_KEY:
        # /sports — бесплатный (0 кредитов), проверяет валидность ключа
        _key_test = _http(f"https://api.the-odds-api.com/v4/sports/?apiKey={ODDS_API_KEY}")
        if _key_test is None:
            print("  🔑 Odds API: ключ недействителен")
            print("     → Получи бесплатный ключ на https://the-odds-api.com (500 req/мес)")
            _odds_api_auth_ok = False
        elif isinstance(_key_test, list):
            # Ключ валиден — проверяем реальный остаток через заголовок
            # (заголовок X-Requests-Remaining приходит в _http и сохраняется в _odds_api_remaining)
            _rem = _odds_api_remaining  # заполняется в _http при каждом запросе к odds-api
            if _rem == 0:
                print(f"  ⚠️  Odds API: квота исчерпана (0/500 кредитов)")
                print(f"     → Сбрасывается 1-го числа каждого месяца")
                print(f"     → Или зарегистрируй новый аккаунт для доп. 500 кредитов")
                _odds_api_auth_ok = False
            elif _rem > 0:
                _status = "✅" if _rem > 50 else ("⚠️" if _rem > 10 else "🔴")
                print(f"  {_status} Odds API: {_rem} кредитов осталось")
                _odds_api_auth_ok = _rem > 1
            else:
                # Заголовок не пришёл (старый запрос без rem) — делаем тест-запрос к /odds
                # чтобы узнать точно
                _sport_test = "soccer_epl"
                _test_url = (f"https://api.the-odds-api.com/v4/sports/{_sport_test}/odds/"
                             f"?apiKey={ODDS_API_KEY}&regions=eu&markets=h2h&oddsFormat=decimal")
                _odds_test = _http(_test_url)
                _rem2 = _odds_api_remaining
                if isinstance(_odds_test, dict) and "OUT_OF_USAGE" in str(_odds_test.get("error_code","")):
                    print(f"  ⚠️  Odds API: квота исчерпана — сбрасывается 1-го числа")
                    print(f"     → Зарегистрируй новый аккаунт: https://the-odds-api.com")
                    _odds_api_auth_ok = False
                elif _rem2 == 0:
                    print(f"  ⚠️  Odds API: квота исчерпана (0 кредитов)")
                    _odds_api_auth_ok = False
                elif isinstance(_odds_test, list) or _rem2 > 0:
                    _status = "✅" if _rem2 > 50 else ("⚠️" if _rem2 > 5 else "🔴")
                    print(f"  {_status} Odds API: {_rem2} кредитов осталось")
                    _odds_api_auth_ok = _rem2 > 1
                else:
                    print(f"  ✅ Odds API: ключ действителен")
                    _odds_api_auth_ok = True

    # ── Статус API-Football ────────────────────────────────────
    # Используем _http напрямую — status не тратит quota (кэш)
    # НО при очень малой квоте даже кэш-промах опасен — пропускаем
    if _af_quota_rem <= 2 and not API_FOOTBALL_KEY:
        print(f"  ℹ️  AF статус пропущен (нет ключа)")
        _af_quota_ok = False
        _st_data = {}
    _st_url  = f"https://v3.football.api-sports.io/status"
    _st_data = _http(_st_url, {"x-apisports-key": API_FOOTBALL_KEY})
    if not isinstance(_st_data, dict):
        _st_data = {}
    _st_resp = _st_data.get("response", {})
    if isinstance(_st_resp, list):
        _st_resp = _st_resp[0] if _st_resp else {}
    if isinstance(_st_resp, dict):
        req = _st_resp.get("requests", {})
        sub = _st_resp.get("subscription", {})
        try:
            cur = int(req.get("current", 0))
            lim = int(req.get("limit_day", 100))
            rem = lim - cur
            _af_quota_ok  = rem > 3
            _af_quota_rem = rem
            plan = sub.get("plan", "Free")
            status_icon = "✅" if rem > 20 else ("⚠️" if rem > 5 else "🔴")
            print(f"\n{status_icon} API-Football: {plan} | Запросов: {cur}/{lim} | Осталось: {rem}")
        except Exception as _e:
            print(f"  ⚠️  AF статус: ошибка парсинга ({_e})")
    else:
        # Статус не получен — продолжаем с дефолтными 100
        print(f"  ⚠️  AF статус недоступен — работаем с quota={_af_quota_rem}")
    time.sleep(2)

    # ── Предзагрузка через football-data.org (1 запрос на всё) ─
    print(f"\n📥 Загружаю матчи football-data.org: {d_from_fetch} → {d_to}")
    all_fd = fetch_all_by_date_fd(d_from_fetch, d_to)

    if all_fd:
        unique_comps = sorted(set(m.get("_league_name","?") for m in all_fd))
        print(f"   ✅ FD: {len(all_fd)} матчей (топ-лиги: {', '.join(unique_comps)})")
    else:
        print("   ⚠️  FD: матчей нет (покрывает только АПЛ/ЛаЛига/СерияА/Бундеслига/ЛЧ)")

    # ── ВСЕГДА дополняем AF кубки / доп. лиги (не только когда FD пустой) ──
    # При квоте ≤ 5 — НЕ тратим последние запросы на загрузку расписания.
    # Используем FD + дисковый кэш.
    if _af_quota_rem <= 5:
        print(f"   ⚠️  AF квота критическая ({_af_quota_rem} req) — используем FD + кэш")
        af_all = []
        # Пробуем достать из дискового кэша прошлого запроса
        import json as _js
        for _ck in (f"af_all_{d_from_fetch}_{d_to}", f"af_all_{d_from}_{d_to}",
                    f"af_all_{d_from_fetch}_{d_from_fetch}", f"af_all_{d_from}_{d_from}"):
            if _ck in _fd_cache and _fd_cache[_ck]:
                af_all = _fd_cache[_ck]
                print(f"   💾 Восстановлено из кэша: {len(af_all)} матчей")
                break
    else:
        print(f"   📡 Дополнение через API-Football (кубки, доп. лиги)...")
        af_all = fetch_all_by_date_af(d_from_fetch, d_to)
    if af_all:
        # Объединяем: FD-матчи + AF-матчи (дедупликация по fixture_id)
        fd_ids = set(m.get("fixture",{}).get("id",0) for m in all_fd)
        af_new = [f for f in af_all if f.get("fixture",{}).get("id",0) not in fd_ids]
        all_fd = all_fd + af_new
        # Показываем только новые турниры от AF
        af_comps = sorted(set(f.get("_league_name","?") for f in af_new))
        if af_new:
            print(f"   ✅ AF доп: +{len(af_new)} матчей | {', '.join(af_comps)}")
        else:
            print(f"   ℹ️  AF: матчей сверх FD нет (на выбранную дату)")
    else:
        if not af_all and not all_fd:
            # ── Последний шанс: дисковый кэш ─────────────────────
            _rescued = []
            import json as _json
            # Перебираем все возможные ключи кэша
            for _fix_key in [
                f"fixtures|{_json.dumps({'date': d_from_fetch}, sort_keys=True)}",
                f"fixtures|{_json.dumps({'date': d_from}, sort_keys=True)}",
            ]:
                _cached_fix = _AF_DISK_CACHE.get(_fix_key)
                if _cached_fix and isinstance(_cached_fix, dict):
                    _resp_list = _cached_fix.get("response", [])
                    league_ids_set = set(LEAGUES.keys())
                    for fix in _resp_list:
                        lid = fix.get("league", {}).get("id", 0)
                        if lid in league_ids_set:
                            fix["_league_id"]   = lid
                            fix["_league_name"] = LEAGUES.get(lid, "?")
                            _rescued.append(fix)
                    if _rescued:
                        break
            if _rescued:
                all_fd = _rescued
                print(f"   💾 Восстановлено из кэша: {len(_rescued)} матчей")
            elif all_fd:
                pass  # FD дал матчи — всё ок
            else:
                print("   ⚠️  Матчей не найдено")
                if not _af_quota_ok:
                    today_utc = datetime.datetime.utcnow()
                    reset_h = 24 - today_utc.hour
                    print(f"      AF квота исчерпана — сброс через ~{reset_h}ч (полночь UTC)")
                    print(f"      ▶ Матчи из football-data.org: только АПЛ/ЛаЛига/СерияА/Бундеслига")
                    print(f"      ▶ Данные сохранены в af_cache.json для следующего запуска")
                elif _af_quota_rem < 5:
                    print(f"      AF: осталось {_af_quota_rem} запросов — экономим!")
                else:
                    print("      AF: сетевая ошибка — проверь интернет/файрвол")

    if all_fd:
        unique_dates = sorted(set(m.get("fixture",{}).get("date","")[:10] for m in all_fd))
        unique_comps = sorted(set(m.get("_league_name","?") for m in all_fd))
        print(f"   📊 Итого: {len(all_fd)} матчей | {', '.join(unique_dates)}")
        print(f"   🏆 Турниры: {', '.join(unique_comps)}")

    # Если всё ещё пусто и today_only — расширяем до 3 дней (хоть что-то найдём)
    if not all_fd and today_only:
        print("   🔄 Режим today пустой — расширяем до 3 дней...")
        _ext_to = (today + datetime.timedelta(days=3)).isoformat()
        _ext_fd = fetch_all_by_date_fd(d_from, _ext_to)
        _ext_af = fetch_all_by_date_af(d_from, _ext_to)
        if _ext_fd: all_fd.extend(_ext_fd)
        if _ext_af:
            _ext_ids = set(m.get("fixture",{}).get("id",0) for m in all_fd)
            all_fd.extend(f for f in _ext_af if f.get("fixture",{}).get("id",0) not in _ext_ids)
        if all_fd:
            print(f"   ✅ Расширенный поиск: {len(all_fd)} матчей")

    # КРИТИЧНО: инжектируем all_fd в _fd_cache чтобы get_fixtures() его нашёл.
    # Без этого цикл лиг получает 0 матчей даже когда all_fd заполнен FD/кэшем.
    if all_fd:
        _d3_inj = (today + datetime.timedelta(days=3)).isoformat()
        # Инжектируем под всеми возможными ключами
        for _key in (
            f"{d_from}|{d_from}", f"{d_from}|{d_to}", f"{d_from}|{_d3_inj}",
            f"{d_from_fetch}|{d_to}", f"{d_from_fetch}|{d_from}",
        ):
            _fd_cache[_key] = all_fd
        _fd_cache[f"af_all_{d_from}_{d_from}"]       = all_fd
        _fd_cache[f"af_all_{d_from}_{d_to}"]         = all_fd
        _fd_cache[f"af_all_{d_from_fetch}_{d_to}"]   = all_fd

    print(f"\n  Период: {d_from} → {d_to}  |  Лиг: {len(LEAGUES)}")
    print(f"{'─'*62}")

    # Считаем матчи напрямую из all_fd — БЕЗ вызова get_fixtures() 42 раза
    # (42 вызова могли тратить квоту AF на лиги без матчей)
    _dt_window_start = d_from
    _dt_window_end   = (today + datetime.timedelta(days=1)).isoformat()
    if today_only:
        _all_fixtures_today = [
            f for f in all_fd
            if _dt_window_start <= f.get("fixture",{}).get("date","")[:10] <= _dt_window_end
        ]
    else:
        _all_fixtures_today = list(all_fd)
    _total_matches = max(1, len(_all_fixtures_today))
    _budget_per_match = max(1, int(_af_quota_rem / max(_total_matches, 1)))
    print(f"  💰 Квота AF: {_af_quota_rem} | Матчей: {_total_matches} | Бюджет: {_budget_per_match} req/матч")
    fetch_clubelo_ratings()          # обновляем Elo с ClubElo.com
    _cleanup_old_caches()            # чистим старые кэш файлы

    # ── Обход лиг ─────────────────────────────────────────────
    for league_id, league_name in LEAGUES.items():
        fixtures = list(get_fixtures(league_id, d_from_fetch, d_to))
        # OpenLigaDB — Бундеслига без AF квоты
        if not fixtures and league_id == 78:
            _oldb = fetch_openligadb(d_from_fetch)
            if _oldb:
                fixtures = _oldb
                print(f"  🏆 Бундеслига: {len(fixtures)} матчей из OpenLigaDB")
        if not fixtures:
            continue

        # today_only: только матчи сегодня/завтра, которые ещё не сыграны
        if today_only:
            def _not_played(f):
                d = f.get("fixture",{}).get("date","")[:10]
                if not (_dt_window_start <= d <= _dt_window_end):
                    return False
                status = f.get("fixture",{}).get("status",{})
                short  = status.get("short","") if isinstance(status, dict) else ""
                # NS = Not Started, TBD = To Be Defined, PST = Postponed
                # Если нет статуса — пропускаем только если дата прошла
                if short in ("FT","AET","PEN","ABD","CANC","AWD","WO"):
                    return False  # уже завершён
                return True
            fixtures = [f for f in fixtures if _not_played(f)]
            if not fixtures:
                continue

        print(f"\n📂 {league_name}  ({len(fixtures)} матчей)")
        n_fix += len(fixtures)

        for fix in fixtures:
            try:
                fdata = fix["fixture"]
                hdata = fix["teams"]["home"]
                adata = fix["teams"]["away"]
                fid   = fdata["id"]
                fdt   = fdata["date"]
                fdate, ftime = _utc_to_local(fdt)
                hid   = hdata["id"]
                aid   = adata["id"]
                hname_en = hdata["name"]   # оригинал EN — для lookup в TEAM_DB
                aname_en = adata["name"]   # оригинал EN — для lookup в TEAM_DB
                hname = _ru(hname_en)       # русское — только для вывода
                aname = _ru(aname_en)
            except (KeyError, TypeError):
                continue

            # FIX: дедупликация fixture_id и валидация лиги/даты
            # Пропускаем лиги из LEAGUES_SKIP
            first_leg = None   # инициализация (устанавливается ниже для ЛЧ/ЛЕ/ЛК)
            if league_id in LEAGUES_SKIP:
                continue
            if fid in _scanned_fids:
                continue
            if fid > 0:
                _scanned_fids.add(fid)
            if fdate < d_from or fdate > d_to:
                continue   # дата за пределами окна
            fix_lid = fix.get("_league_id", league_id)
            if fix_lid and fix_lid != league_id:
                continue   # фантомный матч из другой лиги

            if _af_quota_rem == 0:
                quota_str = " [AF:исчерпан→FD+TEAM_DB]"
            elif _af_quota_rem < 5:
                quota_str = f" [AF:{_af_quota_rem}→экономия]"
            elif _af_quota_rem < 50:
                quota_str = f" [AF:{_af_quota_rem}]"
            else:
                quota_str = ""
            print(f"\n   ⚽ {hname} vs {aname}  ({_fmt_date(fdate)} {ftime}){quota_str}")

            # ── СТЕК ИСТОЧНИКОВ ДАННЫХ ────────────────────────
            # Приоритет: Understat > API-Football > TEAM_DB > Среднее лиги
            # lookup всегда по английскому имени — TEAM_DB хранит EN ключи
            # ────────────────────────────────────────────────────

            # 1. Understat — реальный xG (топ-6 лиг, бесплатно)
            us_h = fetch_understat_team(hname_en, league_id)
            us_a = fetch_understat_team(aname_en, league_id)

            if us_h:
                # Understat: сезонный xG + recent (последние 6 матчей) — взвешенно
                _us_xg  = us_h["xg_per_game"]  * 0.55 + us_h.get("recent_xg",  us_h["xg_per_game"])  * 0.45
                _us_xga = us_h["xga_per_game"] * 0.55 + us_h.get("recent_xga", us_h["xga_per_game"]) * 0.45
                hs = TeamStats(hname, hid, round(_us_xg, 3), round(_us_xga, 3), 0.08)
                if us_h.get("recent_xg", 0) > 0.2:
                    hs.home_gs = round(us_h["recent_xg"] * 1.10, 3)
                    hs.away_gs = round(us_h["recent_xg"] * 0.90, 3)
                if us_h.get("recent_xga", 0) > 0.2:
                    hs.home_gc = round(us_h["recent_xga"] * 0.95, 3)
                    hs.away_gc = round(us_h["recent_xga"] * 1.10, 3)
                # xg_trend из Understat — последние 3 vs предыдущие 3
                if us_h.get("xg_trend", 0) > 0.1:
                    hs.attack_trend = round(min(max(us_h["xg_trend"], 0.75), 1.35), 3)
                src_h = "📐"   # Understat
            else:
                # 2. TEAM_DB / API-Football
                hgs, hgc, h_found = _lookup_team(hname_en, True, league_id)
                if h_found:
                    hs = TeamStats(hname, hid, hgs, hgc, 0.08)
                    src_h = "📊"
                else:
                    # AF статистика только при достаточной квоте
                    hs = fetch_team_stats(hid, hname_en, league_id) if (_af_quota_ok and _budget_per_match >= 2) else None
                    if hs:
                        src_h = "📡"
                    else:
                        hs = TeamStats(hname, hid, hgs, hgc, 0.08)
                        src_h = "ℹ️"

            if us_a:
                _us_xg_a  = us_a["xg_per_game"]  * 0.55 + us_a.get("recent_xg",  us_a["xg_per_game"])  * 0.45
                _us_xga_a = us_a["xga_per_game"] * 0.55 + us_a.get("recent_xga", us_a["xga_per_game"]) * 0.45
                as_ = TeamStats(aname, aid, round(_us_xg_a, 3), round(_us_xga_a, 3), 0.0)
                if us_a.get("recent_xg", 0) > 0.2:
                    as_.home_gs = round(us_a["recent_xg"] * 1.10, 3)
                    as_.away_gs = round(us_a["recent_xg"] * 0.90, 3)
                if us_a.get("recent_xga", 0) > 0.2:
                    as_.home_gc = round(us_a["recent_xga"] * 0.95, 3)
                    as_.away_gc = round(us_a["recent_xga"] * 1.10, 3)
                if us_a.get("xg_trend", 0) > 0.1:
                    as_.attack_trend = round(min(max(us_a["xg_trend"], 0.75), 1.35), 3)
                src_a = "📐"
            else:
                ags, agc, a_found = _lookup_team(aname_en, False, league_id)
                if a_found:
                    as_ = TeamStats(aname, aid, ags, agc, 0.0)
                    src_a = "📊"
                else:
                    as_ = fetch_team_stats(aid, aname_en, league_id) if (_af_quota_ok and _budget_per_match >= 2) else None
                    if as_:
                        src_a = "📡"
                    else:
                        as_ = TeamStats(aname, aid, ags, agc, 0.0)
                        src_a = "ℹ️"

            # OPENLIGADB для статистики не используем (нет API для статистики)
            # Данные берутся из TEAM_DB + AF

            # ── ФОРМА: SofaScore > API-Football > FORM_DB ─────
            sofa_form_h, sofa_form_a = fetch_sofa_form(hname_en, aname_en, fdate)

            if sofa_form_h or sofa_form_a:
                # SofaScore нашёл — используем (не тратим AF квоту)
                real_form_h = sofa_form_h
                real_form_a = sofa_form_a
                if sofa_form_h: src_h += "🦅"
                if sofa_form_a: src_a += "🦅"
            elif _af_quota_ok and _budget_per_match >= 1:
                # AF форма при любом положительном бюджете
                real_form_h = fetch_team_form(hid, hname, league_id) if hid else None
                real_form_a = fetch_team_form(aid, aname, league_id) if aid else None
            else:
                real_form_h = None
                real_form_a = None

            # Если форма не найдена через API — берём из FORM_DB (статика сезона)
            if not real_form_h:
                real_form_h = _form_from_db(hname)
                if real_form_h:
                    src_h += "📋"
                elif hname.lower() in _LEARNED_STATS:
                    st = _LEARNED_STATS[hname.lower()]
                    m_ = st.get("matches", 0)
                    if m_ >= 3:
                        wr = st.get("wins", m_*0.45) / m_
                        _fr = round(0.7 + wr * 1.4, 3)
                        real_form_h = (min(1.4, _fr), 1.0, 1.0)
            if not real_form_a:
                real_form_a = _form_from_db(aname)
                if real_form_a:
                    src_a += "📋"
                elif aname.lower() in _LEARNED_STATS:
                    st = _LEARNED_STATS[aname.lower()]
                    m_ = st.get("matches", 0)
                    if m_ >= 3:
                        wr = st.get("wins", m_*0.45) / m_
                        _fr = round(0.7 + wr * 1.4, 3)
                        real_form_a = (min(1.4, _fr), 1.0, 1.0)

            # Если Understat есть — его тренд точнее формы из результатов
            if us_h and us_h.get("xg_trend"):
                tr = us_h["xg_trend"]
                if real_form_h:
                    # Смешиваем: 60% тренд Understat + 40% форма из матчей
                    fr, at, dt = real_form_h
                    at = round(at * 0.4 + tr * 0.6, 3)
                    real_form_h = (fr, at, dt)
                else:
                    real_form_h = (1.0, round(tr, 3), round(2.0-tr, 3))

            if us_a and us_a.get("xg_trend"):
                tr = us_a["xg_trend"]
                if real_form_a:
                    fr, at, dt = real_form_a
                    at = round(at * 0.4 + tr * 0.6, 3)
                    real_form_a = (fr, at, dt)
                else:
                    real_form_a = (1.0, round(tr, 3), round(2.0-tr, 3))

            hs  = _enrich_teamstats(hs,  hname, real_form_h)
            as_ = _enrich_teamstats(as_, aname, real_form_a)

            # ── ДИСКВАЛИФИКАЦИИ (угроза ж/к) ─────────────────
            if _af_quota_ok and _budget_per_match >= 7 and not _AF_ECONOMY_MODE:
                yc_h = fetch_yellow_card_risk(hid, hname, fid)
                yc_a = fetch_yellow_card_risk(aid, aname, fid)
                if yc_h["note"]: print(f"      {yc_h['note']}")
                if yc_a["note"]: print(f"      {yc_a['note']}")
                if yc_h["xg_penalty"] < 1.0:
                    hs.avg_goals_scored = round(hs.avg_goals_scored * yc_h["xg_penalty"], 3)
                if yc_a["xg_penalty"] < 1.0:
                    as_.avg_goals_scored = round(as_.avg_goals_scored * yc_a["xg_penalty"], 3)
            else:
                yc_h = yc_a = {"note":"","xg_penalty":1.0,"risk_players":[]}

            # ── ТРАВМЫ: SofaScore > API-Football ──────────────
            sofa_inj_h, sofa_inj_a = fetch_sofa_injuries(hname_en, aname_en, fdate)
            if sofa_inj_h < 1.0 or sofa_inj_a < 1.0:
                inj_h, inj_a = sofa_inj_h, sofa_inj_a
            else:
                # SofaScore не нашёл → API-Football только при хорошем бюджете
                if _budget_per_match >= 8 and not _AF_ECONOMY_MODE:
                    inj_h = fetch_injuries(fid, hid) if hid else 1.0
                    inj_a = fetch_injuries(fid, aid) if aid else 1.0
                else:
                    inj_h = inj_a = 1.0

            if inj_h < 1.0:
                hs.avg_goals_scored = round(hs.avg_goals_scored * inj_h, 3)
                print(f"      🏥 {_ru(hname)}: травмы/диск. → xG -{(1-inj_h)*100:.0f}%")
            if inj_a < 1.0:
                as_.avg_goals_scored = round(as_.avg_goals_scored * inj_a, 3)
                print(f"      🏥 {_ru(aname)}: травмы/диск. → xG -{(1-inj_a)*100:.0f}%")

            # ── ДОМАШНЯЯ / ВЫЕЗДНАЯ ФОРМА ─────────────────────
            # Только если бюджет >= 5 req/матч (есть запас)
            if _af_quota_ok and _budget_per_match >= 3:   # УЛУЧШ: порог 5→3
                # Venue form пропускаем только в жёстком экономном режиме
                if not _AF_ECONOMY_MODE:
                    vf_h = fetch_venue_form(hid, hname, league_id, is_home=True)
                    vf_a = fetch_venue_form(aid, aname, league_id, is_home=False)
                else:
                    vf_h = {"venue_form": 1.0, "venue_gs": 0.0, "venue_gc": 0.0}
                    vf_a = {"venue_form": 1.0, "venue_gs": 0.0, "venue_gc": 0.0}
            else:
                vf_h = {"venue_form": 1.0, "venue_gs": 0.0, "venue_gc": 0.0}
                vf_a = {"venue_form": 1.0, "venue_gs": 0.0, "venue_gc": 0.0}
            if vf_h["venue_form"] != 1.0:
                hs.home_form = vf_h["venue_form"]
                if vf_h["venue_gs"] > 0: hs.home_gs = vf_h["venue_gs"]
                if vf_h["venue_gc"] > 0: hs.home_gc = vf_h["venue_gc"]
            if vf_a["venue_form"] != 1.0:
                as_.away_form = vf_a["venue_form"]
                if vf_a["venue_gs"] > 0: as_.away_gs = vf_a["venue_gs"]
                if vf_a["venue_gc"] > 0: as_.away_gc = vf_a["venue_gc"]

            # ── H2H ───────────────────────────────────────────
            # Пропускаем если квоты мало (экономия)
            # H2H только если бюджет >= 4 req/матч
            h2h = fetch_h2h(hid, aid, hname, aname) if (_af_quota_ok and _budget_per_match >= 3) else None
            if h2h and h2h.get("matches", 0) > 0:
                print(f"      ⚔️  H2H: {h2h['matches']} встреч | тотал {h2h['h2h_avg_total']:.1f} | фактор {h2h['h2h_factor']:.2f}")
                if h2h.get("note"):
                    print(f"         {h2h['note']}")
            else:
                h2h = None

            # ── ПЕРВАЯ НОГА ПЛЕЙ-ОФФ ──────────────────────────
            first_leg = None
            if league_id in (2, 3, 848) and _af_quota_ok and _budget_per_match >= 2:
                first_leg = fetch_first_leg(hid, aid, league_id, fdate)
                if first_leg and first_leg.get("is_second_leg"):
                    _fl = first_leg
                    print(f"      🥇 1-я нога: {_fl['leg1_str']} | Агрегат: {_fl['agg_home']}:{_fl['agg_away']}")
                    print(f"         Давление → H:{_fl['pressure_h']:.2f}  A:{_fl['pressure_a']:.2f}  ({_fl['context']})")

            # ── ВЫВОД ─────────────────────────────────────────
            stars_h = "⭐"*round(hs.home_form*2) if hs.home_form >= 1.0 else "▽"*round((1.4-hs.home_form)*3)
            stars_a = "⭐"*round(as_.away_form*2) if as_.away_form >= 1.0 else "▽"*round((1.4-as_.away_form)*3)
            elo_h_str = get_elo_str(hname)
            elo_a_str = get_elo_str(aname)
            us_xg_h = f"xG_us={us_h['recent_xg']:.2f}" if us_h else ""
            us_xg_a = f"xG_us={us_a['recent_xg']:.2f}" if us_a else ""
            h_home_str = f"(дом:{hs.home_gs:.2f}/{hs.home_gc:.2f})" if hs.home_gs > 0 else ""
            a_away_str = f"(выезд:{as_.away_gs:.2f}/{as_.away_gc:.2f})" if as_.away_gs > 0 else ""
            print(f"      {src_h} {_ru(hname)}: gs={hs.avg_goals_scored:.2f} gc={hs.avg_goals_conceded:.2f} {h_home_str} форма:{hs.home_form:.2f} {elo_h_str} {us_xg_h} {stars_h}")
            print(f"      {src_a} {_ru(aname)}: gs={as_.avg_goals_scored:.2f} gc={as_.avg_goals_conceded:.2f} {a_away_str} форма:{as_.away_form:.2f} {elo_a_str} {us_xg_a} {stars_a}")

            # ══════════════════════════════════════════════════════
            # КОЭФФИЦИЕНТЫ — АВТОМАТИЧЕСКАЯ ЦЕПОЧКА (6 источников)
            # Каждый следующий включается если предыдущий недоступен
            # ══════════════════════════════════════════════════════

            bk_odds = {}
            _odds_source_used = "—"

            # 0) Ручные коэфы (если введены через 'manual') — приоритет
            _manual = match_manual_odds(hname_en, aname_en)
            if _manual and _manual.get("1"):
                bk_odds = _manual
                _odds_source_used = "✋ Ручной ввод"
                _real_keys = [k for k in bk_odds if not k.startswith("_")]
                print(f"      ✋ Ручные коэфы: {len(_real_keys)} рынков  "
                      f"1={bk_odds.get('1','—')}  X={bk_odds.get('X','—')}  2={bk_odds.get('2','—')}")

            # 1) Pinnacle Guest API — без регистрации, острая линия
            if not bk_odds:
                pg = fetch_pinnacle_guest_odds(hname_en, aname_en, fdate)
                if pg and pg.get("1"):
                    bk_odds = pg
                    _odds_source_used = "📌 Pinnacle Guest"
                    _real_keys = [k for k in bk_odds if not k.startswith("_")]
                    print(f"      📌 Pinnacle Guest: {len(_real_keys)} рынков  "
                          f"1={bk_odds.get('1','—')}  X={bk_odds.get('X','—')}  2={bk_odds.get('2','—')}")

            # 2) Fonbet — реальные RU коэфы (только из RU IP)
            if not bk_odds:
                fb_line = fetch_fonbet_odds(hname_en, aname_en, fdate, league_name)
                if fb_line:
                    bk_odds = fb_line
                    _odds_source_used = "🎰 Fonbet"
                    _real_keys = [k for k in bk_odds if not k.startswith("_")]
                    fb_home = bk_odds.get("_fonbet_home", hname_en)
                    fb_away = bk_odds.get("_fonbet_away", aname_en)
                    print(f"      🎰 Fonbet: {len(_real_keys)} рынков  ({fb_home} vs {fb_away})")
                    print(f"         1={bk_odds.get('1','—')}  X={bk_odds.get('X','—')}  "
                          f"2={bk_odds.get('2','—')}  Т>2.5={bk_odds.get('over_2.5','—')}")

            # 3) The Odds API — международные букмекеры
            if not bk_odds:
                _odds_api_r = fetch_odds_api(league_id, hname_en, aname_en)
                if _odds_api_r and _odds_api_r.get("1"):
                    bk_odds = _odds_api_r
                    _odds_source_used = "💹 Odds API"
                    _real_keys = [k for k in bk_odds if not k.startswith("_")]
                    print(f"      💹 Odds API: {len(_real_keys)} рынков  "
                          f"1={bk_odds.get('1','—')}  X={bk_odds.get('X','—')}  2={bk_odds.get('2','—')}")

            # 4) SofaScore — Pinnacle/bet365 коэфы бесплатно
            if not bk_odds:
                sf = fetch_sofascore_odds(hname_en, aname_en, fdate)
                if sf and sf.get("1"):
                    bk_odds = sf
                    _odds_source_used = "📊 SofaScore"
                    _real_keys = [k for k in bk_odds if not k.startswith("_")]
                    print(f"      📊 SofaScore: {len(_real_keys)} рынков  "
                          f"1={bk_odds.get('1','—')}  X={bk_odds.get('X','—')}  2={bk_odds.get('2','—')}")

            # 5) Pari.ru — резервный RU источник
            pari_ev = _match_pari(hname_en, aname_en, fdate)
            if pari_ev:
                if pari_ev.get("time"):
                    old_time = ftime
                    ftime    = pari_ev["time"]
                    if old_time and old_time != ftime:
                        print(f"      🎰 Pari: время {old_time} → {ftime} (МСК)")
                if not bk_odds and pari_ev.get("odds"):
                    bk_odds = pari_ev["odds"]
                    _odds_source_used = "🎰 Pari"
                    print(f"      🎰 Pari: коэф подгружены")

            # 6) Расчётные коэфы — всегда работают (последний резерв)
            if not bk_odds:
                print(f"      ⚙️  Используем расчётные коэфы [все 6 источников недоступны]")
            # Всегда дополняем коэфы расчётными для недостающих рынков
            # Это не заменяет реальные — только добавляет отсутствующие
            # (например: есть 1x2/totals от Pinnacle, но нет угловых → добавим расчётные)
            _real_before = len([k for k in bk_odds if not k.startswith("_")])

            # (print перенесён ПОСЛЕ calc_odds — см. ниже)

            # Сохраняем открывающий коэф (только при первом сканировании)
            if bk_odds:
                save_opening_odds(fid, f"{hname_en} vs {aname_en}", bk_odds)

            # Движение линии
            movements = get_line_movement(fid, bk_odds) if bk_odds else {}
            if movements:
                for mkey, mdiff in movements.items():
                    arrow = "📉" if mdiff < 0 else "📈"
                    print(f"      {arrow} Линия [{mkey}]: {mdiff:+.2f}")

            # ── BETFAIR EXCHANGE ───────────────────────────────
            bf_odds = fetch_betfair_odds(hname_en, aname_en, fdate)

            # ── НОВОСТИ О КОМАНДАХ ─────────────────────────────
            news_h = fetch_team_news(hname, fdate)
            news_a = fetch_team_news(aname, fdate)
            if news_h.get("note"): print(f"      📰 {_ru(hname)}: {news_h['note']}")
            if news_a.get("note"): print(f"      📰 {_ru(aname)}: {news_a['note']}")

            # ── СТОИМОСТЬ СОСТАВОВ (TransferMarkt) ────────────
            tm_h = fetch_squad_value(hname, league_id)
            tm_a = fetch_squad_value(aname, league_id)
            sv_f = squad_value_factor(tm_h, tm_a)
            # Применяем только если оба значения >= €10m (не мусор от TM API)
            # TransferMarkt иногда возвращает 0.1-0.5 для неизвестных клубов
            if tm_h and tm_a and tm_h >= 10 and tm_a >= 10 and abs(sv_f - 1.0) > 0.01:
                ratio = tm_h / max(tm_a, 1)
                print(f"      💰 TM: {_ru(hname)} €{tm_h:.0f}m vs {_ru(aname)} €{tm_a:.0f}m "
                      f"(ratio {ratio:.1f}x → xG {(sv_f-1):+.0%})")
                hs.avg_goals_scored    = round(hs.avg_goals_scored    * sv_f, 3)
                as_.avg_goals_conceded = round(as_.avg_goals_conceded / max(sv_f, 0.88), 3)
            else:
                if not tm_h or not tm_a:
                    pass  # TM не нашёл — молча пропускаем, не штрафуем
                sv_f = 1.0

            # Контекст матча (турнирная ситуация)
            ctx = get_match_context(fid, hid, aid, league_id)
            if ctx["note"]:
                print(f"      🏆 {ctx['note']}")
            hs.avg_goals_scored  = round(hs.avg_goals_scored  * ctx["home_motivation"], 3)
            as_.avg_goals_scored = round(as_.avg_goals_scored * ctx["away_motivation"], 3)

            # ── СУДЬЯ ─────────────────────────────────────────
            # Судья только при очень высоком бюджете (дорогой запрос)
            ref = (fetch_referee_stats(fid)
                   if (_af_quota_ok and _budget_per_match >= 4 and not _AF_ECONOMY_MODE)  # УЛУЧШ: 6→4
                   else {"note":"","total_factor":1.0})
            if ref["note"]:
                print(f"      {ref['note']}")

            # ── ПОГОДА ────────────────────────────────────────
            match_hour = int(ftime[:2]) if ftime and len(ftime) >= 2 else 17
            wx = fetch_weather(league_id, fdate, match_hour)
            if wx["note"]:
                print(f"      {wx['note']}")

            # ── ДНИ ОТДЫХА ────────────────────────────────────
            rest_h = fetch_rest_days(hid, fdate) if hid else 99
            rest_a = fetch_rest_days(aid, fdate) if aid else 99
            rf_h   = rest_factor(rest_h)
            rf_a   = rest_factor(rest_a)
            if rf_h < 1.0:
                hs.avg_goals_scored = round(hs.avg_goals_scored * rf_h, 3)
                print(f"      😴 {_ru(hname)}: {rest_h} дн. отдыха → xG -{(1-rf_h)*100:.0f}%")
            if rf_a < 1.0:
                as_.avg_goals_scored = round(as_.avg_goals_scored * rf_a, 3)
                print(f"      😴 {_ru(aname)}: {rest_a} дн. отдыха → xG -{(1-rf_a)*100:.0f}%")

            # ── Расчётные коэффициенты для ВСЕХ рынков ───────────────
            # Используем ЛИГОВЫЕ СРЕДНИЕ как базу (не нашу модель!).
            # Это даёт реальный value когда наш matч сильно отклоняется от среднего.
            # Маржа 8% (как Odds API) → no_vig честный.
            if not bk_odds or ("1" not in bk_odds and "over_2.5" not in bk_odds):
                import math as _math
                def _pp(lam, k):
                    return _math.exp(-lam) * lam**k / _math.factorial(k)

                # ── Командные лямбды (РАЗНЫЕ для каждого матча!) ──
                # Используем реальную статистику команд из TEAM_DB
                # Еврокубки: home_adv 4% (не 7%) — нет фактора родного чемпионата
                _euro_lgs = {2, 3, 848, 45, 48, 137, 9, 81, 65, 276, 210, 560}
                _home_mult = 1.04 if league_id in _euro_lgs else 1.07
                _lh = (hs.home_gs or hs.avg_goals_scored) * _home_mult
                _la = (as_.away_gs or as_.avg_goals_scored)
                _lh = max(0.5, min(_lh, 2.5))   # FIX: реалистичный cap (было 3.5)
                _la = max(0.5, min(_la, 2.2))   # FIX: реалистичный cap (было 3.0)

                # Матрица Пуассона по КОМАНДНОЙ статистике
                _CALC_MARGIN = 1.07
                _R = 8
                _mat_avg = [[_pp(_lh, i)*_pp(_la, j) for j in range(_R)] for i in range(_R)]
                _ph_avg = sum(_mat_avg[i][j] for i in range(_R) for j in range(_R) if i > j)
                _pd_avg = sum(_mat_avg[i][i] for i in range(_R))
                _pa_avg = sum(_mat_avg[i][j] for i in range(_R) for j in range(_R) if i < j)

                # Синонимы для совместимости с остальным кодом
                _avg_lh, _avg_la = _lh, _la

                def _o(p, margin=_CALC_MARGIN):
                    p = max(0.02, min(p, 0.98))
                    return round(1.0 / p / margin, 2)

                # ── 1X2 по лиговым средним ──────────────────────
                if "1" not in bk_odds:
                    bk_odds["1"] = _o(_ph_avg); bk_odds["X"] = _o(_pd_avg); bk_odds["2"] = _o(_pa_avg)
                    bk_odds["_calc_1x2"] = True   # флаг что расчётные

                # ── Тоталы по лиговым средним ───────────────────
                for _ln in [1.5, 2.5, 3.5]:
                    ok = f"over_{_ln}"; uk = f"under_{_ln}"
                    if ok not in bk_odds:
                        _p_ov = sum(_mat_avg[i][j] for i in range(_R) for j in range(_R) if i+j > _ln)
                        _p_ov = max(0.02, min(_p_ov, 0.98))
                        bk_odds[ok] = _o(_p_ov); bk_odds[uk] = _o(1-_p_ov)

                # ── Европейская Фора ±1, ±2 по модели ───────────
                for _hcp in EH_LINES:
                    _s = f"+{_hcp}" if _hcp > 0 else str(_hcp)
                    if f"eh_home_{_s}" not in bk_odds:
                        # adj = (i + hcap) - j  → та же формула что в prob_eh()
                        _ph_h = sum(_mat_avg[i][j] for i in range(_R) for j in range(_R) if (i+_hcp)-j > 0)
                        _pd_h = sum(_mat_avg[i][j] for i in range(_R) for j in range(_R) if (i+_hcp)-j == 0)
                        _pa_h = sum(_mat_avg[i][j] for i in range(_R) for j in range(_R) if (i+_hcp)-j < 0)
                        if _ph_h > 0.01:
                            bk_odds[f"eh_home_{_s}"] = _o(_ph_h)
                        if _pd_h > 0.01:
                            bk_odds[f"eh_draw_{_s}"] = _o(_pd_h)
                        if _pa_h > 0.01:
                            bk_odds[f"eh_away_{_s}"] = _o(_pa_h)

                # ── Азиатский гандикап (расчётный) ──────────────
                for _ah_hcap in [-0.5, -1.0, -1.5, 0.5, 1.0, 1.5]:
                    _k_h = f"ah_home_{_ah_hcap}"
                    _k_a = f"ah_away_{abs(_ah_hcap)}"
                    if _k_h not in bk_odds and _k_a not in bk_odds:
                        try:
                            _ph_ah, _pa_ah = _ph_avg, _pa_avg   # заглушка через prob_asian недоступна здесь
                            # Используем prob_asian из матрицы лиговых средних
                            _ph_ah = sum(
                                _mat_avg[ii][jj] for ii in range(_R) for jj in range(_R)
                                if (ii + _ah_hcap) - jj > 0
                            )
                            _pa_ah = sum(
                                _mat_avg[ii][jj] for ii in range(_R) for jj in range(_R)
                                if (ii + _ah_hcap) - jj < 0
                            )
                            _tot_ah = _ph_ah + _pa_ah
                            if _tot_ah > 0.01:
                                _ph_ah /= _tot_ah
                                _pa_ah /= _tot_ah
                                bk_odds[_k_h] = _o(_ph_ah)
                                bk_odds[_k_a] = _o(_pa_ah)
                        except Exception:
                            pass

                # ── DNB ─────────────────────────────────────────
                if "dnb_home" not in bk_odds:
                    _sum_nd = _ph_avg + _pa_avg
                    if _sum_nd > 0.01:
                        bk_odds["dnb_home"] = _o(_ph_avg / _sum_nd)
                        bk_odds["dnb_away"] = _o(_pa_avg / _sum_nd)

                # ── Двойной шанс ─────────────────────────────────
                if "dc_1x" not in bk_odds:
                    bk_odds["dc_1x"] = _o(_ph_avg + _pd_avg)
                    bk_odds["dc_12"] = _o(_ph_avg + _pa_avg)
                    bk_odds["dc_x2"] = _o(_pd_avg + _pa_avg)

                # ── ИТ хозяев / гостей (по нашей модели - нет лигового среднего) ─
                for _ln2 in [0.5, 1.5, 2.5]:
                    ok_h = f"it_h_over_{_ln2}"
                    if ok_h not in bk_odds:
                        _po_h = 1 - sum(_pp(_avg_lh, k) for k in range(int(_ln2)+1))
                        _po_a = 1 - sum(_pp(_avg_la, k) for k in range(int(_ln2)+1))
                        if _po_h > 0.03:
                            bk_odds[ok_h]                 = _o(_po_h)
                            bk_odds[f"it_h_under_{_ln2}"] = _o(1-_po_h)
                        if _po_a > 0.03:
                            bk_odds[f"it_a_over_{_ln2}"]  = _o(_po_a)
                            bk_odds[f"it_a_under_{_ln2}"] = _o(1-_po_a)

                # ── Тоталы 1-го тайма ────────────────────────────
                _lh1 = _avg_lh * 0.45; _la1 = _avg_la * 0.45
                _mat1h = [[_pp(_lh1, i)*_pp(_la1, j) for j in range(_R)] for i in range(_R)]
                for _ln1 in [0.5, 1.5]:
                    ok1 = f"1h_over_{_ln1}"
                    if ok1 not in bk_odds:
                        _p1 = sum(_mat1h[i][j] for i in range(_R) for j in range(_R) if i+j > _ln1)
                        bk_odds[ok1]                = _o(max(0.02, _p1))
                        bk_odds[f"1h_under_{_ln1}"] = _o(max(0.02, 1-_p1))

                # ── Исход 1-го тайма ─────────────────────────────
                if "1h_home" not in bk_odds:
                    _ph1 = sum(_mat1h[i][j] for i in range(_R) for j in range(_R) if i > j)
                    _pd1 = sum(_mat1h[i][i] for i in range(_R))
                    _pa1 = sum(_mat1h[i][j] for i in range(_R) for j in range(_R) if i < j)
                    bk_odds["1h_home"] = _o(max(0.02, _ph1))
                    bk_odds["1h_draw"] = _o(max(0.02, _pd1))
                    bk_odds["1h_away"] = _o(max(0.02, _pa1))

                # ── BTTS (Обе забьют) ─────────────────────────────
                if "btts_yes" not in bk_odds:
                    _p_btts = sum(
                        _mat_avg[i][j] for i in range(_R) for j in range(_R)
                        if i > 0 and j > 0
                    )
                    _p_btts = max(0.05, min(_p_btts, 0.95))
                    bk_odds["btts_yes"] = _o(_p_btts)
                    bk_odds["btts_no"]  = _o(1 - _p_btts)

                # ── УГЛОВЫЕ (расчётные через lh/la) ──────────────
                if "corners_over_9.5" not in bk_odds:
                    try:
                        import math as _math
                        _CORNERS_TOTAL = {
                            39:10.5, 140:9.8, 135:9.2, 78:11.0,
                            61:9.5, 2:10.2, 3:9.8, 848:9.4,
                            40:10.2, 144:10.4, 235:8.8, 203:9.8,
                        }
                        _ct = _CORNERS_TOTAL.get(league_id, 10.0)
                        _avg_xg_lg = 1.55
                        _atk_h_c = (_avg_lh / _avg_xg_lg) if _avg_lh > 0 else 1.0
                        _atk_a_c = (_avg_la / _avg_xg_lg) if _avg_la > 0 else 1.0
                        _lam_ch = (_ct * 0.52) * max(0.5, min(_atk_h_c, 2.5)) ** 0.60
                        _lam_ca = (_ct * 0.48) * max(0.5, min(_atk_a_c, 2.5)) ** 0.60
                        _lam_ct = _lam_ch + _lam_ca
                        for _cln in [8.5, 9.5, 10.5, 11.5]:
                            _k_co = f"corners_over_{_cln}"
                            _k_cu = f"corners_under_{_cln}"
                            if _k_co not in bk_odds:
                                _kmax = int(_cln + 0.5)
                                _p_cu = sum(
                                    _math.exp(-_lam_ct) * _lam_ct**_kk / _math.factorial(_kk)
                                    for _kk in range(_kmax + 1)
                                )
                                _p_co = max(0.02, 1 - _p_cu)
                                _p_cu = max(0.02, min(_p_cu, 0.98))
                                bk_odds[_k_co] = _o(_p_co)
                                bk_odds[_k_cu] = _o(_p_cu)
                        # Индивидуальные угловые
                        for _cln_i in [4.5, 5.5]:
                            for _lam_ci, _side in [(_lam_ch, "h"), (_lam_ca, "a")]:
                                _ki = f"corners_{_side}_over_{_cln_i}"
                                if _ki not in bk_odds:
                                    _kmax_i = int(_cln_i + 0.5)
                                    _pu_i = sum(
                                        _math.exp(-_lam_ci)*_lam_ci**_kk/_math.factorial(_kk)
                                        for _kk in range(_kmax_i+1)
                                    )
                                    bk_odds[_ki] = _o(max(0.02, 1 - _pu_i))
                    except Exception:
                        pass

                # ── ЖЁЛТЫЕ КАРТОЧКИ (только в лигах с высоким avg) ─
                if "yc_over_3.5" not in bk_odds:
                    _YC_AVG = {
                        140: (4.8, 3.5, 2.4, 2.4),  # Ла Лига: avg, line, home, away
                        135: (4.2, 3.5, 2.1, 2.1),  # Серия А
                        203: (5.2, 4.5, 2.6, 2.6),  # Турция
                        40:  (4.5, 3.5, 2.3, 2.2),  # Чемпионшип
                        61:  (4.0, 3.5, 2.0, 2.0),  # Лига 1
                        39:  (3.8, 3.5, 1.9, 1.9),  # АПЛ
                        78:  (3.5, 3.5, 1.8, 1.7),  # Бундеслига
                    }
                    if league_id in _YC_AVG:
                        try:
                            import math as _math
                            _yc_avg, _yc_line, _yc_h, _yc_a = _YC_AVG[league_id]
                            # Суммарные ЖК
                            _kmax_yc = int(_yc_line + 0.5)
                            _p_yc_u = sum(
                                _math.exp(-_yc_avg)*_yc_avg**_kk/_math.factorial(_kk)
                                for _kk in range(_kmax_yc+1)
                            )
                            _p_yc_o = max(0.02, 1 - _p_yc_u)
                            bk_odds[f"yc_over_{_yc_line}"]  = _o(_p_yc_o)
                            bk_odds[f"yc_under_{_yc_line}"] = _o(max(0.02, _p_yc_u))
                            # Индивидуальные ЖК команд
                            for _yc_tm, _yc_lam_t in [("h", _yc_h), ("a", _yc_a)]:
                                _kmax_t = int(1.5 + 0.5)
                                _pu_t = sum(
                                    _math.exp(-_yc_lam_t)*_yc_lam_t**_kk/_math.factorial(_kk)
                                    for _kk in range(_kmax_t+1)
                                )
                                bk_odds[f"yc_{_yc_tm}_over_1.5"] = _o(max(0.02, 1-_pu_t))
                        except Exception:
                            pass

            # Жёсткий cap: не более 3.5 гол/игра (среднее топ-команды)
            # Все внешние факторы (TM, мотивация, форма) могут накапливаться
            # и давать нереальные 5-6 xG — ограничиваем вход в модель
            _MAX_GS = 3.0   # не более 3.0 голов в атаке (топ-команда дома)
            _MAX_GC = 2.0   # не более 2.0 пропускает (слабейший аутсайдер)
            hs.avg_goals_scored    = min(hs.avg_goals_scored,    _MAX_GS)
            as_.avg_goals_scored   = min(as_.avg_goals_scored,   _MAX_GS)
            hs.avg_goals_conceded  = min(max(hs.avg_goals_conceded,  0.45), _MAX_GC)
            as_.avg_goals_conceded = min(max(as_.avg_goals_conceded, 0.45), _MAX_GC)
            hs.home_gs  = min(hs.home_gs,  _MAX_GS) if hs.home_gs  > 0 else hs.home_gs
            as_.away_gs = min(as_.away_gs, _MAX_GS) if as_.away_gs > 0 else as_.away_gs
            hs.home_gc  = min(hs.home_gc,  _MAX_GC) if hs.home_gc  > 0 else hs.home_gc
            as_.away_gc = min(as_.away_gc, _MAX_GC) if as_.away_gc > 0 else as_.away_gc

            # Качество данных: от источника зависит вес модели в emit()
            _dq = 0.50  # по умолчанию — AF stats
            if "📐" in (src_h + src_a):  _dq = 0.62  # есть Understat xG
            elif "📊" in (src_h + src_a): _dq = 0.50  # обученные данные
            elif "📡" in (src_h + src_a): _dq = 0.50  # AF API
            else:                          _dq = 0.38  # только TEAM_DB static

            # ── ИТОГОВЫЙ ЛОГ РЫНКОВ (после calc_odds) ─────────
            n_markets = len([k for k in bk_odds if not k.startswith("_")])
            eh_keys   = [k for k in bk_odds if k.startswith("eh_")]
            ah_keys   = [k for k in bk_odds if k.startswith("ah_")]
            has_btts  = "btts_yes" in bk_odds
            has_dnb   = "dnb_home" in bk_odds
            has_dc    = "dc_1x" in bk_odds
            has_1h    = any(k.startswith("1h_") for k in bk_odds)
            has_crn   = any(k.startswith("corners_") for k in bk_odds)
            has_yc    = any(k.startswith("yc_") for k in bk_odds)
            extras = []
            if has_btts:  extras.append("BTTS")
            if has_dnb:   extras.append("Фора0")
            if has_dc:    extras.append("DC")
            if has_1h:    extras.append("1Т")
            if has_crn:   extras.append("Углы")
            if has_yc:    extras.append("ЖК")
            if eh_keys:   extras.append(f"EH:{len(eh_keys)//3}")
            if ah_keys:   extras.append(f"AH:{len(ah_keys)//2}")
            ext_str    = " | " + " ".join(extras) if extras else ""
            _calc_flag = " [⚙️расчётные]" if bk_odds.get("_calc_1x2") else " [реальные]"
            _src_flag  = f" ← {_odds_source_used}" if n_markets > 0 and not bk_odds.get("_calc_1x2") else ""
            print(f"      Коэф.: {n_markets} рынков{ext_str}{_calc_flag}{_src_flag}")

            match = Match(
                fixture_id=fid, home=hs, away=as_,
                league=_norm_league_name(fix.get("_league_name", league_name)),
                date=fdate, time=ftime,
                bookmaker_odds=bk_odds,
                data_quality=_dq,
            )
            # Погода влияет на тотал — передаём в analyze
            wx_factor = wx.get("total_factor", 1.0) * ref.get("total_factor", 1.0)

            lh, la, sigs = engine.analyze(match, h2h=h2h, wx_factor=wx_factor,
                                              league_id=league_id,
                                              first_leg=first_leg)
            print(f"      xG → H:{lh:.2f}  A:{la:.2f}  Tot:{lh+la:.2f}")

            # Сохраняем прогноз для самообучения
            if _LEARNING:
                _save_pred(
                    fixture_id=fid, home=_ru(hname), away=_ru(aname),
                    league=fix.get("_league_name", league_name),
                    date=fdate, match_time=ftime,
                    xg_home=lh, xg_away=la,
                    signals=[{
                        "market":          s.market,
                        "selection":       s.selection,
                        "model_prob":      s.model_prob,
                        "bookmaker_odds":  s.bookmaker_odds,
                        "edge":            s.edge,
                    "confidence":  s.confidence,
                    "kelly_stake": round(s.kelly_stake, 2),
                    "score":       round(s.score, 3),
                    } for s in sigs]
                )

            # ── ФИЛЬТР ДВИЖЕНИЯ ЛИНИИ (умные деньги) ─────────
            sigs = filter_line_movement(sigs, movements)

            # ── BETFAIR + PINNACLE КОНСЕНСУС ФИЛЬТР ───────────
            sigs = betfair_consensus_filter(sigs, bf_odds, bk_odds)

            # ── ФИЛЬТР КОРРЕЛЯЦИЙ ─────────────────────────────
            sigs = filter_correlated(sigs)
            sigs = filter_diverse(sigs, max_per_type=0.45)  # НОВОЕ: разнообразие рынков

            # ── КОМПЛЕКСНЫЙ СКОРИНГ СИГНАЛОВ ──────────────────
            for s in sigs:
                s.score = score_signal(
                    s, h2h=h2h, wx=wx, bf_odds=bf_odds,
                    rest_h=rest_h, rest_a=rest_a,
                    sv_factor=sv_f,
                    news_h=news_h, news_a=news_a,
                )
            # Убираем сигналы с очень низким комплексным скором
            sigs = [s for s in sigs if s.score >= 1]   # FIX: порог снижен (был 5)
            if sigs:
                sigs.sort(key=lambda s: s.score, reverse=True)

            # Пересчитываем бюджет после каждого матча
            _matches_processed = n_fix + 1
            _remaining_matches = max(1, _total_matches - _matches_processed)
            _budget_per_match  = max(1, int(_af_quota_rem / _remaining_matches))

            if sigs:
                for s in sigs: _print_sig(s)
                save_csv(sigs)
                tg_match(sigs, lh, la, movements=movements, fixture_id=fid,
                         h2h=h2h, wx=wx, rest_h=rest_h, rest_a=rest_a, ref=ref,
                         news_h=news_h, news_a=news_a,
                         yc_h=yc_h, yc_a=yc_a,
                         first_leg=first_leg)
                all_sig.extend(sigs)
            else:
                # ── ИНФОРМАЦИОННЫЙ СИГНАЛ (нет value-ставок) ─────
                # На каждый матч ВСЕГДА есть минимум 1 сигнал
                best_info = _best_info_signal(lh, la, match, league_id, bk_odds)
                if best_info:
                    _print_sig(best_info)
                    save_csv([best_info])
                    tg_match([best_info], lh, la, fixture_id=fid)
                else:
                    # Крайний случай: генерируем без котировок
                    ph, _, pa = fb_engine.prob_1x2(fb_engine.matrix(lh, la, league_id))
                    best_sel = "Победа хозяев" if ph >= pa else "Победа гостей"
                    best_prob = max(ph, pa)
                    info_sig = Signal(
                        match=f"{_ru(hname)} vs {_ru(aname)}", league=league_name,
                        date=fdate, time=ftime, market="📊 xG прогноз",
                        selection=f"{best_sel}  |  xG {lh:.1f}:{la:.1f}",
                        model_prob=round(best_prob,4), bookmaker_odds=0.0,
                        implied_prob=round(best_prob,4), edge=0.0, kelly_stake=0.0,
                        confidence="📊 ИНФО",
                    )
                    _print_sig(info_sig)
                    save_csv([info_sig])

    # ── Итог и ТОП-5 лучших сигналов ────────────────────────
    hi = sum(1 for s in all_sig if "ВЫСОКАЯ" in s.confidence)
    me = sum(1 for s in all_sig if "СРЕДНЯЯ" in s.confidence)
    lo = sum(1 for s in all_sig if "НИЗКАЯ"  in s.confidence)
    print(f"\n{'═'*62}")
    print(f"  📋 ГОТОВО | Матчей: {n_fix} | Сигналов: {len(all_sig)}")
    print(f"  🔥 {hi} высоких  ✅ {me} средних  📌 {lo} низких")



    if all_sig:
        # Сортируем по проходимости: уверенность + преимущество
        def _score(s):
            # Комплексный скор если есть, иначе старый расчёт
            if s.score > 0:
                return s.score
            c_val = 3 if "ВЫСОКАЯ" in s.confidence else (2 if "СРЕДНЯЯ" in s.confidence else 1)
            return c_val * 100 + s.edge * 100 + (s.model_prob - 0.5) * 50
        ranked = sorted(all_sig, key=_score, reverse=True)
        print(f"\n  🏆 ТОП-5 СИГНАЛОВ ПО ПРОХОДИМОСТИ:")
        print(f"  {'─'*58}")
        for i, s in enumerate(ranked[:5], 1):
            win_pct = _win_chance(s.model_prob, s.edge, s.confidence)
            ev      = round(s.model_prob * s.bookmaker_odds - 1.0, 3)
            print(f"  #{i}  {s.confidence}")
            print(f"       {s.match}  |  {_fmt_date(s.date)} {s.time}")
            print(f"       [{s.market}]  {s.selection}")
            print(f"       Коэф: {s.bookmaker_odds}  |  Шанс: {win_pct}%  |  Валуй: {s.edge:+.1%}  |  EV: {ev:+.3f}")
            print()
        tg_top(ranked[:5])

    print(f"{'═'*62}\n")
    tg_summary(all_sig, len(LEAGUES), n_fix)
    # Проверяем нажатые кнопки ✅/❌
    process_tg_callbacks()
    return all_sig

# ══════════════════════════════════════════════════════════════
#  🔄  ПЛАНИРОВЩИК
# ══════════════════════════════════════════════════════════════

# ══════════════════════════════════════════════════════════════════
#  📊 SOFASCORE ODDS — бесплатный источник (Pinnacle коэфы)
# ══════════════════════════════════════════════════════════════════
_sofa_event_cache: dict = {}

def _sofa_find_event(home: str, away: str, date_str: str) -> Optional[int]:
    """Ищет event_id на SofaScore по именам команд."""
    cache_key = f"{home.lower()}|{away.lower()}|{date_str}"
    if cache_key in _sofa_event_cache:
        return _sofa_event_cache[cache_key]
    data = _sofa(f"/sport/football/scheduled-events/{date_str}")
    if not data:
        return None
    _SOFA_ALIASES = {
        "man united":"manchester united","man utd":"manchester united",
        "man city":"manchester city","spurs":"tottenham",
        "wolves":"wolverhampton","wolverhampton wanderers":"wolverhampton",
        "afc bournemouth":"bournemouth","brighton & hove albion":"brighton",
        "newcastle united":"newcastle","west ham united":"west ham",
        "atletico madrid":"atletico","atletico de madrid":"atletico",
        "rb leipzig":"leipzig","borussia dortmund":"dortmund",
    }
    def _n(s):
        s2 = s.lower().replace("-"," ").replace("."," ")
        return _SOFA_ALIASES.get(s2, s2)
    hn, an = _n(home), _n(away)
    for ev in (data.get("events") or []):
        ht = _n(ev.get("homeTeam",{}).get("name",""))
        at = _n(ev.get("awayTeam",{}).get("name",""))
        def _match(a, b):
            parts = [p for p in a.split() if len(p)>=4]
            return any(p in b for p in parts)
        if (_match(hn,ht) and _match(an,at)) or (_match(hn,at) and _match(an,ht)):
            eid = ev.get("id")
            if eid:
                _sofa_event_cache[cache_key] = eid
                return eid
    return None


def fetch_sofascore_odds(home: str, away: str, date_str: str = "") -> dict:
    """
    Получает коэфы через SofaScore (Pinnacle/bet365).
    Бесплатно, без регистрации.
    """
    if not date_str:
        date_str = str(datetime.date.today())
    eid = _sofa_find_event(home, away, date_str)
    if not eid:
        return {}
    # Пробуем Pinnacle (1), затем bet365 (16), затем 1xbet (10)
    for bk_id in (1, 16, 10):
        data = _sofa(f"/event/{eid}/odds/{bk_id}")
        if data and data.get("markets"):
            break
    if not data or not data.get("markets"):
        return {}
    result = {}
    try:
        for market in data.get("markets", []):
            mname = market.get("marketName","").lower()
            for c in market.get("choices", []):
                nm  = c.get("name","")
                fr  = str(c.get("fractionalValue","") or "")
                pt  = str(c.get("handicap","") or "")
                if not fr or fr == "None": continue
                try:
                    dec = (lambda f: round(int(f[0])/int(f[1])+1,2) if "/" in f
                           else round(float(f),2))(fr.split("/") if "/" in fr else [fr])
                    if dec < 1.01 or dec > 50: continue
                    if "full time" in mname and "result" in mname:
                        if nm in ("1","X","2"): result[nm] = dec
                    elif "over" in mname and "under" in mname and pt:
                        if nm.lower()=="over":  result[f"over_{pt}"] = dec
                        elif nm.lower()=="under": result[f"under_{pt}"] = dec
                    elif "both teams" in mname or "btts" in mname:
                        if nm.lower() in ("yes","да"): result["btts_yes"] = dec
                        elif nm.lower() in ("no","нет"): result["btts_no"] = dec
                    elif "corner" in mname and pt:
                        if nm.lower()=="over":  result[f"corners_over_{pt}"] = dec
                        elif nm.lower()=="under": result[f"corners_under_{pt}"] = dec
                except Exception:
                    pass
        if result.get("1"):
            result["_source_sofascore"] = True
    except Exception:
        pass
    return result


# ══════════════════════════════════════════════════════════════════
#  ✋ РУЧНОЙ ВВОД КОЭФФИЦИЕНТОВ
# ══════════════════════════════════════════════════════════════════
_MANUAL_ODDS_FILE = "manual_odds.json"

def load_manual_odds() -> dict:
    """Загружает вручную введённые коэфы на сегодня."""
    if not os.path.exists(_MANUAL_ODDS_FILE):
        return {}
    try:
        with open(_MANUAL_ODDS_FILE, encoding="utf-8") as f:
            data = json.load(f)
        today = str(datetime.date.today())
        return {k: v for k, v in data.items() if v.get("date") == today}
    except Exception:
        return {}

def match_manual_odds(home: str, away: str) -> dict:
    """Ищет ручные коэфы по именам команд."""
    manual = load_manual_odds()
    if not manual:
        return {}
    def _n(s): return s.lower().strip()
    hn, an = _n(home), _n(away)
    for key, val in manual.items():
        kh = _n(val.get("home",""))
        ka = _n(val.get("away",""))
        if (hn in kh or kh in hn) and (an in ka or ka in an):
            return val.get("odds",{})
    return {}

def run_manual_odds_input():
    """Ручной ввод коэфов из букмекера. python football_bot_v3.py manual"""
    today = str(datetime.date.today())
    print()
    print("═"*62)
    print(f"  ✋ ВВОД КОЭФФИЦИЕНТОВ — {today}")
    print("  Источник: Фонбет / 1xBet / любой букмекер")
    print()
    print("  Формат: Команда1 vs Команда2 | 1 | X | 2")
    print("  Пример: Bournemouth vs Man Utd | 2.40 | 3.30 | 3.10")
    print("  После — бот спросит тотал, BTTS и угловые.")
    print("  Пустая строка = завершить.")
    print("═"*62)
    existing = {}
    if os.path.exists(_MANUAL_ODDS_FILE):
        try:
            with open(_MANUAL_ODDS_FILE, encoding="utf-8") as f:
                existing = json.load(f)
        except Exception:
            pass
    saved = 0
    while True:
        try:
            line = input(f"\nМатч {saved+1}: ").strip()
        except EOFError:
            break
        if not line:
            break
        try:
            parts = [p.strip() for p in line.split("|")]
            if len(parts) < 4:
                print("  ⚠️  Нужно: Команда1 vs Команда2 | 1 | X | 2")
                continue
            teams = parts[0].split(" vs ")
            if len(teams) != 2:
                print("  ⚠️  Нужно 'vs' между командами")
                continue
            home_t, away_t = teams[0].strip(), teams[1].strip()
            odds = {}
            try:
                if parts[1]: odds["1"] = float(parts[1])
                if parts[2]: odds["X"] = float(parts[2])
                if parts[3]: odds["2"] = float(parts[3])
            except ValueError:
                print("  ⚠️  Коэфы должны быть числами (например 2.40)")
                continue
            print(f"  ✅ {home_t} vs {away_t}: 1={odds.get('1','-')} X={odds.get('X','-')} 2={odds.get('2','-')}")
            # Тотал
            for line_v, label in [("2.5","Тотал >2.5"), ("1.5","Тотал >1.5"), ("3.5","Тотал >3.5")]:
                inp = input(f"    {label} (Enter=пропустить): ").strip()
                if inp:
                    try:
                        odds[f"over_{line_v}"] = float(inp)
                        inp2 = input(f"    Тотал <{line_v}: ").strip()
                        if inp2: odds[f"under_{line_v}"] = float(inp2)
                    except ValueError: pass
            # BTTS
            inp_b = input("    BTTS Да (Enter=пропустить): ").strip()
            if inp_b:
                try:
                    odds["btts_yes"] = float(inp_b)
                    inp_bn = input("    BTTS Нет: ").strip()
                    if inp_bn: odds["btts_no"] = float(inp_bn)
                except ValueError: pass
            # Углы
            inp_c = input("    Угловые >9.5 (Enter=пропустить): ").strip()
            if inp_c:
                try:
                    odds["corners_over_9.5"] = float(inp_c)
                    inp_cu = input("    Угловые <9.5: ").strip()
                    if inp_cu: odds["corners_under_9.5"] = float(inp_cu)
                except ValueError: pass
            key = f"{home_t} vs {away_t}"
            existing[key] = {"home": home_t, "away": away_t, "date": today, "odds": odds}
            saved += 1
        except Exception as e:
            print(f"  ⚠️  {e}")
    if saved > 0:
        with open(_MANUAL_ODDS_FILE, "w", encoding="utf-8") as f:
            json.dump(existing, f, ensure_ascii=False, indent=2)
        print(f"\n✅ Сохранено {saved} матчей → {_MANUAL_ODDS_FILE}")
        print("Запусти: python football_bot_v3.py today")
    else:
        print("\nНет данных для сохранения.")


def run_scheduler(hours: int = 12):
    print(f"⏰ Планировщик запущен — каждые {hours}ч")
    last_report_week = -1
    while True:
        try:
            run_scan()
            # Еженедельный отчёт по воскресеньям
            now = datetime.datetime.now()
            week = now.isocalendar()[1]
            if now.weekday() == 6 and week != last_report_week:
                send_weekly_report()
                last_report_week = week
            # Алерт просадки/серии — каждый скан
            check_drawdown_alert()
        except Exception as e:
            print(f"[ОШИБКА] {e}")
            _tg(f"⚠️ Ошибка бота: {e}")
        time.sleep(hours * 3600)

# ══════════════════════════════════════════════════════════════
#  🧪  ДЕМО-РЕЖИМ
# ══════════════════════════════════════════════════════════════
def run_demo():
    engine = Poisson()
    demo = [
        Match(1001,
            TeamStats("Манчестер Сити", 1, 2.3, 0.9, 0.09),
            TeamStats("Арсенал",        2, 2.0, 1.0),
            "Премьер-лига", "2026-03-01", "17:30",
            {"1":1.88,"X":3.60,"2":4.20,
             "over_2.5":1.70,"under_2.5":2.12,
             "over_1.5":1.27,"under_1.5":3.80,
             "over_3.5":2.85,"under_3.5":1.44,
             "btts_yes":1.72,"btts_no":2.05,
             "dnb_home":1.42,"dnb_away":2.80,
             "dc_1x":1.22,"dc_12":1.30,"dc_x2":1.75,
             "eh_home_-1":2.10,"eh_home_+1":1.55,
             "eh_away_-1":2.05,"eh_away_+1":1.75,
             "ah_home_-0.5":1.92,"ah_away_+0.5":1.92,
             "1h_over_0.5":1.65,"1h_under_0.5":2.15,
             "1h_over_1.5":2.80,"1h_under_1.5":1.42}),
        Match(1002,
            TeamStats("Бернли",  3, 0.8, 2.0, 0.05),
            TeamStats("Челси",   4, 2.0, 1.1),
            "Премьер-лига", "2026-03-01", "15:00",
            {"1":5.00,"X":3.80,"2":1.70,
             "over_2.5":1.80,"under_2.5":2.00,
             "over_1.5":1.30,"under_1.5":3.40,
             "btts_yes":1.95,"btts_no":1.85,
             "dnb_home":3.80,"dnb_away":1.38,
             "dc_1x":2.30,"dc_12":1.28,"dc_x2":1.18,
             "eh_home_+1":1.88,"eh_away_-1":2.05,
             "ah_home_+0.5":1.88,"ah_away_-0.5":1.95,
             "1h_over_0.5":2.00,"1h_under_0.5":1.80}),
        Match(1003,
            TeamStats("ПСЖ",   5, 2.4, 0.9, 0.10),
            TeamStats("Монако", 6, 1.7, 1.5),
            "Лига Чемпионов", "2026-03-01", "20:00",
            {"1":1.28,"X":5.50,"2":9.00,
             "over_2.5":1.75,"under_2.5":2.00,
             "over_3.5":2.60,"under_3.5":1.45,
             "btts_yes":2.10,"btts_no":1.65,
             "dnb_home":1.18,"dnb_away":5.50,
             "dc_1x":1.15,"dc_12":1.20,"dc_x2":2.40,
             "eh_home_-1":2.20,"eh_home_-2":4.00,
             "eh_away_+1":1.68,"eh_away_+2":1.30,
             "ah_home_-0.75":1.95,"ah_away_+0.75":1.88,
             "1h_over_0.5":1.55,"1h_under_0.5":2.35,
             "1h_over_1.5":2.70,"1h_under_1.5":1.44}),
    ]
    all_sig = []
    print(f"\n{'═'*62}")
    print(f"  🧪 ДЕМО  |  {datetime.datetime.now().strftime('%d.%m.%Y  %H:%M')}")
    print(f"{'═'*62}")
    for match in demo:
        lh, la, sigs = engine.analyze(match)
        print(f"\n  ⚽ {match.home.name} vs {match.away.name}  [{match.league}]  🕐 {match.time}")
        print(f"     xG → H:{lh:.2f}  A:{la:.2f}  Tot:{lh+la:.2f}")
        for s in sigs: _print_sig(s)
        if not sigs: print("     ─ Нет сигналов")
        tg_match(sigs, lh, la)
        all_sig.extend(sigs)
    save_csv(all_sig, "demo_signals.csv")
    tg_summary(all_sig, 2, len(demo))
    print(f"\n✅ Демо: {len(all_sig)} сигналов\n")

# ══════════════════════════════════════════════════════════════
#  🏁  ТОЧКА ВХОДА
# ══════════════════════════════════════════════════════════════

# ══════════════════════════════════════════════════════════════
#  📺  LIVE SIGNALS — сигналы по идущим матчам
#  python football_bot_v3.py live_signals        — разовый скан
#  python football_bot_v3.py live_signals watch  — каждые 10 мин
# ══════════════════════════════════════════════════════════════

def _fetch_live_fixtures() -> list:
    """Возвращает все матчи которые идут прямо сейчас."""
    data = _af_resp("fixtures", {"live": "all"})
    if not data:
        return []
    out = []
    for fix in data:
        lg  = fix.get("league", {})
        lid = lg.get("id", 0)
        if lid not in TRACKED_LEAGUES:
            continue
        st    = fix.get("fixture", {}).get("status", {})
        goals = fix.get("goals", {})
        teams = fix.get("teams", {})
        out.append({
            "fixture_id": fix.get("fixture", {}).get("id"),
            "home":       teams.get("home", {}).get("name", ""),
            "away":       teams.get("away", {}).get("name", ""),
            "home_id":    teams.get("home", {}).get("id", 0),
            "away_id":    teams.get("away", {}).get("id", 0),
            "league":     lg.get("name", ""),
            "league_id":  lid,
            "elapsed":    st.get("elapsed") or 0,
            "status":     st.get("short", ""),
            "home_goals": goals.get("home") or 0,
            "away_goals": goals.get("away") or 0,
        })
    return out


def _fetch_live_stats(fixture_id: int) -> dict:
    """Статистика матча: удары, владение, угловые и т.д."""
    data = _af_resp("fixtures/statistics", {"fixture": fixture_id})
    if not data or len(data) < 2:
        return {}

    def _parse(team_data: dict) -> dict:
        out = {}
        for item in team_data.get("statistics", []):
            t = item.get("type", "").lower()
            v = item.get("value")
            if v is None or str(v) == "None":
                v = 0
            try:
                v = float(str(v).replace("%", ""))
            except Exception:
                v = 0
            if "total shots" in t or "shots total" in t:
                out["shots"] = v
            elif "shots on" in t:
                out["shots_on"] = v
            elif "possession" in t:
                out["poss"] = v
            elif "corner" in t:
                out["corners"] = v
            elif "dangerous" in t:
                out["danger"] = v
            elif "offsides" in t:
                out["offsides"] = v
            elif "yellow" in t:
                out["yellows"] = v
        return out

    h = _parse(data[0])
    a = _parse(data[1])
    return {"home": h, "away": a}


def _live_xg(s: dict) -> float:
    """Расчётный xG из live-статистики."""
    return round(
        s.get("shots_on", 0) * 0.33 +
        (s.get("shots", 0) - s.get("shots_on", 0)) * 0.07 +
        s.get("corners", 0) * 0.04 +
        s.get("danger", 0) * 0.025,
        2
    )


def _fetch_live_odds(fixture_id: int) -> dict:
    """Лайв-коэффициенты из API-Football inplay."""
    data = _af_resp("odds/live", {"fixture": fixture_id})
    if not data:
        return {}
    odds = {}
    for item in data:
        for bet in item.get("bets", []):
            name   = bet.get("name", "").lower()
            values = bet.get("values", [])
            for v in values:
                val = v.get("value", "")
                p   = v.get("odd")
                try:
                    p = float(p)
                except Exception:
                    continue
                if p <= 1.01:
                    continue
                # Исход
                if "match winner" in name or "1x2" in name:
                    if val in ("Home","1"):   odds["1"]  = max(odds.get("1",  0), p)
                    elif val in ("Draw","X"): odds["X"]  = max(odds.get("X",  0), p)
                    elif val in ("Away","2"): odds["2"]  = max(odds.get("2",  0), p)
                # Тотал
                elif "total" in name and ("over" in val.lower() or "under" in val.lower()):
                    try:
                        num  = ''.join(c for c in val if c.isdigit() or c == '.')
                        line = float(num)
                        k    = f"over_{line}" if "over" in val.lower() else f"under_{line}"
                        odds[k] = max(odds.get(k, 0), p)
                    except Exception:
                        pass
    return odds


def _poisson_prob(lam: float, k: int) -> float:
    import math
    return math.exp(-lam) * (lam ** k) / math.factorial(k)


def _prob_over(lam_total: float, line: float) -> float:
    """P(total > line) по Пуассону."""
    import math
    p_under = sum(_poisson_prob(lam_total, k)
                  for k in range(int(line) + 1))
    return round(1 - p_under, 4)


def _prob_win(lh: float, la: float) -> tuple:
    """Вероятности победы хозяев/ничья/гостей по Пуассону."""
    import math
    N  = 10
    ph = pd = pa = 0.0
    for i in range(N):
        for j in range(N):
            p = math.exp(-lh)*(lh**i)/math.factorial(i) *                 math.exp(-la)*(la**j)/math.factorial(j)
            if   i > j: ph += p
            elif i == j: pd += p
            else:        pa += p
    return round(ph,4), round(pd,4), round(pa,4)


def generate_live_signals(fix: dict, stats: dict, odds: dict,
                           xg_pre_h: float = 0.0, xg_pre_a: float = 0.0) -> list:
    """
    Генерирует лайв-сигналы для одного матча.
    Использует: текущий счёт, статистику, лайв xG, предматчевый прогноз.
    """
    el      = fix["elapsed"]
    hg      = fix["home_goals"]
    ag      = fix["away_goals"]
    home    = fix["home"]
    away    = fix["away"]
    total   = hg + ag
    remaining = max(1, 90 - el)
    rem_frac  = remaining / 90

    hs = stats.get("home", {})
    as_ = stats.get("away", {})

    h_xg_live = _live_xg(hs)
    a_xg_live = _live_xg(as_)

    # Блендируем предматчевый и лайв xG
    if el >= 15 and (h_xg_live + a_xg_live) > 0:
        live_w = min(0.75, el / 90)
        pre_w  = 1.0 - live_w
        h_rate = h_xg_live / max(el, 1) * 90
        a_rate = a_xg_live / max(el, 1) * 90
        h_xg_proj = (xg_pre_h or h_rate) * pre_w + h_rate * live_w
        a_xg_proj = (xg_pre_a or a_rate) * pre_w + a_rate * live_w
    else:
        h_xg_proj = xg_pre_h if xg_pre_h > 0 else 1.5
        a_xg_proj = xg_pre_a if xg_pre_a > 0 else 1.2

    # xG за оставшееся время
    h_rem = round(h_xg_proj * rem_frac, 2)
    a_rem = round(a_xg_proj * rem_frac, 2)
    tot_rem = round(h_rem + a_rem, 2)

    # Давление
    h_poss  = hs.get("poss", 50)
    h_shots = hs.get("shots_on", 0)
    h_crn   = hs.get("corners", 0)
    h_dan   = hs.get("danger", 0)
    a_shots = as_.get("shots_on", 0)
    a_crn   = as_.get("corners", 0)
    a_dan   = as_.get("danger", 0)

    h_press = h_shots * 15 + (h_poss - 50) * 0.5 + h_crn * 2 + h_dan * 3
    a_press = a_shots * 15 + (50 - h_poss) * 0.5 + a_crn * 2 + a_dan * 3
    h_press = round(max(0, min(100, h_press)), 1)
    a_press = round(max(0, min(100, a_press)), 1)

    sigs = []
    MIN_E = 0.04  # минимальный валуй

    def _emit(market, sel, prob, key, min_e=MIN_E):
        bk = odds.get(key)
        if not bk or bk <= 1.05 or bk > 15.0:
            return
        imp  = round(1 / bk, 4)
        edge = round(prob - imp, 4)
        if prob >= 0.50 and edge >= min_e:
            ev   = round(prob * bk - 1, 3)
            conf = ("🔥 ВЫСОКАЯ" if edge >= 0.12 else
                    "✅ СРЕДНЯЯ" if edge >= 0.07 else "📌 НИЗКАЯ")
            sigs.append({
                "market":    market,
                "selection": sel,
                "prob":      round(prob, 3),
                "bk_odds":   bk,
                "edge":      edge,
                "ev":        ev,
                "conf":      conf,
            })

    # ── 1. ТОТАЛ ─────────────────────────────────────────────
    # Проецируем итоговый тотал: текущий + ожидаемые
    proj_total_lam = tot_rem  # ожидаемые голы за остаток — Пуассон
    for line in [total + 0.5, total + 1.5, total + 2.5]:
        po = _prob_over(proj_total_lam, line - total - 0.01)
        pu = 1 - po
        _emit("Тотал (лайв)", f"Больше {line}", po, f"over_{line}", min_e=0.04)
        _emit("Тотал (лайв)", f"Меньше {line}", pu, f"under_{line}", min_e=0.04)

    # ── 2. ИСХОД — кто победит ───────────────────────────────
    # Вероятность через Пуассон на остаток + текущий счёт
    if el >= 20 and el <= 80:
        # Симулируем остаток матча
        ph_rem, pd_rem, pa_rem = _prob_win(h_rem, a_rem)

        # Итоговые вероятности с учётом счёта
        # Если ведёт — шансы на победу = P(не пропустить достаточно)
        if hg > ag:
            diff = hg - ag
            # Вероятность сохранить победу = P(гости не наберут diff голов)
            p_a_catches = 1 - sum(_poisson_prob(a_rem, k)
                                  for k in range(diff)) if diff > 0 else 0
            ph_win = 1 - p_a_catches + pa_rem * 0.1
            ph_win = round(min(0.97, max(0.50, ph_win)), 3)
            _emit("Исход (лайв)", f"{home} победит", ph_win, "1", min_e=0.035)

        elif ag > hg:
            diff = ag - hg
            p_h_catches = 1 - sum(_poisson_prob(h_rem, k)
                                  for k in range(diff)) if diff > 0 else 0
            pa_win = 1 - p_h_catches + ph_rem * 0.1
            pa_win = round(min(0.97, max(0.50, pa_win)), 3)
            _emit("Исход (лайв)", f"{away} победит", pa_win, "2", min_e=0.035)

        elif hg == ag and el >= 60:
            # Ничья — смотрим давление
            if h_press > a_press + 25 and ph_rem > 0.38:
                _emit("Исход (лайв)", f"{home} победит", ph_rem + 0.10, "1", min_e=0.04)
            elif a_press > h_press + 25 and pa_rem > 0.35:
                _emit("Исход (лайв)", f"{away} победит", pa_rem + 0.10, "2", min_e=0.04)
            else:
                # Ничья вероятна
                pd_proj = round(pd_rem + 0.15, 3)
                _emit("Исход (лайв)", "Ничья", min(pd_proj, 0.55), "X", min_e=0.05)

    # ── 3. СЛЕДУЮЩИЙ ГОЛ — на основе давления ────────────────
    # (если букмекер даёт — это next_goal рынок, ключ "next_goal_h"/"next_goal_a")
    if el < 80:
        if h_press > a_press + 30 and h_rem > 0.3:
            p_ng_h = round(min(0.75, h_rem / (h_rem + a_rem + 0.01)), 3)
            _emit("След. гол", f"{home}", p_ng_h, "next_goal_h", min_e=0.035)
        elif a_press > h_press + 30 and a_rem > 0.3:
            p_ng_a = round(min(0.75, a_rem / (h_rem + a_rem + 0.01)), 3)
            _emit("След. гол", f"{away}", p_ng_a, "next_goal_a", min_e=0.035)

    # ── 4. ОБОЮДНЫЕ ГОЛЫ (если оба не забивали — вероятность забьют) ──
    if hg == 0 or ag == 0:
        # Оба ещё не забили или один не забил
        p_h_scores = 1 - _poisson_prob(h_rem, 0)  # P(хозяева забьют хоть 1)
        p_a_scores = 1 - _poisson_prob(a_rem, 0)
        p_btts = round(p_h_scores * p_a_scores, 3)
        if hg > 0: p_btts = p_a_scores  # хозяева уже забили
        if ag > 0: p_btts = p_h_scores
        _emit("Обе забьют (лайв)", "Да", p_btts, "btts_yes", min_e=0.05)

    return sigs, {
        "el": el, "score": f"{hg}:{ag}",
        "h_xg_live": h_xg_live, "a_xg_live": a_xg_live,
        "h_rem": h_rem, "a_rem": a_rem, "tot_rem": tot_rem,
        "h_press": h_press, "a_press": a_press,
    }


def run_live_signals(watch: bool = False):
    """
    Сканирует все текущие матчи и генерирует лайв-сигналы.
    watch=True — повторяет каждые 10 минут.
    """
    import time as _time

    # Загружаем предматчевые прогнозы чтобы знать наш xG
    pred_cache = {}
    try:
        if os.path.exists("predictions.json"):
            with open("predictions.json", encoding="utf-8") as f:
                preds = json.load(f)
            for p in preds:
                pred_cache[str(p.get("fixture_id",""))] = p
    except Exception:
        pass

    # Кэш уже отправленных сигналов (чтобы не спамить)
    sent_cache: set = set()

    def _scan_once():
        now_str = datetime.datetime.now().strftime("%H:%M")
        print(f"\n{'═'*62}")
        print(f"  📺 ЛАЙВ-СИГНАЛЫ  [{now_str}]")
        print(f"{'═'*62}")

        fixtures = _fetch_live_fixtures()
        if not fixtures:
            print("  ℹ️  Нет матчей в эфире прямо сейчас")
            return

        print(f"  Матчей в эфире: {len(fixtures)}")
        total_sigs = 0

        for fix in fixtures:
            fid  = fix["fixture_id"]
            home = fix["home"]
            away = fix["away"]
            el   = fix["elapsed"]
            hg   = fix["home_goals"]
            ag   = fix["away_goals"]
            lid  = fix["league_id"]
            lg   = fix["league"]

            # Только матчи с 10 по 80 минуту — до и после лайв-ставки обычно закрыты
            if el < 10 or el > 82:
                continue

            print(f"\n  🏟  {home} {hg}:{ag} {away}  [{el}']  {lg}")

            # Предматчевый xG если есть
            pred   = pred_cache.get(str(fid), {})
            xg_h   = pred.get("xg_home", 0)
            xg_a   = pred.get("xg_away", 0)

            # Загружаем статистику и лайв-коэффициенты
            stats = _fetch_live_stats(fid)
            _time.sleep(3)
            odds  = _fetch_live_odds(fid)
            _time.sleep(3)

            if not stats:
                print(f"     ⚠️  Нет live-статистики")
                continue

            sigs, info = generate_live_signals(fix, stats, odds, xg_h, xg_a)

            # Строка давления
            hp = info["h_press"]; ap = info["a_press"]
            hbar = ("█" * int(hp/10)).ljust(10)
            abar = ("█" * int(ap/10)).ljust(10)
            print(f"     xG лайв: {info['h_xg_live']} — {info['a_xg_live']}"
                  f"  |  Ост: +{info['h_rem']} +{info['a_rem']}")
            print(f"     Давление: {hp:.0f} {hbar} | {abar} {ap:.0f}")

            if not sigs:
                # Проверяем есть ли коэффициенты вообще
                if not odds:
                    print(f"     💡 Нет лайв-коэффициентов в API")
                else:
                    print(f"     ─ Валуя не найдено ({len(odds)} коэф. доступно)")
                continue

            print(f"     {'─'*50}")
            tg_lines = [
                f"📺 <b>ЛАЙВ-СИГНАЛ</b>",
                f"⚽ {home} {hg}:{ag} {away}  [{el}']  {lg}",
                f"📊 xG ост: +{info['h_rem']} — +{info['a_rem']}  "
                f"давл: {hp:.0f}—{ap:.0f}",
                "",
                "🎯 <b>Сигналы:</b>",
            ]

            for s in sigs:
                sig_key = f"{fid}_{s['market']}_{s['selection']}"
                is_new  = sig_key not in sent_cache
                marker  = "🆕 " if is_new else "   "

                print(f"     {marker}{s['conf']}  [{s['market']}]  ➜  {s['selection']}")
                print(f"          Коэф: {s['bk_odds']}  |  Валуй: {s['edge']:+.1%}"
                      f"  |  EV: {s['ev']:+.3f}")

                if is_new:
                    sent_cache.add(sig_key)
                    ev = s["ev"]
                    tg_lines.append(
                        f"  {s['conf']}  [{s['market']}]  ➜  <b>{s['selection']}</b>\n"
                        f"  Коэф: <b>{s['bk_odds']}</b>  Валуй: {s['edge']:+.1%}  EV: {ev:+.3f}"
                    )
                total_sigs += 1

            if any(sig_key not in sent_cache or True
                   for s in sigs
                   for sig_key in [f"{fid}_{s['market']}_{s['selection']}"]):
                if tg_lines[-1] != "🎯 <b>Сигналы:</b>":
                    _tg("\n".join(tg_lines))

        print(f"\n{'─'*62}")
        print(f"  Итого лайв-сигналов: {total_sigs}")
        if watch:
            print(f"  Следующий скан через 10 мин  (Ctrl+C — выход)")

    if not watch:
        _scan_once()
        return

    # Watch режим
    print(f"  👁️  Авторежим — скан каждые 10 минут")
    print(f"  Ctrl+C — остановить")
    while True:
        try:
            _scan_once()
            _time.sleep(600)
        except KeyboardInterrupt:
            print("\n⛔ Лайв-сигналы остановлены")
            break
        except Exception as e:
            print(f"  ⚠️ Ошибка: {e}")
            _time.sleep(60)

# ══════════════════════════════════════════════════════════════
#  📺  LIVE_MATCH — анализ матча с сигналом в реальном времени
# ══════════════════════════════════════════════════════════════

def _load_today_signals() -> list:
    """Загружает предматчевые прогнозы за сегодня из predictions.json."""
    try:
        if not os.path.exists("predictions.json"):
            return []
        with open("predictions.json", encoding="utf-8") as f:
            preds = json.load(f)
        today = datetime.datetime.now().strftime("%Y-%m-%d")
        return [p for p in preds
                if p.get("date","")[:10] == today and p.get("signals")]
    except Exception:
        return []


def cmd_live_match_list():
    """Показывает список матчей сегодня у которых есть сигналы."""
    preds = _load_today_signals()
    if not preds:
        print("  ℹ️  Нет матчей с сигналами сегодня.")
        print("  Сначала запусти: python football_bot_v3.py today")
        return
    print(f"\n{'═'*62}")
    print(f"  📺 МАТЧИ С СИГНАЛАМИ СЕГОДНЯ  ({len(preds)} матчей)")
    print(f"{'═'*62}")
    for p in preds:
        fid  = p.get("fixture_id","?")
        h    = p.get("home","?")
        a    = p.get("away","?")
        t    = p.get("time","?")
        xgh  = p.get("xg_home",0)
        xga  = p.get("xg_away",0)
        sigs = p.get("signals",[])
        print(f"  🆔 {str(fid):>10}  ⏰ {t}  ⚽ {h} vs {a}")
        print(f"     xG: {xgh} — {xga}  (тотал {round(xgh+xga,2)})")
        for s in sigs:
            conf = s.get("confidence","")
            icon = "🔥" if "ВЫСОК" in conf else ("✅" if "СРЕДН" in conf else "📌")
            edge = s.get("edge",0)
            print(f"     {icon} [{s.get('market','')}] {s.get('selection','')} "
                  f"@ {s.get('bookmaker_odds','')}  валуй {edge*100:.1f}%")
        print()
    print("  ▶  Анализ матча: python football_bot_v3.py live_match <ID>")
    print("  ▶  Авто-режим:   python football_bot_v3.py live_match watch")


def cmd_live_match_analyze(fixture_id: int):
    """Полный лайв-анализ конкретного матча с разбором сигналов."""
    preds = _load_today_signals()
    pred  = next((p for p in preds
                  if str(p.get("fixture_id")) == str(fixture_id)), None)
    if not pred:
        print(f"  ❌ Матч {fixture_id} не найден в сегодняшних сигналах.")
        cmd_live_match_list()
        return

    fid  = pred["fixture_id"]
    home = pred["home"]
    away = pred["away"]
    xgh  = pred.get("xg_home", 1.5)
    xga  = pred.get("xg_away", 1.2)
    sigs = pred.get("signals", [])

    print(f"\n{'═'*62}")
    print(f"  📺 ЛАЙВ-АНАЛИЗ: {home} vs {away}")
    print(f"  🔮 Предматчевый прогноз: xG {xgh} — {xga}  "
          f"(тотал {round(xgh+xga,2)})")
    print(f"{'─'*62}")
    print(f"  📋 Ваши сигналы на этот матч:")
    for s in sigs:
        conf = s.get("confidence","")
        icon = "🔥" if "ВЫСОК" in conf else ("✅" if "СРЕДН" in conf else "📌")
        ev   = round(s.get("model_prob",0.5) * s.get("bookmaker_odds",2.0) - 1, 3)
        print(f"    {icon} [{s.get('market','')}]  {s.get('selection','')}  "
              f"@ {s.get('bookmaker_odds','')}  EV: {ev:+.3f}")
    print(f"{'─'*62}")
    print(f"  ⏳ Загружаю live-статистику...")

    analysis = analyze_live_team(fid, home, away, xgh, xga)

    if "error" in analysis:
        print(f"  ⚠️  {analysis['error']}")
        print(f"  💡 Матч ещё не начался или нет live данных.")
        print(f"     Попробуй снова после начала матча.")
        return

    el = analysis["elapsed"]
    sc = analysis["score"]
    hg, ag = map(int, sc.split(":"))
    remaining = max(0, 90 - el)
    hp = analysis["home_pressure"]
    ap = analysis["away_pressure"]

    print(f"\n  ⚽ СЧЁТ: {home}  {sc}  {away}  [{el}']")
    print(f"{'─'*62}")
    print(f"  📊 СТАТИСТИКА ЛАЙВ:")
    print(f"    {'':22s}  {home[:16]:>16s}  {away[:16]:>16s}")
    print(f"    {'─'*56}")
    print(f"    {'xG накоплено':22s}  {analysis['home_xg_live']:>16.2f}  "
          f"{analysis['away_xg_live']:>16.2f}")
    print(f"    {'xG за ост. {remaining}мин':22s}  {analysis['home_xg_rem']:>16.2f}  "
          f"{analysis['away_xg_rem']:>16.2f}")
    print(f"    {'Удары (цель/всего)':22s}  {analysis['home_shots']:>16s}  "
          f"{analysis['away_shots']:>16s}")
    print(f"    {'Владение':22s}  {analysis['home_poss']:>15.0f}%  "
          f"{100-analysis['home_poss']:>15.0f}%")
    # Полоса давления
    hbar = ("█" * int(hp / 10)).ljust(10)
    abar = ("█" * int(ap / 10)).ljust(10)
    print(f"    {'Давление':22s}  {hp:>4.0f}/100 {hbar}  {ap:>4.0f}/100 {abar}")

    print(f"{'─'*62}")
    proj_total = hg + ag + analysis["total_rem"]
    print(f"  🔮 ПРОГНОЗ НА ОСТАВШИЕСЯ {remaining} МИН:")
    print(f"     Ожидаем ещё голов:  {analysis['total_rem']:.2f}")
    print(f"     Итоговый тотал:    ~{proj_total:.1f}")

    # Оценка сигналов по текущему счёту
    print(f"{'─'*62}")
    print(f"  🎯 ОЦЕНКА ВАШИХ СИГНАЛОВ:")
    status_labels = {
        "ok":       ("✅","ИДЁТ ПО ПЛАНУ"),
        "danger":   ("⚠️","ОПАСНОСТЬ — следи"),
        "dead":     ("🚨","МЁРТВ — рассмотри кэшаут"),
        "pending":  ("⏳","В ОЖИДАНИИ"),
        "finished": ("🏁","ЗАВЕРШЁН"),
    }
    score_data = {"status":"LIVE","elapsed":el,"home":hg,"away":ag}
    try:
        from live_monitor import evaluate_signal_live
        for s in sigs:
            st = evaluate_signal_live(s, score_data)
            icon, label = status_labels.get(st, ("❓", st))
            print(f"    {icon} [{s.get('market','')}] "
                  f"{s.get('selection','')} @ {s.get('bookmaker_odds','')}  → {label}")
    except ImportError:
        print("    ℹ️  live_monitor.py не найден — оценка недоступна")

    # Новые лайв-сигналы
    if analysis["live_signals"]:
        print(f"{'─'*62}")
        print(f"  💡 НОВЫЕ ЛАЙВ-СИГНАЛЫ:")
        for sig in analysis["live_signals"]:
            print(f"    {sig['confidence']} [{sig['market']}]  {sig['selection']}")
            print(f"       {sig['reason']}")

    print(f"{'═'*62}")

    # Отправляем в Telegram
    tg_lines = [
        f"📺 <b>ЛАЙВ-АНАЛИЗ</b>  [{el}']  {home} {sc} {away}",
        "",
        f"<b>{home}</b>: xG {analysis['home_xg_live']} | удары {analysis['home_shots']} | давление {hp:.0f}/100",
        f"<b>{away}</b>: xG {analysis['away_xg_live']} | удары {analysis['away_shots']} | давление {ap:.0f}/100",
        "",
        f"🔮 Ожидаем ещё <b>{analysis['total_rem']:.1f}</b> голов (итог ~{proj_total:.1f})",
        "",
        "📋 <b>Статус сигналов:</b>",
    ]
    try:
        from live_monitor import evaluate_signal_live
        for s in sigs:
            st = evaluate_signal_live(s, score_data)
            icon = status_labels.get(st, ("❓",""))[0]
            tg_lines.append(
                f"  {icon} [{s.get('market','')}] "
                f"{s.get('selection','')} @ {s.get('bookmaker_odds','')}"
            )
    except ImportError:
        pass
    if analysis["live_signals"]:
        tg_lines.append("")
        tg_lines.append("💡 <b>Новые лайв-сигналы:</b>")
        for sig in analysis["live_signals"]:
            tg_lines.append(f"  {sig['confidence']} [{sig['market']}] {sig['selection']}")
            tg_lines.append(f"  <i>{sig['reason']}</i>")

    _tg("\n".join(tg_lines))
    print(f"  📱 Анализ отправлен в Telegram")


def cmd_live_match_watch():
    """Авто-режим: обновляет анализ всех матчей с сигналами каждые 10 минут."""
    print(f"\n{'═'*62}")
    print(f"  👁️  WATCH MODE — обновление каждые 10 минут")
    print(f"  Остановить: Ctrl+C")
    print(f"{'═'*62}")

    seen = {}   # skey → last_status

    while True:
        preds  = _load_today_signals()
        active = []
        for p in preds:
            a = analyze_live_team(p["fixture_id"], p["home"], p["away"],
                                  p.get("xg_home",1.5), p.get("xg_away",1.2))
            if "error" not in a and a.get("elapsed", 0) > 0:
                active.append((p, a))

        now = datetime.datetime.now().strftime("%H:%M")
        if not active:
            print(f"  [{now}] Нет активных матчей, жду 5 мин...")
            time.sleep(300)
            continue

        print(f"\n  [{now}] Активных: {len(active)}")
        print(f"{'─'*62}")

        try:
            from live_monitor import evaluate_signal_live
            _eval_available = True
        except ImportError:
            _eval_available = False

        for pred, a in active:
            fid  = pred["fixture_id"]
            home = pred["home"]
            away = pred["away"]
            el   = a["elapsed"]
            sc   = a["score"]
            hg, ag = map(int, sc.split(":"))
            hp   = a["home_pressure"]
            ap   = a["away_pressure"]

            print(f"  ⚽ {home} {sc} {away}  [{el}']  "
                  f"давл: {hp:.0f}—{ap:.0f}  "
                  f"ост.xG: {a['home_xg_rem']:.1f}—{a['away_xg_rem']:.1f}")

            if _eval_available:
                score_data = {"status":"LIVE","elapsed":el,"home":hg,"away":ag}
                for s in pred.get("signals", []):
                    skey   = f"{fid}_{s.get('market','')}_{s.get('selection','')}"
                    status = evaluate_signal_live(s, score_data)
                    prev   = seen.get(skey)
                    if status != prev:
                        seen[skey] = status
                        if status == "dead":
                            print(f"     🚨 МЁРТВ: [{s.get('market','')}] {s.get('selection','')}")
                            _tg(f"🚨 <b>СИГНАЛ МЁРТВ</b>\n"
                                f"⚽ {home} {sc} {away} [{el}']\n"
                                f"❌ [{s.get('market','')}] {s.get('selection','')} @ {s.get('bookmaker_odds','')}")
                        elif status == "danger":
                            print(f"     ⚠️  ОПАСНОСТЬ: [{s.get('market','')}] {s.get('selection','')}")
                            _tg(f"⚠️ <b>ОПАСНОСТЬ</b>\n"
                                f"⚽ {home} {sc} {away} [{el}']\n"
                                f"⚠️ [{s.get('market','')}] {s.get('selection','')} идёт против прогноза")
                        elif status == "ok":
                            print(f"     ✅ ПО ПЛАНУ: [{s.get('market','')}] {s.get('selection','')}")

            for sig in a.get("live_signals", []):
                print(f"     💡 {sig['confidence']} {sig['selection']}: {sig['reason']}")

        print(f"{'─'*62}")
        print(f"  Следующее обновление через 10 мин...")
        time.sleep(600)



# ══════════════════════════════════════════════════════════════
#  📈  BACKTESTING
#  Запуск: python football_bot_v3.py backtest [2021] [100]
#  league: 2021=АПЛ 2002=Бундеслига 2014=ЛаЛига 2019=СерияА
# ══════════════════════════════════════════════════════════════

def run_backtest(league_fd_id: int = 2021, season: int = 2024,
                 max_matches: int = 100) -> None:
    import time, collections
    NAMES = {2021:"АПЛ 2024/25", 2002:"Бундеслига 2024/25",
             2014:"Ла Лига 2024/25", 2019:"Серия А 2024/25",
             2015:"Лига 1 2024/25", 2017:"Прем.лига Португалии 2024/25"}
    lname = NAMES.get(league_fd_id, f"Лига {league_fd_id}")
    print(f"\n{'='*60}")
    print(f"  📈 BACKTESTING: {lname}")
    print(f"  До {max_matches} завершённых матчей...")
    print(f"{'='*60}")

    url  = (f"https://api.football-data.org/v4/competitions/{league_fd_id}"
            f"/matches?season={season}&status=FINISHED")
    data = _http(url, {"X-Auth-Token": FOOTBALL_DATA_KEY}, silent=True)
    if not isinstance(data, dict) or "matches" not in data:
        print("  ❌ Не удалось загрузить матчи")
        print("     Проверь FOOTBALL_DATA_KEY или попробуй другую лигу")
        return

    matches = data["matches"][:max_matches]
    print(f"  Загружено {len(matches)} матчей\n")

    eng = Poisson()
    res = {"1X2": [0,0], "Тотал>2.5": [0,0], "BTTS": [0,0]}
    edge_signals = []   # (edge, correct)

    for m in matches:
        try:
            hn = (m["homeTeam"]["shortName"] or m["homeTeam"]["name"])
            an = (m["awayTeam"]["shortName"] or m["awayTeam"]["name"])
            hs = m["score"]["fullTime"]["home"]
            as_ = m["score"]["fullTime"]["away"]
            if hs is None or as_ is None:
                continue
            hs, as_ = int(hs), int(as_)

            hgs, hgc, _ = _lookup_team(hn.lower(), True,  league_fd_id)
            ags, agc, _ = _lookup_team(an.lower(), False, league_fd_id)
            ts_h = TeamStats(hn, 0, hgs, hgc, 0.08)
            ts_a = TeamStats(an, 0, ags, agc, 0.00)
            mi   = MatchInput(home=ts_h, away=ts_a, league=lname,
                              date=m.get("utcDate","")[:10], time="", fixture_id=0)
            lh2, la2 = eng.lambdas(mi)
            mat2      = eng.matrix(lh2, la2)
            ph, pd, pa = eng.prob_1x2(mat2)
            po, _      = eng.prob_total(mat2, 2.5)
            btts_yes   = sum(mat2[i][j] for i in range(1,8) for j in range(1,8))

            # 1X2 точность
            pred = "1" if ph>pd and ph>pa else ("X" if pd>pa else "2")
            real = "1" if hs>as_ else ("X" if hs==as_ else "2")
            res["1X2"][0] += 1
            if pred == real: res["1X2"][1] += 1

            # Тотал
            tot = hs+as_
            res["Тотал>2.5"][0] += 1
            if (po>0.55 and tot>2.5) or (po<=0.55 and tot<=2.5):
                res["Тотал>2.5"][1] += 1

            # BTTS
            rb = hs>0 and as_>0
            res["BTTS"][0] += 1
            if (btts_yes>0.5 and rb) or (btts_yes<=0.5 and not rb):
                res["BTTS"][1] += 1

            # Edge-анализ: только сигналы с edge > 5%
            best_p = max(ph, pd, pa)
            est_coef = 1.07 / best_p
            edge = best_p - 1.0/est_coef
            if edge > 0.05:
                correct = (pred == real)
                edge_signals.append((edge, correct, best_p))

        except Exception:
            continue
        time.sleep(0.06)

    # Отчёт
    print(f"  {'Рынок':<18} {'Правильно':>9} {'Всего':>7} {'%':>7}")
    print(f"  {'-'*45}")
    for mkt, (tot2, cor) in res.items():
        if tot2 == 0: continue
        pct = cor/tot2*100
        print(f"  {mkt:<18} {cor:>9} {tot2:>7} {pct:>6.1f}%")

    pct_1x2 = res["1X2"][1]/max(1,res["1X2"][0])*100
    base = 33.3
    diff = pct_1x2 - base
    print(f"\n  Случайный выбор 1X2: {base:.0f}%")
    print(f"  Модель: {pct_1x2:.1f}% ({'+'if diff>0 else ''}{diff:.1f}% к случайному)")
    if pct_1x2 > 42:
        print(f"  ✅ Модель выше базового — хороший результат")
    else:
        print(f"  ⚠️  Близко к случайному — нужен реальный xG из Understat")

    if edge_signals:
        n = len(edge_signals)
        w = sum(1 for _,c2,_ in edge_signals if c2)
        avg_e = sum(e for e,_,_ in edge_signals)/n
        print(f"\n  Edge>5% сигналов: {n}")
        print(f"  Проходимость: {w}/{n} = {w/n*100:.1f}%")
        print(f"  Средний edge: {avg_e*100:.1f}%")
        roi = (w/n - (1 - w/n)) * avg_e
        print(f"  Грубый ROI: {roi*100:.1f}%")

    print(f"\n  💡 Для точного backtesting подключи реальный xG (Understat)")
    print(f"  📊 После 200+ реальных сигналов → запускай ML")
    print(f"{'='*60}\n")

if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "today"

    if   mode == "manual":     run_manual_odds_input()
    elif mode == "today":      run_scan(today_only=True)
    elif mode == "scan":       run_scan(int(sys.argv[2]) if len(sys.argv)>2 else 3)
    elif mode == "schedule":   run_scheduler(int(sys.argv[2]) if len(sys.argv)>2 else 12)
    elif mode == "demo":       run_demo()
    elif mode == "pinnacle":   test_pinnacle_connection()
    elif mode == "backtest":
        lg = int(sys.argv[2]) if len(sys.argv) > 2 else 2021
        mx = int(sys.argv[3]) if len(sys.argv) > 3 else 100
        run_backtest(league_fd_id=lg, max_matches=mx)
    elif mode == "report":     generate_html_report()
    elif mode == "live":
        import subprocess, sys as _sys
        subprocess.Popen([_sys.executable, "live_monitor.py"])
        print("⚡ Live Monitor запущен в фоне")
    elif mode == "live_signals":
        arg = sys.argv[2] if len(sys.argv) > 2 else ""
        run_live_signals(watch=(arg == "watch"))
    elif mode == "verify":
        verify_yesterday_signals()
        print_ml_stats()
    else:
        print(f"Режимы: today | scan [дней] | schedule | demo | backtest [league_id] | verify")
        run_scan(today_only=True)
