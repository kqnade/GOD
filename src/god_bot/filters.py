from __future__ import annotations

import re
import unicodedata

_URL_RE = re.compile(r"(?:https?://|www\.)\S+", re.IGNORECASE)
_EMAIL_RE = re.compile(r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b")
_CODE_FENCE_RE = re.compile(r"```|`[^`]+`")
_DISCORD_USER_MENTION_RE = re.compile(r"<@!?\d+>")
_DISCORD_CHANNEL_MENTION_RE = re.compile(r"<#\d+>")
_DISCORD_ROLE_MENTION_RE = re.compile(r"<@&\d+>")
_SECRET_RE = re.compile(
    r"(?:"
    r"-----BEGIN [A-Z ]+PRIVATE KEY-----|"
    r"\b(?:api[_-]?key|access[_-]?token|client[_-]?secret|password)\s*[:=]|"
    r"\b(?:gh[pousr]_[A-Za-z0-9_]{20,}|sk-[A-Za-z0-9_-]{20,})"
    r")",
    re.IGNORECASE,
)
_CODEISH_RE = re.compile(
    r"(?:"
    r"\b(?:const|let|var|def|class|function|SELECT|INSERT|UPDATE|DELETE)\b|"
    r"=>|::|[{}]\s*;?|;\s*$"
    r")",
    re.IGNORECASE,
)
_SPACE_RE = re.compile(r"\s+")


def prepare_message(
    raw: str,
    *,
    bot_user_id: int | None = None,
    max_length: int = 500,
) -> str | None:
    """Return safe learnable text, or None when the message must be ignored."""
    text = unicodedata.normalize("NFKC", raw).strip()
    if not text or len(text) > max_length:
        return None

    if (
        _URL_RE.search(text)
        or _EMAIL_RE.search(text)
        or _CODE_FENCE_RE.search(text)
        or _SECRET_RE.search(text)
        or _CODEISH_RE.search(text)
    ):
        return None

    if text.startswith(("/", "!", "$")) or text.count("\n") > 2:
        return None

    if bot_user_id is not None:
        text = re.sub(fr"<@!?{bot_user_id}>", "", text)

    text = _DISCORD_USER_MENTION_RE.sub("誰か", text)
    text = _DISCORD_CHANNEL_MENTION_RE.sub("チャンネル", text)
    text = _DISCORD_ROLE_MENTION_RE.sub("みんな", text)
    text = text.replace("@everyone", "みんな").replace("@here", "みんな")
    text = _SPACE_RE.sub(" ", text).strip()

    if not text or not any(char.isalnum() for char in text):
        return None
    return text


def prepare_corpus_message(
    raw: str,
    *,
    max_length: int = 500,
) -> str | None:
    """Apply only safety filters appropriate for an already-curated corpus."""
    text = unicodedata.normalize("NFKC", raw).strip()
    if not text or len(text) > max_length:
        return None
    if (
        _URL_RE.search(text)
        or _EMAIL_RE.search(text)
        or _SECRET_RE.search(text)
    ):
        return None
    text = _SPACE_RE.sub(" ", text).strip()
    return text or None


def sanitize_reply(text: str, *, max_length: int = 1_800) -> str:
    """Make remembered text safe to send back to Discord."""
    text = text.replace("@", "＠").replace("\x00", "")
    return text[:max_length].strip()
