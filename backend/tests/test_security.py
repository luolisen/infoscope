from infoscope.security import (
    hash_password,
    hash_session_token,
    new_session_token,
    verify_password,
)


async def test_passwords_are_hashed_and_verified_with_argon2() -> None:
    encoded = await hash_password("correct-horse")

    assert encoded.startswith("$argon2")
    assert "correct-horse" not in encoded
    assert await verify_password("correct-horse", encoded) is True
    assert await verify_password("wrong-password", encoded) is False
    assert await verify_password("wrong-password", None) is False


def test_session_tokens_are_opaque_and_only_the_digest_is_persisted() -> None:
    token = new_session_token()
    digest = hash_session_token(token)

    assert len(token) >= 40
    assert len(digest) == 64
    assert token not in digest
    assert digest == hash_session_token(token)
