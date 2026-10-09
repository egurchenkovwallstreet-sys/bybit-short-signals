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
# REST-круг коллектора: без 5m/30m — движку достаточно 1/15/60/240/D.
KLINE_INTERVALS = ("1", "15", "60", "240", "D")

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
REST_CYCLE_PAUSE_SEC = _env_int("REST_CYCLE_PAUSE_SEC", 60)
# Throttle публикации в Redis (снижает CPU на малых VPS). 0 = без ограничения.
COLLECTOR_ORDERBOOK_PUBLISH_MIN_SEC = _env_float("COLLECTOR_ORDERBOOK_PUBLISH_MIN_SEC", 0.35)
COLLECTOR_TICKER_PUBLISH_MIN_SEC = _env_float("COLLECTOR_TICKER_PUBLISH_MIN_SEC", 1.0)
KLINE_FETCH_LIMIT = _env_int("KLINE_FETCH_LIMIT", 200)
OI_FETCH_LIMIT = _env_int("OI_FETCH_LIMIT", 200)
# Окно индикаторов в карточке сигнала (открытый интерес, CVD и т.д.), часы.
DETAIL_CHART_WINDOW_HOURS = _env_int("DETAIL_CHART_WINDOW_HOURS", 48)
ORDERBOOK_DEPTH = _env_int("ORDERBOOK_DEPTH", 500)


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

# --- Тест стратегии: виртуальные шорты после пампа --------------------------
# Сделки только на бумаге. Ордера на бирже не выставляются.

PAPER_SQLITE_PATH = Path(_env("PAPER_SQLITE_PATH", str(DATA_DIR / "paper_strategy.db")))
PAPER_START_BALANCE_USD = _env_float("PAPER_START_BALANCE_USD", 1000.0)
PAPER_MARGIN_PCT = _env_float("PAPER_MARGIN_PCT", 5.0)
PAPER_LEVERAGE = _env_int("PAPER_LEVERAGE", 10)
PAPER_FEE_RATE_TAKER = _env_float("PAPER_FEE_RATE_TAKER", 0.00055)
# Поддерживающая маржа: изолированный шорт ×10 ликвидируется около +9.5%, а не ровно +10%.
PAPER_MAINT_MARGIN_RATE = _env_float("PAPER_MAINT_MARGIN_RATE", 0.005)
PAPER_REENTRY_COOLDOWN_SEC = _env_int("PAPER_REENTRY_COOLDOWN_SEC", 300)

# Трейлинг: расстояние стопа от лучшей цены в % цены по прибыли на маржу (ROE).
PAPER_TRAIL_START_DIST_PCT = _env_float("PAPER_TRAIL_START_DIST_PCT", 10.0)
PAPER_TRAIL_TIGHTEN_FROM_ROE = _env_float("PAPER_TRAIL_TIGHTEN_FROM_ROE", 100.0)
PAPER_TRAIL_TIGHTEN_TO_ROE = _env_float("PAPER_TRAIL_TIGHTEN_TO_ROE", 300.0)
PAPER_TRAIL_MIN_DIST_PCT = _env_float("PAPER_TRAIL_MIN_DIST_PCT", 2.0)

# Памп: короткий (окно до 4 ч / 24 ч по 15m), длинный (7 д / 14 д по 4H).
PAPER_SHORT_4H_MIN_PCT = _env_float("PAPER_SHORT_4H_MIN_PCT", 30.0)
PAPER_SHORT_24H_MIN_PCT = _env_float("PAPER_SHORT_24H_MIN_PCT", 50.0)
PAPER_LONG_7D_MIN_PCT = _env_float("PAPER_LONG_7D_MIN_PCT", 80.0)
PAPER_LONG_14D_MIN_PCT = _env_float("PAPER_LONG_14D_MIN_PCT", 100.0)
PAPER_PUMP_VOLUME_MIN_RATIO = _env_float("PAPER_PUMP_VOLUME_MIN_RATIO", 10.0)
PAPER_PUMP_VOLUME_BASE_BARS = _env_int("PAPER_PUMP_VOLUME_BASE_BARS", 20)
PAPER_PUMP_BUY_SHARE_MIN_PCT = _env_float("PAPER_PUMP_BUY_SHARE_MIN_PCT", 70.0)
# Лента сделок покрывает рост не меньше этого (минуты), иначе доля покупок неизвестна.
PAPER_PUMP_TAPE_MIN_MINUTES = _env_int("PAPER_PUMP_TAPE_MIN_MINUTES", 60)
PAPER_TAPE_RETENTION_HOURS = _env_int("PAPER_TAPE_RETENTION_HOURS", 26)
# Сколько кандидат живёт после пика и насколько цена может уйти от пика.
PAPER_SHORT_LIFETIME_HOURS = _env_int("PAPER_SHORT_LIFETIME_HOURS", 12)
PAPER_LONG_LIFETIME_HOURS = _env_int("PAPER_LONG_LIFETIME_HOURS", 48)
PAPER_MAX_DRAWDOWN_FROM_PEAK_PCT = _env_float("PAPER_MAX_DRAWDOWN_FROM_PEAK_PCT", 25.0)

