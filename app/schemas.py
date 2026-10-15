"""
Module for requests and responses validations - describes and validates data sent to or returned by the API.
"""

import re
from datetime import datetime
from typing import Literal

from pydantic import (BaseModel, ConfigDict, EmailStr, Field, HttpUrl,
                      JsonValue, TypeAdapter, ValidationError, field_validator,
                      model_validator)

SHA1_HEX = r"^[0-9a-f]{40}$"
SHA256_HEX = r"^[0-9a-f]{64}$"
BOOLEAN_ATTRIBUTES = {"sensitive", "writes", "requires_approval"}
ComponentKind = Literal[
    "model", "framework", "tool", "mcp_server", "vendor", "data_source"
]
Environment = Literal["dev", "staging", "prod"]
_HTTP_URL = TypeAdapter(HttpUrl)


"""User-related request and response models"""


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


"""Scan-related request and response models"""


class ScanInputModel(BaseModel):
    """
    Reject unknown fields and trim strings throughout the scan report.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ScanEvidence(ScanInputModel):
    """
    Evidence for a component, including file path, line range, detector, and optional snippet hash"""

    file_path: str = Field(min_length=1, max_length=1000)
    line_start: int = Field(ge=1)
    line_end: int = Field(ge=1)
    detector: str = Field(min_length=1, max_length=100)
    snippet_sha256: str | None = Field(default=None, pattern=SHA256_HEX)

    @field_validator("file_path")
    @classmethod
    def relative_path(cls, value: str) -> str:
        """
        validate that the file_path is a relative path inside the repository, not an absolute path or a path with parent directory references.
        """
        if (
            value.startswith("/")
            or re.match(r"^[A-Za-z]:", value)
            or "\\" in value
            or ".." in value
        ):
            raise ValueError("file_path must be a relative path inside the repository")
        return value

    @model_validator(mode="after")
    def line_range(self):
        """
        validate that line_end is greater than or equal to line_start."""
        if self.line_end < self.line_start:
            raise ValueError("line_end must be greater than or equal to line_start")
        return self


class ScanComponent(ScanInputModel):
    """
    Component in the scan report, including kind, name, version, attributes, and evidence."""

    kind: ComponentKind
    name: str = Field(min_length=1, max_length=200)
    version: str | None = Field(default=None, min_length=1, max_length=100)
    attributes: dict[str, JsonValue] = Field(default_factory=dict)
    evidence: list[ScanEvidence] = Field(min_length=1, max_length=100)

    @field_validator("attributes")
    @classmethod
    def known_flags_are_booleans(
        cls, value: dict[str, JsonValue]
    ) -> dict[str, JsonValue]:
        """
        validate that known boolean attributes are true or false if present.
        """
        for key in BOOLEAN_ATTRIBUTES & value.keys():
            if not isinstance(value[key], bool):
                raise ValueError(f"attributes.{key} must be true or false")
        return value


class ScanSystem(ScanInputModel):
    """
    System in the scan report, including name, repository URL, environment, and optional owner user ID
    """

    name: str = Field(min_length=1, max_length=200)
    repository_url: str = Field(min_length=1, max_length=500)
    environment: Environment
    owner_user_id: int | None = Field(default=None, gt=0)

    @field_validator("repository_url")
    @classmethod
    def normalize_repository_url(cls, value: str) -> str:
        """
        validate that the repository_url is a valid https URL without query or fragment, and does not
        """
        try:
            url = _HTTP_URL.validate_python(value)
        except ValidationError:
            raise ValueError("repository_url must be a valid URL") from None
        if url.scheme != "https" or url.query or url.fragment:
            raise ValueError(
                "repository_url must be an https URL without query or fragment"
            )
        if url.username is not None or url.password is not None:
            raise ValueError("repository_url must not contain credentials")
        return str(url).rstrip("/").removesuffix(".git")


class ScanReport(ScanInputModel):
    """
    Scan report consists of system details, commit SHA, and a list of components."""

    system: ScanSystem
    commit_sha: str = Field(pattern=SHA1_HEX)
    components: list[ScanComponent] = Field(default_factory=list, max_length=500)

    @model_validator(mode="after")
    def unique_components(self):
        """
        validate that each component in the list is unique based on its kind and name.
        """
        seen = set()
        for component in self.components:
            # create a tuple of (kind, name) to use as a unique key for each component
            key = (component.kind, component.name)
            if key in seen:
                raise ValueError(
                    f"duplicate component: {component.kind} {component.name}"
                )
            seen.add(key)
        return self


"""System-related response models"""


class SystemSummary(BaseModel):
    """Public summary of a single recorded AI system."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    repository_url: str
    environment: Environment
    owner_user_id: int | None
    created_at: datetime


class SystemsPage(BaseModel):
    """System summaries and pagination metadata."""

    items: list[SystemSummary]
    total: int = Field(ge=0)
    limit: int = Field(ge=1, le=100)
    offset: int = Field(ge=0)


class EvidenceResponse(BaseModel):
    """Stored evidence identifying the source location of a component."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    commit_sha: str
    file_path: str
    line_start: int
    line_end: int
    detector: str
    snippet_sha256: str | None


class ComponentResponse(BaseModel):
    """A stored component with its supporting source locations."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    kind: ComponentKind
    name: str
    version: str | None
    attributes: dict[str, JsonValue]
    evidence: list[EvidenceResponse]


class SystemDetail(SystemSummary):
    """System summary extended with components and their evidence."""

    components: list[ComponentResponse]


"""AI BOM models"""


class AIBOMResponse(BaseModel):
    """AI inventory grouped by kind, preserving every component's evidence."""

    system: SystemSummary
    components_by_kind: dict[ComponentKind, list[ComponentResponse]]
