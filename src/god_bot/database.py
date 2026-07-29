from __future__ import annotations

import sqlite3
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from .generator import MemoryMessage
from .proper_nouns import normalize_proper_noun, proper_noun_key


@dataclass(frozen=True, slots=True)
class MemoryStats:
    messages: int


class MemoryRepository:
    def __init__(self, path: Path) -> None:
        self.path = path

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 10000")
        return connection

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = self._connect()
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connection() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS messages (
                    discord_message_id INTEGER PRIMARY KEY,
                    guild_id INTEGER NOT NULL,
                    channel_id INTEGER NOT NULL,
                    author_id INTEGER NOT NULL,
                    content TEXT NOT NULL,
                    created_at REAL NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_messages_channel_time
                    ON messages (guild_id, channel_id, created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_messages_author
                    ON messages (guild_id, author_id);

                CREATE TABLE IF NOT EXISTS proper_nouns (
                    guild_id INTEGER NOT NULL,
                    term TEXT NOT NULL,
                    normalized_term TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    PRIMARY KEY (guild_id, normalized_term)
                );

                """
            )

    def learn_message(
        self,
        *,
        message_id: int,
        guild_id: int,
        channel_id: int,
        author_id: int,
        content: str,
        created_at: float,
        max_messages: int,
    ) -> bool:
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            duplicate = connection.execute(
                "SELECT 1 FROM messages WHERE discord_message_id = ?",
                (message_id,),
            ).fetchone()
            if duplicate:
                connection.rollback()
                return False

            connection.execute(
                """
                INSERT INTO messages (
                    discord_message_id, guild_id, channel_id,
                    author_id, content, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    message_id,
                    guild_id,
                    channel_id,
                    author_id,
                    content,
                    created_at,
                ),
            )

            connection.execute(
                """
                DELETE FROM messages
                WHERE discord_message_id IN (
                    SELECT discord_message_id
                    FROM messages
                    WHERE guild_id = ? AND channel_id = ?
                    ORDER BY created_at DESC, discord_message_id DESC
                    LIMIT -1 OFFSET ?
                )
                """,
                (guild_id, channel_id, max_messages),
            )
            connection.commit()
            return True
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def memory_messages(
        self, guild_id: int, channel_id: int, *, limit: int
    ) -> list[MemoryMessage]:
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT discord_message_id, author_id, content
                FROM (
                    SELECT discord_message_id, author_id, content, created_at
                    FROM messages
                    WHERE guild_id = ? AND channel_id = ?
                    ORDER BY created_at DESC, discord_message_id DESC
                    LIMIT ?
                )
                ORDER BY created_at ASC, discord_message_id ASC
                """,
                (guild_id, channel_id, limit),
            ).fetchall()
        return [
            MemoryMessage(
                message_id=row["discord_message_id"],
                author_id=row["author_id"],
                content=row["content"],
                conversation_id=-1,
            )
            for row in rows
        ]

    def memory_messages_since(
        self,
        guild_id: int,
        channel_id: int,
        *,
        since: float,
        limit: int,
    ) -> list[MemoryMessage]:
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT discord_message_id, author_id, content
                FROM messages
                WHERE guild_id = ? AND channel_id = ? AND created_at >= ?
                ORDER BY created_at ASC, discord_message_id ASC
                LIMIT ?
                """,
                (guild_id, channel_id, since, limit),
            ).fetchall()
        return [
            MemoryMessage(
                message_id=row["discord_message_id"],
                author_id=row["author_id"],
                content=row["content"],
                conversation_id=-1,
            )
            for row in rows
        ]

    def update_message(self, message_id: int, content: str) -> bool:
        with self._connection() as connection:
            cursor = connection.execute(
                """
                UPDATE messages SET content = ?
                WHERE discord_message_id = ?
                """,
                (content, message_id),
            )
        return cursor.rowcount > 0

    def delete_message(self, message_id: int) -> bool:
        with self._connection() as connection:
            cursor = connection.execute(
                "DELETE FROM messages WHERE discord_message_id = ?",
                (message_id,),
            )
        return cursor.rowcount > 0

    def forget_user(self, guild_id: int, author_id: int) -> int:
        with self._connection() as connection:
            cursor = connection.execute(
                """
                DELETE FROM messages
                WHERE guild_id = ? AND author_id = ?
                """,
                (guild_id, author_id),
            )
        return cursor.rowcount

    def purge_channel(self, guild_id: int, channel_id: int) -> int:
        with self._connection() as connection:
            cursor = connection.execute(
                """
                DELETE FROM messages
                WHERE guild_id = ? AND channel_id = ?
                """,
                (guild_id, channel_id),
            )
        return cursor.rowcount

    def purge_expired(self, retention_days: int) -> int:
        if retention_days <= 0:
            return 0
        threshold = time.time() - retention_days * 86_400
        with self._connection() as connection:
            cursor = connection.execute(
                "DELETE FROM messages WHERE created_at < ?",
                (threshold,),
            )
        return cursor.rowcount

    def purge_low_value_messages(
        self,
        guild_id: int,
        channel_id: int,
        *,
        max_length: int = 3,
    ) -> int:
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT discord_message_id, content
                FROM messages
                WHERE guild_id = ? AND channel_id = ?
                """,
                (guild_id, channel_id),
            ).fetchall()
            message_ids = [
                row["discord_message_id"]
                for row in rows
                if len(row["content"]) <= max_length
                or not any(char.isalnum() for char in row["content"])
            ]
            connection.executemany(
                "DELETE FROM messages WHERE discord_message_id = ?",
                ((message_id,) for message_id in message_ids),
            )
        return len(message_ids)

    def stats(self, guild_id: int, channel_id: int) -> MemoryStats:
        with self._connection() as connection:
            messages = connection.execute(
                """
                SELECT COUNT(*) FROM messages
                WHERE guild_id = ? AND channel_id = ?
                """,
                (guild_id, channel_id),
            ).fetchone()[0]
        return MemoryStats(messages=messages)

    def add_proper_noun(self, guild_id: int, term: str) -> bool:
        normalized = normalize_proper_noun(term)
        key = proper_noun_key(normalized)
        with self._connection() as connection:
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO proper_nouns (
                    guild_id, term, normalized_term, created_at
                ) VALUES (?, ?, ?, ?)
                """,
                (guild_id, normalized, key, time.time()),
            )
        return cursor.rowcount > 0

    def remove_proper_noun(self, guild_id: int, term: str) -> bool:
        key = proper_noun_key(term)
        with self._connection() as connection:
            cursor = connection.execute(
                """
                DELETE FROM proper_nouns
                WHERE guild_id = ? AND normalized_term = ?
                """,
                (guild_id, key),
            )
        return cursor.rowcount > 0

    def proper_nouns(self, guild_id: int) -> tuple[str, ...]:
        """Load the guild dictionary in one query for in-memory use."""
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT term
                FROM proper_nouns
                WHERE guild_id = ?
                ORDER BY normalized_term
                """,
                (guild_id,),
            ).fetchall()
        return tuple(row["term"] for row in rows)
