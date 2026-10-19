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
# 5m нужны баблососу и пылесосу 5 (pivot и вход).
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

# Стопы теста и пылесос. Поиск пампов и старые доски — отдельно, втрое реже.
MARKET_SCAN_INTERVAL_SEC = _env_int("MARKET_SCAN_INTERVAL_SEC", 3)
PUMP_BOARD_INTERVAL_SEC = _env_int("PUMP_BOARD_INTERVAL_SEC", 9)

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

# Трейлинг p10: расстояние стопа от лучшей цены в % цены по прибыли на маржу (ROE).
PAPER_TRAIL_START_DIST_PCT = _env_float("PAPER_TRAIL_START_DIST_PCT", 10.0)
PAPER_TRAIL_TIGHTEN_FROM_ROE = _env_float("PAPER_TRAIL_TIGHTEN_FROM_ROE", 100.0)
PAPER_TRAIL_TIGHTEN_TO_ROE = _env_float("PAPER_TRAIL_TIGHTEN_TO_ROE", 300.0)
PAPER_TRAIL_MIN_DIST_PCT = _env_float("PAPER_TRAIL_MIN_DIST_PCT", 2.0)
# Только вариант p10: после пика ROE не ниже этого стоп держит «пик − gap» п.п.
PAPER_TRAIL_PEAK_GAP_ROE = _env_float("PAPER_TRAIL_PEAK_GAP_ROE", 10.0)
# t20: пик ≥ +3% → +0.5% net, с +7% пол +5%. p10 дополнительно: ≥ +10% → +2% net.
PAPER_BE_ARM_ROE = _env_float("PAPER_BE_ARM_ROE", 3.0)
PAPER_BE_LOCK_NET_ROE = _env_float("PAPER_BE_LOCK_NET_ROE", 0.5)
PAPER_PLUS10_ARM_ROE = _env_float("PAPER_PLUS10_ARM_ROE", 10.0)
PAPER_PLUS10_LOCK_NET_ROE = _env_float("PAPER_PLUS10_LOCK_NET_ROE", 2.0)
PAPER_LOCK_ARM_ROE = _env_float("PAPER_LOCK_ARM_ROE", 7.0)
PAPER_LOCK_MIN_ROE = _env_float("PAPER_LOCK_MIN_ROE", 5.0)
PAPER_TRAIL_GAP_ROE = _env_float("PAPER_TRAIL_GAP_ROE", 20.0)
# Доп. стоп: после ухода в минус net ROE — не хуже этого уровня (оба варианта).
PAPER_LOSS_CAP_ROE = _env_float("PAPER_LOSS_CAP_ROE", -15.0)

# Памп: короткий (окно до 4 ч / 24 ч по 15m), длинный (7 д / 14 д по 4H).
PAPER_SHORT_4H_MIN_PCT = _env_float("PAPER_SHORT_4H_MIN_PCT", 30.0)
PAPER_SHORT_24H_MIN_PCT = _env_float("PAPER_SHORT_24H_MIN_PCT", 50.0)
PAPER_LONG_7D_MIN_PCT = _env_float("PAPER_LONG_7D_MIN_PCT", 80.0)
PAPER_LONG_14D_MIN_PCT = _env_float("PAPER_LONG_14D_MIN_PCT", 100.0)
# Множитель порогов роста пампа для t20/p10 (1.0 = базовые PAPER_SHORT_* / PAPER_LONG_*).
PAPER_PUMP_FLOOR_SCALE = _env_float("PAPER_PUMP_FLOOR_SCALE", 0.8)
# Доп. шлюз t20/p10: без stall — не входить при позднем/глубоком/7d профиле.
PAPER_TRI_NO_STALL_SINCE_PEAK_MIN = _env_float("PAPER_TRI_NO_STALL_SINCE_PEAK_MIN", 90.0)
PAPER_TRI_NO_STALL_DRAWDOWN_PCT = _env_float("PAPER_TRI_NO_STALL_DRAWDOWN_PCT", 11.0)
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
# Фон 5м для пылесоса: реже и короче, чем свечи кандидатов теста.
PAPER_FIVE_MIN_REFRESH_SEC = _env_int("PAPER_FIVE_MIN_REFRESH_SEC", 180)
PAPER_FIVE_MIN_FETCH_LIMIT = _env_int("PAPER_FIVE_MIN_FETCH_LIMIT", 120)
# Полный разбор pivot только в эти миллисекунды после закрытия 5м.
# Вспышка подтверждения считает pivot сразу, без этого окна.
PAPER_PIVOT_EVAL_WINDOW_MS = _env_int("PAPER_PIVOT_EVAL_WINDOW_MS", 20_000)

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

# Бумажные варианты: шорты t20/p10/mln (шлюз + 5 из 9),
# копии t20p/p10p/mlnp — тот же выход, но обязательный вход (не 5 из 9),
# лонг lt20 (детектор роста),
# Курсор СС 2 (css2) — вход по развороту лаборатории,
# шорты e5s / e5p — тот же поиск пампа, вход по EMA50 5м.
# Курсор3 (c3) — тот же поиск пампа и выход Трейл 20, вход из восьми обязательных пунктов.
# Cursor SS (css) с вкладки снят: новые сделки не открываются.
PAPER_SHORT_VARIANTS = ("t20", "p10")
PAPER_PLUS_VARIANTS = ("t20p", "mlnp")
# Активные счета: баланс на VPS > $1000 (2026-10-16). Остальное снято с вкладки.
PAPER_VARIANTS = ("t20", "p10", "t20p", "mlnp", "mt2", "graf", "pyl", "333", "33315", "vps15")
# Стол во вкладке «Пылесос»: бумага крутится здесь, в тесте стратегии скрыты.
PAPER_DESK_VARIANTS = ("pyl", "333", "33315", "vps15")
PAPER_T20_VARIANT = "t20"
PAPER_P10_VARIANT = "p10"
PAPER_MLN_VARIANT = "mln"
PAPER_T20P_VARIANT = "t20p"
PAPER_P10P_VARIANT = "p10p"
PAPER_MLNP_VARIANT = "mlnp"
PAPER_LT20_VARIANT = "lt20"
PAPER_CSS_VARIANT = "css"
PAPER_CSS2_VARIANT = "css2"
PAPER_SC10_VARIANT = "sc10"
PAPER_E5S_VARIANT = "e5s"
PAPER_E5P_VARIANT = "e5p"
PAPER_C3_VARIANT = "c3"
PAPER_MT1_VARIANT = "mt1"
PAPER_MT2_VARIANT = "mt2"
PAPER_MT2C_VARIANT = "mt2c"
PAPER_GRAF_VARIANT = "graf"
PAPER_DPS_VARIANT = "dps"
PAPER_MINI_VARIANTS = (PAPER_MT2_VARIANT,)
PAPER_GRAF_PIVOT_WING = _env_int("PAPER_GRAF_PIVOT_WING", 1)

