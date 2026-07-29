from __future__ import annotations

import asyncio
from collections.abc import Callable

import discord
from discord import app_commands

from .database import MemoryRepository
from .proper_nouns import normalize_proper_noun


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


def build_dictionary_group(
    repository: MemoryRepository,
    add_to_cache: Callable[[str], None],
    remove_from_cache: Callable[[str], None],
    *,
    target_guild_id: int,
) -> app_commands.Group:
    group = app_commands.Group(
        name="dictionary",
        description="固有名詞辞書を管理します",
    )

    async def require_guild(interaction: discord.Interaction) -> bool:
        if interaction.guild_id == target_guild_id:
            return True
        await interaction.response.send_message(
            "このBotの対象サーバーではありません。",
            ephemeral=True,
        )
        return False

    @group.command(
        name="add",
        description="固有名詞を登録し、分割や部分置換を防ぎます",
    )
    @app_commands.describe(term="登録する固有名詞（例: 揖保乃糸）")
    @app_commands.guild_only()
    @app_commands.check(require_guild)
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.checks.has_permissions(manage_guild=True)
    async def add(interaction: discord.Interaction, term: str) -> None:
        assert interaction.guild_id is not None
        try:
            normalized = normalize_proper_noun(term)
        except ValueError as error:
            await interaction.response.send_message(
                str(error),
                ephemeral=True,
            )
            return
        inserted = await asyncio.to_thread(
            repository.add_proper_noun,
            interaction.guild_id,
            normalized,
        )
        add_to_cache(normalized)
        message = (
            f"固有名詞「{normalized}」を登録しました。"
            if inserted
            else f"固有名詞「{normalized}」は登録済みです。"
        )
        await interaction.response.send_message(message, ephemeral=True)

    @group.command(
        name="remove",
        description="固有名詞辞書から削除します",
    )
    @app_commands.describe(term="削除する固有名詞")
    @app_commands.guild_only()
    @app_commands.check(require_guild)
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.checks.has_permissions(manage_guild=True)
    async def remove(interaction: discord.Interaction, term: str) -> None:
        assert interaction.guild_id is not None
        try:
            normalized = normalize_proper_noun(term)
        except ValueError as error:
            await interaction.response.send_message(
                str(error),
                ephemeral=True,
            )
            return
        removed = await asyncio.to_thread(
            repository.remove_proper_noun,
            interaction.guild_id,
            normalized,
        )
        remove_from_cache(normalized)
        message = (
            f"固有名詞「{normalized}」を削除しました。"
            if removed
            else f"固有名詞「{normalized}」は登録されていません。"
        )
        await interaction.response.send_message(message, ephemeral=True)

    @group.command(
        name="list",
        description="登録済みの固有名詞を表示します",
    )
    @app_commands.guild_only()
    @app_commands.check(require_guild)
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.checks.has_permissions(manage_guild=True)
    async def list_terms(interaction: discord.Interaction) -> None:
        assert interaction.guild_id is not None
        terms = await asyncio.to_thread(
            repository.proper_nouns,
            interaction.guild_id,
        )
        if not terms:
            message = "登録済みの固有名詞はありません。"
        else:
            lines = [f"登録済み固有名詞: {len(terms)}件"]
            for term in terms:
                line = f"・{term}"
                if len("\n".join((*lines, line))) > 1_800:
                    lines.append("・…（残りは省略）")
                    break
                lines.append(line)
            message = "\n".join(lines)
        await interaction.response.send_message(message, ephemeral=True)

    return group
