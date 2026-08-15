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
    verify_password,
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

    async def register(self, username: str, password: str) -> tuple[SessionResponse, str]:
        user = User(
            username=username,
            username_normalized=username.casefold(),
            password_hash=await hash_password(password),
        )
        self.database.add(user)
        try:
            await self.database.flush()
        except IntegrityError as error:
            await self.database.rollback()
            raise ApiError(
                status_code=status.HTTP_409_CONFLICT,
                code="USERNAME_TAKEN",
                message="Username is already registered.",
            ) from error

        token = self._add_session(user)
        await self.database.commit()
        return self._session_response(user), token

    async def login(self, username: str, password: str) -> tuple[SessionResponse, str]:
        user = await self.database.scalar(
            select(User).where(User.username_normalized == username.casefold())
        )
        if not await verify_password(password, user.password_hash if user else None):
            raise ApiError(
                status_code=status.HTTP_401_UNAUTHORIZED,
                code="INVALID_CREDENTIALS",
                message="Username or password is invalid.",
            )

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
        return SessionResponse(state=state, user=SessionUser(username=user.username))

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
