from __future__ import annotations

import asyncio
from collections.abc import Callable

import discord
from discord import app_commands

from .database import MemoryRepository


def build_memory_group(
    repository: MemoryRepository,
    reset_memory_state: Callable[[], None],
    *,
    target_guild_id: int,
    target_channel_id: int,
) -> app_commands.Group:
    group = app_commands.Group(
        name="memory",
        description="このBotの会話学習を管理します",
    )

    async def require_target(interaction: discord.Interaction) -> bool:
        if (
            interaction.guild_id == target_guild_id
            and interaction.channel_id == target_channel_id
        ):
            return True
        await interaction.response.send_message(
            f"このBotの対象は <#{target_channel_id}> だけです。",
            ephemeral=True,
        )
        return False

    @group.command(name="status", description="このチャンネルの学習状態を表示します")
    @app_commands.guild_only()
    @app_commands.check(require_target)
    async def status(interaction: discord.Interaction) -> None:
        assert interaction.guild_id is not None
        assert interaction.channel_id is not None
        stats = await asyncio.to_thread(
            repository.stats,
            interaction.guild_id,
            interaction.channel_id,
        )
        await interaction.response.send_message(
            f"対象チャンネル: はい\n記憶した発言: {stats.messages}件",
            ephemeral=True,
        )

    @group.command(name="forget-me", description="このサーバーで自分の発言を忘れさせます")
    @app_commands.guild_only()
    @app_commands.check(require_target)
    async def forget_me(interaction: discord.Interaction) -> None:
        assert interaction.guild_id is not None
        deleted = await asyncio.to_thread(
            repository.forget_user,
            interaction.guild_id,
            interaction.user.id,
        )
        reset_memory_state()
        await interaction.response.send_message(
            f"あなたの学習済み発言を{deleted}件削除しました。",
            ephemeral=True,
        )

    @group.command(
        name="purge",
        description="このチャンネルで覚えた内容をすべて削除します",
    )
    @app_commands.guild_only()
    @app_commands.check(require_target)
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.checks.has_permissions(manage_guild=True)
    async def purge(interaction: discord.Interaction) -> None:
        assert interaction.guild_id is not None
        assert interaction.channel_id is not None
        deleted = await asyncio.to_thread(
            repository.purge_channel,
            interaction.guild_id,
            interaction.channel_id,
        )
        reset_memory_state()
        await interaction.response.send_message(
            f"このチャンネルの学習済み発言を{deleted}件削除しました。",
            ephemeral=True,
        )

    return group