# Дип сик (DeepSeek paper): пороги входа; нет данных — пункт не блокирует.
PAPER_DPS_RSI_PERIOD = _env_int("PAPER_DPS_RSI_PERIOD", 7)
PAPER_DPS_RSI_CROSS = _env_float("PAPER_DPS_RSI_CROSS", 70.0)
PAPER_DPS_RSI_1H_MIN = _env_float("PAPER_DPS_RSI_1H_MIN", 70.0)
PAPER_DPS_RSI_15M_MIN = _env_float("PAPER_DPS_RSI_15M_MIN", 35.0)
PAPER_DPS_OI_24H_MIN = _env_float("PAPER_DPS_OI_24H_MIN", 5.0)
PAPER_DPS_OI_1H_MIN = _env_float("PAPER_DPS_OI_1H_MIN", 2.0)
PAPER_DPS_FUNDING_MIN = _env_float("PAPER_DPS_FUNDING_MIN", 0.001)
PAPER_DPS_BOOK_IMBALANCE_MAX = _env_float("PAPER_DPS_BOOK_IMBALANCE_MAX", -0.2)
PAPER_DPS_ASK_BID_MIN = _env_float("PAPER_DPS_ASK_BID_MIN", 1.5)
PAPER_DPS_VOL_FADE_RATIO = _env_float("PAPER_DPS_VOL_FADE_RATIO", 0.5)
PAPER_DPS_VOL_SPIKE_MIN = _env_float("PAPER_DPS_VOL_SPIKE_MIN", 2.0)
PAPER_DPS_DROP_FROM_4H_HIGH_PCT = _env_float("PAPER_DPS_DROP_FROM_4H_HIGH_PCT", 8.0)
PAPER_DPS_LIQ_ZONE_MIN_PCT = _env_float("PAPER_DPS_LIQ_ZONE_MIN_PCT", 5.0)
PAPER_DPS_LIQ_ZONE_MAX_PCT = _env_float("PAPER_DPS_LIQ_ZONE_MAX_PCT", 10.0)
PAPER_DPS_MIN_TURNOVER = _env_float("PAPER_DPS_MIN_TURNOVER", 10_000_000.0)
PAPER_DPS_COOLDOWN_SEC = _env_int("PAPER_DPS_COOLDOWN_SEC", 90 * 60)
PAPER_DPS_MAX_OPEN = _env_int("PAPER_DPS_MAX_OPEN", 3)

# БАБЛОСОС $$$ (pyl): M5 pivot как LH-скан; стоп ±5% ROE от high/low свечи pivot.
# Вход и закрытие по противоположному pivot — не позже 10 с после закрытия второй свечи.
PAPER_PYL_VARIANT = "pyl"
PAPER_PYL1_VARIANT = "pyl1"
PAPER_PYL_INTERVAL = "5"
PAPER_PYL_STOP_ROE = _env_float("PAPER_PYL_STOP_ROE", 5.0)
# БАБЛОСОС 1: только монеты с размахом цены за час ≥ этого порога (%).
PAPER_PYL1_HOUR_RANGE_PCT = _env_float("PAPER_PYL1_HOUR_RANGE_PCT", 2.0)
# 333: как БАБЛОСОС + не узкий боковик + EMA20/60 (тренд вниз→шорт, вверх→лонг).
PAPER_333_VARIANT = "333"
PAPER_333_MA_FAST = _env_int("PAPER_333_MA_FAST", 20)
PAPER_333_MA_SLOW = _env_int("PAPER_333_MA_SLOW", 60)
# Наклон EMA20/EMA60: сравнение текущего значения с тем же EMA N свечей назад (5m).
PAPER_333_MA_SLOPE_BARS = _env_int("PAPER_333_MA_SLOPE_BARS", 60)
PAPER_333_MA_SLOPE_MIN_PCT = _env_float("PAPER_333_MA_SLOPE_MIN_PCT", 0.7)
# Зона входа у EMA60: лонг EMA…EMA+1%, шорт EMA−1%…EMA; мёртвая зона 1–4%; отрыв >4% — stretch.
PAPER_333_MA_BAND_PCT = _env_float("PAPER_333_MA_BAND_PCT", 1.0)
PAPER_333_MA_STRETCH_PCT = _env_float("PAPER_333_MA_STRETCH_PCT", 4.0)
PAPER_333_TRAIL_ARM_ROE = _env_float("PAPER_333_TRAIL_ARM_ROE", 5.0)
PAPER_333_TRAIL_LOCK_NET_ROE = _env_float("PAPER_333_TRAIL_LOCK_NET_ROE", 0.5)
PAPER_333_LOCK5_ARM_ROE = _env_float("PAPER_333_LOCK5_ARM_ROE", 10.0)
PAPER_333_LOCK5_ROE = _env_float("PAPER_333_LOCK5_ROE", 5.0)
PAPER_333_LOCK10_ARM_ROE = _env_float("PAPER_333_LOCK10_ARM_ROE", 14.0)
PAPER_333_LOCK10_ROE = _env_float("PAPER_333_LOCK10_ROE", 10.0)
PAPER_333_TRAIL_GAP_ROE = _env_float("PAPER_333_TRAIL_GAP_ROE", 15.0)
PAPER_333_LOSS_STOP_COOLDOWN_MIN = _env_int("PAPER_333_LOSS_STOP_COOLDOWN_MIN", 45)
PAPER_33315_VARIANT = "33315"
PAPER_33315_INTERVAL = "15"


def paper_333_family_variants() -> tuple[str, ...]:
    return (PAPER_333_VARIANT, PAPER_33315_VARIANT)


def is_paper_333_family(variant: str) -> bool:
    return variant in paper_333_family_variants()
