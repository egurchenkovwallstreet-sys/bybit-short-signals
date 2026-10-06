"""
Настройки сигнальной системы.

Значения по умолчанию совпадают с ТЗ. Секреты читаются только из
переменных окружения или из локального файла .env (он не коммитится).
Уже заданные переменные окружения файл .env не перезаписывает.
"""

from __future__ import annotations

import os
from pathlib import Path


# Корень проекта — каталог, где лежит этот файл.
BASE_DIR = Path(__file__).resolve().parent


def load_dotenv(path: Path | None = None) -> None:
    """Прочитать KEY=VALUE из .env, не затирая уже заданное окружение."""
    env_path = path or (BASE_DIR / ".env")
    if not env_path.is_file():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            os.environ.setdefault(key, value)


def _env(name: str, default: str) -> str:
    """Строка из окружения или значение по умолчанию."""
    value = os.environ.get(name)
    if value is None or value.strip() == "":
        return default
    return value.strip()


def _env_int(name: str, default: int) -> int:
    """Целое из окружения или значение по умолчанию."""
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    return int(raw)


def _env_float(name: str, default: float) -> float:
    """Дробное из окружения или значение по умолчанию."""
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    return float(raw)


# Подхватываем локальный .env до чтения настроек.
load_dotenv()


# --- Bybit -------------------------------------------------------------------

# Публичный REST и линейный WebSocket USDT-перпетуалов.
BYBIT_REST_URL = _env("BYBIT_REST_URL", "https://api.bybit.com")
BYBIT_WS_PUBLIC_LINEAR = _env(
    "BYBIT_WS_PUBLIC_LINEAR",
    "wss://stream.bybit.com/v5/public/linear",
)

# Read-Only ключ. Для публичных рыночных данных не обязателен.
BYBIT_API_KEY = _env("BYBIT_API_KEY", "")
BYBIT_API_SECRET = _env("BYBIT_API_SECRET", "")

# Прокси для REST и WebSocket Bybit (HTTP, HTTPS или SOCKS5).
# Пусто — прямое подключение. Нужен, если CDN Bybit блокирует IP сервера (403 country).
# Пример: http://user:pass@host:port или socks5://host:1080
BYBIT_PROXY = _env("BYBIT_PROXY", "")

# Рынок: бессрочные контракты с котировкой USDT.
BYBIT_CATEGORY = "linear"
BYBIT_QUOTE = "USDT"

# Шаблоны топиков Bybit v5. Подставляется символ вида BEAMUSDT.
WS_TOPIC_TRADE = "publicTrade.{symbol}"
WS_TOPIC_LIQUIDATION = "allLiquidation.{symbol}"
WS_TOPIC_ORDERBOOK = "orderbook.50.{symbol}"
WS_TOPIC_TICKER = "tickers.{symbol}"

# Интервалы истории открытого интереса (параметр intervalCoin / intervalTime).
OI_INTERVALS = ("5min", "15min", "30min", "1h", "4h", "1d")

# Коды интервалов свечей Bybit v5: 1, 5, 15, 60, 240, D.
KLINE_INTERVALS = ("1", "5", "15", "30", "60", "240", "D")

# Ссылка на график. Открывается только Bybit, решение о входе — вручную.
BYBIT_TRADE_URL = "https://www.bybit.com/trade/usdt/{symbol}"


# --- Переподключение коллектора ---------------------------------------------

# Пауза растёт 1с → 2с → 4с → 8с и дальше держится на 8 секундах.
RECONNECT_DELAYS_SEC = (1, 2, 4, 8)
# Если соединение прожило дольше этого порога, следующая пауза снова начинается с 1 с.
RECONNECT_RESET_AFTER_SEC = _env_int("RECONNECT_RESET_AFTER_SEC", 10)

# Документация Bybit: у фьючерсов нет лимита числа args, но длина массива
# args на одно публичное соединение не больше 21 000 символов.
# Свой предел символов на сокет: стакан 50 уровней приходит каждые 20 мс.
WS_MAX_ARGS_CHARS = _env_int("WS_MAX_ARGS_CHARS", 21000)
WS_SYMBOLS_PER_CONNECTION = _env_int("WS_SYMBOLS_PER_CONNECTION", 40)
WS_SUBSCRIBE_BATCH = _env_int("WS_SUBSCRIBE_BATCH", 10)
WS_PING_INTERVAL_SEC = _env_int("WS_PING_INTERVAL_SEC", 20)

# Как часто заново запрашивать список USDT-перпетуалов.
INSTRUMENTS_REFRESH_SEC = _env_int("INSTRUMENTS_REFRESH_SEC", 300)