# Торможение: без нового хая 20 мин – 2 ч, ширина диапазона 5–10%.
PAPER_STALL_MIN_MINUTES = _env_int("PAPER_STALL_MIN_MINUTES", 20)
PAPER_STALL_MAX_MINUTES = _env_int("PAPER_STALL_MAX_MINUTES", 120)
PAPER_RANGE_MIN_PCT = _env_float("PAPER_RANGE_MIN_PCT", 5.0)
PAPER_RANGE_MAX_PCT = _env_float("PAPER_RANGE_MAX_PCT", 10.0)
# Покупки «упали»: последние 15 мин не больше этой доли от пика 15 мин за 3 ч.
PAPER_BUYS_FADE_MAX_RATIO = _env_float("PAPER_BUYS_FADE_MAX_RATIO", 0.5)
PAPER_SELL_WINDOWS_MIN = (5, 10, 15)
PAPER_SELL_SHARE_MIN_PCT = _env_float("PAPER_SELL_SHARE_MIN_PCT", 50.0)
PAPER_SELL_WINDOWS_REQUIRED = _env_int("PAPER_SELL_WINDOWS_REQUIRED", 2)
# Объём «падает»: средний 1m объём за 20 мин против пика такой же средней за 3 ч.
PAPER_VOLUME_WINDOW_MIN = _env_int("PAPER_VOLUME_WINDOW_MIN", 20)
PAPER_VOLUME_FADE_MAX_RATIO = _env_float("PAPER_VOLUME_FADE_MAX_RATIO", 0.6)
# Раздача: объём не упал, а цена за 20 мин снизилась минимум на столько.
PAPER_DISTRIBUTION_PRICE_DROP_PCT = _env_float("PAPER_DISTRIBUTION_PRICE_DROP_PCT", 2.0)
# Ликвидации шортов: текущий поток не больше (1 − fade) от пика в окне.
PAPER_SHORT_LIQ_WINDOW_MIN = _env_int("PAPER_SHORT_LIQ_WINDOW_MIN", 15)
PAPER_SHORT_LIQ_FADE_MIN = _env_float("PAPER_SHORT_LIQ_FADE_MIN", 0.80)
PAPER_SHORT_LIQ_FADE_STRONG = _env_float("PAPER_SHORT_LIQ_FADE_STRONG", 0.90)

# BTC: рост за 4 ч от порога — строгий режим (нужен пробой EMA50 15m или двойная вершина).
PAPER_BTC_SYMBOL = _env("PAPER_BTC_SYMBOL", "BTCUSDT")
PAPER_BTC_STRICT_4H_PCT = _env_float("PAPER_BTC_STRICT_4H_PCT", 3.0)

# EMA 50/100/200 на 15m/30m/1H/4H — пробой закрытием свечи.
PAPER_EMA_INTERVALS = ("15", "30", "60", "240")
PAPER_EMA_PERIODS = (50, 100, 200)
PAPER_KLINE_LIMIT = _env_int("PAPER_KLINE_LIMIT", 320)
PAPER_KLINE_REFRESH_SEC = _env_int("PAPER_KLINE_REFRESH_SEC", 60)

# Двойная вершина: 1H ≥10 свечей между вершинами или 30m ≥20, разница ≤3%, после 2-й ≥3 ч.
PAPER_DT_MIN_BARS_1H = _env_int("PAPER_DT_MIN_BARS_1H", 10)
PAPER_DT_MIN_BARS_30M = _env_int("PAPER_DT_MIN_BARS_30M", 20)
PAPER_DT_MAX_DIFF_PCT = _env_float("PAPER_DT_MAX_DIFF_PCT", 3.0)
PAPER_DT_MIN_HOURS_AFTER = _env_float("PAPER_DT_MIN_HOURS_AFTER", 3.0)
PAPER_DT_PIVOT_WING = _env_int("PAPER_DT_PIVOT_WING", 2)

