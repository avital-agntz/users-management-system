"""
Provide password hashing, password verification, and JWT creation and validation.
"""

from fastapi import HTTPException, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import InvalidTokenError

from app.security import verify_access_token

bearer_scheme = HTTPBearer(auto_error=False)


def get_current_user_id(
    credentials: HTTPAuthorizationCredentials | None = Security(bearer_scheme),
) -> int:
    """
    Dependency to get the current user ID from the access token.
    Raises an HTTPException if the token is missing or invalid."""
    if credentials is None:
        raise HTTPException(
            status_code=401,
            detail="Missing or invalid authentication credentials.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        return verify_access_token(credentials.credentials)
    except InvalidTokenError:
        raise HTTPException(
            status_code=401,
            detail="Missing or invalid authentication credentials.",
            headers={"WWW-Authenticate": "Bearer"},
        ) from None
