from __future__ import annotations

import asyncio
import logging
import math
import random
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from io import BytesIO
from pathlib import Path

import discord
from discord import app_commands

from .amedas import AmedasError, latest_amedas_image
from .commands import build_dictionary_group, build_memory_group
from .config import Config
from .database import MemoryRepository
from .earthquake import EarthquakeError, latest_earthquake
from .filters import prepare_message, sanitize_reply
from .generator import ReudyEngine, load_seed_corpus
from .lisp import LispError, evaluate_lisp
from .persona import apply_cute_tone, apply_persona
from .qr import QrError, make_qr_image
from .scheduler import JST, is_sleeping_time, next_lifecycle_event
from .utilities import (
    HELP_TEXT,
    CalculationError,
    calculate,
    choose_option,
    convert_unit,
    current_weather,
    dns_lookup,
    domain_whois,
    format_bytes,
    format_duration,
    generate_password,
    hash_text,
    ip_lookup,
    parse_utility_command,
    pc_status,
    roll_dice,
    text_stats,
    tls_certificate_info,
)

LOGGER = logging.getLogger(__name__)
CONFUSED_FALLBACKS = (
    "よくわからない。",
    "そうなの？",
    "何の話だっけ。",
    "たぶん。",
    "不確定だ。",
)


class LearningBot(discord.Client):
    def __init__(self, config: Config) -> None:
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(
            intents=intents,
            allowed_mentions=discord.AllowedMentions.none(),
        )
        self.config = config
        self.repository = MemoryRepository(config.database_path)
        self._seed_memories = load_seed_corpus(config.seed_corpus_path)
        self._engine = ReudyEngine(
            seed_messages=self._seed_memories,
            seed_corpus_weight=self.config.seed_corpus_weight,
            recent_unused_messages=self.config.recent_unused_messages,
            repeat_proof_messages=self.config.repeat_proof_messages,
            max_reply_source_length=self.config.max_reply_source_length,
            response_drift_rate=self.config.response_drift_rate,
            word_splice_rate=self.config.word_splice_rate,
            word_mutation_rate=self.config.word_mutation_rate,
        )
        self.tree = app_commands.CommandTree(self)
        self._last_reply_at: defaultdict[int, float] = defaultdict(float)
        self._started_at = time.monotonic()
        self._greeting_sent = False
        self._farewell_sent = False
        self._sleeping = is_sleeping_time(datetime.now(timezone.utc))
        self._lifecycle_task: asyncio.Task[None] | None = None

    async def setup_hook(self) -> None:
        await asyncio.to_thread(self.repository.initialize)
        deleted = await asyncio.to_thread(
            self.repository.purge_expired,
            self.config.retention_days,
        )
        if deleted:
            LOGGER.info("Purged %d expired messages", deleted)
        low_value_deleted = await asyncio.to_thread(
            self.repository.purge_low_value_messages,
            self.config.target_guild_id,
            self.config.target_channel_id,
        )
        if low_value_deleted:
            LOGGER.info(
                "Purged %d short or symbol-only messages",
                low_value_deleted,
            )
        LOGGER.info(
            "Loaded %d seed corpus messages",
            len(self._seed_memories),
        )
        proper_nouns = await asyncio.to_thread(
            self.repository.proper_nouns,
            self.config.target_guild_id,
        )
        self._engine.set_proper_nouns(proper_nouns)
        LOGGER.info(
            "Loaded %d custom proper nouns",
            len(proper_nouns),
        )

        self.tree.add_command(
            build_memory_group(
                self.repository,
                self._reset_memory_state,
                target_guild_id=self.config.target_guild_id,
                target_channel_id=self.config.target_channel_id,
            )
        )
        self.tree.add_command(
            build_dictionary_group(
                self.repository,
                self._engine.add_proper_noun,
                self._engine.remove_proper_noun,
                target_guild_id=self.config.target_guild_id,
            )
        )
        self.tree.on_error = self._on_app_command_error

        guild = discord.Object(id=self.config.target_guild_id)
        self.tree.copy_global_to(guild=guild)
        try:
            await self.tree.sync(guild=guild)
        except discord.Forbidden:
            LOGGER.warning(
                "Could not sync commands to target guild %d: missing access. "
                "The bot will continue without slash commands.",
                self.config.target_guild_id,
            )
        else:
            LOGGER.info(
                "Synced commands to target guild %d",
                self.config.target_guild_id,
            )

    async def on_ready(self) -> None:
        LOGGER.info(
            "Logged in as %s (%s)",
            self.user,
            self.user.id if self.user else "?",
        )
        guild = self.get_guild(self.config.target_guild_id)
        if guild is None:
            LOGGER.error(
                "Target guild %d is not visible to this bot. "
                "Check TARGET_GUILD_ID and invite the bot to that server.",
                self.config.target_guild_id,
            )
            return
        channel = guild.get_channel(self.config.target_channel_id)
        if channel is None:
            LOGGER.error(
                "Target channel %d is not visible in guild %d. "
                "Check TARGET_CHANNEL_ID and the bot's channel permissions.",
                self.config.target_channel_id,
                self.config.target_guild_id,
            )
            return
        LOGGER.info(
            "Listening to target guild %d, channel %d",
            self.config.target_guild_id,
            self.config.target_channel_id,
        )
        self._sleeping = is_sleeping_time(datetime.now(timezone.utc))
        LOGGER.info(
            "Conversation mode is %s",
            "sleeping (utility commands only)" if self._sleeping else "awake",
        )
        if not self._sleeping and not self._greeting_sent:
            await self._send_morning_greeting(channel)
        if (
            self._lifecycle_task is None
            or self._lifecycle_task.done()
        ):
            self._lifecycle_task = asyncio.create_task(
                self._lifecycle_loop(),
                name="daily-lifecycle",
            )

    async def _send_morning_greeting(self, channel: object) -> None:
        try:
            memories = await asyncio.to_thread(
                self.repository.memory_messages,
                self.config.target_guild_id,
                self.config.target_channel_id,
                limit=self.config.candidate_pool_size,
            )
            lucky_item = self._engine.daily_lucky_item(
                memories,
                datetime.now(JST).date(),
            )
            await channel.send(
                "おはよう！\n"
                f"今日のラッキーアイテム: **{lucky_item}**",
                allowed_mentions=discord.AllowedMentions.none(),
            )
        except (discord.Forbidden, discord.HTTPException):
            LOGGER.exception("Could not send morning greeting")
        else:
            self._greeting_sent = True
            self._farewell_sent = False

    async def _send_sleep_warning(self, channel: object) -> None:
        embed = discord.Embed(
            title="🌙 そろそろ眠たくなってきた…",
            description="23:30から06:00までは、便利コマンドだけ使えるよ。",
            color=0x5865F2,
        )
        embed.set_footer(text="神様の就寝予告")
        try:
            await channel.send(
                embed=embed,
                allowed_mentions=discord.AllowedMentions.none(),
            )
        except (discord.Forbidden, discord.HTTPException):
            LOGGER.exception("Could not send daily sleep warning")
        else:
            LOGGER.info("Sent daily sleep warning")

    async def _send_bedtime(self, channel: object) -> None:
        self._sleeping = True
        self._greeting_sent = False
        try:
            await channel.send(
                "おやすみー",
                allowed_mentions=discord.AllowedMentions.none(),
            )
        except (discord.Forbidden, discord.HTTPException):
            LOGGER.exception("Could not send bedtime message")
        else:
            self._farewell_sent = True
        LOGGER.info("Conversation mode changed to sleeping")

    async def _lifecycle_loop(self) -> None:
        while not self.is_closed():
            now = datetime.now(timezone.utc)
            event = next_lifecycle_event(now)
            LOGGER.info(
                "Next lifecycle event %s scheduled for %s",
                event.name,
                event.at.isoformat(),
            )
            await asyncio.sleep(max(0.0, (event.at - now).total_seconds()))
            channel = self.get_channel(self.config.target_channel_id)
            if channel is None or not hasattr(channel, "send"):
                LOGGER.warning("Could not find channel for lifecycle event")
                continue
            if event.name == "sleep_warning":
                await self._send_sleep_warning(channel)
            elif event.name == "sleep":
                await self._send_bedtime(channel)
            else:
                self._sleeping = False
                await self._send_morning_greeting(channel)
                LOGGER.info("Conversation mode changed to awake")

    async def close(self) -> None:
        if self._lifecycle_task is not None:
            self._lifecycle_task.cancel()
            try:
                await self._lifecycle_task
            except asyncio.CancelledError:
                pass
            self._lifecycle_task = None
        if self._greeting_sent and not self._farewell_sent:
            self._farewell_sent = True
            channel = self.get_channel(self.config.target_channel_id)
            if channel is not None and hasattr(channel, "send"):
                try:
                    await channel.send(
                        "おやすみー",
                        allowed_mentions=discord.AllowedMentions.none(),
                    )
                except (discord.Forbidden, discord.HTTPException):
                    LOGGER.exception("Could not send shutdown farewell")
        await super().close()

    def _reset_memory_state(self) -> None:
        self._engine.reset_state()

    async def _on_app_command_error(
        self,
        interaction: discord.Interaction,
        error: app_commands.AppCommandError,
    ) -> None:
        if isinstance(error, app_commands.MissingPermissions):
            message = "この操作には「サーバーの管理」権限が必要です。"
        elif (
            isinstance(error, app_commands.CheckFailure)
            and interaction.response.is_done()
        ):
            return
        elif isinstance(error, app_commands.CheckFailure):
            message = (
                f"このBotの対象は "
                f"<#{self.config.target_channel_id}> だけです。"
            )
        else:
            LOGGER.exception("Application command failed", exc_info=error)
            message = "コマンドの実行中にエラーが発生しました。"

        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)

    async def on_message(self, message: discord.Message) -> None:
        if (
            self.user is None
            or message.guild is None
            or message.guild.id != self.config.target_guild_id
            or message.author.bot
            or message.webhook_id is not None
        ):
            return

        is_target_channel = (
            message.channel.id == self.config.target_channel_id
        )
        command_source = (
            message.content.replace(f"<@{self.user.id}>", "")
            .replace(f"<@!{self.user.id}>", "")
            .strip()
        )
        utility_command = parse_utility_command(command_source)
        text = prepare_message(
            message.content,
            bot_user_id=self.user.id,
            max_length=self.config.max_message_length,
        )
        if text is None and utility_command is None:
            return
        text = text or ""

        explicitly_called = (
            self.user in message.mentions
            or any(word in text for word in self.config.trigger_words)
        )
        if utility_command is None:
            utility_command = parse_utility_command(text)
        should_reply = (
            is_target_channel
            or explicitly_called
            or utility_command is not None
        )
        if self._sleeping and utility_command is None:
            return

        if (
            is_target_channel
            and utility_command is None
            and len(text) > 3
            and any(char.isalnum() for char in text)
        ):
            await asyncio.to_thread(
                self.repository.learn_message,
                message_id=message.id,
                guild_id=message.guild.id,
                channel_id=message.channel.id,
                author_id=message.author.id,
                content=text,
                created_at=message.created_at.timestamp(),
                max_messages=self.config.max_messages_per_channel,
            )

        if not should_reply:
            return

        now = time.monotonic()
        if (
            not is_target_channel
            and self.user not in message.mentions
            and now - self._last_reply_at[message.channel.id]
            < self.config.reply_cooldown_seconds
        ):
            return

        if utility_command is not None:
            reply_file: discord.File | None = None
            if utility_command.name == "help":
                reply = HELP_TEXT
            elif utility_command.name == "status":
                stats = await asyncio.to_thread(
                    self.repository.stats,
                    message.guild.id,
                    self.config.target_channel_id,
                )
                database_paths = (
                    self.config.database_path,
                    Path(str(self.config.database_path) + "-wal"),
                    Path(str(self.config.database_path) + "-shm"),
                )
                database_size = sum(
                    path.stat().st_size
                    for path in database_paths
                    if path.exists()
                )
                latency_ms = self.latency * 1_000
                latency = (
                    f"{latency_ms:.0f}ms"
                    if math.isfinite(latency_ms)
                    else "不明"
                )
                reply = (
                    "**神様の状態**\n"
                    f"モード: "
                    f"{'睡眠中（便利コマンドのみ）' if self._sleeping else '起きてる'}\n"
                    f"稼働時間: "
                    f"{format_duration(time.monotonic() - self._started_at)}\n"
                    f"Discord遅延: {latency}\n"
                    f"学習済み発言: {stats.messages}件\n"
                    f"SQLite: {format_bytes(database_size)}"
                )
            elif utility_command.name == "pc":
                proc_root = (
                    Path("/host/proc")
                    if Path("/host/proc").is_dir()
                    else Path("/proc")
                )
                reply = await asyncio.to_thread(
                    pc_status,
                    proc_root=proc_root,
                    disk_path=self.config.database_path.parent,
                )
            elif utility_command.name == "ping":
                latency_ms = self.latency * 1_000
                reply = (
                    f"pong! {latency_ms:.0f}ms"
                    if math.isfinite(latency_ms)
                    else "pong!"
                )
            elif utility_command.name == "calc":
                try:
                    result = calculate(utility_command.argument)
                except CalculationError as error:
                    reply = str(error)
                else:
                    reply = f"答えは {result}"
            elif utility_command.name == "unit":
                reply = convert_unit(utility_command.argument)
            elif utility_command.name == "hash":
                reply = hash_text(utility_command.argument)
            elif utility_command.name == "文字数":
                reply = text_stats(utility_command.argument)
            elif utility_command.name == "qr":
                try:
                    qr_image = await asyncio.to_thread(
                        make_qr_image,
                        utility_command.argument,
                    )
                except QrError as error:
                    reply = str(error)
                else:
                    reply = qr_image.caption
                    reply_file = discord.File(
                        BytesIO(qr_image.data),
                        filename=qr_image.filename,
                    )
            elif utility_command.name == "password":
                reply = generate_password(utility_command.argument)
            elif utility_command.name == "tls":
                reply = await asyncio.to_thread(
                    tls_certificate_info,
                    utility_command.argument,
                )
            elif utility_command.name == "lisp":
                try:
                    result = await asyncio.wait_for(
                        asyncio.to_thread(
                            evaluate_lisp,
                            utility_command.argument,
                        ),
                        timeout=1.0,
                    )
                except TimeoutError:
                    reply = "Lispエラー: 評価が1秒を超えたよ"
                except LispError as error:
                    reply = f"Lispエラー: {error}"
                else:
                    reply = f"=> `{result}`"
            elif utility_command.name == "地震":
                try:
                    reply = await asyncio.wait_for(
                        asyncio.to_thread(latest_earthquake),
                        timeout=15.0,
                    )
                except TimeoutError:
                    reply = "地震情報の取得がタイムアウトしたよ。"
                except EarthquakeError as error:
                    reply = str(error)
            elif utility_command.name == "アメダス":
                try:
                    amedas_image = await asyncio.wait_for(
                        asyncio.to_thread(
                            latest_amedas_image,
                            utility_command.argument,
                        ),
                        timeout=30.0,
                    )
                except TimeoutError:
                    reply = "アメダス画像の作成がタイムアウトしたよ。"
                except AmedasError as error:
                    reply = str(error)
                else:
                    reply = amedas_image.caption
                    reply_file = discord.File(
                        BytesIO(amedas_image.data),
                        filename=amedas_image.filename,
                    )
            elif utility_command.name == "天気":
                reply = await asyncio.to_thread(
                    current_weather,
                    utility_command.argument,
                )
            elif utility_command.name == "whois":
                reply = await asyncio.to_thread(
                    domain_whois,
                    utility_command.argument,
                )
            elif utility_command.name == "ip":
                reply = await asyncio.to_thread(
                    ip_lookup,
                    utility_command.argument,
                )
            elif utility_command.name == "roll":
                reply = roll_dice(utility_command.argument)
            elif utility_command.name == "choice":
                reply = choose_option(utility_command.argument)
            elif utility_command.name == "dns":
                reply = await asyncio.to_thread(
                    dns_lookup,
                    utility_command.argument,
                )
            elif utility_command.name == "おみくじ":
                memories = await asyncio.to_thread(
                    self.repository.memory_messages,
                    message.guild.id,
                    self.config.target_channel_id,
                    limit=self.config.candidate_pool_size,
                )
                reply = self._engine.fortune(memories)
            elif utility_command.name == "名言":
                memories = await asyncio.to_thread(
                    self.repository.memory_messages,
                    message.guild.id,
                    self.config.target_channel_id,
                    limit=self.config.candidate_pool_size,
                )
                reply = self._engine.oracle_quote(memories)
            elif utility_command.name == "裁判":
                memories = await asyncio.to_thread(
                    self.repository.memory_messages,
                    message.guild.id,
                    self.config.target_channel_id,
                    limit=self.config.candidate_pool_size,
                )
                reply = self._engine.judge_dispute(
                    utility_command.argument,
                    memories,
                )
            elif utility_command.name == "連想":
                if not utility_command.argument:
                    reply = "例: `連想 猫`"
                else:
                    memories = await asyncio.to_thread(
                        self.repository.memory_messages,
                        message.guild.id,
                        self.config.target_channel_id,
                        limit=self.config.candidate_pool_size,
                    )
                    words = self._engine.associated_words(
                        utility_command.argument,
                        memories,
                    )
                    reply = (
                        f"「{utility_command.argument}」から連想: "
                        + " → ".join(words)
                        if words
                        else "近い学習単語が見つからなかったよ。"
                    )
            else:
                if utility_command.argument != "今日":
                    reply = "現在は `要約 今日` に対応しているよ。"
                else:
                    jst = timezone(timedelta(hours=9))
                    start_of_today = (
                        datetime.now(jst)
                        .replace(hour=0, minute=0, second=0, microsecond=0)
                        .astimezone(timezone.utc)
                        .timestamp()
                    )
                    today_messages = await asyncio.to_thread(
                        self.repository.memory_messages_since,
                        message.guild.id,
                        self.config.target_channel_id,
                        since=start_of_today,
                        limit=self.config.candidate_pool_size,
                    )
                    reply = self._engine.summarize_messages(today_messages)
            async with message.channel.typing():
                if reply_file is None:
                    await message.reply(
                        sanitize_reply(reply),
                        mention_author=False,
                        allowed_mentions=discord.AllowedMentions.none(),
                    )
                else:
                    await message.reply(
                        sanitize_reply(reply),
                        file=reply_file,
                        mention_author=False,
                        allowed_mentions=discord.AllowedMentions.none(),
                    )
            self._last_reply_at[message.channel.id] = now
            return

        memories = await asyncio.to_thread(
            self.repository.memory_messages,
            message.guild.id,
            self.config.target_channel_id,
            limit=self.config.candidate_pool_size,
        )
        generated = self._engine.respond(
            text,
            memories,
        )
        if generated is None:
            reply = random.choice(CONFUSED_FALLBACKS)
        else:
            reply = generated.text

        reply = sanitize_reply(
            apply_cute_tone(
                apply_persona(reply, self.config.persona),
                rate=self.config.cute_tone_rate,
            )
        )
        if not reply:
            return

        async with message.channel.typing():
            await message.reply(
                reply,
                mention_author=False,
                allowed_mentions=discord.AllowedMentions.none(),
            )
        self._last_reply_at[message.channel.id] = now

    async def on_message_edit(
        self,
        before: discord.Message,
        after: discord.Message,
    ) -> None:
        if (
            self.user is None
            or after.guild is None
            or after.guild.id != self.config.target_guild_id
            or after.channel.id != self.config.target_channel_id
            or after.author.bot
        ):
            return
        text = prepare_message(
            after.content,
            bot_user_id=self.user.id,
            max_length=self.config.max_message_length,
        )
        if text is None:
            await asyncio.to_thread(self.repository.delete_message, after.id)
            self._engine.reset_state()
        elif before.content != after.content:
            await asyncio.to_thread(
                self.repository.update_message,
                after.id,
                text,
            )
            self._engine.reset_state()

    async def on_raw_message_delete(
        self, payload: discord.RawMessageDeleteEvent
    ) -> None:
        if payload.channel_id != self.config.target_channel_id:
            return
        await asyncio.to_thread(
            self.repository.delete_message,
            payload.message_id,
        )
        self._engine.reset_state()