# Сильная двойная вершина: 2-я ниже 1-й, разница < 10%, после 2-й ≥ 2 ч,
# между вершинами 1H ≥5 свечей или 30m ≥10.
PAPER_STRONG_TOP_MAX_DIFF_PCT = _env_float("PAPER_STRONG_TOP_MAX_DIFF_PCT", 10.0)
PAPER_STRONG_TOP_MIN_HOURS_AFTER = _env_float("PAPER_STRONG_TOP_MIN_HOURS_AFTER", 2.0)
PAPER_STRONG_TOP_MIN_BARS_1H = _env_int("PAPER_STRONG_TOP_MIN_BARS_1H", 5)
PAPER_STRONG_TOP_MIN_BARS_30M = _env_int("PAPER_STRONG_TOP_MIN_BARS_30M", 10)

# Варианты входа, у каждого свой счёт: любые N из 9 условий, все 9, сильная вершина + N условий.
PAPER_VARIANTS = ("v5", "v9", "dt")
PAPER_V5_MIN_PASSED = _env_int("PAPER_V5_MIN_PASSED", 5)
PAPER_DT_MIN_PASSED = _env_int("PAPER_DT_MIN_PASSED", 3)

# После перезапуска свечи в памяти не сразу полные: кандидата не снимаем
# «по условиям пампа», пока не прошло столько минут и не набралась история.
PAPER_STARTUP_GRACE_MIN = _env_int("PAPER_STARTUP_GRACE_MIN", 15)
PAPER_READY_15M_BARS = _env_int("PAPER_READY_15M_BARS", 96)
PAPER_READY_4H_BARS = _env_int("PAPER_READY_4H_BARS", 84)

# Круглый уровень (0.5, 1, 5, 10…): пик или диапазон в пределах этого % от уровня.
PAPER_ROUND_LEVEL_NEAR_PCT = _env_float("PAPER_ROUND_LEVEL_NEAR_PCT", 1.5)

PAPER_DETECT_INTERVAL_SEC = _env_int("PAPER_DETECT_INTERVAL_SEC", 30)
PAPER_PERSIST_INTERVAL_SEC = _env_int("PAPER_PERSIST_INTERVAL_SEC", 15)
PAPER_EQUITY_SNAPSHOT_SEC = _env_int("PAPER_EQUITY_SNAPSHOT_SEC", 300)

# --- Лаборатория пампа (вкладка «Анализ пампа») ------------------------------

