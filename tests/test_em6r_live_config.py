import unittest

import config
from signal_engine.live import em6r_demo


class Em6rLiveConfigTest(unittest.TestCase):
    def test_import_broker(self) -> None:
        self.assertIsNotNone(em6r_demo.Em6rDemoBroker)

    def test_live_flag_is_string(self) -> None:
        self.assertIsInstance(config.EM6R_LIVE_ENABLED, str)


if __name__ == "__main__":
    unittest.main()
