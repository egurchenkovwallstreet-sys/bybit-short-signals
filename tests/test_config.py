"""Проверка настроек Этапа 1: лимиты из ТЗ и чтение .env."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

import config


class ConfigDefaultsTest(unittest.TestCase):
    """Константы защиты от перегрузки и пороги сигнала."""

    def test_reconnect_backoff(self) -> None:
        self.assertEqual(config.RECONNECT_DELAYS_SEC, (1, 2, 4, 8))

    def test_overload_limits(self) -> None:
        self.assertEqual(config.REDIS_CHANNEL_BUFFER, 1024)
        self.assertEqual(config.WS_MAX_HZ, 10)
        self.assertEqual(config.TICKER_BATCH_INTERVAL_MS, 500)
        self.assertEqual(config.MARKET_SCAN_INTERVAL_SEC, 3)

    def test_bybit_topics(self) -> None:
        symbol = "BEAMUSDT"
        self.assertEqual(config.WS_TOPIC_TRADE.format(symbol=symbol), "publicTrade.BEAMUSDT")
        self.assertEqual(
            config.WS_TOPIC_LIQUIDATION.format(symbol=symbol),
            "allLiquidation.BEAMUSDT",
        )
        self.assertEqual(
            config.WS_TOPIC_ORDERBOOK.format(symbol=symbol),
            "orderbook.50.BEAMUSDT",
        )
        self.assertEqual(config.WS_TOPIC_TICKER.format(symbol=symbol), "tickers.BEAMUSDT")
        self.assertNotIn("liquidation.{", config.WS_TOPIC_LIQUIDATION)

    def test_pump_and_outcome_thresholds(self) -> None:
        self.assertEqual(config.PUMP_PRICE_CHANGE_15M, 5.0)
        self.assertEqual(config.PUMP_PRICE_CHANGE_5M, 3.0)
        self.assertEqual(config.PUMP_VOLUME_MULTIPLIER, 5.0)
        self.assertEqual(config.PUMP_VOLUME_MA_PERIOD, 20)
        self.assertEqual(config.PUMP_RSI_MIN, 60.0)
        self.assertEqual(config.PUMP_RSI_MAX, 85.0)
        self.assertEqual(config.LIQUIDATION_SIDE_SHORT, "Sell")
        self.assertEqual(config.TP_PCT, 3.0)
        self.assertEqual(config.LIQUIDATION_PCT, 10.0)
        self.assertEqual(config.TIME_EXIT_HOURS, 24)
        self.assertEqual(config.PNL_LEVERAGE, 10)

    def test_signal_columns(self) -> None:
        self.assertEqual(list(config.SIGNAL_COLUMNS), [5, 4, 3, 2, 1])
        self.assertEqual(config.SIGNAL_COLUMNS[5]["status"], "ВХОД")
        self.assertEqual(config.SIGNAL_COLUMNS[1]["status"], "НАБЛЮДЕНИЕ")

    def test_expert_weights(self) -> None:
        self.assertEqual(config.EXPERT_WEIGHTS["sweep"], 0.15)
        self.assertEqual(config.EXPERT_WEIGHTS["liquidations_faded"], 0.20)
        self.assertEqual(config.EXPERT_WEIGHTS["oi_drop"], 0.10)
        self.assertEqual(config.EXPERT_WEIGHTS["cvd_divergence"], 0.10)
        self.assertEqual(config.EXPERT_WEIGHTS["round_level"], 0.05)
        self.assertEqual(config.EXPERT_WEIGHTS["funding_extreme"], 0.05)

    def test_rating_formula_weights(self) -> None:
        self.assertEqual(config.RATING_WEIGHT_STRENGTH, 20)
        self.assertEqual(config.RATING_WEIGHT_PROBABILITY, 0.5)
        self.assertEqual(config.RATING_WEIGHT_QUALITY, 10)
        self.assertEqual(config.RATING_WEIGHT_TF, 5)
        self.assertEqual(config.RATING_WEIGHT_EXTRA, 3)

    def test_project_packages_exist(self) -> None:
        root = config.BASE_DIR
        for name in ("collector", "signal_engine", "ws_server", "shared", "tests"):
            self.assertTrue((root / name / "__init__.py").is_file(), name)


class DotenvTest(unittest.TestCase):
    """Локальный .env не затирает переменные, которые уже заданы снаружи."""

    def test_setdefault_keeps_existing_env(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            env_file = Path(folder) / ".env"
            env_file.write_text("DEMO_KEY=from-file\n", encoding="utf-8")
            os.environ["DEMO_KEY"] = "from-env"
            try:
                config.load_dotenv(env_file)
                self.assertEqual(os.environ["DEMO_KEY"], "from-env")
            finally:
                os.environ.pop("DEMO_KEY", None)

    def test_loads_missing_key(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            env_file = Path(folder) / ".env"
            env_file.write_text(
                "# комментарий\nDEMO_NEW='значение'\n\n",
                encoding="utf-8",
            )
            os.environ.pop("DEMO_NEW", None)
            try:
                config.load_dotenv(env_file)
                self.assertEqual(os.environ["DEMO_NEW"], "значение")
            finally:
                os.environ.pop("DEMO_NEW", None)


if __name__ == "__main__":
    unittest.main()