# --- Universe (collector): какие USDT-перпетуалы мониторим -----------------
# Минимальный оборот за 24h (turnover24h в USDT) по тикеру Bybit v5.
UNIVERSE_MIN_TURNOVER_24H_USDT = _env_float("UNIVERSE_MIN_TURNOVER_24H_USDT", 1_000_000.0)
# Минимальный возраст листинга linear perpetual (дней).
UNIVERSE_MIN_LISTING_AGE_DAYS = _env_int("UNIVERSE_MIN_LISTING_AGE_DAYS", 90)
# Пауза после полного круга REST (OI и свечи). Сами запросы ещё тормозит ccxt.
REST_CYCLE_PAUSE_SEC = _env_int("REST_CYCLE_PAUSE_SEC", 30)
KLINE_FETCH_LIMIT = _env_int("KLINE_FETCH_LIMIT", 200)
OI_FETCH_LIMIT = _env_int("OI_FETCH_LIMIT", 200)
# Окно индикаторов в карточке сигнала (открытый интерес, CVD и т.д.), часы.
DETAIL_CHART_WINDOW_HOURS = _env_int("DETAIL_CHART_WINDOW_HOURS", 48)
ORDERBOOK_DEPTH = 50


# --- Redis -------------------------------------------------------------------

REDIS_URL = _env("REDIS_URL", "redis://127.0.0.1:6379/0")

# Лимит буфера канала. При переполнении отбрасываются самые старые сообщения.
REDIS_CHANNEL_BUFFER = _env_int("REDIS_CHANNEL_BUFFER", 1024)

# collector публикует нормализованный поток, signal_engine — готовые сигналы.
REDIS_CHANNEL_MARKET = _env("REDIS_CHANNEL_MARKET", "market:data")
REDIS_CHANNEL_SIGNALS = _env("REDIS_CHANNEL_SIGNALS", "signals:updates")


# --- Частота -----------------------------------------------------------------

# Веб-сокет к браузеру не чаще 10 Гц. Тикеры пакуются раз в 500 мс.
WS_MAX_HZ = _env_int("WS_MAX_HZ", 10)
TICKER_BATCH_INTERVAL_MS = _env_int("TICKER_BATCH_INTERVAL_MS", 500)

# Как часто проверять каждую пару на памп.
MARKET_SCAN_INTERVAL_SEC = _env_int("MARKET_SCAN_INTERVAL_SEC", 3)

# Страница и WebSocket. Только локальный просмотр, сервер не торгует.
WEB_HOST = _env("WEB_HOST", "127.0.0.1")
WEB_PORT = _env_int("WEB_PORT", 8787)


# --- SQLite ------------------------------------------------------------------

DATA_DIR = BASE_DIR / "data"
SQLITE_PATH = Path(_env("SQLITE_PATH", str(DATA_DIR / "signals.db")))

# --- Тест: BTC стратегия (вне основного ТЗ) ---------------------------------

BTC_TEST_SYMBOL = _env("BTC_TEST_SYMBOL", "BTCUSDT")
BTC_TEST_SYMBOL_REDIS_KEY = _env("BTC_TEST_SYMBOL_REDIS_KEY", "btc_test:active_symbol")
BTC_TEST_SQLITE_PATH = Path(_env("BTC_TEST_SQLITE_PATH", str(DATA_DIR / "btc_strategy.db")))
REDIS_CHANNEL_BTC_TEST = _env("REDIS_CHANNEL_BTC_TEST", "btc:strategy:updates")
BTC_TEST_SCAN_SEC = _env_float("BTC_TEST_SCAN_SEC", 3.0)
BTC_TEST_KLINE_REFRESH_SEC = _env_int("BTC_TEST_KLINE_REFRESH_SEC", 45)
# Taker ~0.055% за сделку (открытие + закрытие = 2×).
BTC_TEST_FEE_RATE_TAKER = _env_float("BTC_TEST_FEE_RATE_TAKER", 0.00055)
BTC_TEST_MIN_MTF_SCORE_INTRADAY = _env_int("BTC_TEST_MIN_MTF_SCORE_INTRADAY", 6)
BTC_TEST_MIN_MTF_SCORE_SCALP = _env_int("BTC_TEST_MIN_MTF_SCORE_SCALP", 5)
BTC_TEST_MIN_PERP_SCORE = _env_int("BTC_TEST_MIN_PERP_SCORE", 2)
BTC_TEST_MIN_ENTRY_SCORE = _env_int("BTC_TEST_MIN_ENTRY_SCORE", 8)
BTC_TEST_ENTRY_COOLDOWN_SEC = _env_int("BTC_TEST_ENTRY_COOLDOWN_SEC", 300)
# Лонг: не догонять памп — RSI и отрыв от EMA20 на 15m.
BTC_TEST_LONG_MAX_RSI_15 = _env_float("BTC_TEST_LONG_MAX_RSI_15", 68.0)
BTC_TEST_LONG_MAX_RSI_5 = _env_float("BTC_TEST_LONG_MAX_RSI_5", 62.0)
BTC_TEST_LONG_MAX_EMA_EXTENSION_ATR = _env_float("BTC_TEST_LONG_MAX_EMA_EXTENSION_ATR", 1.2)
# Рост за ~4 часа (15m×16): выше — лонг не открываем (типичный хвост пампа).
BTC_TEST_LONG_BLOCK_4H_CHANGE_PCT = _env_float("BTC_TEST_LONG_BLOCK_4H_CHANGE_PCT", 6.0)


