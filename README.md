# Сигнальная система для шортов на памп-дампах Bybit

Веб-сервис смотрит USDT-перпетуалы Bybit, замечает памп и после затухания движения собирает сигнал на шорт. Сделки система не открывает. Вход решает трейдер.

Полное описание поведения — в [TZ.md](TZ.md). Ход работ — в [PROGRESS.md](PROGRESS.md).

## Слои

| Процесс | Каталог | Роль |
|---|---|---|
| Collector | `collector/` | WebSocket Bybit, нормализация, публикация в Redis |
| Signal Engine | `signal_engine/` | Пампы, ликвидации, OI, CVD, уровни, запись в SQLite |
| Web Server | `ws_server/` | FastAPI: страница, WebSocket в браузер |

Связь между процессами — Redis Pub/Sub. История сигналов — SQLite. Браузер получает только готовые сигналы.

## Что уже есть

Этап 1 — каркас и `config.py`.

Этап 2 — коллектор. Он подписывается на `publicTrade`, `allLiquidation`, `orderbook.50` и `tickers` всех USDT-перпетуалов, режет подписки по соединениям и публикует нормализованный поток в Redis (`market:data`). OI и свечи добираются по REST. Памп коллектор не считает.

Запуск коллектора (нужны Redis и зависимости):

```bash
python -m collector
```

Этап 3 — движок сигналов. Раз в 3 секунды он ищет памп и добирает подтверждения: затухание ликвидаций шортов, падение OI, спад объёма, свуп на 1H/4H/1D. Карточки пишутся в SQLite и в Redis (`signals:updates`).

```bash
python -m signal_engine
```

Этап 4 — страница. FastAPI отдаёт доску, карточку и статистику. Браузер подключается к `/ws`. Пока Redis молчит, на экране пример и жёлтый баннер: это не живой рынок.

```bash
python -m ws_server
```

Страница открывается на `http://127.0.0.1:8787`. Кнопка «Открыть график на Bybit» открывает только Bybit в браузере этой машины.

## Запуск окружения

Нужен Python 3.10+.

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
```

На Linux и macOS активация — `source .venv/bin/activate`, копия файла — `cp .env.example .env`.

Redis должен быть доступен по `REDIS_URL` (по умолчанию `redis://127.0.0.1:6379/0`). Ключ Bybit для публичных каналов не обязателен. Если ключ используется, он должен быть Read-Only.

Проверка настроек:

```bash
python -m unittest tests.test_config
```

## VPS (Timeweb): деплой и PM2

После `git pull` на сервере в `/opt/signals`:

```bash
bash scripts/deploy.sh
```

Первый раз — установка PM2 и автозапуск после reboot:

```bash
bash scripts/setup_pm2.sh
```

Процессы: `collector`, `signal-engine`, `ws-server`, `btc-strategy-test`. Логи: `logs-*.txt` в корне проекта.

## Чего система не делает

- Не выставляет ордера.
- Не советует размер позиции.
- Не открывает другие биржи: кнопка графика ведёт только на Bybit.