PAPER_CHOP_WINDOW_BARS = _env_int("PAPER_CHOP_WINDOW_BARS", 20)
PAPER_CHOP_MIN_BARS = _env_int("PAPER_CHOP_MIN_BARS", 10)
PAPER_CHOP_TIGHT_RANGE_PCT = _env_float("PAPER_CHOP_TIGHT_RANGE_PCT", 1.5)
PAPER_CHOP_MIN_WIDE_RANGE_PCT = _env_float("PAPER_CHOP_MIN_WIDE_RANGE_PCT", 3.5)
PAPER_CHOP_TIGHT_BAR_RATIO = _env_float("PAPER_CHOP_TIGHT_BAR_RATIO", 4.0)
PAPER_PIVOT_CONFIRM_SLACK_MS = _env_int("PAPER_PIVOT_CONFIRM_SLACK_MS", 10_000)
# Пылесос 15: окно закрытия по противоп. pivot (вход по-прежнему 10 с).
PAPER_VPS15_EXIT_CONFIRM_SLACK_MS = _env_int("PAPER_VPS15_EXIT_CONFIRM_SLACK_MS", 120_000)
PAPER_PIVOT_CONFIRM_FETCH_LIMIT = _env_int("PAPER_PIVOT_CONFIRM_FETCH_LIMIT", 8)
PAPER_PIVOT_CONFIRM_PARALLEL = _env_int("PAPER_PIVOT_CONFIRM_PARALLEL", 8)
# vac — прежний трейл pyl (не путать с bab):
PAPER_PYL_INITIAL_STOP_ROE = _env_float("PAPER_PYL_INITIAL_STOP_ROE", -10.0)
PAPER_PYL_LOSS_CAP_ROE = _env_float("PAPER_PYL_LOSS_CAP_ROE", -10.0)
PAPER_PYL_TRAIL_ARM_ROE = _env_float("PAPER_PYL_TRAIL_ARM_ROE", 10.0)
PAPER_PYL_TRAIL_GAP_ROE = _env_float("PAPER_PYL_TRAIL_GAP_ROE", 5.0)

# Пылесос (vac): A→C→B на 5m (pivot wing=1), 2 медвежьих B и +1, выход как pyl.
PAPER_VAC_VARIANT = "vac"
PAPER_VAC_SWING_WING = _env_int("PAPER_VAC_SWING_WING", 1)
PAPER_VAC_LOOKBACK_BARS = _env_int("PAPER_VAC_LOOKBACK_BARS", 240)

# Пылесос 15 / 5: сразу −15% net, дальше ступени Трейл 20 (+3%→+0.5% net, +7%→+5%, трейл 20 п.п.).
PAPER_VPS15_VARIANT = "vps15"
PAPER_VPS5_VARIANT = "vps5"
PAPER_VPS_VARIANTS = (PAPER_VPS15_VARIANT,)
PAPER_VPS15_INTERVAL = "15"
# Пылесос 15: вход после 1-й закрытой 15m справа (график LH — по-прежнему 2 справа).
PAPER_VPS15_ENTRY_PIVOT_RIGHT = _env_int("PAPER_VPS15_ENTRY_PIVOT_RIGHT", 1)
PAPER_VPS5_INTERVAL = "5"
PAPER_VPS_INITIAL_STOP_ROE = _env_float("PAPER_VPS_INITIAL_STOP_ROE", -15.0)

PAPER_V5_MIN_PASSED = _env_int("PAPER_V5_MIN_PASSED", 5)
PAPER_DT_MIN_PASSED = _env_int("PAPER_DT_MIN_PASSED", 3)

# Жёсткий шлюз входа (t20, p10, mln и копии на том же шлюзе).
PAPER_ENTRY_SINCE_PEAK_MIN = _env_float("PAPER_ENTRY_SINCE_PEAK_MIN", 6.0)
PAPER_ENTRY_SINCE_PEAK_MAX = _env_float("PAPER_ENTRY_SINCE_PEAK_MAX", 180.0)
PAPER_ENTRY_LATE_MIN = _env_float("PAPER_ENTRY_LATE_MIN", 60.0)
PAPER_ENTRY_MEGAVOL_RATIO = _env_float("PAPER_ENTRY_MEGAVOL_RATIO", 80.0)
# Не шортить, если цена уже ушла от пика пампа дальше этого отката.
PAPER_ENTRY_MAX_DRAWDOWN_PCT = _env_float("PAPER_ENTRY_MAX_DRAWDOWN_PCT", 12.0)
# После PAPER_ENTRY_SINCE_PEAK_MAX (180 мин): вход разрешён, если все условия «позднего» шлюза.
PAPER_ENTRY_LATE_EXT_MAX_DRAWDOWN_PCT = _env_float("PAPER_ENTRY_LATE_EXT_MAX_DRAWDOWN_PCT", 30.0)
PAPER_ENTRY_LATE_EXT_SELL_SHARE_MIN_PCT = _env_float("PAPER_ENTRY_LATE_EXT_SELL_SHARE_MIN_PCT", 60.0)
PAPER_ENTRY_LATE_EXT_SELL_WINDOWS_REQUIRED = _env_int("PAPER_ENTRY_LATE_EXT_SELL_WINDOWS_REQUIRED", 2)

# Копии t20p/p10p/mlnp: все пункты обязательны, «5 из 9» и покупки ≥70% не используются.
PAPER_PLUS_NO_HIGH_BARS = _env_int("PAPER_PLUS_NO_HIGH_BARS", 7)
PAPER_PLUS_SELL_SHARE_MIN_PCT = _env_float("PAPER_PLUS_SELL_SHARE_MIN_PCT", 55.0)
PAPER_PLUS_LATE_SINCE_MIN = _env_float("PAPER_PLUS_LATE_SINCE_MIN", 180.0)
PAPER_PLUS_LATE_MAX_DD_PCT = _env_float("PAPER_PLUS_LATE_MAX_DD_PCT", 15.0)

