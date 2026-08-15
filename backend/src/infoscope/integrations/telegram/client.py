from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

from telethon import TelegramClient, functions, types, utils
from telethon.errors import RPCError

from infoscope.integrations.telegram.models import (
    TelegramConfig,
    TelegramDialog,
    TelegramMessage,
)


class TelegramSourceError(Exception):
    def __init__(self, error_code: str) -> None:
        super().__init__(error_code)
        self.error_code = error_code


def _filter_title(value: Any) -> str | None:
    title = getattr(value, "title", None)
    text = getattr(title, "text", None)
    return text if isinstance(text, str) else None


def _peer_ids(values: list[Any]) -> set[int]:
    return {utils.get_peer_id(value) for value in values}


def _is_muted(dialog: Any, *, now: datetime) -> bool:
    settings = getattr(dialog.dialog, "notify_settings", None)
    mute_until = getattr(settings, "mute_until", None)
    if isinstance(mute_until, datetime):
        if mute_until.tzinfo is None:
            mute_until = mute_until.replace(tzinfo=UTC)
        return mute_until > now
    return bool(mute_until)


def _dialog_matches(dialog: Any, folder: types.DialogFilter | types.DialogFilterChatlist) -> bool:
    peer_id = dialog.id
    excluded = _peer_ids(getattr(folder, "exclude_peers", []))
    if peer_id in excluded:
        return False

    explicit = _peer_ids([*folder.pinned_peers, *folder.include_peers])
    if peer_id in explicit:
        return dialog.is_group or (dialog.is_channel and not dialog.is_group)

    if isinstance(folder, types.DialogFilterChatlist):
        return False

    entity = dialog.entity
    is_broadcast = dialog.is_channel and not dialog.is_group
    included_by_type = (dialog.is_group and bool(folder.groups)) or (
        is_broadcast and bool(folder.broadcasts)
    )
    if not included_by_type:
        return False
    if folder.exclude_archived and dialog.archived:
        return False
    if folder.exclude_read and dialog.unread_count == 0:
        return False
    if folder.exclude_muted and _is_muted(dialog, now=datetime.now(UTC)):
        return False
    return not bool(getattr(entity, "left", False))


class TelegramNewsClient:
    def __init__(self, config: TelegramConfig) -> None:
        self.config = config
        config.session_path.parent.mkdir(parents=True, exist_ok=True)
        self.client = TelegramClient(str(config.session_path), config.api_id, config.api_hash)

    async def login(self) -> None:
        if self.config.phone is None:
            await self.client.start()
        else:
            await self.client.start(phone=self.config.phone)
        await self.client.disconnect()

    async def connect(self) -> None:
        try:
            await self.client.connect()
            if not await self.client.is_user_authorized():
                raise TelegramSourceError("TGNEWS_SESSION_UNAUTHORIZED")
        except TelegramSourceError:
            await self.client.disconnect()
            raise
        except (OSError, RPCError) as error:
            await self.client.disconnect()
            raise TelegramSourceError("TGNEWS_CONNECT_FAILED") from error

    async def disconnect(self) -> None:
        await self.client.disconnect()

    async def folder_dialogs(self) -> list[TelegramDialog]:
        try:
            response = await self.client(functions.messages.GetDialogFiltersRequest())
            matches = [
                item
                for item in response.filters
                if _filter_title(item) == self.config.folder_title
            ]
            if not matches:
                raise TelegramSourceError("TGNEWS_FOLDER_NOT_FOUND")
            if len(matches) > 1:
                raise TelegramSourceError("TGNEWS_FOLDER_AMBIGUOUS")
            folder = matches[0]
            if not isinstance(folder, (types.DialogFilter, types.DialogFilterChatlist)):
                raise TelegramSourceError("TGNEWS_FOLDER_UNSUPPORTED")

            dialogs: list[TelegramDialog] = []
            async for dialog in self.client.iter_dialogs(limit=None, ignore_migrated=True):
                if not _dialog_matches(dialog, folder):
                    continue
                username = getattr(dialog.entity, "username", None)
                dialogs.append(
                    TelegramDialog(
                        peer_id=dialog.id,
                        title=dialog.title,
                        username=username if isinstance(username, str) and username else None,
                        input_entity=dialog.input_entity,
                    )
                )
            return dialogs
        except TelegramSourceError:
            raise
        except (OSError, RPCError) as error:
            raise TelegramSourceError("TGNEWS_FOLDER_REQUEST_FAILED") from error

    async def iter_messages(
        self,
        dialog: TelegramDialog,
        *,
        after_message_id: int | None,
    ) -> AsyncIterator[TelegramMessage]:
        try:
            if after_message_id is None:
                recent = [
                    message
                    async for message in self.client.iter_messages(
                        dialog.input_entity,
                        limit=self.config.initial_message_limit,
                    )
                ]
                for message in reversed(recent):
                    converted = _message_value(message)
                    if converted is not None:
                        yield converted
            else:
                async for message in self.client.iter_messages(
                    dialog.input_entity,
                    limit=None,
                    min_id=after_message_id,
                    reverse=True,
                ):
                    converted = _message_value(message)
                    if converted is not None:
                        yield converted
        except (OSError, RPCError) as error:
            raise TelegramSourceError("TGNEWS_DIALOG_REQUEST_FAILED") from error


def _message_value(message: Any) -> TelegramMessage | None:
    text = (message.raw_text or "").strip()
    if not text or message.date is None:
        return None
    media = type(message.media).__name__ if message.media is not None else None
    return TelegramMessage(
        id=message.id,
        text=text,
        published_at=message.date,
        edited_at=message.edit_date,
        sender_id=message.sender_id,
        reply_to_message_id=message.reply_to_msg_id,
        grouped_id=message.grouped_id,
        media_type=media,
        views=message.views,
        forwards=message.forwards,
    )
