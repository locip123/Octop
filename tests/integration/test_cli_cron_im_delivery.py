"""CLI cron delivery to an IM session starts only its target channel."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from octop.cli.support.db import open_cli_services
from octop.cli.support.embedded_ops import cron_run_now_async
from octop.config import DatabaseConfig
from octop.infra.db.rebind import persist_database_config
from octop.infra.db.repos.channels import ChannelRow
from octop.infra.gateway.gateway import Gateway
from octop.infra.gateway.threads import ThreadRegistry


async def test_cron_run_now_registers_only_target_im_channel(
    tmp_octop_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    persist_database_config(tmp_octop_home / "config.json", DatabaseConfig())
    monkeypatch.setenv("OCTOP_HOME", str(tmp_octop_home))
    session_key = ThreadRegistry.make_key(
        agent_id="agent-1", channel_type="feishu", channel_subject_id="user-1"
    )
    with open_cli_services(home=tmp_octop_home) as services:
        user_id = services.user_repo.create(username="owner", role="user")
        services.agent_repo.create(agent_id="agent-1", user_id=user_id, name="agent")
        services.channel_repo.create(
            channel_id="feishu-1",
            agent_id="agent-1",
            user_id=user_id,
            kind="feishu",
            name="main",
            config_json='{"app_id":"x","app_secret":"y"}',
        )
        services.channel_repo.create(
            channel_id="feishu-2",
            agent_id="agent-1",
            user_id=user_id,
            kind="feishu",
            name="other",
            config_json='{"app_id":"x","app_secret":"y"}',
        )
        services.thread_repo.insert(
            thread_id="thread-1",
            agent_id="agent-1",
            user_id=user_id,
            channel_type="feishu",
            session_key=session_key,
        )
        services.session_repo.upsert(
            session_key=session_key,
            agent_id="agent-1",
            user_id=user_id,
            channel_type="feishu",
            chat_type="dm",
            thread_id="thread-1",
            channel_id="feishu-1",
        )
        services.cron_repo.create(
            cron_id="cron-1",
            agent_id="agent-1",
            user_id=user_id,
            trigger="interval:3600",
            prompt="hello",
            session_key=session_key,
            task_type="text",
        )

    registered: list[str] = []
    pushed = AsyncMock()

    async def register(gateway: Gateway, row: ChannelRow) -> None:
        registered.append(row.channel_id)
        channel = MagicMock()
        channel.constraints.show_thinking = False
        channel.push_text = pushed
        channel.stop = AsyncMock()
        assert gateway.channel_manager is not None
        gateway.channel_manager._channels[row.channel_id] = channel

    monkeypatch.setattr(Gateway, "_safe_register_channel", register)

    await cron_run_now_async("agent-1", "cron-1")

    assert registered == ["feishu-1"]
    pushed.assert_awaited_once()
    with open_cli_services(home=tmp_octop_home) as services:
        row = services.cron_repo.get("cron-1")
        assert row is not None
        assert row.last_status == "ok"