# Курсор3: все восемь пунктов обязательны, «5 из 9» и поздний шлюз не используются.
# Выход — как у t20 (paper_stop_style default, без пик−10).
PAPER_C3_SINCE_PEAK_MIN = _env_float("PAPER_C3_SINCE_PEAK_MIN", 6.0)
PAPER_C3_SINCE_PEAK_MAX = _env_float("PAPER_C3_SINCE_PEAK_MAX", 180.0)
PAPER_C3_MAX_DRAWDOWN_PCT = _env_float("PAPER_C3_MAX_DRAWDOWN_PCT", 10.0)
PAPER_C3_MIN_PRICE_20M_PCT = _env_float("PAPER_C3_MIN_PRICE_20M_PCT", 0.0)
PAPER_C3_LONG_LIQ_MAX_USD = _env_float("PAPER_C3_LONG_LIQ_MAX_USD", 200.0)
PAPER_C3_MAX_SCORE = _env_float("PAPER_C3_MAX_SCORE", 12.0)
PAPER_C3_TRIGGERS = ("4h", "24h")

# Мини тест 1 / 2: пороги роста пампа на 40% ниже образцов. Выход mt1 как t20, mt2 как p10.
PAPER_MINI_PUMP_SCALE = _env_float("PAPER_MINI_PUMP_SCALE", 0.6)
PAPER_MINI_SINCE_PEAK_MIN = _env_float("PAPER_MINI_SINCE_PEAK_MIN", 6.0)
PAPER_MINI_SINCE_PEAK_MAX = _env_float("PAPER_MINI_SINCE_PEAK_MAX", 180.0)
PAPER_MINI_MAX_DRAWDOWN_PCT = _env_float("PAPER_MINI_MAX_DRAWDOWN_PCT", 10.0)
PAPER_MINI_MAX_SCORE = _env_float("PAPER_MINI_MAX_SCORE", 12.0)
PAPER_MINI_TRIGGERS = ("4h", "24h")

# Импульс 5 / Импульс 15: закрытая свеча своего таймфрейма, выход как у t20.
PAPER_IMP5_VARIANT = "i5"
PAPER_IMP15_VARIANT = "i15"
PAPER_IMPULSE_VARIANTS = (PAPER_IMP5_VARIANT, PAPER_IMP15_VARIANT)
PAPER_IMPULSE_VOLUME_MIN_RATIO = _env_float("PAPER_IMPULSE_VOLUME_MIN_RATIO", 3.0)
PAPER_IMPULSE_FLOW_MIN_PCT = _env_float("PAPER_IMPULSE_FLOW_MIN_PCT", 60.0)
# Импульс 5: фильтры входа, чтобы чаще дойти до первого лока t20 (+3% ROE).
PAPER_IMP5_MIN_BODY_PCT = _env_float("PAPER_IMP5_MIN_BODY_PCT", 0.25)
PAPER_IMP5_CLOSE_EDGE_MAX = _env_float("PAPER_IMP5_CLOSE_EDGE_MAX", 0.35)
PAPER_IMP5_MAX_SNAPBACK_PCT = _env_float("PAPER_IMP5_MAX_SNAPBACK_PCT", 0.08)


def paper_is_long(variant: str) -> bool:
    return variant == PAPER_LT20_VARIANT


def paper_stop_style(variant: str) -> str:
    if variant == PAPER_CSS_VARIANT:
        return "css"
    if variant == PAPER_CSS2_VARIANT:
        return "css2"
    if variant == PAPER_SC10_VARIANT:
        return "sc10"
    if variant == PAPER_E5S_VARIANT:
        return "e5s"
    if variant == PAPER_E5P_VARIANT:
        return "e5p"
    if variant in (PAPER_MLN_VARIANT, PAPER_MLNP_VARIANT):
        return "mln"
    if variant in PAPER_IMPULSE_VARIANTS:
        return "impulse"
    if variant == PAPER_PYL_VARIANT:
        return "bab"
    if is_paper_333_family(variant):
        return "333"
    if variant == PAPER_VAC_VARIANT:
        return "pyl"
    if variant in PAPER_VPS_VARIANTS:
        return "vps"
    return "default"


def paper_peak_gap_roe(variant: str) -> float:
    """Лок «пик − gap» у p10 и копии 10 п.п.+; t20/lt20 — свои правила ROE."""
    if variant in (PAPER_P10_VARIANT, PAPER_P10P_VARIANT, PAPER_MT2_VARIANT, PAPER_MT2C_VARIANT):
        return PAPER_TRAIL_PEAK_GAP_ROE
    return 0.0


# Лонг lt20: −10% → BE в плюсе → +10% лок +5% → трейл 20 п.п.
PAPER_LONG_INITIAL_STOP_ROE = _env_float("PAPER_LONG_INITIAL_STOP_ROE", -10.0)
PAPER_LONG_LOCK_ARM_ROE = _env_float("PAPER_LONG_LOCK_ARM_ROE", 10.0)
PAPER_LONG_LOCK_MIN_ROE = _env_float("PAPER_LONG_LOCK_MIN_ROE", 5.0)
PAPER_LONG_TRAIL_GAP_ROE = _env_float("PAPER_LONG_TRAIL_GAP_ROE", 20.0)

# Детектор роста (кандидаты lt20).
PAPER_GROWTH_DETECT_HOURS = _env_int("PAPER_GROWTH_DETECT_HOURS", 12)
PAPER_GROWTH_MIN_RALLY_PCT = _env_float("PAPER_GROWTH_MIN_RALLY_PCT", 4.0)
PAPER_GROWTH_MAX_PULLBACK_PCT = _env_float("PAPER_GROWTH_MAX_PULLBACK_PCT", 25.0)
PAPER_GROWTH_BUY_SHARE_MIN = _env_float("PAPER_GROWTH_BUY_SHARE_MIN", 52.0)
PAPER_GROWTH_BUY_SHARE_TURBO = _env_float("PAPER_GROWTH_BUY_SHARE_TURBO", 68.0)
PAPER_GROWTH_VOL_GROWTH_MIN_PCT = _env_float("PAPER_GROWTH_VOL_GROWTH_MIN_PCT", 10.0)
PAPER_GROWTH_TURBO_VOL_RATIO = _env_float("PAPER_GROWTH_TURBO_VOL_RATIO", 2.5)
PAPER_GROWTH_SWING_WING = _env_int("PAPER_GROWTH_SWING_WING", 2)
PAPER_GROWTH_SWING_LOOKBACK_BARS = _env_int("PAPER_GROWTH_SWING_LOOKBACK_BARS", 200)
PAPER_GROWTH_STRUCTURE_HOURS = _env_int("PAPER_GROWTH_STRUCTURE_HOURS", 12)
PAPER_GROWTH_MIN_HH_COUNT = _env_int("PAPER_GROWTH_MIN_HH_COUNT", 2)
PAPER_GROWTH_PREFER_HH_COUNT = _env_int("PAPER_GROWTH_PREFER_HH_COUNT", 3)
PAPER_GROWTH_PULLBACK_MIN_PCT = _env_float("PAPER_GROWTH_PULLBACK_MIN_PCT", 1.0)
PAPER_GROWTH_PULLBACK_MAX_PCT = _env_float("PAPER_GROWTH_PULLBACK_MAX_PCT", 8.0)
PAPER_GROWTH_FLEX_MIN = _env_int("PAPER_GROWTH_FLEX_MIN", 3)
PAPER_GROWTH_EMA_KEYS = ("15m_EMA50", "1H_EMA50")

