from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from god_bot.database import MemoryRepository


class MemoryRepositoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_directory = tempfile.TemporaryDirectory()
        path = Path(self.temp_directory.name) / "memory.sqlite3"
        self.repository = MemoryRepository(path)
        self.repository.initialize()

    def tearDown(self) -> None:
        self.temp_directory.cleanup()

    def _learn(
        self,
        message_id: int,
        author_id: int,
        content: str,
        created_at: float,
    ) -> None:
        self.repository.learn_message(
            message_id=message_id,
            guild_id=1,
            channel_id=10,
            author_id=author_id,
            content=content,
            created_at=created_at,
            max_messages=100,
        )

    def test_remembers_messages_in_order(self) -> None:
        self._learn(100, 1, "おはよう", 1_000)
        self._learn(101, 2, "おはようございます", 1_010)

        self.assertEqual(
            self.repository.memory_messages(1, 10, limit=10)[1].content,
            "おはようございます",
        )

    def test_remembers_consecutive_messages_from_same_speaker(self) -> None:
        self._learn(100, 1, "一つ目", 1_000)
        self._learn(101, 1, "二つ目", 1_010)
        self.assertEqual(self.repository.stats(1, 10).messages, 2)

    def test_edit_and_delete_are_reflected_in_memory(self) -> None:
        self._learn(100, 1, "おはよう", 1_000)
        self._learn(101, 2, "こんにちは", 1_010)
        self.repository.update_message(101, "やあ")
        self.assertEqual(
            self.repository.memory_messages(1, 10, limit=10)[1].content,
            "やあ",
        )

        self.repository.delete_message(100)
        self.assertEqual(self.repository.stats(1, 10).messages, 1)

    def test_forget_user_deletes_their_messages(self) -> None:
        self._learn(100, 1, "おはよう", 1_000)
        self._learn(101, 2, "こんにちは", 1_010)
        self.assertEqual(self.repository.forget_user(1, 1), 1)
        self.assertEqual(self.repository.stats(1, 10).messages, 1)

    def test_reads_only_messages_since_threshold(self) -> None:
        self._learn(100, 1, "昨日", 1_000)
        self._learn(101, 2, "今日", 2_000)
        messages = self.repository.memory_messages_since(
            1,
            10,
            since=1_500,
            limit=10,
        )
        self.assertEqual([message.content for message in messages], ["今日"])

    def test_purges_short_and_symbol_only_messages(self) -> None:
        self._learn(100, 1, "はい", 1_000)
        self._learn(101, 1, "？？？？", 1_010)
        self._learn(102, 1, "これは残る", 1_020)
        deleted = self.repository.purge_low_value_messages(1, 10)
        self.assertEqual(deleted, 2)
        self.assertEqual(
            [
                message.content
                for message in self.repository.memory_messages(
                    1, 10, limit=10
                )
            ],
            ["これは残る"],
        )

    def test_manages_proper_noun_dictionary_per_guild(self) -> None:
        self.assertTrue(self.repository.add_proper_noun(1, "揖保乃糸"))
        self.assertFalse(self.repository.add_proper_noun(1, "揖保乃糸"))
        self.assertTrue(self.repository.add_proper_noun(1, "OpenAI"))
        self.assertFalse(self.repository.add_proper_noun(1, "openai"))
        self.assertTrue(self.repository.add_proper_noun(2, "OpenAI"))

        self.assertEqual(
            set(self.repository.proper_nouns(1)),
            {"揖保乃糸", "OpenAI"},
        )
        self.assertEqual(
            self.repository.proper_nouns(2),
            ("OpenAI",),
        )

        self.assertTrue(self.repository.remove_proper_noun(1, "OPENAI"))
        self.assertFalse(self.repository.remove_proper_noun(1, "OPENAI"))
        self.assertEqual(
            self.repository.proper_nouns(1),
            ("揖保乃糸",),
        )

    def test_normalizes_dictionary_entries(self) -> None:
        self.assertTrue(
            self.repository.add_proper_noun(1, "  ＯｐｅｎＡＩ   Japan  ")
        )
        self.assertEqual(
            self.repository.proper_nouns(1),
            ("OpenAI Japan",),
        )
        with self.assertRaises(ValueError):
            self.repository.add_proper_noun(1, "？？？")


if __name__ == "__main__":
    unittest.main()
