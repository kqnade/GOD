from __future__ import annotations

import hashlib
import random
import re
import shlex
from collections import Counter, deque
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from functools import lru_cache
from pathlib import Path

from janome.tokenizer import Tokenizer

from .proper_nouns import normalize_proper_noun


@dataclass(frozen=True, slots=True)
class MemoryMessage:
    message_id: int
    author_id: int
    content: str
    conversation_id: int = 0


@dataclass(frozen=True, slots=True)
class GeneratedReply:
    text: str
    base_message_id: int


@dataclass(frozen=True, slots=True)
class _NounTerm:
    surface: str
    token_indices: tuple[int, ...]
    proper: bool


_TOKENIZER = Tokenizer()
_NON_REUDY_TAIL_CHARS = re.compile(r"[^ぁ-んー−？！?!\.]+")
_ASCII_NAME_RE = re.compile(r"[A-Za-z][A-Za-z0-9_.+#-]*\Z")


def load_seed_corpus(path: Path | None) -> list[MemoryMessage]:
    if path is None:
        return []
    messages: list[MemoryMessage] = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        conversation_id = 0
        content = line
        prefix, separator, remainder = line.partition("\t")
        if separator and prefix.lstrip("-").isdigit():
            conversation_id = int(prefix)
            content = remainder.strip()
        if not content:
            continue
        messages.append(
            MemoryMessage(
                message_id=-(len(messages) + 1),
                author_id=len(messages) % 2,
                content=content,
                conversation_id=conversation_id,
            )
        )
    return messages


def _looks_like_ascii_name(surface: str) -> bool:
    return bool(_ASCII_NAME_RE.fullmatch(surface))


def _ascii_case_insensitive(value: str) -> str:
    return "".join(
        char.lower() if "A" <= char <= "Z" else char
        for char in value
    )


def _noun_candidate(token: object) -> bool:
    parts = token.part_of_speech.split(",")
    return (
        parts[0] == "名詞"
        and len(parts) > 1
        and parts[1] not in {"非自立", "代名詞", "数", "形容動詞語幹"}
    )


