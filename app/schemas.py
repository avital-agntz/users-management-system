"""
Module for requests validations - describes and validates data sent to or returned by the API.
"""

from pydantic import (BaseModel, ConfigDict, EmailStr, Field, field_validator,
                      model_validator)


class RegisterRequest(BaseModel):
    """
    Register request consists of first name, last name, email and password, all required.
    """

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
    """
    Login request consists of email and password, both required
    """

    email: EmailStr
    password: str = Field(min_length=8)


class UpdateRequest(BaseModel):
    """
    Update request consists of first name, last name, and email, all optional.
    At least one field must be provided for update.
    """

    # Model configuration to forbid extra fields
    model_config = ConfigDict(extra="forbid")

    first_name: str | None = Field(default=None, min_length=1, max_length=50)
    last_name: str | None = Field(default=None, min_length=1, max_length=50)
    email: EmailStr | None = None

    # removes surrounding spaces before checking the name’s length.
    @field_validator("first_name", "last_name", mode="before")
    @classmethod
    def trim_names(cls, value):
        if isinstance(value, str):
            return value.strip()
        return value

    @model_validator(mode="after")
    def check_changes(self):
        # at least one field is provided for update
        if not self.model_fields_set:
            raise ValueError("Provide at least one field to update.")

        # no field is null
        for field in self.model_fields_set:
            if getattr(self, field) is None:
                raise ValueError(f"{field} cannot be null.")

        return self


class UserResponse(BaseModel):
    """
    User response model for returning user profile information.
    It includes id, first name, last name, and email.
    """

    model_config = ConfigDict(extra="forbid")

    id: int = Field(gt=0)
    first_name: str = Field(min_length=1, max_length=50)
    last_name: str = Field(min_length=1, max_length=50)
    email: EmailStr
