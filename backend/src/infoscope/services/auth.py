from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import Depends, status
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from infoscope.config import Settings, get_settings
from infoscope.db import get_session
from infoscope.errors import ApiError
from infoscope.models import User, UserSession
from infoscope.schemas.auth import SessionResponse, SessionState, SessionUser
from infoscope.security import (
    hash_password,
    hash_session_token,
    new_session_token,
)


class AuthService:
    def __init__(self, database: AsyncSession, settings: Settings) -> None:
        self.database = database
        self.settings = settings

    async def get_session(self, token: str | None) -> SessionResponse:
        user = await self._user_for_token(token)
        if user is None:
            return SessionResponse(state=SessionState.ANONYMOUS, user=None)
        return self._session_response(user)

    async def require_user(self, token: str | None) -> User:
        user = await self._user_for_token(token)
        if user is None:
            raise self._auth_required()
        return user

    async def local_access(self, display_name: str) -> tuple[SessionResponse, str]:
        internal_username = self.settings.local_user_username.strip()
        user = await self.database.scalar(
            select(User)
            .where(User.username_normalized == internal_username.casefold())
            .with_for_update()
        )
        if user is None:
            user = User(
                username=internal_username,
                username_normalized=internal_username.casefold(),
                display_name=display_name,
                password_hash=await hash_password(new_session_token()),
            )
            self.database.add(user)
            try:
                await self.database.flush()
            except IntegrityError as error:
                await self.database.rollback()
                raise ApiError(
                    status_code=status.HTTP_409_CONFLICT,
                    code="LOCAL_USER_CONFLICT",
                    message="The local user could not be created.",
                ) from error
        else:
            user.display_name = display_name

        token = self._add_session(user)
        await self.database.commit()
        return self._session_response(user), token

    async def logout(self, token: str | None) -> None:
        if token is None:
            raise self._auth_required()

        result = await self.database.execute(
            delete(UserSession).where(UserSession.token_hash == hash_session_token(token))
        )
        if result.rowcount == 0:
            await self.database.rollback()
            raise self._auth_required()
        await self.database.commit()

    async def _user_for_token(self, token: str | None) -> User | None:
        if token is None:
            return None

        session = await self.database.scalar(
            select(UserSession)
            .options(joinedload(UserSession.user))
            .where(
                UserSession.token_hash == hash_session_token(token),
                UserSession.expires_at > datetime.now(UTC),
            )
        )
        return session.user if session else None

    def _add_session(self, user: User) -> str:
        token = new_session_token()
        self.database.add(
            UserSession(
                user=user,
                token_hash=hash_session_token(token),
                expires_at=datetime.now(UTC) + timedelta(seconds=self.settings.session_ttl_seconds),
            )
        )
        return token

    @staticmethod
    def _session_response(user: User) -> SessionResponse:
        state = (
            SessionState.READY if user.onboarding_completed else SessionState.ONBOARDING_REQUIRED
        )
        return SessionResponse(
            state=state,
            user=SessionUser(display_name=user.display_name or user.username),
        )

    @staticmethod
    def _auth_required() -> ApiError:
        return ApiError(
            status_code=status.HTTP_401_UNAUTHORIZED,
            code="AUTH_REQUIRED",
            message="A valid session is required.",
        )


def get_auth_service(
    database: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> AuthService:
    return AuthService(database, settings)
