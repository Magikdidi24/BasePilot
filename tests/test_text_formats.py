"""Short texts the UI shows: loot amounts and aspect names."""
import unittest

from app.config import aspect_label

try:
    from app.ui.qt.widgets import short_amount
except ImportError:  # no PySide6 (the Linux CI)
    short_amount = None


class AspectLabelTests(unittest.TestCase):
    def test_known_and_unknown_keys(self):
        self.assertEqual([aspect_label(k) for k in ('16_9', '16_10', None, 'x')], ['16:9', '16:10', 'unknown aspect', 'unknown aspect'])
        self.assertEqual(aspect_label(None, 'unsupported aspect'), 'unsupported aspect')


@unittest.skipIf(short_amount is None, 'needs PySide6')
class ShortAmountTests(unittest.TestCase):
    def test_millions_thousands_and_small_amounts(self):
        cases = {0: '0', 9999: '9999', 10000: '10k', 450000: '450k', 999999: '1000k', 1000000: '1.0M', 12720391: '12.7M',
                 3.9: '3', -2345678: '-2.3M'}
        for (value, text) in cases.items():
            with self.subTest(value=value):
                self.assertEqual(short_amount(value), text)


if __name__ == '__main__':
    unittest.main()