# Cursor SS (css): быстрый памп → затихание → вход на дампе.
PAPER_CSS_MIN_GROWTH_PCT = _env_float("PAPER_CSS_MIN_GROWTH_PCT", 12.0)
PAPER_CSS_MAX_LEG_HOURS = _env_float("PAPER_CSS_MAX_LEG_HOURS", 6.0)
PAPER_CSS_LOOKBACK_HOURS = _env_float("PAPER_CSS_LOOKBACK_HOURS", 12.0)
PAPER_CSS_LIFETIME_HOURS = _env_float("PAPER_CSS_LIFETIME_HOURS", 12.0)
PAPER_CSS_MAX_DRAWDOWN_PCT = _env_float("PAPER_CSS_MAX_DRAWDOWN_PCT", 25.0)
PAPER_CSS_VOLUME_MIN_RATIO = _env_float("PAPER_CSS_VOLUME_MIN_RATIO", 4.0)
PAPER_CSS_BUY_SHARE_MIN_PCT = _env_float("PAPER_CSS_BUY_SHARE_MIN_PCT", 55.0)
PAPER_CSS_TAPE_MIN_MINUTES = _env_int("PAPER_CSS_TAPE_MIN_MINUTES", 15)
PAPER_CSS_QUIET_MIN_MINUTES = _env_float("PAPER_CSS_QUIET_MIN_MINUTES", 8.0)
PAPER_CSS_VOLUME_FADE_MAX_RATIO = _env_float("PAPER_CSS_VOLUME_FADE_MAX_RATIO", 0.7)
PAPER_CSS_DUMP_EXCLUDE_MIN = _env_int("PAPER_CSS_DUMP_EXCLUDE_MIN", 5)
PAPER_CSS_SELL_SHARE_MIN_PCT = _env_float("PAPER_CSS_SELL_SHARE_MIN_PCT", 52.0)
PAPER_CSS_INITIAL_STOP_ROE = _env_float("PAPER_CSS_INITIAL_STOP_ROE", -15.0)
PAPER_CSS_BE_ARM_ROE = _env_float("PAPER_CSS_BE_ARM_ROE", 10.0)
PAPER_CSS_TRAIL_GAP_ROE = _env_float("PAPER_CSS_TRAIL_GAP_ROE", 20.0)
PAPER_CSS_MAX_ENTRIES = _env_int("PAPER_CSS_MAX_ENTRIES", 3)

# Курсор СС 2: быстрый памп ≥40% за ≤6 ч, вход на откате 5–8% после разворота.
PAPER_CSS2_MIN_GROWTH_PCT = _env_float("PAPER_CSS2_MIN_GROWTH_PCT", 40.0)
PAPER_CSS2_MAX_LEG_HOURS = _env_float("PAPER_CSS2_MAX_LEG_HOURS", 6.0)
PAPER_CSS2_LOOKBACK_HOURS = _env_float("PAPER_CSS2_LOOKBACK_HOURS", 12.0)
PAPER_CSS2_MIN_TURNOVER_USDT = _env_float("PAPER_CSS2_MIN_TURNOVER_USDT", 1_000_000.0)
PAPER_CSS2_SINCE_PEAK_MIN = _env_float("PAPER_CSS2_SINCE_PEAK_MIN", 20.0)
PAPER_CSS2_SINCE_PEAK_MAX = _env_float("PAPER_CSS2_SINCE_PEAK_MAX", 180.0)
PAPER_CSS2_DD_MIN_PCT = _env_float("PAPER_CSS2_DD_MIN_PCT", 5.0)
PAPER_CSS2_DD_MAX_PCT = _env_float("PAPER_CSS2_DD_MAX_PCT", 8.0)
PAPER_CSS2_WATCH_MAX_DD_PCT = _env_float("PAPER_CSS2_WATCH_MAX_DD_PCT", 25.0)
PAPER_CSS2_LATE_MIN = _env_float("PAPER_CSS2_LATE_MIN", 60.0)
PAPER_CSS2_MEGAVOL_RATIO = _env_float("PAPER_CSS2_MEGAVOL_RATIO", 80.0)
PAPER_CSS2_BUY_SHARE_5M_MAX = _env_float("PAPER_CSS2_BUY_SHARE_5M_MAX", 45.0)
PAPER_CSS2_SELL_SHARE_MIN_PCT = _env_float("PAPER_CSS2_SELL_SHARE_MIN_PCT", 50.0)
PAPER_CSS2_OI_1H_MAX_PCT = _env_float("PAPER_CSS2_OI_1H_MAX_PCT", 1.0)
PAPER_CSS2_SHORT_LIQ_MAX_RATIO = _env_float("PAPER_CSS2_SHORT_LIQ_MAX_RATIO", 0.15)
PAPER_CSS2_STOP_ROE = _env_float("PAPER_CSS2_STOP_ROE", -60.0)
PAPER_CSS2_BE_ARM_ROE = _env_float("PAPER_CSS2_BE_ARM_ROE", 50.0)
PAPER_CSS2_HALF_DD_PCT = _env_float("PAPER_CSS2_HALF_DD_PCT", 15.0)
PAPER_CSS2_TARGET_DD_PCT = _env_float("PAPER_CSS2_TARGET_DD_PCT", 20.0)
PAPER_CSS2_LOCK_ROE = _env_float("PAPER_CSS2_LOCK_ROE", 50.0)
PAPER_CSS2_TIME_FLAT_MIN = _env_float("PAPER_CSS2_TIME_FLAT_MIN", 120.0)
PAPER_CSS2_TIME_FLAT_BAND_PCT = _env_float("PAPER_CSS2_TIME_FLAT_BAND_PCT", 2.0)

