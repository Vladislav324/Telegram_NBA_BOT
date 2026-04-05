"""
Тест подключения к Google Sheets.
python test_sheets.py
"""
import os, sys, json, ssl, time

SHEET_ID  = "1R6_VG3BqpJK-qW2ItBHm4Mvqpa27uheFEOXQx1IjJ80"
CREDS_FILE = "credentials.json"

def _get_token():
    if not os.path.exists(CREDS_FILE):
        print(f"❌ Файл {CREDS_FILE} не найден в папке!")
        print(f"   Положи credentials.json рядом с этим скриптом.")
        return None
    try:
        with open(CREDS_FILE, encoding="utf-8") as f:
            creds = json.load(f)
        print(f"✅ credentials.json найден")
        print(f"   Email: {creds.get('client_email','?')}")

        import base64
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import padding

        def _b64url(data):
            return base64.urlsafe_b64encode(data).rstrip(b"=").decode()

        now   = int(time.time())
        claim = {
            "iss":   creds["client_email"],
            "scope": "https://www.googleapis.com/auth/spreadsheets",
            "aud":   "https://oauth2.googleapis.com/token",
            "iat":   now, "exp": now + 3600,
        }
        header  = _b64url(json.dumps({"alg":"RS256","typ":"JWT"}).encode())
        payload = _b64url(json.dumps(claim).encode())
        msg     = f"{header}.{payload}".encode()

        priv_key = serialization.load_pem_private_key(
            creds["private_key"].encode(), password=None
        )
        sig = priv_key.sign(msg, padding.PKCS1v15(), hashes.SHA256())
        jwt = f"{header}.{payload}.{_b64url(sig)}"

        import urllib.request, urllib.parse
        body = urllib.parse.urlencode({
            "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
            "assertion":  jwt,
        }).encode()
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        req = urllib.request.Request(
            "https://oauth2.googleapis.com/token", data=body,
            headers={"Content-Type": "application/x-www-form-urlencoded"}
        )
        with urllib.request.urlopen(req, timeout=15, context=ctx) as r:
            tok = json.load(r)
            token = tok.get("access_token")
            if token:
                print("✅ Токен Google OAuth получен")
                return token
            else:
                print(f"❌ Токен не получен: {tok}")
                return None
    except ImportError:
        print("❌ Не установлена библиотека cryptography")
        print("   Запусти: pip install cryptography")
        return None
    except Exception as e:
        print(f"❌ Ошибка получения токена: {e}")
        return None

def test_connection(token):
    import urllib.request
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    # Читаем инфо о таблице
    url = f"https://sheets.googleapis.com/v4/spreadsheets/{SHEET_ID}"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(req, timeout=15, context=ctx) as r:
            data = json.load(r)
        title = data.get("properties", {}).get("title", "?")
        sheets = [s["properties"]["title"] for s in data.get("sheets", [])]
        print(f"✅ Таблица найдена: «{title}»")
        print(f"   Вкладки: {sheets}")
        return True
    except Exception as e:
        print(f"❌ Не могу открыть таблицу: {e}")
        print(f"   Проверь: добавил ли ты email сервисного аккаунта")
        print(f"   как редактора в настройках доступа таблицы?")
        return False

def write_test_row(token):
    import urllib.request
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    # Пишем тестовую строку
    body = json.dumps({"values": [["✅ ТЕСТ", "Бот подключён!", str(time.strftime("%d.%m.%Y %H:%M"))]]}).encode()
    import urllib.parse as _up
    tab  = _up.quote("Лист1")
    url  = f"https://sheets.googleapis.com/v4/spreadsheets/{SHEET_ID}/values/{tab}!A1:append?valueInputOption=USER_ENTERED"
    req  = urllib.request.Request(url, data=body, method="POST",
           headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=15, context=ctx) as r:
            json.load(r)
        print("✅ Тестовая строка записана в таблицу!")
        print(f"   Открой таблицу и проверь — должна появиться строка с текстом '✅ ТЕСТ'")
    except Exception as e:
        print(f"❌ Не могу записать в таблицу: {e}")

# ── Запуск ──────────────────────────────────────────────────
print("="*50)
print("  ТЕСТ ПОДКЛЮЧЕНИЯ К GOOGLE SHEETS")
print("="*50)
print()

token = _get_token()
if not token:
    sys.exit(1)

print()
ok = test_connection(token)
if not ok:
    sys.exit(1)

print()
write_test_row(token)
print()
print("="*50)
print("  Если всё ✅ — бот готов писать в таблицу!")
print("  Запусти: python football_bot_v3.py")
print("  Потом:   python learning.py")
print("  Данные появятся автоматически после матчей.")
print("="*50)
