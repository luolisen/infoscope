from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from telethon import types

from infoscope.integrations.telegram.client import (
    TelegramNewsClient,
    _dialog_matches,
    _filter_title,
)
from infoscope.integrations.telegram.models import TelegramConfig


def _dialog(*, peer_id: int, group: bool, channel: bool, archived: bool = False):
    return SimpleNamespace(
        id=peer_id,
        is_group=group,
        is_channel=channel,
        archived=archived,
        unread_count=1,
        entity=SimpleNamespace(left=False),
        dialog=SimpleNamespace(notify_settings=SimpleNamespace(mute_until=None)),
    )


def test_folder_title_is_read_from_text_with_entities() -> None:
    folder = types.DialogFilter(
        id=2,
        title=types.TextWithEntities("News", []),
        pinned_peers=[],
        include_peers=[],
        exclude_peers=[],
    )

    assert _filter_title(folder) == "News"


def test_folder_matches_groups_and_broadcasts_but_not_direct_users() -> None:
    folder = types.DialogFilter(
        id=2,
        title=types.TextWithEntities("News", []),
        pinned_peers=[],
        include_peers=[],
        exclude_peers=[],
        groups=True,
        broadcasts=True,
    )

    assert _dialog_matches(_dialog(peer_id=-10, group=True, channel=True), folder)
    assert _dialog_matches(_dialog(peer_id=-20, group=False, channel=True), folder)
    assert not _dialog_matches(_dialog(peer_id=30, group=False, channel=False), folder)


def test_explicit_folder_peer_is_included_and_exclusion_wins() -> None:
    included = types.InputPeerChannel(channel_id=10, access_hash=1)
    peer_id = -1000000000010
    folder = types.DialogFilter(
        id=2,
        title=types.TextWithEntities("News", []),
        pinned_peers=[],
        include_peers=[included],
        exclude_peers=[],
    )
    dialog = _dialog(peer_id=peer_id, group=False, channel=True)

    assert _dialog_matches(dialog, folder)

    excluded_folder = types.DialogFilter(
        id=2,
        title=types.TextWithEntities("News", []),
        pinned_peers=[],
        include_peers=[included],
        exclude_peers=[included],
    )
    assert not _dialog_matches(dialog, excluded_folder)


async def test_login_uses_telethon_interactive_phone_prompt_when_phone_is_unset(tmp_path) -> None:
    transport = SimpleNamespace(start=AsyncMock(), disconnect=AsyncMock())
    config = TelegramConfig(12345, "secret", None, tmp_path / "session", "News", 100)

    with patch("infoscope.integrations.telegram.client.TelegramClient", return_value=transport):
        client = TelegramNewsClient(config)
        await client.login()

    transport.start.assert_awaited_once_with()
    transport.disconnect.assert_awaited_once_with()
