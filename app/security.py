"""
Provide FastAPI authentication dependencies that validate Bearer tokens and return user IDs.
"""

from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

from app.core.config import get_settings

settings = get_settings()


def hash_password(password: str) -> str:
    """
    Recieves a string password and converts the password to hashed bytes.
    """
    password_bytes = password.encode("utf-8")
    # rejects passwords exceeding bcrypt’s input limit.
    if len(password_bytes) > 72:
        raise ValueError("Password must not exceed 72 UTF-8 bytes.")

    salt = bcrypt.gensalt()
    hashed_bytes = bcrypt.hashpw(password_bytes, salt)
    str_hashed = hashed_bytes.decode("utf-8")
    return str_hashed


def verify_password(password: str, password_hash: str) -> bool:
    """
    Checks an entered password against the stored hash
    """
    password_bytes = password.encode("utf-8")
    if len(password_bytes) > 72:
        return False

    return bcrypt.checkpw(password_bytes, password_hash.encode("utf-8"))


def create_access_token(user_id: int) -> str:
    """
    Creates access tocken for user uppon login
    """
    expires_at = datetime.now(timezone.utc) + timedelta(
        minutes=settings.jwt_expire_minutes
    )
    # subject is the user id and token expiration time
    payload = {
        "sub": str(user_id),
        "exp": expires_at,
    }

    return jwt.encode(
        payload,
        settings.jwt_secret_key.get_secret_value(),
        algorithm=settings.jwt_algorithm,
    )


def verify_access_token(token: str) -> int:
    """
    Verifies the access token and returns the user ID if valid.
    """
    # Decode the token and validate its structure
    payload = jwt.decode(
        token,
        settings.jwt_secret_key.get_secret_value(),
        algorithms=[settings.jwt_algorithm],
        options={"require": ["sub", "exp"]},
    )

    # Extract the subject (user ID) from the payload
    subject = payload["sub"]

    # Validate that the subject is a valid user ID (positive integer)
    if not isinstance(subject, str) or not subject.isdecimal():
        raise jwt.InvalidTokenError("Invalid user ID in token.")

    user_id = int(subject)

    # Else = invalid
    if user_id <= 0:
        raise jwt.InvalidTokenError("Invalid user ID in token.")

    return user_id
