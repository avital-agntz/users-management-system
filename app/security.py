"""
Hash passwords for storage and verify them during login.
"""

import os
from pathlib import Path

import bcrypt
import jwt
from dotenv import load_dotenv

# JWT tokenization
env_path = Path(__file__).resolve().parent / ".env"
load_dotenv(env_path)

JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY")
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")

if not JWT_SECRET_KEY:
    raise RuntimeError("JWT_SECRET_KEY is missing from configuration.")


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
    # subject is the user id
    payload = {"sub": str(user_id)}

    return jwt.encode(
        payload,
        JWT_SECRET_KEY,
        algorithm=JWT_ALGORITHM,
    )
