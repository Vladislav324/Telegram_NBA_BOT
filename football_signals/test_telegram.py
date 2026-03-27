"""
Диагностика Telegram — запусти и скинь результат.
python test_telegram.py
"""
import json, ssl, urllib.request

TOKEN   = "8263616332:AAGGJwEnlJSy160VlpaLcN2v8bbJ3hpf7gA"
CHAT_ID = "-3885532223"

def _tg_raw(method, body):
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    url = f"https://api.telegram.org/bot{TOKEN}/{method}"
    data = json.dumps(body).encode()
    req  = urllib.request.Request(url, data=data,
           headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10, context=ctx) as r:
            return json.load(r), None
    except urllib.error.HTTPError as e:
        return None, f"HTTP {e.code}: {e.read().decode()}"
    except Exception as e:
        return None, str(e)

print("="*50)
print("ТЕСТ 1 — Простой текст (без HTML):")
res, err = _tg_raw("sendMessage", {
    "chat_id": CHAT_ID,
    "text": "Тест бота ⚽"
})
if res:
    print("  ✅ OK — простой текст работает!")
else:
    print(f"  ❌ {err}")
    # Пробуем с -100 prefix
    chat_id2 = "-100" + CHAT_ID.lstrip("-")
    print(f"\n  Пробую chat_id = {chat_id2}")
    res2, err2 = _tg_raw("sendMessage", {
        "chat_id": chat_id2,
        "text": "Тест бота ⚽"
    })
    if res2:
        print(f"  ✅ Работает с chat_id = {chat_id2}")
        print(f"  ⚠️  Нужно поменять TELEGRAM_CHAT_ID в боте на {chat_id2}")
    else:
        print(f"  ❌ {err2}")
        print("\n  Возможные причины:")
        print("  1. Бот не добавлен в канал как администратор")
        print("  2. У бота нет права публиковать сообщения")
        print("  3. chat_id неверный")

print("\nТЕСТ 2 — HTML текст:")
res, err = _tg_raw("sendMessage", {
    "chat_id": CHAT_ID,
    "text": "⚽ <b>Тест</b> HTML",
    "parse_mode": "HTML"
})
if res:
    print("  ✅ HTML работает!")
else:
    print(f"  ❌ {err}")

print("\nТЕСТ 3 — getChat (инфо о канале):")
res, err = _tg_raw("getChat", {"chat_id": CHAT_ID})
if res:
    ch = res.get("result", {})
    print(f"  ✅ Канал найден: {ch.get('title','?')} | тип: {ch.get('type','?')}")
    print(f"  ID: {ch.get('id','?')}")
else:
    print(f"  ❌ {err}")
print("="*50)