@lru_cache(maxsize=128)
def _prepared_proper_nouns(terms: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(
        sorted(
            {normalize_proper_noun(name) for name in terms},
            key=len,
            reverse=True,
        )
    )


def _custom_name_spans(
    text: str,
    proper_nouns: Iterable[str],
) -> list[tuple[int, int]]:
    folded = _ascii_case_insensitive(text)
    occupied = [False] * len(text)
    spans: list[tuple[int, int]] = []
    names = _prepared_proper_nouns(tuple(proper_nouns))
    for name in names:
        folded_name = _ascii_case_insensitive(name)
        start = 0
        while True:
            start = folded.find(folded_name, start)
            if start < 0:
                break
            end = start + len(name)
            start_is_ascii = name[0].isascii() and name[0].isalnum()
            end_is_ascii = name[-1].isascii() and name[-1].isalnum()
            left_is_word = (
                start > 0
                and text[start - 1].isascii()
                and text[start - 1].isalnum()
            )
            right_is_word = (
                end < len(text)
                and text[end].isascii()
                and text[end].isalnum()
            )
            if (
                not any(occupied[start:end])
                and not (start_is_ascii and left_is_word)
                and not (end_is_ascii and right_is_word)
            ):
                spans.append((start, end))
                occupied[start:end] = [True] * (end - start)
            start = max(end, start + 1)
    return sorted(spans)


def _noun_terms(
    text: str,
    proper_nouns: Iterable[str] = (),
) -> tuple[_NounTerm, ...]:
    tokens = list(_TOKENIZER.tokenize(text))
    token_spans: list[tuple[int, int]] = []
    offset = 0
    for token in tokens:
        end = offset + len(token.surface)
        token_spans.append((offset, end))
        offset = end

    custom_spans = _custom_name_spans(text, proper_nouns)
    custom_token_indices: set[int] = set()
    terms: list[tuple[int, _NounTerm]] = []
    for start, end in custom_spans:
        indices = tuple(
            index
            for index, (token_start, token_end) in enumerate(token_spans)
            if token_start < end and token_end > start
        )
        custom_token_indices.update(indices)
        terms.append(
            (
                start,
                _NounTerm(
                    surface=text[start:end],
                    token_indices=indices,
                    proper=True,
                ),
            )
        )

    segment: list[int] = []

    def flush_segment() -> None:
        if not segment:
            return
        noun_indices = [
            index for index in segment if _noun_candidate(tokens[index])
        ]
        is_proper = any(
            tokens[index].part_of_speech.split(",")[1] == "固有名詞"
            or _looks_like_ascii_name(tokens[index].surface)
            for index in noun_indices
        )
        if is_proper:
            start = token_spans[segment[0]][0]
            end = token_spans[segment[-1]][1]
            terms.append(
                (
                    start,
                    _NounTerm(
                        surface=text[start:end],
                        token_indices=tuple(noun_indices),
                        proper=True,
                    ),
                )
            )
        else:
            for index in noun_indices:
                parts = tokens[index].part_of_speech.split(",")
                surface = tokens[index].surface.strip()
                if (
                    parts[1] != "接尾"
                    and surface
                    and not (len(surface) < 2 and surface.isascii())
                ):
                    terms.append(
                        (
                            token_spans[index][0],
                            _NounTerm(
                                surface=surface,
                                token_indices=(index,),
                                proper=False,
                            ),
                        )
                    )
        segment.clear()

    for index, token in enumerate(tokens):
        if index in custom_token_indices:
            flush_segment()
            continue
        if _noun_candidate(token):
            segment.append(index)
            continue
        parts = token.part_of_speech.split(",")
        if (
            segment
            and parts[:2] == ["記号", "空白"]
            and index + 1 < len(tokens)
            and index + 1 not in custom_token_indices
            and _noun_candidate(tokens[index + 1])
            and all(
                tokens[noun_index].surface.isascii()
                for noun_index in segment
                if _noun_candidate(tokens[noun_index])
            )
            and tokens[index + 1].surface.isascii()
        ):
            segment.append(index)
            continue
        flush_segment()
    flush_segment()

    terms.sort(key=lambda item: item[0])
    return tuple(term for _, term in terms)


def extract_words(
    text: str,
    proper_nouns: Iterable[str] = (),
) -> tuple[str, ...]:
    """Extract Reudy-style replaceable words (mostly independent nouns)."""
    words: list[str] = []
    for term in _noun_terms(text, proper_nouns):
        if term.surface not in words:
            words.append(term.surface)
    return tuple(words)


def normalize_tail(text: str) -> str:
    """Match Reudy's hiragana-and-punctuation-only tail normalizer."""
    normalized = _NON_REUDY_TAIL_CHARS.sub("", text)
    return (
        normalized.replace("？", "?")
        .replace("！", "!")
        .replace("−", "ー")
    )


def tail_keys(text: str, *, comparison_length: int = 6) -> set[str]:
    """Return the same tail and one-character-omission keys Reudy indexes."""
    normalized = normalize_tail(text)
    if len(normalized) <= 1:
        return set()
    if len(normalized) < comparison_length:
        return {normalized}

    tail = normalized[-comparison_length:]
    keys = {tail}
    keys.update(tail[:index] + tail[index + 1 :] for index in range(len(tail)))
    return keys


class ReudyEngine:
    """A small Python port of Reudy's free-speech selection algorithm."""

    def __init__(
        self,
        *,
        seed_messages: list[MemoryMessage] | None = None,
        seed_corpus_weight: float = 0.15,
        recent_unused_messages: int = 100,
        repeat_proof_messages: int = 50,
        max_reply_source_length: int = 20,
        response_drift_rate: float = 0.85,
        word_splice_rate: float = 0.0,
        word_mutation_rate: float = 0.35,
        proper_nouns: Iterable[str] = (),
        rng: random.Random | None = None,
    ) -> None:
        self.recent_unused_messages = recent_unused_messages
        self._recent_base_ids: deque[int] = deque(maxlen=repeat_proof_messages)
        self._input_words: list[str] = []
        self._rng = rng or random.Random()
        self._seed_corpus_weight = min(
            max(seed_corpus_weight, 0.0),
            1.0,
        )
        self._max_reply_source_length = max_reply_source_length
        self._response_drift_rate = min(
            max(response_drift_rate, 0.0),
            1.0,
        )
        self._word_splice_rate = min(max(word_splice_rate, 0.0), 1.0)
        self._word_mutation_rate = min(
            max(word_mutation_rate, 0.0), 1.0
        )
        self._proper_nouns: tuple[str, ...] = ()
        self.set_proper_nouns(proper_nouns)
        self._seed_messages = list(seed_messages or [])
        self._seed_tail_index: dict[str, list[int]] = {}
        for index, message in enumerate(self._seed_messages):
            for key in tail_keys(message.content):
                self._seed_tail_index.setdefault(key, []).append(index)

    def reset_state(self) -> None:
        self._recent_base_ids.clear()
        self._input_words.clear()

    def set_proper_nouns(self, terms: Iterable[str]) -> None:
        """Replace the in-memory dictionary without per-message DB access."""
        normalized: dict[str, str] = {}
        for term in terms:
            cleaned = normalize_proper_noun(term)
            normalized[cleaned.casefold()] = cleaned
        self._proper_nouns = tuple(normalized.values())

    def add_proper_noun(self, term: str) -> None:
        normalized = normalize_proper_noun(term)
        terms = {
            existing.casefold(): existing
            for existing in self._proper_nouns
        }
        terms[normalized.casefold()] = normalized
        self._proper_nouns = tuple(terms.values())

    def remove_proper_noun(self, term: str) -> None:
        key = normalize_proper_noun(term).casefold()
        self._proper_nouns = tuple(
            existing
            for existing in self._proper_nouns
            if existing.casefold() != key
        )

    def associated_words(
        self,
        query: str,
        dynamic_messages: list[MemoryMessage],
        *,
        limit: int = 8,
    ) -> tuple[str, ...]:
        """Return learned content words from vector-near utterances."""
        messages = self._seed_messages + dynamic_messages
        seed_count = len(self._seed_messages)
        seed_sample_size = min(seed_count, 512)
        seed_indices = (
            self._rng.sample(range(seed_count), seed_sample_size)
            if seed_sample_size
            else []
        )
        dynamic_indices = list(range(seed_count, len(messages)))
        reference = self._text_vector(query)
        scored: list[tuple[float, int]] = []
        for index in seed_indices + dynamic_indices:
            score = self._cosine_similarity(
                reference,
                self._text_vector(messages[index].content),
            )
            if score > 0:
                scored.append((score, index))
        scored.sort(key=lambda item: item[0], reverse=True)

        query_words = set(extract_words(query, self._proper_nouns))
        query_words.update({
            token.surface
            for token in _TOKENIZER.tokenize(query)
            if self._replaceable_part(token) is not None
        })
        weights: Counter[str] = Counter()
        for rank, (_, index) in enumerate(scored[:40]):
            rank_weight = max(1, 40 - rank)
            content = messages[index].content
            tokens = list(_TOKENIZER.tokenize(content))
            proper_terms = [
                term
                for term in _noun_terms(content, self._proper_nouns)
                if term.proper
            ]
            protected_indices = {
                token_index
                for term in proper_terms
                for token_index in term.token_indices
            }
            for term in proper_terms:
                if term.surface not in query_words:
                    weights[term.surface] += rank_weight
            for token_index, token in enumerate(tokens):
                if (
                    token_index not in protected_indices
                    and self._replaceable_part(token) is not None
                    and token.surface not in query_words
                    and any(char.isalnum() for char in token.surface)
                ):
                    weights[token.surface] += rank_weight
        return tuple(word for word, _ in weights.most_common(limit))

    def fortune(
        self,
        dynamic_messages: list[MemoryMessage],
    ) -> str:
        """Build an intentionally dubious fortune from learned words."""
        source = list(dynamic_messages)
        if len(source) < 20 and self._seed_messages:
            source.extend(
                self._rng.sample(
                    self._seed_messages,
                    min(40, len(self._seed_messages)),
                )
            )
        buckets: dict[str, list[str]] = {
            "名詞": [],
            "動詞": [],
            "形容詞": [],
        }
        for message in source:
            for term in _noun_terms(
                message.content,
                self._proper_nouns,
            ):
                if term.surface not in buckets["名詞"]:
                    buckets["名詞"].append(term.surface)
            for token in _TOKENIZER.tokenize(message.content):
                part = self._replaceable_part(token)
                if (
                    part in {"動詞", "形容詞"}
                    and any(char.isalnum() for char in token.surface)
                    and token.surface not in buckets[part]
                ):
                    buckets[part].append(token.surface)
        nouns = buckets["名詞"] or ["謎"]
        verbs = buckets["動詞"] or ["現れる"]
        adjectives = buckets["形容詞"] or ["あやしい"]
        luck = self._rng.choice(
            ("大吉", "中吉", "小吉", "末吉", "吉", "凶", "概念吉")
        )
        noun = self._rng.choice(nouns)
        second_noun = self._rng.choice(nouns)
        verb = self._rng.choice(verbs)
        adjective = self._rng.choice(adjectives)
        return (
            f"⛩️ **{luck}**\n"
            f"{noun}が{second_noun}を{verb}と、"
            f"{adjective}未来が来る。\n"
            f"ラッキー単語: **{self._rng.choice(nouns)}**"
        )

    def oracle_quote(
        self,
        dynamic_messages: list[MemoryMessage],
    ) -> str:
        """Frame one short memory as a dubious divine quotation."""
        candidates = [
            message
            for message in dynamic_messages
            if (
                4 <= len(message.content) <= 60
                and "\n" not in message.content
                and any(char.isalnum() for char in message.content)
            )
        ]
        if not candidates:
            candidates = [
                message
                for message in self._seed_messages
                if (
                    4 <= len(message.content) <= 60
                    and "\n" not in message.content
                )
            ]
        if not candidates:
            return "まだ名言にできる記憶がない。"

        base = self._rng.choice(candidates).content.strip()
        learned_words: list[str] = []
        sample = (
            candidates
            if len(candidates) <= 80
            else self._rng.sample(candidates, 80)
        )
        for message in sample:
            for term in _noun_terms(
                message.content,
                self._proper_nouns,
            ):
                if term.surface not in learned_words:
                    learned_words.append(term.surface)
        interpretation = (
            f"{self._rng.choice(learned_words)}の予兆"
            if learned_words
            else "たぶん何かの予兆"
        )
        attribution = self._rng.choice(
            ("神様、記憶より", "神様の雑な神託", "出典不明、たぶん神様")
        )
        return f"📜「{base}」\n— {attribution}\n解釈: {interpretation}"

    def judge_dispute(
        self,
        expression: str,
        dynamic_messages: list[MemoryMessage],
    ) -> str:
        """Choose between two sides and justify it with remembered nouns."""
        try:
            sides = shlex.split(expression)
        except ValueError:
            return '例: `裁判 猫 犬` または `裁判 "きのこの山" "たけのこの里"`'
        if len(sides) == 3 and sides[1].lower() in {"vs", "対"}:
            sides = [sides[0], sides[2]]
        elif len(sides) == 1:
            sides = [
                side.strip()
                for side in re.split(r"\s*(?:vs|対|、|,)\s*", sides[0])
                if side.strip()
            ]
        if len(sides) != 2:
            return '争う二者を指定してね。例: `裁判 猫 犬`'
        if any(not side or len(side) > 80 for side in sides):
            return "名前はそれぞれ1〜80文字にしてね。"

        winner_index = self._rng.randrange(2)
        winner = sides[winner_index]
        loser = sides[1 - winner_index]
        sources = dynamic_messages or self._seed_messages
        nouns: list[str] = []
        sample = (
            sources
            if len(sources) <= 100
            else self._rng.sample(sources, 100)
        )
        for message in sample:
            for term in _noun_terms(
                message.content,
                self._proper_nouns,
            ):
                if term.surface not in nouns:
                    nouns.append(term.surface)
        evidence = self._rng.choice(nouns) if nouns else "宇宙"
        reason = self._rng.choice(
            (
                f"「{evidence}」の加護が認められたため",
                f"記憶の中で「{evidence}」が証言したため",
                f"法廷に「{evidence}」の気配があったため",
            )
        )
        return (
            f"⚖️ **判決**\n"
            f"勝訴: 「{winner}」\n"
            f"敗訴: 「{loser}」\n"
            f"理由: {reason}。異議申し立てはrollで。"
        )

    def daily_lucky_item(
        self,
        dynamic_messages: list[MemoryMessage],
        day: date,
    ) -> str:
        """Build a stable adjective+noun lucky item for a JST calendar day."""
        sources = dynamic_messages or self._seed_messages
        nouns: list[str] = []
        modifiers: list[str] = []
        for message in sources:
            for term in _noun_terms(
                message.content,
                self._proper_nouns,
            ):
                if (
                    1 <= len(term.surface) <= 20
                    and term.surface not in nouns
                ):
                    nouns.append(term.surface)
            for token in _TOKENIZER.tokenize(message.content):
                parts = token.part_of_speech.split(",")
                if parts[0] == "形容詞":
                    adjective = (
                        token.base_form
                        if token.base_form not in {"", "*"}
                        else token.surface
                    )
                    if adjective not in modifiers:
                        modifiers.append(adjective)
                elif (
                    parts[0] == "名詞"
                    and len(parts) > 1
                    and parts[1] == "形容動詞語幹"
                ):
                    modifier = token.surface + "な"
                    if modifier not in modifiers:
                        modifiers.append(modifier)
        if not nouns:
            nouns = ["石"]
        if not modifiers:
            modifiers = [
                "不思議な",
                "あやしい",
                "やたら強い",
                "少し湿った",
                "概念的な",
            ]
        digest = hashlib.sha256(day.isoformat().encode("ascii")).digest()
        modifier_index = int.from_bytes(digest[:8], "big") % len(modifiers)
        noun_index = int.from_bytes(digest[8:16], "big") % len(nouns)
        return modifiers[modifier_index] + nouns[noun_index]

    def summarize_messages(
        self,
        messages: list[MemoryMessage],
    ) -> str:
        """Summarize a day as counts, frequent words, and one odd sentence."""
        if not messages:
            return "今日はまだ要約できる発言を覚えていないよ。"
        nouns: Counter[str] = Counter()
        verbs: Counter[str] = Counter()
        adjectives: Counter[str] = Counter()
        for message in messages:
            nouns.update(
                term.surface
                for term in _noun_terms(
                    message.content,
                    self._proper_nouns,
                )
            )
            for token in _TOKENIZER.tokenize(message.content):
                part = self._replaceable_part(token)
                if not any(char.isalnum() for char in token.surface):
                    continue
                if part == "動詞":
                    verbs[token.surface] += 1
                elif part == "形容詞":
                    adjectives[token.surface] += 1
        keywords = [
            word for word, _ in (nouns + verbs + adjectives).most_common(8)
        ]
        keyword_text = "、".join(keywords) if keywords else "特になし"
        noun_words = list(nouns) or ["みんな"]
        verb_words = list(verbs) or ["考えた"]
        adjective_words = list(adjectives) or ["不思議な"]
        odd_line = (
            f"{self._rng.choice(noun_words)}が"
            f"{self._rng.choice(adjective_words)}顔で"
            f"{self._rng.choice(verb_words)}日だった。"
        )
        authors = len({message.author_id for message in messages})
        return (
            f"今日の記憶: {len(messages)}件・{authors}人\n"
            f"頻出語: {keyword_text}\n"
            f"雑な要約: {odd_line}"
        )

    def _weighted_order(
        self,
        seed_indices: list[int],
        dynamic_indices: list[int],
    ) -> list[int]:
        seed = list(seed_indices)
        dynamic = list(dynamic_indices)
        self._rng.shuffle(seed)
        self._rng.shuffle(dynamic)
        ordered: list[int] = []
        while seed or dynamic:
            if seed and dynamic:
                use_seed = (
                    self._rng.random() < self._seed_corpus_weight
                )
            else:
                use_seed = bool(seed)
            ordered.append(
                seed.pop() if use_seed else dynamic.pop()
            )
        return ordered

    def _usable(self, messages: list[MemoryMessage], index: int) -> bool:
        if not 0 <= index < len(messages):
            return False
        message = messages[index]
        if message.message_id in self._recent_base_ids:
            return False
        if (
            self.recent_unused_messages > 0
            and len(messages) > self.recent_unused_messages
            and index >= len(messages) - self.recent_unused_messages
        ):
            return False
        return (
            bool(message.content)
            and len(message.content) <= self._max_reply_source_length
        )

    def _response_to(
        self,
        messages: list[MemoryMessage],
        prompt_index: int,
        *,
        drift: bool = False,
    ) -> tuple[int | None, int]:
        """Estimate a reply from the following five messages, like Reudy."""
        candidate_indices = [
            index
            for index in range(prompt_index + 1, prompt_index + 6)
            if self._usable(messages, index)
            and (
                messages[index].conversation_id
                == messages[prompt_index].conversation_id
            )
        ]
        if not candidate_indices:
            return None, 0
        if drift:
            return self._rng.choice(candidate_indices), 11

        prompt_words = extract_words(
            messages[prompt_index].content,
            self._proper_nouns,
        )
        response_index: int | None = None
        for word in prompt_words:
            containing = [
                index
                for index in candidate_indices
                if word in messages[index].content
            ]
            if containing:
                found = min(containing)
                if response_index is None or found < response_index:
                    response_index = found

        probability = 5 if response_index is not None else 0
        if response_index is None:
            response_index = candidate_indices[0]
        probability += 6 - (response_index - prompt_index)
        return response_index, probability

    def _base_using_similarity(
        self,
        input_text: str,
        messages: list[MemoryMessage],
        *,
        drift: bool = False,
    ) -> int | None:
        input_keys = tail_keys(input_text)
        if not input_keys:
            return None

        seed_prompt_index_set: set[int] = set()
        for key in input_keys:
            seed_prompt_index_set.update(
                self._seed_tail_index.get(key, ())
            )
        seed_count = len(self._seed_messages)
        dynamic_prompt_indices = [
            index
            for index in range(seed_count, len(messages))
            if tail_keys(messages[index].content) & input_keys
        ]
        prompt_indices = self._weighted_order(
            list(seed_prompt_index_set),
            dynamic_prompt_indices,
        )

        best_response: int | None = None
        best_probability = 0
        checked = 0
        for prompt_index in prompt_indices:
            response_index, probability = self._response_to(
                messages,
                prompt_index,
                drift=drift,
            )
            if response_index is None:
                continue
            if probability > best_probability:
                best_response = response_index
                best_probability = probability
            checked += 1
            if checked >= 5:
                break
        return best_response

    def _base_using_keyword(
        self,
        words: list[str],
        messages: list[MemoryMessage],
        *,
        drift: bool = False,
    ) -> int | None:
        shuffled_words = list(words)
        self._rng.shuffle(shuffled_words)

        best_response: int | None = None
        best_probability = 0
        checked = 0
        for word in shuffled_words:
            prompt_indices = [
                index
                for index, message in enumerate(messages)
                if word in message.content
            ]
            seed_count = len(self._seed_messages)
            prompt_indices = self._weighted_order(
                [
                    index
                    for index in prompt_indices
                    if index < seed_count
                ],
                [
                    index
                    for index in prompt_indices
                    if index >= seed_count
                ],
            )
            for prompt_index in prompt_indices:
                response_index, probability = self._response_to(
                    messages,
                    prompt_index,
                    drift=drift,
                )
                if response_index is None:
                    continue
                if probability > best_probability:
                    best_response = response_index
                    best_probability = probability
                checked += 1
                if checked >= 5:
                    return best_response
        return best_response

    def _replace_words(self, base: str, new_words: list[str]) -> str:
        old_words = [
            term.surface
            for term in _noun_terms(base, self._proper_nouns)
            if not term.proper
        ]
        if not old_words or not new_words:
            return base

        shuffled_new_words = list(new_words)
        self._rng.shuffle(shuffled_new_words)
        for new_word in shuffled_new_words:
            if not old_words:
                break
            compatible_words = [
                word
                for word in old_words
                if word.isascii() == new_word.isascii()
            ]
            old_word = self._rng.choice(compatible_words or old_words)
            base = base.replace(old_word, new_word)
            old_words = [
                new_word if word == old_word else word
                for word in old_words
            ]
            if self._rng.random() < 0.5:
                break

        if base.startswith("」") and "「" not in base:
            base = "「" + base
        elif base.startswith("）") and "（" not in base:
            base = "（" + base
        elif base.startswith(")") and "(" not in base:
            base = "(" + base
        return base

    def _random_base(self, messages: list[MemoryMessage]) -> int | None:
        seed_count = len(self._seed_messages)
        usable_seed = [
            index
            for index in range(seed_count)
            if self._usable(messages, index)
        ]
        usable_dynamic = [
            index
            for index in range(seed_count, len(messages))
            if self._usable(messages, index)
        ]
        if usable_seed and usable_dynamic:
            choices = (
                usable_seed
                if self._rng.random() < self._seed_corpus_weight
                else usable_dynamic
            )
        else:
            choices = usable_seed or usable_dynamic
        return self._rng.choice(choices) if choices else None

    def _distant_base(
        self,
        input_text: str,
        messages: list[MemoryMessage],
    ) -> int | None:
        """Choose a complete learned utterance that is unlike the input."""
        seed_count = len(self._seed_messages)
        sample_size = 256

        def sampled(pool: range) -> list[int]:
            candidates = (
                list(pool)
                if len(pool) <= sample_size * 3
                else self._rng.sample(pool, sample_size * 3)
            )
            usable = [
                index
                for index in candidates
                if self._usable(messages, index)
            ]
            if len(usable) <= sample_size:
                return usable
            return self._rng.sample(usable, sample_size)

        reference = self._text_vector(input_text)
        seed_indices = sampled(range(seed_count))
        dynamic_indices = sampled(range(seed_count, len(messages)))

        def distant(indices: list[int]) -> list[int]:
            scored = [
                (
                    self._cosine_similarity(
                        reference,
                        self._text_vector(messages[index].content),
                    ),
                    index,
                )
                for index in indices
            ]
            scored.sort(key=lambda item: item[0])
            if not scored:
                return []
            floor_size = min(40, max(1, len(scored) // 3))
            return [index for _, index in scored[:floor_size]]

        distant_seed = distant(seed_indices)
        distant_dynamic = distant(dynamic_indices)
        if distant_seed and distant_dynamic:
            choices = (
                distant_seed
                if self._rng.random() < self._seed_corpus_weight
                else distant_dynamic
            )
        else:
            choices = distant_seed or distant_dynamic
        return self._rng.choice(choices) if choices else None

    def _splice_words(
        self,
        base: str,
        base_index: int,
        messages: list[MemoryMessage],
        *,
        force: bool = False,
    ) -> str:
        """Splice two remembered utterances at Janome token boundaries."""
        if not force and self._rng.random() >= self._word_splice_rate:
            return base

        base_parts = [
            token.surface
            for token in _TOKENIZER.tokenize(base)
            if token.surface
        ]
        if len(base_parts) < 2:
            return base

        for donor_index in self._nearby_donor_indices(
            base, base_index, messages, limit=8
        ):
            donor_parts = [
                token.surface
                for token in _TOKENIZER.tokenize(messages[donor_index].content)
                if token.surface
            ]
            if len(donor_parts) < 2:
                continue
            base_cut = self._rng.randrange(1, len(base_parts))
            donor_cut = self._rng.randrange(1, len(donor_parts))
            if self._rng.random() < 0.5:
                parts = base_parts[:base_cut] + donor_parts[donor_cut:]
            else:
                parts = donor_parts[:donor_cut] + base_parts[base_cut:]
            spliced = "".join(parts).strip()
            if (
                spliced
                and spliced != base
                and len(spliced) <= self._max_reply_source_length
            ):
                return spliced
        return base

    def _text_vector(self, text: str) -> Counter[str]:
        vector: Counter[str] = Counter()
        for token in _TOKENIZER.tokenize(text):
            part = token.part_of_speech.split(",")[0]
            if part not in {"名詞", "動詞", "形容詞", "副詞"}:
                continue
            term = (
                token.base_form
                if token.base_form not in {"", "*"}
                else token.surface
            )
            if term:
                vector[f"{part}:{term}"] += 1
        for noun_term in _noun_terms(text, self._proper_nouns):
            if noun_term.proper:
                vector[f"固有:{noun_term.surface.casefold()}"] += 3
        compact = re.sub(r"\s+", "", text)
        for index in range(len(compact) - 1):
            vector[f"字:{compact[index:index + 2]}"] += 1
        return vector

    @staticmethod
    def _cosine_similarity(
        left: Counter[str], right: Counter[str]
    ) -> float:
        if not left or not right:
            return 0.0
        common = left.keys() & right.keys()
        dot = sum(left[key] * right[key] for key in common)
        left_norm = sum(value * value for value in left.values()) ** 0.5
        right_norm = sum(value * value for value in right.values()) ** 0.5
        return dot / (left_norm * right_norm)

    def _nearby_donor_indices(
        self,
        reference: str,
        base_index: int,
        messages: list[MemoryMessage],
        *,
        limit: int,
    ) -> list[int]:
        if len(messages) < 2:
            return []

        seed_count = len(self._seed_messages)
        sample_size = max(limit * 12, 48)

        def sampled(pool: range) -> list[int]:
            if len(pool) <= sample_size:
                return list(pool)
            return self._rng.sample(pool, sample_size)

        candidates = sampled(range(seed_count))
        candidates += sampled(range(seed_count, len(messages)))
        candidates = [
            index
            for index in candidates
            if index != base_index and self._usable(messages, index)
        ]
        self._rng.shuffle(candidates)
        reference_vector = self._text_vector(reference)
        scored = [
            (
                self._cosine_similarity(
                    reference_vector,
                    self._text_vector(messages[index].content),
                ),
                index,
            )
            for index in candidates
        ]
        scored.sort(key=lambda item: item[0], reverse=True)
        nearby = [index for score, index in scored if score > 0][
            : limit * 3
        ]
        self._rng.shuffle(nearby)
        return nearby[:limit]

    @staticmethod
    def _replaceable_part(token: object) -> str | None:
        parts = token.part_of_speech.split(",")
        if parts[0] == "名詞":
            if len(parts) > 1 and parts[1] in {"非自立", "代名詞", "数"}:
                return None
            return "名詞"
        if parts[0] in {"動詞", "形容詞"}:
            return parts[0]
        return None

    @staticmethod
    def _replaceable_noun(token: object) -> bool:
        """Limit mutation to concrete noun slots, not adjectival stems."""
        parts = token.part_of_speech.split(",")
        return (
            parts[0] == "名詞"
            and len(parts) > 1
            and parts[1] in {"一般", "固有名詞"}
        )

    def _mutate_words(
        self,
        base: str,
        base_index: int,
        messages: list[MemoryMessage],
        *,
        force: bool = False,
    ) -> str:
        """Replace up to two nouns while keeping the sentence structure."""
        if not force and self._rng.random() >= self._word_mutation_rate:
            return base

        tokens = list(_TOKENIZER.tokenize(base))
        protected_indices = {
            token_index
            for term in _noun_terms(base, self._proper_nouns)
            if term.proper
            for token_index in term.token_indices
        }
        replaceable = [
            index
            for index, token in enumerate(tokens)
            if (
                index not in protected_indices
                and self._replaceable_noun(token)
            )
        ]
        if not replaceable:
            return base

        donor_words: list[str] = []
        for donor_index in self._nearby_donor_indices(
            base, base_index, messages, limit=20
        ):
            donor_content = messages[donor_index].content
            donor_tokens = list(_TOKENIZER.tokenize(donor_content))
            donor_protected_indices = {
                token_index
                for term in _noun_terms(
                    donor_content,
                    self._proper_nouns,
                )
                if term.proper
                for token_index in term.token_indices
            }
            for token_index, token in enumerate(donor_tokens):
                if (
                    token_index not in donor_protected_indices
                    and self._replaceable_noun(token)
                    and token.surface not in donor_words
                ):
                    donor_words.append(token.surface)

        self._rng.shuffle(replaceable)
        changes = 0
        target_changes = min(2, len(replaceable))
        used_donor_words: set[str] = set()
        surfaces = [token.surface for token in tokens]
        for index in replaceable:
            choices = [
                word
                for word in donor_words
                if word != surfaces[index]
                and word not in used_donor_words
            ]
            if not choices:
                continue
            replacement = self._rng.choice(choices)
            surfaces[index] = replacement
            used_donor_words.add(replacement)
            changes += 1
            if changes >= target_changes:
                break
        mutated = "".join(surfaces).strip()
        if (
            changes
            and mutated
            and len(mutated) <= self._max_reply_source_length
        ):
            return mutated
        return base

    def respond(
        self,
        input_text: str,
        dynamic_messages: list[MemoryMessage],
    ) -> GeneratedReply | None:
        """Choose and mangle a response using Reudy's decision order."""
        messages = self._seed_messages + dynamic_messages
        new_words = list(extract_words(input_text, self._proper_nouns))
        drift = self._rng.random() < self._response_drift_rate
        if new_words:
            if self._rng.randrange(5) != 0:
                self._input_words = list(new_words)
            else:
                self._input_words.extend(
                    word for word in new_words if word not in self._input_words
                )

        base_index = (
            self._distant_base(input_text, messages)
            if drift
            else self._base_using_similarity(
                input_text,
                messages,
                drift=False,
            )
        )
        output: str | None = None

        if new_words:
            if base_index is not None:
                output = messages[base_index].content
            else:
                base_index = self._base_using_keyword(
                    new_words,
                    messages,
                    drift=drift,
                )
                if base_index is not None:
                    output = messages[base_index].content
        elif base_index is not None:
            output = messages[base_index].content
        elif self._input_words:
            base_index = self._base_using_keyword(
                self._input_words,
                messages,
                drift=drift,
            )
            if base_index is not None:
                output = messages[base_index].content

        # A direct call is Reudy's mustRespond mode: fall back to any memory.
        if output is None:
            base_index = self._random_base(messages)
            if base_index is not None:
                output = messages[base_index].content

        if output is None or base_index is None:
            return None

        # Noun replacement can make a short source unexpectedly long.
        # Keep the original short utterance instead of cutting it mid-sentence.
        if len(output) > self._max_reply_source_length:
            output = messages[base_index].content
        creative_roll = self._rng.random()
        if creative_roll < self._word_splice_rate:
            output = self._splice_words(
                output,
                base_index,
                messages,
                force=True,
            )
        elif creative_roll < (
            self._word_splice_rate + self._word_mutation_rate
        ):
            output = self._mutate_words(
                output,
                base_index,
                messages,
                force=True,
            )

        base_message_id = messages[base_index].message_id
        self._recent_base_ids.append(base_message_id)
        return GeneratedReply(
            text=output,
            base_message_id=base_message_id,
        )
