from __future__ import annotations

import re
import unicodedata

MAX_PROPER_NOUN_LENGTH = 80
_WHITESPACE_RE = re.compile(r"\s+")


def normalize_proper_noun(value: str) -> str:
    """Return a safe, display-ready dictionary entry."""
    normalized = unicodedata.normalize("NFKC", value)
    normalized = _WHITESPACE_RE.sub(" ", normalized).strip()
    if not normalized:
        raise ValueError("固有名詞を入力してください。")
    if len(normalized) > MAX_PROPER_NOUN_LENGTH:
        raise ValueError(
            f"固有名詞は{MAX_PROPER_NOUN_LENGTH}文字以内にしてください。"
        )
    if any(unicodedata.category(char).startswith("C") for char in normalized):
        raise ValueError("制御文字を含む固有名詞は登録できません。")
    if not any(char.isalnum() for char in normalized):
        raise ValueError("文字または数字を含む固有名詞を入力してください。")
    return normalized


def proper_noun_key(value: str) -> str:
    """Return a normalization and case-insensitive uniqueness key."""
    return normalize_proper_noun(value).casefold()
