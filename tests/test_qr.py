from __future__ import annotations

import unittest

from god_bot.qr import QrError, make_qr_image


class QrTests(unittest.TestCase):
    def test_generates_png(self) -> None:
        result = make_qr_image("https://example.com")
        self.assertTrue(result.data.startswith(b"\x89PNG\r\n\x1a\n"))
        self.assertEqual(result.filename, "qr.png")
        self.assertIn("https://example.com", result.caption)

    def test_rejects_empty_or_oversized_input(self) -> None:
        with self.assertRaises(QrError):
            make_qr_image("")
        with self.assertRaises(QrError):
            make_qr_image("猫" * 400)


if __name__ == "__main__":
    unittest.main()
