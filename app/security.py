"""
Hash passwords for storage and verify them during login.
"""

import bcrypt


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