# Скальп sc10: старт хода 1м, лонг и шорт, трейл 10% ROE с входа.
PAPER_SC10_RANGE_BARS = _env_int("PAPER_SC10_RANGE_BARS", 15)
PAPER_SC10_VOLUME_BARS = _env_int("PAPER_SC10_VOLUME_BARS", 20)
PAPER_SC10_VOLUME_MIN_RATIO = _env_float("PAPER_SC10_VOLUME_MIN_RATIO", 3.0)
PAPER_SC10_VOL_DOMINATE_BARS = _env_int("PAPER_SC10_VOL_DOMINATE_BARS", 3)
PAPER_SC10_TAKER_SHARE_MIN_PCT = _env_float("PAPER_SC10_TAKER_SHARE_MIN_PCT", 68.0)
PAPER_SC10_TAKER_MINUTES = _env_int("PAPER_SC10_TAKER_MINUTES", 3)
PAPER_SC10_OI_LOOKBACK_MIN = _env_int("PAPER_SC10_OI_LOOKBACK_MIN", 15)
PAPER_SC10_OI_MIN_PCT = _env_float("PAPER_SC10_OI_MIN_PCT", 0.25)
PAPER_SC10_BTC_MINUTES = _env_int("PAPER_SC10_BTC_MINUTES", 5)
PAPER_SC10_BTC_AGAINST_PCT = _env_float("PAPER_SC10_BTC_AGAINST_PCT", 0.15)
PAPER_SC10_BODY_MIN_RATIO = _env_float("PAPER_SC10_BODY_MIN_RATIO", 0.62)
PAPER_SC10_BREAK_MIN_PCT = _env_float("PAPER_SC10_BREAK_MIN_PCT", 0.15)
PAPER_SC10_TRAIL_GAP_ROE = _env_float("PAPER_SC10_TRAIL_GAP_ROE", 10.0)
PAPER_SC10_REENTRY_SEC = _env_int("PAPER_SC10_REENTRY_SEC", 120)

# Шорты e5s / e5p: тот же поиск пампа, вход — закрытая 5м под EMA50.
# e5s: −20% → с +5% лок +1% net → с +10% стоп +5% и трейл пик − 20 п.п., не ниже +5%.
# e5p: те же −20% и лок +1% net с +5%, сразу после лока трейл пик − 3 п.п. ROE.
PAPER_E5S_EMA_PERIOD = _env_int("PAPER_E5S_EMA_PERIOD", 50)
PAPER_E5S_SELL_SHARE_MIN_PCT = _env_float("PAPER_E5S_SELL_SHARE_MIN_PCT", 60.0)
PAPER_E5S_PEAK_BARS_5M = _env_int("PAPER_E5S_PEAK_BARS_5M", 5)
PAPER_E5S_INITIAL_STOP_ROE = _env_float("PAPER_E5S_INITIAL_STOP_ROE", -20.0)
PAPER_E5S_PLUS5_ARM_ROE = _env_float("PAPER_E5S_PLUS5_ARM_ROE", 5.0)
PAPER_E5S_PLUS5_LOCK_NET_ROE = _env_float("PAPER_E5S_PLUS5_LOCK_NET_ROE", 1.0)
PAPER_E5S_BE_ARM_ROE = _env_float("PAPER_E5S_BE_ARM_ROE", 10.0)
PAPER_E5S_PLUS10_LOCK_ROE = _env_float("PAPER_E5S_PLUS10_LOCK_ROE", 5.0)
PAPER_E5S_TRAIL_GAP_ROE = _env_float("PAPER_E5S_TRAIL_GAP_ROE", 20.0)
PAPER_E5P_TRAIL_GAP_ROE = _env_float("PAPER_E5P_TRAIL_GAP_ROE", 3.0)

# Молния: −10% ROE, +2.5%→+2%, +6%→+4%, +7%→+5%, дальше трейл пик − 20 п.п. как в ТЗ.
PAPER_MLN_INITIAL_STOP_ROE = _env_float("PAPER_MLN_INITIAL_STOP_ROE", -10.0)
PAPER_MLN_LOCK2_ARM_ROE = _env_float("PAPER_MLN_LOCK2_ARM_ROE", 2.5)
PAPER_MLN_LOCK2_ROE = _env_float("PAPER_MLN_LOCK2_ROE", 2.0)
PAPER_MLN_LOCK4_ARM_ROE = _env_float("PAPER_MLN_LOCK4_ARM_ROE", 6.0)
PAPER_MLN_LOCK4_ROE = _env_float("PAPER_MLN_LOCK4_ROE", 4.0)
PAPER_MLN_LOCK5_ARM_ROE = _env_float("PAPER_MLN_LOCK5_ARM_ROE", 7.0)
PAPER_MLN_LOCK5_ROE = _env_float("PAPER_MLN_LOCK5_ROE", 5.0)
PAPER_MLN_TRAIL_GAP_ROE = _env_float("PAPER_MLN_TRAIL_GAP_ROE", 20.0)

# После перезапуска свечи в памяти не сразу полные: кандидата не снимаем
# «по условиям пампа», пока не прошло столько минут и не набралась история.
PAPER_STARTUP_GRACE_MIN = _env_int("PAPER_STARTUP_GRACE_MIN", 15)
PAPER_READY_15M_BARS = _env_int("PAPER_READY_15M_BARS", 96)
PAPER_READY_4H_BARS = _env_int("PAPER_READY_4H_BARS", 84)

# Круглый уровень (0.5, 1, 5, 10…): пик или диапазон в пределах этого % от уровня.
PAPER_ROUND_LEVEL_NEAR_PCT = _env_float("PAPER_ROUND_LEVEL_NEAR_PCT", 1.5)

PAPER_DETECT_INTERVAL_SEC = _env_int("PAPER_DETECT_INTERVAL_SEC", 90)
PAPER_PERSIST_INTERVAL_SEC = _env_int("PAPER_PERSIST_INTERVAL_SEC", 15)
PAPER_EQUITY_SNAPSHOT_SEC = _env_int("PAPER_EQUITY_SNAPSHOT_SEC", 300)

