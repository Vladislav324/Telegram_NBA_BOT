# ⚽ Football Signals Bot v3

Betting-бот для поиска Value Bets на футбол с ML-моделью.

## 🏗️ Архитектура

```
football_signals/
├── football_bot_v3.py    # Главный бот — сканирование + сигналы
├── learning.py           # Обучение — результаты + Google Sheets
├── live_monitor.py       # Live-мониторинг активных ставок
├── ml_calibrate.py       # ML-калибровка (Platt + XGBoost)
├── backtest.py           # Бэктест и метрики
├── odds_fetcher.py       # Реальные коэфы (Odds API + 1xBet + AF)
├── betfair_client.py     # Betfair Exchange API
├── config.py             # Централизованная конфигурация
├── logger.py             # Логирование (консоль + файл)
├── run_bot.py            # Единая точка запуска
├── .env                  # Секреты (НЕ в Git!)
├── .env.example          # Шаблон переменных
├── requirements.txt      # Зависимости
└── docker-compose.yml    # Docker окружение
```

## 🚀 Быстрый старт

```bash
# 1. Клонируй и настрой
git clone https://github.com/Vladislav324/Telegram_NBA_BOT
cd football_signals
pip install -r requirements.txt

# 2. Создай .env (скопируй из .env.example и заполни)
cp .env.example .env

# 3. Статус
python run_bot.py status

# 4. Первый скан
python run_bot.py today
```

## ⏰ Расписание (cron)

```cron
# Утренний скан (09:00 пн-пт)
0 9 * * 1-5 cd /path && python run_bot.py today >> logs/cron.log 2>&1

# Дневной скан (18:00)
0 18 * * * cd /path && python run_bot.py today >> logs/cron.log 2>&1

# Обновление результатов (08:00)
0 8 * * * cd /path && python run_bot.py learn >> logs/cron.log 2>&1

# ML калибровка (раз в 2 недели)
0 10 1,15 * * cd /path && python run_bot.py calibrate >> logs/cron.log 2>&1
```

## 📊 Источники коэффициентов

| Приоритет | Источник | Покрытие | Квота |
|---|---|---|---|
| 0a | Betfair Exchange | Топ-лиги | Без лимита |
| 0b | OddsFetcher (Odds API + 1xBet) | Широкое | 500/мес |
| 1 | Pinnacle Guest | Топ-лиги | Без лимита |
| 2 | Fonbet | Топ-лиги | Только RU IP |
| 3 | Odds API | 30+ лиг | 500/мес |
| 4 | SofaScore | Широкое | Только не-PL IP |
| 5 | Pari.ru | Топ-лиги | Только RU IP |
| 6 | Расчётные | Все | Без лимита |

## 🧮 Модель

- **Пуассон** — базовая вероятность по xG
- **ELO** — форма команд
- **Platt calibration** — коррекция вероятностей
- **XGBoost (опц.)** — второй уровень на реальных данных
- **Kelly criterion (×0.15)** — оптимальный размер ставки

## ⚠️ Ответственный гемблинг

- Никогда не ставь больше 2-5% банкролла на один сигнал
- Бот не даёт гарантий прибыли
- Букмекеры могут ограничить аккаунт при систематических выигрышах
- Всегда проверяй сигналы перед ставкой

## 🐳 Docker

```bash
docker-compose up -d
docker-compose logs -f football-bot
```
