from __future__ import annotations

import random
import re

from janome.tokenizer import Tokenizer


_TOKENIZER = Tokenizer()
_CASUAL_SENTENCE_RE = re.compile(
    r"(?P<body>[^。.!！?？\n]+?)"
    r"(?P<polite>でした|です)"
    r"(?P<tone>よね|ね|よ|か)?"
    r"(?P<punctuation>[。.!！?？]*)"
    r"(?=$|\n|(?<=[。.!！?？]))"
)


def _needs_copula(text: str) -> bool:
    tokens = [
        token
        for token in _TOKENIZER.tokenize(text)
        if token.part_of_speech.split(",", 1)[0] != "記号"
    ]
    if not tokens:
        return False
    parts = tokens[-1].part_of_speech.split(",")
    return parts[0] == "名詞" or (
        parts[0] == "形容詞"
        and len(parts) > 1
        and parts[1] == "非自立"
    )


def _casual_sentence(match: re.Match[str]) -> str:
    body = match.group("body")
    polite = match.group("polite")
    tone = match.group("tone") or ""
    punctuation = match.group("punctuation")
    copula = _needs_copula(body)

    if polite == "でした":
        ending = "だった" if copula else ""
    else:
        ending = "だ" if copula else ""

    if tone == "か":
        ending = ("なの" if copula and polite == "です" else ending) + "？"
        punctuation = punctuation.lstrip("？?")
    elif tone:
        ending += tone
    return body + ending + punctuation


def apply_persona(text: str, persona: str) -> str:
    if persona == "normal":
        return text
    if persona == "casual":
        result = text
        replacements = (
            (r"ありがとうございます", "ありがとう"),
            (r"ではありませんか[？?]?", "じゃない？"),
            (r"ではありません", "じゃないよ"),
        )
        for pattern, replacement in replacements:
            result = re.sub(pattern, replacement, result)
        return _CASUAL_SENTENCE_RE.sub(_casual_sentence, result)
    if persona != "samurai":
        raise ValueError(f"unknown persona: {persona}")

    result = text
    replacements = (
        (r"ありがとうございます?", "かたじけない"),
        (r"(?:私|わたし|あたし|俺|僕)", "拙者"),
        (r"(?:あなた|あんた|お前|おまえ)", "おぬし"),
        (r"ください", "くだされ"),
        (r"ません", "ませぬ"),
        (r"でしょう", "でござろう"),
        (r"です", "でござる"),
        (r"ます", "まする"),
    )
    for pattern, replacement in replacements:
        result = re.sub(pattern, replacement, result)

    result = result.replace("...", "、、、").replace("…", "、、、")
    return result


def apply_cute_tone(
    text: str,
    *,
    rate: float = 0.35,
    rng: random.Random | None = None,
) -> str:
    """Occasionally add a soft, cute tail to a conversational reply."""
    chooser = rng or random
    if not text or chooser.random() >= rate:
        return text
    if text.rstrip().endswith(
        ("うにゃ〜", "うにゃー", "なのだ〜", "のだ〜")
    ):
        return text

    match = re.fullmatch(
        r"(?P<body>.*?)(?P<punctuation>[。.!！?？…]*)",
        text,
        flags=re.DOTALL,
    )
    if match is None:
        return text
    body = match.group("body").rstrip()
    punctuation = match.group("punctuation")
    if not body:
        return text

    if body.endswith(("よ", "ね")):
        return text
    elif body.endswith("だ"):
        ending = chooser.choice(("よ", "ね", "にゃ", "うにゃ〜"))
    elif _needs_copula(body):
        ending = chooser.choice(
            ("だよ", "だね", "なのだ", "にゃ", "うにゃ〜")
        )
    else:
        ending = chooser.choice(
            ("よ", "ね", "のだ", "にゃ", "うにゃ〜")
        )
    return body + ending + punctuation