# --- Единый детект пампа (лаборатория + памп-скан + 2× + поиск) ------------

PUMP_UNIFIED_MIN_TURNOVER_USDT = _env_float("PUMP_UNIFIED_MIN_TURNOVER_USDT", 300_000.0)
PUMP_UNIFIED_MIN_24H_PCT = _env_float("PUMP_UNIFIED_MIN_24H_PCT", 35.0)
PUMP_UNIFIED_MIN_MULTIPLIER = _env_float("PUMP_UNIFIED_MIN_MULTIPLIER", 1.72)
PUMP_UNIFIED_VOLUME_RELAXED = _env_float("PUMP_UNIFIED_VOLUME_RELAXED", 4.0)
PUMP_UNIFIED_ALLOW_WITHOUT_VOLUME = _env("PUMP_UNIFIED_ALLOW_WITHOUT_VOLUME", "0").strip() in (
    "1",
    "true",
    "True",
    "yes",
)
# Снять карточку с досок и из лаборатории, когда откат от пика ≥ этого %.
PUMP_UNIFIED_MAX_DRAWDOWN_PCT = _env_float("PUMP_UNIFIED_MAX_DRAWDOWN_PCT", 50.0)
PUMP_UNIFIED_GROWTH_MIN_FAST = _env_float("PUMP_UNIFIED_GROWTH_MIN_FAST", 40.0)
PUMP_UNIFIED_GROWTH_MIN_MEDIUM = _env_float("PUMP_UNIFIED_GROWTH_MIN_MEDIUM", 60.0)
PUMP_UNIFIED_GROWTH_MIN_LONG = _env_float("PUMP_UNIFIED_GROWTH_MIN_LONG", 100.0)
PUMP_UNIFIED_VOLUME_MIN_FAST = _env_float("PUMP_UNIFIED_VOLUME_MIN_FAST", 10.0)
PUMP_UNIFIED_VOLUME_MIN_MEDIUM = _env_float("PUMP_UNIFIED_VOLUME_MIN_MEDIUM", 20.0)
PUMP_UNIFIED_VOLUME_MIN_LONG = _env_float("PUMP_UNIFIED_VOLUME_MIN_LONG", 10.0)
PUMP_UNIFIED_MAX_AGE_DAYS = _env_int("PUMP_UNIFIED_MAX_AGE_DAYS", 20)
PUMP_UNIFIED_WINDOW_HOURS_FAST = _env_int("PUMP_UNIFIED_WINDOW_HOURS_FAST", 6)
PUMP_UNIFIED_WINDOW_DAYS_MEDIUM = _env_int("PUMP_UNIFIED_WINDOW_DAYS_MEDIUM", 2)
PUMP_UNIFIED_MEDIUM_MAX_MS = _env_int("PUMP_UNIFIED_MEDIUM_MAX_MS", 2 * 24 * 3_600_000)

# --- Лаборатория пампа (вкладка «Анализ пампа») ------------------------------

PUMP_LAB_SQLITE_PATH = Path(_env("PUMP_LAB_SQLITE_PATH", str(DATA_DIR / "pump_lab.db")))
PUMP_LAB_SCAN_INTERVAL_SEC = _env_int("PUMP_LAB_SCAN_INTERVAL_SEC", 300)
PUMP_LAB_SNAPSHOT_INTERVAL_SEC = _env_int("PUMP_LAB_SNAPSHOT_INTERVAL_SEC", 300)
PUMP_LAB_HISTORY_POINTS = _env_int("PUMP_LAB_HISTORY_POINTS", 48)
PUMP_LAB_MAX_DRAWDOWN_PCT = _env_float("PUMP_LAB_MAX_DRAWDOWN_PCT", 50.0)
# Минимальный рост дно→пик по классу пампа (%).
PUMP_LAB_GROWTH_MIN_FAST = _env_float("PUMP_LAB_GROWTH_MIN_FAST", 40.0)
PUMP_LAB_GROWTH_MIN_MEDIUM = _env_float("PUMP_LAB_GROWTH_MIN_MEDIUM", 60.0)
PUMP_LAB_GROWTH_MIN_LONG = _env_float("PUMP_LAB_GROWTH_MIN_LONG", 100.0)
# Сумма объёма дно→пик / сумма за такой же интервал до дна.
PUMP_LAB_VOLUME_MIN_FAST = _env_float("PUMP_LAB_VOLUME_MIN_FAST", 10.0)
PUMP_LAB_VOLUME_MIN_MEDIUM = _env_float("PUMP_LAB_VOLUME_MIN_MEDIUM", 20.0)
PUMP_LAB_VOLUME_MIN_LONG = _env_float("PUMP_LAB_VOLUME_MIN_LONG", 10.0)
# «Памп прошёл»: откат от пика до минимума коррекции (дно, откуда мог пойти новый рост).
# Минимум глубины дна по типу; типичный верх диапазона — 40%.
PUMP_LAB_PASSED_DD_FAST = _env_float("PUMP_LAB_PASSED_DD_FAST", 20.0)
PUMP_LAB_PASSED_DD_MEDIUM = _env_float("PUMP_LAB_PASSED_DD_MEDIUM", 30.0)
PUMP_LAB_PASSED_DD_LONG = _env_float("PUMP_LAB_PASSED_DD_LONG", 40.0)
PUMP_LAB_PASSED_DD_MAX = _env_float("PUMP_LAB_PASSED_DD_MAX", 40.0)
# Дно коррекции считаем сформированным: столько минут после свечи-минимума и/или отскок %.
PUMP_LAB_TROUGH_CONFIRM_MIN = _env_int("PUMP_LAB_TROUGH_CONFIRM_MIN", 15)
PUMP_LAB_TROUGH_BOUNCE_PCT = _env_float("PUMP_LAB_TROUGH_BOUNCE_PCT", 1.0)
PUMP_LAB_MAX_AGE_DAYS = _env_int("PUMP_LAB_MAX_AGE_DAYS", 20)
# Окна истории от «сейчас» назад для детекта по классу.
PUMP_LAB_WINDOW_HOURS_FAST = _env_int("PUMP_LAB_WINDOW_HOURS_FAST", 6)
PUMP_LAB_WINDOW_DAYS_MEDIUM = _env_int("PUMP_LAB_WINDOW_DAYS_MEDIUM", 2)
# Длительность роста (дно → пик) для подписи: быстрый ≤6 ч, средний ≤2 сут, иначе длинный.
PUMP_LAB_FAST_MAX_MS = _env_int("PUMP_LAB_FAST_MAX_MS", 6 * 3_600_000)
PUMP_LAB_MEDIUM_MAX_MS = _env_int("PUMP_LAB_MEDIUM_MAX_MS", 2 * 24 * 3_600_000)
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


