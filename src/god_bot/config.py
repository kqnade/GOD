from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _required_int(name: str) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        raise ValueError(f"{name} is required")
    return int(raw)


def _int(name: str, default: int, *, minimum: int = 0) -> int:
    value = int(os.getenv(name, str(default)))
    if value < minimum:
        raise ValueError(f"{name} must be at least {minimum}")
    return value


def _float(name: str, default: float, *, minimum: float = 0.0) -> float:
    value = float(os.getenv(name, str(default)))
    if value < minimum:
        raise ValueError(f"{name} must be at least {minimum}")
    return value


@dataclass(frozen=True, slots=True)
class Config:
    token: str
    database_path: Path
    seed_corpus_path: Path | None
    seed_corpus_weight: float
    target_guild_id: int
    target_channel_id: int
    trigger_words: tuple[str, ...]
    persona: str
    retention_days: int
    max_messages_per_channel: int
    candidate_pool_size: int
    recent_unused_messages: int
    repeat_proof_messages: int
    reply_cooldown_seconds: float
    max_message_length: int
    max_reply_source_length: int
    response_drift_rate: float
    word_splice_rate: float
    word_mutation_rate: float
    cute_tone_rate: float

    @classmethod
    def from_env(cls) -> "Config":
        token = os.getenv("DISCORD_TOKEN", "").strip()
        if not token:
            raise ValueError("DISCORD_TOKEN is required")

        persona = os.getenv("BOT_PERSONA", "normal").strip().lower()
        if persona not in {"normal", "casual", "samurai"}:
            raise ValueError(
                "BOT_PERSONA must be 'normal', 'casual', or 'samurai'"
            )

        trigger_words = tuple(
            word.strip()
            for word in os.getenv("TRIGGER_WORDS", "神,仏").split(",")
            if word.strip()
        )
        corpus_value = os.getenv(
            "SEED_CORPUS_PATH",
            "corpus/real_persona_chat.txt",
        ).strip()
        seed_corpus_weight = _float("SEED_CORPUS_WEIGHT", 0.15)
        if seed_corpus_weight > 1:
            raise ValueError(
                "SEED_CORPUS_WEIGHT must be between 0 and 1"
            )
        response_drift_rate = _float("RESPONSE_DRIFT_RATE", 0.85)
        if response_drift_rate > 1:
            raise ValueError(
                "RESPONSE_DRIFT_RATE must be between 0 and 1"
            )
        word_splice_rate = _float("WORD_SPLICE_RATE", 0.0)
        if word_splice_rate > 1:
            raise ValueError("WORD_SPLICE_RATE must be between 0 and 1")
        word_mutation_rate = _float("WORD_MUTATION_RATE", 0.35)
        if word_mutation_rate > 1:
            raise ValueError("WORD_MUTATION_RATE must be between 0 and 1")
        cute_tone_rate = _float("CUTE_TONE_RATE", 0.35)
        if cute_tone_rate > 1:
            raise ValueError("CUTE_TONE_RATE must be between 0 and 1")

        return cls(
            token=token,
            database_path=Path(
                os.getenv("DATABASE_PATH", "data/memory.sqlite3")
            ).expanduser(),
            seed_corpus_path=(
                Path(corpus_value).expanduser()
                if corpus_value
                else None
            ),
            seed_corpus_weight=seed_corpus_weight,
            target_guild_id=_required_int("TARGET_GUILD_ID"),
            target_channel_id=_required_int("TARGET_CHANNEL_ID"),
            trigger_words=trigger_words,
            persona=persona,
            retention_days=_int("MEMORY_RETENTION_DAYS", 90),
            max_messages_per_channel=_int(
                "MAX_MESSAGES_PER_CHANNEL", 10_000, minimum=2
            ),
            candidate_pool_size=_int(
                "CANDIDATE_POOL_SIZE", 10_000, minimum=1
            ),
            recent_unused_messages=_int("RECENT_UNUSED_MESSAGES", 100),
            repeat_proof_messages=_int(
                "REPEAT_PROOF_MESSAGES", 50, minimum=1
            ),
            reply_cooldown_seconds=_float("REPLY_COOLDOWN_SECONDS", 5.0),
            max_message_length=_int("MAX_MESSAGE_LENGTH", 500, minimum=1),
            max_reply_source_length=_int(
                "MAX_REPLY_SOURCE_LENGTH", 20, minimum=1
            ),
            response_drift_rate=response_drift_rate,
            word_splice_rate=word_splice_rate,
            word_mutation_rate=word_mutation_rate,
            cute_tone_rate=cute_tone_rate,
        )