# --- Telegram (опционально, отправка не входит в Этап 1) --------------------

TELEGRAM_BOT_TOKEN = _env("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = _env("TELEGRAM_CHAT_ID", "")


# --- Детекция пампа (шаг 1 signal engine) -----------------------------------

# Памп по цене: ≥30% за 1ч или ≥50% за сутки. Объём — всплеск на одном из TF; порог × растёт с TF.
# На 1h: учитывается только при росте ≥30% и объёме ≥×8 за час (иначе окно не актуально).
PUMP_PRICE_CHANGE_1H = _env_float("PUMP_PRICE_CHANGE_1H", 30.0)
PUMP_PRICE_CHANGE_24H = _env_float("PUMP_PRICE_CHANGE_24H", 50.0)
PUMP_PRICE_CHANGE_15M = _env_float("PUMP_PRICE_CHANGE_15M", 5.0)
PUMP_PRICE_CHANGE_5M = _env_float("PUMP_PRICE_CHANGE_5M", 3.0)
PUMP_VOLUME_SPIKE_MIN = _env_float("PUMP_VOLUME_SPIKE_MIN", 5.0)
PUMP_VOLUME_SPIKE_MIN_5M = _env_float("PUMP_VOLUME_SPIKE_MIN_5M", 5.0)
PUMP_VOLUME_SPIKE_MIN_30M = _env_float("PUMP_VOLUME_SPIKE_MIN_30M", 6.0)
PUMP_VOLUME_SPIKE_MIN_1H = _env_float("PUMP_VOLUME_SPIKE_MIN_1H", 8.0)
PUMP_VOLUME_SPIKE_MIN_4H = _env_float("PUMP_VOLUME_SPIKE_MIN_4H", 10.0)
PUMP_VOLUME_SPIKE_MIN_1D = _env_float("PUMP_VOLUME_SPIKE_MIN_1D", 12.0)
PUMP_VOLUME_SPIKE_WINDOWS_1M = (5, 30, 60)
PUMP_VOLUME_MULTIPLIER = _env_float("PUMP_VOLUME_MULTIPLIER", 5.0)
PUMP_VOLUME_MA_PERIOD = _env_int("PUMP_VOLUME_MA_PERIOD", 20)
PUMP_RSI_MIN = _env_float("PUMP_RSI_MIN", 60.0)
PUMP_RSI_MAX = _env_float("PUMP_RSI_MAX", 85.0)

# Ликвидации шортистов: сторона S = Sell. Затухание — падение потока на 70%+ от пика.
LIQUIDATION_SIDE_SHORT = "Sell"
LIQUIDATION_FADE_RATIO = _env_float("LIQUIDATION_FADE_RATIO", 0.70)
# Окно, в котором ищется пик ликвидаций и текущий поток.
LIQUIDATION_WINDOW_MIN = _env_int("LIQUIDATION_WINDOW_MIN", 15)

# RSI считается по минутным закрытиям. В ТЗ период не задан: берётся Уайлдер 14.
PUMP_RSI_PERIOD = _env_int("PUMP_RSI_PERIOD", 14)

# OI «падает», если за окно снижение не меньше этого процента.
OI_DROP_PCT = _env_float("OI_DROP_PCT", 0.5)
OI_LOOKBACK_MIN = _env_int("OI_LOOKBACK_MIN", 30)

# Спад объёма ищется среди последних минутных баров после пика.
VOLUME_LOOKBACK_BARS = _env_int("VOLUME_LOOKBACK_BARS", 15)

# Допуск касания уровня, в процентах от цены. Классы силы — пороги формулы из ТЗ.
LEVEL_TOUCH_PCT = _env_float("LEVEL_TOUCH_PCT", 0.15)
LEVEL_STRONG_MIN = _env_float("LEVEL_STRONG_MIN", 8)
LEVEL_MEDIUM_MIN = _env_float("LEVEL_MEDIUM_MIN", 4)

# Funding Bybit — доля за период. 0.001 = 0.1%, это уже перегрев.
FUNDING_EXTREME_RATE = _env_float("FUNDING_EXTREME_RATE", 0.001)
ROUND_LEVEL_WINDOW_BARS = _env_int("ROUND_LEVEL_WINDOW_BARS", 60)
TAKER_WINDOW_MIN = _env_int("TAKER_WINDOW_MIN", 5)
DIVERGENCE_LOOKBACK_MIN = _env_int("DIVERGENCE_LOOKBACK_MIN", 15)

# Пока закрытых сигналов меньше порога, вероятность берётся из экспертных весов.
PROBABILITY_MIN_SAMPLE = _env_int("PROBABILITY_MIN_SAMPLE", 20)
PROBABILITY_BASE = _env_float("PROBABILITY_BASE", 50)
PROBABILITY_CAP = _env_float("PROBABILITY_CAP", 95)

BAR_HISTORY_LIMIT = 200
# Минутные бары для пампа. Старшие ТФ для свупов: 1H, 4H, 1D.
HTF_INTERVALS = ("60", "240", "D")
# Свечи для EMA 50/100/200 в «Памп-скан» (пересекаются с HTF на 60 и 240).
PUMP_SCAN_EMA_INTERVALS = ("15", "30", "60", "240")
PUMP_SCAN_MIN_24H_PCT = _env_float("PUMP_SCAN_MIN_24H_PCT", 35.0)
PUMP_SCAN_COLUMNS = {
    4: {"color": "green", "status": "К ШОРТУ", "label": "4/4"},
    3: {"color": "orange", "status": "ОСЛАБЛЕНИЕ", "label": "3/4"},
    2: {"color": "yellow", "status": "СМЕНА ИМПУЛЬСА", "label": "2/4"},
    1: {"color": "blue", "status": "НАБЛЮДЕНИЕ", "label": "1/4"},
}


# --- Исход сигнала -----------------------------------------------------------

# Для шорта: цена упала на 3% — цель, выросла на 10% — ликвидация, иначе 24 часа.
TP_PCT = _env_float("TP_PCT", 3.0)
LIQUIDATION_PCT = _env_float("LIQUIDATION_PCT", 10.0)
TIME_EXIT_HOURS = _env_int("TIME_EXIT_HOURS", 24)

# Множитель в формуле живого P&L из ТЗ. Это отображение, не совет по размеру позиции.
PNL_LEVERAGE = _env_int("PNL_LEVERAGE", 10)


# --- Колонки интерфейса ------------------------------------------------------

# Ключ — число подтверждений. Слева направо на экране: 5, 4, 3, 2, 1.
SIGNAL_COLUMNS = {
    5: {"color": "green", "status": "ВХОД", "label": "5/5"},
    4: {"color": "orange", "status": "ПОЧТИ ГОТОВ", "label": "4/5"},
    3: {"color": "yellow", "status": "ОЖИДАНИЕ", "label": "3/5"},
    2: {"color": "blue", "status": "ФОРМИРОВАНИЕ", "label": "2/5"},
    1: {"color": "gray", "status": "НАБЛЮДЕНИЕ", "label": "1/5"},
}


# --- Уровни и рейтинг (константы формулы, расчёт — на Этапе 3) --------------

PIVOT_NEIGHBORS = 5
LEVEL_LOOKBACK_CANDLES = 200
LEVEL_SCORE_REVERSAL = 3
LEVEL_SCORE_SWEEP = 2
LEVEL_SCORE_TOUCH = 1
LEVEL_SCORE_BREAK = 5
ROUND_LEVEL_MIN_PIERCES = 2

# Рейтинг = (Сила × 20) + (Вероятность × 0.5) + (Качество × 10)
#           + (Совпадение ТФ × 5) + (Доп × 3)
RATING_WEIGHT_STRENGTH = 20
RATING_WEIGHT_PROBABILITY = 0.5
RATING_WEIGHT_QUALITY = 10
RATING_WEIGHT_TF = 5
RATING_WEIGHT_EXTRA = 3


# --- Экспертные веса на старте (модуль статистики) --------------------------

EXPERT_WEIGHTS = {
    "sweep": 0.15,
    "liquidations_faded": 0.20,
    "oi_drop": 0.10,
    "cvd_divergence": 0.10,
    "round_level": 0.05,
    "funding_extreme": 0.05,
}
