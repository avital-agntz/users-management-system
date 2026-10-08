"""
Module for requests validations - describes and validates data sent to or returned by the API.
"""

from pydantic import BaseModel, EmailStr, Field, field_validator


class RegisterRequest(BaseModel):
    first_name: str = Field(min_length=1, max_length=50)
    last_name: str = Field(min_length=1, max_length=50)
    email: EmailStr
    password: str = Field(min_length=8)

    @field_validator("first_name", "last_name", mode="before")
    @classmethod
    def trim_names(cls, value):
        if isinstance(value, str):
            return value.strip()
        return value


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)