PUMP_LAB_SQLITE_PATH = Path(_env("PUMP_LAB_SQLITE_PATH", str(DATA_DIR / "pump_lab.db")))
PUMP_LAB_SCAN_INTERVAL_SEC = _env_int("PUMP_LAB_SCAN_INTERVAL_SEC", 300)
PUMP_LAB_SNAPSHOT_INTERVAL_SEC = _env_int("PUMP_LAB_SNAPSHOT_INTERVAL_SEC", 300)
PUMP_LAB_HISTORY_POINTS = _env_int("PUMP_LAB_HISTORY_POINTS", 48)
PUMP_LAB_MAX_DRAWDOWN_PCT = _env_float("PUMP_LAB_MAX_DRAWDOWN_PCT", 25.0)
# Минимальный рост дно→пик по классу пампа (%).
PUMP_LAB_GROWTH_MIN_FAST = _env_float("PUMP_LAB_GROWTH_MIN_FAST", 40.0)
PUMP_LAB_GROWTH_MIN_MEDIUM = _env_float("PUMP_LAB_GROWTH_MIN_MEDIUM", 80.0)
PUMP_LAB_GROWTH_MIN_LONG = _env_float("PUMP_LAB_GROWTH_MIN_LONG", 100.0)
# Пик объёма на ноге роста / средняя 20 баров до дна.
PUMP_LAB_VOLUME_MIN_FAST = _env_float("PUMP_LAB_VOLUME_MIN_FAST", 10.0)
PUMP_LAB_VOLUME_MIN_MEDIUM = _env_float("PUMP_LAB_VOLUME_MIN_MEDIUM", 20.0)
PUMP_LAB_VOLUME_MIN_LONG = _env_float("PUMP_LAB_VOLUME_MIN_LONG", 20.0)
# Откат от пика ≥ этого % — фаза «памп прошёл», эпизод снимается с доски.
PUMP_LAB_PASSED_DD_FAST = _env_float("PUMP_LAB_PASSED_DD_FAST", 10.0)
PUMP_LAB_PASSED_DD_MEDIUM = _env_float("PUMP_LAB_PASSED_DD_MEDIUM", 12.0)
PUMP_LAB_PASSED_DD_LONG = _env_float("PUMP_LAB_PASSED_DD_LONG", 15.0)
PUMP_LAB_MAX_AGE_DAYS = _env_int("PUMP_LAB_MAX_AGE_DAYS", 20)
# Длительность роста (дно → пик): быстрый ≤6 ч, средний ≤3 сут, иначе длинный (до 20 сут).
PUMP_LAB_FAST_MAX_MS = _env_int("PUMP_LAB_FAST_MAX_MS", 6 * 3_600_000)
PUMP_LAB_MEDIUM_MAX_MS = _env_int("PUMP_LAB_MEDIUM_MAX_MS", 3 * 24 * 3_600_000)
# Фазы: откат от пика (%), «нет нового хая» (мин), подтверждение дампа (%).
PUMP_LAB_PHASE_STALL_MIN_FAST = _env_int("PUMP_LAB_PHASE_STALL_MIN_FAST", 20)
PUMP_LAB_PHASE_STALL_MIN_MED = _env_int("PUMP_LAB_PHASE_STALL_MIN_MED", 120)
PUMP_LAB_PHASE_STALL_MIN_LONG = _env_int("PUMP_LAB_PHASE_STALL_MIN_LONG", 720)
PUMP_LAB_PHASE_DD_YELLOW_FAST = _env_float("PUMP_LAB_PHASE_DD_YELLOW_FAST", 3.0)
PUMP_LAB_PHASE_DD_YELLOW_MED = _env_float("PUMP_LAB_PHASE_DD_YELLOW_MED", 5.0)
PUMP_LAB_PHASE_DD_YELLOW_LONG = _env_float("PUMP_LAB_PHASE_DD_YELLOW_LONG", 8.0)
PUMP_LAB_PHASE_DD_GREEN_FAST = _env_float("PUMP_LAB_PHASE_DD_GREEN_FAST", 3.0)
PUMP_LAB_PHASE_DD_GREEN_MED = _env_float("PUMP_LAB_PHASE_DD_GREEN_MED", 5.0)
PUMP_LAB_PHASE_DD_GREEN_LONG = _env_float("PUMP_LAB_PHASE_DD_GREEN_LONG", 8.0)


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
# Графики объёма и OI во вкладке «Памп-скан»: грузим историю, прокрутка в UI.
PUMP_SCAN_CHART_MIN_DAYS = _env_int("PUMP_SCAN_CHART_MIN_DAYS", 7)
PUMP_SCAN_CHART_FETCH_DAYS = _env_int("PUMP_SCAN_CHART_FETCH_DAYS", 30)
BYBIT_KLINE_MAX_LIMIT = _env_int("BYBIT_KLINE_MAX_LIMIT", 1000)

_KLINE_BAR_MINUTES = {"1": 1, "5": 5, "15": 15, "30": 30, "60": 60, "240": 240, "D": 1440}
_OI_BAR_MINUTES = {"5min": 5, "15min": 15, "30min": 30, "1h": 60, "4h": 240, "1d": 1440}
CHART_TF_TO_OI_INTERVAL = {
    "1": "5min",
    "5": "5min",
    "15": "15min",
    "30": "30min",
    "60": "1h",
    "240": "4h",
    "D": "1d",
}


def kline_bars_for_days(interval: str, days: int | None = None) -> int:
    import math

    span = days if days is not None else PUMP_SCAN_CHART_FETCH_DAYS
    minutes = _KLINE_BAR_MINUTES.get(interval, 60)
    return max(10, int(math.ceil(span * 24 * 60 / minutes)))


def oi_bars_for_days(oi_interval: str, days: int | None = None) -> int:
    import math

    span = days if days is not None else PUMP_SCAN_CHART_FETCH_DAYS
    minutes = _OI_BAR_MINUTES.get(oi_interval.lower(), 5)
    return max(10, int(math.ceil(span * 24 * 60 / minutes)))


def chart_tf_to_oi_interval(chart_tf: str) -> str:
    return CHART_TF_TO_OI_INTERVAL.get(chart_tf, "5min")


# --- Вкладка «2× откат» (рост от min 5d, LH 1H/4H, OI↓, EMA) ----------------

# Мин. оборот фьючерса за 24h (turnover24h USDT). Ниже — не попадают на доску.
X2_RETRACE_MIN_TURNOVER_24H_USDT = _env_float("X2_RETRACE_MIN_TURNOVER_24H_USDT", 300_000.0)
# Рост цены за 7 календарных дней (%); отрицательный 7d — исключаем.
X2_RETRACE_MIN_PRICE_CHANGE_7D_PCT = _env_float("X2_RETRACE_MIN_PRICE_CHANGE_7D_PCT", 0.0)
# Всплеск объёма на 1H-свечах в фазе роста (от дна пампа до пика): max vol / база.
X2_RETRACE_PUMP_VOLUME_SPIKE_MIN = _env_float("X2_RETRACE_PUMP_VOLUME_SPIKE_MIN", 4.0)

