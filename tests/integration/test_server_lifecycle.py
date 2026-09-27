"""tests/integration/test_server_lifecycle.py"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from octop.cli.repl.embedded_session import embedded_runtime
from octop.config import DatabaseConfig
from octop.infra.db.rebind import persist_database_config
from octop.infra.db.repos.channels import ChannelRepo
from octop.infra.gateway.gateway import Gateway
from octop.infra.server import OctopServer
from tests.support.app import ensure_control_plane_bound


async def _bind_default_sqlite(srv: OctopServer) -> None:
    await ensure_control_plane_bound(srv)


@pytest.fixture
async def server(tmp_octop_home: Path):
    srv = OctopServer(home=tmp_octop_home)
    await srv.start()
    await _bind_default_sqlite(srv)
    yield srv
    await srv.stop()


async def test_start_defers_db_until_bind(tmp_octop_home: Path):
    srv = OctopServer(home=tmp_octop_home)
    await srv.start()
    try:
        assert tmp_octop_home.is_dir()
        assert (tmp_octop_home / "config.json").exists()
        assert not (tmp_octop_home / "octop.db").exists()
        assert srv.database_bound is False
        assert srv.services is None
        await _bind_default_sqlite(srv)
        assert (tmp_octop_home / "octop.db").exists()
        assert srv.database_bound is True
    finally:
        await srv.stop()


async def test_start_creates_root_and_db(server: OctopServer, tmp_octop_home: Path):
    assert tmp_octop_home.is_dir()
    assert (tmp_octop_home / "octop.db").exists()
    assert (tmp_octop_home / "config.json").exists()


async def test_jwt_secret_seeded(server: OctopServer):
    assert server.services is not None
    secret = server.services.secret_repo.get("jwt")
    assert secret is not None
    assert len(secret) >= 32


async def test_user_manager_loaded(server: OctopServer):
    assert server.user_manager is not None
    assert server.user_manager.count() == 0


async def test_boot_then_stop_idempotent(tmp_octop_home: Path):
    srv = OctopServer(home=tmp_octop_home)
    await srv.start()
    await _bind_default_sqlite(srv)
    await srv.stop()
    await srv.stop()  # idempotent


async def test_embedded_cli_skips_im_channels_while_server_starts_them(
    tmp_octop_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_config = DatabaseConfig()
    persist_database_config(tmp_octop_home / "config.json", db_config)
    db_config.resolve_sqlite_path(tmp_octop_home).touch()
    monkeypatch.setenv("OCTOP_HOME", str(tmp_octop_home))
    row = MagicMock(kind="feishu", channel_id="feishu-1")
    monkeypatch.setattr(ChannelRepo, "list_all", lambda self, **kwargs: [row])
    register = AsyncMock()
    monkeypatch.setattr(Gateway, "_safe_register_channel", register)

    async with embedded_runtime() as server:
        assert server.database_bound

    register.assert_not_awaited()

    server = OctopServer(home=tmp_octop_home)
    await server.start()
    try:
        register.assert_awaited_once_with(row)
    finally:
        await server.stop()
