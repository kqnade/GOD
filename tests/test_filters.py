from __future__ import annotations

import unittest

from god_bot.filters import prepare_message, sanitize_reply


class PrepareMessageTests(unittest.TestCase):
    def test_accepts_normal_japanese_message(self) -> None:
        self.assertEqual(
            prepare_message(" 今日はいい天気ですね "),
            "今日はいい天気ですね",
        )

    def test_removes_bot_mention_and_generalizes_other_mentions(self) -> None:
        self.assertEqual(
            prepare_message(
                "<@123> <@456> 元気？",
                bot_user_id=123,
            ),
            "誰か 元気?",
        )

    def test_rejects_urls_code_and_secrets(self) -> None:
        self.assertIsNone(prepare_message("これ見て https://example.com"))
        self.assertIsNone(prepare_message("`print('hello')`"))
        self.assertIsNone(prepare_message("api_key=super-secret-value"))

    def test_sanitizes_mentions_in_reply(self) -> None:
        self.assertEqual(sanitize_reply("@everyone おはよう"), "＠everyone おはよう")


if __name__ == "__main__":
    unittest.main()