X2_RETRACE_MIN_MULTIPLIER = _env_float("X2_RETRACE_MIN_MULTIPLIER", 1.72)
X2_RETRACE_LOOKBACK_DAYS = _env_int("X2_RETRACE_LOOKBACK_DAYS", 14)
X2_RETRACE_MIN_BARS = _env_int("X2_RETRACE_MIN_BARS", 8)
# Откат от абсолютного max 1H: пик 1–24 ч назад, падение не меньше этого %.
X2_RETRACE_MIN_PULLBACK_PCT = _env_float("X2_RETRACE_MIN_PULLBACK_PCT", 3.0)
X2_RETRACE_PIVOT_WING = _env_int("X2_RETRACE_PIVOT_WING", 2)
# Две вершины: минимум свечей между барами pivot-high; «один уровень» — допуск %.
X2_RETRACE_MIN_BARS_BETWEEN_PEAKS = _env_int("X2_RETRACE_MIN_BARS_BETWEEN_PEAKS", 4)
X2_RETRACE_PEAK_EQUAL_TOLERANCE_PCT = _env_float("X2_RETRACE_PEAK_EQUAL_TOLERANCE_PCT", 2.5)
# Вторая вершина чуть выше первой (failed breakout) — всё ещё «две вершины».
X2_RETRACE_MAX_SECOND_PEAK_ABOVE_PCT = _env_float("X2_RETRACE_MAX_SECOND_PEAK_ABOVE_PCT", 15.0)
# Выход с доски 2×: цена у дна пампа или текущий mult слишком мал (не «красный 24h»).
X2_RETRACE_EXIT_NEAR_VALLEY_MULT = _env_float("X2_RETRACE_EXIT_NEAR_VALLEY_MULT", 1.08)
X2_RETRACE_EXIT_MIN_CURRENT_MULT = _env_float("X2_RETRACE_EXIT_MIN_CURRENT_MULT", 1.15)
# Подтверждение смены колонки на досках и вкладке «Сигналы» (секунды).
WATCH_STAGE_CONFIRM_SEC = _env_int("WATCH_STAGE_CONFIRM_SEC", 900)
WATCH_STAGE_DOWN_CONFIRM_SEC = _env_int("WATCH_STAGE_DOWN_CONFIRM_SEC", 1200)
WATCH_STAGE_CONFIRM_MS = WATCH_STAGE_CONFIRM_SEC * 1000
WATCH_STAGE_DOWN_CONFIRM_MS = WATCH_STAGE_DOWN_CONFIRM_SEC * 1000
X2_RETRACE_COLUMNS = {
    4: {"color": "green", "status": "К ШОРТУ", "label": "4/4"},
    3: {"color": "orange", "status": "OI + EMA", "label": "3/4"},
    2: {"color": "yellow", "status": "СТРУКТУРА LH", "label": "2/4"},
    1: {"color": "blue", "status": "ПАМП 2×+", "label": "1/4"},
}


# --- Вкладка «Поиск пампов» (стратегия с чистого листа) ----------------------

PUMP_STRATEGY_MIN_TURNOVER_24H_USDT = _env_float(
    "PUMP_STRATEGY_MIN_TURNOVER_24H_USDT", 300_000.0
)
# Длинный памп: рост от минимума до максимума за окно (дней).
PUMP_STRATEGY_LONG_DAYS = _env_int("PUMP_STRATEGY_LONG_DAYS", 10)
# Верхняя цена ≥ ×2 от нижней (низ = 100%, верх минимум 200% от низа).
PUMP_STRATEGY_LONG_MIN_MULTIPLIER = _env_float("PUMP_STRATEGY_LONG_MIN_MULTIPLIER", 2.0)
PUMP_STRATEGY_LONG_MIN_PCT = _env_float(
    "PUMP_STRATEGY_LONG_MIN_PCT",
    (PUMP_STRATEGY_LONG_MIN_MULTIPLIER - 1.0) * 100.0,
)
# Быстрый памп — позже (1–12 ч, от 40%).
PUMP_STRATEGY_SHORT_HOURS_MIN = _env_int("PUMP_STRATEGY_SHORT_HOURS_MIN", 1)
PUMP_STRATEGY_SHORT_HOURS_MAX = _env_int("PUMP_STRATEGY_SHORT_HOURS_MAX", 12)
PUMP_STRATEGY_SHORT_MIN_PCT = _env_float("PUMP_STRATEGY_SHORT_MIN_PCT", 40.0)


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