def kline_bar_ms(interval: str) -> int:
    return _KLINE_BAR_MINUTES.get(interval, 60) * 60_000


def kline_bars_for_days(interval: str, days: int | None = None) -> int:
    import math

    span = days if days is not None else PUMP_SCAN_CHART_FETCH_DAYS
    minutes = _KLINE_BAR_MINUTES.get(interval, 60)
    return max(10, int(math.ceil(span * 24 * 60 / minutes)))


def kline_tail_fresh(last_ts_ms: int, interval: str, now_ms: int) -> bool:
    """Последняя свеча — текущий бар (биржа отдаёт и незакрытую)."""
    bar_ms = kline_bar_ms(interval)
    if bar_ms <= 0 or int(last_ts_ms or 0) <= 0:
        return False
    bucket = (int(now_ms) // bar_ms) * bar_ms
    return int(last_ts_ms) >= bucket


def kline_history_complete(oldest_ts_ms: int, interval: str, days: int, now_ms: int) -> bool:
    """Ряд достаёт до начала окна days, а не обрывается на коротком кэше."""
    if int(oldest_ts_ms or 0) <= 0 or int(days or 0) <= 0:
        return False
    cutoff = int(now_ms) - int(days) * 86_400_000
    return int(oldest_ts_ms) <= cutoff + kline_bar_ms(interval) * 2


def kline_cache_servable(count: int, last_ts_ms: int, interval: str, min_bars: int, now_ms: int) -> bool:
    """Можно отдать свечи из памяти, не запрашивая биржу ещё раз.

    Полный ряд с устаревшим хвостом не отдаём: последняя свеча должна быть текущим баром.
    """
    if count <= 0:
        return False
    if count >= min_bars:
        return kline_tail_fresh(last_ts_ms, interval, now_ms)
    if count < 48 or last_ts_ms <= 0:
        return False
    minutes = _KLINE_BAR_MINUTES.get(interval, 60)
    return now_ms - int(last_ts_ms) <= minutes * 60_000 * 3


def oi_bars_for_days(oi_interval: str, days: int | None = None) -> int:
    import math

    span = days if days is not None else PUMP_SCAN_CHART_FETCH_DAYS
    minutes = _OI_BAR_MINUTES.get(oi_interval.lower(), 5)
    return max(10, int(math.ceil(span * 24 * 60 / minutes)))


def chart_tf_to_oi_interval(chart_tf: str) -> str:
    return CHART_TF_TO_OI_INTERVAL.get(chart_tf, "5min")


# --- Пылесос LH: 1H lower highs → проекция на 15m (сканер, не paper vac) -----
VACUUM_LH_MIN_TURNOVER_24H_USDT = _env_float("VACUUM_LH_MIN_TURNOVER_24H_USDT", 1_000_000.0)
# Размах (макс − мин) за последний час, % от текущей цены. Нет свечей — монета не в списке.
VACUUM_LH_HOUR_RANGE_PCT = _env_float("VACUUM_LH_HOUR_RANGE_PCT", 2.0)
VACUUM_LH_HOUR_MIN_1M_BARS = _env_int("VACUUM_LH_HOUR_MIN_1M_BARS", 10)
VACUUM_LH_HOUR_MIN_5M_BARS = _env_int("VACUUM_LH_HOUR_MIN_5M_BARS", 3)
VACUUM_LH_PEAK_COUNT = _env_int("VACUUM_LH_PEAK_COUNT", 5)
VACUUM_LH_PRICE_BELOW_LAST = _env_int("VACUUM_LH_PRICE_BELOW_LAST", 3)
# Pivot LH/HL: L10–L30 слева, 2 справа; min gap 10 (в окне ~30 баров до 3 экстремумов одного типа).
VACUUM_LH_PIVOT_LEFT = _env_int("VACUUM_LH_PIVOT_LEFT", 10)
VACUUM_LH_PIVOT_LEFT_MAX = _env_int("VACUUM_LH_PIVOT_LEFT_MAX", 30)
VACUUM_LH_PIVOT_RIGHT = _env_int("VACUUM_LH_PIVOT_RIGHT", 2)
# Между соседними pivot одного типа — не ближе N баров; ближе — один экстремум по цене.
VACUUM_LH_PIVOT_MIN_GAP = _env_int("VACUUM_LH_PIVOT_MIN_GAP", 10)
VACUUM_LH_LIVE_INTERVAL = "15"
VACUUM_LH_LOOKBACK_DAYS = _env_int("VACUUM_LH_LOOKBACK_DAYS", 14)
VACUUM_LH_MIN_1H_BARS = _env_int("VACUUM_LH_MIN_1H_BARS", 24)
VACUUM_LH_INTERVALS = ("15", "30", "60", "240")
VACUUM_LH_DEFAULT_INTERVAL = "15"
# Все TF графика/списка для совпадения вершин (цена + time_ms pivot).
VACUUM_LH_CONFLUENCE_INTERVALS = ("5", "15", "30", "60", "240")
VACUUM_LH_SCAN_INTERVAL_SEC = _env_int("VACUUM_LH_SCAN_INTERVAL_SEC", 45)
# Минимум закрытых свечей на TF для расчёта LH.
VACUUM_LH_MIN_BARS: dict[str, int] = {
    "5": _env_int("VACUUM_LH_MIN_BARS_5", 48),
    "15": _env_int("VACUUM_LH_MIN_BARS_15", 32),
    "30": _env_int("VACUUM_LH_MIN_BARS_30", 48),
    "60": _env_int("VACUUM_LH_MIN_BARS_60", 24),
    "240": _env_int("VACUUM_LH_MIN_BARS_240", 12),
}

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
