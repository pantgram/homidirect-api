from pydantic import field_validator

from app.schemas.base import CamelModel

VALID_ROLES = {"LANDLORD", "TENANT", "BOTH"}


class SyncProfileRequest(CamelModel):
    first_name: str
    last_name: str
    role: str

    @field_validator("role")
    @classmethod
    def validate_role(cls, v: str) -> str:
        if v not in VALID_ROLES:
            raise ValueError(f"Role must be one of: {', '.join(sorted(VALID_ROLES))}")
        return v
