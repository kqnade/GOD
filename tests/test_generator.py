from __future__ import annotations

import random
import tempfile
import unittest
from datetime import date
from pathlib import Path

from god_bot.generator import (
    MemoryMessage,
    ReudyEngine,
    extract_words,
    load_seed_corpus,
    normalize_tail,
    tail_keys,
)
from god_bot.persona import apply_cute_tone, apply_persona


class ReudyGeneratorTests(unittest.TestCase):
    def test_loads_seed_corpus_lines(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "corpus.txt"
            path.write_text(
                "# comment\n12\tおはよう\n\n12\t元気だよ\n",
                encoding="utf-8",
            )
            corpus = load_seed_corpus(path)
        self.assertEqual(
            [message.content for message in corpus],
            ["おはよう", "元気だよ"],
        )
        self.assertEqual(
            [message.conversation_id for message in corpus],
            [12, 12],
        )

    def test_tail_normalization_matches_original_reudy_rule(self) -> None:
        self.assertEqual(normalize_tail("Rubyってどうよ？"), "ってどうよ?")
        self.assertTrue(
            tail_keys("Rubyってどうよ？")
            & tail_keys("Railsってどうよ？")
        )

    def test_extracts_japanese_nouns(self) -> None:
        words = extract_words("攻殻機動隊ってご存知？")
        self.assertIn("攻殻機動隊", words)

    def test_groups_automatic_compound_proper_nouns(self) -> None:
        self.assertEqual(
            extract_words("夏は揖保乃糸を食べる"),
            ("夏", "揖保乃糸"),
        )
        self.assertEqual(
            extract_words("田中太郎さんと東京都へ行く"),
            ("田中太郎さん", "東京都"),
        )
        self.assertEqual(
            extract_words("Visual Studio Codeを使う"),
            ("Visual Studio Code",),
        )

    def test_custom_dictionary_groups_unknown_proper_noun(self) -> None:
        self.assertEqual(
            extract_words("青空食堂へ行く"),
            ("青空", "食堂"),
        )
        self.assertEqual(
            extract_words("青空食堂へ行く", ("青空食堂",)),
            ("青空食堂",),
        )

    def test_keeps_selected_learned_reply_intact(self) -> None:
        messages = [
            MemoryMessage(1, 10, "Rubyってどうよ？"),
            MemoryMessage(2, 20, "Rubyは最高だよ！"),
            MemoryMessage(3, 10, "Railsってどうよ？"),
        ]
        engine = ReudyEngine(
            recent_unused_messages=0,
            response_drift_rate=0,
            word_splice_rate=0,
            word_mutation_rate=0,
            rng=random.Random(1),
        )
        reply = engine.respond("Railsってどうよ？", messages)
        self.assertIsNotNone(reply)
        assert reply is not None
        self.assertEqual(reply.text, "Rubyは最高だよ！")

    def test_must_respond_falls_back_to_random_memory(self) -> None:
        messages = [
            MemoryMessage(1, 10, "おはよう"),
            MemoryMessage(2, 20, "カレー食べたい"),
        ]
        engine = ReudyEngine(
            recent_unused_messages=0,
            word_splice_rate=0,
            rng=random.Random(2),
        )
        reply = engine.respond("xyz", messages)
        self.assertIsNotNone(reply)
        assert reply is not None
        self.assertIn(reply.text, {"おはよう", "カレー食べたい"})

    def test_seed_weight_zero_prefers_dynamic_memory(self) -> None:
        seed = [MemoryMessage(-1, 0, "初期コーパス")]
        dynamic = [
            MemoryMessage(1, 1, "Discordの記憶", conversation_id=-1)
        ]
        engine = ReudyEngine(
            seed_messages=seed,
            seed_corpus_weight=0.0,
            recent_unused_messages=0,
            word_splice_rate=0,
            rng=random.Random(4),
        )
        reply = engine.respond("xyz", dynamic)
        self.assertIsNotNone(reply)
        assert reply is not None
        self.assertEqual(reply.text, "Discordの記憶")

    def test_long_memory_is_not_used_as_a_reply(self) -> None:
        messages = [
            MemoryMessage(1, 1, "短い返事"),
            MemoryMessage(2, 2, "長すぎる返事です"),
        ]
        engine = ReudyEngine(
            recent_unused_messages=0,
            max_reply_source_length=5,
            word_splice_rate=0,
            rng=random.Random(2),
        )
        reply = engine.respond("xyz", messages)
        self.assertIsNotNone(reply)
        assert reply is not None
        self.assertEqual(reply.text, "短い返事")

    def test_splices_different_memories_at_word_boundaries(self) -> None:
        messages = [
            MemoryMessage(1, 1, "今日はカレーを食べる"),
            MemoryMessage(2, 2, "今日は宇宙人が踊る"),
        ]
        engine = ReudyEngine(
            recent_unused_messages=0,
            max_reply_source_length=30,
            response_drift_rate=0,
            word_splice_rate=1,
            rng=random.Random(0),
        )
        reply = engine.respond("xyz", messages)
        self.assertIsNotNone(reply)
        assert reply is not None
        self.assertNotIn(
            reply.text,
            {"今日はカレーを食べる", "今日は宇宙人が踊る"},
        )
        self.assertLessEqual(len(reply.text), 30)

    def test_mutates_nouns_and_keeps_sentence_structure(self) -> None:
        messages = [
            MemoryMessage(1, 1, "猫が布団で静かに眠る"),
            MemoryMessage(2, 2, "宇宙船が惑星で静かに眠る"),
        ]
        engine = ReudyEngine(
            recent_unused_messages=0,
            max_reply_source_length=30,
            response_drift_rate=0,
            word_splice_rate=0,
            word_mutation_rate=1,
            rng=random.Random(12),
        )
        mutated = engine._mutate_words(
            messages[0].content,
            0,
            messages,
            force=True,
        )
        self.assertNotIn("猫", mutated)
        self.assertNotIn("布団", mutated)
        self.assertTrue(mutated.endswith("で静かに眠る"))

    def test_does_not_partially_mutate_proper_nouns(self) -> None:
        messages = [
            MemoryMessage(1, 1, "揖保乃糸を食べる"),
            MemoryMessage(2, 2, "カレーを食べる"),
        ]
        engine = ReudyEngine(
            proper_nouns=("揖保乃糸",),
            recent_unused_messages=0,
            max_reply_source_length=30,
            word_mutation_rate=1,
            rng=random.Random(12),
        )
        mutated = engine._mutate_words(
            messages[0].content,
            0,
            messages,
            force=True,
        )
        self.assertEqual(mutated, "揖保乃糸を食べる")

    def test_dictionary_updates_take_effect_without_rebuilding_engine(
        self,
    ) -> None:
        engine = ReudyEngine()
        self.assertEqual(
            extract_words("青空食堂へ行く"),
            ("青空", "食堂"),
        )
        engine.add_proper_noun("青空食堂")
        self.assertIn(
            "固有:青空食堂",
            engine._text_vector("青空食堂へ行く"),
        )
        engine.remove_proper_noun("青空食堂")
        self.assertNotIn(
            "固有:青空食堂",
            engine._text_vector("青空食堂へ行く"),
        )

    def test_does_not_mutate_from_unrelated_memory(self) -> None:
        messages = [
            MemoryMessage(1, 1, "猫が静かに眠る"),
            MemoryMessage(2, 2, "社長が激しく走る"),
        ]
        engine = ReudyEngine(
            recent_unused_messages=0,
            word_splice_rate=0,
            word_mutation_rate=1,
            rng=random.Random(12),
        )
        reply = engine.respond("xyz", messages)
        self.assertIsNotNone(reply)
        assert reply is not None
        self.assertIn(
            reply.text,
            {"猫が静かに眠る", "社長が激しく走る"},
        )

    def test_text_vector_rates_related_phrases_more_highly(self) -> None:
        engine = ReudyEngine()
        reference = engine._text_vector("猫がソファで眠る")
        related = engine._text_vector("猫がベッドで寝る")
        unrelated = engine._text_vector("会社の会議を始める")
        self.assertGreater(
            engine._cosine_similarity(reference, related),
            engine._cosine_similarity(reference, unrelated),
        )

    def test_drift_selects_an_unrelated_complete_sentence(self) -> None:
        messages = [
            MemoryMessage(1, 1, "猫がソファで眠る"),
            MemoryMessage(2, 2, "会社の会議を始める"),
        ]
        engine = ReudyEngine(
            recent_unused_messages=0,
            response_drift_rate=1,
            word_splice_rate=0,
            word_mutation_rate=0,
            rng=random.Random(3),
        )
        reply = engine.respond("猫がソファで眠る", messages)
        self.assertIsNotNone(reply)
        assert reply is not None
        self.assertEqual(reply.text, "会社の会議を始める")

    def test_returns_vector_associated_learned_words(self) -> None:
        messages = [
            MemoryMessage(1, 1, "猫がベッドで眠る"),
            MemoryMessage(2, 2, "会社の会議を始める"),
        ]
        engine = ReudyEngine(rng=random.Random(3))
        words = engine.associated_words("猫", messages)
        self.assertIn("ベッド", words)
        self.assertIn("眠る", words)

    def test_associated_words_keep_registered_names_whole(self) -> None:
        messages = [
            MemoryMessage(1, 1, "青空食堂でカレーを食べる"),
            MemoryMessage(2, 2, "青空食堂で昼食を食べる"),
        ]
        engine = ReudyEngine(
            proper_nouns=("青空食堂",),
            rng=random.Random(3),
        )
        words = engine.associated_words("カレー", messages)
        self.assertIn("青空食堂", words)
        self.assertNotIn("青空", words)
        self.assertNotIn("食堂", words)

    def test_builds_fortune_from_learned_words(self) -> None:
        messages = [
            MemoryMessage(1, 1, "猫が元気に走る"),
            MemoryMessage(2, 2, "カレーが美味しい"),
        ]
        engine = ReudyEngine(rng=random.Random(4))
        result = engine.fortune(messages)
        self.assertIn("ラッキー単語", result)
        self.assertTrue(any(word in result for word in ("猫", "カレー")))

    def test_builds_oracle_quote_from_learned_memory(self) -> None:
        messages = [
            MemoryMessage(1, 1, "猫は液体である"),
            MemoryMessage(2, 2, "カレーが未来を救う"),
        ]
        engine = ReudyEngine(rng=random.Random(4))
        result = engine.oracle_quote(messages)
        self.assertTrue(
            any(message.content in result for message in messages)
        )
        self.assertIn("解釈:", result)
        self.assertIn("神様", result)

    def test_judges_two_sides_with_learned_reason(self) -> None:
        messages = [MemoryMessage(1, 1, "宇宙とカレーの会議")]
        engine = ReudyEngine(rng=random.Random(2))
        result = engine.judge_dispute("猫 犬", messages)
        self.assertIn("勝訴:", result)
        self.assertIn("敗訴:", result)
        self.assertIn("猫", result)
        self.assertIn("犬", result)
        self.assertTrue(
            any(word in result for word in ("宇宙", "カレー", "会議"))
        )
        self.assertIn(
            "二者",
            engine.judge_dispute("猫 犬 鳥", messages),
        )

    def test_daily_lucky_item_is_stable_for_the_date(self) -> None:
        messages = [
            MemoryMessage(1, 1, "レモンと時計"),
            MemoryMessage(2, 2, "カレーと帽子"),
        ]
        engine = ReudyEngine(rng=random.Random(2))
        day = date(2026, 7, 28)
        first = engine.daily_lucky_item(messages, day)
        second = engine.daily_lucky_item(messages, day)
        self.assertEqual(first, second)
        self.assertTrue(
            any(first.endswith(noun) for noun in ("レモン", "時計", "カレー", "帽子"))
        )
        self.assertNotIn(first, {"レモン", "時計", "カレー", "帽子"})

    def test_summarizes_learned_messages(self) -> None:
        messages = [
            MemoryMessage(1, 1, "猫が眠る"),
            MemoryMessage(2, 2, "猫が走る"),
            MemoryMessage(3, 1, "カレーが美味しい"),
        ]
        engine = ReudyEngine(rng=random.Random(5))
        result = engine.summarize_messages(messages)
        self.assertIn("今日の記憶: 3件・2人", result)
        self.assertIn("猫", result)
        self.assertIn("雑な要約:", result)

    def test_summary_keeps_registered_names_whole(self) -> None:
        messages = [
            MemoryMessage(1, 1, "青空食堂で食べる"),
            MemoryMessage(2, 2, "青空食堂で話す"),
        ]
        engine = ReudyEngine(
            proper_nouns=("青空食堂",),
            rng=random.Random(5),
        )
        result = engine.summarize_messages(messages)
        self.assertIn("頻出語: 青空食堂", result)

    def test_samurai_persona(self) -> None:
        self.assertEqual(
            apply_persona("私は大丈夫です", "samurai"),
            "拙者は大丈夫でござる",
        )

    def test_casual_persona(self) -> None:
        self.assertEqual(
            apply_persona("今日はいい天気ですね", "casual"),
            "今日はいい天気だね",
        )
        self.assertEqual(
            apply_persona("これは本当ですか？", "casual"),
            "これは本当なの？",
        )
        self.assertEqual(
            apply_persona("大丈夫ですよ", "casual"),
            "大丈夫だよ",
        )
        self.assertEqual(
            apply_persona("今日は暑いですよ", "casual"),
            "今日は暑いよ",
        )
        self.assertEqual(
            apply_persona("海へ行きたいですね", "casual"),
            "海へ行きたいね",
        )
        self.assertEqual(
            apply_persona("これは猫です", "casual"),
            "これは猫だ",
        )
        self.assertEqual(
            apply_persona("昨日は暑かったです", "casual"),
            "昨日は暑かった",
        )

    def test_adds_cute_tone_only_when_enabled(self) -> None:
        self.assertEqual(
            apply_cute_tone(
                "ストレンジャーシングスネックカレーライス",
                rate=0,
                rng=random.Random(1),
            ),
            "ストレンジャーシングスネックカレーライス",
        )
        result = apply_cute_tone(
            "ストレンジャーシングスネックカレーライス",
            rate=1,
            rng=random.Random(1),
        )
        self.assertTrue(
            result.endswith(("だよ", "だね", "なのだ", "にゃ", "うにゃ〜"))
        )
        self.assertEqual(
            apply_cute_tone(
                "そうだよ",
                rate=1,
                rng=random.Random(1),
            ),
            "そうだよ",
        )


if __name__ == "__main__":
    unittest.main()
