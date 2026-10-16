# -*- coding: utf-8 -*-
import unittest

from signal_engine.paper.vac_detect import VAC_MANDATORY, _entry_trigger, _is_pin_bar
from signal_engine.state import Bar


class VacTriggerTest(unittest.TestCase):
    def test_pin_plus_bearish(self) -> None:
        pin = Bar(0, 10.0, 12.0, 9.5, 10.2, 100.0)
        bear = Bar(1, 10.2, 10.3, 9.8, 9.9, 100.0)
        self.assertTrue(_is_pin_bar(pin, 0.66, 0.33))
        self.assertEqual(_entry_trigger(pin, bear), "pin_bear")

    def test_two_bearish(self) -> None:
        b1 = Bar(0, 10.0, 10.1, 9.7, 9.8, 100.0)
        b2 = Bar(1, 9.8, 9.9, 9.5, 9.6, 100.0)
        self.assertEqual(_entry_trigger(b1, b2), "two_bear")

    def test_mandatory_count(self) -> None:
        self.assertEqual(len(VAC_MANDATORY), 6)


if __name__ == "__main__":
    unittest.main()
